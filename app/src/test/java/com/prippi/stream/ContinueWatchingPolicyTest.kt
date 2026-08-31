package com.prippi.stream

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ContinueWatchingPolicyTest {
    @Test
    fun `episodes from the same series share one canonical key`() {
        val first = episode(1, 2, "ep-12")
        val second = episode(2, 1, "ep-21")

        assertEquals(first.continueWatchingKey, second.continueWatchingKey)
        assertFalse(ContinueWatchingPolicy.sameEpisode(first.rawJson, second))
        assertTrue(ContinueWatchingPolicy.sameEpisode(second.rawJson, second))
    }

    @Test
    fun `series card and its episodes share the same canonical key`() {
        val currentEpisode = episode(2, 1, "ep-21")
        val parent = ContentItem.fromJson(currentEpisode.toJson().getJSONObject("_app_series_parent"))

        assertEquals(parent.continueWatchingKey, currentEpisode.continueWatchingKey)
    }

    @Test
    fun `migration keeps only the most recently updated episode of a series`() {
        val older = episode(1, 4, "14")
        val newer = episode(2, 1, "21")
        val migrated = ContinueWatchingPolicy.normalizeProgress(listOf(
            WatchProgress(older.stableKey, older.rawJson, 40_000, 100_000, 100),
            WatchProgress(newer.stableKey, newer.rawJson, 20_000, 100_000, 200),
        ))

        assertEquals(1, migrated.size)
        assertEquals(200, migrated.single().updatedAt)
        assertTrue(ContinueWatchingPolicy.sameEpisode(migrated.single().rawJson, newer))
    }

    @Test
    fun `different series with similarly numbered episodes stay separate`() {
        val first = episode(1, 1, "a", seriesId = "101", seriesTitle = "Serie A")
        val second = episode(1, 1, "b", seriesId = "202", seriesTitle = "Serie A")

        assertFalse(first.continueWatchingKey == second.continueWatchingKey)
    }

    @Test
    fun `movie identity is unchanged`() {
        val movie = ContentItem.fromJson(JSONObject().apply {
            put("title", "Film")
            put("fulltitle", "Film")
            put("action", "findvideos")
            put("channel", "streamingcommunity")
            put("contentType", "movie")
            put("id", "42")
        })

        assertEquals(movie.stableKey, movie.continueWatchingKey)
    }

    @Test
    fun `queue crosses from last episode of one season to first of next`() {
        val shuffled = listOf(
            episode(2, 2, "22"),
            episode(1, 2, "12"),
            episode(2, 1, "21"),
            episode(1, 1, "11"),
        )
        val ordered = EpisodeFlowPolicy.ordered(shuffled)
        val lastSeasonOne = ordered.indexOfFirst { it.season == 1 && it.episode == 2 }
        val next = EpisodeFlowPolicy.nextIndex(lastSeasonOne, ordered.size)

        assertEquals(listOf(1 to 1, 1 to 2, 2 to 1, 2 to 2), ordered.map { it.season to it.episode })
        assertEquals(2 to 1, ordered[next!!].season to ordered[next].episode)
        assertNull(EpisodeFlowPolicy.nextIndex(ordered.lastIndex, ordered.size))
    }

    @Test
    fun `queue lookup survives equivalent reserialization`() {
        val items = EpisodeFlowPolicy.ordered(listOf(episode(1, 1, "11"), episode(1, 2, "12")))
        val reserialized = ContentItem.fromJson(JSONObject(items[1].rawJson).put("transient", true))

        assertEquals(1, EpisodeFlowPolicy.indexOf(items, reserialized))
    }

    @Test
    fun `new series card starts from first ordered episode`() {
        val second = episode(1, 2, "12")
        val first = episode(1, 1, "11")
        val parent = ContentItem.fromJson(first.toJson().getJSONObject("_app_series_parent"))

        val selected = EpisodeFlowPolicy.playbackItem(
            requested = parent,
            resume = false,
            saved = second,
            orderedEpisodes = EpisodeFlowPolicy.ordered(listOf(second, first)),
        )

        assertEquals(1, selected.episode)
    }

    @Test
    fun `series resume uses saved episode including zero-position CW marker`() {
        val first = episode(1, 1, "11")
        val saved = episode(2, 1, "21")
        val parent = ContentItem.fromJson(first.toJson().getJSONObject("_app_series_parent"))

        val selected = EpisodeFlowPolicy.playbackItem(
            requested = parent,
            resume = true,
            saved = saved,
            orderedEpisodes = EpisodeFlowPolicy.ordered(listOf(first, saved)),
        )

        assertEquals(2 to 1, selected.season to selected.episode)
    }

    @Test
    fun `explicit episode selection is never replaced by series CW`() {
        val requested = episode(1, 1, "11")
        val saved = episode(2, 1, "21")

        val selected = EpisodeFlowPolicy.playbackItem(
            requested = requested,
            resume = true,
            saved = saved,
            orderedEpisodes = EpisodeFlowPolicy.ordered(listOf(requested, saved)),
        )

        assertEquals(1 to 1, selected.season to selected.episode)
    }

    private fun episode(
        season: Int,
        episode: Int,
        id: String,
        seriesId: String = "900",
        seriesTitle: String = "La Serie",
    ): ContentItem {
        val parent = JSONObject().apply {
            put("title", seriesTitle)
            put("fulltitle", seriesTitle)
            put("action", "episodios")
            put("channel", "streamingcommunity")
            put("contentType", "tvshow")
            put("url", "https://example.test/titles/$seriesId-la-serie")
            put("infoLabels", JSONObject().put("tmdb_id", seriesId).put("mediatype", "tvshow"))
        }
        return ContentItem.fromJson(JSONObject().apply {
            put("title", "Episodio $episode")
            put("contentTitle", "Episodio $episode")
            put("action", "findvideos")
            put("channel", "streamingcommunity")
            put("contentType", "episode")
            put("contentSerieName", seriesTitle)
            put("contentSeason", season)
            put("contentEpisodeNumber", episode)
            put("url", "https://example.test/watch/$id")
            put("_app_series_parent", parent)
            put("infoLabels", JSONObject().apply {
                put("mediatype", "episode")
                put("season", season)
                put("episode", episode)
                put("tvshowtitle", seriesTitle)
            })
        })
    }
}
