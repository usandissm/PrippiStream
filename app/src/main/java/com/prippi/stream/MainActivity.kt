package com.prippi.stream

import android.content.Intent
import android.content.Context
import android.content.pm.ActivityInfo
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.os.SystemClock
import android.Manifest
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.focusable
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.Image
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.itemsIndexed as gridItemsIndexed
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.LiveTv
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Sort
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Switch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import com.prippi.stream.diagnostics.DiagnosticSanitizer
import com.prippi.stream.diagnostics.DiagnosticDelivery
import com.prippi.stream.playback.planAndroidPlayback
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import coil.compose.SubcomposeAsyncImage
import coil.request.ImageRequest
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

open class MainActivity : ComponentActivity() {
    private lateinit var model: MainViewModel
    private lateinit var deviceProfile: DeviceProfile
    private var focusRecoveryNonce by mutableIntStateOf(0)
    private var engineStarting = false
    private var mainUiInitialized = false
    @Volatile
    private var startupContentReady = false
    private val firstComposeContentReady = CompletableDeferred<Unit>()
    private var downloadRestoreScheduled = false
    private val homeSnapshotStore by lazy {
        HomeSnapshotStore(applicationContext)
    }
    protected open val forceTelevisionProfile: Boolean = false

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen().setKeepOnScreenCondition { !startupContentReady }
        super.onCreate(savedInstanceState)
        val detectedProfile = DeviceProfile.detect(this)
        deviceProfile = if (forceTelevisionProfile) {
            detectedProfile.asTelevision()
        } else {
            detectedProfile
        }
        AppDiagnostics.event(
            "main_create form_factor=${deviceProfile.formFactor.name.lowercase()} " +
                "input=${deviceProfile.inputMode.name.lowercase()} " +
                "performance=${deviceProfile.performanceTier.name.lowercase()} " +
                "television=${deviceProfile.isTelevision} " +
                "low_power=${deviceProfile.isLowPower} " +
                "width_dp=${resources.configuration.screenWidthDp} " +
                "height_dp=${resources.configuration.screenHeightDp}",
        )
        if (deviceProfile.isTelevision) {
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            WindowCompat.setDecorFitsSystemWindows(window, false)
            WindowInsetsControllerCompat(window, window.decorView).apply {
                hide(WindowInsetsCompat.Type.systemBars())
                systemBarsBehavior =
                    WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2102)
        }
        startEngineAndUi()
    }

    private fun startEngineAndUi() {
        if (engineStarting || isFinishing || isDestroyed) return
        engineStarting = true
        lifecycleScope.launch {
            val initialRows = withContext(Dispatchers.IO) {
                homeSnapshotStore.load()
            }
            if (initialRows.isNotEmpty()) {
                // Con uno snapshot valido la Home è il primo contenuto Compose:
                // evita il flash del bootstrap e anticipa il primo frame utile.
                initializeMainUi(initialRows)
            } else {
                renderEngineBootstrap()
            }
            // Non basta attendere un tempo fisso dopo setContent: la prima
            // composizione può richiedere più tempo sui box lenti. Chaquopy
            // parte solo dopo che Compose ha realmente applicato il contenuto.
            firstComposeContentReady.await()
            delay(500)
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val tid = android.os.Process.myTid()
                    val previousPriority = android.os.Process.getThreadPriority(tid)
                    try {
                        android.os.Process.setThreadPriority(
                            android.os.Process.THREAD_PRIORITY_BACKGROUND,
                        )
                        PythonBridge.start(applicationContext)
                        PythonBridge.setDeviceProfile(deviceProfile)
                    } finally {
                        android.os.Process.setThreadPriority(previousPriority)
                    }
                }
            }
            engineStarting = false
            result.onSuccess {
                if (!mainUiInitialized) initializeMainUi(emptyList())
                model.onEngineReady()
                scheduleDownloadRestore()
            }.onFailure { error ->
                AppDiagnostics.event("engine_start_failed", error)
                if (!mainUiInitialized) {
                    renderEngineBootstrap(error.message ?: "Errore inizializzazione motore")
                }
            }
        }
    }

    private fun renderEngineBootstrap(error: String? = null) {
        setContent {
            PrippiTheme(deviceProfile) {
                EngineBootstrapScreen(error = error, onRetry = ::startEngineAndUi)
            }
            SideEffect { markStartupContentComposed() }
        }
    }

    private fun initializeMainUi(initialRows: List<HomeRow>) {
        if (mainUiInitialized || isFinishing || isDestroyed) return
        model = ViewModelProvider(
            this,
            MainViewModel.factory(
                ContentRepository(),
                WatchProgressStore(applicationContext),
                homeSnapshotStore,
                initialRows,
                lowPowerDevice = deviceProfile.isLowPower,
            ),
        )[MainViewModel::class.java]
        mainUiInitialized = true
        setContent {
            PrippiTheme(deviceProfile) {
                PrippiApp(
                    model,
                    deviceProfile = deviceProfile,
                    focusRecoveryNonce = focusRecoveryNonce,
                )
            }
            SideEffect { markStartupContentComposed() }
        }
    }

    private fun markStartupContentComposed() {
        if (!startupContentReady) startupContentReady = true
        if (!firstComposeContentReady.isCompleted) firstComposeContentReady.complete(Unit)
    }

    private fun scheduleDownloadRestore() {
        if (downloadRestoreScheduled || !::model.isInitialized) return
        downloadRestoreScheduled = true
        // Il download manager importa una parte ampia del motore Python. Farlo
        // prima della Home teneva il GIL durante il primo paint e poteva
        // trasformare un host lento in decine di secondi di bootstrap. Il
        // ripristino resta automatico, ma parte soltanto quando la Home è utile.
        lifecycleScope.launch {
            var waitedMs = 0L
            while (model.state.homeRows.isEmpty() && waitedMs < 60_000L) {
                delay(1_000)
                waitedMs += 1_000
            }
            delay(if (deviceProfile.isLowPower) 20_000 else 8_000)
            if (!isFinishing && !isDestroyed) {
                DownloadForegroundService.start(
                    applicationContext,
                    restoreInterrupted = true,
                )
            }
        }
    }

    override fun onPause() {
        if (::model.isInitialized) model.setUiPaused(true)
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        if (deviceProfile.isTelevision) {
            WindowInsetsControllerCompat(window, window.decorView)
                .hide(WindowInsetsCompat.Type.systemBars())
        }
        // Il player usa il landscape. Tornando indietro, alcuni telefoni Samsung
        // mantengono quella rotazione anche se la UI principale è pensata in
        // verticale. TV/tablet restano invece liberi di usare il landscape.
        if (!deviceProfile.isTelevision &&
            resources.configuration.smallestScreenWidthDp < 600
        ) {
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
        if (::model.isInitialized) {
            model.setUiPaused(false)
            model.refreshContinueWatching()
        }
    }

    @android.annotation.SuppressLint("RestrictedApi")
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        return try {
            super.dispatchKeyEvent(event)
        } catch (error: IllegalStateException) {
            val detachedComposeFocus =
                deviceProfile.isTelevision &&
                    error.message?.contains(
                        "LayoutCoordinate operations are only valid when isAttached is true",
                    ) == true
            if (!detachedComposeFocus) throw error
            AppDiagnostics.event(
                "compose_detached_focus_recovered key=${event.keyCode} action=${event.action}",
                error,
            )
            // Fa ricomporre la pagina e richiede nuovamente il focus sulla
            // card stabile registrata, invece di terminare l'intero processo.
            focusRecoveryNonce += 1
            true
        }
    }

    override fun onDestroy() {
        if (isFinishing && !isChangingConfigurations) {
            AppDiagnostics.markCleanExit("MainActivity finishing")
        }
        super.onDestroy()
    }
}

@Composable
private fun EngineBootstrapScreen(error: String?, onRetry: () -> Unit) {
    Box(
        Modifier.fillMaxSize().background(Color(0xFF060A0F)),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            Image(
                painter = painterResource(R.drawable.prippistream_logo_banner),
                contentDescription = "PrippiStream",
                modifier = Modifier.width(300.dp),
            )
            if (error == null) {
                CircularProgressIndicator()
                Text(
                    "Preparazione dell'esperienza PrippiStream…",
                    style = MaterialTheme.typography.titleMedium,
                    color = Color(0xFFB9C9DA),
                )
            } else {
                Text(
                    "Avvio non riuscito",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    error,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color(0xFFB9C9DA),
                )
                Button(onClick = onRetry) { Text("Riprova") }
            }
        }
    }
}

