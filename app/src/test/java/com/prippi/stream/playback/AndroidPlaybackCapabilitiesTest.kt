package com.prippi.stream.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidPlaybackCapabilitiesTest {
    @Test
    fun usesHardwareDecoderCeilingAndCodecSet() {
        val capabilities = summarizePlaybackCapabilities(
            displayHeight = 2160,
            isLowPower = false,
            decoders = listOf(
                DecoderDescriptor(VideoCodec.AVC, 1080, hardwareAccelerated = true),
                DecoderDescriptor(VideoCodec.HEVC, 2160, hardwareAccelerated = true),
                DecoderDescriptor(VideoCodec.AV1, 4320, hardwareAccelerated = false),
            ),
        )

        assertEquals(2160, capabilities.displayMaxHeight)
        assertEquals(2160, capabilities.decoderMaxHeight)
        assertEquals(setOf(VideoCodec.AVC, VideoCodec.HEVC), capabilities.supportedCodecs)
        assertEquals(1080, capabilities.decoderMaxHeightByCodec[VideoCodec.AVC])
        assertEquals(2160, capabilities.decoderMaxHeightByCodec[VideoCodec.HEVC])
        assertEquals(1080, capabilities.maximumUsableHeight(VideoCodec.UNKNOWN))
    }

    @Test
    fun fallsBackToDisplayWhenHardwareInformationIsUnavailable() {
        val capabilities = summarizePlaybackCapabilities(
            displayHeight = 1080,
            isLowPower = true,
            decoders = emptyList(),
        )

        assertEquals(1080, capabilities.decoderMaxHeight)
        assertTrue(capabilities.supportedCodecs.isEmpty())
        assertTrue(capabilities.isLowPower)
    }

    @Test
    fun capsBrokenCodecRangesToEightKHeight() {
        val capabilities = summarizePlaybackCapabilities(
            displayHeight = 2160,
            isLowPower = false,
            decoders = listOf(
                DecoderDescriptor(VideoCodec.HEVC, Int.MAX_VALUE, hardwareAccelerated = true),
            ),
        )

        assertEquals(4320, capabilities.decoderMaxHeight)
    }

    @Test
    fun infersCodecWithoutInspectingUrlSecrets() {
        assertEquals(VideoCodec.HEVC, inferVideoCodec(request(label = "2160p HEVC")))
        assertEquals(VideoCodec.AV1, inferVideoCodec(request(url = "https://cdn/video-av01.mpd")))
        assertEquals(VideoCodec.VP9, inferVideoCodec(request(server = "vp09")))
        assertEquals(VideoCodec.AVC, inferVideoCodec(request(label = "H.264")))
        assertEquals(
            VideoCodec.UNKNOWN,
            inferVideoCodec(request(url = "https://cdn/video.m3u8?token=hevc")),
        )
    }

    @Test
    fun infersExplicitHeightWithoutInspectingUrlSecrets() {
        assertEquals(2160, inferVideoHeight(request(label = "Ultra HD 2160p")))
        assertEquals(2160, inferVideoHeight(request(server = "fourk")))
        assertEquals(1080, inferVideoHeight(request(url = "https://cdn/video-1080.m3u8")))
        assertEquals(
            0,
            inferVideoHeight(request(url = "https://cdn/video.m3u8?quality=2160")),
        )
    }

    private fun request(
        url: String = "https://cdn/video.m3u8",
        label: String = "Sorgente",
        server: String = "directo",
    ) = com.prippi.stream.PlaybackRequest(
        url = url,
        bootstrapUrl = "",
        manifest = "hls",
        audioLanguage = "it",
        headersJson = "{}",
        label = label,
        server = server,
    )
}
