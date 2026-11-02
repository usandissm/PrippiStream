package com.prippi.stream

import android.content.Context
import org.json.JSONObject

internal object OfflinePlaybackPolicy {
    fun content(entry: DownloadEntry): ContentItem? = runCatching {
        ContentItem.fromJson(JSONObject(entry.contentJson))
    }.getOrNull()

    fun find(item: ContentItem, entries: List<DownloadEntry>): DownloadEntry? =
        entries.firstOrNull { entry ->
            entry.isComplete && content(entry)?.let { candidate ->
                candidate.continueWatchingKey == item.continueWatchingKey &&
                    (!item.isEpisode || ContinueWatchingPolicy.sameEpisode(candidate.rawJson, item))
            } == true
        }

    fun playerTitle(item: ContentItem): String = listOf(
        item.continueWatchingTitle, item.continueWatchingSubtitle,
    ).filter(String::isNotBlank).joinToString(" · ")

    fun resumePosition(bookmark: JSONObject?, shared: WatchProgress?, resume: Boolean): Long {
        if (!resume) return 0L
        if (shared != null && !ContinueWatchingPolicy.isCompleted(shared.positionMs, shared.durationMs) &&
            shared.updatedAt > (bookmark?.optLong("updated") ?: 0L)) return shared.positionMs
        val position = bookmark?.optLong("position") ?: 0L
        return if (ContinueWatchingPolicy.isCompleted(position, bookmark?.optLong("duration") ?: 0L)) 0L else position
    }
}

/** A per-file bookmark, independent of the single series-level CW entry. */
internal class OfflineWatchStore(context: Context, profile: String = "") {
    private val prefs = context.applicationContext.getSharedPreferences("offline_watch" +
        if (profile.isBlank()) "" else "_" + java.security.MessageDigest.getInstance("SHA-256")
            .digest(profile.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }, Context.MODE_PRIVATE)
    fun find(key: String): JSONObject? = runCatching {
        JSONObject(prefs.getString(key, "").orEmpty())
    }.getOrNull()

    fun save(key: String, position: Long, duration: Long, synchronous: Boolean) {
        if (key.isBlank()) return
        val record = JSONObject().put("position", position.coerceAtLeast(0))
            .put("duration", duration).put("updated", System.currentTimeMillis())
        val editor = prefs.edit().putString(key, record.toString())
        if (synchronous) editor.commit() else editor.apply()
    }
}
