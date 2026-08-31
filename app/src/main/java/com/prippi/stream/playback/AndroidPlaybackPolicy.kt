package com.prippi.stream.playback

import android.content.Context
import android.hardware.display.DisplayManager
import android.media.MediaCodecList
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import com.prippi.stream.DeviceProfile
import com.prippi.stream.PlaybackRequest
import kotlin.math.min

data class AndroidPlaybackPlan(
    val ordered: List<PlaybackRequest>,
    val fourK: List<PlaybackRequest>,
    val standard: List<PlaybackRequest>,
    val askForConfirmation: Boolean,
)

/**
 * Android boundary for the shared pure policy. Source resolution remains in the
 * shared engine; this layer only applies device/network limits before Media3.
 */
fun planAndroidPlayback(
    context: Context,
    profile: DeviceProfile,
    requests: List<PlaybackRequest>,
    allow4KOnMetered: Boolean = false,
    treatWifiAsMetered: Boolean = false,
): AndroidPlaybackPlan {
    val indexed = requests.mapIndexed { index, request ->
        index.toString() to request
    }.toMap()
    val preference = when {
        requests.any { it.maxVideoHeight in 1..480 } -> QualityPreference.MAX_480P
        requests.any { it.maxVideoHeight in 481..720 } -> QualityPreference.MAX_720P
        requests.any { it.maxVideoHeight in 721..1080 } -> QualityPreference.MAX_1080P
        requests.firstOrNull()?.askQuality == true -> QualityPreference.ASK
        requests.any { it.maxVideoHeight > 1080 } -> QualityPreference.PREFER_4K
        else -> QualityPreference.AUTO
    }
    val capabilities = AndroidPlaybackCapabilities.detect(context, profile)
    val sources = requests.mapIndexed { index, request ->
        PlaybackSource(
            id = index.toString(),
            maxHeight = inferVideoHeight(request),
            codec = inferVideoCodec(request),
            type = when (request.manifest.lowercase()) {
                "hls", "m3u8" -> SourceType.HLS
                "dash", "mpd" -> SourceType.DASH
                else -> SourceType.PROGRESSIVE
            },
            priority = index,
        )
    }
    val detectedNetwork = currentNetworkType(context)
    val networkType =
        if (treatWifiAsMetered && detectedNetwork == NetworkType.WIFI) {
            NetworkType.METERED
        } else {
            detectedNetwork
        }
    val decision = PlaybackPolicy.decide(
        sources = sources,
        request = PlaybackPolicyRequest(
            preference = preference,
            networkType = networkType,
            capabilities = capabilities,
            allow4KOnMobile = allow4KOnMetered,
        ),
    )

    fun materialize(source: OrderedPlaybackSource): PlaybackRequest? =
        indexed[source.source.id]?.let { original ->
            source.trackSelectionMaxHeight?.let { original.copy(maxVideoHeight = it) } ?: original
        }

    return AndroidPlaybackPlan(
        ordered = decision.orderedSources.mapNotNull(::materialize),
        fourK = decision.confirmation?.fourKSources.orEmpty().mapNotNull(::materialize),
        standard = decision.confirmation?.standardSources.orEmpty().mapNotNull(::materialize),
        askForConfirmation = decision.askForConfirmation,
    )
}

internal fun inferVideoHeight(request: PlaybackRequest): Int {
    if (request.server.equals("fourk", ignoreCase = true)) return 2160
    val urlWithoutSecrets = request.url.substringBefore('?').substringBefore('#')
    val evidence = "${request.label} ${request.server} $urlWithoutSecrets".lowercase()
    return when {
        Regex("""(?:^|[^0-9])(2160|4k)(?:p|[^0-9]|$)""").containsMatchIn(evidence) -> 2160
        Regex("""(?:^|[^0-9])1440p?(?:[^0-9]|$)""").containsMatchIn(evidence) -> 1440
        Regex("""(?:^|[^0-9])1080p?(?:[^0-9]|$)""").containsMatchIn(evidence) -> 1080
        Regex("""(?:^|[^0-9])720p?(?:[^0-9]|$)""").containsMatchIn(evidence) -> 720
        Regex("""(?:^|[^0-9])480p?(?:[^0-9]|$)""").containsMatchIn(evidence) -> 480
        else -> 0
    }
}

internal data class DecoderDescriptor(
    val codec: VideoCodec,
    val maxHeight: Int,
    val hardwareAccelerated: Boolean,
)

