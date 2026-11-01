package com.prippi.stream

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class OfflinePlaybackPolicyTest {
    private fun episode(number: Int, show: String = "100") = ContentItem.fromJson(JSONObject().apply {
        put("title", "Puntata $number")
        put("contentType", "episode")
        put("contentSeason", 1)
        put("contentEpisodeNumber", number)
        put("contentSerieName", "La serie")
        put("channel", "streamingcommunity")
        put("id", "episode-$number")
        put("_app_series_parent", JSONObject().put("title", "La serie").put("contentType", "tvshow")
            .put("channel", "streamingcommunity").put("id", show))
    })
    private fun entry(item: ContentItem, status: String = "done") = DownloadEntry.fromJson(JSONObject()
        .put("key", "download").put("status", status).put("content_item", item.toJson()))

    @Test fun downloadAndOnlineEpisodeShareCWIdentity() {
        val online = episode(2)
        val offline = OfflinePlaybackPolicy.content(entry(online))!!
        assertEquals(online.continueWatchingKey, offline.continueWatchingKey)
        assertNotNull(OfflinePlaybackPolicy.find(online, listOf(entry(online))))
    }
    @Test fun incompleteDifferentEpisodeOrDifferentSeriesDoesNotShowOfflineBadge() {
        assertNull(OfflinePlaybackPolicy.find(episode(2), listOf(entry(episode(1)))))
        assertNull(OfflinePlaybackPolicy.find(episode(2), listOf(entry(episode(2, "200")))))
        assertNull(OfflinePlaybackPolicy.find(episode(2), listOf(entry(episode(2), "downloading"))))
    }
    @Test fun playerTitleContainsSeriesAndEpisode() {
        val title = OfflinePlaybackPolicy.playerTitle(episode(2))
        assertTrue(title.contains("La serie"))
        assertTrue(title.contains("S01E02"))
        assertTrue(title.contains("Puntata 2"))
    }
    @Test fun cwDoesNotPersistLocalTransportOrMediaCredentials() {
        val raw = episode(1).toJson().put("_app_offline_download_key", "private-local-key")
            .put("_app_media_url", "https://example.invalid/signed")
            .put("_app_media_headers", JSONObject().put("Cookie", "secret"))
            .put("_app_offline_completed", true)
        val cleaned = JSONObject(ContinueWatchingPolicy.cleanMetadata(raw.toString()))
        assertFalse(cleaned.has("_app_media_url"))
        assertFalse(cleaned.has("_app_media_headers"))
        assertFalse(cleaned.has("_app_offline_download_key"))
        assertTrue(cleaned.getBoolean("_app_offline_completed"))
        assertEquals(episode(1).continueWatchingKey, ContentItem.fromJson(cleaned).continueWatchingKey)
    }
    @Test fun latestOnlineOrOfflinePositionWinsForTheSameEpisode() {
        val bookmark = JSONObject().put("position", 40_000).put("duration", 100_000).put("updated", 200)
        val olderCW = WatchProgress("key", episode(1).rawJson, 20_000, 100_000, 100)
        assertEquals(40_000L, OfflinePlaybackPolicy.resumePosition(bookmark, olderCW, true))
        assertEquals(60_000L, OfflinePlaybackPolicy.resumePosition(bookmark, olderCW.copy(positionMs=60_000, updatedAt=300), true))
        assertEquals(0L, OfflinePlaybackPolicy.resumePosition(bookmark, olderCW, false))
    }
    @Test fun completedFileCanBeReplayedFromStartWithoutChangingTheSeriesIdentity() {
        val bookmark = JSONObject().put("position", 98_000).put("duration", 100_000).put("updated", 200)
        assertEquals(0L, OfflinePlaybackPolicy.resumePosition(bookmark, null, true))
    }
}
