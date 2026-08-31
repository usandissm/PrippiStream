package com.prippi.stream

import android.content.Context
import org.json.JSONObject
import java.util.Locale

internal enum class TrackPreferenceMode { AUTO, TRACK, OFF }

internal data class TrackDescriptor(
    val language: String = "",
    val label: String = "",
    val roleFlags: Int = 0,
)

internal data class StoredTrackPreference(
    val mode: TrackPreferenceMode,
    val descriptor: TrackDescriptor? = null,
)

internal data class MediaTrackPreferences(
    val audio: StoredTrackPreference? = null,
    val subtitles: StoredTrackPreference? = null,
)

internal data class TrackCandidate(
    val groupIndex: Int,
    val trackIndex: Int,
    val descriptor: TrackDescriptor,
    val supported: Boolean = true,
)

/** Stable media identity and conservative matching shared by the player and JVM tests. */
internal object MediaTrackPreferencePolicy {
    fun keyFor(item: ContentItem): String? {
        if (item.isLive) return null
        val identity = ContinueWatchingPolicy.keyFor(item).trim()
        return identity.takeIf(String::isNotBlank)?.let { "media-tracks:$it" }
    }

    /**
     * Never guesses by list position. A candidate must agree with the stored language or label;
     * role flags only refine a match because providers do not expose them consistently.
     */
    fun bestMatch(
        preferred: TrackDescriptor,
        candidates: List<TrackCandidate>,
    ): TrackCandidate? {
        val wantedLanguage = normalizeLanguage(preferred.language)
        val wantedLabel = normalizeText(preferred.label)
        if (wantedLanguage.isBlank() && wantedLabel.isBlank() && preferred.roleFlags == 0) return null

        return candidates.asSequence()
            .filter(TrackCandidate::supported)
            .mapNotNull { candidate ->
                val language = normalizeLanguage(candidate.descriptor.language)
                val label = normalizeText(candidate.descriptor.label)
                val languageMatches = wantedLanguage.isNotBlank() && language == wantedLanguage
                val labelMatches = wantedLabel.isNotBlank() && label == wantedLabel
                val roleMatches = preferred.roleFlags != 0 &&
                    candidate.descriptor.roleFlags and preferred.roleFlags != 0

                val eligible = when {
                    wantedLanguage.isNotBlank() -> languageMatches
                    wantedLabel.isNotBlank() -> labelMatches
                    else -> roleMatches
                }
                if (!eligible) return@mapNotNull null

                val score =
                    (if (languageMatches) 100 else 0) +
                        (if (labelMatches) 40 else 0) +
                        (if (roleMatches) 20 else 0) +
                        (if (candidate.descriptor.roleFlags == preferred.roleFlags) 5 else 0)
                candidate to score
            }
            .maxWithOrNull(
                compareBy<Pair<TrackCandidate, Int>> { it.second }
                    .thenBy { -it.first.groupIndex }
                    .thenBy { -it.first.trackIndex },
            )
            ?.first
    }

    internal fun normalizeLanguage(value: String): String {
        val normalized = value.trim().lowercase(Locale.ROOT).replace('_', '-')
        if (normalized.isBlank() || normalized == "und") return ""
        val primary = normalized.substringBefore('-')
        return when (primary) {
            "ita" -> "it"
            "eng" -> "en"
            "spa" -> "es"
            "fra", "fre" -> "fr"
            "deu", "ger" -> "de"
            "por" -> "pt"
            "jpn" -> "ja"
            else -> primary
        }
    }

    private fun normalizeText(value: String): String = value.trim()
        .lowercase(Locale.ROOT)
        .replace(Regex("[^a-z0-9]+"), " ")
        .trim()
}

/** Local-only preferences: one movie key or one canonical series key, never a live channel. */
internal class MediaTrackPreferenceStore(context: Context) {
    private val prefs = context.applicationContext
        .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun get(key: String?): MediaTrackPreferences? {
        if (key.isNullOrBlank()) return null
        val raw = prefs.getString(key, null) ?: return null
        return runCatching { decode(JSONObject(raw)) }.getOrNull()
    }

    fun setAudio(key: String?, preference: StoredTrackPreference) = update(key) {
        copy(audio = preference)
    }

    fun setSubtitles(key: String?, preference: StoredTrackPreference) = update(key) {
        copy(subtitles = preference)
    }

    private fun update(key: String?, transform: MediaTrackPreferences.() -> MediaTrackPreferences) {
        if (key.isNullOrBlank()) return
        val updated = (get(key) ?: MediaTrackPreferences()).transform()
        prefs.edit().putString(key, encode(updated).toString()).apply()
    }

    private fun encode(value: MediaTrackPreferences) = JSONObject().apply {
        put("schema", SCHEMA_VERSION)
        value.audio?.let { put("audio", encode(it)) }
        value.subtitles?.let { put("subtitles", encode(it)) }
    }

    private fun encode(value: StoredTrackPreference) = JSONObject().apply {
        put("mode", value.mode.name.lowercase(Locale.ROOT))
        value.descriptor?.let { descriptor ->
            put("language", descriptor.language)
            put("label", descriptor.label)
            put("role_flags", descriptor.roleFlags)
        }
    }

    private fun decode(value: JSONObject) = MediaTrackPreferences(
        audio = value.optJSONObject("audio")?.let(::decodeTrack),
        subtitles = value.optJSONObject("subtitles")?.let(::decodeTrack),
    )

    private fun decodeTrack(value: JSONObject): StoredTrackPreference? {
        val mode = runCatching {
            TrackPreferenceMode.valueOf(value.optString("mode").uppercase(Locale.ROOT))
        }.getOrNull() ?: return null
        val descriptor = if (mode == TrackPreferenceMode.TRACK) {
            TrackDescriptor(
                language = value.optString("language"),
                label = value.optString("label"),
                roleFlags = value.optInt("role_flags"),
            )
        } else null
        return StoredTrackPreference(mode, descriptor)
    }

    private companion object {
        const val PREFS_NAME = "prippi_media_track_preferences"
        const val SCHEMA_VERSION = 1
    }
}
