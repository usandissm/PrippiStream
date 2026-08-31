package com.prippi.stream

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val PrippiColorScheme = darkColorScheme(
    primary = Color(0xFF9FCBFF),
    onPrimary = Color(0xFF003258),
    secondary = Color(0xFFB9C8DB),
    background = Color(0xFF0A0E13),
    onBackground = Color(0xFFF2F6FA),
    surface = Color(0xFF111820),
    onSurface = Color(0xFFF2F6FA),
    surfaceVariant = Color(0xFF1B2632),
    onSurfaceVariant = Color(0xFFC5D0DC),
)

@Immutable
data class PrippiDimensions(
    val screenHorizontalPadding: Dp,
    val screenVerticalPadding: Dp,
    val railWidth: Dp,
    val heroHeight: Dp,
    val mediaCardWidth: Dp,
    val mediaCardImageHeight: Dp,
    val rowSpacing: Dp,
    val cardSpacing: Dp,
    val focusScale: Float,
    val heroDebounceMillis: Long,
    val uiScale: Float,
)

private val PhoneDimensions = PrippiDimensions(
    screenHorizontalPadding = 16.dp,
    screenVerticalPadding = 12.dp,
    railWidth = 0.dp,
    heroHeight = 220.dp,
    mediaCardWidth = 152.dp,
    mediaCardImageHeight = 86.dp,
    rowSpacing = 16.dp,
    cardSpacing = 12.dp,
    focusScale = 1f,
    heroDebounceMillis = 0L,
    uiScale = 1f,
)

private val TabletDimensions = PrippiDimensions(
    screenHorizontalPadding = 24.dp,
    screenVerticalPadding = 18.dp,
    railWidth = 0.dp,
    heroHeight = 252.dp,
    mediaCardWidth = 190.dp,
    mediaCardImageHeight = 108.dp,
    rowSpacing = 18.dp,
    cardSpacing = 14.dp,
    focusScale = 1f,
    heroDebounceMillis = 0L,
    uiScale = 1f,
)

private fun televisionDimensions(
    profile: DeviceProfile,
    widthDp: Int,
    heightDp: Int,
): PrippiDimensions {
    // 1280x720 dp is the design canvas. Android normally keeps this logical
    // canvas stable across Full HD and 4K televisions; smaller windows and
    // unusual aspect ratios are scaled as one coherent system.
    val scale = minOf(
        widthDp.coerceAtLeast(1) / 1280f,
        heightDp.coerceAtLeast(1) / 720f,
    ).coerceIn(0.78f, 1.28f)
    return PrippiDimensions(
    screenHorizontalPadding = (46f * scale).dp,
    screenVerticalPadding = (24f * scale).dp,
    railWidth = (104f * scale).dp,
    heroHeight = (244f * scale).dp,
    mediaCardWidth = (220f * scale).dp,
    mediaCardImageHeight = (124f * scale).dp,
    rowSpacing = (18f * scale).dp,
    cardSpacing = (16f * scale).dp,
    focusScale = 1.045f,
    heroDebounceMillis = if (profile.isLowPower) 240L else 170L,
    uiScale = scale,
    )
}

val LocalPrippiDimensions = staticCompositionLocalOf { PhoneDimensions }

private val PhoneTypography = Typography()

private val TabletTypography = Typography(
    headlineLarge = TextStyle(fontSize = 36.sp, lineHeight = 43.sp, fontWeight = FontWeight.Bold),
    headlineSmall = TextStyle(fontSize = 25.sp, lineHeight = 31.sp, fontWeight = FontWeight.SemiBold),
    titleLarge = TextStyle(fontSize = 23.sp, lineHeight = 29.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 19.sp, lineHeight = 25.sp, fontWeight = FontWeight.Medium),
    titleSmall = TextStyle(fontSize = 16.sp, lineHeight = 22.sp, fontWeight = FontWeight.Medium),
    bodyLarge = TextStyle(fontSize = 17.sp, lineHeight = 24.sp),
    bodyMedium = TextStyle(fontSize = 15.sp, lineHeight = 21.sp),
    bodySmall = TextStyle(fontSize = 14.sp, lineHeight = 19.sp),
    labelLarge = TextStyle(fontSize = 16.sp, lineHeight = 21.sp, fontWeight = FontWeight.SemiBold),
    labelMedium = TextStyle(fontSize = 14.sp, lineHeight = 19.sp, fontWeight = FontWeight.Medium),
    labelSmall = TextStyle(fontSize = 13.sp, lineHeight = 18.sp, fontWeight = FontWeight.Medium),
)

private fun televisionTypography(scale: Float): Typography {
    val textScale = scale.coerceIn(0.86f, 1.18f)
    fun text(size: Float, line: Float, weight: FontWeight? = null) = TextStyle(
        fontSize = (size * textScale).sp,
        lineHeight = (line * textScale).sp,
        fontWeight = weight,
    )
    return Typography(
        displaySmall = text(42f, 48f, FontWeight.Black),
        headlineLarge = text(40f, 46f, FontWeight.Black),
        headlineMedium = text(30f, 37f, FontWeight.Bold),
        headlineSmall = text(24f, 30f, FontWeight.Bold),
        titleLarge = text(22f, 28f, FontWeight.SemiBold),
        titleMedium = text(20f, 26f, FontWeight.SemiBold),
        titleSmall = text(18f, 24f, FontWeight.SemiBold),
        bodyLarge = text(18f, 24f),
        bodyMedium = text(16f, 22f),
        bodySmall = text(14f, 20f),
        labelLarge = text(18f, 24f, FontWeight.SemiBold),
        labelMedium = text(16f, 22f, FontWeight.SemiBold),
        labelSmall = text(15f, 20f, FontWeight.Medium),
    )
}

@Composable
fun PrippiTheme(profile: DeviceProfile, content: @Composable () -> Unit) {
    val configuration = LocalConfiguration.current
    val dimensions = when (profile.formFactor) {
        FormFactor.PHONE -> PhoneDimensions
        FormFactor.TABLET -> TabletDimensions
        FormFactor.TELEVISION -> televisionDimensions(
            profile,
            configuration.screenWidthDp,
            configuration.screenHeightDp,
        )
    }
    val typography = when (profile.formFactor) {
        FormFactor.PHONE -> PhoneTypography
        FormFactor.TABLET -> TabletTypography
        FormFactor.TELEVISION -> televisionTypography(dimensions.uiScale)
    }
    androidx.compose.runtime.CompositionLocalProvider(
        LocalPrippiDimensions provides dimensions,
    ) {
        MaterialTheme(
            colorScheme = PrippiColorScheme,
            typography = typography,
            content = content,
        )
    }
}