private fun networkSummary(context: Context, includeAddresses: Boolean = true): String {
    val manager = context.getSystemService(ConnectivityManager::class.java)
    val network = manager?.activeNetwork
    val capabilities = network?.let(manager::getNetworkCapabilities)
    val links = network?.let(manager::getLinkProperties)
    val transport = when {
        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true -> "Wi-Fi"
        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true -> "Rete mobile"
        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) == true -> "Ethernet"
        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true -> "VPN"
        else -> "Non connesso"
    }
    val addresses = links?.linkAddresses?.joinToString { it.address.hostAddress.orEmpty() }.orEmpty()
    val dns = links?.dnsServers?.joinToString { it.hostAddress.orEmpty() }.orEmpty()
    return buildString {
        appendLine("PrippiStream ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
        appendLine("Dispositivo: ${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
        appendLine("Connessione: $transport")
        appendLine("Internet validato: ${capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true}")
        if (includeAddresses) {
            appendLine("Indirizzi IP: ${addresses.ifBlank { "non disponibili" }}")
            append("DNS: ${dns.ifBlank { "non disponibili" }}")
        } else {
            appendLine("Indirizzi IP: [oscurati]")
            append("DNS: [oscurati]")
        }
    }
}

private val diagnosticReportInProgress = AtomicBoolean(false)

private fun promptAndShareDiagnosticReport(context: Context) {
    val note = android.widget.EditText(context).apply {
        hint = "Nome e problema (facoltativo)"
        isSingleLine = false
        maxLines = 4
        setPadding(32, 20, 32, 20)
    }
    android.app.AlertDialog.Builder(context)
        .setTitle("Invia diagnostica")
        .setMessage(
            "Il report viene sanitizzato e inviato direttamente allo sviluppatore via Telegram.",
        )
        .setView(note)
        .setPositiveButton("Invia") { _, _ ->
            shareDiagnosticReport(context, note.text?.toString().orEmpty())
        }
        .setNegativeButton("Annulla", null)
        .show()
}

private fun shareDiagnosticReport(context: Context, note: String = "") {
    if (!diagnosticReportInProgress.compareAndSet(false, true)) {
        android.widget.Toast.makeText(
            context,
            "La diagnostica è già in preparazione.",
            android.widget.Toast.LENGTH_SHORT,
        ).show()
        return
    }
    android.widget.Toast.makeText(
        context,
        "Preparazione diagnostica…",
        android.widget.Toast.LENGTH_SHORT,
    ).show()
    Thread {
        runCatching {
            val directory = File(context.cacheDir, "diagnostics").apply { mkdirs() }
            val downloadTask = FutureTask { PythonBridge.downloads() }
            Thread(downloadTask, "prippi-diagnostic-downloads").apply {
                isDaemon = true
                start()
            }
            val downloads = runCatching {
                downloadTask.get(2_500, TimeUnit.MILLISECONDS)
            }.getOrElse {
                downloadTask.cancel(true)
                emptyList()
            }
            val downloadSnapshot = if (downloads.isEmpty()) {
                "Nessun download registrato."
            } else {
                downloads.joinToString("\n") { entry ->
                    buildString {
                        append(entry.optString("key"))
                        append(" · stato=").append(entry.optString("status"))
                        append(" · progresso=").append(entry.optDouble("progress", 0.0)).append('%')
                        append(" · byte=").append(entry.optLong("total_bytes", 0L))
                        entry.optString("error").takeIf(String::isNotBlank)
                            ?.let { append(" · errore=").append(it) }
                    }
                }
            }
            val generatedAt = SimpleDateFormat(
                "yyyy-MM-dd'T'HH:mm:ss.SSSXXX",
                Locale.ROOT,
            ).format(Date())
            val reportBody = buildString {
                appendLine("Report generato: $generatedAt")
                appendLine(networkSummary(context, includeAddresses = false))
                appendLine()
                appendLine("--- APP / CRASH ---")
                appendLine(AppDiagnostics.report())
                appendLine()
                appendLine("--- STATO DOWNLOAD ---")
                appendLine(downloadSnapshot)
            }
            val report = File(directory, "PrippiStream-diagnostica-${System.currentTimeMillis()}.txt")
            val sanitized = DiagnosticSanitizer.sanitize(reportBody)
            report.writeText(sanitized)
            DiagnosticDelivery.deliverOrFallback(context, sanitized, report, note)
        }.onFailure { error ->
            android.os.Handler(context.mainLooper).post {
                android.widget.Toast.makeText(
                    context,
                    "Impossibile creare il report: ${error.message}",
                    android.widget.Toast.LENGTH_LONG,
                ).show()
            }
        }.also {
            diagnosticReportInProgress.set(false)
        }
    }.start()
}

private typealias PlaybackStarter = (ContentItem, List<PlaybackRequest>, Long) -> Unit

private val TvFocusBorder = Color(0xFFFFD54F)
private val TvFocusBackground = Color(0xFF075A9C)

@Composable
private fun Modifier.tvFocusableFrame(
    enabled: Boolean,
    shape: RoundedCornerShape = RoundedCornerShape(10.dp),
    onFocused: () -> Unit = {},
): Modifier {
    if (!enabled) return this
    var focused by remember { mutableStateOf(false) }
    return this
        .onFocusChanged {
            focused = it.isFocused
            if (it.isFocused) onFocused()
        }
        .scale(if (focused) 1.09f else 1f)
        .zIndex(if (focused) 1f else 0f)
        .border(
            width = if (focused) 4.dp else 0.dp,
            color = if (focused) TvFocusBorder else Color.Transparent,
            shape = shape,
        )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PrippiApp(
    model: MainViewModel,
    deviceProfile: DeviceProfile,
    focusRecoveryNonce: Int,
) {
    val state = model.state
    val context = androidx.compose.ui.platform.LocalContext.current
    UpdateReminderDialog()
    val isTelevision = deviceProfile.isTelevision
    val compactTvLandscape = isTelevision &&
        LocalConfiguration.current.screenHeightDp < 540
    var tvSearchVisible by rememberSaveable { mutableStateOf(false) }
    var tvHomeFocusedRow by rememberSaveable { mutableStateOf("") }
    var tvHomeFocusedItem by rememberSaveable { mutableStateOf("") }
    var tvLiveFocusedRow by rememberSaveable { mutableStateOf("") }
    var tvLiveFocusedItem by rememberSaveable { mutableStateOf("") }
    fun startPlayer(item: ContentItem, requests: List<PlaybackRequest>, startMs: Long) {
        val request = requests.first()
        context.startActivity(Intent(context, PlayerActivity::class.java).apply {
            putExtra("television_player", isTelevision)
            putExtra("url", request.url)
            putExtra("bootstrap_url", request.bootstrapUrl)
            putExtra("manifest", request.manifest)
            putExtra("audio", request.audioLanguage)
            putExtra("headers", request.headersJson)
            putExtra("playback_candidates_json", JSONArray().apply {
                requests.forEach { put(it.toJson()) }
            }.toString())
            if (item.isLive) {
                val livePayload = item.toJson()
                putExtra("live_channel_title", item.title)
                putExtra("live_programme", item.plot)
                putExtra(
                    "live_row_items_json",
                    livePayload.optJSONArray("_app_live_row_items")?.toString().orEmpty(),
                )
                putExtra("live_row_index", livePayload.optInt("_app_live_row_index", -1))
            } else {
                val episodePayload = item.toJson()
                val fullQueue = episodePayload.optJSONArray("_app_episode_queue")
                val fullIndex = episodePayload.optInt("_app_episode_index", -1)
                var episodeQueueKey = ""
                var episodeQueueSize = 0
                if (fullQueue != null && fullIndex in 0 until fullQueue.length()) {
                    episodeQueueKey = runCatching {
                        EpisodeQueueStore.put(context, fullQueue)
                    }.getOrElse {
                        android.util.Log.e("Prippi", "Salvataggio coda episodi", it)
                        ""
                    }
                    episodeQueueSize = if (episodeQueueKey.isNotBlank()) fullQueue.length() else 0
                }
                putExtra("episode_queue_key", episodeQueueKey)
                putExtra("episode_queue_size", episodeQueueSize)
                putExtra("episode_queue_index", if (episodeQueueSize > 0) fullIndex else -1)
                putExtra("progress_key", item.continueWatchingKey)
                putExtra(
                    "content_json",
                    JSONObject(item.rawJson).apply {
                        remove("_app_episode_queue")
                        remove("_app_episode_index")
                    }.toString(),
                )
                putExtra("start_position_ms", startMs)
            }
        })
    }
    val play: PlaybackStarter = { item, requests, startMs ->
        val policyOptions = runCatching { PythonBridge.playbackPolicyOptions() }
            .getOrDefault(JSONObject())
        val plan = planAndroidPlayback(
            context = context,
            profile = deviceProfile,
            requests = requests,
            allow4KOnMetered = policyOptions.optBoolean("allow_4k_metered", false),
            treatWifiAsMetered = policyOptions.optBoolean("treat_wifi_metered", false),
        )
        if (plan.ordered.isEmpty()) {
            android.widget.Toast.makeText(
                context,
                "Nessuna sorgente compatibile con rete e dispositivo.",
                android.widget.Toast.LENGTH_LONG,
            ).show()
        } else if (plan.askForConfirmation) {
            android.app.AlertDialog.Builder(context)
                .setTitle("Qualità di riproduzione — ${item.title}")
                .setItems(arrayOf("4K (Ultra HD)", "Full HD (1080p)")) { _, choice ->
                    startPlayer(
                        item,
                        if (choice == 0) plan.fourK else plan.standard,
                        startMs,
                    )
                }
                .setNegativeButton("Annulla", null)
                .show()
        } else {
            startPlayer(item, plan.ordered, startMs)
        }
    }
    val playOffline: (PlaybackRequest) -> Unit = { request ->
        context.startActivity(Intent(context, PlayerActivity::class.java).apply {
            putExtra("television_player", isTelevision)
            putExtra("url", request.url)
            putExtra("bootstrap_url", request.bootstrapUrl)
            putExtra("manifest", request.manifest)
            putExtra("audio", request.audioLanguage)
            putExtra("headers", request.headersJson)
        })
    }
    val download: (ContentItem, PlaybackRequest) -> Unit = { item, request ->
        val labels = arrayOf("Migliore disponibile", "Full HD · 1080p", "HD · 720p", "SD · 480p")
        val heights = intArrayOf(0, 1080, 720, 480)
        var selectedIndex = 0
        android.app.AlertDialog.Builder(context)
            .setTitle("Qualità download — ${item.title}")
            .setSingleChoiceItems(labels, selectedIndex) { _, index ->
                selectedIndex = index
            }
            .setPositiveButton("Scarica") { _, _ ->
                android.widget.Toast.makeText(
                    context,
                    "Preparazione download…",
                    android.widget.Toast.LENGTH_SHORT,
                ).show()
                context.startActivity(Intent(context, DownloadPreparationActivity::class.java).apply {
                    putExtra("url", request.url)
                    putExtra("bootstrap_url", request.bootstrapUrl)
                    putExtra("manifest", request.manifest)
                    putExtra("headers", request.headersJson)
                    putExtra("download_target_height", heights[selectedIndex])
                    putExtra(
                        "download_item_json",
                        item.toJson().apply { put("channel", item.channel) }.toString(),
                    )
                })
            }
            .setNegativeButton("Annulla", null)
            .show()
    }
    LaunchedEffect(state.page) {
        if (state.page == AppPage.DOWNLOADS) {
            while (true) {
                delay(2_000)
                model.refreshDownloads()
            }
        }
    }
    BackHandler(enabled = state.page != AppPage.HOME) { model.back() }

    if (isTelevision) {
        TelevisionApp(
            model = model,
            state = state,
            play = play,
            playOffline = playOffline,
            download = download,
            focusRecoveryNonce = focusRecoveryNonce,
            homeFocusedRow = tvHomeFocusedRow,
            homeFocusedItem = tvHomeFocusedItem,
            liveFocusedRow = tvLiveFocusedRow,
            liveFocusedItem = tvLiveFocusedItem,
            onHomeFocus = { rowId, itemKey ->
                tvHomeFocusedRow = rowId
                tvHomeFocusedItem = itemKey
                AppDiagnostics.focus("home", rowId, itemKey)
            },
            onLiveFocus = { rowId, itemKey ->
                model.lockLiveFocus()
                tvLiveFocusedRow = rowId
                tvLiveFocusedItem = itemKey
                AppDiagnostics.focus("live", rowId, itemKey)
            },
        )
        return
    }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Image(
                        painter = painterResource(R.drawable.prippistream_logo_banner),
                        contentDescription = "PrippiStream",
                        contentScale = ContentScale.Fit,
                        modifier = Modifier.width(280.dp).height(58.dp),
                    )
                },
                navigationIcon = {
                    if (state.page != AppPage.HOME) {
                        IconButton(onClick = { model.back() }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Indietro")
                        }
                    }
                },
                actions = {
                    if (isTelevision && state.page in setOf(AppPage.HOME, AppPage.SEARCH)) {
                        IconButton(onClick = { tvSearchVisible = !tvSearchVisible }) {
                            Icon(Icons.Default.Search, contentDescription = "Cerca")
                        }
                    }
                    if (state.page == AppPage.HOME) {
                        IconButton(onClick = model::loadHome) {
                            Icon(Icons.Default.Refresh, contentDescription = "Aggiorna")
                        }
                    } else {
                        IconButton(onClick = model::loadHome) {
                            Icon(Icons.Default.Home, contentDescription = "Home")
                        }
                    }
                },
            )
        },
        bottomBar = {
            val tvRootPage = state.page in setOf(
                AppPage.HOME,
                AppPage.CHANNELS,
                AppPage.LIVE,
                AppPage.DOWNLOADS,
            )
            if (state.page != AppPage.SETTINGS && (!isTelevision || tvRootPage)) {
                val selectedRoot = when (state.page) {
                    AppPage.BROWSE -> state.browseRootPage
                    AppPage.DETAIL -> when (state.returnPage) {
                        AppPage.BROWSE -> state.browseRootPage
                        AppPage.SEARCH -> AppPage.HOME
                        else -> state.returnPage
                    }
                    AppPage.SEARCH -> AppPage.HOME
                    else -> state.page
                }
                NavigationBar(
                    modifier = if (compactTvLandscape) {
                        Modifier.height(56.dp)
                    } else {
                        Modifier
                    },
                ) {
                    NavigationBarItem(
                        selected = selectedRoot == AppPage.HOME,
                        onClick = model::loadHome,
                        icon = { Icon(Icons.Default.Home, contentDescription = null) },
                        label = { Text("Home") },
                    )
                    NavigationBarItem(
                        selected = selectedRoot == AppPage.CHANNELS,
                        onClick = model::showChannels,
                        icon = { Icon(Icons.Default.List, contentDescription = null) },
                        label = { Text("Sfoglia") },
                    )
                    NavigationBarItem(
                        selected = selectedRoot == AppPage.LIVE,
                        onClick = model::showLive,
                        icon = { Icon(Icons.Default.LiveTv, contentDescription = null) },
                        label = { Text("Live") },
                    )
                    NavigationBarItem(
                        selected = selectedRoot == AppPage.DOWNLOADS,
                        onClick = model::showDownloads,
                        icon = { Icon(Icons.Default.Download, contentDescription = null) },
                        label = { Text("Download") },
                    )
                    NavigationBarItem(
                        selected = false,
                        onClick = model::showSettings,
                        icon = { Icon(Icons.Default.Settings, contentDescription = "Impostazioni") },
                        label = null,
                        alwaysShowLabel = false,
                    )
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (state.page in setOf(AppPage.HOME, AppPage.SEARCH) &&
                (!isTelevision || tvSearchVisible || state.page == AppPage.SEARCH)
            ) {
            SearchBar(
                state.query,
                model::setQuery,
                model::search,
                requestInitialFocus = isTelevision && tvSearchVisible,
                television = isTelevision,
            )
            }
            if (state.page == AppPage.HOME && state.searchHistory.isNotEmpty() &&
                (!isTelevision || tvSearchVisible)
            ) {
                SearchHistoryRow(
                    values = state.searchHistory,
                    onSelect = model::searchFromHistory,
                    onClear = model::clearSearchHistory,
                )
            }
            if (state.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            state.error?.let { ErrorState(it, model::loadHome) }
            when (state.page) {
                AppPage.HOME -> HomePage(
                    state.homeRows,
                    state.loading,
                    model::showDetail,
                    model::loadHome,
                    isTelevision,
                    tvHomeFocusedRow,
                    tvHomeFocusedItem,
                    focusRecoveryNonce,
                    { rowId, itemKey ->
                        tvHomeFocusedRow = rowId
                        tvHomeFocusedItem = itemKey
                        AppDiagnostics.focus("home", rowId, itemKey)
                    },
                )
                AppPage.SEARCH -> SearchResults(
                    items = state.results,
                    filter = state.searchFilter,
                    loading = state.loading,
                    onFilter = model::selectSearchFilter,
                    onClick = model::showDetail,
                )
                AppPage.CHANNELS -> BrowseLanding(
                    macros = state.browseMacros,
                    loading = state.loading,
                    onMacro = model::openBrowseItem,
                )
                AppPage.LIVE -> LivePage(
                    rows = state.liveRows,
                    loading = state.loading,
                    onLive = { model.playLive(it, play) },
                    isTelevision = isTelevision,
                    focusedRowId = tvLiveFocusedRow,
                    focusedItemKey = tvLiveFocusedItem,
                    focusRecoveryNonce = focusRecoveryNonce,
                    onItemFocused = { rowId, itemKey ->
                        model.lockLiveFocus()
                        tvLiveFocusedRow = rowId
                        tvLiveFocusedItem = itemKey
                        AppDiagnostics.focus("live", rowId, itemKey)
                    },
                )
                AppPage.DOWNLOADS -> DownloadsPage(
                    entries = state.downloads,
                    loading = state.loading,
                    isTelevision = false,
                    onPlay = { model.playDownload(it, playOffline) },
                    onPause = model::pauseDownload,
                    onResume = {
                        // Sincronizza prima il gate: il worker non deve avere
                        // neppure una breve finestra per partire senza rete.
                        PythonBridge.syncDownloadNetwork(context)
                        DownloadForegroundService.start(context)
                        model.resumeDownload(it)
                    },
                    onRemove = model::removeDownload,
                )
                AppPage.BROWSE -> ResultList(state.browseItems, state.loading, model::openBrowseItem)
                AppPage.SETTINGS -> SettingsPage(state.settings, model::updateSetting)
                AppPage.DETAIL -> state.selectedItem?.let { selected ->
                    DetailPage(
                        item = selected,
                        progressItem = state.selectedProgressItem,
                        overview = state.detailOverview,
                        episodes = state.episodes,
                        selectedSeason = state.selectedSeason,
                        loading = state.loading,
                        onSeason = model::selectSeason,
                        onPlay = { item, resume -> model.play(item, resume, play) },
                        onDownload = { item -> model.prepareDownload(item, download) },
                        onTrailer = { item ->
                            model.openTrailer(item) { urls ->
                                context.startActivity(Intent(context, TrailerActivity::class.java).apply {
                                    putExtra(TrailerActivity.EXTRA_URLS, JSONArray(urls).toString())
                                    putExtra(TrailerActivity.EXTRA_TITLE, item.title)
                                })
                            }
                        },
                        onRemoveProgress = model::removeProgress,
                        isTelevision = isTelevision,
                    )
                }
            }
        }
    }
}

@Composable
private fun TelevisionApp(
    model: MainViewModel,
    state: AppUiState,
    play: PlaybackStarter,
    playOffline: (PlaybackRequest) -> Unit,
    download: (ContentItem, PlaybackRequest) -> Unit,
    focusRecoveryNonce: Int,
    homeFocusedRow: String,
    homeFocusedItem: String,
    liveFocusedRow: String,
    liveFocusedItem: String,
    onHomeFocus: (String, String) -> Unit,
    onLiveFocus: (String, String) -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var searchOpen by rememberSaveable { mutableStateOf(false) }
    BackHandler(enabled = searchOpen && state.page == AppPage.HOME) {
        searchOpen = false
    }
    val selectedRoot = when (state.page) {
        AppPage.BROWSE -> state.browseRootPage
        AppPage.DETAIL -> state.returnPage
        AppPage.SEARCH -> AppPage.HOME
        else -> state.page
    }
    androidx.compose.runtime.CompositionLocalProvider(LocalContentColor provides Color.White) {
        Row(
            Modifier.fillMaxSize().background(Color(0xFF060A0F)),
        ) {
            TelevisionRail(
            selected = selectedRoot,
            searchSelected = searchOpen ||
                state.page == AppPage.SEARCH ||
                (state.page == AppPage.DETAIL && state.returnPage == AppPage.SEARCH),
            onHome = { searchOpen = false; model.loadHome() },
            onSearch = { searchOpen = true },
            onBrowse = { searchOpen = false; model.showBrowseCatalog() },
            onLive = { searchOpen = false; model.showLive() },
            onDownloads = { searchOpen = false; model.showDownloads() },
            onSettings = { searchOpen = false; model.showSettings() },
        )
            Box(Modifier.weight(1f).fillMaxSize()) {
                Column(Modifier.fillMaxSize()) {
                if (searchOpen || state.page == AppPage.SEARCH) {
                    val dimensions = LocalPrippiDimensions.current
                    Row(
                        Modifier.fillMaxWidth()
                            .background(Color(0xE6101720))
                            .padding(
                                start = dimensions.screenHorizontalPadding,
                                end = dimensions.screenHorizontalPadding +
                                    (196f * dimensions.uiScale).dp,
                                top = (14f * dimensions.uiScale).dp,
                                bottom = (14f * dimensions.uiScale).dp,
                            ),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        SearchBar(
                            state.query,
                            model::setQuery,
                            model::search,
                            requestInitialFocus = searchOpen,
                            television = true,
                        )
                    }
                }
                if (state.loading) {
                    LinearProgressIndicator(
                        Modifier.fillMaxWidth(),
                        color = Color(0xFF5CB3FF),
                    )
                }
                state.error?.let { ErrorState(it, model::loadHome) }
                if (searchOpen && state.page != AppPage.SEARCH) {
                    TelevisionSearchLanding()
                } else when (state.page) {
                    AppPage.HOME -> TelevisionHome(
                        rows = state.homeRows,
                        loading = state.loading,
                        onClick = model::showDetail,
                        onPlay = { item -> model.play(item, false, play) },
                        onRetry = model::loadHome,
                        focusedRowId = homeFocusedRow,
                        focusedItemKey = homeFocusedItem,
                        focusRecoveryNonce = focusRecoveryNonce,
                        onFocused = onHomeFocus,
                    )
                    AppPage.SEARCH -> TelevisionSearchResults(
                        items = state.results,
                        filter = state.searchFilter,
                        loading = state.loading,
                        onFilter = model::selectSearchFilter,
                        onClick = {
                            searchOpen = false
                            model.showDetail(it)
                        },
                    )
                    AppPage.CHANNELS -> TelevisionBrowseLanding(
                        state.browseMacros,
                        state.loading,
                        model::openBrowseItem,
                    )
                    AppPage.LIVE -> TelevisionLive(
                        rows = state.liveRows,
                        loading = state.loading,
                        onLive = { model.playLive(it, play) },
                        focusedRowId = liveFocusedRow,
                        focusedItemKey = liveFocusedItem,
                        focusRecoveryNonce = focusRecoveryNonce,
                        onFocused = onLiveFocus,
                    )
                    AppPage.DOWNLOADS -> DownloadsPage(
                        entries = state.downloads,
                        loading = state.loading,
                        isTelevision = true,
                        onPlay = { model.playDownload(it, playOffline) },
                        onPause = model::pauseDownload,
                        onResume = {
                            PythonBridge.syncDownloadNetwork(context)
                            DownloadForegroundService.start(context)
                            model.resumeDownload(it)
                        },
                        onRemove = model::removeDownload,
                    )
                    AppPage.BROWSE -> TelevisionBrowseCatalog(
                        macros = state.browseMacros,
                        items = state.browseItems,
                        selectedFilterKey = state.browseSelectedFilterKey,
                        loading = state.loading,
                        onClick = model::openBrowseItem,
                    )
                    AppPage.SETTINGS -> TelevisionSettingsPage(
                        state.settings,
                        model::updateSetting,
                    )
                    AppPage.DETAIL -> state.selectedItem?.let { item ->
                        var previewUrls by remember(item.stableKey) {
                            mutableStateOf<List<String>>(emptyList())
                        }
                        val automaticPreview = remember(context) {
                            val activityManager =
                                context.getSystemService(android.app.ActivityManager::class.java)
                            DeviceProfile.supportsAutomaticTrailerPreview(
                                memoryClassMb = activityManager?.memoryClass ?: 0,
                                isLowRamDevice = activityManager?.isLowRamDevice ?: true,
                            )
                        }
                        LaunchedEffect(item.stableKey, automaticPreview) {
                            previewUrls = emptyList()
                            if (automaticPreview) {
                                delay(2_500)
                                previewUrls = model.prefetchTrailer(item)
                            }
                        }
                        TelevisionDetail(
                            item = item,
                            progressItem = state.selectedProgressItem,
                            overview = state.detailOverview,
                            episodes = state.episodes,
                            selectedSeason = state.selectedSeason,
                            loading = state.loading,
                            onBack = { model.back() },
                            onSeason = model::selectSeason,
                            onPlay = { target, resume -> model.play(target, resume, play) },
                            onDownload = { target -> model.prepareDownload(target, download) },
                            onTrailer = { target ->
                                model.openTrailer(target) { urls ->
                                    context.startActivity(
                                        Intent(context, TrailerActivity::class.java).apply {
                                            putExtra(
                                                TrailerActivity.EXTRA_URLS,
                                                JSONArray(urls).toString(),
                                            )
                                            putExtra(TrailerActivity.EXTRA_TITLE, target.title)
                                        },
                                    )
                                }
                            },
                            onRemoveProgress = model::removeProgress,
                            previewUrls = previewUrls,
                            onPreviewUnavailable = { previewUrls = emptyList() },
                        )
                    }
                    }
                }
                TelevisionBrandHeader(
                    Modifier.align(Alignment.TopEnd).zIndex(20f),
                )
            }
        }
    }
}

@Composable
private fun TelevisionBrandHeader(
    modifier: Modifier = Modifier,
) {
    val dimensions = LocalPrippiDimensions.current
    Box(
        modifier.padding(
            end = dimensions.screenHorizontalPadding,
            top = dimensions.screenVerticalPadding,
        ).background(
            Color(0x99060A0F),
            RoundedCornerShape((10f * dimensions.uiScale).dp),
        ).padding(
            horizontal = (12f * dimensions.uiScale).dp,
            vertical = (7f * dimensions.uiScale).dp,
        ),
    ) {
        Image(
            painter = painterResource(R.drawable.prippistream_logo_banner),
            contentDescription = "PrippiStream",
            contentScale = ContentScale.Fit,
            modifier = Modifier
                .width((168f * dimensions.uiScale).dp)
                .height((35f * dimensions.uiScale).dp),
        )
    }
}

@Composable
private fun TelevisionRail(
    selected: AppPage,
    searchSelected: Boolean,
    onHome: () -> Unit,
    onSearch: () -> Unit,
    onBrowse: () -> Unit,
    onLive: () -> Unit,
    onDownloads: () -> Unit,
    onSettings: () -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    val homeFocus = remember { FocusRequester() }
    val searchFocus = remember { FocusRequester() }
    val browseFocus = remember { FocusRequester() }
    val liveFocus = remember { FocusRequester() }
    val downloadsFocus = remember { FocusRequester() }
    val settingsFocus = remember { FocusRequester() }
    Column(
        Modifier.width(dimensions.railWidth).fillMaxSize()
            .focusGroup()
            .background(Color(0xF20B1119))
            .padding(vertical = (12f * scale).dp, horizontal = (12f * scale).dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy((9f * scale).dp),
    ) {
        Box(
            Modifier.size((44f * scale).dp)
                .background(
                    Color(0xFF183B58),
                    RoundedCornerShape((14f * scale).dp),
                ),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Default.PlayArrow,
                contentDescription = "PrippiStream",
                modifier = Modifier.size((31f * scale).dp),
                tint = Color.White,
            )
        }
        Spacer(Modifier.height((4f * scale).dp))
        TelevisionRailButton(Icons.Default.Home, "Home", selected == AppPage.HOME, onHome, Modifier.focusRequester(homeFocus).focusProperties { down = searchFocus })
        TelevisionRailButton(Icons.Default.Search, "Cerca", searchSelected, onSearch, Modifier.focusRequester(searchFocus).focusProperties { up = homeFocus; down = browseFocus })
        TelevisionRailButton(Icons.Default.List, "Sfoglia", selected == AppPage.CHANNELS, onBrowse, Modifier.focusRequester(browseFocus).focusProperties { up = searchFocus; down = liveFocus })
        TelevisionRailButton(Icons.Default.LiveTv, "Live", selected == AppPage.LIVE, onLive, Modifier.focusRequester(liveFocus).focusProperties { up = browseFocus; down = downloadsFocus })
        TelevisionRailButton(
            Icons.Default.Download,
            "Download",
            selected == AppPage.DOWNLOADS,
            onDownloads,
            Modifier.focusRequester(downloadsFocus).focusProperties { up = liveFocus; down = settingsFocus },
        )
        Spacer(Modifier.weight(1f))
        TelevisionRailButton(
            Icons.Default.Settings,
            "Impostazioni",
            selected == AppPage.SETTINGS,
            onSettings,
            showLabel = false,
            modifier = Modifier.focusRequester(settingsFocus).focusProperties { up = downloadsFocus },
        )
    }
}

@Composable
private fun TelevisionRailButton(
    icon: ImageVector,
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    showLabel: Boolean = true,
) {
    var focused by remember { mutableStateOf(false) }
    val scale = LocalPrippiDimensions.current.uiScale
    Column(
        modifier.width((80f * scale).dp)
            .onFocusChanged { focused = it.isFocused }
            .border(
                if (focused) (4f * scale).dp else 0.dp,
                if (focused) TvFocusBorder else Color.Transparent,
                RoundedCornerShape((14f * scale).dp),
            )
            .background(
                when {
                    focused -> TvFocusBackground
                    selected -> Color(0xFF183B58)
                    else -> Color.Transparent
                },
                RoundedCornerShape((14f * scale).dp),
            )
            .clickable(onClick = onClick)
            .padding(
                vertical = (if (showLabel) 7f * scale else 11f * scale).dp,
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            icon,
            contentDescription = label,
            modifier = Modifier.size((27f * scale).dp),
        )
        if (showLabel) {
            Spacer(Modifier.height((2f * scale).dp))
            Text(label, style = MaterialTheme.typography.labelSmall, maxLines = 1)
        }
    }
}

@Composable
private fun TelevisionHome(
    rows: List<HomeRow>,
    loading: Boolean,
    onClick: (ContentItem) -> Unit,
    onPlay: (ContentItem) -> Unit,
    onRetry: () -> Unit,
    focusedRowId: String,
    focusedItemKey: String,
    focusRecoveryNonce: Int,
    onFocused: (String, String) -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    if (rows.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            if (loading) CircularProgressIndicator()
            else TextButton(onClick = onRetry) { Text("Riprova") }
        }
        return
    }
    val initialHero = rows.firstNotNullOfOrNull { it.items.firstOrNull() }
    var hero by remember { mutableStateOf<ContentItem?>(initialHero) }
    var pendingHero by remember { mutableStateOf<ContentItem?>(initialHero) }
    LaunchedEffect(rows) {
        val currentKey = hero?.stableKey
        hero = rows.asSequence()
            .flatMap { it.items.asSequence() }
            .firstOrNull { it.stableKey == currentKey }
            ?: initialHero
        if (pendingHero == null) pendingHero = hero
    }
    LaunchedEffect(pendingHero?.stableKey) {
        val candidate = pendingHero ?: return@LaunchedEffect
        if (dimensions.heroDebounceMillis > 0) {
            delay(dimensions.heroDebounceMillis)
        }
        hero = candidate
    }
    // A FocusRequester must not move between recycled lazy-list nodes while the
    // user is navigating. Freeze the restore target for this recovery cycle.
    val restoreRowId = remember(focusRecoveryNonce) { focusedRowId }
    val restoreItemKey = remember(focusRecoveryNonce) { focusedItemKey }
    val targetRow = rows.indexOfFirst { it.id == restoreRowId }.takeIf { it >= 0 } ?: 0
    val targetItem = rows.getOrNull(targetRow)?.items?.indexOfFirst {
        it.stableKey == restoreItemKey
    }?.takeIf { it >= 0 } ?: 0
    val firstFocus = remember(focusRecoveryNonce) { FocusRequester() }
    val homeListState = rememberLazyListState()
    val homeScrollScope = rememberCoroutineScope()
    val rowTopMarginPx = with(LocalDensity.current) {
        (18f * dimensions.uiScale).dp.roundToPx()
    }
    var lastFocusedRowIndex by remember(focusRecoveryNonce) {
        mutableIntStateOf(targetRow)
    }
    LaunchedEffect(rows.isNotEmpty(), focusRecoveryNonce) {
        if (restoreItemKey.isNotBlank()) {
            homeListState.scrollToItem(targetRow)
            delay(80)
            runCatching { firstFocus.requestFocus() }
        }
    }
    Column(Modifier.fillMaxSize()) {
        // The hero is deliberately outside the vertical lazy list: it remains
        // visible and cannot be recycled together with focusable row nodes.
        hero?.let {
            TelevisionHero(
                item = it,
                onPlay = { onPlay(it) },
                onDetails = { onClick(it) },
            )
        }
        LazyColumn(
            Modifier.fillMaxWidth().weight(1f).focusGroup(),
            state = homeListState,
            contentPadding = PaddingValues(
                top = (10f * dimensions.uiScale).dp,
                bottom = (76f * dimensions.uiScale).dp,
            ),
            verticalArrangement = Arrangement.spacedBy(
                dimensions.rowSpacing + (8f * dimensions.uiScale).dp,
            ),
        ) {
            itemsIndexed(
                items = rows,
                key = { _, row -> row.id },
                // Rows own independent nested LazyRows and focus state. Giving
                // each one a distinct type prevents unsafe node reuse.
                contentType = { _, row -> "home-row:${row.id}" },
            ) { rowIndex, row ->
                if (row.items.isNotEmpty()) {
                    Column(
                        modifier = Modifier.padding(vertical = (4f * dimensions.uiScale).dp),
                        verticalArrangement =
                            Arrangement.spacedBy((10f * dimensions.uiScale).dp),
                    ) {
                        Text(
                            row.title.replaceFirstChar { it.uppercase() },
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(
                                horizontal = dimensions.screenHorizontalPadding,
                            ),
                        )
                        LazyRow(
                            modifier = Modifier.focusGroup(),
                            contentPadding = PaddingValues(
                                horizontal = dimensions.screenHorizontalPadding,
                                vertical = (14f * dimensions.uiScale).dp,
                            ),
                            horizontalArrangement = Arrangement.spacedBy(dimensions.cardSpacing),
                        ) {
                            itemsIndexed(
                                items = row.items,
                                key = { index, item -> "${item.stableKey}:$index" },
                                contentType = { _, item ->
                                    if (item.isLive) "live-card" else "media-card"
                                },
                            ) { itemIndex, item ->
                                TelevisionMediaCard(
                                    item = item,
                                    modifier = if (
                                        rowIndex == targetRow &&
                                        itemIndex == targetItem
                                    ) Modifier.focusRequester(firstFocus) else Modifier,
                                    onFocused = {
                                        pendingHero = item
                                        onFocused(row.id, item.stableKey)
                                        if (rowIndex != lastFocusedRowIndex) {
                                            lastFocusedRowIndex = rowIndex
                                            homeScrollScope.launch {
                                                delay(35)
                                                homeListState.animateScrollToItem(
                                                    rowIndex,
                                                    scrollOffset = -rowTopMarginPx,
                                                )
                                            }
                                        }
                                    },
                                    onClick = { onClick(item) },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun TelevisionHero(
    item: ContentItem,
    onPlay: () -> Unit,
    onDetails: () -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    Box(
        Modifier.fillMaxWidth().height(dimensions.heroHeight)
            .background(Color(0xFF0A1017)),
    ) {
        AppImage(
            model = item.backdropUrl.ifBlank { item.posterUrl },
            fallbackModel = item.posterUrl,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(),
        )
        Box(
            Modifier.fillMaxSize().background(
                Brush.horizontalGradient(
                    listOf(
                        Color(0xFF060A0F),
                        Color(0xE6060A0F),
                        Color(0x45060A0F),
                        Color(0xB0060A0F),
                    ),
                ),
            ),
        )
        Column(
            Modifier.align(Alignment.CenterStart).width((560f * scale).dp)
                .padding(
                    start = dimensions.screenHorizontalPadding,
                    top = (12f * scale).dp,
                    bottom = (10f * scale).dp,
                ),
            verticalArrangement = Arrangement.spacedBy((7f * scale).dp),
        ) {
            Text(
                item.title,
                style = if (item.title.length > 24) {
                    MaterialTheme.typography.headlineMedium
                } else {
                    MaterialTheme.typography.headlineLarge
                },
                fontWeight = FontWeight.Black,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            val meta = listOfNotNull(
                item.year.takeIf { it > 0 }?.toString(),
                item.certification.takeIf { it.isNotBlank() },
                item.runtimeMinutes.takeIf { it > 0 }?.let(::formatRuntimeMinutes),
                item.genres.takeIf { it.isNotBlank() },
                item.rating.takeIf { it > 0 }?.let {
                    "★ ${String.format(Locale.US, "%.1f", it)}"
                },
            ).joinToString("  ·  ")
            if (meta.isNotBlank()) {
                Text(
                    meta,
                    color = Color(0xFFBBD7EF),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                item.plot.ifBlank { "Apri la scheda per scoprire tutti i dettagli." },
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyMedium,
                color = Color(0xFFE0E7EF),
            )
            Row(horizontalArrangement = Arrangement.spacedBy((10f * scale).dp)) {
                if (!item.isSeries) {
                    Button(
                        onClick = onPlay,
                        modifier = Modifier
                            .tvFocusableFrame(true, RoundedCornerShape((24f * scale).dp))
                            .height((48f * scale).dp),
                    ) {
                        Icon(Icons.Default.PlayArrow, contentDescription = null)
                        Spacer(Modifier.width((7f * scale).dp))
                        Text("Riproduci")
                    }
                }
                Button(
                    onClick = onDetails,
                    modifier = Modifier
                        .tvFocusableFrame(true, RoundedCornerShape((24f * scale).dp))
                        .height((48f * scale).dp),
                ) {
                    Icon(Icons.Default.Info, contentDescription = null)
                    Spacer(Modifier.width((7f * scale).dp))
                    Text("Dettagli")
                }
            }
        }
    }
}

@Composable
private fun TelevisionMediaCard(
    item: ContentItem,
    modifier: Modifier = Modifier,
    onFocused: () -> Unit,
    onClick: () -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    var focused by remember { mutableStateOf(false) }
    Column(
        modifier.width(dimensions.mediaCardWidth)
            .onFocusChanged {
                focused = it.isFocused
                if (it.isFocused) onFocused()
            }
            .scale(if (focused) dimensions.focusScale else 1f)
            .zIndex(if (focused) 2f else 0f)
            .border(
                if (focused) (4f * scale).dp else 0.dp,
                if (focused) TvFocusBorder else Color.Transparent,
                RoundedCornerShape((12f * scale).dp),
            )
            .background(Color(0xFF111B25), RoundedCornerShape((12f * scale).dp))
            .clickable(onClick = onClick),
    ) {
        Box {
            AppImage(
                model = item.backdropUrl.ifBlank { item.posterUrl },
                fallbackModel = item.posterUrl,
                contentDescription = item.title,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxWidth().height(dimensions.mediaCardImageHeight)
                    .clip(
                        RoundedCornerShape(
                            topStart = (12f * scale).dp,
                            topEnd = (12f * scale).dp,
                        ),
                    ),
            )
            if (item.progressFraction > 0f) {
                LinearProgressIndicator(
                    progress = { item.progressFraction },
                    modifier = Modifier.fillMaxWidth().align(Alignment.BottomCenter),
                )
            }
        }
        Column(
            Modifier.padding(
                horizontal = (12f * scale).dp,
                vertical = (9f * scale).dp,
            ),
            verticalArrangement = Arrangement.spacedBy((2f * scale).dp),
        ) {
            Text(
                item.title,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            val metadata = listOfNotNull(
                item.year.takeIf { it > 0 }?.toString(),
                item.mediaType.takeIf { it.isNotBlank() }?.replaceFirstChar {
                    it.uppercase()
                },
                item.runtimeMinutes.takeIf { it > 0 }?.let(::formatRuntimeMinutes),
                item.rating.takeIf { it > 0 }?.let {
                    "★ ${String.format(Locale.US, "%.1f", it)}"
                },
            ).joinToString(" · ")
            if (metadata.isNotBlank()) {
                Text(
                    metadata,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFFBBD0E2),
                )
            }
        }
    }
}

@Composable
private fun TelevisionLive(
    rows: List<HomeRow>,
    loading: Boolean,
    onLive: (ContentItem) -> Unit,
    focusedRowId: String,
    focusedItemKey: String,
    focusRecoveryNonce: Int,
    onFocused: (String, String) -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    if (rows.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Row(horizontalArrangement = Arrangement.spacedBy((14f * scale).dp)) {
                CircularProgressIndicator(Modifier.size((30f * scale).dp))
                Text("Verifica dei canali in corso…", style = MaterialTheme.typography.titleLarge)
            }
        }
        return
    }
    var highlighted by remember(rows) { mutableStateOf(rows.first().items.firstOrNull()) }
    val targetRow = rows.indexOfFirst { it.id == focusedRowId }.takeIf { it >= 0 } ?: 0
    val targetItem = rows.getOrNull(targetRow)?.items?.indexOfFirst {
        it.stableKey == focusedItemKey
    }?.takeIf { it >= 0 } ?: 0
    val restore = remember(focusRecoveryNonce) { FocusRequester() }
    val liveListState = rememberLazyListState()
    LaunchedEffect(rows.isNotEmpty(), focusRecoveryNonce, focusedItemKey) {
        if (focusedItemKey.isNotBlank()) {
            liveListState.scrollToItem(targetRow + 1)
            delay(80)
            runCatching { restore.requestFocus() }
        }
    }
    LazyColumn(
        Modifier.fillMaxSize().focusGroup(),
        state = liveListState,
        contentPadding = PaddingValues(
            top = (26f * scale).dp,
            bottom = (40f * scale).dp,
        ),
        verticalArrangement = Arrangement.spacedBy((24f * scale).dp),
    ) {
        item(key = "live-title") {
            Row(
                Modifier.fillMaxWidth().padding(
                    horizontal = dimensions.screenHorizontalPadding,
                ),
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column {
                    Text("Live TV", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Black)
                    Text(
                        highlighted?.plot?.lineSequence()?.firstOrNull()
                            ?: "Canali verificati nella sessione",
                        color = Color(0xFFB9C9DA),
                        style = MaterialTheme.typography.titleMedium,
                    )
                }
                if (loading) Text("Aggiornamento…", color = Color(0xFF86C9FF))
            }
        }
        itemsIndexed(rows, key = { _, row -> row.id }) { rowIndex, row ->
            Column(verticalArrangement = Arrangement.spacedBy((10f * scale).dp)) {
                Text(
                    row.title,
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(
                        horizontal = dimensions.screenHorizontalPadding,
                    ),
                )
                LazyRow(
                    modifier = Modifier.focusGroup(),
                    contentPadding = PaddingValues(
                        horizontal = dimensions.screenHorizontalPadding,
                        vertical = (8f * scale).dp,
                    ),
                    horizontalArrangement =
                        Arrangement.spacedBy(dimensions.cardSpacing),
                ) {
                    itemsIndexed(
                        row.items,
                        key = { index, item -> "${item.stableKey}:$index" },
                    ) { itemIndex, item ->
                        TelevisionLiveCard(
                            item = item,
                            modifier = if (
                                rowIndex == targetRow && itemIndex == targetItem
                            ) Modifier.focusRequester(restore) else Modifier,
                            onFocused = {
                                highlighted = item
                                onFocused(row.id, item.stableKey)
                            },
                            onClick = { onLive(item) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TelevisionLiveCard(
    item: ContentItem,
    modifier: Modifier = Modifier,
    onFocused: () -> Unit,
    onClick: () -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    var focused by remember { mutableStateOf(false) }
    Column(
        modifier.width((252f * scale).dp)
            .onFocusChanged {
                focused = it.isFocused
                if (it.isFocused) onFocused()
            }
            .scale(if (focused) dimensions.focusScale else 1f)
            .zIndex(if (focused) 2f else 0f)
            .border(
                if (focused) (4f * scale).dp else 0.dp,
                if (focused) TvFocusBorder else Color.Transparent,
                RoundedCornerShape((12f * scale).dp),
            )
            .background(Color(0xFF111B25), RoundedCornerShape((12f * scale).dp))
            .clickable(onClick = onClick),
    ) {
        AppImage(
            model = item.posterUrl,
            fallbackModel = item.backdropUrl.takeIf { it.isNotBlank() },
            contentDescription = item.title,
            contentScale = ContentScale.Fit,
            modifier = Modifier.fillMaxWidth().height((112f * scale).dp)
                .background(Color(0xFF080C11))
                .clip(
                    RoundedCornerShape(
                        topStart = (12f * scale).dp,
                        topEnd = (12f * scale).dp,
                    ),
                ),
        )
        Text(
            item.title,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(
                start = (12f * scale).dp,
                end = (12f * scale).dp,
                top = (9f * scale).dp,
            ),
        )
        Text(
            item.plot.lineSequence().drop(1).firstOrNull()
                ?: item.plot.lineSequence().firstOrNull()
                ?: "Diretta",
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            color = Color(0xFFB9C9DA),
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(
                start = (12f * scale).dp,
                end = (12f * scale).dp,
                bottom = (10f * scale).dp,
            ),
        )
    }
}

@Composable
private fun TelevisionSearchLanding() {
    val scale = LocalPrippiDimensions.current.uiScale
    Box(
        Modifier.fillMaxSize()
            .background(
                Brush.verticalGradient(
                    listOf(Color(0xFF101B27), Color(0xFF060A0F)),
                ),
            ),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(
                Icons.Default.Search,
                contentDescription = null,
                tint = Color(0xFF86C9FF),
                modifier = Modifier.size((72f * scale).dp),
            )
            Spacer(Modifier.height((18f * scale).dp))
            Text(
                "Cosa vuoi guardare?",
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Black,
            )
            Text(
                "Cerca film, serie TV e anime in un unico catalogo.",
                color = Color(0xFFB9C9DA),
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(top = (8f * scale).dp),
            )
        }
    }
}

@Composable
private fun TelevisionSearchResults(
    items: List<ContentItem>,
    filter: String,
    loading: Boolean,
    onFilter: (String) -> Unit,
    onClick: (ContentItem) -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    val choices = listOf(
        "all" to "Tutti",
        "film" to "Film",
        "serie" to "Serie",
        "anime" to "Anime",
    )
    val shown = if (filter == "all") items else items.filter { it.searchType == filter }
    val firstResultFocus = remember(shown) { FocusRequester() }
    LaunchedEffect(shown) {
        if (shown.isNotEmpty()) {
            delay(120)
            runCatching { firstResultFocus.requestFocus() }
        }
    }
    Column(Modifier.fillMaxSize().focusGroup()) {
        Row(
            Modifier.fillMaxWidth().padding(
                start = dimensions.screenHorizontalPadding,
                end = dimensions.screenHorizontalPadding,
                top = (18f * scale).dp,
            ),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "Risultati",
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Black,
            )
            Text(
                "${shown.size}",
                color = Color(0xFF86C9FF),
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(start = (14f * scale).dp),
            )
        }
        LazyRow(
            modifier = Modifier.focusGroup(),
            contentPadding = PaddingValues(
                horizontal = dimensions.screenHorizontalPadding,
                vertical = (12f * scale).dp,
            ),
            horizontalArrangement = Arrangement.spacedBy((12f * scale).dp),
        ) {
            items(choices, key = { it.first }) { (value, label) ->
                TelevisionFilterButton(
                    label = label,
                    selected = filter == value,
                    onClick = { onFilter(value) },
                )
            }
        }
        if (shown.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                if (loading) CircularProgressIndicator()
                else Text("Nessun risultato per questa categoria")
            }
        } else {
            LazyVerticalGrid(
                columns = GridCells.Adaptive((190f * scale).dp),
                modifier = Modifier.weight(1f).fillMaxWidth().focusGroup(),
                contentPadding = PaddingValues(
                    start = dimensions.screenHorizontalPadding,
                    end = dimensions.screenHorizontalPadding,
                    top = (6f * scale).dp,
                    bottom = (36f * scale).dp,
                ),
                verticalArrangement = Arrangement.spacedBy((18f * scale).dp),
                horizontalArrangement = Arrangement.spacedBy((18f * scale).dp),
            ) {
                gridItemsIndexed(
                    items = shown,
                    key = { index, item -> "search:$index:${item.stableKey}" },
                    contentType = { _, _ -> "search-poster" },
                ) { index, item ->
                    TelevisionPosterCard(
                        item,
                        modifier = if (index == 0) Modifier.focusRequester(firstResultFocus) else Modifier,
                        onClick = { onClick(item) },
                    )
                }
            }
        }
    }
}

@Composable
private fun TelevisionBrowseLanding(
    macros: List<ContentItem>,
    loading: Boolean,
    onMacro: (ContentItem) -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    Column(Modifier.fillMaxSize().focusGroup()) {
        Text(
            "Sfoglia",
            style = MaterialTheme.typography.headlineLarge,
            fontWeight = FontWeight.Black,
            modifier = Modifier.padding(
                horizontal = dimensions.screenHorizontalPadding,
                vertical = (28f * dimensions.uiScale).dp,
            ),
        )
        TelevisionCatalog(macros, loading, onMacro)
    }
}

@Composable
private fun TelevisionBrowseCatalog(
    macros: List<ContentItem>,
    items: List<ContentItem>,
    selectedFilterKey: String,
    loading: Boolean,
    onClick: (ContentItem) -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    val filters = items.filter {
        it.posterUrl.isBlank() && it.backdropUrl.isBlank()
    }.distinctBy { "${it.action}:${it.title}" }
    val content = items.filter {
        it.posterUrl.isNotBlank() || it.backdropUrl.isNotBlank()
    }
    val activeMacro = items.firstOrNull()
        ?.toJson()
        ?.optString("_app_macro")
        .orEmpty()
    val firstBrowseFocus = remember(content) { FocusRequester() }
    LaunchedEffect(content) {
        if (content.isNotEmpty()) {
            delay(120)
            runCatching { firstBrowseFocus.requestFocus() }
        }
    }

    Column(Modifier.fillMaxSize()) {
        Text(
            "Sfoglia",
            style = MaterialTheme.typography.headlineLarge,
            fontWeight = FontWeight.Black,
            modifier = Modifier.padding(
                start = dimensions.screenHorizontalPadding,
                end = dimensions.screenHorizontalPadding,
                top = (20f * scale).dp,
            ),
        )
        LazyRow(
            modifier = Modifier.focusGroup(),
            contentPadding = PaddingValues(
                horizontal = dimensions.screenHorizontalPadding,
                vertical = (10f * scale).dp,
            ),
            horizontalArrangement = Arrangement.spacedBy((10f * scale).dp),
        ) {
            itemsIndexed(
                items = macros,
                key = { index, macro -> "browse-macro:$index:${macro.stableKey}" },
                contentType = { _, _ -> "browse-macro" },
            ) { _, macro ->
                val macroId = macro.toJson().optString("_app_macro")
                TelevisionFilterButton(
                    label = macro.title,
                    selected = macroId.isNotBlank() && macroId == activeMacro,
                    onClick = { onClick(macro) },
                )
            }
        }
        if (filters.isNotEmpty()) {
            LazyRow(
                modifier = Modifier.focusGroup(),
                contentPadding = PaddingValues(
                    horizontal = dimensions.screenHorizontalPadding,
                    vertical = (4f * scale).dp,
                ),
                horizontalArrangement = Arrangement.spacedBy((8f * scale).dp),
            ) {
                items(filters, key = { "filter:${it.action}:${it.title}" }) { filter ->
                    TelevisionFilterButton(
                        label = filter.title,
                        selected = filter.stableKey == selectedFilterKey,
                        compact = true,
                        onClick = { onClick(filter) },
                    )
                }
            }
        }
        if (content.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                if (loading) CircularProgressIndicator()
                else Text("Nessun contenuto disponibile")
            }
        } else {
            LazyVerticalGrid(
                columns = GridCells.Adaptive((190f * scale).dp),
                modifier = Modifier.weight(1f).fillMaxWidth().focusGroup(),
                contentPadding = PaddingValues(
                    start = dimensions.screenHorizontalPadding,
                    end = dimensions.screenHorizontalPadding,
                    top = (10f * scale).dp,
                    bottom = (36f * scale).dp,
                ),
                verticalArrangement = Arrangement.spacedBy((18f * scale).dp),
                horizontalArrangement = Arrangement.spacedBy((18f * scale).dp),
            ) {
                gridItemsIndexed(
                    items = content,
                    key = { index, item -> "browse:$index:${item.stableKey}" },
                    contentType = { _, _ -> "browse-poster" },
                ) { index, item ->
                    TelevisionPosterCard(
                        item,
                        modifier = if (index == 0) Modifier.focusRequester(firstBrowseFocus) else Modifier,
                        onClick = { onClick(item) },
                    )
                }
            }
        }
    }
}

@Composable
private fun TelevisionFilterButton(
    label: String,
    selected: Boolean,
    compact: Boolean = false,
    onClick: () -> Unit,
) {
    val scale = LocalPrippiDimensions.current.uiScale
    var focused by remember { mutableStateOf(false) }
    Box(
        Modifier.height((if (compact) 40f * scale else 46f * scale).dp)
            .onFocusChanged { focused = it.isFocused }
            .border(
                (if (focused) 4f * scale else 1f * scale).dp,
                if (focused) TvFocusBorder else Color(0xFF365069),
                RoundedCornerShape((20f * scale).dp),
            )
            .background(
                when {
                    focused -> TvFocusBackground
                    selected -> Color(0xFF1D527D)
                    else -> Color(0xFF111B25)
                },
                RoundedCornerShape((20f * scale).dp),
            )
            .clickable(onClick = onClick)
            .padding(
                horizontal = (if (compact) 14f * scale else 18f * scale).dp,
            ),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            style = if (compact) {
                MaterialTheme.typography.labelMedium
            } else {
                MaterialTheme.typography.labelLarge
            },
            maxLines = 1,
        )
    }
}

@Composable
private fun TelevisionPosterCard(
    item: ContentItem,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    var focused by remember { mutableStateOf(false) }
    Column(
        modifier.fillMaxWidth()
            .onFocusChanged { focused = it.isFocused }
            .scale(if (focused) dimensions.focusScale else 1f)
            .zIndex(if (focused) 2f else 0f)
            .border(
                if (focused) (4f * scale).dp else 0.dp,
                if (focused) TvFocusBorder else Color.Transparent,
                RoundedCornerShape((12f * scale).dp),
            )
            .background(Color(0xFF111B25), RoundedCornerShape((12f * scale).dp))
            .clickable(onClick = onClick),
    ) {
        AppImage(
            model = item.posterUrl.ifBlank { item.backdropUrl },
            fallbackModel = item.backdropUrl,
            contentDescription = item.title,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxWidth().aspectRatio(2f / 3f)
                .clip(
                    RoundedCornerShape(
                        topStart = (12f * scale).dp,
                        topEnd = (12f * scale).dp,
                    ),
                ),
        )
        Text(
            item.title,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(
                start = (9f * scale).dp,
                end = (9f * scale).dp,
                top = (8f * scale).dp,
            ).height((52f * scale).dp),
        )
        Text(
            posterMetadata(item),
            style = MaterialTheme.typography.labelSmall,
            color = Color(0xFFB8C7D7),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(
                start = (9f * scale).dp,
                end = (9f * scale).dp,
                bottom = (9f * scale).dp,
            ),
        )
    }
}

@Composable
private fun TelevisionCatalog(
    items: List<ContentItem>,
    loading: Boolean,
    onClick: (ContentItem) -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    if (items.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            if (loading) CircularProgressIndicator() else Text("Nessun contenuto disponibile")
        }
        return
    }
    val firstCatalogFocus = remember(items) { FocusRequester() }
    LaunchedEffect(items) {
        delay(120)
        runCatching { firstCatalogFocus.requestFocus() }
    }
    LazyColumn(
        Modifier.fillMaxSize().focusGroup(),
        contentPadding = PaddingValues(
            horizontal = dimensions.screenHorizontalPadding,
            vertical = (12f * scale).dp,
        ),
        verticalArrangement = Arrangement.spacedBy((18f * scale).dp),
    ) {
        itemsIndexed(items.chunked(4), key = { index, _ -> "catalog-row:$index" }) { rowIndex, row ->
            Row(
                Modifier.focusGroup(),
                horizontalArrangement = Arrangement.spacedBy((18f * scale).dp),
            ) {
                row.forEachIndexed { columnIndex, item ->
                    val itemIndex = rowIndex * 4 + columnIndex
                    if (item.posterUrl.isBlank() && item.backdropUrl.isBlank()) {
                        TelevisionActionCard(
                            item,
                            modifier = if (itemIndex == 0) Modifier.focusRequester(firstCatalogFocus) else Modifier,
                            onClick = { onClick(item) },
                        )
                    } else {
                        TelevisionMediaCard(
                            item = item,
                            modifier = if (itemIndex == 0) Modifier.focusRequester(firstCatalogFocus) else Modifier,
                            onFocused = {},
                            onClick = { onClick(item) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TelevisionActionCard(
    item: ContentItem,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    var focused by remember { mutableStateOf(false) }
    Column(
        modifier.width((230f * scale).dp).height((170f * scale).dp)
            .onFocusChanged { focused = it.isFocused }
            .scale(if (focused) dimensions.focusScale else 1f)
            .zIndex(if (focused) 2f else 0f)
            .border(
                (if (focused) 4f * scale else 1f * scale).dp,
                if (focused) TvFocusBorder else Color(0xFF32475B),
                RoundedCornerShape((14f * scale).dp),
            )
            .background(
                if (focused) TvFocusBackground else Color(0xFF111B25),
                RoundedCornerShape((14f * scale).dp),
            )
            .clickable(onClick = onClick)
            .padding((18f * scale).dp),
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        Icon(
            Icons.Default.List,
            contentDescription = null,
            modifier = Modifier.size((34f * scale).dp),
        )
        Text(
            item.title,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
            maxLines = 3,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun TelevisionDetail(
    item: ContentItem,
    progressItem: ContentItem?,
    overview: String,
    episodes: List<ContentItem>,
    selectedSeason: Int,
    loading: Boolean,
    onBack: () -> Unit,
    onSeason: (Int) -> Unit,
    onPlay: (ContentItem, Boolean) -> Unit,
    onDownload: (ContentItem) -> Unit,
    onTrailer: (ContentItem) -> Unit,
    onRemoveProgress: (ContentItem) -> Unit,
    previewUrls: List<String>,
    onPreviewUnavailable: () -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    val primaryActionFocus = remember(item.stableKey) { FocusRequester() }
    LaunchedEffect(item.stableKey) {
        delay(160)
        runCatching { primaryActionFocus.requestFocus() }
    }
    LazyColumn(
        Modifier.fillMaxSize().focusGroup(),
        contentPadding = PaddingValues(bottom = (44f * scale).dp),
        verticalArrangement = Arrangement.spacedBy((20f * scale).dp),
    ) {
        item(key = "detail-hero") {
            Box(Modifier.fillMaxWidth().height((390f * scale).dp)) {
                AppImage(
                    model = item.backdropUrl.ifBlank { item.posterUrl },
                    fallbackModel = item.posterUrl,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                )
                if (previewUrls.isNotEmpty()) {
                    Box(
                        Modifier.align(Alignment.CenterEnd)
                            .fillMaxHeight()
                            .fillMaxWidth(0.62f),
                    ) {
                        TelevisionTrailerPreview(
                            urls = previewUrls,
                            onUnavailable = onPreviewUnavailable,
                            modifier = Modifier.fillMaxSize(),
                        )
                        Text(
                            "ANTEPRIMA TRAILER · AUDIO DISATTIVATO",
                            color = Color(0xFFC4D4E4),
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.align(Alignment.BottomEnd)
                                .padding(
                                    end = (28f * scale).dp,
                                    bottom = (18f * scale).dp,
                                )
                                .background(
                                    Color(0xB3060A0F),
                                    RoundedCornerShape((6f * scale).dp),
                                )
                                .padding(
                                    horizontal = (10f * scale).dp,
                                    vertical = (6f * scale).dp,
                                ),
                        )
                    }
                }
                Box(
                    Modifier.fillMaxSize().background(
                        Brush.horizontalGradient(
                            listOf(Color(0xFF060A0F), Color(0xE6060A0F), Color(0x30060A0F)),
                        ),
                    ),
                )
                Column(
                    Modifier.align(Alignment.CenterStart)
                        .width((650f * scale).dp)
                        .padding(start = dimensions.screenHorizontalPadding),
                    verticalArrangement = Arrangement.spacedBy((12f * scale).dp),
                ) {
                    Text(
                        item.title,
                        style = MaterialTheme.typography.displaySmall,
                        fontWeight = FontWeight.Black,
                        maxLines = 2,
                    )
                    Text(
                        listOfNotNull(
                            item.year.takeIf { it > 0 }?.toString(),
                            item.certification.takeIf { it.isNotBlank() },
                            item.runtimeMinutes.takeIf { it > 0 }?.let(::formatRuntimeMinutes),
                            item.genres.takeIf { it.isNotBlank() },
                            item.rating.takeIf { it > 0 }?.let {
                                "★ ${String.format(Locale.US, "%.1f", it)}"
                            },
                        ).joinToString("  ·  "),
                        color = Color(0xFFBBD7EF),
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        overview.ifBlank { item.plot },
                        maxLines = 5,
                        overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.bodyLarge,
                        color = Color(0xFFE4EBF3),
                    )
                    Row(
                        Modifier.focusGroup(),
                        horizontalArrangement = Arrangement.spacedBy((12f * scale).dp),
                    ) {
                        TelevisionDetailActionButton(
                            label = continueWatchingActionLabel(item, progressItem),
                            icon = Icons.Default.PlayArrow,
                            primary = true,
                            modifier = Modifier.focusRequester(primaryActionFocus),
                            onClick = { onPlay(item, progressItem != null) },
                        )
                        TelevisionDetailActionButton(
                            label = "Trailer",
                            icon = Icons.Default.PlayArrow,
                            onClick = { onTrailer(item) },
                        )
                        TelevisionDetailActionButton(
                            label = "Scarica",
                            icon = Icons.Default.Download,
                            onClick = { onDownload(item) },
                        )
                        if (progressItem != null) {
                            TelevisionDetailActionButton(
                                label = "Rimuovi da CW",
                                icon = Icons.Default.DeleteOutline,
                                onClick = { onRemoveProgress(item) },
                            )
                        }
                        TelevisionDetailActionButton(
                            label = "Indietro",
                            icon = Icons.AutoMirrored.Filled.ArrowBack,
                            onClick = onBack,
                        )
                    }
                }
            }
        }
        if (item.hasEditorialCredits()) {
            item(key = "detail-credits") {
                EditorialCreditsPanel(
                    item = item,
                    modifier = Modifier.fillMaxWidth().padding(
                        horizontal = dimensions.screenHorizontalPadding,
                    ),
                    television = true,
                )
            }
        }
        if (loading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        if (episodes.isNotEmpty()) {
            item(key = "seasons") {
                val seasons = episodes.map { it.season }.filter { it > 0 }.distinct().sorted()
                LazyRow(
                    contentPadding = PaddingValues(
                        horizontal = dimensions.screenHorizontalPadding,
                    ),
                    horizontalArrangement = Arrangement.spacedBy((10f * scale).dp),
                ) {
                    items(seasons, key = { it }) { season ->
                        TelevisionFilterButton(
                            label = "Stagione $season",
                            selected = selectedSeason == season,
                            onClick = { onSeason(season) },
                        )
                    }
                }
            }
            item(key = "episode-title") {
                Text(
                    "Episodi",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(
                        horizontal = dimensions.screenHorizontalPadding,
                    ),
                )
            }
            item(key = "episodes") {
                LazyRow(
                    contentPadding = PaddingValues(
                        horizontal = dimensions.screenHorizontalPadding,
                        vertical = (8f * scale).dp,
                    ),
                    horizontalArrangement =
                        Arrangement.spacedBy(dimensions.cardSpacing),
                ) {
                    itemsIndexed(
                        episodes.filter { selectedSeason <= 0 || it.season == selectedSeason },
                        key = { index, episode -> "${episode.stableKey}:$index" },
                    ) { _, episode ->
                        TelevisionMediaCard(
                            item = episode,
                            onFocused = {},
                            onClick = { onPlay(episode, episode.progressMs > 0) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TelevisionDetailActionButton(
    label: String,
    icon: ImageVector,
    primary: Boolean = false,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val scale = LocalPrippiDimensions.current.uiScale
    var focused by remember { mutableStateOf(false) }
    val normalBackground = if (primary) Color(0xFF9FCBFF) else Color(0xFF172431)
    val normalForeground = if (primary) Color(0xFF003258) else Color.White
    val background = if (focused) Color.White else normalBackground
    val foreground = if (focused) Color(0xFF071019) else normalForeground
    Row(
        modifier
            .height((52f * scale).dp)
            .onFocusChanged { focused = it.isFocused }
            .focusable()
            .scale(if (focused) 1.06f else 1f)
            .zIndex(if (focused) 3f else 0f)
            .border(
                width = if (focused) (4f * scale).dp else (1f * scale).dp,
                color = if (focused) TvFocusBorder else Color(0xFF52677A),
                shape = RoundedCornerShape((12f * scale).dp),
            )
            .background(background, RoundedCornerShape((12f * scale).dp))
            .clickable(onClick = onClick)
            .padding(horizontal = (22f * scale).dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy((8f * scale).dp),
    ) {
        Icon(
            icon,
            contentDescription = null,
            tint = foreground,
            modifier = Modifier.size((24f * scale).dp),
        )
        Text(
            label,
            color = foreground,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
            softWrap = false,
        )
    }
}

@android.annotation.SuppressLint("SetJavaScriptEnabled")
@Composable
private fun TelevisionTrailerPreview(
    urls: List<String>,
    onUnavailable: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val videoIds = remember(urls) {
        urls.mapNotNull(::trailerYoutubeId).distinct()
    }
    if (videoIds.isEmpty()) return

    val lifecycleOwner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    var lifecycleResumed by remember(lifecycleOwner) {
        mutableStateOf(
            lifecycleOwner.lifecycle.currentState.isAtLeast(
                androidx.lifecycle.Lifecycle.State.RESUMED,
            ),
        )
    }
    var webView by remember(videoIds) {
        mutableStateOf<android.webkit.WebView?>(null)
    }
    val rendererGoneViews = remember(videoIds) {
        java.util.Collections.newSetFromMap(
            java.util.WeakHashMap<android.webkit.WebView, Boolean>(),
        )
    }
    DisposableEffect(lifecycleOwner) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, _ ->
            lifecycleResumed = lifecycleOwner.lifecycle.currentState.isAtLeast(
                androidx.lifecycle.Lifecycle.State.RESUMED,
            )
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    if (!lifecycleResumed) return

    androidx.compose.ui.viewinterop.AndroidView(
        modifier = modifier,
        factory = { context ->
            android.webkit.WebView(context).apply {
                setBackgroundColor(android.graphics.Color.BLACK)
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.mediaPlaybackRequiresUserGesture = false
                settings.allowContentAccess = false
                settings.allowFileAccess = false
                isFocusable = false
                isFocusableInTouchMode = false
                importantForAccessibility = android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO
                setOnTouchListener { _, _ -> true }
                webViewClient = renderAwareWebViewClient { failedView ->
                    rendererGoneViews.add(failedView)
                    android.util.Log.w(
                        "PrippiTrailer",
                        "Renderer preview terminato; fallback al backdrop",
                    )
                    failedView.post(onUnavailable)
                }
                loadDataWithBaseURL(
                    "$TRAILER_PLAYER_ORIGIN/",
                    trailerPlayerHtml(
                        JSONArray(videoIds).toString(),
                        showNativeControls = false,
                        muted = true,
                    ),
                    "text/html",
                    "UTF-8",
                    null,
                )
                webView = this
            }
        },
        onRelease = { released ->
            if (webView === released) webView = null
            if (!rendererGoneViews.remove(released)) {
                released.stopLoading()
                released.loadUrl("about:blank")
            }
            released.removeAllViews()
            released.destroy()
        },
    )
    LaunchedEffect(videoIds, webView) {
        val activeWebView = webView ?: return@LaunchedEffect
        delay(10_000)
        if (rendererGoneViews.contains(activeWebView)) return@LaunchedEffect
        activeWebView.evaluateJavascript(
            "Boolean(window.__prippiTrailerPlaying)",
        ) { result ->
            if (result != "true") onUnavailable()
        }
    }
}

@Composable
private fun BrowseLanding(
    macros: List<ContentItem>,
    loading: Boolean,
    onMacro: (ContentItem) -> Unit,
) {
    if (macros.isEmpty() && loading) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    val dimensions = LocalPrippiDimensions.current
    Column(Modifier.fillMaxSize()) {
        Text(
            "Sfoglia",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Black,
            modifier = Modifier.padding(
                start = dimensions.screenHorizontalPadding,
                end = dimensions.screenHorizontalPadding,
                top = 18.dp,
                bottom = 4.dp,
            ),
        )
        Text(
            "Scegli un catalogo, poi esplora generi e poster.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = dimensions.screenHorizontalPadding),
        )
        LazyVerticalGrid(
            columns = GridCells.Adaptive(minSize = 168.dp),
            modifier = Modifier.weight(1f).fillMaxWidth(),
            contentPadding = PaddingValues(
                start = dimensions.screenHorizontalPadding,
                end = dimensions.screenHorizontalPadding,
                top = 18.dp,
                bottom = 28.dp,
            ),
            horizontalArrangement = Arrangement.spacedBy(dimensions.cardSpacing),
            verticalArrangement = Arrangement.spacedBy(dimensions.cardSpacing),
        ) {
            gridItemsIndexed(
                macros,
                key = { index, item -> "macro:${item.title}:$index" },
            ) { index, macro ->
                BrowseMacroCard(macro, index, onMacro)
            }
        }
    }
}

@Composable
private fun BrowseMacroCard(
    macro: ContentItem,
    index: Int,
    onClick: (ContentItem) -> Unit,
) {
    val accents = listOf(
        Color(0xFF12395A) to Color(0xFF1F6A8A),
        Color(0xFF3B234F) to Color(0xFF764A78),
        Color(0xFF173E35) to Color(0xFF33745E),
        Color(0xFF4A2C20) to Color(0xFF8A5A38),
    )
    val (start, end) = accents[index % accents.size]
    Card(
        modifier = Modifier.fillMaxWidth().height(138.dp).clickable { onClick(macro) },
        shape = RoundedCornerShape(16.dp),
    ) {
        Box(
            Modifier.fillMaxSize().background(Brush.linearGradient(listOf(start, end))),
        ) {
            Icon(
                Icons.Default.List,
                contentDescription = null,
                tint = Color.White.copy(alpha = 0.18f),
                modifier = Modifier.align(Alignment.TopEnd).padding(14.dp).size(54.dp),
            )
            Column(
                Modifier.align(Alignment.BottomStart).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(5.dp),
            ) {
                Text(
                    macro.title,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Black,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    "Generi e catalogo",
                    style = MaterialTheme.typography.labelMedium,
                    color = Color.White.copy(alpha = 0.78f),
                )
            }
        }
    }
}

@Composable
private fun DownloadsPage(
    entries: List<DownloadEntry>,
    loading: Boolean,
    isTelevision: Boolean = false,
    onPlay: (DownloadEntry) -> Unit,
    onPause: (DownloadEntry) -> Unit,
    onResume: (DownloadEntry) -> Unit,
    onRemove: (DownloadEntry) -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scale = LocalPrippiDimensions.current.uiScale
    val freeBytes = remember(entries) {
        runCatching { StatFs(context.filesDir.absolutePath).availableBytes }.getOrDefault(0L)
    }
    val freeLabel = String.format(Locale.ROOT, "%.1f GB liberi", freeBytes / 1_073_741_824.0)
    if (entries.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            if (loading) CircularProgressIndicator() else Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(
                    Icons.Default.Download,
                    contentDescription = null,
                    modifier = Modifier.size((52f * scale).dp),
                )
                Spacer(Modifier.height((8f * scale).dp))
                Text("Non hai ancora scaricato contenuti")
                Text("Apri un film o un episodio e premi Scarica", style = MaterialTheme.typography.bodySmall)
                Text(
                    freeLabel,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(top = (8f * scale).dp),
                )
            }
        }
        return
    }
    LazyColumn(Modifier.fillMaxSize().focusGroup()) {
        item(key = "download-storage") {
            ListItem(
                headlineContent = { Text("Spazio disponibile") },
                supportingContent = { Text(freeLabel) },
                leadingContent = { Icon(Icons.Default.Info, contentDescription = null) },
            )
            HorizontalDivider()
        }
        items(entries, key = { it.key }) { entry ->
            var speedBytesPerSecond by remember(entry.key) { mutableStateOf(0.0) }
            var previousBytes by remember(entry.key) { mutableStateOf(entry.totalBytes) }
            var previousSampleAt by remember(entry.key) { mutableStateOf(SystemClock.elapsedRealtime()) }
            LaunchedEffect(entry.totalBytes, entry.status) {
                val now = SystemClock.elapsedRealtime()
                val elapsedSeconds = (now - previousSampleAt) / 1000.0
                if (entry.status == "downloading" && elapsedSeconds > 0.25 && entry.totalBytes >= previousBytes) {
                    speedBytesPerSecond = (entry.totalBytes - previousBytes) / elapsedSeconds
                } else if (entry.status != "downloading") {
                    speedBytesPerSecond = 0.0
                }
                previousBytes = entry.totalBytes
                previousSampleAt = now
            }
            ListItem(
                headlineContent = { Text(entry.displayTitle, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                supportingContent = {
                    Column {
                        val status = when (entry.status) {
                            "queued" -> "In coda"
                            "downloading" -> "Download ${entry.progress.toInt()}%"
                            "waiting_network" -> "In attesa della rete · ${entry.progress.toInt()}%"
                            "done" -> "Disponibile offline${entry.quality.takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty()}"
                            "paused" -> "In pausa · ${entry.progress.toInt()}%"
                            "error" -> "Errore${entry.error.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()}"
                            else -> entry.status
                        }
                        Text(status, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        if (entry.status in setOf("downloading", "paused") && entry.totalBytes > 0L) {
                            val estimatedTotal = if (entry.progress > 0f) {
                                (entry.totalBytes / (entry.progress / 100.0)).toLong()
                            } else 0L
                            val details = buildList {
                                add("${formatBytes(entry.totalBytes)} scaricati")
                                if (estimatedTotal > entry.totalBytes) add("su ~${formatBytes(estimatedTotal)}")
                                if (speedBytesPerSecond > 0.0 && entry.status == "downloading") {
                                    add("${formatBytes(speedBytesPerSecond.toLong())}/s")
                                }
                            }.joinToString(" · ")
                            Text(details, style = MaterialTheme.typography.bodySmall)
                        }
                        if (entry.progress > 0f && !entry.isComplete) {
                            LinearProgressIndicator(
                                progress = { entry.progress / 100f },
                                modifier = Modifier.fillMaxWidth()
                                    .padding(top = (6f * scale).dp),
                            )
                        }
                    }
                },
                leadingContent = {
                    AppImage(
                        model = entry.thumbnail,
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .size(
                                width = (52f * scale).dp,
                                height = (76f * scale).dp,
                            )
                            .clip(RoundedCornerShape((6f * scale).dp)),
                    )
                },
                trailingContent = {
                    Row {
                        when {
                            entry.isComplete -> IconButton(onClick = { onPlay(entry) }) {
                                Icon(Icons.Default.PlayArrow, contentDescription = "Riproduci offline")
                            }
                            entry.isActive -> IconButton(onClick = { onPause(entry) }) {
                                Icon(Icons.Default.Pause, contentDescription = "Pausa")
                            }
                            entry.canResume -> IconButton(onClick = { onResume(entry) }) {
                                Icon(Icons.Default.Replay, contentDescription = "Riprendi download")
                            }
                        }
                        if (!entry.isActive) {
                            IconButton(onClick = { onRemove(entry) }) {
                                Icon(Icons.Default.DeleteOutline, contentDescription = "Elimina download")
                            }
                        }
                    }
                },
                modifier = Modifier.tvFocusableFrame(
                    isTelevision,
                    RoundedCornerShape((10f * scale).dp),
                ),
            )
            HorizontalDivider()
        }
    }
}

private fun formatBytes(bytes: Long): String {
    if (bytes < 1_024L) return "$bytes B"
    val units = arrayOf("KB", "MB", "GB", "TB")
    var value = bytes.toDouble()
    var unit = -1
    while (value >= 1_024.0 && unit < units.lastIndex) {
        value /= 1_024.0
        unit++
    }
    return if (value >= 100.0) String.format(Locale.ROOT, "%.0f %s", value, units[unit])
    else String.format(Locale.ROOT, "%.1f %s", value, units[unit])
}

@Composable
private fun ChannelPage(
    channels: List<ChannelInfo>,
    loading: Boolean,
    heading: String,
    onClick: (ChannelInfo) -> Unit,
) {
    if (channels.isEmpty() && loading) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Text(
                heading,
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(16.dp),
            )
        }
        items(channels, key = { it.id }) { channel ->
            ListItem(
                headlineContent = { Text(channel.title) },
                supportingContent = {
                    Text(channel.categories.joinToString(" · ").ifBlank { "Provider" })
                },
                leadingContent = {
                    AppImage(
                        model = channel.thumbnail,
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.size(56.dp).clip(RoundedCornerShape(8.dp)),
                    )
                },
                trailingContent = { Text("Apri") },
                modifier = Modifier.clickable { onClick(channel) },
            )
            HorizontalDivider()
        }
    }
}

@Composable
private fun TelevisionSettingsPage(
    categories: List<SettingCategory>,
    onChange: (AppSetting, Any) -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    fun runAction(setting: AppSetting) {
        when (setting.id) {
            "network_info" -> android.app.AlertDialog.Builder(context)
                .setTitle("Rete e dispositivo")
                .setMessage(networkSummary(context))
                .setPositiveButton("OK", null)
                .show()
            "send_log_to_dev" -> promptAndShareDiagnosticReport(context)
            else -> android.widget.Toast.makeText(
                context,
                "Azione non necessaria su Android",
                android.widget.Toast.LENGTH_SHORT,
            ).show()
        }
    }
    LazyColumn(
        Modifier.fillMaxSize().focusGroup(),
        contentPadding = PaddingValues(
            start = dimensions.screenHorizontalPadding,
            end = dimensions.screenHorizontalPadding,
            top = (24f * scale).dp,
            bottom = (40f * scale).dp,
        ),
        verticalArrangement = Arrangement.spacedBy((12f * scale).dp),
    ) {
        item(key = "settings-title") {
            Text(
                "Impostazioni",
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Black,
            )
        }
        item(key = "settings-update") { AppUpdatePanel() }
        categories.forEach { category ->
            item(key = "tv-category:${category.label}") {
                Text(
                    category.label,
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(
                        top = (12f * scale).dp,
                        bottom = (2f * scale).dp,
                    ),
                )
            }
            items(category.settings, key = { "tv-setting:${it.channel}:${it.id}" }) { setting ->
                TelevisionSettingRow(setting, onChange, ::runAction)
            }
        }
    }
}

@Composable
private fun TelevisionSettingRow(
    setting: AppSetting,
    onChange: (AppSetting, Any) -> Unit,
    onAction: (AppSetting) -> Unit,
) {
    val dimensions = LocalPrippiDimensions.current
    val scale = dimensions.uiScale
    var focused by remember { mutableStateOf(false) }
    val valueLabel = when (setting.type) {
        "bool" -> if (setting.boolValue) "Attivo" else "Disattivato"
        "action" -> "Apri"
        else -> setting.value.ifBlank { setting.defaultValue }
    }
    fun activate() {
        when (setting.type) {
            "bool" -> onChange(setting, !setting.boolValue)
            "select", "list" -> if (setting.values.isNotEmpty()) {
                val current = setting.values.indexOf(setting.value).takeIf { it >= 0 } ?: -1
                onChange(setting, setting.values[(current + 1) % setting.values.size])
            }
            "slider" -> {
                val current = setting.value.toIntOrNull() ?: setting.defaultValue.toIntOrNull() ?: 0
                val minimum = setting.range.getOrNull(0) ?: current
                val step = setting.range.getOrNull(1) ?: 1
                val maximum = setting.range.getOrNull(2) ?: current
                onChange(setting, if (current + step <= maximum) current + step else minimum)
            }
            "action" -> onAction(setting)
            else -> Unit
        }
    }
    Row(
        Modifier.fillMaxWidth()
            .onFocusChanged { focused = it.isFocused }
            .border(
                (if (focused) 4f * scale else 1f * scale).dp,
                if (focused) TvFocusBorder else Color(0xFF2D4357),
                RoundedCornerShape((14f * scale).dp),
            )
            .background(
                if (focused) TvFocusBackground else Color(0xFF101923),
                RoundedCornerShape((14f * scale).dp),
            )
            .clickable(enabled = setting.enabled, onClick = ::activate)
            .padding(
                horizontal = (20f * scale).dp,
                vertical = (15f * scale).dp,
            ),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            setting.label,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.weight(1f),
        )
        Text(
            valueLabel,
            color = if (setting.enabled) Color(0xFF91CEFF) else Color(0xFF778492),
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(start = (24f * scale).dp),
        )
    }
}

@Composable
private fun SettingsPage(
    categories: List<SettingCategory>,
    onChange: (AppSetting, Any) -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    fun runAction(setting: AppSetting) {
        when (setting.id) {
            "network_info" -> android.app.AlertDialog.Builder(context)
                .setTitle("Rete e dispositivo")
                .setMessage(networkSummary(context))
                .setPositiveButton("OK", null)
                .show()
            "send_log_to_dev" -> promptAndShareDiagnosticReport(context)
            else -> android.widget.Toast.makeText(
                context, "Azione non necessaria su Android", android.widget.Toast.LENGTH_SHORT,
            ).show()
        }
    }
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(bottom = 24.dp),
    ) {
        item(key = "app-update") { AppUpdatePanel() }
        categories.forEach { category ->
            item(key = "category:${category.label}") {
                Text(
                    category.label,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 22.dp, bottom = 8.dp),
                )
            }
            items(category.settings, key = { "setting:${it.channel}:${it.id}" }) { setting ->
                SettingRow(setting, onChange, ::runAction)
                HorizontalDivider()
            }
        }
    }
}

@Composable
private fun AppUpdatePanel() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var checking by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("Controllo GitHub Releases…") }
    var update by remember { mutableStateOf<AppUpdateInfo?>(null) }

    fun check() {
        checking = true
        scope.launch {
            try {
                val result = AppUpdateManager.checkForUpdate()
                update = result.info
                status = result.message
            } catch (error: Exception) {
                status = "Controllo non riuscito: ${error.message ?: "errore di rete"}"
            } finally {
                checking = false
            }
        }
    }

    LaunchedEffect(Unit) { check() }
    Card(Modifier.fillMaxWidth().padding(16.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("Aggiornamenti app", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(status)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(enabled = !checking, onClick = ::check) { Text("Controlla ora") }
                update?.let { info ->
                    Button(
                        enabled = !checking,
                        onClick = {
                            checking = true
                            status = "Download di PrippiStream ${info.version}…"
                            scope.launch {
                                try {
                                    val apk = AppUpdateManager.download(context, info)
                                    val launched = AppUpdateManager.requestInstall(context, apk)
                                    status = if (launched) {
                                        "APK scaricato: completa l'installazione nella schermata Android."
                                    } else {
                                        "Consenti l'installazione da questa sorgente, poi premi di nuovo Aggiorna."
                                    }
                                } catch (error: Exception) {
                                    status = "Aggiornamento non riuscito: ${error.message ?: "errore"}"
                                } finally {
                                    checking = false
                                }
                            }
                        },
                    ) { Text("Aggiorna") }
                }
            }
            if (BuildConfig.DEBUG) {
                TextButton(
                    onClick = {
                        val candidates = listOf(
                            PlaybackRequest(
                                url = "http://127.0.0.1:9/missing.m3u8",
                                bootstrapUrl = "",
                                manifest = "hls",
                                audioLanguage = "it",
                                headersJson = "{}",
                                label = "Sorgente guasta",
                            ),
                            PlaybackRequest(
                                url = "https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_ts/master.m3u8",
                                bootstrapUrl = "",
                                manifest = "hls",
                                audioLanguage = "en",
                                headersJson = "{}",
                                label = "HLS di verifica",
                                subtitleUrls = listOf(
                                    "https://storage.googleapis.com/exoplayer-test-media-1/webvtt/numeric-lines.vtt",
                                ),
                            ),
                        )
                        context.startActivity(Intent(context, PlayerActivity::class.java).apply {
                            putExtra("url", candidates.first().url)
                            putExtra("manifest", "hls")
                            putExtra("headers", "{}")
                            putExtra("playback_candidates_json", JSONArray().apply {
                                candidates.forEach { put(it.toJson()) }
                            }.toString())
                        })
                    },
                ) { Text("Diagnostica fallback player") }
            }
        }
    }
}

/**
 * Checks once per app opening and keeps the update prompt available until the
 * user installs the newer release. Dismissing it only postpones it for the
 * current opening; the next opening checks again.
 */
@Composable
private fun UpdateReminderDialog() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var update by remember { mutableStateOf<AppUpdateInfo?>(null) }
    var installing by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        try {
            val result = AppUpdateManager.checkForUpdate()
            update = result.info
        } catch (error: Exception) {
            errorMessage = error.message
        } finally {
        }
    }

    val info = update ?: return
    AlertDialog(
        onDismissRequest = { if (!installing) update = null },
        title = { Text("Nuovo aggiornamento disponibile") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("È disponibile PrippiStream ${info.version}.")
                Text("Aggiorna l'app per ricevere le ultime correzioni e migliorie.")
                if (errorMessage != null) {
                    Text(errorMessage!!, style = MaterialTheme.typography.bodySmall)
                }
            }
        },
        confirmButton = {
            Button(
                enabled = !installing,
                onClick = {
                    installing = true
                    scope.launch {
                        try {
                            val apk = AppUpdateManager.download(context, info)
                            AppUpdateManager.requestInstall(context, apk)
                        } catch (error: Exception) {
                            errorMessage = "Aggiornamento non riuscito: ${error.message ?: "errore"}"
                            installing = false
                        }
                    }
                },
            ) { Text(if (installing) "Download…" else "Aggiorna") }
        },
        dismissButton = {
            TextButton(enabled = !installing, onClick = { update = null }) {
                Text("Più tardi")
            }
        },
    )
}

@Composable
private fun SettingRow(
    setting: AppSetting,
    onChange: (AppSetting, Any) -> Unit,
    onAction: (AppSetting) -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val internalDownloads = File(context.filesDir, "downloads").absolutePath
    val externalDownloads = context.getExternalFilesDir(Environment.DIRECTORY_MOVIES)
        ?.let { File(it, "PrippiStream").absolutePath }
    val usesExternalDownloads = setting.id == "downloadpath" &&
        externalDownloads != null && setting.value == externalDownloads
    ListItem(
        headlineContent = { Text(setting.label) },
        supportingContent = {
            when (setting.type) {
                "folder" -> Text(
                    when {
                        setting.id != "downloadpath" -> setting.value.ifBlank { "Cartella privata dell'app" }
                        usesExternalDownloads -> "Memoria esterna dell'app"
                        else -> "Memoria interna dell'app"
                    },
                )
                "action" -> Text("Tocca per eseguire")
                "select", "list" -> Text(setting.value)
                "slider" -> Text("Valore: ${setting.value}")
                else -> if (setting.type != "bool" && setting.value.isNotBlank()) Text(setting.value)
            }
        },
        trailingContent = {
            when (setting.type) {
                "bool" -> Switch(
                    checked = setting.boolValue,
                    enabled = setting.enabled,
                    onCheckedChange = { onChange(setting, it) },
                )
                "select", "list" -> TextButton(
                    enabled = setting.enabled && setting.values.isNotEmpty(),
                    onClick = {
                        val index = setting.values.indexOf(setting.value).takeIf { it >= 0 } ?: -1
                        onChange(setting, setting.values[(index + 1) % setting.values.size])
                    },
                ) { Text("Cambia") }
                "slider" -> {
                    val current = setting.value.toIntOrNull() ?: setting.defaultValue.toIntOrNull() ?: 1
                    val min = setting.range.getOrNull(0) ?: 1
                    val step = setting.range.getOrNull(1) ?: 1
                    val max = setting.range.getOrNull(2) ?: current
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        TextButton(enabled = current > min, onClick = { onChange(setting, current - step) }) {
                            Text("−")
                        }
                        Text(current.toString())
                        TextButton(enabled = current < max, onClick = { onChange(setting, current + step) }) {
                            Text("+")
                        }
                    }
                }
                "action" -> TextButton(
                    enabled = setting.enabled,
                    onClick = { onAction(setting) },
                ) { Text("Apri") }
                "folder" -> if (setting.id == "downloadpath") {
                    TextButton(
                        enabled = setting.enabled && externalDownloads != null,
                        onClick = {
                            onChange(
                                setting,
                                if (usesExternalDownloads) internalDownloads else externalDownloads!!,
                            )
                        },
                    ) { Text(if (usesExternalDownloads) "Usa interna" else "Usa esterna") }
                } else Unit
                else -> Unit
            }
        },
    )
}

@Composable
private fun SearchBar(
    query: String,
    onQuery: (String) -> Unit,
    onSearch: () -> Unit,
    requestInitialFocus: Boolean = false,
    television: Boolean = false,
) {
    val fieldFocus = remember { FocusRequester() }
    LaunchedEffect(requestInitialFocus) {
        if (requestInitialFocus) {
            delay(80)
            runCatching { fieldFocus.requestFocus() }
        }
    }
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedTextField(
            value = query,
            onValueChange = onQuery,
            label = { Text("Cerca film, serie o anime") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(
                onSearch = { if (query.isNotBlank()) onSearch() },
            ),
            modifier = Modifier
                .weight(1f)
                .focusRequester(fieldFocus)
                .tvFocusableFrame(television, RoundedCornerShape(8.dp)),
        )
        Spacer(Modifier.width(8.dp))
        Button(
            onClick = onSearch,
            enabled = query.isNotBlank(),
            modifier = Modifier.tvFocusableFrame(television, RoundedCornerShape(22.dp)),
        ) {
            Icon(Icons.Default.Search, contentDescription = null)
            Spacer(Modifier.width(4.dp))
            Text("Cerca")
        }
    }
}

@Composable
private fun SearchHistoryRow(
    values: List<String>,
    onSelect: (String) -> Unit,
    onClear: () -> Unit,
) {
    LazyRow(
        contentPadding = PaddingValues(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        items(values, key = { it.lowercase(Locale.ROOT) }) { query ->
            FilterChip(
                selected = false,
                onClick = { onSelect(query) },
                label = { Text(query) },
            )
        }
        item {
            TextButton(onClick = onClear) { Text("Cancella cronologia") }
        }
    }
}

@Composable
private fun HomePage(
    rows: List<HomeRow>,
    loading: Boolean,
    onClick: (ContentItem) -> Unit,
    onRetry: () -> Unit,
    isTelevision: Boolean,
    focusedRowId: String,
    focusedItemKey: String,
    focusRecoveryNonce: Int,
    onItemFocused: (String, String) -> Unit,
) {
    if (rows.isEmpty() && loading) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    if (rows.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("La Home non ha ancora contenuti")
                TextButton(onClick = onRetry) { Text("Riprova") }
            }
        }
        return
    }
    // Congela il target soltanto all'ingresso della schermata. In precedenza
    // ogni movimento del telecomando spostava lo stesso FocusRequester sulla
    // nuova card e riavviava scroll/requestFocus, creando una tempesta di
    // ricomposizioni proprio durante gli aggiornamenti progressivi della Home.
    val restoreRowId = remember(rows.isNotEmpty(), focusRecoveryNonce) { focusedRowId }
    val restoreItemKey = remember(rows.isNotEmpty(), focusRecoveryNonce) { focusedItemKey }
    val targetRowIndex = rows.indexOfFirst { it.id == restoreRowId }
        .takeIf { it >= 0 } ?: 0
    val targetRow = rows.getOrNull(targetRowIndex)
    val targetItemIndex = targetRow?.items?.indexOfFirst {
        it.stableKey == restoreItemKey
    }?.takeIf { it >= 0 } ?: 0
    val restoredCardFocus = remember { FocusRequester() }
    val columnState = rememberLazyListState()
    LaunchedEffect(
        isTelevision,
        rows.isNotEmpty(),
        focusRecoveryNonce,
    ) {
        if (isTelevision && rows.firstOrNull()?.items?.isNotEmpty() == true) {
            columnState.scrollToItem(targetRowIndex)
            delay(120)
            runCatching { restoredCardFocus.requestFocus() }
        }
    }
    LazyColumn(
        state = columnState,
        contentPadding = PaddingValues(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        itemsIndexed(rows, key = { _, row -> row.id }) { rowIndex, row ->
            Column {
                Text(
                    row.title,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
                LazyRow(
                    state = rememberLazyListState(
                        initialFirstVisibleItemIndex = if (rowIndex == targetRowIndex) {
                            targetItemIndex
                        } else {
                            0
                        },
                    ),
                    contentPadding = PaddingValues(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (row.items.isEmpty()) {
                        item(key = "${row.id}:empty") {
                            Card(Modifier.width(260.dp)) {
                                Row(
                                    Modifier.fillMaxWidth().padding(12.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                ) {
                                    Text(if (loading) "Caricamento…" else "Nessun contenuto disponibile")
                                    if (!loading) TextButton(onClick = onRetry) { Text("Riprova") }
                                }
                            }
                        }
                    } else {
                        itemsIndexed(
                            row.items,
                            key = { index, item -> "${row.id}:${item.stableKey}:$index" },
                        ) { itemIndex, item ->
                            PosterCard(
                                item = item,
                                onClick = { onClick(item) },
                                isTelevision = isTelevision,
                                onFocused = { onItemFocused(row.id, item.stableKey) },
                                modifier = if (
                                    rowIndex == targetRowIndex &&
                                    itemIndex == targetItemIndex
                                ) {
                                    Modifier.focusRequester(restoredCardFocus)
                                } else {
                                    Modifier
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AppImage(
    model: Any?,
    fallbackModel: Any? = null,
    contentDescription: String?,
    contentScale: ContentScale,
    modifier: Modifier = Modifier,
) {
    var activeModel by remember(model, fallbackModel) { mutableStateOf(model) }
    val imageContext = androidx.compose.ui.platform.LocalContext.current
    val lowPowerImages = remember(imageContext) {
        DeviceProfile.detect(imageContext).isLowPower
    }
    val request = remember(activeModel, lowPowerImages) {
        ImageRequest.Builder(imageContext)
            .data(activeModel)
            .setHeader(
                "User-Agent",
                "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
            )
            .apply {
                (activeModel as? String)?.takeIf { it.startsWith("http") }?.let { url ->
                    runCatching { Uri.parse(url) }.getOrNull()?.let { uri ->
                        val origin = "${uri.scheme}://${uri.host}/"
                        setHeader("Referer", origin)
                    }
                }
            }
            // La dissolvenza mantiene contemporaneamente bitmap vecchia e
            // nuova. Sulle box da 2 GB è uno spreco visibile durante lo scroll.
            .crossfade(!lowPowerImages)
            .build()
    }
    val placeholder: @Composable () -> Unit = {
        Box(
            Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.Info, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
    SubcomposeAsyncImage(
        model = request,
        contentDescription = contentDescription,
        contentScale = contentScale,
        modifier = modifier,
        loading = { placeholder() },
        onError = {
            android.util.Log.w("PrippiImage", "Immagine non caricata: $activeModel")
            if (fallbackModel != null && fallbackModel != activeModel) activeModel = fallbackModel
        },
        error = { placeholder() },
    )
}

@Composable
private fun LivePage(
    rows: List<HomeRow>,
    loading: Boolean,
    onLive: (ContentItem) -> Unit,
    isTelevision: Boolean,
    focusedRowId: String,
    focusedItemKey: String,
    focusRecoveryNonce: Int,
    onItemFocused: (String, String) -> Unit,
) {
    val restoreRowId = remember(rows.isNotEmpty(), focusRecoveryNonce) { focusedRowId }
    val restoreItemKey = remember(rows.isNotEmpty(), focusRecoveryNonce) { focusedItemKey }
    val targetRowIndex = rows.indexOfFirst { it.id == restoreRowId }
        .takeIf { it >= 0 } ?: 0
    val targetRow = rows.getOrNull(targetRowIndex)
    val targetItemIndex = targetRow?.items?.indexOfFirst {
        it.stableKey == restoreItemKey
    }?.takeIf { it >= 0 } ?: 0
    val restoredCardFocus = remember { FocusRequester() }
    val columnState = rememberLazyListState()
    LaunchedEffect(
        isTelevision,
        rows.isNotEmpty(),
        focusRecoveryNonce,
    ) {
        if (isTelevision && targetRow?.items?.isNotEmpty() == true) {
            columnState.scrollToItem(targetRowIndex)
            delay(120)
            runCatching { restoredCardFocus.requestFocus() }
        }
    }
    LazyColumn(
        Modifier.fillMaxSize(),
        state = columnState,
        contentPadding = PaddingValues(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        if (rows.isEmpty()) {
            item {
                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    CircularProgressIndicator(Modifier.size(28.dp))
                    Text("Verifica dei canali SKY, Sport e TV in corso…")
                }
            }
        }
        itemsIndexed(rows, key = { _, row -> row.id }) { rowIndex, row ->
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    row.title,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
                LazyRow(
                    state = rememberLazyListState(
                        initialFirstVisibleItemIndex = if (rowIndex == targetRowIndex) {
                            targetItemIndex
                        } else {
                            0
                        },
                    ),
                    contentPadding = PaddingValues(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    itemsIndexed(
                        row.items,
                        key = { index, item -> "${row.id}:${item.stableKey}:$index" },
                    ) { itemIndex, item ->
                        LiveCard(
                            item = item,
                            isTelevision = isTelevision,
                            modifier = if (
                                rowIndex == targetRowIndex &&
                                itemIndex == targetItemIndex
                            ) {
                                Modifier.focusRequester(restoredCardFocus)
                            } else {
                                Modifier
                            },
                            onFocused = { onItemFocused(row.id, item.stableKey) },
                            onClick = { onLive(item) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun LiveCard(
    item: ContentItem,
    isTelevision: Boolean,
    modifier: Modifier = Modifier,
    onFocused: () -> Unit = {},
    onClick: () -> Unit,
) {
    val compactLandscape = LocalConfiguration.current.screenHeightDp < 540
    Card(
        modifier = modifier
            .width(
                when {
                    !isTelevision -> 132.dp
                    compactLandscape -> 110.dp
                    else -> 166.dp
                },
            )
            .tvFocusableFrame(isTelevision, onFocused = onFocused)
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(10.dp),
    ) {
        Column {
            AppImage(
                model = item.posterUrl,
                fallbackModel = item.backdropUrl.takeIf { it.isNotBlank() },
                contentDescription = item.title,
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxWidth().aspectRatio(2f / 3f)
                    .background(Color(0xFF0D0D0D))
                    .clip(RoundedCornerShape(topStart = 10.dp, topEnd = 10.dp)),
            )
            Text(
                item.title,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(start = 10.dp, end = 10.dp, top = 8.dp),
            )
            Text(
                item.plot.ifBlank { "Diretta verificata" },
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(10.dp).height(52.dp),
            )
        }
    }
}

@Composable
private fun PosterCard(
    item: ContentItem,
    onClick: () -> Unit,
    isTelevision: Boolean = false,
    modifier: Modifier = Modifier,
    onFocused: () -> Unit = {},
) {
    val compactLandscape = LocalConfiguration.current.screenHeightDp < 540
    Card(
        modifier = modifier
            .width(
                when {
                    !isTelevision -> 148.dp
                    compactLandscape -> 100.dp
                    else -> 174.dp
                },
            )
            .tvFocusableFrame(isTelevision, onFocused = onFocused)
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(10.dp),
    ) {
        Column {
            Box {
                AppImage(
                    model = item.posterUrl,
                    fallbackModel = item.backdropUrl.takeIf { it.isNotBlank() },
                    contentDescription = item.title,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxWidth().aspectRatio(2f / 3f)
                        .clip(RoundedCornerShape(topStart = 10.dp, topEnd = 10.dp)),
                )
                if (item.progressFraction > 0f) {
                    LinearProgressIndicator(
                        progress = { item.progressFraction },
                        modifier = Modifier.fillMaxWidth().align(Alignment.BottomCenter),
                    )
                }
            }
            Text(
                item.title,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(start = 9.dp, end = 9.dp, top = 8.dp).height(40.dp),
            )
            val type = when {
                item.isEpisode -> "Episodio"
                item.isSeries -> "Serie"
                else -> "Film"
            }
            val metadata = listOfNotNull(
                type,
                item.year.takeIf { it > 0 }?.toString(),
                item.rating.takeIf { it > 0 }?.let { "★ ${String.format(Locale.US, "%.1f", it)}" },
            ).joinToString(" · ")
            Text(
                metadata,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 9.dp, end = 9.dp, bottom = 9.dp),
            )
        }
    }
}

@Composable
private fun ResultList(items: List<ContentItem>, loading: Boolean, onClick: (ContentItem) -> Unit) {
    if (items.isEmpty() && !loading) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("Nessun contenuto trovato") }
        return
    }
    val controls = items.filter {
        (it.posterUrl.isBlank() && it.backdropUrl.isBlank()) ||
            it.action in setOf("_app_macro_more", "_app_macro_sort")
    }
    val media = items - controls.toSet()
    Column(Modifier.fillMaxSize()) {
        if (controls.isNotEmpty()) {
            LazyRow(
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 10.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                itemsIndexed(
                    controls,
                    key = { index, item -> "control:${item.action}:${item.title}:$index" },
                ) { _, item ->
                    FilterChip(
                        selected = false,
                        onClick = { onClick(item) },
                        label = { Text(item.title) },
                        leadingIcon = {
                            Icon(
                                if (item.action == "_app_macro_more") {
                                    Icons.Default.Add
                                } else {
                                    Icons.Default.Sort
                                },
                                contentDescription = null,
                            )
                        },
                    )
                }
            }
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            AdaptivePosterGrid(media, loading, onClick)
        }
    }
}

@Composable
private fun SearchResults(
    items: List<ContentItem>,
    filter: String,
    loading: Boolean,
    onFilter: (String) -> Unit,
    onClick: (ContentItem) -> Unit,
) {
    val choices = listOf(
        "all" to "Tutti",
        "film" to "Film",
        "serie" to "Serie",
        "anime" to "Anime",
    )
    val shown = if (filter == "all") items else items.filter { it.searchType == filter }
    Column(Modifier.fillMaxSize()) {
        LazyRow(
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(choices, key = { it.first }) { (value, label) ->
                FilterChip(
                    selected = filter == value,
                    onClick = { onFilter(value) },
                    label = { Text(label) },
                )
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "Risultati",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Black,
            )
            Text(
                shown.size.toString(),
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(start = 10.dp),
            )
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            AdaptivePosterGrid(shown, loading, onClick)
        }
    }
}

@Composable
private fun AdaptivePosterGrid(
    items: List<ContentItem>,
    loading: Boolean,
    onClick: (ContentItem) -> Unit,
) {
    if (items.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            if (loading) CircularProgressIndicator() else Text("Nessun contenuto trovato")
        }
        return
    }
    val dimensions = LocalPrippiDimensions.current
    val tablet = LocalConfiguration.current.smallestScreenWidthDp >= 600
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = if (tablet) 172.dp else 142.dp),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            start = dimensions.screenHorizontalPadding,
            end = dimensions.screenHorizontalPadding,
            top = 10.dp,
            bottom = 28.dp,
        ),
        horizontalArrangement = Arrangement.spacedBy(dimensions.cardSpacing),
        verticalArrangement = Arrangement.spacedBy(dimensions.cardSpacing),
    ) {
        gridItemsIndexed(
            items,
            key = { index, item -> "${item.stableKey}:${item.action}:$index" },
        ) { _, item ->
            AdaptivePosterGridCard(item) { onClick(item) }
        }
    }
}

@Composable
private fun AdaptivePosterGridCard(
    item: ContentItem,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column {
            Box {
                AppImage(
                    model = item.posterUrl.ifBlank { item.backdropUrl },
                    fallbackModel = item.backdropUrl,
                    contentDescription = item.title,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxWidth().aspectRatio(2f / 3f)
                        .clip(RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp)),
                )
                if (item.progressFraction > 0f) {
                    LinearProgressIndicator(
                        progress = { item.progressFraction },
                        modifier = Modifier.fillMaxWidth().align(Alignment.BottomCenter),
                    )
                }
            }
            Text(
                item.title,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(start = 10.dp, end = 10.dp, top = 9.dp)
                    .height(44.dp),
            )
            Text(
                posterMetadata(item),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 10.dp, end = 10.dp, bottom = 10.dp),
            )
        }
    }
}

private fun posterMetadata(item: ContentItem): String {
    val type = when {
        item.isEpisode -> "Episodio"
        item.isSeries -> "Serie"
        else -> "Film"
    }
    return listOfNotNull(
        type,
        item.year.takeIf { it > 0 }?.toString(),
        item.runtimeMinutes.takeIf { it > 0 }?.let(::formatRuntimeMinutes),
        item.rating.takeIf { it > 0 }
            ?.let { "★ ${String.format(Locale.US, "%.1f", it)}" },
    ).joinToString(" · ")
}

private fun formatRuntimeMinutes(minutes: Int): String {
    if (minutes <= 0) return ""
    val hours = minutes / 60
    val remaining = minutes % 60
    return when {
        hours <= 0 -> "$minutes min"
        remaining == 0 -> "${hours}h"
        else -> "${hours}h ${remaining}min"
    }
}

private fun ContentItem.hasEditorialCredits(): Boolean =
    director.isNotBlank() ||
        cast.isNotBlank() ||
        studio.isNotBlank() ||
        country.isNotBlank() ||
        premiered.isNotBlank()

@Composable
private fun EditorialCreditsPanel(
    item: ContentItem,
    modifier: Modifier,
    television: Boolean,
) {
    val rows = listOfNotNull(
        item.director.takeIf(String::isNotBlank)?.let { "Regia" to it },
        item.cast.takeIf(String::isNotBlank)?.let { "Cast" to it },
        item.studio.takeIf(String::isNotBlank)?.let { "Studio" to it },
        item.country.takeIf(String::isNotBlank)?.let { "Paese" to it },
        item.premiered.takeIf(String::isNotBlank)?.let { "Uscita" to it },
    )
    if (rows.isEmpty()) return
    Card(modifier = modifier, shape = RoundedCornerShape(14.dp)) {
        Column(
            Modifier.padding(if (television) 20.dp else 16.dp),
            verticalArrangement = Arrangement.spacedBy(if (television) 10.dp else 7.dp),
        ) {
            Text(
                "Informazioni",
                style = if (television) {
                    MaterialTheme.typography.titleLarge
                } else {
                    MaterialTheme.typography.titleMedium
                },
                fontWeight = FontWeight.Bold,
            )
            rows.forEach { (label, value) ->
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.Top,
                ) {
                    Text(
                        label,
                        modifier = Modifier.width(if (television) 96.dp else 64.dp),
                        color = MaterialTheme.colorScheme.primary,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        value,
                        modifier = Modifier.weight(1f),
                        maxLines = if (label == "Cast") 2 else 1,
                        overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        }
    }
}

@Composable
private fun ContentListItem(item: ContentItem, onClick: (ContentItem) -> Unit) {
    if (item.channel == "_app_macro" && item.action == "_app_macro_titles") {
        ListItem(
            headlineContent = { Text(item.title, style = MaterialTheme.typography.titleMedium) },
            trailingContent = { Text("Apri") },
            modifier = Modifier.clickable { onClick(item) },
        )
        return
    }
    if (item.action in setOf("_app_macro_more", "_app_macro_sort")) {
        ListItem(
            headlineContent = { Text(item.title, fontWeight = FontWeight.SemiBold) },
            leadingContent = {
                Icon(
                    if (item.action == "_app_macro_more") Icons.Default.Add else Icons.Default.Sort,
                    contentDescription = null,
                )
            },
            modifier = Modifier.clickable { onClick(item) },
        )
        return
    }
    ListItem(
        headlineContent = { Text(item.title) },
        supportingContent = {
            val metadata = listOfNotNull(
                when {
                    item.isEpisode -> "Episodio"
                    item.isSeries -> "Serie"
                    else -> "Film"
                },
                item.year.takeIf { it > 0 }?.toString(),
                item.rating.takeIf { it > 0 }?.let { "★ ${String.format(Locale.US, "%.1f", it)}" },
                item.genres.takeIf { it.isNotBlank() },
                if (item.isEpisode) "S${item.season} E${item.episode}" else null,
            ).joinToString(" · ")
            Text(metadata.ifBlank { "Apri dettaglio" }, maxLines = 2, overflow = TextOverflow.Ellipsis)
        },
        leadingContent = {
            AppImage(
                model = item.posterUrl,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.size(width = 52.dp, height = 76.dp).clip(RoundedCornerShape(6.dp)),
            )
        },
        trailingContent = { Icon(Icons.Default.Info, contentDescription = "Dettagli") },
        modifier = Modifier.clickable { onClick(item) },
    )
}

private fun continueWatchingActionLabel(
    item: ContentItem,
    progressItem: ContentItem?,
): String {
    if (progressItem == null) return "Riproduci"
    if (item.isSeries && !item.isEpisode &&
        progressItem.season > 0 && progressItem.episode > 0
    ) {
        return String.format(
            Locale.ROOT,
            "Continua S%02dE%02d",
            progressItem.season,
            progressItem.episode,
        )
    }
    return if (progressItem.progressMs > 0L) "Riprendi" else "Continua"
}

@Composable
private fun DetailPage(
    item: ContentItem,
    progressItem: ContentItem?,
    overview: String,
    episodes: List<ContentItem>,
    selectedSeason: Int,
    loading: Boolean,
    onSeason: (Int) -> Unit,
    onPlay: (ContentItem, Boolean) -> Unit,
    onDownload: (ContentItem) -> Unit,
    onTrailer: (ContentItem) -> Unit,
    onRemoveProgress: (ContentItem) -> Unit,
    isTelevision: Boolean,
) {
    val seasons = episodes.map { it.season.takeIf { season -> season > 0 } ?: 1 }.distinct().sorted()
    val visibleEpisodes = episodes.filter { (it.season.takeIf { season -> season > 0 } ?: 1) == selectedSeason }
    val hasEpisodePicker = item.isSeries || episodes.isNotEmpty()
    var plotExpanded by rememberSaveable(item.stableKey) { mutableStateOf(false) }
    val displayPlot = overview.ifBlank { item.plot }
    val primaryActionFocus = remember { FocusRequester() }
    LaunchedEffect(isTelevision, item.stableKey, hasEpisodePicker) {
        if (isTelevision) {
            delay(120)
            runCatching { primaryActionFocus.requestFocus() }
        }
    }
    LazyColumn(
        Modifier.fillMaxSize().focusGroup(),
        contentPadding = PaddingValues(bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            AppImage(
                model = item.backdropUrl.ifBlank { item.posterUrl },
                fallbackModel = item.posterUrl.takeIf { it.isNotBlank() },
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxWidth().height(if (isTelevision) 140.dp else 220.dp),
            )
        }
        item {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                AppImage(
                    model = item.posterUrl,
                    contentDescription = item.title,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.width(108.dp).aspectRatio(2f / 3f).clip(RoundedCornerShape(8.dp)),
                )
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(item.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    val facts = listOfNotNull(
                        item.year.takeIf { it > 0 }?.toString(),
                        item.certification.takeIf { it.isNotBlank() },
                        item.runtimeMinutes.takeIf { it > 0 }?.let(::formatRuntimeMinutes),
                        item.country.takeIf { it.isNotBlank() },
                        item.genres.takeIf { it.isNotBlank() },
                        item.rating.takeIf { it > 0 }?.let { "★ ${String.format(Locale.US, "%.1f", it)}" },
                    ).joinToString(" · ")
                    if (facts.isNotBlank()) Text(facts, style = MaterialTheme.typography.bodyMedium)
                    if (!item.isLive) {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(
                                onClick = { onPlay(item, progressItem != null) },
                                modifier = if (isTelevision) {
                                    Modifier.focusRequester(primaryActionFocus)
                                } else {
                                    Modifier
                                },
                            ) {
                                Icon(Icons.Default.PlayArrow, contentDescription = null)
                                Spacer(Modifier.width(4.dp))
                                Text(continueWatchingActionLabel(item, progressItem))
                            }
                            if ((!hasEpisodePicker || item.isEpisode) && progressItem == null) {
                                TextButton(onClick = { onDownload(item) }) {
                                    Icon(Icons.Default.Download, contentDescription = null)
                                    Text(" Scarica")
                                }
                            }
                        }
                    }
                    TextButton(
                        onClick = { onTrailer(item) },
                    ) {
                        Icon(Icons.Default.PlayArrow, contentDescription = null)
                        Text(" Trailer")
                    }
                    if (progressItem != null) {
                        TextButton(onClick = { onRemoveProgress(item) }) {
                            Icon(Icons.Default.DeleteOutline, contentDescription = null)
                            Text(" Rimuovi da Continua a guardare")
                        }
                    }
                }
            }
        }
        if (item.hasEditorialCredits()) {
            item {
                EditorialCreditsPanel(
                    item = item,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    television = false,
                )
            }
        }
        if (displayPlot.isNotBlank()) {
            item {
                Card(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Column(
                        Modifier.padding(16.dp).animateContentSize(),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                    Text("Trama", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        Text(
                            displayPlot,
                            style = MaterialTheme.typography.bodyLarge,
                            maxLines = if (plotExpanded) Int.MAX_VALUE else 5,
                            overflow = TextOverflow.Ellipsis,
                        )
                        if (displayPlot.length > 220) {
                            TextButton(onClick = { plotExpanded = !plotExpanded }) {
                                Text(if (plotExpanded) "Mostra meno" else "Leggi tutta la trama")
                            }
                        }
                    }
                }
            }
        }
        if (hasEpisodePicker) {
            item {
                Text(
                    "Episodi",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
            }
            if (seasons.size > 1) {
                item {
                    LazyRow(
                        contentPadding = PaddingValues(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(seasons) { season ->
                            FilterChip(
                                selected = season == selectedSeason,
                                onClick = { onSeason(season) },
                                label = { Text("Stagione $season") },
                            )
                        }
                    }
                }
            }
            if (visibleEpisodes.isEmpty() && loading) {
                item { Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
            } else {
                itemsIndexed(
                    visibleEpisodes,
                    key = { index, episode -> "${episode.stableKey}:$index" },
                ) { _, episode ->
                    EpisodeRow(
                        item = episode,
                        onPlay = { onPlay(episode, episode.progressMs > 0) },
                        onDownload = { onDownload(episode) },
                    )
                    HorizontalDivider(Modifier.padding(horizontal = 16.dp))
                }
            }
        }
    }
}

@Composable
private fun EpisodeRow(item: ContentItem, onPlay: () -> Unit, onDownload: () -> Unit) {
    var expanded by rememberSaveable(item.stableKey) { mutableStateOf(false) }
    ListItem(
        headlineContent = { Text(item.title, maxLines = 2, overflow = TextOverflow.Ellipsis) },
        supportingContent = {
            Column {
                if (item.progressFraction > 0f) {
                    LinearProgressIndicator(progress = { item.progressFraction }, modifier = Modifier.fillMaxWidth())
                    Text("Riprendi da ${formatDuration(item.progressMs)}")
                }
                if (item.plot.isNotBlank()) {
                    Text(
                        item.plot,
                        maxLines = if (expanded) Int.MAX_VALUE else 3,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.animateContentSize().clickable { expanded = !expanded },
                    )
                    if (item.plot.length > 150) {
                        TextButton(onClick = { expanded = !expanded }) {
                            Text(if (expanded) "Chiudi trama" else "Leggi trama")
                        }
                    }
                }
            }
        },
        leadingContent = {
            AppImage(
                model = item.backdropUrl.ifBlank { item.posterUrl },
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.size(width = 112.dp, height = 64.dp).clip(RoundedCornerShape(6.dp)),
            )
        },
        trailingContent = {
            Row {
                IconButton(onClick = onDownload) {
                    Icon(Icons.Default.Download, contentDescription = "Scarica")
                }
                IconButton(onClick = onPlay) {
                    Icon(Icons.Default.PlayArrow, contentDescription = "Riproduci")
                }
            }
        },
        modifier = Modifier.clickable(onClick = onPlay),
    )
}

@Composable
private fun ErrorState(message: String, retry: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(message, color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f))
        IconButton(onClick = retry) { Icon(Icons.Default.Refresh, contentDescription = "Riprova") }
    }
}

private fun formatDuration(milliseconds: Long): String {
    val totalSeconds = milliseconds.coerceAtLeast(0) / 1000
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds)
    else "%d:%02d".format(minutes, seconds)
}
