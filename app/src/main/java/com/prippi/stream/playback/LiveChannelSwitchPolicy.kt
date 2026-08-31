package com.prippi.stream.playback

internal object LiveChannelSwitchPolicy {
    fun candidateIndices(
        currentIndex: Int,
        total: Int,
        delta: Int,
        maxAttempts: Int,
    ): List<Int> {
        if (currentIndex !in 0 until total || total < 2 || delta == 0 || maxAttempts <= 0) {
            return emptyList()
        }
        return (1..minOf(total - 1, maxAttempts)).map { step ->
            Math.floorMod(currentIndex + delta * step, total)
        }
    }

    fun acceptsInput(nowMs: Long, previousMs: Long, debounceMs: Long): Boolean =
        previousMs <= 0L || nowMs - previousMs >= debounceMs
}
