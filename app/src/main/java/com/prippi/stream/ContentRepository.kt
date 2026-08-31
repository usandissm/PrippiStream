package com.prippi.stream

import org.json.JSONObject

class ContentRepository {
    fun refreshScDomain(): JSONObject = PythonBridge.refreshScDomain()
    fun loadHome(): List<HomeRow> =
        PythonBridge.home().map { HomeRow.fromJson(it) }.filter { it.items.isNotEmpty() }

    fun liveRows(): List<HomeRow> =
        PythonBridge.liveRows().map { HomeRow.fromJson(it) }.filter { it.items.isNotEmpty() }

    fun search(query: String, channel: String = DEFAULT_CHANNEL): List<ContentItem> =
        (if (channel == GLOBAL_CHANNEL) PythonBridge.globalSearch(query) else PythonBridge.search(channel, query))
            .map { ContentItem.fromJson(it, channel.takeUnless { it == GLOBAL_CHANNEL } ?: DEFAULT_CHANNEL) }

    fun searchHistory(): List<String> = PythonBridge.searchHistory()

    fun saveSearch(query: String): List<String> = PythonBridge.searchHistory("save", query)

    fun clearSearchHistory() = PythonBridge.searchHistory("clear")

    fun channels(category: String? = null): List<ChannelInfo> =
        PythonBridge.channelCatalog(category).map { ChannelInfo.fromJson(it) }

    fun browseMacros(): List<ContentItem> =
        PythonBridge.browseMacros().map { ContentItem.fromJson(it, "_app_macro") }

    fun settings(): List<SettingCategory> =
        PythonBridge.settingsSchema()
            .map { SettingCategory.fromJson(it) }
            .mapNotNull { category ->
                category.copy(settings = category.settings.filter { it.channel.isBlank() })
                    .takeIf {
                        it.settings.isNotEmpty() &&
                            !it.label.startsWith("Provider", ignoreCase = true)
                    }
            }

    fun setSetting(id: String, value: Any, channel: String = "") =
        PythonBridge.setSetting(id, value, channel)

    fun trailerUrls(item: ContentItem): List<String> = PythonBridge.trailerUrls(item.toJson())

    fun detailMetadata(item: ContentItem): ContentItem =
        ContentItem.fromJson(PythonBridge.detailMetadata(item.toJson()), item.channel)

    fun downloads(resumeInterrupted: Boolean = false): List<DownloadEntry> =
        PythonBridge.downloads(resumeInterrupted).map { DownloadEntry.fromJson(it) }

    fun enqueueDownload(item: ContentItem, targetHeight: Int = 0) =
        PythonBridge.enqueueDownload(item.toJson().apply {
            // Alcuni Item restituiti dai canali non serializzano `channel`; la UI
            // lo ha già normalizzato e il resolver download deve riceverlo.
            put("channel", item.channel)
        }, targetHeight)

    fun pauseDownload(key: String) = PythonBridge.pauseDownload(key)

    fun resumeDownload(key: String) = PythonBridge.resumeDownload(key)

    fun removeDownload(key: String) = PythonBridge.removeDownload(key)

    fun downloadPlayback(key: String): PlaybackRequest =
        PlaybackRequest.fromJson(PythonBridge.downloadPlayback(key))

    fun channelMenu(channel: ChannelInfo): List<ContentItem> {
        val items = PythonBridge.channelCall(channel.id, "mainlist", org.json.JSONObject())
            .map { ContentItem.fromJson(it, channel.id) }
            .filterNot { it.action == "channel_config" }
        if ("search" !in PythonBridge.channelMethods(channel.id)) return items
        val search = org.json.JSONObject().apply {
            put("title", "Cerca in ${channel.title}")
            put("fulltitle", "Cerca in ${channel.title}")
            put("action", "search")
            put("channel", channel.id)
            put("thumbnail", channel.thumbnail)
        }
        return listOf(ContentItem.fromJson(search, channel.id)) + items
    }

    fun browse(item: ContentItem): List<ContentItem> =
        (if (item.channel == "_app_macro") {
            PythonBridge.browseMacroCall(item.toJson())
        } else {
            PythonBridge.channelCall(item.channel, item.action, item.toJson())
        })
            .map { ContentItem.fromJson(it, item.channel) }
            .filterNot { it.action == "channel_config" }

    fun episodes(item: ContentItem): List<ContentItem> {
        val parent = item.toJson().apply {
            remove("_app_episode_queue")
            remove("_app_series_parent")
        }
        return PythonBridge.seriesEpisodes(parent)
            .map { episodeJson ->
                episodeJson.put("_app_series_parent", org.json.JSONObject(parent.toString()))
                ContentItem.fromJson(episodeJson, item.channel)
            }
            .filter { it.isEpisode || it.action in setOf("findvideos", "play") }
            .sortedWith(compareBy<ContentItem> { it.season }.thenBy { it.episode })
    }

