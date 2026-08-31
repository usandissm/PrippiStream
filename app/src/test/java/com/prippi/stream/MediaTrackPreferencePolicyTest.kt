package com.prippi.stream

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MediaTrackPreferencePolicyTest {
    @Test
    fun `all episodes and seasons of one series share one preference key`() {
        val first = episode(1, 8)
        val nextSeason = episode(2, 1)

        assertEquals(
            MediaTrackPreferencePolicy.keyFor(first),
            MediaTrackPreferencePolicy.keyFor(nextSeason),
        )
    }

    @Test
    fun `movies have independent preference keys and live has none`() {
        val first = movie("101")
        val second = movie("202")
        val live = ContentItem.fromJson(JSONObject().apply {
            put("title", "Rai 1")
            put("contentType", "live")
            put("_app_live", true)
            put("url", "https://example.test/live.m3u8")
        })

        assertTrue(MediaTrackPreferencePolicy.keyFor(first) != MediaTrackPreferencePolicy.keyFor(second))
        assertNull(MediaTrackPreferencePolicy.keyFor(live))
    }

    @Test
    fun `language alias label and role select the intended supported track`() {
        val selected = MediaTrackPreferencePolicy.bestMatch(
            TrackDescriptor(language = "ita-IT", label = "Italiano 5.1", roleFlags = 4),
            listOf(
                candidate(0, "en", "English 5.1", 4),
                candidate(1, "it", "Italiano", 0),
                candidate(2, "ita", "Italiano 5.1", 4),
                candidate(3, "it", "Italiano 5.1", 4, supported = false),
            ),
        )

        assertEquals(2, selected?.trackIndex)
    }

    @Test
    fun `missing language never falls back to an unrelated track`() {
        val selected = MediaTrackPreferencePolicy.bestMatch(
            TrackDescriptor(language = "ja", label = "Giapponese"),
            listOf(
                candidate(0, "it", "Italiano", 0),
                candidate(1, "en", "English", 0),
            ),
        )

        assertNull(selected)
    }

    @Test
    fun `label can identify an undetermined subtitle without using its list position`() {
        val selected = MediaTrackPreferencePolicy.bestMatch(
            TrackDescriptor(label = "Forced signs", roleFlags = 0),
            listOf(
                candidate(0, "", "Italiano", 0),
                candidate(1, "und", "Forced signs", 0),
            ),
        )

        assertEquals(1, selected?.trackIndex)
    }

    private fun candidate(
        index: Int,
        language: String,
        label: String,
        roleFlags: Int,
        supported: Boolean = true,
    ) = TrackCandidate(
        groupIndex = 0,
        trackIndex = index,
        descriptor = TrackDescriptor(language, label, roleFlags),
        supported = supported,
    )

    private fun movie(id: String): ContentItem = ContentItem.fromJson(JSONObject().apply {
        put("title", "Film $id")
        put("fulltitle", "Film $id")
        put("channel", "streamingcommunity")
        put("contentType", "movie")
        put("id", id)
    })

    private fun episode(season: Int, episode: Int): ContentItem {
        val parent = JSONObject().apply {
            put("title", "Serie Globale")
            put("fulltitle", "Serie Globale")
            put("channel", "streamingcommunity")
            put("contentType", "tvshow")
            put("action", "episodios")
            put("url", "https://example.test/titles/777-serie-globale")
            put("infoLabels", JSONObject().apply {
                put("tmdb_id", "777")
                put("mediatype", "tvshow")
            })
        }
        return ContentItem.fromJson(JSONObject().apply {
            put("title", "Episodio $episode")
            put("contentTitle", "Episodio $episode")
            put("channel", "streamingcommunity")
            put("contentType", "episode")
            put("contentSerieName", "Serie Globale")
            put("contentSeason", season)
            put("contentEpisodeNumber", episode)
            put("_app_series_parent", parent)
            put("infoLabels", JSONObject().apply {
                put("mediatype", "episode")
                put("season", season)
                put("episode", episode)
                put("tvshowtitle", "Serie Globale")
            })
        })
    }
}
