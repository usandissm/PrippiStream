package com.prippi.stream

import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Pure layout rules shared by the player view and its unit tests. */
internal object PlayerLayoutPolicy {
    private const val REFERENCE_WIDTH_DP = 1280f
    private const val REFERENCE_HEIGHT_DP = 720f
    private const val MIN_UI_SCALE = 0.68f
    private const val MAX_UI_SCALE = 1.28f
    private const val HEADER_CONTENT_FRACTION = 0.58f

    /**
     * PlayerActivity is landscape-only, but its first onCreate can still observe the
     * portrait configuration while Android is rotating the window. Normalising the
     * axes makes the first-frame scale identical to the settled landscape scale.
     */
    fun landscapeUiScale(screenWidthDp: Int, screenHeightDp: Int): Float {
        val width = max(screenWidthDp, screenHeightDp).coerceAtLeast(1)
        val height = min(screenWidthDp, screenHeightDp).coerceAtLeast(1)
        return min(width / REFERENCE_WIDTH_DP, height / REFERENCE_HEIGHT_DP)
            .coerceIn(MIN_UI_SCALE, MAX_UI_SCALE)
    }

    /** Width of the centred title/metadata block, resolved from the measured header. */
    fun headerContentWidth(headerWidthPx: Int): Int =
        (headerWidthPx.coerceAtLeast(1) * HEADER_CONTENT_FRACTION)
            .roundToInt()
            .coerceAtLeast(1)
}
