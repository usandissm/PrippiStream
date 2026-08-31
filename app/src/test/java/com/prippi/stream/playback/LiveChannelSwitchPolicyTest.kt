package com.prippi.stream.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LiveChannelSwitchPolicyTest {
    @Test
    fun `next channel wraps and remains bounded`() {
        assertEquals(
            listOf(0, 1, 2),
            LiveChannelSwitchPolicy.candidateIndices(
                currentIndex = 3,
                total = 4,
                delta = 1,
                maxAttempts = 3,
            ),
        )
    }

    @Test
    fun `previous channel wraps backwards`() {
        assertEquals(
            listOf(3, 2, 1),
            LiveChannelSwitchPolicy.candidateIndices(
                currentIndex = 0,
                total = 4,
                delta = -1,
                maxAttempts = 3,
            ),
        )
    }

    @Test
    fun `debounce rejects rapid repeats`() {
        assertTrue(LiveChannelSwitchPolicy.acceptsInput(1_000, 0, 650))
        assertFalse(LiveChannelSwitchPolicy.acceptsInput(1_500, 1_000, 650))
        assertTrue(LiveChannelSwitchPolicy.acceptsInput(1_650, 1_000, 650))
    }
}
