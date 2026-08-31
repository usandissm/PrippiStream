package com.prippi.stream

import android.text.Html
import org.json.JSONArray
import org.json.JSONObject

private val kodiMarkup = Regex("\\[/?(?:B|I|COLOR[^\\]]*)\\]", RegexOption.IGNORE_CASE)

private fun JSONObject.ratingValue(vararg keys: String): Double {
    for (key in keys) {
        val value = opt(key)
        val parsed = when (value) {
            is Number -> value.toDouble()
            is String -> value.replace(',', '.').trim().toDoubleOrNull()
            else -> null
        }
        if (parsed != null && parsed > 0.0) return parsed
    }
    return 0.0
}

private fun JSONObject.cleanTextValue(vararg keys: String): String {
    for (key in keys) {
        val value = opt(key)
        val text = when (value) {
            is JSONArray -> (0 until value.length())
                .mapNotNull { index ->
                    when (val entry = value.opt(index)) {
                        is JSONObject -> entry.optString("name")
                            .ifBlank { entry.optString("title") }
                            .ifBlank { entry.optString("iso_3166_1") }
                        null, JSONObject.NULL -> ""
                        else -> entry.toString()
                    }.takeIf(String::isNotBlank)
                }
                .joinToString(", ")
            is JSONObject -> value.keys().asSequence()
                .mapNotNull { childKey ->
                    value.optString(childKey).takeIf(String::isNotBlank)
                }
                .joinToString(", ")
            null, JSONObject.NULL -> ""
            else -> value.toString()
        }
        cleanKodiText(text).takeIf(String::isNotBlank)?.let { return it }
    }
    return ""
}

private fun JSONObject.runtimeMinutes(): Int {
    val raw = opt("runtime") ?: return 0
    if (raw is Number) return raw.toInt().coerceAtLeast(0)
    val text = raw.toString().trim()
    text.toIntOrNull()?.let { return it.coerceAtLeast(0) }
    Regex("(\\d+)\\s*(?:min|m)", RegexOption.IGNORE_CASE)
        .find(text)?.groupValues?.getOrNull(1)?.toIntOrNull()?.let { return it }
    val parts = text.split(':').mapNotNull(String::toIntOrNull)
    return when (parts.size) {
        2 -> parts[0] * 60 + parts[1]
        3 -> parts[0] * 60 + parts[1] + if (parts[2] >= 30) 1 else 0
        else -> 0
    }
}

fun cleanKodiText(value: String?): String {
    val stripped = value.orEmpty().replace(kodiMarkup, "").trim()
    return runCatching {
        Html.fromHtml(stripped, Html.FROM_HTML_MODE_LEGACY).toString().trim()
    }.getOrElse {
        // Mantiene modelli/snapshot leggibili anche in ambienti JVM headless;
        // Android continua a usare il parser HTML completo.
        stripped
            .replace("&amp;", "&")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .trim()
    }
}

