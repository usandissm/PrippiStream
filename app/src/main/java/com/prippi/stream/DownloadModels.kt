package com.prippi.stream

import org.json.JSONObject

data class DownloadEntry(
    val key: String,
    val title: String,
    val showTitle: String,
    val thumbnail: String,
    val status: String,
    val progress: Float,
    val quality: String,
    val error: String,
    val season: Int,
    val episode: Int,
    val totalBytes: Long,
) {
    val displayTitle: String
        get() = if (showTitle.isNotBlank() && episode > 0) {
            "$showTitle · S${season.toString().padStart(2, '0')}E${episode.toString().padStart(2, '0')} · $title"
        } else title

    val isComplete: Boolean get() = status == "done"
    val isActive: Boolean get() = status in setOf("queued", "downloading", "waiting_network")
    val canResume: Boolean get() = status in setOf("paused", "error")

    companion object {
        fun fromJson(json: JSONObject) = DownloadEntry(
            key = json.optString("key"),
            title = cleanKodiText(json.optString("title")),
            showTitle = cleanKodiText(json.optString("show_title")),
            thumbnail = json.optString("thumbnail"),
            status = json.optString("status", "queued"),
            progress = json.optDouble("progress", 0.0).toFloat().coerceIn(0f, 100f),
            quality = json.optString("quality"),
            error = json.optString("error"),
            season = json.optInt("season"),
            episode = json.optInt("episode"),
            totalBytes = json.optLong("total_bytes"),
        )
    }
}
