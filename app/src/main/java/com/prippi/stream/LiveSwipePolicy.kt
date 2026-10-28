package com.prippi.stream

import kotlin.math.abs

/** Touch-only Live zapping; vertical gestures and short drags remain untouched. */
internal object LiveSwipePolicy {
    fun channelDelta(dx: Float, dy: Float, velocityX: Float, density: Float): Int? {
        if (abs(dx) < 80f * density || abs(dx) < abs(dy) * 1.5f ||
            abs(velocityX) < 180f * density
        ) return null
        return if (dx < 0f) 1 else -1
    }
}