data class ContentItem(
    val title: String,
    val subtitle: String,
    val posterUrl: String,
    val backdropUrl: String,
    val action: String,
    val channel: String,
    val source: String,
    val searchType: String,
    val rawJson: String,
    val mediaType: String,
    val tmdbId: String,
    val plot: String,
    val year: Int,
    val genres: String,
    val rating: Double,
    val season: Int,
    val episode: Int,
    val runtimeMinutes: Int = 0,
    val certification: String = "",
    val premiered: String = "",
    val country: String = "",
    val studio: String = "",
    val director: String = "",
    val cast: String = "",
    val isLive: Boolean = false,
    val progressMs: Long = 0,
    val durationMs: Long = 0,
) {
    val opensEpisodes: Boolean
        get() = action in setOf("episodios", "epmenu", "epMenu", "seasons", "get_seasons")

    fun toJson(): JSONObject = JSONObject(rawJson)

    val isSeries: Boolean
        get() = mediaType in setOf("tvshow", "season", "serie") || opensEpisodes

    val isEpisode: Boolean
        get() = mediaType == "episode" || episode > 0

    val stableKey: String
        get() {
            if (isLive) {
                val payload = toJson()
                val kind = payload.optString("sport_kind")
                    .ifBlank { payload.optString("_app_live_provider") }
                    .ifBlank { channel }
                val id = payload.optString("sport_par")
                    .ifBlank { payload.optString("url") }
                    .ifBlank { title }
                return "live:$kind:$id"
            }
            val payload = toJson()
            val id = tmdbId.ifBlank {
                payload.optString("id")
                    .ifBlank { payload.optString("contentId") }
                    .ifBlank { payload.optString("slug") }
                    .ifBlank {
                        listOf(
                            title.trim().lowercase(),
                            year.takeIf { it > 0 }?.toString().orEmpty(),
                            source,
                            action,
                        ).joinToString("|")
                    }
            }
            return buildString {
                append(channel).append(':').append(mediaType.ifBlank { "video" }).append(':').append(id)
                if (season > 0) append(":s").append(season)
                if (episode > 0) append(":e").append(episode)
            }
        }

    val progressFraction: Float
        get() = if (durationMs > 0) (progressMs.toFloat() / durationMs).coerceIn(0f, 1f) else 0f

    val continueWatchingKey: String
        get() = ContinueWatchingPolicy.keyFor(this)

    fun withProgress(positionMs: Long, totalMs: Long): ContentItem =
        copy(progressMs = positionMs, durationMs = totalMs)

    companion object {
        fun fromJson(json: JSONObject, defaultChannel: String = "streamingcommunity"): ContentItem {
            val info = json.optJSONObject("infoLabels") ?: JSONObject()
            val mediaType = info.optString("mediatype").ifBlank { json.optString("contentType") }
            val rawTitle = if (mediaType == "episode" || json.optInt("contentEpisodeNumber") > 0) {
                json.optString("contentTitle")
                    .ifBlank { json.optString("title") }
                    .ifBlank { json.optString("fulltitle") }
            } else {
                json.optString("fulltitle").ifBlank { json.optString("title") }
            }
            return ContentItem(
                title = cleanKodiText(rawTitle),
                subtitle = cleanKodiText(json.optString("title")),
                posterUrl = json.optString("thumbnail").ifBlank { info.optString("thumbnail") },
                backdropUrl = json.optString("fanart").ifBlank { info.optString("fanart") },
                action = json.optString("action"),
                channel = json.optString("channel").ifBlank { defaultChannel },
                source = json.optString("_app_search_source"),
                searchType = json.optString("_search_type").ifBlank {
                    when (mediaType) {
                        "tvshow", "season", "episode", "serie" -> "serie"
                        else -> "film"
                    }
                },
                rawJson = json.toString(),
                mediaType = mediaType,
                tmdbId = info.optString("tmdb_id"),
                plot = cleanKodiText(
                    info.optString("plot")
                        .ifBlank { info.optString("plotoutline") }
                        .ifBlank { json.optString("contentPlot") }
                        .ifBlank { json.optString("plot") }
                        .ifBlank { json.optString("description") },
                ),
                year = info.optInt("year", json.optInt("year")),
                genres = info.optString("genre"),
                rating = info.ratingValue("rating", "vote_average", "tmdb_rating")
                    .takeIf { it > 0.0 }
                    ?: json.ratingValue("rating", "vote_average", "tmdb_rating"),
                season = info.optInt("season").takeIf { it > 0 }
                    ?: json.optInt("contentSeason").takeIf { it > 0 }
                    ?: json.optInt("season"),
                episode = info.optInt("episode").takeIf { it > 0 }
                    ?: json.optInt("contentEpisodeNumber").takeIf { it > 0 }
                    ?: json.optInt("episode"),
                runtimeMinutes = info.runtimeMinutes().takeIf { it > 0 }
                    ?: json.runtimeMinutes(),
                certification = info.cleanTextValue(
                    "mpaa",
                    "certification",
                    "age_rating",
                ).ifBlank {
                    json.cleanTextValue("mpaa", "certification", "age_rating")
                },
                premiered = info.cleanTextValue(
                    "premiered",
                    "firstaired",
                    "release_date",
                ).ifBlank {
                    json.cleanTextValue("premiered", "firstaired", "release_date")
                },
                country = info.cleanTextValue(
                    "country",
                    "country_origin",
                    "origin_country",
                ).ifBlank {
                    json.cleanTextValue("country", "country_origin", "origin_country")
                },
                studio = info.cleanTextValue("studio", "production_company").ifBlank {
                    json.cleanTextValue("studio", "production_company")
                },
                director = info.cleanTextValue("director").ifBlank {
                    json.cleanTextValue("director")
                },
                cast = info.cleanTextValue("cast").ifBlank {
                    json.cleanTextValue("cast")
                },
                isLive = json.optBoolean("_app_live") ||
                    json.optString("contentType").equals("live", ignoreCase = true),
            )
        }
    }
}

