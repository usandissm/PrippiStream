package com.prippi.stream

import android.app.PictureInPictureParams
import android.content.Context
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.util.Rational
import android.view.Gravity
import android.view.GestureDetector
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.addCallback
import androidx.media3.common.C
import androidx.media3.common.AudioAttributes
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionParameters
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.drm.DefaultDrmSessionManager
import androidx.media3.exoplayer.drm.FrameworkMediaDrm
import androidx.media3.exoplayer.drm.HttpMediaDrmCallback
import androidx.media3.exoplayer.drm.LocalMediaDrmCallback
import androidx.media3.exoplayer.dash.DashMediaSource
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.session.MediaSession
import androidx.media3.ui.PlayerView
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.TrackSelectionDialogBuilder
import com.prippi.stream.playback.LiveChannelSwitchPolicy
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/**
 * Measures the centred header content from the real parent width on every layout pass.
 * This avoids freezing a portrait displayMetrics width while PlayerActivity is entering
 * its forced landscape orientation.
 */
private class ResponsivePlayerHeader(context: Context) : FrameLayout(context) {
    var centerContent: View? = null

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        centerContent?.let { content ->
            val targetWidth = PlayerLayoutPolicy.headerContentWidth(
                View.MeasureSpec.getSize(widthMeasureSpec),
            )
            if (content.layoutParams.width != targetWidth) {
                content.layoutParams.width = targetWidth
            }
        }
        super.onMeasure(widthMeasureSpec, heightMeasureSpec)
    }
}

/** Player nativo Media3 con bootstrap VixCloud e salvataggio posizione. */
open class PlayerActivity : ComponentActivity() {
    private var player: ExoPlayer? = null
    private var mediaSession: MediaSession? = null
    private var bootstrapWebView: WebView? = null
    private lateinit var progressStore: WatchProgressStore
    private lateinit var mediaTrackPreferenceStore: MediaTrackPreferenceStore
    private var mediaTrackPreferenceKey: String? = null
    private var progressKey = ""
    private var contentJson = ""
    private var startPositionMs = 0L
    private var downloadItemJson = ""
    private var downloadTargetHeight = 0
    private var downloadPreparationMode = false
    private lateinit var rootView: FrameLayout
    private lateinit var playerView: PlayerView
    private lateinit var statusView: TextView
    private lateinit var liveGuideView: TextView
    private var liveGuideText = ""
    private lateinit var trackControlsView: View
    private var televisionTitleView: TextView? = null
    private var televisionMetadataView: TextView? = null
    private var televisionStateView: TextView? = null
    private var televisionPrimaryAction: TextView? = null
    private var televisionFirstAction: View? = null
    private var televisionFirstBottomAction: View? = null
    private var episodesActionView: View? = null
    private var nextEpisodeActionView: View? = null
    private var televisionTimelineView: View? = null
    private var televisionSeekBar: SeekBar? = null
    private var televisionPositionView: TextView? = null
    private var televisionDurationView: TextView? = null
    private var televisionSeeking = false
    private var mobileLivePositionView: TextView? = null
    private var televisionPlayer = false
    private var tabletPlayer = false
    private var liveAacOverrideApplied = false
    private val controlsHandler = Handler(Looper.getMainLooper())
    private val hideTelevisionControls = Runnable { setTelevisionControlsVisible(false) }
    private val updateTelevisionTimeline = object : Runnable {
        override fun run() {
            refreshTelevisionTimeline()
            if (::trackControlsView.isInitialized && trackControlsView.visibility == View.VISIBLE) {
                controlsHandler.postDelayed(this, 500)
            }
        }
    }
    private var bootstrapCallbackHost: View? = null
    private val bootstrapCallbacks = mutableListOf<Runnable>()
    private var playbackCandidates: List<PlaybackRequest> = emptyList()
    private var currentCandidateIndex = 0
    private var currentSubtitleUrls: List<String> = emptyList()
    private var liveRowItems = JSONArray()
    private var liveRowIndex = -1
    private var liveRetryCount = 0
    private val liveSwitching = AtomicBoolean(false)
    private val playbackGeneration = AtomicLong(0L)
    private val asyncOperationGeneration = AtomicLong(0L)
    @Volatile private var activityStarted = true
    private var lastLiveSwitchAtMs = 0L
    private var episodeQueueItems = JSONArray()
    private var episodeQueueKey = ""
    private var episodeQueueSize = 0
    private var episodeQueueIndex = -1
    private val episodeSwitching = AtomicBoolean(false)
    private var upNextOverlay: View? = null
    private var upNextTimerView: TextView? = null
    private var upNextProgressView: ProgressBar? = null
    private var upNextTriggered = false
    private var upNextPromptHidden = false
    private val upNextHandler = Handler(Looper.getMainLooper())
    private val updateUpNextPrompt = object : Runnable {
        override fun run() {
            updateUpNextState()
            if (activityStarted && !isFinishing) {
                upNextHandler.postDelayed(this, 1_000)
            }
        }
    }
    private var restartAfterStop = false
    private var resumePlaybackAfterBackground = false
    private var currentPictureInPictureParams: PictureInPictureParams? = null
    private var pictureInPictureSessionActive = false
    private val progressHandler = Handler(Looper.getMainLooper())
    private val progressSaver = object : Runnable {
        override fun run() {
            persistProgress()
            progressHandler.postDelayed(this, 5_000)
        }
    }

    private fun nextPlaybackGeneration(): Long = playbackGeneration.incrementAndGet()
    private fun nextAsyncOperationGeneration(): Long = asyncOperationGeneration.incrementAndGet()

    private fun isPlaybackGenerationActive(generation: Long): Boolean =
        activityStarted &&
            playbackGeneration.get() == generation &&
            !isFinishing &&
            !isDestroyed

    private fun isAsyncOperationActive(generation: Long): Boolean =
        activityStarted &&
            asyncOperationGeneration.get() == generation &&
            !isFinishing &&
            !isDestroyed

    private fun postBootstrapCallback(host: View, delayMs: Long, action: () -> Unit) {
        if (bootstrapCallbackHost !== host) {
            clearBootstrapCallbacks()
            bootstrapCallbackHost = host
        }
        val callback = Runnable(action)
        bootstrapCallbacks += callback
        host.postDelayed(callback, delayMs)
    }

    private fun clearBootstrapCallbacks() {
        bootstrapCallbackHost?.let { host ->
            bootstrapCallbacks.forEach(host::removeCallbacks)
        }
        bootstrapCallbacks.clear()
        bootstrapCallbackHost = null
    }

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        downloadPreparationMode =
            intent.getStringExtra("download_item_json").orEmpty().isNotBlank()
        if (downloadPreparationMode) {
            overridePendingTransition(0, 0)
        }
        super.onCreate(savedInstanceState)
        if (!downloadPreparationMode) {
            // Una riproduzione video è attività utente: impedisce al timeout
            // di sistema di spegnere lo schermo finché il player è aperto.
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        }
        val deviceProfile = DeviceProfile.detect(this)
        televisionPlayer =
            intent.getBooleanExtra("television_player", false) || deviceProfile.isTelevision
        tabletPlayer = deviceProfile.isTablet && !deviceProfile.isTelevision
        onBackPressedDispatcher.addCallback(this) {
            if (upNextOverlay != null) {
                hideUpNextPrompt(cancelAutoplay = true)
            } else {
                finish()
            }
        }
        if (!downloadPreparationMode) enterImmersiveMode()

        val url = intent.getStringExtra("url") ?: return finish()
        val bootstrapUrl = intent.getStringExtra("bootstrap_url").orEmpty()
        val manifest = intent.getStringExtra("manifest") ?: "hls"
        val audioLang = intent.getStringExtra("audio") ?: "it"
        val headers = parseHeaders(intent.getStringExtra("headers"))
        downloadItemJson = intent.getStringExtra("download_item_json").orEmpty()
        downloadTargetHeight = intent.getIntExtra("download_target_height", 0).coerceAtLeast(0)
        progressStore = WatchProgressStore(applicationContext)
        mediaTrackPreferenceStore = MediaTrackPreferenceStore(applicationContext)
        progressKey = intent.getStringExtra("progress_key").orEmpty()
        contentJson = intent.getStringExtra("content_json").orEmpty()
        mediaTrackPreferenceKey = mediaPreferenceKey(contentJson)
        startPositionMs = intent.getLongExtra("start_position_ms", 0L).coerceAtLeast(0L)
        liveRowItems = runCatching {
            JSONArray(intent.getStringExtra("live_row_items_json").orEmpty())
        }.getOrDefault(JSONArray())
        liveRowIndex = intent.getIntExtra("live_row_index", -1)
        updateLiveGuideText(
            intent.getStringExtra("live_channel_title").orEmpty(),
            intent.getStringExtra("live_programme").orEmpty(),
        )
        episodeQueueItems = runCatching {
            JSONArray(intent.getStringExtra("episode_queue_json").orEmpty())
        }.getOrDefault(JSONArray())
        episodeQueueKey = intent.getStringExtra("episode_queue_key").orEmpty()
        episodeQueueSize = intent.getIntExtra("episode_queue_size", episodeQueueItems.length())
            .coerceAtLeast(0)
        episodeQueueIndex = intent.getIntExtra("episode_queue_index", -1)

