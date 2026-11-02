package com.prippi.stream

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.ConnectivityManager
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.SeekBar
import android.widget.TextView
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionParameters
import androidx.media3.common.Tracks
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.TransferListener
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.SeekParameters
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import java.io.File
import java.security.MessageDigest
import java.util.Locale
import java.util.TreeMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.abs

internal object TimelinePreviewPolicy {
    const val STEP_MS = 5000L
    fun position(position: Long, duration: Long): Long = position.coerceIn(0, (duration - 1).coerceAtLeast(0))
    fun bucket(position: Long, duration: Long): Long = position(position, duration) / STEP_MS * STEP_MS
    fun label(position: Long): String {
        val seconds = position.coerceAtLeast(0) / 1000
        return if (seconds >= 3600) String.format(Locale.ROOT, "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
            else String.format(Locale.ROOT, "%d:%02d", seconds / 60, seconds % 60)
    }
    fun nearest(keys: Collection<Long>, position: Long): Long? =
        keys.minWithOrNull(compareBy<Long> { abs(it - position) }.thenBy { it })
    /** Coarse coverage of the whole title first, then refinements; never every segment. */
    fun warmTargets(duration: Long, resume: Long, limit: Int = 32): List<Long> {
        if (duration <= 0 || limit <= 0) return emptyList()
        val points = linkedSetOf(bucket(resume, duration), 0L)
        var divisions = 2
        while (points.size < limit && divisions <= 64) {
            for (part in 1 until divisions step 2) {
                points.add(bucket(duration * part / divisions, duration))
                if (points.size >= limit) break
            }
            divisions *= 2
        }
        return points.take(limit)
    }
}

/**
 * Cached story frames, not an on-demand black video rectangle. A small silent
 * decoder prepares bounded samples behind the opaque main PlayerView; the popup
 * only contains an ImageView. Seek requests are latest-wins, never debounced until
 * the user stops moving. Decoding/caching never seeks the real player or writes CW.
 */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
internal class TimelinePreviewController(private val context: Context, private val root: FrameLayout) {
    private val handler = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private val closed = AtomicBoolean(false)
    private fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()
    // The full-screen, opaque main PlayerView is a later sibling and covers this
    // surface. Unlike a GONE TextureView, it remains attached and can prepare frames.
    private val texture = TextureView(context).apply {
        isFocusable = false
        isClickable = false
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val panel = FrameLayout(context).apply {
        visibility = View.GONE
        isFocusable = false
        descendantFocusability = ViewGroup.FOCUS_BLOCK_DESCENDANTS
        background = GradientDrawable().apply {
            setColor(Color.BLACK); cornerRadius = dp(8).toFloat(); setStroke(dp(1), Color.WHITE)
        }
        clipToOutline = true
        elevation = dp(24).toFloat()
    }
    private val image = ImageView(context).apply {
        scaleType = ImageView.ScaleType.FIT_CENTER
        setBackgroundColor(Color.BLACK)
        isFocusable = false
    }
    private val time = TextView(context).apply {
        setTextColor(Color.WHITE); setBackgroundColor(Color.BLACK); textSize = 12f; gravity = Gravity.CENTER
    }
    private val frames = TreeMap<Long, Bitmap>()
    private var directory: File? = null
    private var decoder: ExoPlayer? = null
    private var url = ""
    private var manifest = ""
    private var headers: Map<String, String> = emptyMap()
    private var offline = false
    private var warmAllowed: () -> Boolean = { false }
    @Volatile private var warmDisabled = false
    private val networkBytes = AtomicLong(0)
    private var duration = 0L
    private var warmQueue = ArrayDeque<Long>()
    private var prepared = false
    private var requested: Long? = null
    private var shown = false
    private var inFlight: Long? = null
    private var captured = false
    private var failures = 0
    private var suspended = false
    private var pumpTask: Runnable? = null
    private var timeout: Runnable? = null
    private var hideTask: Runnable? = null
    private var idleTask: Runnable? = null
    init {
        root.addView(texture, 0, FrameLayout.LayoutParams(dp(160), dp(90), Gravity.TOP or Gravity.LEFT))
        panel.addView(image, FrameLayout.LayoutParams(-1, dp(90)))
        panel.addView(time, FrameLayout.LayoutParams(-1, dp(24), Gravity.BOTTOM))
        root.addView(panel, FrameLayout.LayoutParams(dp(160), dp(114), Gravity.TOP or Gravity.LEFT))
    }

    fun configure(url: String, manifest: String, headers: Map<String, String>,
                  identity: String, offline: Boolean, warmAllowed: () -> Boolean) {
        this.url = url
        this.manifest = manifest
        this.headers = headers.toMap()
        this.offline = offline
        this.warmAllowed = warmAllowed
        val key = MessageDigest.getInstance("SHA-256").digest(identity.toByteArray())
            .joinToString("") { "%02x".format(it) }
        val folder = File(context.cacheDir, "timeline-previews/$key")
        directory = folder
        // Disk I/O is not allowed to hold up playback or cursor movement.
        io.execute {
            val loaded = folder.listFiles()?.filter { it.extension == "jpg" }
                ?.sortedByDescending(File::lastModified)?.take(96).orEmpty().mapNotNull { file ->
                    val position = file.nameWithoutExtension.toLongOrNull() ?: return@mapNotNull null
                    val bitmap = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply {
                        inPreferredConfig = Bitmap.Config.RGB_565
                    }) ?: return@mapNotNull null
                    position to bitmap
                }
            handler.post {
                if (closed.get()) return@post
                loaded.forEach { (position, bitmap) -> putFrame(position, bitmap, persist = false) }
                paintCached()
            }
        }
    }

