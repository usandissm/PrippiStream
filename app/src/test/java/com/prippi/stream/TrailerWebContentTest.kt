package com.prippi.stream

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TrailerWebContentTest {
    @Test
    fun extractsSupportedYoutubeUrls() {
        assertEquals("abcdefghijk", trailerYoutubeId("https://www.youtube.com/watch?v=abcdefghijk"))
        assertEquals("abcdefghijk", trailerYoutubeId("https://youtu.be/abcdefghijk?t=4"))
        assertEquals(
            "abcdefghijk",
            trailerYoutubeId("https://www.youtube-nocookie.com/embed/abcdefghijk"),
        )
    }

    @Test
    fun rejectsUnsupportedTrailerUrls() {
        assertNull(trailerYoutubeId("https://example.com/video.mp4"))
        assertNull(trailerYoutubeId("https://youtu.be/short"))
    }

    @Test
    fun previewIsMutedAndFullscreenIsNotForcedMuted() {
        val preview = trailerPlayerHtml("[\"abcdefghijk\"]", showNativeControls = false, muted = true)
        val fullscreen =
            trailerPlayerHtml("[\"abcdefghijk\"]", showNativeControls = true, muted = false)

        assertTrue(preview.contains("if (true) event.target.mute();"))
        assertTrue(preview.contains("controls: 0"))
        assertTrue(preview.contains("window.__prippiTrailerPlaying = true;"))
        assertTrue(fullscreen.contains("if (false) event.target.mute();"))
        assertTrue(fullscreen.contains("controls: 1"))
        assertFalse(fullscreen.contains("if (true) event.target.mute();"))
    }
}
