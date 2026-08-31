package com.prippi.stream

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

enum class AppPage { HOME, SEARCH, CHANNELS, LIVE, DOWNLOADS, BROWSE, SETTINGS, DETAIL }

data class AppUiState(
    val page: AppPage = AppPage.HOME,
    val returnPage: AppPage = AppPage.HOME,
    val homeRows: List<HomeRow> = emptyList(),
    val liveRows: List<HomeRow> = emptyList(),
    val results: List<ContentItem> = emptyList(),
    val channels: List<ChannelInfo> = emptyList(),
    val browseMacros: List<ContentItem> = emptyList(),
    val browseItems: List<ContentItem> = emptyList(),
    val browseSelectedFilterKey: String = "",
    val browseStack: List<BrowseLevel> = emptyList(),
    val browseRootPage: AppPage = AppPage.CHANNELS,
    val settings: List<SettingCategory> = emptyList(),
    val settingsChannel: String = "",
    val downloads: List<DownloadEntry> = emptyList(),
    val selectedItem: ContentItem? = null,
    val selectedProgressItem: ContentItem? = null,
    val detailOverview: String = "",
    val episodes: List<ContentItem> = emptyList(),
    val selectedSeason: Int = 0,
    val pageTitle: String = "PrippiStream",
    val returnTitle: String = "PrippiStream",
    val query: String = "",
    val searchChannel: String = "__global__",
    val searchFilter: String = "all",
    val searchHistory: List<String> = emptyList(),
    val loading: Boolean = false,
    val error: String? = null,
)

