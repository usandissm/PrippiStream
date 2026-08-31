package com.prippi.stream

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject

data class WatchProgress(
    val key: String,
    val rawJson: String,
    val positionMs: Long,
    val durationMs: Long,
    val updatedAt: Long,
) {
    fun contentItem(): ContentItem? = try {
        ContentItem.fromJson(JSONObject(rawJson)).withProgress(positionMs, durationMs)
    } catch (_: Exception) {
        null
    }
}

/** Cronologia locale versionata. I token di playback non vengono mai salvati:
 * alla ripresa il resolver genera una sorgente fresca dall'Item originale. */
class WatchProgressStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    @Synchronized
    fun list(): List<WatchProgress> = readAll().values
        .sortedByDescending { it.updatedAt }
        .take(MAX_ITEMS)

    @Synchronized
    fun find(key: String): WatchProgress? = readAll()[key]

    @Synchronized
    fun find(item: ContentItem): WatchProgress? {
        val saved = readAll()[item.continueWatchingKey] ?: return null
        return saved.takeIf { ContinueWatchingPolicy.sameEpisode(it.rawJson, item) }
    }

    @Synchronized
    fun save(key: String, rawJson: String, positionMs: Long, durationMs: Long) {
        saveInternal(key, rawJson, positionMs, durationMs, synchronous = false)
    }

    /** Salvataggio bloccante usato prima di chiudere il player/PiP. */
    @Synchronized
    fun saveNow(key: String, rawJson: String, positionMs: Long, durationMs: Long) {
        saveInternal(key, rawJson, positionMs, durationMs, synchronous = true)
        AppDiagnostics.event(
            "cw_save_sync position_ms=$positionMs duration_ms=$durationMs",
        )
    }

    private fun saveInternal(
        key: String,
        rawJson: String,
        positionMs: Long,
        durationMs: Long,
        synchronous: Boolean,
    ) {
        if (key.isBlank() || rawJson.isBlank() || positionMs < MIN_PROGRESS_MS) return
        if (runCatching { JSONObject(rawJson).optBoolean("_app_live") }.getOrDefault(false)) {
            remove(key)
            return
        }
        val canonicalKey = ContinueWatchingPolicy.keyFor(key, rawJson)
        if (durationMs > 0 && positionMs >= durationMs * COMPLETE_PERCENT / 100) {
            remove(canonicalKey)
            return
        }
        val all = readAll().toMutableMap()
        all[canonicalKey] = WatchProgress(
            canonicalKey,
            rawJson,
            positionMs,
            durationMs,
            System.currentTimeMillis(),
        )
        writeAll(
            all.values.sortedByDescending { it.updatedAt }.take(MAX_ITEMS),
            synchronous = synchronous,
        )
    }

    /** Move CW to a newly selected/autoplayed episode before it has 10 seconds of progress. */
    @Synchronized
    fun advanceTo(item: ContentItem) {
        if (item.isLive || !item.isEpisode) return
        val all = readAll().toMutableMap()
        all[item.continueWatchingKey] = WatchProgress(
            key = item.continueWatchingKey,
            rawJson = item.rawJson,
            positionMs = 0L,
            durationMs = 0L,
            updatedAt = System.currentTimeMillis(),
        )
        writeAll(all.values.sortedByDescending { it.updatedAt }.take(MAX_ITEMS))
    }

    @Synchronized
    fun remove(key: String) {
        val all = readAll().toMutableMap()
        if (all.remove(key) != null) writeAll(all.values)
    }

    @Synchronized
    fun remove(item: ContentItem) = remove(item.continueWatchingKey)

    @Synchronized
    fun remove(key: String, rawJson: String) =
        remove(ContinueWatchingPolicy.keyFor(key, rawJson))

    /** Rewrites stale SC URLs in local CW after the provider rotates domain. */
    @Synchronized
    fun rewriteDomain(channel: String, currentHost: String): Int {
        val authority = runCatching { Uri.parse(currentHost).authority.orEmpty() }.getOrDefault("")
        if (authority.isBlank()) return 0
        val all = readAll().toMutableMap()
        var changed = 0
        val rewritten = all.values.map { entry ->
            val item = runCatching { ContentItem.fromJson(JSONObject(entry.rawJson)) }.getOrNull()
            if (item?.channel?.equals(channel, ignoreCase = true) != true) return@map entry
            val root = runCatching { JSONObject(entry.rawJson) }.getOrNull() ?: return@map entry
            val before = root.toString()
            rewriteJsonUrls(root, authority)
            val after = root.toString()
            if (before == after) return@map entry
            changed++
            entry.copy(
                key = ContinueWatchingPolicy.keyFor(entry.key, after),
                rawJson = after,
            )
        }
        if (changed > 0) {
            writeAll(rewritten.sortedByDescending { it.updatedAt }.take(MAX_ITEMS))
            AppDiagnostics.event("cw_domain_rewritten channel=$channel entries=$changed")
        }
        return changed
    }

    private fun rewriteJsonUrls(value: Any?, authority: String) {
        when (value) {
            is JSONObject -> {
                val names = value.keys().asSequence().toList()
                names.forEach { name ->
                    val child = value.opt(name)
                    if (child is String) {
                        val uri = runCatching { Uri.parse(child) }.getOrNull()
                        val host = uri?.host.orEmpty()
                        if (uri != null && uri.scheme in listOf("http", "https") &&
                            host.contains("streamingcommunity", ignoreCase = true) &&
                            host != authority
                        ) {
                            value.put(name, uri.buildUpon().authority(authority).build().toString())
                        }
                    } else rewriteJsonUrls(child, authority)
                }
            }
            is org.json.JSONArray -> for (index in 0 until value.length()) {
                rewriteJsonUrls(value.opt(index), authority)
            }
        }
    }

    private fun readAll(): Map<String, WatchProgress> {
        val raw = prefs.getString(KEY_ENTRIES, "[]") ?: "[]"
        return try {
            val array = JSONArray(raw)
            val parsed = mutableListOf<WatchProgress>()
            var migrationNeeded = false
            for (index in 0 until array.length()) {
                val stored = array.optJSONObject(index)
                if (stored == null) {
                    migrationNeeded = true
                    continue
                }
                val storedKey = stored.optString("key")
                val rawJson = stored.optString("item")
                if (storedKey.isBlank() || rawJson.isBlank()) {
                    migrationNeeded = true
                    continue
                }
                val progress = WatchProgress(
                    key = storedKey,
                    rawJson = rawJson,
                    positionMs = stored.optLong("position_ms"),
                    durationMs = stored.optLong("duration_ms"),
                    updatedAt = stored.optLong("updated_at"),
                )
                parsed += progress
                if (stored.optInt("schema", 1) < SCHEMA_VERSION) migrationNeeded = true
            }
            val normalizedList = ContinueWatchingPolicy.normalizeProgress(parsed).take(MAX_ITEMS)
            val normalized = normalizedList.associateBy(WatchProgress::key)
            if (normalizedList.size != parsed.size ||
                normalizedList.map(WatchProgress::key).toSet() != parsed.map(WatchProgress::key).toSet()
            ) migrationNeeded = true
            if (migrationNeeded) {
                android.util.Log.i(
                    "Prippi",
                    "CW migration v$SCHEMA_VERSION: ${parsed.size} -> ${normalizedList.size}",
                )
                writeAll(normalizedList)
            }
            normalized
        } catch (error: Exception) {
            android.util.Log.e("Prippi", "Cronologia non leggibile: reset", error)
            emptyMap()
        }
    }

    private fun writeAll(entries: Collection<WatchProgress>, synchronous: Boolean = false) {
        val array = JSONArray()
        entries.forEach { progress ->
            array.put(JSONObject().apply {
                put("schema", SCHEMA_VERSION)
                put("key", progress.key)
                put("item", progress.rawJson)
                put("position_ms", progress.positionMs)
                put("duration_ms", progress.durationMs)
                put("updated_at", progress.updatedAt)
            })
        }
        val editor = prefs.edit().putString(KEY_ENTRIES, array.toString())
        if (synchronous) {
            if (!editor.commit()) {
                android.util.Log.e("Prippi", "Salvataggio sincrono CW non riuscito")
            }
        } else {
            editor.apply()
        }
    }

    private companion object {
        const val PREFS = "prippi_watch_progress"
        const val KEY_ENTRIES = "entries_v1"
        const val SCHEMA_VERSION = 2
        const val MAX_ITEMS = 30
        const val MIN_PROGRESS_MS = 10_000L
        const val COMPLETE_PERCENT = 92
    }
}
