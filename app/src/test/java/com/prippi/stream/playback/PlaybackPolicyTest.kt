package com.prippi.stream.playback

import org.junit.Test

/**
 * Dependency-free JVM contract tests. They intentionally use only the Kotlin
 * standard library so this new pure policy can be verified without changing
 * the app module dependencies.
 */
class PlaybackPolicyTest {
    private val fourKProgressive = PlaybackSource(
        id = "fourk-progressive",
        maxHeight = 2160,
        codec = VideoCodec.HEVC,
        type = SourceType.PROGRESSIVE,
    )
    private val fullHdFallback = PlaybackSource(
        id = "full-hd-fallback",
        maxHeight = 1080,
        codec = VideoCodec.AVC,
        type = SourceType.HLS,
        priority = 10,
    )
    private val hdFallback = PlaybackSource(
        id = "hd-fallback",
        maxHeight = 720,
        codec = VideoCodec.AVC,
        type = SourceType.HLS,
        priority = 20,
    )
    private val fourKCapabilities = PlaybackCapabilities(
        displayMaxHeight = 2160,
        decoderMaxHeight = 2160,
        supportedCodecs = setOf(VideoCodec.AVC, VideoCodec.HEVC),
    )

    @Test
    fun playbackPolicyContract() {
        autoCapsLowPowerBoxAtFullHd()
        mobileNetworkBlocksFourKWithoutExplicitOptIn()
        mobileNetworkAllowsFourKAfterExplicitOptIn()
        askRequiresBothFourKAndStandardChoices()
        askDoesNotPromptWithoutARealFallback()
        max1080RejectsProgressiveFourKInsteadOfPretendingToDownscaleIt()
        adaptiveManifestCanBeConstrainedTo1080()
        unknownAdaptiveManifestStillReceivesNetworkCeiling()
        max720ConstrainsAdaptiveSourcesAndRetainsFallback()
        max480IsRepresentedExactly()
        unsupportedFourKCodecFallsBack()
        codecSpecificDecoderLimitIsRespected()
        fallbackOrderIsDeterministic()
        offlineRejectsEverySource()
    }

    private fun autoCapsLowPowerBoxAtFullHd() {
        val decision = decide(
            sources = listOf(fourKProgressive, fullHdFallback, hdFallback),
            preference = QualityPreference.AUTO,
            capabilities = fourKCapabilities.copy(isLowPower = true),
        )

        assertIds(decision, "full-hd-fallback", "hd-fallback")
        assertRejected(
            decision,
            "fourk-progressive",
            RejectionReason.EXCEEDS_QUALITY_PREFERENCE,
        )
        assertFalse(decision.askForConfirmation)
    }

    private fun mobileNetworkBlocksFourKWithoutExplicitOptIn() {
        val decision = decide(
            sources = listOf(fourKProgressive, fullHdFallback),
            preference = QualityPreference.PREFER_4K,
            networkType = NetworkType.MOBILE,
        )

        assertIds(decision, "full-hd-fallback")
        assertRejected(
            decision,
            "fourk-progressive",
            RejectionReason.EXCEEDS_QUALITY_PREFERENCE,
        )
    }

    private fun mobileNetworkAllowsFourKAfterExplicitOptIn() {
        val decision = decide(
            sources = listOf(fullHdFallback, fourKProgressive),
            preference = QualityPreference.PREFER_4K,
            networkType = NetworkType.MOBILE,
            allow4KOnMobile = true,
        )

        assertIds(decision, "fourk-progressive", "full-hd-fallback")
    }

    private fun askRequiresBothFourKAndStandardChoices() {
        val decision = decide(
            sources = listOf(fullHdFallback, fourKProgressive),
            preference = QualityPreference.ASK,
        )

        assertTrue(decision.askForConfirmation)
        assertEquals(listOf("fourk-progressive"), decision.confirmation?.fourKSources?.ids())
        assertEquals(listOf("full-hd-fallback"), decision.confirmation?.standardSources?.ids())
    }

    private fun askDoesNotPromptWithoutARealFallback() {
        val decision = decide(
            sources = listOf(fourKProgressive),
            preference = QualityPreference.ASK,
        )

        assertFalse(decision.askForConfirmation)
        assertEquals(null, decision.confirmation)
    }

    private fun max1080RejectsProgressiveFourKInsteadOfPretendingToDownscaleIt() {
        val decision = decide(
            sources = listOf(fourKProgressive, fullHdFallback),
            preference = QualityPreference.MAX_1080P,
        )

        assertIds(decision, "full-hd-fallback")
        assertRejected(
            decision,
            "fourk-progressive",
            RejectionReason.EXCEEDS_QUALITY_PREFERENCE,
        )
    }

    private fun adaptiveManifestCanBeConstrainedTo1080() {
        val adaptiveFourK = PlaybackSource(
            id = "adaptive-fourk",
            maxHeight = 2160,
            codec = VideoCodec.HEVC,
            type = SourceType.DASH,
            variantHeights = setOf(2160, 1080, 720),
        )
        val decision = decide(
            sources = listOf(adaptiveFourK),
            preference = QualityPreference.MAX_1080P,
        )

        assertIds(decision, "adaptive-fourk")
        assertEquals(1080, decision.orderedSources.single().selectedHeight)
        assertEquals(1080, decision.orderedSources.single().trackSelectionMaxHeight)
        assertFalse(decision.orderedSources.single().isFourK)
    }

