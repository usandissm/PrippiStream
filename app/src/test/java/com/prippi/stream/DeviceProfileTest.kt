package com.prippi.stream

import android.content.res.Configuration
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceProfileTest {
    @Test
    fun automaticTrailerPreviewRequiresComfortableTvHeap() {
        assertFalse(DeviceProfile.supportsAutomaticTrailerPreview(128, isLowRamDevice = false))
        assertFalse(DeviceProfile.supportsAutomaticTrailerPreview(256, isLowRamDevice = false))
        assertFalse(DeviceProfile.supportsAutomaticTrailerPreview(512, isLowRamDevice = true))
        assertTrue(DeviceProfile.supportsAutomaticTrailerPreview(384, isLowRamDevice = false))
        assertTrue(DeviceProfile.supportsAutomaticTrailerPreview(512, isLowRamDevice = false))
    }

    @Test
    fun lowPowerClassificationIncludesSmallBoxHeaps() {
        assertTrue(DeviceProfile.isLowPowerDevice(128, isLowRamDevice = false))
        assertTrue(DeviceProfile.isLowPowerDevice(256, isLowRamDevice = false))
        assertTrue(DeviceProfile.isLowPowerDevice(512, isLowRamDevice = true))
        assertFalse(DeviceProfile.isLowPowerDevice(384, isLowRamDevice = false))
    }

    @Test
    fun undeclaredNonTouchLandscapeBoxStillUsesTelevisionUi() {
        assertTrue(
            DeviceProfile.isTelevisionDevice(
                uiModeType = Configuration.UI_MODE_TYPE_NORMAL,
                hasLeanback = false,
                hasTelevisionFeature = false,
                hasTouchscreen = false,
                widthDp = 1280,
                heightDp = 720,
            ),
        )
    }

    @Test
    fun touchscreenTabletIsNotMisclassifiedAsTelevision() {
        assertFalse(
            DeviceProfile.isTelevisionDevice(
                uiModeType = Configuration.UI_MODE_TYPE_NORMAL,
                hasLeanback = false,
                hasTelevisionFeature = false,
                hasTouchscreen = true,
                widthDp = 1280,
                heightDp = 800,
            ),
        )
    }
}