    fun prepareTimeline(duration: Long, resume: Long) {
        if (duration <= 0 || duration == C.TIME_UNSET || closed.get()) return
        this.duration = duration
        suspended = false
        if (!prepared) {
            prepared = true
            warmQueue.addAll(TimelinePreviewPolicy.warmTargets(duration, resume))
        }
        schedulePump(800)
    }

    private fun canPreload(): Boolean = !suspended && !warmDisabled && warmAllowed() &&
        (offline || runCatching {
            !(context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).isActiveNetworkMetered
        }.getOrDefault(false))

    private fun buildDecoder(start: Long): ExoPlayer {
        val http = DefaultHttpDataSource.Factory().setDefaultRequestProperties(headers)
            .setConnectTimeoutMs(3000).setReadTimeoutMs(3000).setAllowCrossProtocolRedirects(true)
            .setTransferListener(object : TransferListener {
                override fun onTransferInitializing(source: DataSource, spec: DataSpec, network: Boolean) = Unit
                override fun onTransferStart(source: DataSource, spec: DataSpec, network: Boolean) = Unit
                override fun onTransferEnd(source: DataSource, spec: DataSpec, network: Boolean) = Unit
                override fun onBytesTransferred(source: DataSource, spec: DataSpec, network: Boolean, bytes: Int) {
                    // Stop speculative preparation after a small bounded budget.
                    // A user-requested preview can still load its selected point.
                    if (!offline && network && networkBytes.addAndGet(bytes.toLong()) >= 16L * 1024 * 1024)
                        warmDisabled = true
                }
            })
        val renderers = DefaultRenderersFactory(context).setEnableDecoderFallback(true)
            .setMediaCodecSelector { mime, secure, tunnel ->
                MediaCodecSelector.DEFAULT.getDecoderInfos(mime, secure, tunnel).sortedBy { if (it.softwareOnly) 0 else 1 }
            }
        val load = DefaultLoadControl.Builder().setBufferDurationsMs(500, 1000, 100, 250)
            .setTargetBufferBytes(1024 * 1024).build()
        return ExoPlayer.Builder(context, renderers).setLoadControl(load)
            .setMediaSourceFactory(DefaultMediaSourceFactory(DefaultDataSource.Factory(context, http)))
            .build().also { player ->
                player.volume = 0f
                player.playWhenReady = false
                player.setSeekParameters(SeekParameters.CLOSEST_SYNC)
                player.trackSelectionParameters = TrackSelectionParameters.Builder(context)
                    .setTrackTypeDisabled(C.TRACK_TYPE_AUDIO, true).setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
                    .setMaxVideoSize(640, 360).setMaxVideoBitrate(500000).build()
                player.setVideoTextureView(texture)
                player.setVideoFrameMetadataListener { _, _, _, _ ->
                    handler.post { if (decoder === player) captureWhenRendered() }
                }
                player.addListener(object : Player.Listener {
                    override fun onRenderedFirstFrame() {
                        if (decoder === player) captureWhenRendered()
                    }
                    override fun onPlaybackStateChanged(state: Int) {
                        // Some local sources reuse the decoded sync frame on seek.
                        if (decoder === player && state == Player.STATE_READY) captureWhenRendered()
                    }
                    override fun onTracksChanged(tracks: Tracks) {
                        if (offline) return
                        val video = tracks.groups.filter { it.type == C.TRACK_TYPE_VIDEO }.flatMap { group ->
                            (0 until group.length).filter { group.isTrackSelected(it) }.map { group.getTrackFormat(it) }
                        }
                        // Do not pre-download HD-only segments just to make thumbnails.
                        if (video.any { it.height > 720 || it.bitrate > 3000000 }) warmDisabled = true
                    }
                    override fun onPlayerError(error: PlaybackException) {
                        if (decoder === player) failedFrame()
                    }
                })
                val mime = when (manifest) {
                    "hls" -> MimeTypes.APPLICATION_M3U8
                    "mpd" -> MimeTypes.APPLICATION_MPD
                    else -> null
                }
                player.setMediaItem(MediaItem.Builder().setUri(Uri.parse(url)).setMimeType(mime).build(), start)
                player.prepare()
            }
    }

