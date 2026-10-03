package com.prippi.stream

import org.json.JSONObject
import java.util.Locale

data class DownloadEntry(
    val key: String,
    val title: String,
    val showTitle: String,
    val thumbnail: String,
    val status: String,
    val progress: Float,
    val quality: String,
    val error: String,
    val showKey: String,
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
            showKey = json.optString("show_key"),
            season = json.optInt("season"),
            episode = json.optInt("episode"),
            totalBytes = json.optLong("total_bytes"),
        )
    }
}

/** Keep each series' episodes together and in playback order, without
 * disturbing the position of movies or of other series in the download list.
 */
internal object DownloadOrdering {
    fun episodesChronologically(entries: List<DownloadEntry>): List<DownloadEntry> {
        if (entries.size < 2) return entries

        val groups = linkedMapOf<String, MutableList<IndexedValue<DownloadEntry>>>()
        entries.forEachIndexed { index, entry ->
            val seriesIdentity = entry.showKey.trim().ifBlank {
                entry.showTitle.trim().lowercase(Locale.ROOT)
            }
            val isEpisode = entry.episode > 0 && seriesIdentity.isNotBlank()
            val groupKey = if (isEpisode) "series:$seriesIdentity" else "item:$index"
            groups.getOrPut(groupKey) { mutableListOf() }
                .add(IndexedValue(index, entry))
        }

        return groups.values
            .sortedBy { group -> group.first().index }
            .flatMap { group ->
                if (group.size > 1 && group.first().value.episode > 0) {
                    group.sortedWith(
                        compareBy<IndexedValue<DownloadEntry>>(
                            { it.value.season },
                            { it.value.episode },
                            { it.index },
                        ),
                    ).map { it.value }
                } else {
                    group.map { it.value }
                }
            }
    }
}
