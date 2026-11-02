package com.prippi.stream

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.SeekBar
import android.widget.TextView
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionParameters
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.SeekParameters
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory

internal object TimelinePreviewPolicy {
    fun position(position: Long, duration: Long): Long = position.coerceIn(0, (duration - 1).coerceAtLeast(0))
    fun label(position: Long): String {
        val seconds = position.coerceAtLeast(0) / 1000
        return if (seconds >= 3600) "%d:%02d:%02d".format(seconds / 3600, seconds / 60 % 60, seconds % 60)
            else "%d:%02d".format(seconds / 60, seconds % 60)
    }
}

/** On-demand, silent, isolated decoder. It never seeks the real player, saves CW,
 * downloads a whole movie or persists signed playback URLs. Uses the same local
 * loopback/file source for downloads, so it also works without internet. */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
internal class TimelinePreviewController(private val context: Context, private val root: FrameLayout) {
    private val handler = Handler(Looper.getMainLooper())
    private fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()
    private val panel = FrameLayout(context).apply {
        visibility = View.GONE
        isFocusable = false
        descendantFocusability = ViewGroup.FOCUS_BLOCK_DESCENDANTS
        background = GradientDrawable().apply { setColor(Color.BLACK); cornerRadius = dp(8).toFloat(); setStroke(dp(1), Color.WHITE) }
        clipToOutline = true
        elevation = dp(24).toFloat()
    }
    private val texture = TextureView(context).apply { isFocusable = false }
    private val time = TextView(context).apply {
        setTextColor(Color.WHITE); setBackgroundColor(Color.BLACK); textSize = 12f; gravity = Gravity.CENTER
    }
    private val loading = TextView(context).apply {
        setTextColor(Color.WHITE); setBackgroundColor(Color.BLACK); textSize = 11f; gravity = Gravity.CENTER
    }
    private var decoder: ExoPlayer? = null
    private var url = ""
    private var manifest = ""
    private var headers: Map<String, String> = emptyMap()
    private var serial = 0
    private var pending: Runnable? = null
    private var timeout: Runnable? = null
    private var hideTask: Runnable? = null
    private var target = 0L
    init {
        panel.addView(texture, FrameLayout.LayoutParams(-1, dp(90)))
        panel.addView(loading, FrameLayout.LayoutParams(-1, dp(90)))
        panel.addView(time, FrameLayout.LayoutParams(-1, dp(24), Gravity.BOTTOM))
        root.addView(panel, FrameLayout.LayoutParams(dp(160), dp(114), Gravity.TOP or Gravity.LEFT))
    }
    fun configure(url: String, manifest: String, headers: Map<String, String>) {
        hide(); this.url = url; this.manifest = manifest; this.headers = headers.toMap()
    }
    private fun buildDecoder(): ExoPlayer {
        val http = DefaultHttpDataSource.Factory().setDefaultRequestProperties(headers)
            .setConnectTimeoutMs(3000).setReadTimeoutMs(3000).setAllowCrossProtocolRedirects(true)
        // Prefer software for this one paused frame; do not take the primary
        // player's scarce hardware decoder on old TVs/tablets.
        val renderers = DefaultRenderersFactory(context).setEnableDecoderFallback(true)
            .setMediaCodecSelector { mime, secure, tunnel ->
                MediaCodecSelector.DEFAULT.getDecoderInfos(mime, secure, tunnel).sortedBy { if (it.softwareOnly) 0 else 1 }
            }
        val load = DefaultLoadControl.Builder().setBufferDurationsMs(500, 1500, 100, 250)
            .setTargetBufferBytes(2 * 1024 * 1024).build()
        return ExoPlayer.Builder(context, renderers)
            .setLoadControl(load)
            .setMediaSourceFactory(DefaultMediaSourceFactory(DefaultDataSource.Factory(context, http)))
            .build().also { player ->
                player.volume = 0f
                player.playWhenReady = false
                player.setSeekParameters(SeekParameters.CLOSEST_SYNC)
                player.trackSelectionParameters = TrackSelectionParameters.Builder(context)
                    .setTrackTypeDisabled(C.TRACK_TYPE_AUDIO, true).setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
                    .setMaxVideoSize(640, 360).setMaxVideoBitrate(500000).build()
                player.setVideoTextureView(texture)
                player.addListener(object : Player.Listener {
                    override fun onPlaybackStateChanged(state: Int) {
                        if (decoder !== player || panel.visibility != View.VISIBLE) return
                        if (state == Player.STATE_READY) {
                            loading.visibility = View.GONE
                            timeout?.let(handler::removeCallbacks)
                        }
                    }
                    override fun onPlayerError(error: PlaybackException) {
                        if (decoder === player) unavailable()
                    }
                })
                val mime = when (manifest) {
                    "hls" -> MimeTypes.APPLICATION_M3U8
                    "mpd" -> MimeTypes.APPLICATION_MPD
                    else -> null
                }
                player.setMediaItem(MediaItem.Builder().setUri(Uri.parse(url)).setMimeType(mime).build(), target)
                player.prepare()
            }
    }
    private fun unavailable() {
        loading.text = "Anteprima non disponibile"
        loading.visibility = View.VISIBLE
        decoder?.release(); decoder = null
    }
    fun show(position: Long, duration: Long, anchor: SeekBar, autoHide: Boolean = false) {
        if (url.isBlank() || duration <= 0) return
        target = TimelinePreviewPolicy.position(position, duration)
        val token = ++serial
        pending?.let(handler::removeCallbacks); timeout?.let(handler::removeCallbacks); hideTask?.let(handler::removeCallbacks)
        panel.visibility = View.VISIBLE
        panel.bringToFront()
        loading.text = "Anteprima…"; loading.visibility = View.VISIBLE
        time.text = TimelinePreviewPolicy.label(target)
        val screen = IntArray(2); val rootScreen = IntArray(2)
        anchor.getLocationOnScreen(screen); root.getLocationOnScreen(rootScreen)
        val fraction = target.toDouble() / duration
        val width = dp(160); val height = dp(114)
        panel.layoutParams = (panel.layoutParams as FrameLayout.LayoutParams).apply {
            leftMargin = (screen[0] - rootScreen[0] + anchor.paddingLeft +
                fraction * (anchor.width - anchor.paddingLeft - anchor.paddingRight) - width / 2)
                .toInt().coerceIn(dp(6), (root.width - width - dp(6)).coerceAtLeast(dp(6)))
            topMargin = (screen[1] - rootScreen[1] - height - dp(8)).coerceAtLeast(dp(6))
        }
        pending = Runnable {
            if (token != serial || panel.visibility != View.VISIBLE) return@Runnable
            try {
                if (decoder == null) decoder = buildDecoder() else decoder?.seekTo(target)
            } catch (_: Exception) { unavailable() }
        }.also { handler.postDelayed(it, 180) }
        timeout = Runnable { if (token == serial && loading.visibility == View.VISIBLE) unavailable() }
            .also { handler.postDelayed(it, 4500) }
        if (autoHide) hideTask = Runnable { hide() }.also { handler.postDelayed(it, 2200) }
    }
    fun hide() {
        serial++
        pending?.let(handler::removeCallbacks); timeout?.let(handler::removeCallbacks); hideTask?.let(handler::removeCallbacks)
        panel.visibility = View.GONE
        decoder?.release(); decoder = null
    }
    fun close() { hide(); root.removeView(panel); url = ""; headers = emptyMap() }
}
