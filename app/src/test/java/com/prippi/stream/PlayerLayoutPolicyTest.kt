package com.prippi.stream

import org.junit.Assert.assertEquals
import org.junit.Test

class PlayerLayoutPolicyTest {
    @Test
    fun firstPortraitConfigurationUsesSameScaleAsSettledLandscape() {
        assertEquals(
            PlayerLayoutPolicy.landscapeUiScale(891, 411),
            PlayerLayoutPolicy.landscapeUiScale(411, 891),
            0f,
        )
        assertEquals(
            PlayerLayoutPolicy.landscapeUiScale(1280, 800),
            PlayerLayoutPolicy.landscapeUiScale(800, 1280),
            0f,
        )
    }

    @Test
    fun playerScaleKeepsExistingPhoneAndLargeScreenBounds() {
        assertEquals(0.68f, PlayerLayoutPolicy.landscapeUiScale(891, 411), 0f)
        assertEquals(1f, PlayerLayoutPolicy.landscapeUiScale(1280, 720), 0f)
        assertEquals(1.28f, PlayerLayoutPolicy.landscapeUiScale(3840, 2160), 0f)
    }

    @Test
    fun headerWidthAlwaysTracksCurrentMeasuredViewport() {
        assertEquals(742, PlayerLayoutPolicy.headerContentWidth(1280))
        assertEquals(1114, PlayerLayoutPolicy.headerContentWidth(1920))
        assertEquals(1, PlayerLayoutPolicy.headerContentWidth(0))
    }
}