    private fun max720ConstrainsAdaptiveSourcesAndRetainsFallback() {
        val decision = decide(
            sources = listOf(fourKProgressive, fullHdFallback, hdFallback),
            preference = QualityPreference.MAX_720P,
        )

        assertIds(decision, "full-hd-fallback", "hd-fallback")
        assertTrue(decision.orderedSources.all { it.selectedHeight == 720 })
        assertEquals(720, decision.orderedSources.first().trackSelectionMaxHeight)
        assertEquals(null, decision.orderedSources.last().trackSelectionMaxHeight)
    }

    private fun unknownAdaptiveManifestStillReceivesNetworkCeiling() {
        val unknownAdaptive = PlaybackSource(
            id = "unknown-hls",
            maxHeight = 0,
            codec = VideoCodec.UNKNOWN,
            type = SourceType.HLS,
        )
        val decision = decide(
            sources = listOf(unknownAdaptive),
            preference = QualityPreference.PREFER_4K,
            networkType = NetworkType.METERED,
        )

        assertIds(decision, "unknown-hls")
        assertEquals(1080, decision.orderedSources.single().trackSelectionMaxHeight)
    }

    private fun max480IsRepresentedExactly() {
        val decision = decide(
            sources = listOf(fullHdFallback),
            preference = QualityPreference.MAX_480P,
        )

        assertIds(decision, "full-hd-fallback")
        assertEquals(480, decision.orderedSources.single().selectedHeight)
        assertEquals(480, decision.orderedSources.single().trackSelectionMaxHeight)
    }

    private fun unsupportedFourKCodecFallsBack() {
        val avcOnly = PlaybackCapabilities(
            displayMaxHeight = 2160,
            decoderMaxHeight = 2160,
            supportedCodecs = setOf(VideoCodec.AVC),
        )
        val decision = decide(
            sources = listOf(fourKProgressive, fullHdFallback),
            preference = QualityPreference.PREFER_4K,
            capabilities = avcOnly,
        )

        assertIds(decision, "full-hd-fallback")
        assertRejected(decision, "fourk-progressive", RejectionReason.UNSUPPORTED_CODEC)
    }

    private fun codecSpecificDecoderLimitIsRespected() {
        val perCodecCapabilities = fourKCapabilities.copy(
            decoderMaxHeightByCodec = mapOf(
                VideoCodec.AVC to 2160,
                VideoCodec.HEVC to 1080,
            ),
        )
        val avcFourK = fourKProgressive.copy(id = "avc-fourk", codec = VideoCodec.AVC)
        val decision = decide(
            sources = listOf(fourKProgressive, avcFourK, fullHdFallback),
            preference = QualityPreference.PREFER_4K,
            capabilities = perCodecCapabilities,
        )

        assertIds(decision, "avc-fourk", "full-hd-fallback")
        assertRejected(
            decision,
            "fourk-progressive",
            RejectionReason.EXCEEDS_DEVICE_CAPABILITY,
        )
    }

    private fun fallbackOrderIsDeterministic() {
        val firstFallback = fullHdFallback.copy(id = "fallback-a", priority = 2)
        val secondFallback = fullHdFallback.copy(id = "fallback-b", priority = 3)
        val decision = decide(
            sources = listOf(secondFallback, firstFallback, fourKProgressive),
            preference = QualityPreference.PREFER_4K,
        )

        assertIds(decision, "fourk-progressive", "fallback-a", "fallback-b")
    }

    private fun offlineRejectsEverySource() {
        val decision = decide(
            sources = listOf(fourKProgressive, fullHdFallback),
            preference = QualityPreference.AUTO,
            networkType = NetworkType.OFFLINE,
        )

        assertTrue(decision.orderedSources.isEmpty())
        assertTrue(decision.rejectedSources.all {
            it.reason == RejectionReason.NETWORK_UNAVAILABLE
        })
        assertFalse(decision.askForConfirmation)
    }

    private fun decide(
        sources: List<PlaybackSource>,
        preference: QualityPreference,
        networkType: NetworkType = NetworkType.WIFI,
        capabilities: PlaybackCapabilities = fourKCapabilities,
        allow4KOnMobile: Boolean = false,
    ): PlaybackPolicyDecision = PlaybackPolicy.decide(
        sources = sources,
        request = PlaybackPolicyRequest(
            preference = preference,
            networkType = networkType,
            capabilities = capabilities,
            allow4KOnMobile = allow4KOnMobile,
        ),
    )

    private fun assertIds(decision: PlaybackPolicyDecision, vararg expected: String) {
        assertEquals(expected.toList(), decision.orderedSources.ids())
    }

    private fun List<OrderedPlaybackSource>.ids(): List<String> = map { it.source.id }

    private fun assertRejected(
        decision: PlaybackPolicyDecision,
        sourceId: String,
        reason: RejectionReason,
    ) {
        assertTrue(decision.rejectedSources.any {
            it.source.id == sourceId && it.reason == reason
        })
    }

    private fun assertTrue(value: Boolean) {
        check(value) { "Expected true" }
    }

    private fun assertFalse(value: Boolean) {
        check(!value) { "Expected false" }
    }

    private fun assertEquals(expected: Any?, actual: Any?) {
        check(expected == actual) { "Expected <$expected>, got <$actual>" }
    }
}
