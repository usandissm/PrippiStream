package com.prippi.stream

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ScPlaybackRequestTest {
    @Test fun publicFallbackAndPreferencesSurviveIntentRoundTrip() {
        val original = PlaybackRequest(
            url = "", bootstrapUrl = "", manifest = "sc_free_fallback",
            audioLanguage = "it", headersJson = "{}", label = "SC",
            maxVideoHeight = 720, textLanguage = "it", autoplayNext = false,
            scFreeFallbackJson = JSONObject().put("channel", "streamingcommunity")
                .put("url", "https://catalog.example/it/iframe/12?episode_id=34").toString(),
        )
        val restored = PlaybackRequest.fromJson(original.toJson())
        assertEquals(original, restored)
        assertEquals(720, restored.maxVideoHeight)
        assertFalse(restored.autoplayNext)
        assertTrue(restored.url.isBlank())
        assertFalse(restored.scFreeFallbackJson.contains("token"))
    }

    @Test fun legacyPlaybackRemainsCompatible() {
        val original = PlaybackRequest("https://example.org/v.m3u8", "", "hls", "it", "{}")
        assertFalse(original.toJson().has("sc_free_fallback_json"))
        val restored = PlaybackRequest.fromJson(original.toJson())
        assertEquals("", restored.scFreeFallbackJson)
        assertEquals(original.url, restored.url)
    }
}