    private fun captureWhenRendered() {
        val position = inFlight ?: return
        if (captured || decoder?.playbackState != Player.STATE_READY) return
        captured = true
        handler.postDelayed({
            if (closed.get() || inFlight != position || suspended) return@postDelayed
            val bitmap = runCatching { if (texture.isAvailable) texture.getBitmap(160, 90) else null }.getOrNull()
            captured = false
            if (bitmap == null) { failedFrame(); return@postDelayed }
            timeout?.let(handler::removeCallbacks)
            inFlight = null
            failures = 0
            putFrame(position, bitmap, persist = true)
            paintCached()
            schedulePump(if (shown) 60 else 700)
        }, 90)
    }

    private fun putFrame(position: Long, bitmap: Bitmap, persist: Boolean) {
        if (frames.size >= 96 && !frames.containsKey(position)) {
            val oldest = frames.keys.firstOrNull { it != TimelinePreviewPolicy.nearest(frames.keys, requested ?: position) }
            if (oldest != null) frames.remove(oldest)
        }
        frames[position] = bitmap
        if (!persist) return
        val folder = directory ?: return
        io.execute {
            if (closed.get()) return@execute
            runCatching {
                folder.mkdirs()
                val stage = File(folder, "$position.tmp")
                stage.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 75, it) }
                val target = File(folder, "$position.jpg")
                if (!stage.renameTo(target)) stage.delete()
                folder.listFiles()?.filter { it.extension == "jpg" }?.sortedByDescending(File::lastModified)
                    ?.drop(96)?.forEach(File::delete)
                // Bounded disposable cache across all titles; no playback URLs or credentials.
                val all = folder.parentFile?.listFiles()?.flatMap { it.listFiles().orEmpty().toList() }
                    ?.filter { it.extension == "jpg" }?.sortedBy(File::lastModified).orEmpty()
                var bytes = all.sumOf(File::length)
                for (file in all) {
                    if (bytes <= 64L * 1024 * 1024) break
                    val size = file.length()
                    if (file.delete()) bytes -= size
                }
            }
        }
    }

    private fun paintCached() {
        if (!shown) return
        val target = requested ?: return
        val key = TimelinePreviewPolicy.nearest(frames.keys, target) ?: run {
            // Do not show a black square with a loading caption.
            panel.visibility = View.GONE
            return
        }
        image.setImageBitmap(frames[key])
        time.text = (if (abs(key - target) >= TimelinePreviewPolicy.STEP_MS) "≈ " else "") + TimelinePreviewPolicy.label(key)
        panel.visibility = View.VISIBLE
        panel.bringToFront()
    }

    private fun schedulePump(delay: Long) {
        if (closed.get() || suspended || pumpTask != null || inFlight != null) return
        pumpTask = Runnable { pumpTask = null; pump() }.also { handler.postDelayed(it, delay) }
    }

    private fun pump() {
        if (closed.get() || suspended || inFlight != null || url.isBlank() || duration <= 0) return
        val wanted = requested?.let { TimelinePreviewPolicy.bucket(it, duration) }
        val foreground = shown && wanted != null && !frames.containsKey(wanted)
        while (warmQueue.isNotEmpty() && frames.containsKey(warmQueue.first())) warmQueue.removeFirst()
        val next = if (foreground) wanted else if (canPreload()) warmQueue.removeFirstOrNull() else null
        if (next == null) {
            if (warmQueue.isNotEmpty()) schedulePump(1500)
            if (idleTask == null) {
                idleTask?.let(handler::removeCallbacks)
                idleTask = Runnable { idleTask = null; releaseDecoder() }.also { handler.postDelayed(it, 30000) }
            }
            return
        }
        if (failures >= 3 && !foreground) { warmQueue.clear(); return }
        idleTask?.let(handler::removeCallbacks)
        idleTask = null
        inFlight = next
        captured = false
        try {
            if (decoder == null) decoder = buildDecoder(next)
            else {
                decoder?.seekTo(next)
                if (decoder?.playbackState == Player.STATE_READY) captureWhenRendered()
            }
            timeout = Runnable { if (inFlight == next) failedFrame() }.also { handler.postDelayed(it, 4500) }
        } catch (_: Exception) { failedFrame() }
    }

    private fun failedFrame() {
        timeout?.let(handler::removeCallbacks)
        inFlight = null
        captured = false
        failures++
        releaseDecoder()
        // Keep the last cached image visible; never mask it with a black spinner.
        if (failures < 3) schedulePump(500)
    }

    fun show(position: Long, duration: Long, anchor: SeekBar, autoHide: Boolean = false) {
        if (url.isBlank() || duration <= 0 || closed.get()) return
        this.duration = duration
        suspended = false
        requested = TimelinePreviewPolicy.position(position, duration)
        shown = true
        hideTask?.let(handler::removeCallbacks)
        val screen = IntArray(2); val rootScreen = IntArray(2)
        anchor.getLocationOnScreen(screen); root.getLocationOnScreen(rootScreen)
        val fraction = requested!!.toDouble() / duration
        val width = dp(160); val height = dp(114)
        panel.layoutParams = (panel.layoutParams as FrameLayout.LayoutParams).apply {
            leftMargin = (screen[0] - rootScreen[0] + anchor.paddingLeft +
                fraction * (anchor.width - anchor.paddingLeft - anchor.paddingRight) - width / 2)
                .toInt().coerceIn(dp(6), (root.width - width - dp(6)).coerceAtLeast(dp(6)))
            topMargin = (screen[1] - rootScreen[1] - height - dp(8)).coerceAtLeast(dp(6))
        }
        paintCached()
        // Latest target replaces earlier targets without restarting a debounce timer.
        if (pumpTask != null && inFlight == null) {
            handler.removeCallbacks(pumpTask!!); pumpTask = null
        }
        schedulePump(0)
        if (autoHide) hideTask = Runnable { hide() }.also { handler.postDelayed(it, 3000) }
    }

    fun hide() {
        shown = false
        requested = null
        hideTask?.let(handler::removeCallbacks)
        panel.visibility = View.GONE
        // Retain the warm decoder and cached frames between two scrub gestures.
    }

    private fun releaseDecoder() {
        decoder?.release()
        decoder = null
    }

    fun suspend() {
        suspended = true
        hide()
        handler.removeCallbacksAndMessages(null)
        pumpTask = null
        idleTask = null
        timeout = null
        hideTask = null
        inFlight = null
        captured = false
        releaseDecoder()
    }

    fun close() {
        closed.set(true)
        suspend()
        io.shutdownNow()
        root.removeView(panel)
        root.removeView(texture)
        image.setImageDrawable(null)
        frames.clear()
        url = ""
        headers = emptyMap()
    }
}