class MainViewModel(
    private val repository: ContentRepository,
    private val progressStore: WatchProgressStore,
    private val homeSnapshotStore: HomeSnapshotStore,
    initialHomeRows: List<HomeRow> = emptyList(),
    private val lowPowerDevice: Boolean = false,
) : ViewModel() {
    private val trailerPreviewMutex = Mutex()
    var state by mutableStateOf(
        AppUiState(
            homeRows = withContinueWatching(initialHomeRows),
            loading = initialHomeRows.isEmpty(),
        ),
    )
        private set
    private var homeRefreshJob: Job? = null
    private var liveRefreshJob: Job? = null
    private var liveFocusUnlockJob: Job? = null
    private var foregroundTaskJob: Job? = null
    private var foregroundTaskGeneration = 0L
    private var uiPaused = false
    private var liveFocusLocked = false
    private var pendingLiveRows: List<HomeRow>? = null
    private var engineReady = false
    private val engineReadySignal = CompletableDeferred<Unit>()

    private fun rowsStructureSignature(rows: List<HomeRow>): String =
        rows.joinToString("|") { row ->
            row.id + ":" + row.items.joinToString(",") { it.stableKey }
        }

    private fun rowsContentSignature(rows: List<HomeRow>): String =
        rows.joinToString("|") { row ->
            buildString {
                append(row.id)
                row.items.forEach { item ->
                    append(':').append(item.stableKey)
                    append(':').append(item.title.hashCode())
                    append(':').append(item.plot.hashCode())
                    append(':').append(item.posterUrl.hashCode())
                }
            }
        }

    fun onEngineReady() {
        if (engineReady) return
        val pendingUserAction = foregroundTaskJob?.isActive == true
        engineReady = true
        engineReadySignal.complete(Unit)
        viewModelScope.launch {
            // Il registry/redirect SC va validato prima del primo caricamento
            // remoto della Home: cosi' anche i CW ricostruiti dal motore usano
            // subito il dominio corrente. Il timeout breve conserva lo
            // snapshot gia' visibile se la rete e' lenta o irraggiungibile.
            val refresh = withTimeoutOrNull(if (lowPowerDevice) 10_000 else 7_000) {
                runCatching {
                    withContext(Dispatchers.IO) { repository.refreshScDomain() }
                }
            }
            refresh?.onFailure {
                android.util.Log.e("Prippi", "Aggiornamento dominio SC", it)
            }?.getOrNull()?.optString("host")?.takeIf { it.isNotBlank() }?.let { host ->
                // I CW Android sono locali e contengono ancora l'URL completo
                // salvato durante la visione: riallineali prima di renderizzare
                // la riga, mantenendo invariati chiave, posizione e durata.
                runCatching { progressStore.rewriteDomain("streamingcommunity", host) }
                    .onFailure { android.util.Log.e("Prippi", "Aggiornamento URL CW", it) }
            } ?: AppDiagnostics.event("sc_domain_refresh_timeout")
            if (!pendingUserAction) loadHome()
            // Le righe Live vengono aggiornate dopo Home, con la pipeline
            // gia' esistente e senza staccare il focus dell'utente.
            preloadLiveAtStartup()
        }
    }

    private fun preloadLiveAtStartup() {
        if (liveRefreshJob?.isActive == true) return
        liveRefreshJob = viewModelScope.launch {
            // Parte prima della Home e continua finche' tutte le tre righe Live
            // sono state raccolte. L'ingresso nella pagina non avvia altri probe.
            repeat(60) {
                while (uiPaused || state.page !in setOf(AppPage.HOME, AppPage.LIVE)) {
                    // Metadata, ricerca, browse e player sono azioni esplicite:
                    // sui dispositivi lenti hanno sempre precedenza sui probe Live.
                    delay(1_000)
                }
                val rows = runCatching {
                    withContext(Dispatchers.IO) { repository.liveRows() }
                }.getOrDefault(emptyList())
                if (rows.isNotEmpty()) {
                    val focusedLiveVisible = state.page == AppPage.LIVE && liveFocusLocked
                    val structureChanged =
                        rowsStructureSignature(rows) != rowsStructureSignature(state.liveRows)
                    val contentChanged =
                        rowsContentSignature(rows) != rowsContentSignature(state.liveRows)
                    // Mentre il D-pad si muove non sostituiamo la struttura della
                    // lista (è ciò che può staccare il nodo focalizzato). Un update
                    // solo EPG/logo, con le stesse chiavi, è invece sicuro e deve
                    // arrivare subito: altrimenti la guida scaricata resta invisibile.
                    if (contentChanged && (uiPaused || (focusedLiveVisible && structureChanged))) {
                        pendingLiveRows = rows
                    } else if (contentChanged) {
                        state = state.copy(liveRows = rows)
                        pendingLiveRows = null
                        AppDiagnostics.event(
                            "live_rows rows=${rows.size} items=${rows.sumOf { it.items.size }}",
                        )
                    }
                }
                if (rows.map { it.id }.containsAll(listOf("live_sky", "live_sport", "live_tv"))) {
                    return@launch
                }
                delay(5_000)
            }
            // Non blocca per sempre l'app se una sorgente esterna resta appesa.
        }
    }

    fun setQuery(value: String) { state = state.copy(query = value) }

    fun loadHome() = runTask {
        val (rows, history) = withContext(Dispatchers.IO) {
            val freshRows = repository.loadHome()
            homeSnapshotStore.save(freshRows)
            freshRows to repository.searchHistory()
        }
        state = state.copy(
            page = AppPage.HOME,
            returnPage = AppPage.HOME,
            homeRows = withContinueWatching(rows),
            results = emptyList(),
            selectedItem = null,
            detailOverview = "",
            episodes = emptyList(),
            searchChannel = "__global__",
            searchFilter = "all",
            searchHistory = history,
            pageTitle = "PrippiStream",
            returnTitle = "PrippiStream",
        )
        AppDiagnostics.event(
            "home_loaded rows=${rows.size} items=${rows.sumOf { it.items.size }}",
        )
        scheduleProgressiveHomeRefresh()
    }

    private fun scheduleProgressiveHomeRefresh() {
        homeRefreshJob?.cancel()
        homeRefreshJob = viewModelScope.launch {
            // L'addon compone la Home in due fasi: raccogli archivio e Anime
            // mentre l'utente puo' gia' usare gli slider principali.
            // Il backend low-power lavora con un pool ridotto ma completa
            // comunque tutte le righe. Continuiamo a raccogliere lo snapshot
            // progressivo finché quel lavoro serializzato può terminare.
            repeat(if (lowPowerDevice) 24 else 8) {
                delay(if (lowPowerDevice) 5_000 else 2_500)
                if (uiPaused || state.page != AppPage.HOME) return@launch
                val rows = runCatching {
                    withContext(Dispatchers.IO) { repository.loadHome() }
                }.getOrDefault(emptyList())
                if (rows.isNotEmpty() && state.page == AppPage.HOME) {
                    withContext(Dispatchers.IO) {
                        homeSnapshotStore.save(rows)
                    }
                    val nextRows = withContinueWatching(rows)
                    if (rowsContentSignature(nextRows) != rowsContentSignature(state.homeRows)) {
                        state = state.copy(homeRows = nextRows)
                        AppDiagnostics.event(
                            "home_progressive rows=${rows.size} items=${rows.sumOf { it.items.size }}",
                        )
                    }
                }
            }
        }
    }

    fun refreshContinueWatching() {
        val baseRows = state.homeRows.filterNot { it.id == CONTINUE_ROW_ID }
        state = state.copy(homeRows = withContinueWatching(baseRows))
        state.selectedItem?.let { selected ->
            val saved = progressStore.find(selected)
            state = state.copy(
                selectedItem = selected.withProgress(
                    saved?.positionMs ?: 0,
                    saved?.durationMs ?: 0,
                ),
                selectedProgressItem = saved?.contentItem(),
            )
        }
    }

    fun search() {
        val query = state.query.trim()
        if (query.isEmpty()) return
        runTask {
            val channel = state.searchChannel
            val (items, history) = withContext(Dispatchers.IO) {
                repository.search(query, channel) to repository.saveSearch(query)
            }
            val sourcePage = if (state.page == AppPage.SEARCH) state.returnPage else AppPage.HOME
            state = state.copy(
                page = AppPage.SEARCH,
                returnPage = sourcePage,
                results = applyStoredProgress(items),
                searchFilter = "all",
                searchHistory = history,
                selectedItem = null,
                pageTitle = "Risultati per “$query”",
                returnTitle = if (sourcePage == AppPage.HOME) "PrippiStream" else state.returnTitle,
            )
        }
    }

    fun selectSearchFilter(value: String) {
        state = state.copy(searchFilter = value)
    }

    fun searchFromHistory(query: String) {
        state = state.copy(query = query)
        search()
    }

    fun clearSearchHistory() = runTask {
        withContext(Dispatchers.IO) { repository.clearSearchHistory() }
        state = state.copy(searchHistory = emptyList())
    }

    fun showChannels() = runTask {
        val macros = withContext(Dispatchers.IO) { repository.browseMacros() }
        state = state.copy(
            page = AppPage.CHANNELS,
            channels = emptyList(),
            browseMacros = macros,
            browseItems = emptyList(),
            browseSelectedFilterKey = "",
            browseStack = emptyList(),
            selectedItem = null,
            pageTitle = "Canali",
        )
    }

    /** Superficie Sfoglia TV: apre subito Film/Tutti con poster e conserva i
     * macro e i generi come filtri, senza mostrare livelli intermedi vuoti. */
    fun showBrowseCatalog() {
        state = state.copy(
            page = AppPage.BROWSE,
            browseRootPage = AppPage.CHANNELS,
            browseItems = emptyList(),
            browseSelectedFilterKey = "",
            browseStack = emptyList(),
            selectedItem = null,
            pageTitle = "Sfoglia",
            error = null,
        )
        runTask {
            val macros = withContext(Dispatchers.IO) { repository.browseMacros() }
            val initialMacro = macros.firstOrNull()
            val genres = if (initialMacro == null) emptyList() else {
                withContext(Dispatchers.IO) { repository.browse(initialMacro) }
            }
            val initialGenre = genres.firstOrNull()
            val catalog = if (initialGenre == null) emptyList() else {
                withContext(Dispatchers.IO) { repository.browse(initialGenre) }
            }
            state = state.copy(
                page = AppPage.BROWSE,
                browseMacros = macros,
                browseItems = genres + catalog,
                browseSelectedFilterKey = initialGenre?.stableKey.orEmpty(),
                browseStack = emptyList(),
                browseRootPage = AppPage.CHANNELS,
                pageTitle = initialMacro?.title ?: "Sfoglia",
            )
        }
    }

    fun showLive() {
        // Cambio pagina immediato: qui non si caricano ne' si sondano i canali.
        liveFocusLocked = false
        state = state.copy(
            page = AppPage.LIVE,
            browseItems = emptyList(),
            browseSelectedFilterKey = "",
            browseStack = emptyList(),
            selectedItem = null,
            pageTitle = "Live TV",
            error = null,
        )
        preloadLiveAtStartup()
    }

    fun setUiPaused(paused: Boolean) {
        uiPaused = paused
        AppDiagnostics.event("ui_paused=$paused page=${state.page}")
        if (paused) {
            homeRefreshJob?.cancel()
        } else {
            if (state.page == AppPage.HOME) scheduleProgressiveHomeRefresh()
            if (!liveFocusLocked) applyPendingLiveRows()
        }
    }

    fun lockLiveFocus() {
        liveFocusLocked = true
        liveFocusUnlockJob?.cancel()
        liveFocusUnlockJob = viewModelScope.launch {
            // Applica le righe arrivate in background solo quando il telecomando
            // è fermo: il nodo focalizzato non viene sostituito durante il traversal.
            delay(800)
            liveFocusLocked = false
            applyPendingLiveRows()
        }
    }

    private fun applyPendingLiveRows() {
        val rows = pendingLiveRows ?: return
        if (uiPaused || liveFocusLocked) return
        pendingLiveRows = null
        state = state.copy(liveRows = rows)
        AppDiagnostics.event(
            "live_rows_deferred rows=${rows.size} items=${rows.sumOf { it.items.size }}",
        )
    }

    fun showDownloads() = runTask {
        // Questa pagina è una vista: il ripristino appartiene esclusivamente al
        // lifecycle del servizio e non deve mai mutare o riaccodare la coda.
        val downloads = withContext(Dispatchers.IO) { repository.downloads() }
        state = state.copy(
            page = AppPage.DOWNLOADS,
            downloads = downloads,
            selectedItem = null,
            pageTitle = "I miei download",
        )
    }

    fun refreshDownloads() {
        if (state.page != AppPage.DOWNLOADS) return
        viewModelScope.launch {
            try {
                val downloads = withContext(Dispatchers.IO) { repository.downloads() }
                if (state.page == AppPage.DOWNLOADS) state = state.copy(downloads = downloads)
            } catch (error: Exception) {
                android.util.Log.e("Prippi", "aggiornamento download", error)
            }
        }
    }

    fun prepareDownload(
        item: ContentItem,
        onReady: (ContentItem, PlaybackRequest) -> Unit,
    ) = runTask {
        if (item.isLive) error("Le dirette non possono essere scaricate")
        val playback = withContext(Dispatchers.IO) { repository.playback(item) }
            ?: error("Nessuna sorgente disponibile per il download")
        onReady(item, playback)
    }

    fun openTrailer(item: ContentItem, onReady: (List<String>) -> Unit) = runTask {
        val urls = withContext(Dispatchers.IO) { repository.trailerUrls(item) }
        if (urls.isEmpty()) error("Trailer non disponibile per questo contenuto")
        onReady(urls)
    }

    /**
     * Best-effort TV preview: unlike the explicit Trailer action it must not
     * toggle global loading/error state or disturb focus when no trailer exists.
     */
    suspend fun prefetchTrailer(item: ContentItem): List<String> =
        trailerPreviewMutex.withLock {
            try {
                withContext(Dispatchers.IO) { repository.trailerUrls(item) }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                android.util.Log.d(
                    "PrippiTrailer",
                    "Preview non disponibile: ${error.message}",
                )
                emptyList()
            }
        }

    fun pauseDownload(entry: DownloadEntry) = runTask {
        withContext(Dispatchers.IO) { repository.pauseDownload(entry.key) }
        state = state.copy(downloads = withContext(Dispatchers.IO) { repository.downloads() })
    }

    fun resumeDownload(entry: DownloadEntry) = runTask {
        withContext(Dispatchers.IO) { repository.resumeDownload(entry.key) }
        state = state.copy(downloads = withContext(Dispatchers.IO) { repository.downloads() })
    }

    fun removeDownload(entry: DownloadEntry) = runTask {
        withContext(Dispatchers.IO) { repository.removeDownload(entry.key) }
        state = state.copy(downloads = withContext(Dispatchers.IO) { repository.downloads() })
    }

    fun playDownload(entry: DownloadEntry, onPlayback: (PlaybackRequest) -> Unit) = runTask {
        val request = withContext(Dispatchers.IO) { repository.downloadPlayback(entry.key) }
        onPlayback(request)
    }

    fun openChannel(channel: ChannelInfo) = runTask {
        val rootPage = if (state.page == AppPage.LIVE) AppPage.LIVE else AppPage.CHANNELS
        val items = withContext(Dispatchers.IO) { repository.channelMenu(channel) }
        state = state.copy(
            page = AppPage.BROWSE,
            browseItems = items,
            browseSelectedFilterKey = "",
            browseStack = emptyList(),
            browseRootPage = rootPage,
            selectedItem = null,
            pageTitle = channel.title,
        )
    }

    fun openBrowseItem(item: ContentItem) {
        if (item.action == "search") {
            state = state.copy(
                page = AppPage.SEARCH,
                returnPage = AppPage.BROWSE,
                returnTitle = state.pageTitle,
                searchChannel = item.channel,
                query = "",
                results = emptyList(),
                pageTitle = "Cerca in ${state.pageTitle}",
                error = null,
            )
            return
        }
        if (item.channel == "_app_macro" && item.action == "_app_macro_genres") {
            runTask {
                val genres = withContext(Dispatchers.IO) { repository.browse(item) }
                val initialGenre = genres.firstOrNull()
                val catalog = if (initialGenre == null) emptyList() else {
                    withContext(Dispatchers.IO) { repository.browse(initialGenre) }
                }
                state = state.copy(
                    page = AppPage.BROWSE,
                    browseItems = genres + catalog,
                    browseSelectedFilterKey = initialGenre?.stableKey.orEmpty(),
                    browseStack = emptyList(),
                    browseRootPage = AppPage.CHANNELS,
                    pageTitle = item.title,
                )
            }
            return
        }
        if (item.channel == "_app_macro" && item.action == "_app_macro_titles") {
            runTask {
                val filters = state.browseItems.filter {
                    it.channel == "_app_macro" && it.action == "_app_macro_titles"
                }
                val catalog = withContext(Dispatchers.IO) { repository.browse(item) }
                state = state.copy(
                    page = AppPage.BROWSE,
                    browseItems = filters + catalog,
                    browseSelectedFilterKey = item.stableKey,
                    browseRootPage = AppPage.CHANNELS,
                    pageTitle = item.title,
                )
            }
            return
        }
        val playable = item.action in setOf(
            "findvideos", "play", "episodios", "epmenu", "epMenu",
            "seasons", "get_seasons",
        )
        if (playable) {
            showDetail(item)
            return
        }
        if (item.action.isBlank()) return
        runTask {
            val next = withContext(Dispatchers.IO) { repository.browse(item) }
            val isMacroControl = item.channel == "_app_macro" &&
                item.action in setOf("_app_macro_more", "_app_macro_sort")
            if (isMacroControl) {
                val filters = state.browseItems.filter {
                    it.channel == "_app_macro" && it.action == "_app_macro_titles"
                }
                state = state.copy(browseItems = filters + next)
                return@runTask
            }
            val enteringMacro = state.page == AppPage.CHANNELS && item.channel == "_app_macro"
            val level = BrowseLevel(state.pageTitle, item.channel, state.browseItems)
            state = state.copy(
                page = AppPage.BROWSE,
                browseItems = next,
                browseStack = if (enteringMacro) emptyList() else state.browseStack + level,
                browseRootPage = if (enteringMacro) AppPage.CHANNELS else state.browseRootPage,
                pageTitle = item.title,
            )
        }
    }

    fun showSettings() = runTask {
        val settings = withContext(Dispatchers.IO) { repository.settings() }
        state = state.copy(
            page = AppPage.SETTINGS,
            returnPage = AppPage.HOME,
            settings = settings,
            settingsChannel = "",
            selectedItem = null,
            pageTitle = "Impostazioni",
        )
    }

    fun updateSetting(setting: AppSetting, value: Any) = runTask {
        withContext(Dispatchers.IO) { repository.setSetting(setting.id, value, setting.channel) }
        val all = withContext(Dispatchers.IO) { repository.settings() }
        val settings = if (state.settingsChannel.isBlank()) all else all.mapNotNull { category ->
            category.copy(settings = category.settings.filter { it.channel == state.settingsChannel })
                .takeIf { it.settings.isNotEmpty() }
        }
        state = state.copy(settings = settings, page = AppPage.SETTINGS)
    }

    fun showDetail(item: ContentItem) {
        val sourcePage = if (state.page == AppPage.DETAIL) state.returnPage else state.page
        val saved = progressStore.find(item)
        val savedItem = saved?.contentItem()
        val enriched = item.withProgress(saved?.positionMs ?: item.progressMs, saved?.durationMs ?: item.durationMs)
        state = state.copy(
            page = AppPage.DETAIL,
            returnPage = sourcePage,
            selectedItem = enriched,
            selectedProgressItem = savedItem,
            detailOverview = enriched.plot,
            episodes = emptyList(),
            selectedSeason = 0,
            pageTitle = enriched.title,
            returnTitle = if (state.page == AppPage.DETAIL) state.returnTitle else state.pageTitle,
            error = null,
        )
        runTask {
            val detailed = withContext(Dispatchers.IO) {
                runCatching { repository.detailMetadata(enriched) }
                    .onFailure {
                        android.util.Log.e("PrippiDetail", "Arricchimento metadata fallito", it)
                    }
                    .getOrDefault(enriched)
            }.withProgress(enriched.progressMs, enriched.durationMs)
            android.util.Log.i(
                "PrippiDetail",
                "metadata tmdb=${detailed.tmdbId} runtime=${detailed.runtimeMinutes} " +
                    "plot=${detailed.plot.length} cast=${detailed.cast.isNotBlank()}",
            )
            val needsEpisodes =
                detailed.isSeries || detailed.isEpisode || detailed.toJson().has("_app_series_parent")
            val (parent, episodes) = if (needsEpisodes) {
                withContext(Dispatchers.IO) {
                    val parent = repository.seriesParent(detailed)
                    parent to parent?.let(repository::episodes).orEmpty()
                }
            } else {
                null to emptyList()
            }
            val withProgress = applyStoredProgress(episodes)
            state = state.copy(
                selectedItem = detailed,
                episodes = withProgress,
                detailOverview = detailed.plot.takeIf { it.isNotBlank() }
                    ?: parent?.plot?.takeIf { it.isNotBlank() }
                    ?: state.detailOverview,
                selectedSeason = detailed.season.takeIf { it > 0 }
                    ?: saved?.contentItem()?.season?.takeIf { it > 0 }
                    ?: withProgress.firstOrNull()?.season?.takeIf { it > 0 }
                    ?: 1,
            )
        }
    }

    fun selectSeason(season: Int) { state = state.copy(selectedSeason = season) }

    fun play(
        item: ContentItem,
        resume: Boolean,
        onPlayback: (ContentItem, List<PlaybackRequest>, Long) -> Unit,
    ) = runTask {
        val saved = progressStore.find(item)
        val savedItem = saved?.contentItem()
        val needsEpisodeFlow = item.isSeries || item.isEpisode ||
            item.toJson().has("_app_series_parent")
        val currentEpisodes = EpisodeFlowPolicy.ordered(state.episodes)
        val currentQueueUsable = currentEpisodes.size > 1 &&
            (item.isSeries || EpisodeFlowPolicy.indexOf(currentEpisodes, item) >= 0 ||
                savedItem?.let { EpisodeFlowPolicy.indexOf(currentEpisodes, it) >= 0 } == true)
        val episodeQueue = if (needsEpisodeFlow && !currentQueueUsable) {
            withContext(Dispatchers.IO) {
                val parent = repository.seriesParent(savedItem ?: item)
                    ?: repository.seriesParent(item)
                EpisodeFlowPolicy.ordered(parent?.let(repository::episodes).orEmpty())
            }.ifEmpty { currentEpisodes }
        } else {
            currentEpisodes
        }
        val playbackItem = EpisodeFlowPolicy.playbackItem(
            requested = item,
            resume = resume,
            saved = savedItem,
            orderedEpisodes = episodeQueue,
        )
        val playbacks = withContext(Dispatchers.IO) { repository.playbackCandidates(playbackItem) }
        if (playbacks.isEmpty()) error("Nessuna sorgente disponibile")
        val startMs = if (resume) saved?.positionMs ?: playbackItem.progressMs else 0L
        val episodeIndex = EpisodeFlowPolicy.indexOf(episodeQueue, playbackItem)
        val payload = playbackItem.toJson().apply {
            if (episodeIndex >= 0 && episodeQueue.size > 1) {
                put("_app_episode_queue", org.json.JSONArray().apply {
                    episodeQueue.forEach { put(it.toJson()) }
                })
                put("_app_episode_index", episodeIndex)
            }
        }
        onPlayback(playbackItem.copy(rawJson = payload.toString()), playbacks, startMs)
    }

    fun playLive(
        item: ContentItem,
        onPlayback: (ContentItem, List<PlaybackRequest>, Long) -> Unit,
    ) = runTask {
        val playbacks = withContext(Dispatchers.IO) { repository.playbackCandidates(item) }
        if (playbacks.isEmpty()) error("Diretta non disponibile")
        val row = state.liveRows.firstOrNull { liveRow ->
            liveRow.items.any { it.rawJson == item.rawJson }
        }
        val index = row?.items?.indexOfFirst { it.rawJson == item.rawJson } ?: -1
        val payload = item.toJson().apply {
            if (row != null && index >= 0) {
                put("_app_live_row_items", org.json.JSONArray().apply {
                    row.items.forEach { put(it.toJson()) }
                })
                put("_app_live_row_index", index)
            }
        }
        onPlayback(item.copy(rawJson = payload.toString()), playbacks, 0L)
    }

    fun removeProgress(item: ContentItem) {
        progressStore.remove(item)
        refreshContinueWatching()
        if (state.selectedItem?.continueWatchingKey == item.continueWatchingKey) {
            state = state.copy(selectedProgressItem = null)
        }
    }

    fun back(): Boolean {
        when (state.page) {
            AppPage.HOME -> return false
            AppPage.DETAIL -> {
                val target = state.returnPage
                state = state.copy(
                    page = target,
                    selectedItem = null,
                    episodes = emptyList(),
                    pageTitle = if (target == AppPage.SEARCH) state.returnTitle else "PrippiStream",
                    error = null,
                )
            }
            AppPage.SEARCH -> {
                val target = state.returnPage
                state = state.copy(
                    page = target,
                    results = emptyList(),
                    pageTitle = if (target == AppPage.HOME) "PrippiStream" else state.returnTitle,
                    searchChannel = "__global__",
                    searchFilter = "all",
                    error = null,
                )
            }
            AppPage.CHANNELS, AppPage.LIVE, AppPage.DOWNLOADS -> state = state.copy(
                page = AppPage.HOME,
                pageTitle = "PrippiStream",
                error = null,
            )
            AppPage.SETTINGS -> state = state.copy(
                page = state.returnPage,
                pageTitle = if (state.returnPage == AppPage.BROWSE) state.returnTitle else "PrippiStream",
                settingsChannel = "",
                error = null,
            )
            AppPage.BROWSE -> {
                val previous = state.browseStack.lastOrNull()
                if (previous == null) {
                    val rootPage = state.browseRootPage
                    state = state.copy(
                        page = rootPage,
                        browseItems = emptyList(),
                        pageTitle = if (rootPage == AppPage.LIVE) "Live TV" else "Canali",
                        error = null,
                    )
                } else {
                    state = state.copy(
                        browseItems = previous.items,
                        browseStack = state.browseStack.dropLast(1),
                        pageTitle = previous.title,
                        error = null,
                    )
                }
            }
        }
        return true
    }

    private fun applyStoredProgress(items: List<ContentItem>): List<ContentItem> = items.map { item ->
        val saved = progressStore.find(item)
        if (saved == null) item else item.withProgress(saved.positionMs, saved.durationMs)
    }

    private fun withContinueWatching(rows: List<HomeRow>): List<HomeRow> {
        val stored = progressStore.list()
        val items = stored.mapNotNull { it.contentItem() }
        AppDiagnostics.event("cw_home stored=${stored.size} rendered=${items.size}")
        return if (items.isEmpty()) rows else listOf(
            HomeRow(CONTINUE_ROW_ID, "Continua a guardare", items)
        ) + rows
    }

    private fun runTask(block: suspend () -> Unit) {
        foregroundTaskJob?.cancel()
        val generation = ++foregroundTaskGeneration
        foregroundTaskJob = viewModelScope.launch {
            state = state.copy(loading = true, error = null)
            try {
                engineReadySignal.await()
                block()
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                if (generation != foregroundTaskGeneration) return@launch
                android.util.Log.e("Prippi", "errore chiamata motore", error)
                state = state.copy(error = error.message ?: "Errore imprevisto")
            } finally {
                if (generation == foregroundTaskGeneration) {
                    state = state.copy(loading = false)
                }
            }
        }
    }

    companion object {
        private const val CONTINUE_ROW_ID = "continue_watching"

        fun factory(
            repository: ContentRepository,
            progressStore: WatchProgressStore,
            homeSnapshotStore: HomeSnapshotStore,
            initialHomeRows: List<HomeRow> = emptyList(),
            lowPowerDevice: Boolean = false,
        ): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T =
                MainViewModel(
                    repository,
                    progressStore,
                    homeSnapshotStore,
                    initialHomeRows,
                    lowPowerDevice,
                ) as T
        }
    }
}
