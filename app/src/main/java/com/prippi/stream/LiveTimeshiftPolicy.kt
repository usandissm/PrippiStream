package com.prippi.stream

/** Positions are relative to the moving manifest window, not a local recording. */
internal object LiveTimeshiftPolicy {
    const val MAX_REWIND_MS = 2 * 60 * 60 * 1000L
    const val LIVE_TOLERANCE_MS = 10_000L

    fun available(enabled: Boolean, channel: Boolean, event: Boolean,
                  seekable: Boolean, duration: Long): Boolean =
        enabled && channel && !event && seekable && duration > 0

    fun start(duration: Long): Long = (duration - MAX_REWIND_MS).coerceAtLeast(0)
    fun length(duration: Long): Long = duration.coerceIn(0, MAX_REWIND_MS)
    fun target(progress: Int, max: Int, duration: Long): Long =
        start(duration) + length(duration) * progress.coerceIn(0, max.coerceAtLeast(1)) / max.coerceAtLeast(1)
    fun behind(position: Long, duration: Long): Long = (duration - position).coerceAtLeast(0)
}