data class HomeRow(
    val id: String,
    val title: String,
    val items: List<ContentItem>,
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("title", title)
        put("items", org.json.JSONArray().apply {
            items.forEach { item ->
                runCatching { put(item.toJson()) }
            }
        })
    }

    companion object {
        fun fromJson(json: JSONObject): HomeRow {
            val array = json.optJSONArray("items")
            val items = if (array == null) emptyList() else
                (0 until array.length()).mapNotNull { index ->
                    runCatching {
                        ContentItem.fromJson(array.getJSONObject(index))
                    }.getOrNull()
                }
            return HomeRow(json.optString("id"), json.optString("title"), items)
        }
    }
}

data class PlaybackRequest(
    val url: String,
    val bootstrapUrl: String,
    val manifest: String,
    val audioLanguage: String,
    val headersJson: String,
    val label: String = "Sorgente",
    val server: String = "directo",
    val subtitleUrls: List<String> = emptyList(),
    val drmType: String = "",
    val licenseKey: String = "",
    val askQuality: Boolean = false,
    val maxVideoHeight: Int = 0,
    val textLanguage: String = "it",
    val subtitlesEnabled: Boolean = false,
    val autoplayNext: Boolean = true,
    val fallbackEnabled: Boolean = true,
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("url", url)
        put("bootstrap_url", bootstrapUrl)
        put("manifest_type", manifest)
        put("audio_language", audioLanguage)
        put("headers", JSONObject(headersJson))
        put("label", label)
        put("server", server)
        put("subtitles", org.json.JSONArray(subtitleUrls))
        put("drm_type", drmType)
        put("license_key", licenseKey)
        put("ask_quality", askQuality)
        put("max_video_height", maxVideoHeight)
        put("text_language", textLanguage)
        put("subtitles_enabled", subtitlesEnabled)
        put("autoplay_next", autoplayNext)
        put("fallback_enabled", fallbackEnabled)
    }

    companion object {
        fun fromJson(json: JSONObject) = PlaybackRequest(
            url = json.optString("url"),
            bootstrapUrl = json.optString("bootstrap_url"),
            manifest = json.optString("manifest_type", "hls"),
            audioLanguage = json.optString("audio_language", "it"),
            headersJson = json.optJSONObject("headers")?.toString() ?: "{}",
            label = cleanKodiText(json.optString("label")).ifBlank {
                json.optString("server").ifBlank { "Sorgente" }
            },
            server = json.optString("server", "directo"),
            subtitleUrls = parseSubtitleUrls(json.opt("subtitles")),
            drmType = json.optString("drm_type"),
            licenseKey = json.optString("license_key"),
            askQuality = json.optBoolean("ask_quality"),
            maxVideoHeight = json.optInt("max_video_height"),
            textLanguage = json.optString("text_language", "it"),
            subtitlesEnabled = json.optBoolean("subtitles_enabled", false),
            autoplayNext = json.optBoolean("autoplay_next", true),
            fallbackEnabled = json.optBoolean("fallback_enabled", true),
        )

        private fun parseSubtitleUrls(raw: Any?): List<String> {
            fun valid(value: String) = value.takeIf {
                it.startsWith("http://") || it.startsWith("https://") || it.startsWith("file://")
            }
            return when (raw) {
                is org.json.JSONArray -> (0 until raw.length()).mapNotNull { index ->
                    when (val entry = raw.opt(index)) {
                        is String -> valid(entry)
                        is JSONObject -> valid(entry.optString("url"))
                        else -> null
                    }
                }
                is String -> valid(raw)?.let(::listOf).orEmpty()
                else -> emptyList()
            }.distinct()
        }
    }
}
