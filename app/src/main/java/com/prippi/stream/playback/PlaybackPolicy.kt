package com.prippi.stream.playback

/**
 * User-facing quality preference. Presentation layers may render these values
 * differently, while this policy remains shared by phone, tablet and TV.
 */
enum class QualityPreference {
    AUTO,
    PREFER_4K,
    ASK,
    MAX_1080P,
    MAX_720P,
    MAX_480P,
}

enum class NetworkType {
    ETHERNET,
    WIFI,
    MOBILE,
    METERED,
    OTHER,
    OFFLINE,
}

enum class VideoCodec {
    AVC,
    HEVC,
    VP9,
    AV1,
    UNKNOWN,
}

enum class SourceType {
    HLS,
    DASH,
    PROGRESSIVE,
}

/**
 * A source before Media3 is created.
 *
 * [maxHeight] is zero when resolution is unknown. [variantHeights] should be
 * populated when an adaptive manifest has already been inspected; an empty set
 * means that Media3 will discover and constrain its tracks at prepare time.
 */
data class PlaybackSource(
    val id: String,
    val maxHeight: Int,
    val codec: VideoCodec = VideoCodec.UNKNOWN,
    val type: SourceType,
    val variantHeights: Set<Int> = emptySet(),
    val priority: Int = 0,
) {
    init {
        require(id.isNotBlank()) { "A playback source must have a stable id" }
        require(maxHeight >= 0) { "Source height cannot be negative" }
        require(variantHeights.all { it > 0 }) { "Variant heights must be positive" }
    }

    val isAdaptive: Boolean
        get() = type == SourceType.HLS || type == SourceType.DASH
}

/**
 * Capability values are intentionally platform-neutral. The Android boundary
 * is responsible only for detecting them and mapping them into this model.
 *
 * An empty [supportedCodecs] set means that codec support is unknown, rather
 * than that no codec is supported.
 */
data class PlaybackCapabilities(
    val displayMaxHeight: Int,
    val decoderMaxHeight: Int,
    val supportedCodecs: Set<VideoCodec> = emptySet(),
    val decoderMaxHeightByCodec: Map<VideoCodec, Int> = emptyMap(),
    val isLowPower: Boolean = false,
) {
    init {
        require(displayMaxHeight > 0) { "Display height must be positive" }
        require(decoderMaxHeight > 0) { "Decoder height must be positive" }
    }

    fun maximumUsableHeight(codec: VideoCodec): Int {
        val codecLimit = if (codec == VideoCodec.UNKNOWN) {
            decoderMaxHeightByCodec.values.minOrNull() ?: decoderMaxHeight
        } else {
            decoderMaxHeightByCodec[codec] ?: decoderMaxHeight
        }
        return minOf(displayMaxHeight, codecLimit)
    }

    fun supports(codec: VideoCodec): Boolean =
        codec == VideoCodec.UNKNOWN ||
            supportedCodecs.isEmpty() ||
            codec in supportedCodecs
}

data class PlaybackPolicyRequest(
    val preference: QualityPreference,
    val networkType: NetworkType,
    val capabilities: PlaybackCapabilities,
    /**
     * Explicit opt-in. It is deliberately independent from PREFER_4K so that a
     * preference selected on Wi-Fi cannot unexpectedly consume mobile data.
     */
    val allow4KOnMobile: Boolean = false,
)

data class OrderedPlaybackSource(
    val source: PlaybackSource,
    /**
     * Maximum track height to pass to an adaptive player. Null means that the
     * source can be played as-is. Progressive files are never down-selected.
     */
    val trackSelectionMaxHeight: Int?,
    val selectedHeight: Int,
) {
    val isFourK: Boolean
        get() = selectedHeight > FULL_HD_HEIGHT
}

data class QualityConfirmation(
    val fourKSources: List<OrderedPlaybackSource>,
    val standardSources: List<OrderedPlaybackSource>,
)

enum class RejectionReason {
    NETWORK_UNAVAILABLE,
    UNSUPPORTED_CODEC,
    EXCEEDS_DEVICE_CAPABILITY,
    EXCEEDS_QUALITY_PREFERENCE,
}

data class RejectedPlaybackSource(
    val source: PlaybackSource,
    val reason: RejectionReason,
)

data class PlaybackPolicyDecision(
    val orderedSources: List<OrderedPlaybackSource>,
    val askForConfirmation: Boolean,
    val confirmation: QualityConfirmation?,
    val rejectedSources: List<RejectedPlaybackSource>,
)

/**
 * Pure quality and source-ordering policy shared by every app form factor.
 */
