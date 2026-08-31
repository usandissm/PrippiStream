package com.prippi.stream

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.ImageView

/**
 * Lightweight brand mark shared by fullscreen players.
 *
 * It is deliberately a plain ImageView: no Compose/WebView allocation, no
 * focus target and no animation on low-power boxes.
 */
internal fun addPersistentBrandOverlay(
    root: FrameLayout,
    television: Boolean,
) {
    val context = root.context
    val width = context.dp(if (television) 340 else 154)
    val height = context.dp(if (television) 84 else 42)
    val margin = context.dp(if (television) 34 else 12)
    root.addView(
        ImageView(context).apply {
            setImageResource(R.drawable.prippistream_logo_banner)
            scaleType = ImageView.ScaleType.FIT_CENTER
            isFocusable = false
            isClickable = false
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            if (television) {
                setPadding(0, 0, 0, 0)
                background = null
            } else {
                setPadding(context.dp(8), context.dp(4), context.dp(8), context.dp(4))
                background = GradientDrawable().apply {
                    cornerRadius = context.dp(10).toFloat()
                    setColor(Color.argb(142, 3, 8, 13))
                }
            }
        },
        FrameLayout.LayoutParams(width, height, Gravity.TOP or Gravity.END).apply {
            topMargin = margin
            marginEnd = margin
        },
    )
}

private fun Context.dp(value: Int): Int =
    (value * resources.displayMetrics.density).toInt()