    /** Restituisce la serie padre anche per gli episodi salvati da versioni precedenti. */
    fun seriesParent(item: ContentItem): ContentItem? {
        val raw = item.toJson()
        raw.optJSONObject("_app_series_parent")?.let {
            return ContentItem.fromJson(it, item.channel)
        }
        if (!item.isEpisode) return item.takeIf { it.isSeries }

        val info = raw.optJSONObject("infoLabels") ?: org.json.JSONObject()
        val seriesTitle = info.optString("tvshowtitle")
            .ifBlank { raw.optString("contentSerieName") }
            .ifBlank { raw.optString("serieName") }
        if (seriesTitle.isBlank()) return null

        val episodeUrl = raw.optString("url")
        val titleId = Regex("/(?:iframe|watch)/(\\d+)").find(episodeUrl)?.groupValues?.getOrNull(1)
        val candidates = runCatching { search(seriesTitle, item.channel) }.getOrDefault(emptyList())
            .filter { it.isSeries }
        return candidates.firstOrNull { candidate ->
            titleId != null && Regex("/titles/$titleId(?:-|/|$)").containsMatchIn(candidate.toJson().optString("url"))
        } ?: candidates.firstOrNull { it.title.equals(seriesTitle, ignoreCase = true) }
            ?: candidates.firstOrNull()
    }

    fun playback(item: ContentItem): PlaybackRequest? {
        return playbackCandidates(item).firstOrNull()
    }

    fun playbackCandidates(item: ContentItem): List<PlaybackRequest> {
        val candidates = mutableListOf<Pair<String, org.json.JSONObject>>()
        val preResolved = mutableListOf<PlaybackRequest>()

        fun collect(content: org.json.JSONObject, defaultChannel: String) {
            val channel = content.optString("channel").ifBlank { defaultChannel }
            content.put("channel", channel)
            val direct = content.optString("action") in setOf("play", "live_channel") ||
                content.optString("server").isNotBlank() || content.optBoolean("_app_live")
            val sources = if (direct) listOf(content) else runCatching {
                PythonBridge.channelCall(channel, "findvideos", content)
            }.getOrDefault(emptyList())
            sources.filter { source ->
                val label = source.optString("title").lowercase()
                (source.optString("url").isNotBlank() ||
                    source.optString("action") == "live_channel" || source.optBoolean("_app_live")) &&
                    source.optString("server").lowercase() !in setOf("torrent", "unknown") &&
                    "videoteca" !in label
            }.forEach { candidates += channel to it }
        }

        val raw = item.toJson()
        if (!item.isLive && !item.isSeries && !item.isEpisode && item.tmdbId.isNotBlank()) {
            runCatching { PythonBridge.resolve4k(raw) }
                .getOrNull()
                ?.takeIf { it.optString("url").isNotBlank() }
                ?.let { preResolved += PlaybackRequest.fromJson(it) }
        }
        if (preResolved.isNotEmpty() && raw.optString("url").isBlank()) {
            val fhd = runCatching { PythonBridge.fhdFor4k(raw) }.getOrNull()
            if (fhd != null && fhd.length() > 0) collect(fhd, "streamingcommunity")
        } else {
            collect(raw, item.channel)
        }
        raw.optJSONArray("_app_fallback_items")?.let { alternatives ->
            for (index in 0 until alternatives.length()) {
                alternatives.optJSONObject(index)?.let { alternate ->
                    val action = alternate.optString("action")
                    if (action in setOf("findvideos", "play")) {
                        collect(alternate, alternate.optString("channel").ifBlank { item.channel })
                    }
                }
            }
        }

        val imageExtensions = setOf("jpg", "jpeg", "png", "gif", "webp", "bmp")
        return (preResolved + candidates.mapNotNull { (_, source) ->
            runCatching { PlaybackRequest.fromJson(PythonBridge.resolve(source)) }
                .onFailure { android.util.Log.e("Prippi", "Risoluzione sorgente ${source.optString("action")}", it) }
                .getOrNull()
        }.filter { request ->
            request.url.isNotBlank() && request.url.substringBefore('?').substringAfterLast('.', "")
                .lowercase() !in imageExtensions
        }).distinctBy { request -> request.url.substringBefore('|') }
    }

    private companion object {
        const val DEFAULT_CHANNEL = "streamingcommunity"
        const val GLOBAL_CHANNEL = "__global__"
    }
}