object PlaybackPolicy {
    fun decide(
        sources: List<PlaybackSource>,
        request: PlaybackPolicyRequest,
    ): PlaybackPolicyDecision {
        if (request.networkType == NetworkType.OFFLINE) {
            return PlaybackPolicyDecision(
                orderedSources = emptyList(),
                askForConfirmation = false,
                confirmation = null,
                rejectedSources = sources.map {
                    RejectedPlaybackSource(it, RejectionReason.NETWORK_UNAVAILABLE)
                },
            )
        }

        val accepted = mutableListOf<IndexedValue<OrderedPlaybackSource>>()
        val rejected = mutableListOf<RejectedPlaybackSource>()

        sources.forEachIndexed { index, source ->
            val capabilityLimit = request.capabilities.maximumUsableHeight(source.codec)
            val policyLimit = qualityLimit(request, capabilityLimit)
            when {
                !request.capabilities.supports(source.codec) -> {
                    rejected += RejectedPlaybackSource(source, RejectionReason.UNSUPPORTED_CODEC)
                }

                selectableHeight(source, capabilityLimit) == null -> {
                    rejected += RejectedPlaybackSource(
                        source,
                        RejectionReason.EXCEEDS_DEVICE_CAPABILITY,
                    )
                }

                else -> {
                    val selectedHeight = selectableHeight(source, policyLimit)
                    if (selectedHeight == null) {
                        rejected += RejectedPlaybackSource(
                            source,
                            RejectionReason.EXCEEDS_QUALITY_PREFERENCE,
                        )
                    } else {
                        accepted += IndexedValue(
                            index,
                            OrderedPlaybackSource(
                                source = source,
                                trackSelectionMaxHeight = trackSelectionLimit(
                                    source = source,
                                    selectedHeight = selectedHeight,
                                    policyLimit = policyLimit,
                                ),
                                selectedHeight = selectedHeight,
                            ),
                        )
                    }
                }
            }
        }

        val ordered = accepted
            .sortedWith(
                compareByDescending<IndexedValue<OrderedPlaybackSource>> {
                    qualityTier(it.value.selectedHeight)
                }.thenBy { it.value.source.priority }
                    .thenBy { it.index },
            )
            .map(IndexedValue<OrderedPlaybackSource>::value)

        val fourK = ordered.filter(OrderedPlaybackSource::isFourK)
        val standard = ordered.filterNot(OrderedPlaybackSource::isFourK)
        val shouldAsk =
            request.preference == QualityPreference.ASK && fourK.isNotEmpty() && standard.isNotEmpty()

        return PlaybackPolicyDecision(
            orderedSources = ordered,
            askForConfirmation = shouldAsk,
            confirmation = if (shouldAsk) QualityConfirmation(fourK, standard) else null,
            rejectedSources = rejected,
        )
    }

    private fun qualityLimit(
        request: PlaybackPolicyRequest,
        capabilityLimit: Int,
    ): Int {
        val preferenceLimit = when (request.preference) {
            QualityPreference.MAX_480P -> SD_HEIGHT
            QualityPreference.MAX_720P -> HD_HEIGHT
            QualityPreference.MAX_1080P -> FULL_HD_HEIGHT
            QualityPreference.AUTO -> if (request.capabilities.isLowPower) {
                FULL_HD_HEIGHT
            } else {
                capabilityLimit
            }
            QualityPreference.PREFER_4K,
            QualityPreference.ASK,
            -> capabilityLimit
        }
        val networkLimit =
            if (
                request.networkType in setOf(NetworkType.MOBILE, NetworkType.METERED) &&
                !request.allow4KOnMobile
            ) {
                FULL_HD_HEIGHT
            } else {
                capabilityLimit
            }
        return minOf(capabilityLimit, preferenceLimit, networkLimit)
    }

    private fun selectableHeight(source: PlaybackSource, limit: Int): Int? {
        if (source.maxHeight == 0) return UNKNOWN_HEIGHT
        if (source.maxHeight <= limit) return source.maxHeight
        if (!source.isAdaptive) return null

        val knownVariants = source.variantHeights
            .asSequence()
            .filter { it <= source.maxHeight && it <= limit }
            .maxOrNull()
        if (source.variantHeights.isNotEmpty()) return knownVariants

        // The manifest has not been inspected yet. Media3 can apply a track
        // ceiling after parsing it, unlike a progressive file.
        return limit
    }

    private fun trackSelectionLimit(
        source: PlaybackSource,
        selectedHeight: Int,
        policyLimit: Int,
    ): Int? =
        if (source.isAdaptive && source.maxHeight == 0) {
            policyLimit
        } else if (source.isAdaptive && source.maxHeight > selectedHeight) {
            policyLimit
        } else {
            null
        }

    private fun qualityTier(height: Int): Int = when {
        height > FULL_HD_HEIGHT -> 3
        height > HD_HEIGHT -> 2
        height > UNKNOWN_HEIGHT -> 1
        else -> 0
    }
}

private const val UNKNOWN_HEIGHT = 0
private const val SD_HEIGHT = 480
private const val HD_HEIGHT = 720
private const val FULL_HD_HEIGHT = 1080
