package com.prippi.stream

/** A profile must not change underneath a playing/PiP activity. */
internal object ProfilePlaybackGuard {
    val players = java.util.concurrent.atomic.AtomicInteger(0)
}
