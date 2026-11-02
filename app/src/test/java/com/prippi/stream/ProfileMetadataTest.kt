package com.prippi.stream

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ProfileMetadataTest {
    private fun importedEpisode(episode: Int): ContentItem = ContentItem.fromJson(JSONObject().apply {
        put("channel", "streamingcommunity"); put("action", "findvideos")
        put("title", "Puntata $episode"); put("contentType", "episode")
        put("contentSerieName", "Serie sintetica"); put("url", "https://example.com/episode/$episode")
        put("_profile_id", "series:tmdb:100")
        put("infoLabels", JSONObject().put("tmdb_id", "100").put("mediatype", "episode")
            .put("tvshowtitle", "Serie sintetica").put("season", 2).put("episode", episode))
        put("_app_series_parent", JSONObject().put("channel", "streamingcommunity")
            .put("title", "Serie sintetica").put("contentType", "tvshow")
            .put("infoLabels", JSONObject().put("tmdb_id", "100").put("mediatype", "tvshow")))
    })

    @Test fun `Kodi metadata imports into one series key across episodes`() {
        val first = importedEpisode(1); val next = importedEpisode(2)
        assertTrue(first.isEpisode)
        assertEquals(first.continueWatchingKey, next.continueWatchingKey)
        assertEquals("Serie sintetica", first.continueWatchingTitle)
        assertEquals(2, first.season)
        assertEquals("series:tmdb:100", JSONObject(ContinueWatchingPolicy.cleanMetadata(first.rawJson)).getString("_profile_id"))
        assertFalse(ContinueWatchingPolicy.sameEpisode(first.rawJson, next))
    }

    @Test fun `remote CW can supply offline resume without changing the download file`() {
        val current = importedEpisode(2)
        val progress = WatchProgress(current.continueWatchingKey, current.rawJson, 42000, 100000, 2000)
        val bookmark = JSONObject().put("position", 12000).put("duration", 100000).put("updated", 1000)
        assertEquals(42000L, OfflinePlaybackPolicy.resumePosition(bookmark, progress, true))
        assertEquals(0L, OfflinePlaybackPolicy.resumePosition(bookmark, progress, false))
    }
}
