package com.prippi.stream

import org.junit.Assert.*
import org.junit.Test

class TimelineAndForcedSubtitlesTest {
    @Test fun `forced Italian flag wins over default full Italian and English forced`() {
        val full = TrackCandidate(0, 0, TrackDescriptor("it", "Italian", selectionFlags = 1))
        val english = TrackCandidate(1, 0, TrackDescriptor("en", "English (Forced)", selectionFlags = 2))
        val forced = TrackCandidate(2, 0, TrackDescriptor("ita-IT", "Italian", selectionFlags = 2))
        assertEquals(forced, MediaTrackPreferencePolicy.italianForced(listOf(full, english, forced)))
    }
    @Test fun `forced label supports old offline manifests without the flag`() {
        val candidate = TrackCandidate(0, 0, TrackDescriptor("it", "Italian (Forced)"))
        assertEquals(candidate, MediaTrackPreferencePolicy.italianForced(listOf(candidate)))
        assertNull(MediaTrackPreferencePolicy.italianForced(listOf(candidate.copy(supported = false))))
    }
    @Test fun `full subtitles are not mistaken for forced`() {
        assertNull(MediaTrackPreferencePolicy.italianForced(listOf(
            TrackCandidate(0, 0, TrackDescriptor("it", "Italian")),
            TrackCandidate(1, 0, TrackDescriptor("en", "Forced", selectionFlags = 2)))))
    }
    @Test fun `preview positions cannot go beyond the file duration`() {
        assertEquals(0L, TimelinePreviewPolicy.position(-100, 10000))
        assertEquals(9999L, TimelinePreviewPolicy.position(20000, 10000))
        assertEquals(0L, TimelinePreviewPolicy.position(20000, 0))
    }
    @Test fun `preview label represents the selected timeline position`() {
        assertEquals("2:05", TimelinePreviewPolicy.label(125000))
        assertEquals("1:02:03", TimelinePreviewPolicy.label(3723000))
    }
    @Test fun `preview cache buckets are stable across small pointer movements`() {
        assertEquals(10000L, TimelinePreviewPolicy.bucket(10400, 120000))
        assertEquals(10000L, TimelinePreviewPolicy.bucket(14999, 120000))
        assertEquals(15000L, TimelinePreviewPolicy.bucket(15000, 120000))
    }
    @Test fun `warm cache covers the whole title before detailed subdivisions`() {
        val targets = TimelinePreviewPolicy.warmTargets(120000, 10000, 6)
        assertEquals(listOf(10000L, 0L, 60000L, 30000L, 90000L, 15000L), targets)
        assertEquals(targets.size, targets.toSet().size)
        assertTrue(TimelinePreviewPolicy.warmTargets(1000, 0).all { it in 0 until 1000 })
        assertTrue(TimelinePreviewPolicy.warmTargets(0, 0).isEmpty())
    }
    @Test fun `cached preview changes immediately with pointer position`() {
        val keys = listOf(0L, 5000L, 10000L, 15000L)
        assertEquals(0L, TimelinePreviewPolicy.nearest(keys, 1000))
        assertEquals(10000L, TimelinePreviewPolicy.nearest(keys, 11000))
        assertEquals(15000L, TimelinePreviewPolicy.nearest(keys, 14900))
        assertNull(TimelinePreviewPolicy.nearest(emptyList(), 1000))
    }
}