        playerView = PlayerView(this).apply {
            isFocusable = true
            isFocusableInTouchMode = true
            // L'immagine resta sempre intera: nessun crop, zoom o stretch.
            // Le eventuali bande nere sono parte del corretto aspect ratio.
            resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
            useController = false
        }
        statusView = TextView(this).apply {
            text = "Caricamento…"
            setTextColor(Color.WHITE)
            textSize = if (televisionPlayer) 19f else if (tabletPlayer) 18f else 16f
            gravity = Gravity.CENTER
            setPadding(
                if (televisionPlayer) 38 else 28,
                if (televisionPlayer) 22 else 18,
                if (televisionPlayer) 38 else 28,
                if (televisionPlayer) 22 else 18,
            )
            background = if (televisionPlayer) {
                GradientDrawable().apply {
                    cornerRadius = 14f
                    setColor(Color.argb(220, 7, 12, 19))
                    setStroke(1, Color.argb(72, 255, 255, 255))
                }
            } else {
                GradientDrawable().apply { setColor(Color.argb(180, 0, 0, 0)) }
            }
        }
        liveGuideView = TextView(this).apply {
            text = liveGuideText
            setTextColor(Color.WHITE)
            textSize = if (tabletPlayer) 16f else 14f
            gravity = Gravity.START
            maxLines = 6
            maxWidth = (resources.displayMetrics.widthPixels * 0.72f).toInt()
            setPadding(22, 16, 22, 16)
            setBackgroundColor(Color.argb(205, 8, 13, 20))
            visibility = View.GONE
        }
        trackControlsView = buildPrippiControls()
        rootView = FrameLayout(this).apply {
            if (downloadPreparationMode) setBackgroundColor(Color.TRANSPARENT)
            addView(
                playerView,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
            addView(
                statusView,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.CENTER,
                ),
            )
            addView(
                trackControlsView,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    Gravity.CENTER,
                ),
            )
            addView(
                liveGuideView,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.TOP or Gravity.START,
                ).apply { setMargins(24, 24, 24, 24) },
            )
        }
        if (downloadPreparationMode) {
            playerView.visibility = View.GONE
            statusView.alpha = 0f
            trackControlsView.visibility = View.GONE
            liveGuideView.visibility = View.GONE
        }
        setContentView(rootView)
        if (!downloadPreparationMode) playerView.requestFocus()
        setTelevisionControlsVisible(true)
        val seekGestures = GestureDetector(
            this,
            object : GestureDetector.SimpleOnGestureListener() {
                override fun onDown(event: MotionEvent): Boolean = true

                override fun onSingleTapConfirmed(event: MotionEvent): Boolean {
                    setTelevisionControlsVisible(trackControlsView.visibility != View.VISIBLE)
                    return true
                }

                override fun onDoubleTap(event: MotionEvent): Boolean {
                    if (liveRowItems.length() > 0) {
                        setTelevisionControlsVisible(true)
                        return true
                    }
                    val delta = if (event.x < playerView.width / 2f) -10_000L else 10_000L
                    val handled = seekBy(delta)
                    setTelevisionControlsVisible(true)
                    return handled
                }
            },
        )
        playerView.setOnTouchListener { _, event ->
            seekGestures.onTouchEvent(event)
        }
        trackControlsView.setOnTouchListener { _, event ->
            seekGestures.onTouchEvent(event)
        }

        val primary = PlaybackRequest(
            url = url,
            bootstrapUrl = bootstrapUrl,
            manifest = manifest,
            audioLanguage = audioLang,
            headersJson = JSONObject(headers).toString(),
        )
        playbackCandidates = parsePlaybackCandidates(
            intent.getStringExtra("playback_candidates_json"),
        ).ifEmpty { listOf(primary) }
        android.util.Log.i(
            "Prippi",
            "Piano playback: ${playbackCandidates.size} sorgente/i · " +
                playbackCandidates.joinToString { "${it.server}:${it.label}" },
        )
        startPlaybackCandidate(0)
    }

    private fun updateLiveGuideText(channelTitle: String, programme: String) {
        if (channelTitle.isBlank()) {
            liveGuideText = ""
            refreshTelevisionOsd()
            return
        }
        val guideLines = programme.lineSequence()
            .map { it.trim() }
            .filter { it.isNotBlank() && !it.equals(channelTitle, ignoreCase = true) }
            .map { line -> line.replace(Regex("^IN ONDA", RegexOption.IGNORE_CASE), "Adesso") }
            .toList()
        liveGuideText = buildString {
            append(channelTitle)
            if (guideLines.isNotEmpty()) {
                append('\n')
                append(guideLines.joinToString("\n"))
            } else {
                append("\nProgrammazione non disponibile")
            }
        }
        refreshTelevisionOsd()
    }

    private fun enterImmersiveMode() {
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    private fun canUsePictureInPicture(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !downloadPreparationMode &&
            !televisionPlayer &&
            !isFinishing &&
            player != null &&
            player?.playbackState != Player.STATE_ENDED

    private fun updatePictureInPictureParams() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O ||
            downloadPreparationMode || televisionPlayer
        ) return
        val params = PictureInPictureParams.Builder()
            .setAspectRatio(Rational(16, 9))
            .apply {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    setAutoEnterEnabled(
                        player?.playWhenReady == true &&
                            player?.playbackState != Player.STATE_ENDED,
                    )
                    setSeamlessResizeEnabled(true)
                }
            }
            .build()
        currentPictureInPictureParams = params
        setPictureInPictureParams(params)
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        // Da Android 12 l'ingresso è gestito automaticamente e senza lo
        // scatto visivo della vecchia callback. Android 8-11 usa questo
        // fallback quando Home, Recenti o una notifica portano fuori app.
        if (Build.VERSION.SDK_INT in Build.VERSION_CODES.O until Build.VERSION_CODES.S &&
            canUsePictureInPicture() &&
            player?.playWhenReady == true
        ) {
            val params = currentPictureInPictureParams ?: return
            runCatching { enterPictureInPictureMode(params) }
                .onFailure { error ->
                    android.util.Log.w("Prippi", "Picture-in-Picture non disponibile", error)
                }
        }
    }

    override fun onPictureInPictureModeChanged(
        isInPictureInPictureMode: Boolean,
        newConfig: Configuration,
    ) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
        if (!::trackControlsView.isInitialized) return
        if (isInPictureInPictureMode) {
            pictureInPictureSessionActive = true
            controlsHandler.removeCallbacksAndMessages(null)
            trackControlsView.animate().cancel()
            trackControlsView.visibility = View.GONE
            liveGuideView.visibility = View.GONE
            upNextOverlay?.visibility = View.GONE
        } else if (!isFinishing) {
            enterImmersiveMode()
            setTelevisionControlsVisible(true)
        }
    }

    override fun onResume() {
        super.onResume()
        // Viene azzerato solo quando il player torna realmente a schermo
        // intero. Se la finestrella viene chiusa, onStop arriva senza un nuovo
        // onResume e può riconoscere la chiusura definitiva del PiP.
        if (!isInPictureInPictureMode) pictureInPictureSessionActive = false
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && !downloadPreparationMode) enterImmersiveMode()
    }

    override fun finish() {
        super.finish()
        if (downloadPreparationMode) overridePendingTransition(0, 0)
    }

    private fun seekBy(deltaMs: Long): Boolean {
        val current = player ?: return false
        if (!current.isCurrentMediaItemSeekable) return false
        val duration = current.duration.takeIf { it > 0 } ?: Long.MAX_VALUE
        val target = (current.currentPosition + deltaMs).coerceIn(0L, duration)
        current.seekTo(target)
        refreshTelevisionTimeline()
        statusView.text = if (deltaMs < 0) "−10 secondi" else "+10 secondi"
        statusView.visibility = View.VISIBLE
        statusView.postDelayed({
            if (!isFinishing && player?.playbackState == Player.STATE_READY) {
                statusView.visibility = View.GONE
            }
        }, 850)
        return true
    }

    private fun handleTimelineRemoteKey(keyCode: Int, event: KeyEvent): Boolean {
        if (event.action != KeyEvent.ACTION_DOWN) return false
        val delta = when (keyCode) {
            KeyEvent.KEYCODE_DPAD_LEFT -> -10_000L
            KeyEvent.KEYCODE_DPAD_RIGHT -> 10_000L
            else -> return false
        }
        controlsHandler.removeCallbacks(hideTelevisionControls)
        val handled = seekBy(delta)
        if (handled) scheduleTelevisionControlsHide()
        return handled
    }

    private fun buildMobileControls(): View = LinearLayout(this).apply {
        val controlHeight = if (tabletPlayer) 56 else 48
        val controlWidth = if (tabletPlayer) 62 else 52
        val horizontalPadding = if (tabletPlayer) 18 else 14
        val controlTextSize = if (tabletPlayer) 16f else 14f
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(6.dp(), 5.dp(), 6.dp(), 5.dp())
        background = GradientDrawable().apply {
            cornerRadius = 24.dp().toFloat()
            setColor(Color.argb(218, 6, 11, 18))
            setStroke(1.dp(), Color.argb(72, 255, 255, 255))
        }

        fun action(label: String, onClick: () -> Unit): TextView =
            TextView(this@PlayerActivity).apply {
                text = label
                id = View.generateViewId()
                isFocusable = true
                isClickable = true
                gravity = Gravity.CENTER
                minHeight = controlHeight.dp()
                minWidth = controlWidth.dp()
                setPadding(horizontalPadding.dp(), 0, horizontalPadding.dp(), 0)
                setTextColor(Color.WHITE)
                textSize = controlTextSize
                background = GradientDrawable().apply {
                    cornerRadius = 20.dp().toFloat()
                    setColor(Color.TRANSPARENT)
                }
                setOnClickListener { onClick() }
            }

        if (liveRowItems.length() > 1 && liveRowIndex >= 0) {
            addView(action("CH −") { switchLiveChannel(-1) })
            addView(TextView(this@PlayerActivity).also { position ->
                mobileLivePositionView = position
                position.gravity = Gravity.CENTER
                position.minWidth = (if (tabletPlayer) 70 else 58).dp()
                position.setTextColor(Color.rgb(184, 211, 238))
                position.textSize = if (tabletPlayer) 15f else 13f
                position.text = mobileLivePositionText()
            })
            addView(action("CH +") { switchLiveChannel(1) })
        }
        if (episodeQueueIndex >= 0 && episodeQueueIndex + 1 < episodeQueueLength()) {
            addView(action("Episodio successivo") { switchToNextEpisode() })
        }
        addView(action("Tracce") { showMobileTrackMenu() })
        addView(action("Esci") { finish() })
    }

    private fun showMobileTrackMenu() {
        val labels = arrayOf("Qualità video", "Traccia audio", "Sottotitoli")
        val types = intArrayOf(C.TRACK_TYPE_VIDEO, C.TRACK_TYPE_AUDIO, C.TRACK_TYPE_TEXT)
        android.app.AlertDialog.Builder(this)
            .setTitle("Tracce")
            .setItems(labels) { _, index -> showTrackSelection(labels[index], types[index]) }
            .setNegativeButton("Chiudi", null)
            .show()
    }

    private fun showAudioSubtitleMenu() {
        controlsHandler.removeCallbacks(hideTelevisionControls)
        val labels = arrayOf("Traccia audio", "Sottotitoli")
        val types = intArrayOf(C.TRACK_TYPE_AUDIO, C.TRACK_TYPE_TEXT)
        android.app.AlertDialog.Builder(this)
            .setTitle("Audio e sottotitoli")
            .setItems(labels) { _, index -> showTrackSelection(labels[index], types[index]) }
            .setNegativeButton("Chiudi", null)
            .setOnDismissListener { setTelevisionControlsVisible(true) }
            .show()
    }

    private fun mobileLivePositionText(): String =
        if (liveRowIndex >= 0 && liveRowItems.length() > 0) {
            "${liveRowIndex + 1}/${liveRowItems.length()}"
        } else {
            ""
        }

    private fun Int.dp(): Int = (this * resources.displayMetrics.density).toInt()

    private fun televisionUiScale(): Float = PlayerLayoutPolicy.landscapeUiScale(
        resources.configuration.screenWidthDp,
        resources.configuration.screenHeightDp,
    )

    /**
     * OSD unico per telefono, tablet e TV. La composizione riprende la reference:
     * intestazione sospesa, trasporto al centro, timeline e azioni in basso.
     * Il video rimane nel PlayerView sottostante e non viene mai ridimensionato
     * dall'overlay.
     */
    private fun buildPrippiControls(): View = FrameLayout(this).apply {
        val scale = televisionUiScale()
        val textScale = scale.coerceIn(0.78f, 1.16f)
        fun scaled(value: Int) = (value * scale).toInt().coerceAtLeast(1)
        val live = liveRowItems.length() > 0 || liveGuideText.isNotBlank()

        isFocusable = false
        isClickable = false
        background = GradientDrawable(
            GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(
                Color.argb(220, 0, 0, 0),
                Color.argb(42, 0, 0, 0),
                Color.argb(22, 0, 0, 0),
                Color.argb(224, 0, 0, 0),
            ),
        )

        fun focusBackground(focused: Boolean, primary: Boolean, round: Boolean) =
            GradientDrawable().apply {
                cornerRadius = if (round) scaled(42).dp().toFloat() else scaled(8).dp().toFloat()
                setColor(
                    when {
                        focused -> Color.WHITE
                        primary -> Color.argb(224, 229, 9, 20)
                        else -> Color.argb(132, 12, 17, 24)
                    },
                )
                setStroke(
                    if (focused) scaled(3).dp() else scaled(1).dp(),
                    if (focused) Color.rgb(255, 213, 79)
                    else Color.argb(105, 255, 255, 255),
                )
            }

        fun action(
            label: String,
            primary: Boolean = false,
            round: Boolean = false,
            central: Boolean = false,
            onClick: () -> Unit,
        ): TextView = TextView(this@PlayerActivity).apply {
            text = label
            contentDescription = label.replace('\n', ' ')
            id = View.generateViewId()
            setTextColor(Color.WHITE)
            textSize = when {
                central -> 25f * textScale
                else -> 16f * textScale
            }
            setTypeface(typeface, Typeface.BOLD)
            gravity = Gravity.CENTER
            isFocusable = true
            isFocusableInTouchMode = televisionPlayer
            isClickable = true
            minWidth = scaled(if (central) 86 else 116).dp()
            minHeight = scaled(if (central) 76 else 48).dp()
            setPadding(
                scaled(if (central) 15 else 20).dp(),
                scaled(if (central) 9 else 11).dp(),
                scaled(if (central) 15 else 20).dp(),
                scaled(if (central) 9 else 11).dp(),
            )
            background = focusBackground(false, primary, round)
            setOnFocusChangeListener { view, focused ->
                view.animate().cancel()
                view.animate()
                    .scaleX(if (focused) 1.09f else 1f)
                    .scaleY(if (focused) 1.09f else 1f)
                    .setDuration(100)
                    .start()
                setTextColor(if (focused) Color.rgb(7, 13, 20) else Color.WHITE)
                background = focusBackground(focused, primary, round)
                if (focused) controlsHandler.removeCallbacks(hideTelevisionControls)
                else scheduleTelevisionControlsHide()
            }
            setOnClickListener {
                onClick()
                setTelevisionControlsVisible(true)
            }
        }

        val header = ResponsivePlayerHeader(this@PlayerActivity).apply {
            setPadding(
                scaled(38).dp(),
                scaled(22).dp(),
                scaled(38).dp(),
                scaled(8).dp(),
            )
            minimumHeight = scaled(112).dp()
        }
        val back = action("←", round = true, central = true) { finish() }.apply {
            contentDescription = "Indietro"
            textSize = 31f * textScale
            minWidth = scaled(62).dp()
            minHeight = scaled(58).dp()
            setPadding(0, 0, 0, scaled(3).dp())
        }
        header.addView(
            back,
            FrameLayout.LayoutParams(
                scaled(68).dp(),
                scaled(62).dp(),
                Gravity.TOP or Gravity.START,
            ),
        )
        val headerContent = LinearLayout(this@PlayerActivity).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER
                addView(TextView(this@PlayerActivity).also { title ->
                    televisionTitleView = title
                    title.setTextColor(Color.WHITE)
                    title.textSize = 24f * textScale
                    title.setTypeface(title.typeface, Typeface.BOLD)
                    title.gravity = Gravity.CENTER
                    title.maxLines = 2
                })
                addView(TextView(this@PlayerActivity).also { metadata ->
                    televisionMetadataView = metadata
                    metadata.setTextColor(Color.rgb(218, 224, 232))
                    metadata.textSize = 14f * textScale
                    metadata.gravity = Gravity.CENTER
                    metadata.maxLines = 2
                    metadata.setPadding(0, scaled(3).dp(), 0, 0)
                })
            }
        header.centerContent = headerContent
        header.addView(
            headerContent,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP or Gravity.CENTER_HORIZONTAL,
            ),
        )
        header.addView(
            TextView(this@PlayerActivity).also { state ->
                televisionStateView = state
                state.setTextColor(Color.WHITE)
                state.textSize = 13f * textScale
                state.setTypeface(state.typeface, Typeface.BOLD)
                state.gravity = Gravity.END or Gravity.CENTER_VERTICAL
                state.maxLines = 2
            },
            FrameLayout.LayoutParams(
                scaled(240).dp(),
                scaled(58).dp(),
                Gravity.TOP or Gravity.END,
            ),
        )
        addView(
            header,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP,
            ),
        )

        val transport = LinearLayout(this@PlayerActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        fun addTransport(button: View) {
            transport.addView(
                button,
                LinearLayout.LayoutParams(
                    scaled(96).dp(),
                    scaled(86).dp(),
                ).apply {
                    marginStart = scaled(11).dp()
                    marginEnd = scaled(11).dp()
                },
            )
        }
        if (live && liveRowItems.length() > 1 && liveRowIndex >= 0) {
            addTransport(action("CH\n−", round = true, central = true) {
                switchLiveChannel(-1)
            })
        } else if (!live) {
            addTransport(action("↶\n10", round = true, central = true) {
                seekBy(-10_000L)
            })
        }
        val playPause = action("❚❚", primary = false, round = true, central = true) {
            player?.let { if (it.isPlaying) it.pause() else it.play() }
            refreshTelevisionOsd()
        }.also {
            televisionPrimaryAction = it
            televisionFirstAction = it
            it.textSize = 34f * textScale
        }
        addTransport(playPause)
        if (live && liveRowItems.length() > 1 && liveRowIndex >= 0) {
            addTransport(action("CH\n+", round = true, central = true) {
                switchLiveChannel(1)
            })
        } else if (!live) {
            addTransport(action("↷\n10", round = true, central = true) {
                seekBy(10_000L)
            })
        }
        addView(
            transport,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER,
            ),
        )

        val bottom = LinearLayout(this@PlayerActivity).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(
                scaled(48).dp(),
                scaled(8).dp(),
                scaled(48).dp(),
                scaled(24).dp(),
            )
        }
        bottom.addView(
            LinearLayout(this@PlayerActivity).also { timeline ->
                televisionTimelineView = timeline
                timeline.orientation = LinearLayout.HORIZONTAL
                timeline.gravity = Gravity.CENTER_VERTICAL

                fun timeLabel(): TextView = TextView(this@PlayerActivity).apply {
                    setTextColor(Color.WHITE)
                    textSize = 14f * textScale
                    setTypeface(typeface, Typeface.BOLD)
                    gravity = Gravity.CENTER
                    minWidth = scaled(72).dp()
                }
                timeline.addView(timeLabel().also {
                    televisionPositionView = it
                    it.text = "0:00"
                })
                timeline.addView(
                    SeekBar(this@PlayerActivity).also { seek ->
                        televisionSeekBar = seek
                        seek.id = View.generateViewId()
                        seek.max = 10_000
                        seek.isFocusable = true
                        seek.isFocusableInTouchMode = televisionPlayer
                        seek.setOnKeyListener { _, keyCode, event ->
                            handleTimelineRemoteKey(keyCode, event)
                        }
                        televisionPrimaryAction?.nextFocusDownId = seek.id
                        seek.progressTintList = ColorStateList.valueOf(Color.rgb(229, 9, 20))
                        seek.progressBackgroundTintList =
                            ColorStateList.valueOf(Color.argb(180, 183, 190, 200))
                        seek.thumbTintList = ColorStateList.valueOf(Color.WHITE)
                        seek.setOnSeekBarChangeListener(
                            object : SeekBar.OnSeekBarChangeListener {
                                override fun onProgressChanged(
                                    bar: SeekBar,
                                    progress: Int,
                                    fromUser: Boolean,
                                ) {
                                    if (!fromUser) return
                                    val duration = player?.duration
                                        ?.takeIf { it > 0 && it != C.TIME_UNSET }
                                        ?: return
                                    televisionPositionView?.text =
                                        formatPlaybackTime(duration * progress / bar.max)
                                }

                                override fun onStartTrackingTouch(bar: SeekBar) {
                                    televisionSeeking = true
                                    controlsHandler.removeCallbacks(hideTelevisionControls)
                                }

                                override fun onStopTrackingTouch(bar: SeekBar) {
                                    val duration = player?.duration
                                        ?.takeIf { it > 0 && it != C.TIME_UNSET }
                                    if (duration != null) {
                                        player?.seekTo(duration * bar.progress / bar.max)
                                    }
                                    televisionSeeking = false
                                    scheduleTelevisionControlsHide()
                                }
                            },
                        )
                        seek.setOnFocusChangeListener { view, focused ->
                            view.animate().cancel()
                            view.animate().scaleY(if (focused) 1.35f else 1f)
                                .setDuration(100).start()
                            seek.thumbTintList = ColorStateList.valueOf(
                                if (focused) Color.rgb(255, 213, 79) else Color.WHITE,
                            )
                            if (focused) controlsHandler.removeCallbacks(hideTelevisionControls)
                            else scheduleTelevisionControlsHide()
                        }
                    },
                    LinearLayout.LayoutParams(0, scaled(42).dp(), 1f).apply {
                        marginStart = scaled(10).dp()
                        marginEnd = scaled(10).dp()
                    },
                )
                timeline.addView(timeLabel().also {
                    televisionDurationView = it
                    it.text = "0:00"
                })
                timeline.visibility = if (live) View.GONE else View.INVISIBLE
            },
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { bottomMargin = scaled(10).dp() },
        )

        val actions = LinearLayout(this@PlayerActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        fun addBottomAction(view: View) {
            view.nextFocusUpId = televisionSeekBar?.id ?: View.NO_ID
            actions.addView(
                view,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                ).apply {
                    marginStart = scaled(6).dp()
                    marginEnd = scaled(6).dp()
                },
            )
            if (televisionFirstBottomAction == null) {
                televisionFirstBottomAction = view
                televisionSeekBar?.nextFocusDownId = view.id
            }
        }
        if (!live && episodeQueueLength() > 0) {
            addBottomAction(action("▣  Episodi") { showEpisodeSelection() }.also {
                episodesActionView = it
            })
        }
        addBottomAction(action("▤  Audio e sottotitoli") { showAudioSubtitleMenu() })
        if (!live && episodeQueueLength() > 1) {
            addBottomAction(action("▶|  Episodio successivo") { switchToNextEpisode() }.also {
                nextEpisodeActionView = it
                it.visibility = if (
                    episodeQueueIndex >= 0 && episodeQueueIndex + 1 < episodeQueueLength()
                ) View.VISIBLE else View.GONE
            })
        }
        bottom.addView(
            HorizontalScrollView(this@PlayerActivity).apply {
                isHorizontalScrollBarEnabled = false
                isFillViewport = true
                addView(
                    actions,
                    FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        Gravity.CENTER,
                    ),
                )
            },
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ),
        )
        addView(
            bottom,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM,
            ),
        )
        refreshTelevisionOsd()
    }

    private fun buildTelevisionControls(): View = FrameLayout(this).apply {
        val scale = televisionUiScale()
        val textScale = scale.coerceIn(0.88f, 1.16f)
        fun scaled(value: Int) = (value * scale).toInt().coerceAtLeast(1)
        isFocusable = false
        isClickable = false
        background = GradientDrawable(
            GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(
                Color.TRANSPARENT,
                Color.argb(16, 2, 5, 9),
                Color.argb(158, 3, 7, 12),
                Color.argb(248, 3, 7, 12),
            ),
        )

        addView(
            LinearLayout(this@PlayerActivity).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.START
                setPadding(
                    scaled(58).dp(),
                    scaled(26).dp(),
                    scaled(58).dp(),
                    scaled(30).dp(),
                )

                addView(TextView(this@PlayerActivity).also { title ->
                    televisionTitleView = title
                    title.setTextColor(Color.WHITE)
                    title.textSize = 31f * textScale
                    title.setTypeface(title.typeface, Typeface.BOLD)
                    title.maxLines = 1
                })

                addView(TextView(this@PlayerActivity).also { metadata ->
                    televisionMetadataView = metadata
                    metadata.setTextColor(Color.rgb(210, 220, 232))
                    metadata.textSize = 17f * textScale
                    metadata.maxLines = 2
                    metadata.setPadding(0, scaled(5).dp(), 0, 0)
                })

                addView(TextView(this@PlayerActivity).also { state ->
                    televisionStateView = state
                    state.setTextColor(Color.rgb(229, 9, 20))
                    state.textSize = 14f * textScale
                    state.setTypeface(state.typeface, Typeface.BOLD)
                    state.maxLines = 1
                    state.setPadding(0, scaled(7).dp(), 0, scaled(8).dp())
                })

                addView(
                    LinearLayout(this@PlayerActivity).also { timeline ->
                        televisionTimelineView = timeline
                        timeline.orientation = LinearLayout.HORIZONTAL
                        timeline.gravity = Gravity.CENTER_VERTICAL

                        fun timeLabel(): TextView = TextView(this@PlayerActivity).apply {
                            setTextColor(Color.WHITE)
                            textSize = 14f * textScale
                            setTypeface(typeface, Typeface.BOLD)
                            gravity = Gravity.CENTER
                            minWidth = scaled(62).dp()
                        }
                        timeline.addView(timeLabel().also {
                            televisionPositionView = it
                            it.text = "0:00"
                        })
                        timeline.addView(
                            SeekBar(this@PlayerActivity).also { seek ->
                                televisionSeekBar = seek
                                seek.id = View.generateViewId()
                                seek.max = 10_000
                                seek.isFocusable = true
                                seek.setOnKeyListener { _, keyCode, event ->
                                    handleTimelineRemoteKey(keyCode, event)
                                }
                                televisionPrimaryAction?.nextFocusDownId = seek.id
                                seek.progressTintList =
                                    ColorStateList.valueOf(Color.rgb(229, 9, 20))
                                seek.progressBackgroundTintList =
                                    ColorStateList.valueOf(Color.argb(150, 180, 188, 198))
                                seek.thumbTintList = ColorStateList.valueOf(Color.WHITE)
                                seek.setOnSeekBarChangeListener(
                                    object : SeekBar.OnSeekBarChangeListener {
                                        override fun onProgressChanged(
                                            bar: SeekBar,
                                            progress: Int,
                                            fromUser: Boolean,
                                        ) {
                                            if (!fromUser) return
                                            val duration = player?.duration
                                                ?.takeIf { it > 0 && it != C.TIME_UNSET }
                                                ?: return
                                            val position = duration * progress / bar.max
                                            televisionPositionView?.text =
                                                formatPlaybackTime(position)
                                            player?.seekTo(position)
                                        }

                                        override fun onStartTrackingTouch(bar: SeekBar) {
                                            televisionSeeking = true
                                            controlsHandler.removeCallbacks(hideTelevisionControls)
                                        }

                                        override fun onStopTrackingTouch(bar: SeekBar) {
                                            val duration = player?.duration
                                                ?.takeIf { it > 0 && it != C.TIME_UNSET }
                                            if (duration != null) {
                                                player?.seekTo(duration * bar.progress / bar.max)
                                            }
                                            televisionSeeking = false
                                            scheduleTelevisionControlsHide()
                                        }
                                    },
                                )
                                seek.setOnFocusChangeListener { view, focused ->
                                    view.scaleY = if (focused) 1.18f else 1f
                                    seek.thumbTintList = ColorStateList.valueOf(
                                        if (focused) Color.rgb(229, 9, 20) else Color.WHITE,
                                    )
                                    if (focused) {
                                        controlsHandler.removeCallbacks(hideTelevisionControls)
                                    } else {
                                        scheduleTelevisionControlsHide()
                                    }
                                }
                            },
                            LinearLayout.LayoutParams(
                                0,
                                scaled(34).dp(),
                                1f,
                            ).apply {
                                marginStart = scaled(12).dp()
                                marginEnd = scaled(12).dp()
                            },
                        )
                        timeline.addView(timeLabel().also {
                            televisionDurationView = it
                            it.text = "0:00"
                        })
                        timeline.visibility = View.GONE
                    },
                    LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                    ).apply { bottomMargin = scaled(10).dp() },
                )

                addView(LinearLayout(this@PlayerActivity).apply {
                    orientation = LinearLayout.HORIZONTAL
                    gravity = Gravity.CENTER_VERTICAL

                    fun action(label: String, onClick: () -> Unit): TextView {
                        val action = TextView(this@PlayerActivity).apply {
                            fun focusBackground(focused: Boolean) = GradientDrawable().apply {
                                cornerRadius = scaled(9).dp().toFloat()
                                setColor(
                                    if (focused) Color.rgb(238, 244, 250)
                                    else Color.argb(196, 22, 29, 38),
                                )
                                setStroke(
                                    if (focused) 0 else scaled(1).dp(),
                                    Color.argb(105, 210, 228, 245),
                                )
                            }
                            text = label
                            id = View.generateViewId()
                            setTextColor(Color.WHITE)
                            textSize = 16f * textScale
                            setTypeface(typeface, Typeface.BOLD)
                            gravity = Gravity.CENTER
                            isFocusable = true
                            isClickable = true
                            nextFocusUpId = televisionSeekBar?.id ?: View.NO_ID
                            minHeight = scaled(48).dp()
                            setPadding(
                                scaled(20).dp(),
                                scaled(11).dp(),
                                scaled(20).dp(),
                                scaled(11).dp(),
                            )
                            background = focusBackground(false)
                            setOnFocusChangeListener { view, focused ->
                                view.scaleX = if (focused) 1.045f else 1f
                                view.scaleY = if (focused) 1.045f else 1f
                                setTextColor(
                                    if (focused) Color.rgb(8, 17, 27) else Color.WHITE,
                                )
                                background = focusBackground(focused)
                                if (focused) scheduleTelevisionControlsHide()
                            }
                            setOnClickListener {
                                onClick()
                                scheduleTelevisionControlsHide()
                            }
                        }
                        addView(
                            action,
                            LinearLayout.LayoutParams(
                                ViewGroup.LayoutParams.WRAP_CONTENT,
                                ViewGroup.LayoutParams.WRAP_CONTENT,
                            ).apply { marginEnd = scaled(12).dp() },
                        )
                        if (televisionFirstAction == null) televisionFirstAction = action
                        return action
                    }

                    televisionPrimaryAction = action("Pausa") {
                        player?.let { if (it.isPlaying) it.pause() else it.play() }
                        refreshTelevisionOsd()
                    }
                    televisionSeekBar?.nextFocusDownId =
                        televisionPrimaryAction?.id ?: View.NO_ID
                    if (liveRowItems.length() > 1 && liveRowIndex >= 0) {
                        action("Canale −") { switchLiveChannel(-1) }
                        action("Canale +") { switchLiveChannel(1) }
                    } else {
                        action("−10 s") { seekBy(-10_000) }
                        action("+10 s") { seekBy(10_000) }
                    }
                    action("Audio") {
                        showTrackSelection("Traccia audio", C.TRACK_TYPE_AUDIO)
                    }
                    action("Sottotitoli") {
                        showTrackSelection("Sottotitoli", C.TRACK_TYPE_TEXT)
                    }
                    action("Esci") { finish() }
                })

                addView(TextView(this@PlayerActivity).apply {
                    text = if (liveRowItems.length() > 1 && liveRowIndex >= 0) {
                        "OK seleziona  •  CH +/− cambia canale  •  ↑/↓ informazioni  •  INDIETRO nasconde o esce"
                    } else {
                        "OK seleziona  •  ←/→ avanza sulla timeline  •  ↑/↓ informazioni  •  INDIETRO nasconde o esce"
                    }
                    setTextColor(Color.rgb(166, 179, 194))
                    textSize = 13f * textScale
                    maxLines = 1
                    setPadding(0, scaled(13).dp(), 0, 0)
                })
                refreshTelevisionOsd()
            },
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM,
            ),
        )
    }

    private fun refreshTelevisionOsd(playbackState: Int? = player?.playbackState) {
        val liveLines = liveGuideText.lineSequence().map { it.trim() }.filter { it.isNotBlank() }
            .toList()
        val content = runCatching { JSONObject(contentJson) }.getOrNull()
        val contentTitle = content?.let { payload ->
            cleanKodiText(
                payload.optString("fulltitle").ifBlank { payload.optString("title") },
            )
        }.orEmpty()
        val season = content?.optInt("season", 0) ?: 0
        val episode = content?.optInt("episode", 0) ?: 0
        val showTitle = content?.let { payload ->
            cleanKodiText(
                payload.optString("tvshowtitle").ifBlank {
                    payload.optString("showtitle").ifBlank { contentTitle }
                },
            )
        }.orEmpty()
        val episodeTitle = if (season > 0 && episode > 0) {
            buildString {
                append(showTitle.ifBlank { contentTitle })
                append("  ·  S")
                append(season)
                append(":E")
                append(episode)
                if (contentTitle.isNotBlank() && !contentTitle.equals(showTitle, true)) {
                    append("  \"")
                    append(contentTitle)
                    append('"')
                }
            }
        } else {
            contentTitle
        }
        televisionTitleView?.text = liveLines.firstOrNull().orEmpty()
            .ifBlank { episodeTitle }
            .ifBlank { "Riproduzione" }

        val contentMetadata = content?.let { payload ->
            listOf(
                payload.optString("year"),
                payload.optString("genre"),
                payload.optString("mediatype").replaceFirstChar { it.uppercase() },
                payload.optString("rating").takeIf { it.isNotBlank() && it != "0" }
                    ?.let { "★ $it" }.orEmpty(),
            ).filter { it.isNotBlank() }.joinToString("  •  ")
        }.orEmpty()
        televisionMetadataView?.text = if (liveLines.size > 1) {
            liveLines.drop(1).joinToString("  •  ")
        } else {
            contentMetadata.ifBlank {
                if (liveRowItems.length() > 0) "Diretta" else "Riproduzione video"
            }
        }

        val current = player
        val effectiveLive =
            current?.isCurrentMediaItemLive == true ||
                liveRowIndex >= 0 ||
                liveGuideText.isNotBlank()
        val state = when {
            liveSwitching.get() -> "CAMBIO CANALE…"
            playbackState == Player.STATE_BUFFERING -> "CARICAMENTO…"
            playbackState == Player.STATE_ENDED -> "TERMINATO"
            current?.isPlaying == true && effectiveLive && liveRowItems.length() > 0 ->
                "● IN DIRETTA  •  ${liveRowIndex + 1}/${liveRowItems.length()}"
            current?.isPlaying == true && effectiveLive -> "● IN DIRETTA"
            current?.isPlaying == true -> "IN RIPRODUZIONE"
            playbackState == Player.STATE_READY -> "IN PAUSA"
            else -> "PREPARAZIONE…"
        }
        televisionStateView?.text = state
        televisionPrimaryAction?.text = if (current?.isPlaying == true) "❚❚" else "▶"
        nextEpisodeActionView?.visibility = if (
            episodeQueueIndex >= 0 && episodeQueueIndex + 1 < episodeQueueLength()
        ) View.VISIBLE else View.GONE
        episodesActionView?.visibility =
            if (episodeQueueLength() > 0) View.VISIBLE else View.GONE
        refreshTelevisionTimeline()
        if (
            ::trackControlsView.isInitialized &&
            trackControlsView.visibility == View.VISIBLE &&
            current?.isPlaying == true
        ) {
            scheduleTelevisionControlsHide()
        }
    }

    private fun formatPlaybackTime(positionMs: Long): String {
        val totalSeconds = (positionMs.coerceAtLeast(0L) / 1_000L)
        val hours = totalSeconds / 3_600L
        val minutes = (totalSeconds % 3_600L) / 60L
        val seconds = totalSeconds % 60L
        return if (hours > 0) {
            String.format(java.util.Locale.ROOT, "%d:%02d:%02d", hours, minutes, seconds)
        } else {
            String.format(java.util.Locale.ROOT, "%d:%02d", minutes, seconds)
        }
    }

    private fun refreshTelevisionTimeline() {
        val current = player
        val livePlayback =
            liveRowIndex >= 0 ||
                liveRowItems.length() > 0 ||
                liveGuideText.isNotBlank() ||
                current?.isCurrentMediaItemLive == true
        if (livePlayback) {
            televisionTimelineView?.visibility = View.GONE
            televisionPositionView?.text = ""
            televisionDurationView?.text = "LIVE"
            return
        }
        val duration = current?.duration
            ?.takeIf { it > 0 && it != C.TIME_UNSET }
        val available = current?.isCurrentMediaItemSeekable == true && duration != null
        televisionTimelineView?.visibility = if (available) View.VISIBLE else View.GONE
        if (!available || duration == null || televisionSeeking) return
        val position = current.currentPosition.coerceIn(0L, duration)
        televisionPositionView?.text = formatPlaybackTime(position)
        televisionDurationView?.text = formatPlaybackTime(duration)
        televisionSeekBar?.keyProgressIncrement =
            ((10_000L * (televisionSeekBar?.max ?: 10_000)) / duration)
                .toInt()
                .coerceAtLeast(1)
        televisionSeekBar?.progress =
            ((position * (televisionSeekBar?.max ?: 10_000)) / duration)
                .toInt()
                .coerceIn(0, televisionSeekBar?.max ?: 10_000)
    }

    private fun scheduleTelevisionControlsHide() {
        if (downloadPreparationMode || televisionSeeking) return
        controlsHandler.removeCallbacks(hideTelevisionControls)
        if (player?.isPlaying == true) {
            controlsHandler.postDelayed(hideTelevisionControls, 5_000)
        }
    }

    private fun setTelevisionControlsVisible(visible: Boolean) {
        if (downloadPreparationMode) return
        if (visible && upNextOverlay != null) {
            controlsHandler.removeCallbacks(updateTelevisionTimeline)
            controlsHandler.removeCallbacks(hideTelevisionControls)
            trackControlsView.animate().cancel()
            trackControlsView.visibility = View.GONE
            upNextOverlay?.bringToFront()
            return
        }
        val wasVisible = trackControlsView.visibility == View.VISIBLE
        trackControlsView.animate().cancel()
        liveGuideView.visibility = View.GONE
        if (visible) {
            trackControlsView.visibility = View.VISIBLE
            trackControlsView.bringToFront()
            if (!wasVisible) {
                trackControlsView.alpha = 0f
                trackControlsView.translationY =
                    (12f * televisionUiScale()).toInt().dp().toFloat()
                trackControlsView.animate()
                    .alpha(1f)
                    .translationY(0f)
                    .setDuration(160)
                    .start()
            }
            refreshTelevisionOsd()
            controlsHandler.removeCallbacks(updateTelevisionTimeline)
            controlsHandler.post(updateTelevisionTimeline)
            if (televisionPlayer && (!wasVisible || currentFocus === playerView)) {
                televisionFirstAction?.requestFocus()
            }
            scheduleTelevisionControlsHide()
        } else {
            controlsHandler.removeCallbacks(updateTelevisionTimeline)
            trackControlsView.animate()
                .alpha(0f)
                .translationY((12f * televisionUiScale()).toInt().dp().toFloat())
                .setDuration(140)
                .withEndAction {
                    trackControlsView.visibility = View.GONE
                    playerView.requestFocus()
                    enterImmersiveMode()
                }
                .start()
        }
    }

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    private fun showTrackSelection(title: String, trackType: Int) {
        val current = player
        val groups = current?.currentTracks?.groups.orEmpty().filter { it.type == trackType }
        if (current == null || groups.isEmpty()) {
            Toast.makeText(this, "Nessuna traccia disponibile", Toast.LENGTH_SHORT).show()
            return
        }
        runCatching {
            val initialParameters = current.trackSelectionParameters
            val initialOverrides = initialParameters.overrides.filterKeys { it.type == trackType }
            TrackSelectionDialogBuilder(this, title, groups) { disabled, overrides ->
                val parameters = current.trackSelectionParameters.buildUpon()
                    .setTrackTypeDisabled(trackType, disabled)
                    .clearOverridesOfType(trackType)
                    .apply { overrides.values.forEach(::addOverride) }
                    .build()
                persistTrackPreference(trackType, disabled, overrides, groups)
                current.trackSelectionParameters = parameters
                setTelevisionControlsVisible(true)
            }
                .setIsDisabled(trackType in initialParameters.disabledTrackTypes)
                .setOverrides(initialOverrides)
                .setAllowAdaptiveSelections(true)
                .setAllowMultipleOverrides(false)
                .setShowDisableOption(trackType == C.TRACK_TYPE_TEXT)
                .build()
                .apply {
                    setOnDismissListener { setTelevisionControlsVisible(true) }
                }
                .show()
        }.onFailure { error ->
            Toast.makeText(this, "Selettore non disponibile", Toast.LENGTH_SHORT).show()
            android.util.Log.e("Prippi", "Apertura selettore tracce", error)
        }
    }

    private fun mediaPreferenceKey(rawJson: String): String? = runCatching {
        MediaTrackPreferencePolicy.keyFor(ContentItem.fromJson(JSONObject(rawJson)))
    }.getOrNull()

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    private fun persistTrackPreference(
        trackType: Int,
        disabled: Boolean,
        overrides: Map<androidx.media3.common.TrackGroup, TrackSelectionOverride>,
        groups: List<Tracks.Group>,
    ) {
        val key = mediaTrackPreferenceKey ?: return
        val preference = when {
            trackType == C.TRACK_TYPE_TEXT && disabled ->
                StoredTrackPreference(TrackPreferenceMode.OFF)
            overrides.isEmpty() -> StoredTrackPreference(TrackPreferenceMode.AUTO)
            else -> {
                val selected = overrides.asSequence().mapNotNull { (trackGroup, override) ->
                    val group = groups.firstOrNull { it.mediaTrackGroup == trackGroup }
                        ?: return@mapNotNull null
                    val index = override.trackIndices.firstOrNull()
                        ?.takeIf { it in 0 until group.length }
                        ?: return@mapNotNull null
                    val format = group.getTrackFormat(index)
                    StoredTrackPreference(
                        TrackPreferenceMode.TRACK,
                        TrackDescriptor(
                            language = format.language.orEmpty(),
                            label = format.label.orEmpty(),
                            roleFlags = format.roleFlags,
                        ),
                    )
                }.firstOrNull() ?: StoredTrackPreference(TrackPreferenceMode.AUTO)
                selected
            }
        }
        when (trackType) {
            C.TRACK_TYPE_AUDIO -> mediaTrackPreferenceStore.setAudio(key, preference)
            C.TRACK_TYPE_TEXT -> mediaTrackPreferenceStore.setSubtitles(key, preference)
        }
        AppDiagnostics.event(
            "player_track_preference_saved type=$trackType mode=${preference.mode} key=$key",
        )
    }

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    private fun applyPersistedTrackPreferences(current: ExoPlayer, tracks: Tracks) {
        val key = mediaTrackPreferenceKey ?: return
        val preferences = mediaTrackPreferenceStore.get(key) ?: return
        val original = current.trackSelectionParameters
        val builder = original.buildUpon()

        fun apply(trackType: Int, preference: StoredTrackPreference?) {
            if (preference == null) return
            val groups = tracks.groups.filter { it.type == trackType }
            when (preference.mode) {
                TrackPreferenceMode.AUTO -> {
                    builder.clearOverridesOfType(trackType)
                    builder.setTrackTypeDisabled(trackType, false)
                }
                TrackPreferenceMode.OFF -> if (trackType == C.TRACK_TYPE_TEXT) {
                    builder.clearOverridesOfType(trackType)
                    builder.setTrackTypeDisabled(trackType, true)
                }
                TrackPreferenceMode.TRACK -> {
                    val descriptor = preference.descriptor ?: return
                    val candidates = groups.flatMapIndexed { groupIndex, group ->
                        (0 until group.length).map { trackIndex ->
                            val format = group.getTrackFormat(trackIndex)
                            TrackCandidate(
                                groupIndex = groupIndex,
                                trackIndex = trackIndex,
                                descriptor = TrackDescriptor(
                                    language = format.language.orEmpty(),
                                    label = format.label.orEmpty(),
                                    roleFlags = format.roleFlags,
                                ),
                                supported = group.isTrackSupported(trackIndex),
                            )
                        }
                    }
                    val match = MediaTrackPreferencePolicy.bestMatch(descriptor, candidates)
                    if (match != null) {
                        val group = groups[match.groupIndex]
                        builder.setTrackTypeDisabled(trackType, false)
                        builder.setOverrideForType(
                            TrackSelectionOverride(
                                group.mediaTrackGroup,
                                listOf(match.trackIndex),
                            ),
                        )
                    } else if (trackType == C.TRACK_TYPE_TEXT) {
                        // Never substitute an unrelated subtitle if the requested one is absent.
                        builder.clearOverridesOfType(trackType)
                        builder.setTrackTypeDisabled(trackType, true)
                    }
                }
            }
        }

        apply(C.TRACK_TYPE_AUDIO, preferences.audio)
        apply(C.TRACK_TYPE_TEXT, preferences.subtitles)
        val updated = builder.build()
        if (updated != original) {
            current.trackSelectionParameters = updated
            AppDiagnostics.event("player_track_preferences_applied key=$key")
        }
    }

    private fun resolveLiveCandidate(
        candidate: ContentItem,
        timeoutMs: Long,
    ): Result<List<PlaybackRequest>> {
        val task = FutureTask {
            ContentRepository().playbackCandidates(candidate)
        }
        Thread(task, "PrippiLiveResolver").apply {
            isDaemon = true
            start()
        }
        return try {
            Result.success(task.get(timeoutMs.coerceAtLeast(1L), TimeUnit.MILLISECONDS))
        } catch (error: TimeoutException) {
            task.cancel(true)
            Result.failure(error)
        } catch (error: Throwable) {
            Result.failure(error)
        }
    }

    private fun switchLiveChannel(delta: Int, userInitiated: Boolean = true) {
        val now = android.os.SystemClock.elapsedRealtime()
        if (userInitiated && !LiveChannelSwitchPolicy.acceptsInput(
                now,
                lastLiveSwitchAtMs,
                LIVE_SWITCH_DEBOUNCE_MS,
            )
        ) return
        if (userInitiated) lastLiveSwitchAtMs = now
        if (liveRowItems.length() < 2 || liveRowIndex < 0 ||
            !liveSwitching.compareAndSet(false, true)
        ) return
        val operationGeneration = nextAsyncOperationGeneration()
        statusView.text = "Ricerca del prossimo canale disponibile…"
        statusView.visibility = View.VISIBLE
        Thread {
            var selectedIndex = -1
            var selectedTarget: ContentItem? = null
            var selectedRequests: List<PlaybackRequest> = emptyList()
            var lastError: Throwable? = null
            val deadline = android.os.SystemClock.elapsedRealtime() + LIVE_SWITCH_RESOLVE_BUDGET_MS
            val indices = LiveChannelSwitchPolicy.candidateIndices(
                liveRowIndex,
                liveRowItems.length(),
                delta,
                LIVE_SWITCH_MAX_ATTEMPTS,
            )
            for (index in indices) {
                if (!isAsyncOperationActive(operationGeneration) ||
                    android.os.SystemClock.elapsedRealtime() >= deadline
                ) break
                val json = liveRowItems.optJSONObject(index) ?: continue
                val candidate = ContentItem.fromJson(json)
                val remainingMs =
                    deadline - android.os.SystemClock.elapsedRealtime()
                if (remainingMs <= 0) break
                val result = resolveLiveCandidate(candidate, remainingMs)
                lastError = result.exceptionOrNull() ?: lastError
                val requests = result.getOrDefault(emptyList())
                if (requests.isNotEmpty()) {
                    selectedIndex = index
                    selectedTarget = candidate
                    selectedRequests = requests
                    break
                }
            }
            runOnUiThread {
                if (!isAsyncOperationActive(operationGeneration)) {
                    liveSwitching.set(false)
                    return@runOnUiThread
                }
                val target = selectedTarget
                if (target == null || selectedRequests.isEmpty()) {
                    liveSwitching.set(false)
                    statusView.visibility = View.GONE
                    Toast.makeText(
                        this,
                        "Nessun altro canale disponibile in questa riga",
                        Toast.LENGTH_SHORT,
                    ).show()
                    lastError?.let { android.util.Log.e("Prippi", "Zapping Live", it) }
                } else {
                    progressHandler.removeCallbacks(progressSaver)
                    clearBootstrapCallbacks()
                    bootstrapWebView?.apply { stopLoading(); destroy() }
                    bootstrapWebView = null
                    playerView.player = null
                    player?.release()
                    player = null
                    startPositionMs = 0L
                    playbackCandidates = selectedRequests
                    currentCandidateIndex = 0
                    liveRowIndex = selectedIndex
                    mobileLivePositionView?.text = mobileLivePositionText()
                    updateLiveGuideText(target.title, target.plot)
                    liveGuideView.text = liveGuideText
                    liveRetryCount = 0
                    android.util.Log.i(
                        "Prippi",
                        "Zapping Live -> ${target.title} (${selectedIndex + 1}/${liveRowItems.length()})",
                    )
                    startPlaybackCandidate(0)
                }
                refreshTelevisionOsd()
            }
        }.start()
    }

    private fun nextEpisodeItem(): ContentItem? {
        val targetIndex = episodeQueueIndex + 1
        return episodeAt(targetIndex)?.let(ContentItem::fromJson)
    }

    private fun showEpisodeSelection() {
        val length = episodeQueueLength()
        if (length <= 0) {
            Toast.makeText(this, "Nessun episodio disponibile", Toast.LENGTH_SHORT).show()
            return
        }
        controlsHandler.removeCallbacks(hideTelevisionControls)
        val labels = Array(length) { index ->
            episodeAt(index)?.let(ContentItem::fromJson)?.let { item ->
                buildString {
                    if (item.season > 0 && item.episode > 0) {
                        append("S")
                        append(item.season.toString().padStart(2, '0'))
                        append("E")
                        append(item.episode.toString().padStart(2, '0'))
                        append("  ·  ")
                    }
                    append(item.title.ifBlank { "Episodio ${index + 1}" })
                    if (index == episodeQueueIndex) append("  (in riproduzione)")
                }
            } ?: "Episodio ${index + 1}"
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("Episodi")
            .setSingleChoiceItems(labels, episodeQueueIndex.coerceAtLeast(0)) { dialog, index ->
                dialog.dismiss()
                if (index != episodeQueueIndex) switchToEpisode(index)
            }
            .setNegativeButton("Chiudi", null)
            .setOnDismissListener { setTelevisionControlsVisible(true) }
            .show()
    }

    private fun autoplayNextEnabled(): Boolean =
        episodeQueueIndex >= 0 &&
            episodeQueueIndex + 1 < episodeQueueLength() &&
            playbackCandidates.getOrNull(currentCandidateIndex)?.autoplayNext != false

    private fun updateUpNextState() {
        if (!autoplayNextEnabled() || liveRowItems.length() > 0 || upNextPromptHidden) return
        val current = player ?: return
        val duration = current.duration.takeIf { it > 0 && it != C.TIME_UNSET } ?: return
        val position = current.currentPosition.coerceAtLeast(0L)
        val remaining = (duration - position).coerceAtLeast(0L)
        if (
            !upNextTriggered &&
            position >= UP_NEXT_MIN_WATCHED_MS &&
            remaining in 1..UP_NEXT_PROMPT_MS
        ) {
            showUpNextPrompt()
        }
        if (!upNextTriggered || upNextOverlay == null) return
        val seconds = ((remaining + 999L) / 1_000L).toInt().coerceAtLeast(0)
        upNextTimerView?.text = if (seconds > 0) {
            "Parte automaticamente tra ${seconds / 60}:${(seconds % 60).toString().padStart(2, '0')}"
        } else {
            "Avvio episodio successivo…"
        }
        upNextProgressView?.progress =
            (((UP_NEXT_PROMPT_MS - remaining).coerceIn(0L, UP_NEXT_PROMPT_MS) * 100L) /
                UP_NEXT_PROMPT_MS).toInt()
        // STATE_ENDED is handled only by the player listener. Advancing here as
        // well could race its delayed transition and skip one full episode.
    }

    private fun showUpNextPrompt() {
        if (upNextTriggered || upNextPromptHidden || !::rootView.isInitialized) return
        val next = nextEpisodeItem() ?: return
        upNextTriggered = true
        controlsHandler.removeCallbacks(hideTelevisionControls)
        controlsHandler.removeCallbacks(updateTelevisionTimeline)
        if (::trackControlsView.isInitialized) trackControlsView.visibility = View.GONE

        val scale = televisionUiScale()
        fun scaled(value: Int) = (value * scale).toInt().coerceAtLeast(1)
        val overlay = FrameLayout(this)
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(
                scaled(26).dp(),
                scaled(22).dp(),
                scaled(26).dp(),
                scaled(24).dp(),
            )
            background = GradientDrawable().apply {
                cornerRadius = scaled(16).dp().toFloat()
                setColor(Color.argb(246, 7, 12, 19))
                setStroke(scaled(1).dp(), Color.argb(100, 210, 228, 245))
            }
        }
        panel.addView(TextView(this).apply {
            text = "PROSSIMA PUNTATA"
            setTextColor(Color.rgb(229, 9, 20))
            textSize = 14f * scale.coerceIn(0.88f, 1.16f)
            setTypeface(typeface, Typeface.BOLD)
        })
        val episodeLabel = buildString {
            if (next.season > 0 && next.episode > 0) {
                append("S")
                append(next.season.toString().padStart(2, '0'))
                append("E")
                append(next.episode.toString().padStart(2, '0'))
                append("  —  ")
            }
            append(next.title)
        }
        panel.addView(TextView(this).apply {
            text = episodeLabel
            setTextColor(Color.WHITE)
            textSize = 22f * scale.coerceIn(0.88f, 1.16f)
            setTypeface(typeface, Typeface.BOLD)
            maxLines = 2
            setPadding(0, scaled(8).dp(), 0, scaled(4).dp())
        })
        panel.addView(TextView(this).also { timer ->
            upNextTimerView = timer
            timer.setTextColor(Color.rgb(200, 211, 223))
            timer.textSize = 15f * scale.coerceIn(0.88f, 1.16f)
            timer.text = "Parte automaticamente tra 1:00"
            timer.setPadding(0, scaled(4).dp(), 0, scaled(8).dp())
        })
        panel.addView(
            ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).also { progress ->
                upNextProgressView = progress
                progress.max = 100
                progress.progress = 0
                progress.progressTintList = ColorStateList.valueOf(Color.rgb(229, 9, 20))
                progress.progressBackgroundTintList =
                    ColorStateList.valueOf(Color.rgb(54, 63, 73))
            },
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                scaled(5).dp(),
            ).apply { bottomMargin = scaled(16).dp() },
        )

        val actions = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        fun action(label: String, primary: Boolean, onClick: () -> Unit): TextView =
            TextView(this).apply {
                fun focusBackground(focused: Boolean) = GradientDrawable().apply {
                    cornerRadius = scaled(10).dp().toFloat()
                    setColor(
                        when {
                            focused -> Color.WHITE
                            primary -> Color.rgb(229, 9, 20)
                            else -> Color.rgb(27, 38, 50)
                        },
                    )
                    setStroke(
                        if (focused) scaled(3).dp() else scaled(1).dp(),
                        if (focused) Color.rgb(255, 213, 79)
                        else Color.argb(110, 210, 228, 245),
                    )
                }
                text = label
                id = View.generateViewId()
                setTextColor(Color.WHITE)
                textSize = 16f * scale.coerceIn(0.88f, 1.16f)
                setTypeface(typeface, Typeface.BOLD)
                gravity = Gravity.CENTER
                isFocusable = true
                isClickable = true
                minHeight = scaled(50).dp()
                setPadding(
                    scaled(20).dp(),
                    scaled(11).dp(),
                    scaled(20).dp(),
                    scaled(11).dp(),
                )
                background = focusBackground(false)
                setOnFocusChangeListener { view, focused ->
                    view.scaleX = if (focused) 1.06f else 1f
                    view.scaleY = if (focused) 1.06f else 1f
                    setTextColor(
                        if (focused) Color.rgb(7, 16, 25) else Color.WHITE,
                    )
                    background = focusBackground(focused)
                }
                setOnClickListener { onClick() }
            }

        val playNow = action("Guarda subito", primary = true) {
            hideUpNextPrompt(cancelAutoplay = false)
            switchToNextEpisode()
        }
        actions.addView(
            playNow,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { marginEnd = scaled(12).dp() },
        )
        val cancel = action("Annulla", primary = false) {
            hideUpNextPrompt(cancelAutoplay = true)
        }
        playNow.nextFocusRightId = cancel.id
        cancel.nextFocusLeftId = playNow.id
        actions.addView(cancel)
        panel.addView(actions)
        overlay.addView(
            panel,
            FrameLayout.LayoutParams(
                scaled(560).dp(),
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP or Gravity.END,
            ).apply {
                topMargin = scaled(48).dp()
                marginEnd = scaled(52).dp()
            },
        )
        upNextOverlay = overlay
        rootView.addView(
            overlay,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        overlay.alpha = 0f
        overlay.translationX = scaled(24).dp().toFloat()
        overlay.animate().alpha(1f).translationX(0f).setDuration(180).start()
        overlay.post { playNow.requestFocus() }
        updateUpNextState()
    }

    private fun hideUpNextPrompt(cancelAutoplay: Boolean) {
        if (cancelAutoplay) upNextPromptHidden = true
        val overlay = upNextOverlay
        upNextOverlay = null
        upNextTimerView = null
        upNextProgressView = null
        if (overlay != null && ::rootView.isInitialized) {
            overlay.animate().cancel()
            rootView.removeView(overlay)
        }
        if (cancelAutoplay) {
            setTelevisionControlsVisible(true)
        }
    }

    private fun resetUpNextPrompt() {
        hideUpNextPrompt(cancelAutoplay = false)
        upNextTriggered = false
        upNextPromptHidden = false
    }

    private fun switchToNextEpisode() = switchToEpisode(episodeQueueIndex + 1)

    private fun switchToEpisode(targetIndex: Int) {
        if (targetIndex !in 0 until episodeQueueLength() ||
            !episodeSwitching.compareAndSet(false, true)
        ) return
        resetUpNextPrompt()
        val operationGeneration = nextAsyncOperationGeneration()
        val target = episodeAt(targetIndex)?.let(ContentItem::fromJson)
        if (target == null) {
            episodeSwitching.set(false)
            statusView.text = "Episodio successivo non disponibile"
            statusView.visibility = View.VISIBLE
            return
        }
        statusView.text = "Preparazione ${target.title}…"
        statusView.visibility = View.VISIBLE
        Thread {
            val result = runCatching { ContentRepository().playbackCandidates(target) }
            runOnUiThread {
                if (!isAsyncOperationActive(operationGeneration)) {
                    episodeSwitching.set(false)
                    return@runOnUiThread
                }
                val requests = result.getOrDefault(emptyList())
                if (requests.isEmpty()) {
                    statusView.text = "Episodio successivo non disponibile"
                    result.exceptionOrNull()?.let {
                        android.util.Log.e("Prippi", "Autoplay episodio", it)
                    }
                } else {
                    progressHandler.removeCallbacks(progressSaver)
                    clearBootstrapCallbacks()
                    bootstrapWebView?.apply { stopLoading(); destroy() }
                    bootstrapWebView = null
                    playerView.player = null
                    player?.release()
                    player = null
                    episodeQueueIndex = targetIndex
                    progressKey = target.continueWatchingKey
                    contentJson = target.rawJson
                    mediaTrackPreferenceKey = MediaTrackPreferencePolicy.keyFor(target)
                    startPositionMs = 0L
                    progressStore.advanceTo(target)
                    playbackCandidates = requests
                    currentCandidateIndex = 0
                    android.util.Log.i(
                        "Prippi",
                        "Autoplay episodio -> ${target.title} (${targetIndex + 1}/${episodeQueueLength()})",
                    )
                    startPlaybackCandidate(0)
                }
                episodeSwitching.set(false)
            }
        }.start()
    }

    private fun episodeQueueLength(): Int =
        if (episodeQueueKey.isNotBlank()) episodeQueueSize else episodeQueueItems.length()

    private fun episodeAt(index: Int): JSONObject? =
        if (episodeQueueKey.isNotBlank()) {
            EpisodeQueueStore.get(applicationContext, episodeQueueKey, index)
        } else {
            episodeQueueItems.optJSONObject(index)
        }

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && event.repeatCount == 0) {
            if (upNextOverlay != null) {
                hideUpNextPrompt(cancelAutoplay = true)
                return true
            }
            if (televisionPlayer && trackControlsView.visibility == View.VISIBLE) {
                setTelevisionControlsVisible(false)
                return true
            }
            finish()
            return true
        }
        if (upNextOverlay != null) {
            return when (keyCode) {
                KeyEvent.KEYCODE_DPAD_CENTER,
                KeyEvent.KEYCODE_ENTER -> {
                    currentFocus?.performClick() == true
                }
                KeyEvent.KEYCODE_DPAD_LEFT,
                KeyEvent.KEYCODE_DPAD_RIGHT,
                KeyEvent.KEYCODE_DPAD_UP,
                KeyEvent.KEYCODE_DPAD_DOWN -> super.onKeyDown(keyCode, event)
                else -> super.onKeyDown(keyCode, event)
            }
        }
        if (liveRowItems.length() > 1 && event.repeatCount == 0) {
            when (keyCode) {
                KeyEvent.KEYCODE_CHANNEL_UP,
                KeyEvent.KEYCODE_PAGE_UP,
                KeyEvent.KEYCODE_NAVIGATE_NEXT,
                KeyEvent.KEYCODE_MEDIA_NEXT -> {
                    switchLiveChannel(1)
                    setTelevisionControlsVisible(true)
                    return true
                }
                KeyEvent.KEYCODE_CHANNEL_DOWN,
                KeyEvent.KEYCODE_PAGE_DOWN,
                KeyEvent.KEYCODE_NAVIGATE_PREVIOUS,
                KeyEvent.KEYCODE_MEDIA_PREVIOUS -> {
                    switchLiveChannel(-1)
                    setTelevisionControlsVisible(true)
                    return true
                }
            }
        }
        if (event.repeatCount == 0) {
            when (keyCode) {
                KeyEvent.KEYCODE_LANGUAGE_SWITCH -> {
                    showTrackSelection("Traccia audio", C.TRACK_TYPE_AUDIO)
                    return true
                }
                KeyEvent.KEYCODE_CAPTIONS -> {
                    showTrackSelection("Sottotitoli", C.TRACK_TYPE_TEXT)
                    return true
                }
                KeyEvent.KEYCODE_DPAD_UP -> {
                    if (
                        trackControlsView.visibility == View.VISIBLE &&
                        currentFocus === televisionSeekBar
                    ) {
                        televisionPrimaryAction?.requestFocus()
                        return true
                    }
                    if (trackControlsView.visibility == View.VISIBLE && currentFocus !== playerView) {
                        return super.onKeyDown(keyCode, event)
                    }
                    setTelevisionControlsVisible(true)
                    return true
                }
                KeyEvent.KEYCODE_DPAD_DOWN -> {
                    if (
                        trackControlsView.visibility == View.VISIBLE &&
                        currentFocus === televisionSeekBar
                    ) {
                        (televisionFirstBottomAction ?: televisionPrimaryAction)?.requestFocus()
                        return true
                    }
                    if (
                        trackControlsView.visibility == View.VISIBLE &&
                        currentFocus !== playerView
                    ) {
                        scheduleTelevisionControlsHide()
                        return super.onKeyDown(keyCode, event)
                    }
                    setTelevisionControlsVisible(true)
                    return true
                }
                KeyEvent.KEYCODE_INFO,
                KeyEvent.KEYCODE_MENU -> {
                    setTelevisionControlsVisible(true)
                    return true
                }
                KeyEvent.KEYCODE_DPAD_CENTER,
                KeyEvent.KEYCODE_ENTER -> {
                    val focused = currentFocus
                    if (trackControlsView.visibility == View.VISIBLE &&
                        focused != null && focused !== playerView && focused.isClickable
                    ) {
                        focused.performClick()
                    } else {
                        player?.let { current ->
                            if (current.isPlaying) current.pause() else current.play()
                        }
                    }
                    setTelevisionControlsVisible(true)
                    return true
                }
                KeyEvent.KEYCODE_DPAD_LEFT -> {
                    if (trackControlsView.visibility == View.VISIBLE && currentFocus !== playerView) {
                        return super.onKeyDown(keyCode, event)
                    }
                    if (liveRowItems.length() == 0) seekBy(-10_000)
                    setTelevisionControlsVisible(true)
                    return true
                }
                KeyEvent.KEYCODE_DPAD_RIGHT -> {
                    if (trackControlsView.visibility == View.VISIBLE && currentFocus !== playerView) {
                        return super.onKeyDown(keyCode, event)
                    }
                    if (liveRowItems.length() == 0) seekBy(10_000)
                    setTelevisionControlsVisible(true)
                    return true
                }
            }
        }
        if (event.repeatCount == 0 && keyCode in setOf(
                KeyEvent.KEYCODE_MEDIA_PLAY,
                KeyEvent.KEYCODE_MEDIA_PAUSE,
                KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
                KeyEvent.KEYCODE_HEADSETHOOK,
            )
        ) {
            player?.let { current ->
                when (keyCode) {
                    KeyEvent.KEYCODE_MEDIA_PLAY -> current.play()
                    KeyEvent.KEYCODE_MEDIA_PAUSE -> current.pause()
                    else -> if (current.isPlaying) current.pause() else current.play()
                }
                setTelevisionControlsVisible(true)
                return true
            }
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun parsePlaybackCandidates(value: String?): List<PlaybackRequest> {
        if (value.isNullOrBlank()) return emptyList()
        return runCatching {
            val array = JSONArray(value)
            (0 until array.length()).mapNotNull { index ->
                array.optJSONObject(index)?.let(PlaybackRequest::fromJson)
            }.filter { it.url.isNotBlank() }
        }.getOrDefault(emptyList())
    }

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    private fun startPlaybackCandidate(index: Int) {
        if (!activityStarted || isFinishing || index !in playbackCandidates.indices) return
        val generation = nextPlaybackGeneration()
        currentCandidateIndex = index
        liveAacOverrideApplied = false
        val request = playbackCandidates[index]
        currentSubtitleUrls = request.subtitleUrls
        if (playbackCandidates.size > 1) {
            statusView.text = "Preparazione video ${index + 1}/${playbackCandidates.size}"
            statusView.visibility = View.VISIBLE
        }
        val headers = parseHeaders(request.headersJson)
        if (request.manifest == "bootstrap" && request.bootstrapUrl.isNotBlank()) {
            bootstrapHoster(rootView, playerView, statusView, request, generation)
        } else if (request.url.contains("vixcloud", ignoreCase = true) && request.bootstrapUrl.isNotBlank()) {
            bootstrapVixCloud(
                rootView, playerView, statusView, request.bootstrapUrl, request.url,
                request.manifest, request.audioLanguage, headers, generation,
            )
        } else if (downloadItemJson.isNotBlank()) {
            enqueuePreparedDownload(statusView, request.url, headers, generation)
        } else {
            startNativePlayer(
                playerView, statusView, request.url, request.manifest,
                request.audioLanguage, headers, generation,
            )
        }
    }

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    private fun startNativePlayer(
        view: PlayerView,
        status: TextView,
        url: String,
        manifest: String,
        audioLang: String,
        headers: Map<String, String>,
        generation: Long,
    ) {
        if (!isPlaybackGenerationActive(generation) || player != null) return
        val http = DefaultHttpDataSource.Factory().apply {
            if (headers.isNotEmpty()) setDefaultRequestProperties(headers)
            setAllowCrossProtocolRedirects(true)
        }
        val currentRequest = playbackCandidates.getOrNull(currentCandidateIndex)
        val mediaItemBuilder = MediaItem.Builder()
            .setUri(Uri.parse(url))
            .setSubtitleConfigurations(
                currentRequest?.subtitleUrls.orEmpty().mapIndexed { index, subtitleUrl ->
                    val cleanUrl = subtitleUrl.substringBefore('?').lowercase()
                    val mime = when {
                        cleanUrl.endsWith(".vtt") -> "text/vtt"
                        cleanUrl.endsWith(".ass") || cleanUrl.endsWith(".ssa") -> "text/x-ssa"
                        else -> "application/x-subrip"
                    }
                    MediaItem.SubtitleConfiguration.Builder(Uri.parse(subtitleUrl))
                        .setMimeType(mime)
                        .setLanguage(currentRequest?.textLanguage.orEmpty().ifBlank { "it" })
                        .setLabel("Sottotitoli ${index + 1}")
                        .build()
                },
            )
        val clearKeyResponse = currentRequest?.takeIf {
            it.drmType.equals("clearkey", ignoreCase = true) && it.licenseKey.contains(':')
        }?.let { clearKeyResponse(it.licenseKey) }
        if (clearKeyResponse != null) {
            mediaItemBuilder.setDrmConfiguration(
                MediaItem.DrmConfiguration.Builder(C.CLEARKEY_UUID).build(),
            )
        }
        val widevine = currentRequest?.takeIf {
            it.drmType.contains("widevine", ignoreCase = true) && it.licenseKey.isNotBlank()
        }
        if (widevine != null) {
            mediaItemBuilder.setDrmConfiguration(
                MediaItem.DrmConfiguration.Builder(C.WIDEVINE_UUID)
                    .setLicenseUri(widevine.licenseKey.substringBefore('|'))
                    .build(),
            )
        }
        val mediaItem = mediaItemBuilder.build()
        val drmManager = clearKeyResponse?.let { response ->
            DefaultDrmSessionManager.Builder()
                .setUuidAndExoMediaDrmProvider(C.CLEARKEY_UUID, FrameworkMediaDrm.DEFAULT_PROVIDER)
                .build(LocalMediaDrmCallback(response))
        } ?: widevine?.let { request ->
            val parts = request.licenseKey.split('|')
            val callback = HttpMediaDrmCallback(parts.first(), http)
            parts.getOrNull(1).orEmpty().split('&').forEach { encoded ->
                if ('=' in encoded) {
                    val key = Uri.decode(encoded.substringBefore('='))
                    val value = Uri.decode(encoded.substringAfter('='))
                    if (key.isNotBlank() && value.isNotBlank()) {
                        callback.setKeyRequestProperty(key, value)
                    }
                }
            }
            DefaultDrmSessionManager.Builder()
                .setUuidAndExoMediaDrmProvider(C.WIDEVINE_UUID, FrameworkMediaDrm.DEFAULT_PROVIDER)
                .build(callback)
        }
        val source: MediaSource = when {
            manifest == "mpd" -> DashMediaSource.Factory(http).apply {
                drmManager?.let { manager -> setDrmSessionManagerProvider { manager } }
            }
                .createMediaSource(mediaItem)
            manifest == "progressive" -> ProgressiveMediaSource.Factory(http).apply {
                drmManager?.let { manager -> setDrmSessionManagerProvider { manager } }
            }
                .createMediaSource(mediaItem)
            else -> HlsMediaSource.Factory(http).apply {
                drmManager?.let { manager -> setDrmSessionManagerProvider { manager } }
            }
                .createMediaSource(mediaItem)
        }

        val renderersFactory = DefaultRenderersFactory(this)
            .setEnableDecoderFallback(true)
            .setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_PREFER)
        player = ExoPlayer.Builder(this, renderersFactory)
            .setMediaSourceFactory(DefaultMediaSourceFactory(http))
            .build().also { current ->
                current.setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(C.USAGE_MEDIA)
                        .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE)
                        .build(),
                    true,
                )
                mediaSession?.release()
                mediaSession = MediaSession.Builder(this, current).build()
                view.player = current
                current.addListener(object : Player.Listener {
                    override fun onPlaybackStateChanged(playbackState: Int) {
                        if (!isPlaybackGenerationActive(generation) || player !== current) return
                        status.visibility = when (playbackState) {
                            Player.STATE_READY, Player.STATE_ENDED -> View.GONE
                            else -> View.VISIBLE
                        }
                        when (playbackState) {
                            Player.STATE_READY -> {
                                liveSwitching.set(false)
                                if (liveRetryCount > 0) {
                                    progressHandler.postDelayed({
                                        if (isPlaybackGenerationActive(generation) &&
                                            player === current &&
                                            current.isPlaying
                                        ) liveRetryCount = 0
                                    }, 30_000)
                                }
                            }
                            Player.STATE_BUFFERING -> status.text = "Caricamento…"
                            Player.STATE_ENDED -> {
                                val completedItem = runCatching {
                                    ContentItem.fromJson(JSONObject(contentJson))
                                }.getOrNull()
                                val nextEpisode = nextEpisodeItem()
                                if (completedItem?.isEpisode == true && nextEpisode != null) {
                                    // Come nell'addon Kodi, un episodio completato sposta
                                    // subito il CW al successivo anche se l'utente ha
                                    // annullato l'autoplay o la risoluzione successiva fallisce.
                                    progressStore.advanceTo(nextEpisode)
                                } else if (progressKey.isNotBlank()) {
                                    progressStore.remove(progressKey, contentJson)
                                }
                                if (autoplayNextEnabled() && !upNextPromptHidden) {
                                    hideUpNextPrompt(cancelAutoplay = false)
                                    status.text = "Avvio episodio successivo…"
                                    status.visibility = View.VISIBLE
                                    progressHandler.postDelayed({
                                        if (isPlaybackGenerationActive(generation)) {
                                            switchToNextEpisode()
                                        }
                                    }, 1_000)
                                }
                            }
                        }
                        refreshTelevisionOsd(playbackState)
                    }

                    override fun onIsPlayingChanged(isPlaying: Boolean) {
                        if (!isPlaybackGenerationActive(generation) || player !== current) return
                        refreshTelevisionOsd(current.playbackState)
                        updatePictureInPictureParams()
                    }

                    override fun onPlayerError(error: PlaybackException) {
                        if (!isPlaybackGenerationActive(generation) || player !== current) return
                        persistProgress()
                        val detail = error.cause?.message ?: error.message ?: error.errorCodeName
                        android.util.Log.e("Prippi", "Errore Media3: ${error.errorCodeName}", error)
                        if (liveRowItems.length() > 1 && liveRowIndex >= 0) {
                            if (liveRetryCount < 1) {
                                liveRetryCount++
                                current.release()
                                player = null
                                status.text = "Riconnessione al canale…"
                                status.visibility = View.VISIBLE
                                progressHandler.postDelayed(
                                    {
                                        if (isPlaybackGenerationActive(generation)) {
                                            startPlaybackCandidate(currentCandidateIndex)
                                        }
                                    },
                                    1_200,
                                )
                            } else {
                                liveRetryCount = 0
                                liveSwitching.set(false)
                                current.release()
                                player = null
                                status.text = "Canale non disponibile, passo al successivo…"
                                status.visibility = View.VISIBLE
                                progressHandler.postDelayed({
                                    if (isPlaybackGenerationActive(generation)) {
                                        switchLiveChannel(1, userInitiated = false)
                                    }
                                }, 500)
                            }
                            return
                        }
                        val next = currentCandidateIndex + 1
                        if (next < playbackCandidates.size && currentRequest?.fallbackEnabled != false) {
                            startPositionMs = current.currentPosition.coerceAtLeast(startPositionMs)
                            current.release()
                            player = null
                            clearBootstrapCallbacks()
                            bootstrapWebView?.apply { stopLoading(); destroy() }
                            bootstrapWebView = null
                            status.text = "Sorgente non disponibile. Provo ${next + 1}/${playbackCandidates.size}…"
                            status.visibility = View.VISIBLE
                            android.util.Log.i(
                                "Prippi",
                                "Fallback player ${currentCandidateIndex + 1} -> ${next + 1}: $detail",
                            )
                            progressHandler.postDelayed({
                                if (isPlaybackGenerationActive(generation)) {
                                    startPlaybackCandidate(next)
                                }
                            }, 500)
                        } else {
                            status.text = "Riproduzione non riuscita\n${error.errorCodeName}\n$detail"
                            status.visibility = View.VISIBLE
                        }
                    }

                    override fun onTracksChanged(tracks: Tracks) {
                        if (!isPlaybackGenerationActive(generation) || player !== current) return
                        applyPersistedTrackPreferences(current, tracks)
                        val audio = tracks.groups.filter { it.type == C.TRACK_TYPE_AUDIO }
                        if (liveRowItems.length() > 0 && !liveAacOverrideApplied) {
                            val selectedMime = audio.asSequence()
                                .flatMap { group ->
                                    (0 until group.length).asSequence().map { group to it }
                                }
                                .firstOrNull { (group, index) -> group.isTrackSelected(index) }
                                ?.let { (group, index) -> group.getTrackFormat(index).sampleMimeType }
                            val aac = audio.asSequence()
                                .flatMap { group ->
                                    (0 until group.length).asSequence().map { group to it }
                                }
                                .firstOrNull { (group, index) ->
                                    group.isTrackSupported(index) &&
                                        group.getTrackFormat(index).sampleMimeType == MimeTypes.AUDIO_AAC
                                }
                            if (aac != null && selectedMime != MimeTypes.AUDIO_AAC) {
                                val (group, index) = aac
                                liveAacOverrideApplied = true
                                current.trackSelectionParameters =
                                    current.trackSelectionParameters.buildUpon()
                                        .setOverrideForType(
                                            TrackSelectionOverride(
                                                group.mediaTrackGroup,
                                                listOf(index),
                                            ),
                                        )
                                        .build()
                                AppDiagnostics.event(
                                    "player_audio_override live=true from=${selectedMime ?: "none"} to=aac",
                                )
                            }
                        }
                        val report = if (audio.isEmpty()) {
                            "none"
                        } else {
                            audio.joinToString(";") { group ->
                                (0 until group.length).joinToString(",") { index ->
                                    val format = group.getTrackFormat(index)
                                    buildString {
                                        append(format.sampleMimeType ?: format.codecs ?: "unknown")
                                        append('/').append(format.language ?: "und")
                                        append('/').append(format.channelCount)
                                        append(if (group.isTrackSelected(index)) "/selected" else "/idle")
                                        append(if (group.isTrackSupported(index)) "/supported" else "/unsupported")
                                    }
                                }
                            }
                        }
                        android.util.Log.i("Prippi", "Tracce audio Media3: $report")
                        AppDiagnostics.event(
                            "player_audio_tracks server=${currentRequest?.server.orEmpty()} " +
                                "manifest=$manifest groups=${audio.size} tracks=$report",
                        )
                    }
                })
                current.trackSelectionParameters = TrackSelectionParameters.Builder(this).apply {
                    if (audioLang.isNotBlank()) {
                        setPreferredAudioLanguages(audioLang, "it", "ita", "ita-IT", "und")
                    }
                    if (currentRequest?.subtitlesEnabled == false) {
                        setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
                    } else {
                        currentRequest?.textLanguage?.takeIf { it.isNotBlank() }?.let {
                            setPreferredTextLanguage(it)
                        }
                        setSelectUndeterminedTextLanguage(true)
                    }
                    currentRequest?.maxVideoHeight?.takeIf { it > 0 }?.let { height ->
                        setMaxVideoSize(Int.MAX_VALUE, height)
                    }
                }.build()
                current.setMediaSource(source)
                if (liveRowItems.length() == 0 && startPositionMs > 0) {
                    current.seekTo(startPositionMs)
                    android.util.Log.i("Prippi", "Ripresa playback da ${startPositionMs}ms")
                }
                current.playWhenReady = true
                current.prepare()
                updatePictureInPictureParams()
                if (liveRowItems.length() > 1) {
                    progressHandler.postDelayed({
                        if (isPlaybackGenerationActive(generation) &&
                            player === current &&
                            current.playbackState != Player.STATE_READY
                        ) {
                            liveSwitching.set(false)
                            android.util.Log.w("Prippi", "Zapping Live sbloccato per timeout avvio")
                        }
                    }, LIVE_SWITCH_START_TIMEOUT_MS)
                }
            }
        progressHandler.removeCallbacks(progressSaver)
        progressHandler.postDelayed(progressSaver, 5_000)
    }

    /**
     * Fallback browser per gli hoster che richiedono JavaScript/Cloudflare o un
     * captcha (oggi soprattutto Mixdrop e Maxstream da CB01). Il WebView usa la
     * sessione reale Android e intercetta la richiesta video, poi Media3 prende
     * il controllo. La pagina resta sempre invisibile: captcha e gate vengono
     * risolti automaticamente e l'utente non deve interagire con l'hoster.
     */
    @Suppress("SetJavaScriptEnabled")
    private fun bootstrapHoster(
        root: FrameLayout,
        playerView: PlayerView,
        status: TextView,
        playback: PlaybackRequest,
        generation: Long,
    ) {
        status.text = "Preparazione video…"
        status.visibility = View.VISIBLE
        val completed = AtomicBoolean(false)
        val fallbackHeaders = parseHeaders(playback.headersJson)
        val web = WebView(this).also { bootstrapWebView = it }
        web.alpha = 0.01f
        web.setBackgroundColor(Color.BLACK)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.mediaPlaybackRequiresUserGesture = false
        web.settings.javaScriptCanOpenWindowsAutomatically = false
        web.settings.setSupportMultipleWindows(false)
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(web, true)
        }

        fun cleanup() {
            clearBootstrapCallbacks()
            bootstrapWebView = null
            runCatching { root.removeView(web) }
            runCatching { web.stopLoading() }
            runCatching { web.destroy() }
        }

        fun nextOrFail(detail: String) {
            if (!completed.compareAndSet(false, true)) return
            cleanup()
            if (!isPlaybackGenerationActive(generation)) return
            val next = currentCandidateIndex + 1
            if (next < playbackCandidates.size && playback.fallbackEnabled) {
                status.text = "Hoster non disponibile. Provo ${next + 1}/${playbackCandidates.size}…"
                android.util.Log.i("Prippi", "Fallback WebView ${currentCandidateIndex + 1} -> ${next + 1}: $detail")
                postBootstrapCallback(root, 350) {
                    if (isPlaybackGenerationActive(generation)) startPlaybackCandidate(next)
                }
            } else {
                liveSwitching.set(false)
                status.text = "Sorgenti esaurite\n$detail"
                status.visibility = View.VISIBLE
            }
        }

        fun finish(streamUrl: String, requestHeaders: Map<String, String>) {
            if (!completed.compareAndSet(false, true)) return
            if (!isPlaybackGenerationActive(generation)) {
                cleanup()
                return
            }
            val mediaHeaders = fallbackHeaders.toMutableMap()
            requestHeaders.forEach { (key, value) ->
                if (key.lowercase() !in setOf("host", "range", "accept-encoding")) {
                    mediaHeaders[key] = value
                }
            }
            CookieManager.getInstance().getCookie(streamUrl)?.takeIf { it.isNotBlank() }?.let {
                mediaHeaders["Cookie"] = it
            }
            val clean = streamUrl.substringBefore('?').lowercase()
            val manifest = when {
                clean.endsWith(".mpd") -> "mpd"
                clean.endsWith(".m3u8") || streamUrl.contains("playlist", true) -> "hls"
                else -> "progressive"
            }
            runOnUiThread {
                if (!isPlaybackGenerationActive(generation)) {
                    cleanup()
                    return@runOnUiThread
                }
                cleanup()
                android.util.Log.i("Prippi", "Bootstrap ${playback.server} ha intercettato lo stream $manifest")
                if (downloadItemJson.isNotBlank()) {
                    enqueuePreparedDownload(status, streamUrl, mediaHeaders, generation)
                } else {
                    startNativePlayer(
                        playerView, status, streamUrl, manifest,
                        playback.audioLanguage, mediaHeaders, generation,
                    )
                }
            }
        }

        fun isMediaRequest(url: String, headers: Map<String, String>): Boolean {
            val lower = url.lowercase()
            if (listOf("doubleclick", "googlesyndication", "/ads/", "vast").any(lower::contains)) {
                return false
            }
            val clean = lower.substringBefore('?')
            return clean.endsWith(".m3u8") || clean.endsWith(".mpd") ||
                clean.endsWith(".mp4") || clean.endsWith(".mkv") ||
                clean.endsWith(".webm") || lower.contains("/playlist/") ||
                headers.entries.any { (key, value) ->
                    key.equals("Accept", true) && value.contains("video", true)
                }
        }

        fun probePage(view: WebView) {
            if (completed.get()) return
            view.evaluateJavascript(
                "(function(){var t=(document.body&&document.body.innerText)||'';" +
                    "return /WE ARE SORRY|ALMOST THERE|File is no longer available/i.test(t);})()",
            ) { dead ->
                if (dead == "true") nextOrFail("file hoster non disponibile")
            }
            view.evaluateJavascript(
                "(function(){var u='';document.querySelectorAll('video,source').forEach(function(v){" +
                    "if(!u){u=v.currentSrc||v.src||v.getAttribute('src')||'';}});" +
                    "if(!u){var h=document.documentElement.innerHTML;" +
                    "var m=h.match(/https?:[^\\\"'<> ]+\\.(?:m3u8|mp4|mpd)(?:\\?[^\\\"'<> ]*)?/i);" +
                    "if(m)u=m[0].replace(/&amp;/g,'&');}return u;})()",
            ) { encoded ->
                val media = runCatching { JSONArray("[$encoded]").optString(0) }.getOrDefault("")
                if (media.startsWith("http://") || media.startsWith("https://")) {
                    finish(media, emptyMap())
                }
            }
            view.evaluateJavascript(
                "(function(){var v=document.querySelector('video');" +
                    "if(v){v.muted=true;v.play().catch(function(){});}" +
                    "var bs=[].slice.call(document.querySelectorAll('button,a,.play,.play-button'));" +
                    "var b=bs.find(function(x){return /^(continua|continue|play|riproduci)$/i.test((x.innerText||x.title||'').trim());});" +
                    "if(b)b.click();})()",
                null,
            )
        }

        fun allowedNavigation(uri: Uri): Boolean {
            if (uri.scheme.orEmpty().lowercase() !in setOf("http", "https")) return false
            val host = uri.host.orEmpty().lowercase()
            return host.endsWith("uprot.net") || host.contains("maxstream") ||
                host.startsWith("maxwe") || host.startsWith("maxsun") ||
                host.contains("mixdrop") ||
                host.contains("m1xdrop") || host.contains("miiiixdrop")
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                !allowedNavigation(request.url)

            @Deprecated("Compatibilità WebView precedenti")
            override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean =
                !allowedNavigation(Uri.parse(url))

            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest,
            ): WebResourceResponse? {
                val candidate = request.url.toString()
                if (isMediaRequest(candidate, request.requestHeaders)) {
                    finish(candidate, request.requestHeaders)
                }
                return super.shouldInterceptRequest(view, request)
            }

            override fun onPageFinished(view: WebView, url: String) {
                super.onPageFinished(view, url)
                probePage(view)
            }
        }
        root.addView(
            web,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        status.bringToFront()
        web.loadUrl(playback.bootstrapUrl, fallbackHeaders)
        listOf(2_000L, 4_000L, 8_000L, 15_000L).forEach { delay ->
            postBootstrapCallback(root, delay) {
                if (!completed.get() && isPlaybackGenerationActive(generation)) probePage(web)
            }
        }
        postBootstrapCallback(root, 5_000) {
            if (!completed.get() && isPlaybackGenerationActive(generation)) {
                status.text = "Verifica automatica dell'hoster…"
            }
        }
        postBootstrapCallback(root, 90_000) {
            if (!completed.get() && isPlaybackGenerationActive(generation)) {
                nextOrFail("timeout verifica hoster")
            }
        }
    }

    private fun clearKeyResponse(value: String): ByteArray? {
        val pair = value.substringBefore(',').split(':', limit = 2)
        if (pair.size != 2) return null
        fun asBase64Url(raw: String): String {
            val clean = raw.trim()
            val bytes = if (clean.length % 2 == 0 && clean.matches(Regex("[0-9a-fA-F]+"))) {
                ByteArray(clean.length / 2) { index ->
                    clean.substring(index * 2, index * 2 + 2).toInt(16).toByte()
                }
            } else {
                return clean.trimEnd('=')
            }
            return Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        }
        val response = JSONObject().apply {
            put("keys", JSONArray().put(JSONObject().apply {
                put("kty", "oct")
                put("kid", asBase64Url(pair[0]))
                put("k", asBase64Url(pair[1]))
            }))
            put("type", "temporary")
        }.toString()
        return response.toByteArray(Charsets.UTF_8)
    }

    @Suppress("SetJavaScriptEnabled")
    private fun bootstrapVixCloud(
        root: FrameLayout,
        playerView: PlayerView,
        status: TextView,
        bootstrapUrl: String,
        fallbackUrl: String,
        manifest: String,
        audioLang: String,
        fallbackHeaders: Map<String, String>,
        generation: Long,
    ) {
        status.text = "Preparazione stream…"
        val completed = AtomicBoolean(false)
        val web = WebView(this).also { bootstrapWebView = it }
        web.alpha = 0.01f
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.mediaPlaybackRequiresUserGesture = false
        web.settings.javaScriptCanOpenWindowsAutomatically = false
        web.settings.setSupportMultipleWindows(false)
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(web, true)
        }

        fun finishBootstrap(streamUrl: String, requestHeaders: Map<String, String>) {
            if (!completed.compareAndSet(false, true)) return
            clearBootstrapCallbacks()
            if (!isPlaybackGenerationActive(generation)) {
                runCatching { web.stopLoading() }
                runCatching { root.removeView(web) }
                runCatching { web.destroy() }
                return
            }
            val allowed = setOf(
                "user-agent", "referer", "origin", "accept", "accept-language",
                "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site",
                "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
            )
            val mediaHeaders = fallbackHeaders.toMutableMap()
            requestHeaders.forEach { (key, value) ->
                if (key.lowercase() in allowed) mediaHeaders[key] = value
            }
            CookieManager.getInstance().getCookie(streamUrl)?.takeIf { it.isNotBlank() }?.let {
                mediaHeaders["Cookie"] = it
            }
            runOnUiThread {
                if (!isPlaybackGenerationActive(generation)) {
                    runCatching { web.stopLoading() }
                    runCatching { root.removeView(web) }
                    runCatching { web.destroy() }
                    return@runOnUiThread
                }
                android.util.Log.i("Prippi", "Bootstrap VixCloud completato")
                web.stopLoading()
                root.removeView(web)
                web.destroy()
                bootstrapWebView = null
                if (downloadItemJson.isNotBlank()) {
                    enqueuePreparedDownload(status, streamUrl, mediaHeaders, generation)
                } else {
                    startNativePlayer(
                        playerView, status, streamUrl, manifest, audioLang, mediaHeaders, generation,
                    )
                }
            }
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest,
            ): Boolean {
                val scheme = request.url.scheme.orEmpty().lowercase()
                return scheme !in setOf("http", "https")
            }

            @Deprecated("Compatibilità WebView precedenti")
            override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean {
                val scheme = Uri.parse(url).scheme.orEmpty().lowercase()
                return scheme !in setOf("http", "https")
            }

            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest,
            ): WebResourceResponse? {
                val candidate = request.url.toString()
                if (candidate.contains("vixcloud", ignoreCase = true) &&
                    candidate.contains("/playlist/", ignoreCase = true)) {
                    android.util.Log.i("Prippi", "Bootstrap ha intercettato la playlist VixCloud")
                    finishBootstrap(candidate, request.requestHeaders)
                    return super.shouldInterceptRequest(view, request)
                }

                // L'embed VixCloud crea un token playlist nuovo a ogni apertura. Leggiamo
                // la stessa risposta che il WebView stava per caricare e costruiamo subito
                // il manifest: così play e resume non dipendono dall'avvio automatico di
                // JWPlayer (che su alcuni device non parte se il WebView è invisibile).
                if (candidate.contains("vixcloud", ignoreCase = true) &&
                    candidate.contains("/embed/", ignoreCase = true)) {
                    interceptVixCloudEmbed(candidate, request.requestHeaders)?.let { resolved ->
                        resolved.playlistUrl?.let { playlistUrl ->
                            android.util.Log.i("Prippi", "Bootstrap ha preparato la richiesta playlist VixCloud")
                            // La playlist e i token sono appena stati estratti dalla
                            // risposta autorizzata dell'embed. Non aspettiamo che lo
                            // script iniettato esegua una seconda fetch: sui WebView
                            // in background quella fetch può essere sospesa, facendo
                            // scadere il bootstrap e accodare un URL ormai vecchio.
                            finishBootstrap(playlistUrl, request.requestHeaders)
                        }
                        return resolved.response
                    }
                }
                return super.shouldInterceptRequest(view, request)
            }
        }
        root.addView(web, FrameLayout.LayoutParams(2, 2, Gravity.BOTTOM or Gravity.END))
        var bootstrapAttempt = 1
        val maxBootstrapAttempts = 3

        fun loadBootstrapAttempt() {
            if (completed.get() || !isPlaybackGenerationActive(generation)) return
            val retryUrl = if (bootstrapAttempt == 1) {
                bootstrapUrl
            } else {
                Uri.parse(bootstrapUrl).buildUpon()
                    .appendQueryParameter("_prippi_retry", bootstrapAttempt.toString())
                    .build()
                    .toString()
            }
            status.text = if (bootstrapAttempt == 1) {
                "Preparazione stream…"
            } else {
                "Nuovo tentativo VixCloud $bootstrapAttempt/$maxBootstrapAttempts…"
            }
            web.stopLoading()
            web.loadUrl(retryUrl, fallbackHeaders)
            postBootstrapCallback(root, 20_000) {
                if (!completed.get() && isPlaybackGenerationActive(generation) &&
                    bootstrapAttempt < maxBootstrapAttempts
                ) {
                    bootstrapAttempt += 1
                    android.util.Log.w(
                        "Prippi",
                        "Bootstrap VixCloud scaduto: tentativo $bootstrapAttempt/$maxBootstrapAttempts",
                    )
                    loadBootstrapAttempt()
                } else if (!completed.get() &&
                    isPlaybackGenerationActive(generation) &&
                    downloadItemJson.isNotBlank()
                ) {
                    // Un download deve partire soltanto con una playlist appena
                    // autorizzata: accodare fallbackUrl qui riprodurrebbe il 403.
                    android.util.Log.e("Prippi", "Bootstrap VixCloud fallito dopo $maxBootstrapAttempts tentativi")
                    completed.set(true)
                    clearBootstrapCallbacks()
                    web.stopLoading()
                    root.removeView(web)
                    web.destroy()
                    bootstrapWebView = null
                    status.text = "Download non avviato\nImpossibile autorizzare VixCloud. Riprova."
                } else if (!completed.get() && isPlaybackGenerationActive(generation)) {
                    // Conserva il comportamento precedente per la sola
                    // riproduzione: Media3 può ancora tentare il resolver.
                    android.util.Log.w("Prippi", "Bootstrap VixCloud esaurito: uso URL resolver per il player")
                    finishBootstrap(fallbackUrl, fallbackHeaders)
                }
            }
        }

        loadBootstrapAttempt()
    }

    private data class InterceptedEmbed(
        val response: WebResourceResponse,
        val playlistUrl: String?,
    )

    private fun interceptVixCloudEmbed(
        embedUrl: String,
        requestHeaders: Map<String, String>,
    ): InterceptedEmbed? {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(embedUrl).openConnection() as HttpURLConnection).apply {
                instanceFollowRedirects = true
                connectTimeout = 10_000
                readTimeout = 10_000
                requestHeaders.forEach { (key, value) ->
                    if (!key.equals("Accept-Encoding", ignoreCase = true)) {
                        setRequestProperty(key, value)
                    }
                }
                setRequestProperty("Accept-Encoding", "identity")
                CookieManager.getInstance().getCookie(embedUrl)?.takeIf { it.isNotBlank() }?.let {
                    setRequestProperty("Cookie", it)
                }
            }
            val status = connection.responseCode
            val body = (if (status in 200..399) connection.inputStream else connection.errorStream)
                ?.use { it.readBytes() }
                ?: return null
            val html = body.toString(Charsets.UTF_8)

            connection.headerFields.entries
                .filter { (key, _) -> key?.equals("Set-Cookie", ignoreCase = true) == true }
                .flatMap { it.value.orEmpty() }
                .forEach { cookie ->
                    CookieManager.getInstance().setCookie(embedUrl, cookie)
                }
            CookieManager.getInstance().flush()

            val playlist = buildVixCloudPlaylist(embedUrl, html)
            // Il fetch parte dentro Chromium, quindi VixCloud vede un vero contesto
            // browser. shouldInterceptRequest cattura poi quella richiesta completa
            // prima che il WebView consumi lo stream.
            val injectedHtml = playlist?.let {
                val escaped = JSONObject.quote(it)
                html.replace(
                    "</body>",
                    "<script>fetch($escaped,{credentials:'include'}).catch(function(){})</script></body>",
                    ignoreCase = true,
                )
            } ?: html
            val responseBody = injectedHtml.toByteArray(Charsets.UTF_8)

            val responseHeaders = connection.headerFields
                .filterKeys { it != null }
                .mapValues { (_, values) -> values.orEmpty().joinToString(", ") }
                .mapKeys { (key, _) -> key!! }
                .toMutableMap()
                .apply {
                    keys.filter {
                        it.equals("Content-Length", ignoreCase = true) ||
                            it.equals("Content-Encoding", ignoreCase = true) ||
                            it.equals("Transfer-Encoding", ignoreCase = true)
                    }.forEach { remove(it) }
                }
            connection.headerFields.entries
                .filter { (key, _) -> key?.equals("Set-Cookie", ignoreCase = true) == true }
                .flatMap { it.value.orEmpty() }
                .takeIf { it.isNotEmpty() }
                ?.let { responseHeaders["Set-Cookie"] = it.joinToString("\n") }

            val reason = connection.responseMessage?.takeIf { it.isNotBlank() } ?: "OK"
            val mime = connection.contentType?.substringBefore(';') ?: "text/html"
            InterceptedEmbed(
                response = WebResourceResponse(
                    mime,
                    "UTF-8",
                    status,
                    reason,
                    responseHeaders,
                    ByteArrayInputStream(responseBody),
                ),
                playlistUrl = playlist,
            )
        } catch (error: Exception) {
            android.util.Log.w("Prippi", "Intercettazione embed VixCloud non riuscita", error)
            null
        } finally {
            connection?.disconnect()
        }
    }

    private fun buildVixCloudPlaylist(embedUrl: String, html: String): String? {
        val marker = html.indexOf("window.masterPlaylist")
        if (marker < 0) return null
        val end = html.indexOf("window.canPlayFHD", marker).takeIf { it > marker } ?: html.length
        val block = html.substring(marker, end)
        fun value(pattern: String): String? = Regex(pattern, RegexOption.IGNORE_CASE)
            .find(block)?.groupValues?.getOrNull(1)?.takeIf { it.isNotBlank() }

        val masterUrl = value("url\\s*:\\s*['\"]([^'\"]+)") ?: return null
        // Il frontend VixCloud usa l'URL dello stream attivo (oggi contiene
        // ``ub=1``). Senza quel parametro il token è formalmente corretto ma il
        // CDN risponde 403. Il vecchio resolver Kodi leggeva solo masterPlaylist.
        val activeStreamUrl = Regex(
            "window\\.streams\\s*=\\s*(\\[[^;]+])\\s*;",
            setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
        ).find(html)?.groupValues?.getOrNull(1)?.let { streamsJson ->
            runCatching {
                val streams = JSONArray(streamsJson)
                (0 until streams.length())
                    .map { streams.getJSONObject(it) }
                    .firstOrNull { it.optBoolean("active", false) }
                    ?.optString("url")
                    ?.takeIf { it.isNotBlank() }
            }.getOrNull()
        }
        val builder = Uri.parse(activeStreamUrl ?: masterUrl).buildUpon()
        listOf("token", "expires", "asn").forEach { key ->
            value("['\"]?$key['\"]?\\s*:\\s*['\"]([^'\"]*)")?.let {
                builder.appendQueryParameter(key, it)
            }
        }
        if (Regex("window\\.canPlayFHD\\s*=\\s*true", RegexOption.IGNORE_CASE).containsMatchIn(html)) {
            builder.appendQueryParameter("h", "1")
        }
        val embed = Uri.parse(embedUrl)
        listOf("b", "scz").forEach { key ->
            embed.getQueryParameter(key)?.takeIf { it.isNotBlank() }?.let {
                builder.appendQueryParameter(key, it)
            }
        }
        return builder.build().toString()
    }

    private fun parseHeaders(value: String?): Map<String, String> {
        if (value.isNullOrBlank() || value == "{}") return emptyMap()
        return try {
            val json = JSONObject(value)
            json.keys().asSequence().associateWith { json.getString(it) }
        } catch (_: Exception) {
            emptyMap()
        }
    }

    private fun enqueuePreparedDownload(
        status: TextView,
        mediaUrl: String,
        headers: Map<String, String>,
        generation: Long,
    ) {
        if (downloadItemJson.isBlank() || !isPlaybackGenerationActive(generation)) return
        val itemJson = downloadItemJson
        downloadItemJson = ""
        status.text = "Aggiunta alla coda download…"
        Thread {
            val result = runCatching {
                PythonBridge.start(applicationContext)
                PythonBridge.enqueueResolvedDownload(
                    JSONObject(itemJson), mediaUrl, headers, downloadTargetHeight,
                    currentSubtitleUrls,
                )
                DownloadForegroundService.start(applicationContext)
            }
            runOnUiThread {
                if (!isPlaybackGenerationActive(generation)) return@runOnUiThread
                if (result.isSuccess) {
                    Toast.makeText(this, "Download aggiunto alla coda", Toast.LENGTH_SHORT).show()
                    finish()
                } else {
                    val detail = result.exceptionOrNull()?.message ?: "errore imprevisto"
                    status.text = "Download non avviato\n$detail"
                    android.util.Log.e("Prippi", "Accodamento download", result.exceptionOrNull())
                }
            }
        }.start()
    }

    private fun persistProgress(synchronous: Boolean = false) {
        val current = player ?: return
        if (progressKey.isBlank() || contentJson.isBlank()) return
        val duration = current.duration.takeUnless { it == C.TIME_UNSET || it < 0 } ?: 0L
        val position = current.currentPosition.coerceAtLeast(0L)
        if (synchronous) {
            progressStore.saveNow(progressKey, contentJson, position, duration)
        } else {
            progressStore.save(progressKey, contentJson, position, duration)
        }
    }

    override fun onStart() {
        super.onStart()
        activityStarted = true
        if (!downloadPreparationMode) {
            upNextHandler.removeCallbacks(updateUpNextPrompt)
            upNextHandler.post(updateUpNextPrompt)
        }
        player?.let { current ->
            restartAfterStop = false
            if (resumePlaybackAfterBackground) current.play()
            resumePlaybackAfterBackground = false
            progressHandler.removeCallbacks(progressSaver)
            progressHandler.postDelayed(progressSaver, 5_000)
            updatePictureInPictureParams()
        }
        if (
            restartAfterStop &&
            !isFinishing &&
            player == null &&
            bootstrapWebView == null &&
            currentCandidateIndex in playbackCandidates.indices
        ) {
            restartAfterStop = false
            statusView.text = "Ripresa riproduzione…"
            statusView.visibility = View.VISIBLE
            startPlaybackCandidate(currentCandidateIndex)
        }
    }

    override fun onStop() {
        val pictureInPictureClosed =
            pictureInPictureSessionActive || isInPictureInPictureMode
        activityStarted = false
        upNextHandler.removeCallbacksAndMessages(null)
        // Chiude soltanto la vista: la scelta dell'utente e il fatto che il
        // prompt sia gia apparso restano validi dopo notifiche/PiP/background.
        hideUpNextPrompt(cancelAutoplay = false)
        liveSwitching.set(false)
        episodeSwitching.set(false)
        if (liveRowItems.length() == 0) player?.let { current ->
            startPositionMs = current.currentPosition.coerceAtLeast(startPositionMs)
        }
        persistProgress(synchronous = true)
        progressHandler.removeCallbacksAndMessages(null)
        controlsHandler.removeCallbacksAndMessages(null)

        val retainedPlayer = player
        val keepPlayerForReturn =
            retainedPlayer != null &&
                !isFinishing &&
                !isChangingConfigurations &&
                !downloadPreparationMode &&
                !pictureInPictureClosed
        if (keepPlayerForReturn && retainedPlayer != null) {
            // Conserva la sessione e soprattutto l'URL già autorizzato: al
            // ritorno da una notifica il tasto Play controlla ancora lo stesso
            // player valido. Senza PiP lo mette in pausa e riparte solo se era
            // effettivamente in riproduzione prima dell'uscita.
            resumePlaybackAfterBackground = retainedPlayer.playWhenReady
            if (!isInPictureInPictureMode) retainedPlayer.pause()
            restartAfterStop = false
            super.onStop()
            return
        }

        nextPlaybackGeneration()
        nextAsyncOperationGeneration()
        restartAfterStop =
            !pictureInPictureClosed &&
                !isFinishing &&
                !isChangingConfigurations &&
                !downloadPreparationMode
        clearBootstrapCallbacks()
        bootstrapWebView?.apply { stopLoading(); destroy() }
        bootstrapWebView = null
        mediaSession?.release()
        mediaSession = null
        if (::playerView.isInitialized) playerView.player = null
        player?.release()
        player = null
        super.onStop()
        if (pictureInPictureClosed && !isFinishing) {
            // La X/swipe del PiP significa "chiudi il video": termina solo
            // PlayerActivity e lascia MainActivity pronta per il prossimo avvio.
            pictureInPictureSessionActive = false
            finish()
        }
    }

    override fun onDestroy() {
        nextPlaybackGeneration()
        nextAsyncOperationGeneration()
        progressHandler.removeCallbacksAndMessages(null)
        controlsHandler.removeCallbacksAndMessages(null)
        upNextHandler.removeCallbacksAndMessages(null)
        clearBootstrapCallbacks()
        bootstrapWebView?.apply { stopLoading(); destroy() }
        bootstrapWebView = null
        mediaSession?.release()
        mediaSession = null
        if (::playerView.isInitialized) playerView.player = null
        player?.release()
        player = null
        super.onDestroy()
    }

    companion object {
        private const val UP_NEXT_PROMPT_MS = 60_000L
        private const val UP_NEXT_MIN_WATCHED_MS = 60_000L
        private const val LIVE_SWITCH_DEBOUNCE_MS = 650L
        private const val LIVE_SWITCH_RESOLVE_BUDGET_MS = 12_000L
        private const val LIVE_SWITCH_START_TIMEOUT_MS = 20_000L
        private const val LIVE_SWITCH_MAX_ATTEMPTS = 4
    }
}
