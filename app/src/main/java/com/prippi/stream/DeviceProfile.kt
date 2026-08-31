package com.prippi.stream

import android.app.ActivityManager
import android.content.Context
import android.content.pm.PackageManager
import android.content.res.Configuration
import kotlin.math.min

data class DeviceProfile(
    val formFactor: FormFactor,
    val inputMode: InputMode,
    val performanceTier: PerformanceTier,
) {
    val isTelevision: Boolean
        get() = formFactor == FormFactor.TELEVISION

    val isTablet: Boolean
        get() = formFactor == FormFactor.TABLET

    val isLowPower: Boolean
        get() = performanceTier == PerformanceTier.LOW

    fun asTelevision(): DeviceProfile = copy(
        formFactor = FormFactor.TELEVISION,
        inputMode = InputMode.DPAD,
    )

    companion object {
        internal fun supportsAutomaticTrailerPreview(
            memoryClassMb: Int,
            isLowRamDevice: Boolean,
        ): Boolean = !isLowRamDevice && memoryClassMb >= 384

        internal fun isLowPowerDevice(
            memoryClassMb: Int,
            isLowRamDevice: Boolean,
        ): Boolean = isLowRamDevice || memoryClassMb <= 256

        internal fun isTelevisionDevice(
            uiModeType: Int,
            hasLeanback: Boolean,
            hasTelevisionFeature: Boolean,
            hasTouchscreen: Boolean,
            widthDp: Int,
            heightDp: Int,
        ): Boolean {
            val declaredTelevision =
                uiModeType == Configuration.UI_MODE_TYPE_TELEVISION ||
                    hasLeanback ||
                    hasTelevisionFeature
            // Several inexpensive Android boxes omit Leanback/television
            // declarations. A large landscape, non-touch window is still a
            // 10-foot surface and must never fall back to the phone UI.
            val televisionLikeWindow =
                !hasTouchscreen &&
                    widthDp >= 640 &&
                    widthDp > heightDp
            return declaredTelevision || televisionLikeWindow
        }

        fun detect(context: Context): DeviceProfile {
            val packageManager = context.packageManager
            val configuration = context.resources.configuration
            val uiMode = configuration.uiMode and
                Configuration.UI_MODE_TYPE_MASK
            val television = isTelevisionDevice(
                uiModeType = uiMode,
                hasLeanback = packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK),
                hasTelevisionFeature =
                    packageManager.hasSystemFeature(PackageManager.FEATURE_TELEVISION),
                hasTouchscreen =
                    packageManager.hasSystemFeature(PackageManager.FEATURE_TOUCHSCREEN),
                widthDp = configuration.screenWidthDp,
                heightDp = configuration.screenHeightDp,
            )
            val activityManager = context.getSystemService(ActivityManager::class.java)
            val lowRam = isLowPowerDevice(
                memoryClassMb = activityManager?.memoryClass ?: Int.MAX_VALUE,
                isLowRamDevice = activityManager?.isLowRamDevice == true,
            )
            val currentSmallestWidth = min(
                configuration.screenWidthDp,
                configuration.screenHeightDp,
            )
            val formFactor = when {
                television -> FormFactor.TELEVISION
                currentSmallestWidth >= 600 -> FormFactor.TABLET
                else -> FormFactor.PHONE
            }
            return DeviceProfile(
                formFactor = formFactor,
                inputMode = if (television) InputMode.DPAD else InputMode.TOUCH,
                performanceTier = if (lowRam) PerformanceTier.LOW else PerformanceTier.STANDARD,
            )
        }
    }
}

enum class FormFactor {
    PHONE,
    TABLET,
    TELEVISION,
}

enum class InputMode {
    TOUCH,
    DPAD,
    HYBRID,
}

enum class PerformanceTier {
    LOW,
    STANDARD,
}