internal fun summarizePlaybackCapabilities(
    displayHeight: Int,
    isLowPower: Boolean,
    decoders: List<DecoderDescriptor>,
): PlaybackCapabilities {
    val hardware = decoders.filter { it.hardwareAccelerated && it.maxHeight > 0 }
    val decoderMaxHeightByCodec = hardware
        .groupBy(DecoderDescriptor::codec)
        .mapValues { (_, descriptors) ->
            descriptors.maxOf(DecoderDescriptor::maxHeight).coerceAtMost(4_320)
        }
    return PlaybackCapabilities(
        displayMaxHeight = displayHeight.coerceAtLeast(720),
        decoderMaxHeight = hardware.maxOfOrNull(DecoderDescriptor::maxHeight)
            ?.coerceAtMost(4_320)
            ?: displayHeight.coerceAtLeast(720),
        supportedCodecs = hardware.mapTo(linkedSetOf(), DecoderDescriptor::codec),
        decoderMaxHeightByCodec = decoderMaxHeightByCodec,
        isLowPower = isLowPower,
    )
}

internal fun inferVideoCodec(request: PlaybackRequest): VideoCodec {
    val urlWithoutSecrets = request.url.substringBefore('?').substringBefore('#')
    val evidence = "${request.label} ${request.server} $urlWithoutSecrets".lowercase()
    return when {
        listOf("hevc", "h265", "h.265", "x265", "hvc1", "hev1").any(evidence::contains) ->
            VideoCodec.HEVC
        listOf("av1", "av01").any(evidence::contains) -> VideoCodec.AV1
        listOf("vp9", "vp09").any(evidence::contains) -> VideoCodec.VP9
        listOf("avc", "h264", "h.264", "x264", "avc1").any(evidence::contains) ->
            VideoCodec.AVC
        else -> VideoCodec.UNKNOWN
    }
}

private object AndroidPlaybackCapabilities {
    @Volatile
    private var cachedDecoders: List<DecoderDescriptor>? = null

    fun detect(context: Context, profile: DeviceProfile): PlaybackCapabilities =
        summarizePlaybackCapabilities(
            displayHeight = physicalDisplayHeight(context),
            isLowPower = profile.isLowPower,
            decoders = cachedDecoders ?: synchronized(this) {
                cachedDecoders ?: inspectDecoders().also { cachedDecoders = it }
            },
        )

    private fun physicalDisplayHeight(context: Context): Int {
        val metricHeight = context.resources.displayMetrics.run {
            min(widthPixels, heightPixels)
        }
        val displayManager = context.getSystemService(DisplayManager::class.java)
        val modeHeight = displayManager
            ?.displays
            .orEmpty()
            .asSequence()
            .flatMap { display -> display.supportedModes.asSequence() }
            .map { mode -> min(mode.physicalWidth, mode.physicalHeight) }
            .maxOrNull()
            ?: metricHeight
        return maxOf(metricHeight, modeHeight).coerceAtLeast(720)
    }

    private fun inspectDecoders(): List<DecoderDescriptor> =
        runCatching { MediaCodecList(MediaCodecList.ALL_CODECS).codecInfos.toList() }
            .getOrDefault(emptyList())
            .asSequence()
            .filterNot { it.isEncoder }
            .flatMap { codecInfo ->
                codecInfo.supportedTypes.asSequence().mapNotNull { mime ->
                    val codec = when (mime.lowercase()) {
                        "video/avc" -> VideoCodec.AVC
                        "video/hevc" -> VideoCodec.HEVC
                        "video/x-vnd.on2.vp9" -> VideoCodec.VP9
                        "video/av01" -> VideoCodec.AV1
                        else -> return@mapNotNull null
                    }
                    val maxHeight = runCatching {
                        codecInfo.getCapabilitiesForType(mime)
                            .videoCapabilities
                            .supportedHeights
                            .upper
                    }.getOrDefault(0)
                    DecoderDescriptor(
                        codec = codec,
                        maxHeight = maxHeight,
                        hardwareAccelerated = if (Build.VERSION.SDK_INT >= 29) {
                            codecInfo.isHardwareAccelerated
                        } else {
                            val name = codecInfo.name.lowercase()
                            !name.startsWith("omx.google.") &&
                                !name.startsWith("c2.android.") &&
                                !name.contains("ffmpeg") &&
                                !name.contains(".sw.")
                        },
                    )
                }
            }
            .toList()
}

private fun currentNetworkType(context: Context): NetworkType {
    val manager = context.getSystemService(ConnectivityManager::class.java)
        ?: return NetworkType.OTHER
    val network = manager.activeNetwork ?: return NetworkType.OFFLINE
    val capabilities = manager.getNetworkCapabilities(network) ?: return NetworkType.OFFLINE
    if (!capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) {
        return NetworkType.OFFLINE
    }
    return when {
        capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> NetworkType.ETHERNET
        capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> NetworkType.MOBILE
        manager.isActiveNetworkMetered -> NetworkType.METERED
        capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> NetworkType.WIFI
        else -> NetworkType.OTHER
    }
}
