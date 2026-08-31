package com.prippi.stream

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HomeSnapshotStoreTest {
    private val now = 1_800_000_000_000L

    private fun item(title: String = "Titolo") = ContentItem(
        title = title,
        subtitle = "",
        posterUrl = "",
        backdropUrl = "",
        action = "findvideos",
        channel = "streamingcommunity",
        source = "",
        searchType = "",
        rawJson = JSONObject().apply {
            put("title", title)
            put("channel", "streamingcommunity")
            put("action", "findvideos")
            put("url", "https://example.invalid/$title")
        }.toString(),
        mediaType = "movie",
        tmdbId = "",
        plot = "",
        year = 0,
        genres = "",
        rating = 0.0,
        season = 0,
        episode = 0,
    )

    @Test
    fun roundTripPreservesRowsWithoutContinueWatching() {
        val item = item()
        val blob = HomeSnapshotStore.encode(
            listOf(
                HomeRow("continue_watching", "Continua", listOf(item)),
                HomeRow("trending", "Trending", listOf(item)),
            ),
            now,
        )

        val rows = HomeSnapshotStore.decode(requireNotNull(blob), now + 1_000)

        assertEquals(1, rows.size)
        assertEquals("trending", rows.single().id)
        assertEquals("Titolo", rows.single().items.single().title)
    }

    @Test
    fun expiredSnapshotIsRejected() {
        val blob = """{"version":1,"saved_at_ms":1,"rows":[]}"""
        assertTrue(HomeSnapshotStore.decode(blob, now).isEmpty())
    }

    @Test
    fun emptyRowsAreNotSerialized() {
        assertNull(HomeSnapshotStore.encode(emptyList(), now))
    }

    @Test
    fun snapshotIsBoundedForFastFirstPaint() {
        val rows = (0 until 8).map { row ->
            HomeRow(
                id = "row_$row",
                title = "Riga $row",
                items = (0 until 20).map { item("$row-$it") },
            )
        }

        val decoded = HomeSnapshotStore.decode(
            requireNotNull(HomeSnapshotStore.encode(rows, now)),
            now,
        )

        assertEquals(6, decoded.size)
        assertTrue(decoded.all { it.items.size == 12 })
    }
}
