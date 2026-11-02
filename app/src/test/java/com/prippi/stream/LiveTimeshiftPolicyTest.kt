package com.prippi.stream

import org.junit.Assert.*
import org.junit.Test

class LiveTimeshiftPolicyTest {
    @Test fun disabledByDefaultAndEventsExcluded() {
        assertFalse(LiveTimeshiftPolicy.available(false, true, false, true, 7_200_000))
        assertFalse(LiveTimeshiftPolicy.available(true, true, true, true, 7_200_000))
        assertFalse(LiveTimeshiftPolicy.available(true, false, false, true, 7_200_000))
        assertFalse(LiveTimeshiftPolicy.available(true, true, false, false, 7_200_000))
        assertFalse(LiveTimeshiftPolicy.available(true, true, false, true, -1))
        assertTrue(LiveTimeshiftPolicy.available(true, true, false, true, 60_000))
    }
    @Test fun usesOnlyManifestWindowWithoutInventingTwoHours() {
        assertEquals(0L, LiveTimeshiftPolicy.target(0, 10000, 60_000))
        assertEquals(30_000L, LiveTimeshiftPolicy.target(5000, 10000, 60_000))
        assertEquals(60_000L, LiveTimeshiftPolicy.target(10000, 10000, 60_000))
    }
    @Test fun longerWindowsAreCappedAtTwoHours() {
        assertEquals(3_600_000L, LiveTimeshiftPolicy.target(0, 10000, 10_800_000))
        assertEquals(7_200_000L, LiveTimeshiftPolicy.length(10_800_000))
        assertEquals(7_200_000L, LiveTimeshiftPolicy.target(5000, 10000, 10_800_000))
        assertEquals(10_800_000L, LiveTimeshiftPolicy.target(10000, 10000, 10_800_000))
    }
    @Test fun positionsRemainClampedWhileManifestSlides() {
        assertEquals(3_600_000L, LiveTimeshiftPolicy.target(-5, 10000, 10_800_000))
        assertEquals(10_800_000L, LiveTimeshiftPolicy.target(20000, 10000, 10_800_000))
        assertEquals(0L, LiveTimeshiftPolicy.behind(100_000, 60_000))
        assertEquals(30_000L, LiveTimeshiftPolicy.behind(30_000, 60_000))
    }
}
