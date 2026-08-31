package com.prippi.stream

import org.json.JSONObject
import java.text.Normalizer
import java.util.Locale

/** One CW identity per movie or series, independently from the current episode. */
internal object ContinueWatchingPolicy {
    fun keyFor(item: ContentItem): String = keyFor(item.stableKey, item.rawJson)

    fun keyFor(fallbackKey: String, rawJson: String): String {
        val raw = runCatching { JSONObject(rawJson) }.getOrNull() ?: return fallbackKey
        val item = runCatching { ContentItem.fromJson(raw) }.getOrNull() ?: return fallbackKey
        val channel = item.channel.trim().lowercase(Locale.ROOT).ifBlank { "unknown" }
        if (item.isSeries && !item.isEpisode) {
            return seriesIdentity(raw, channel)?.let { "cw:series:$channel:$it" }
                ?: item.stableKey
        }
        if (!item.isEpisode) return item.stableKey

        raw.optJSONObject("_app_series_parent")?.let { parent ->
            seriesIdentity(parent, channel)?.let { return "cw:series:$channel:$it" }
        }

        val info = raw.optJSONObject("infoLabels") ?: JSONObject()
        firstValue(
            raw,
            info,
            "_app_series_tmdb_id",
            "series_tmdb_id",
            "tvshow_tmdb_id",
            "tmdb_tv_id",
        )?.let { return "cw:series:$channel:tmdb:$it" }
        seriesTitle(raw, info)?.let { return "cw:series:$channel:title:${normalize(it)}" }

        // Last-resort compatibility for old providers which omitted show data.
        return fallbackKey.replace(Regex(":s\\d+:e\\d+$"), "").ifBlank { fallbackKey }
    }

    fun sameEpisode(savedRawJson: String, candidate: ContentItem): Boolean {
        if (!candidate.isEpisode) return true
        val saved = runCatching { ContentItem.fromJson(JSONObject(savedRawJson)) }.getOrNull()
            ?: return false
        if (!saved.isEpisode || keyFor(saved) != keyFor(candidate)) return false
        if (saved.season > 0 && saved.episode > 0 && candidate.season > 0 && candidate.episode > 0) {
            return saved.season == candidate.season && saved.episode == candidate.episode
        }
        val savedUrl = saved.toJson().optString("url")
        val candidateUrl = candidate.toJson().optString("url")
        return savedUrl.isNotBlank() && savedUrl == candidateUrl
    }

    fun normalizeProgress(entries: Collection<WatchProgress>): List<WatchProgress> {
        val normalized = linkedMapOf<String, WatchProgress>()
        entries.forEach { entry ->
            val raw = runCatching { JSONObject(entry.rawJson) }.getOrNull() ?: return@forEach
            if (raw.optBoolean("_app_live")) return@forEach
            val canonicalKey = keyFor(entry.key, entry.rawJson)
            val candidate = entry.copy(key = canonicalKey)
            val previous = normalized[canonicalKey]
            if (previous == null || candidate.updatedAt > previous.updatedAt) {
                normalized[canonicalKey] = candidate
            }
        }
        return normalized.values.sortedByDescending(WatchProgress::updatedAt)
    }

    private fun seriesIdentity(raw: JSONObject, defaultChannel: String): String? {
        val info = raw.optJSONObject("infoLabels") ?: JSONObject()
        firstValue(raw, info, "tmdb_id", "tmdb", "_app_series_tmdb_id")
            ?.let { return "tmdb:$it" }
        firstValue(raw, info, "id", "contentId", "slug")
            ?.let { return "provider:$it" }
        Regex("/titles/(\\d+)(?:[-/]|$)")
            .find(raw.optString("url"))?.groupValues?.getOrNull(1)
            ?.let { return "provider:$it" }
        seriesTitle(raw, info)?.let { return "title:${normalize(it)}" }
        return runCatching { ContentItem.fromJson(raw, defaultChannel) }.getOrNull()
            ?.title?.takeIf(String::isNotBlank)?.let { "title:${normalize(it)}" }
    }

    private fun seriesTitle(raw: JSONObject, info: JSONObject): String? = sequenceOf(
        info.optString("tvshowtitle"),
        info.optString("showtitle"),
        raw.optString("contentSerieName"),
        raw.optString("serieName"),
        raw.optString("showTitle"),
    ).map(String::trim).firstOrNull(String::isNotBlank)

    private fun firstValue(raw: JSONObject, info: JSONObject, vararg keys: String): String? {
        for (key in keys) {
            sequenceOf(raw.optString(key), info.optString(key))
                .map(String::trim).firstOrNull(String::isNotBlank)
                ?.let { return normalizeIdentifier(it) }
        }
        return null
    }

    private fun normalizeIdentifier(value: String): String =
        value.lowercase(Locale.ROOT).replace(Regex("[^a-z0-9._-]+"), "-").trim('-')

    private fun normalize(value: String): String = Normalizer
        .normalize(cleanKodiText(value), Normalizer.Form.NFD)
        .replace(Regex("\\p{M}+"), "")
        .lowercase(Locale.ROOT)
        .replace(Regex("[^a-z0-9]+"), "-")
        .trim('-')
}

/** Deterministic all-season queue used by detail and player transitions. */
internal object EpisodeFlowPolicy {
    fun ordered(items: List<ContentItem>): List<ContentItem> = items
        .withIndex()
        .sortedWith(compareBy<IndexedValue<ContentItem>>(
            { it.value.season.takeIf { value -> value > 0 } ?: Int.MAX_VALUE },
            { it.value.episode.takeIf { value -> value > 0 } ?: Int.MAX_VALUE },
            { it.index },
        ))
        .map(IndexedValue<ContentItem>::value)
        .distinctBy { item ->
            if (item.season > 0 && item.episode > 0) {
                "${ContinueWatchingPolicy.keyFor(item)}:${item.season}:${item.episode}"
            } else item.stableKey
        }

    fun indexOf(items: List<ContentItem>, current: ContentItem): Int {
        val exact = items.indexOfFirst { it.rawJson == current.rawJson }
        if (exact >= 0) return exact
        return items.indexOfFirst { candidate ->
            candidate.stableKey == current.stableKey ||
                (candidate.season > 0 && candidate.episode > 0 &&
                    candidate.season == current.season && candidate.episode == current.episode &&
                    ContinueWatchingPolicy.keyFor(candidate) == ContinueWatchingPolicy.keyFor(current))
        }
    }

    fun nextIndex(currentIndex: Int, size: Int): Int? =
        (currentIndex + 1).takeIf { currentIndex >= 0 && it < size }

    /**
     * A series card is only a container: playback always targets an episode.
     * Resume selects the CW episode, while an explicit episode selection is
     * never replaced by the series-level progress.
     */
    fun playbackItem(
        requested: ContentItem,
        resume: Boolean,
        saved: ContentItem?,
        orderedEpisodes: List<ContentItem>,
    ): ContentItem = when {
        requested.isSeries && !requested.isEpisode && resume && saved?.isEpisode == true -> saved
        requested.isSeries && !requested.isEpisode -> orderedEpisodes.firstOrNull() ?: requested
        else -> requested
    }
}
