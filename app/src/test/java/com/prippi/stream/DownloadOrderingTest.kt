package com.prippi.stream

import org.junit.Assert.assertEquals
import org.junit.Test

class DownloadOrderingTest {
    @Test
    fun `episodes of a series are grouped and ordered by season then episode`() {
        val input = listOf(
            episode("serie-a-s2e1", "serie-a", "Serie A", 2, 1),
            movie("film"),
            episode("serie-b-s1e1", "serie-b", "Serie B", 1, 1),
            episode("serie-a-s1e2", "serie-a", "Serie A", 1, 2),
            episode("serie-a-s1e1", "serie-a", "Serie A", 1, 1),
        )

        val ordered = DownloadOrdering.episodesChronologically(input)

        assertEquals(
            listOf(
                "serie-a-s1e1",
                "serie-a-s1e2",
                "serie-a-s2e1",
                "film",
                "serie-b-s1e1",
            ),
            ordered.map { it.key },
        )
    }

    @Test
    fun `same display title with different series keys stays separate`() {
        val input = listOf(
            episode("a-s2e1", "show-1", "Same title", 2, 1),
            episode("b-s1e1", "show-2", "Same title", 1, 1),
            episode("a-s1e1", "show-1", "Same title", 1, 1),
        )

        assertEquals(
            listOf("a-s1e1", "a-s2e1", "b-s1e1"),
            DownloadOrdering.episodesChronologically(input).map { it.key },
        )
    }

    private fun episode(
        key: String,
        showKey: String,
        showTitle: String,
        season: Int,
        episode: Int,
    ) = DownloadEntry(
        key = key,
        title = "Episode $episode",
        showTitle = showTitle,
        thumbnail = "",
        status = "done",
        progress = 100f,
        quality = "",
        error = "",
        showKey = showKey,
        season = season,
        episode = episode,
        totalBytes = 0,
    )

    private fun movie(key: String) = DownloadEntry(
        key = key,
        title = key,
        showTitle = "",
        thumbnail = "",
        status = "done",
        progress = 100f,
        quality = "",
        error = "",
        showKey = "",
        season = 0,
        episode = 0,
        totalBytes = 0,
    )
}
