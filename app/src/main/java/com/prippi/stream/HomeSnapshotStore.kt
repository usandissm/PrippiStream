package com.prippi.stream

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Snapshot nativo della Home, leggibile senza avviare Chaquopy.
 *
 * Non è una seconda fonte dati: conserva l'ultima risposta già validata dal
 * motore e la mostra durante il suo avvio. Il refresh Python la sostituisce
 * appena pronto. Scrittura atomica, TTL e limite dimensione impediscono che un
 * file vecchio o corrotto rallenti il bootstrap.
 */
class HomeSnapshotStore(context: Context) {
    private val snapshotFile = File(context.filesDir, FILE_NAME)

    fun load(nowMs: Long = System.currentTimeMillis()): List<HomeRow> = runCatching {
        if (!snapshotFile.isFile || snapshotFile.length() !in 1..MAX_BYTES) {
            return@runCatching emptyList()
        }
        decode(snapshotFile.readText(Charsets.UTF_8), nowMs)
    }.onSuccess {
        android.util.Log.i("PrippiSnapshot", "loaded rows=${it.size}")
    }.onFailure {
        android.util.Log.e("PrippiSnapshot", "load failed", it)
    }.getOrDefault(emptyList())

    fun save(rows: List<HomeRow>, nowMs: Long = System.currentTimeMillis()) {
        runCatching {
            val payload = encode(rows, nowMs) ?: return
            if (payload.toByteArray(Charsets.UTF_8).size > MAX_BYTES) return
            val staging = File(snapshotFile.parentFile, "$FILE_NAME.tmp")
            val backup = File(snapshotFile.parentFile, "$FILE_NAME.bak")
            staging.writeText(payload, Charsets.UTF_8)
            backup.delete()
            if (snapshotFile.exists() && !snapshotFile.renameTo(backup)) {
                staging.delete()
                return
            }
            if (!staging.renameTo(snapshotFile)) {
                backup.renameTo(snapshotFile)
                staging.delete()
                return
            }
            backup.delete()
            android.util.Log.i(
                "PrippiSnapshot",
                "saved rows=${stableRowCount(rows)} bytes=${snapshotFile.length()}",
            )
        }.onFailure {
            android.util.Log.e("PrippiSnapshot", "save failed", it)
        }
    }

    companion object {
        private const val VERSION = 1
        private const val FILE_NAME = "home-ui-snapshot.json"
        private const val CONTINUE_ROW_ID = "continue_watching"
        private const val MAX_AGE_MS = 12 * 60 * 60 * 1000L
        private const val MAX_BYTES = 2L * 1024 * 1024
        private const val MAX_ROWS = 6
        private const val MAX_ITEMS_PER_ROW = 12

        internal fun encode(rows: List<HomeRow>, nowMs: Long): String? {
            val stableRows = rows.filter { row ->
                row.id != CONTINUE_ROW_ID && row.items.isNotEmpty()
            }.take(MAX_ROWS).map { row ->
                row.copy(items = row.items.take(MAX_ITEMS_PER_ROW))
            }
            if (stableRows.isEmpty()) return null
            return JSONObject().apply {
                put("version", VERSION)
                put("saved_at_ms", nowMs)
                put("rows", JSONArray().apply {
                    stableRows.forEach { put(it.toJson()) }
                })
            }.toString()
        }

        private fun stableRowCount(rows: List<HomeRow>): Int =
            rows.count { it.id != CONTINUE_ROW_ID && it.items.isNotEmpty() }

        internal fun decode(blob: String, nowMs: Long): List<HomeRow> {
            val payload = JSONObject(blob)
            if (payload.optInt("version") != VERSION) return emptyList()
            val savedAt = payload.optLong("saved_at_ms")
            val age = nowMs - savedAt
            if (savedAt <= 0 || age !in 0..MAX_AGE_MS) return emptyList()
            val jsonRows = payload.optJSONArray("rows") ?: return emptyList()
            return buildList {
                for (index in 0 until minOf(jsonRows.length(), MAX_ROWS)) {
                    val row = runCatching {
                        val source = jsonRows.getJSONObject(index)
                        val sourceItems = source.optJSONArray("items") ?: JSONArray()
                        val boundedItems = JSONArray().apply {
                            for (itemIndex in 0 until minOf(
                                sourceItems.length(),
                                MAX_ITEMS_PER_ROW,
                            )) {
                                put(sourceItems.getJSONObject(itemIndex))
                            }
                        }
                        HomeRow.fromJson(
                            JSONObject().apply {
                                put("id", source.optString("id"))
                                put("title", source.optString("title"))
                                put("items", boundedItems)
                            },
                        )
                    }.getOrNull()
                    if (row != null && row.id != CONTINUE_ROW_ID && row.items.isNotEmpty()) {
                        add(row)
                    }
                }
            }
        }
    }
}
