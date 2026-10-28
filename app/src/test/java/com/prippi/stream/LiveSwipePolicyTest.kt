package com.prippi.stream

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LiveSwipePolicyTest {
    @Test fun leftMeansNext() = assertEquals(1, LiveSwipePolicy.channelDelta(-160f, 10f, -600f, 1f))
    @Test fun rightMeansPrevious() = assertEquals(-1, LiveSwipePolicy.channelDelta(160f, 10f, 600f, 1f))
    @Test fun verticalIgnored() = assertNull(LiveSwipePolicy.channelDelta(90f, 200f, 600f, 1f))
    @Test fun smallDragIgnored() = assertNull(LiveSwipePolicy.channelDelta(25f, 2f, 600f, 1f))
    @Test fun densityApplied() = assertNull(LiveSwipePolicy.channelDelta(120f, 2f, 600f, 2f))
    @Test fun slowDragIgnored() = assertNull(LiveSwipePolicy.channelDelta(180f, 2f, 20f, 1f))
}
