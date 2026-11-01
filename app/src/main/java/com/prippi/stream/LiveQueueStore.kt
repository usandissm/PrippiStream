package com.prippi.stream

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/** Keep large live/event rows out of activity Intents and Android's Binder buffer. */
object LiveQueueStore {
    private val validKey = Regex("^[a-f0-9-]{36}$")
    private const val MAX_AGE_MS = 48L * 60L * 60L * 1_000L

    fun put(cacheDir: File, queue: JSONArray): String {
        if (queue.length() == 0) return ""
        val directory = File(cacheDir, "live-queues").apply { mkdirs() }
        directory.listFiles().orEmpty()
            .filter { it.lastModified() < System.currentTimeMillis() - MAX_AGE_MS }
            .forEach { it.delete() }
        val records = JSONArray()
        for (index in 0 until queue.length()) {
            val source = queue.getJSONObject(index)
            records.put(JSONObject(source.toString()).apply {
                remove("_app_live_row_items")
                remove("_app_live_row_index")
            })
        }
        val key = UUID.randomUUID().toString()
        val pending = File(directory, "$key.tmp")
        try {
            pending.writeText(records.toString(), Charsets.UTF_8)
            check(pending.renameTo(File(directory, "$key.json"))) {
                "Impossibile salvare la lista Live"
            }
        } finally {
            pending.delete()
        }
        return key
    }

    fun get(cacheDir: File, key: String): JSONArray {
        if (!validKey.matches(key)) return JSONArray()
        return runCatching {
            JSONArray(File(File(cacheDir, "live-queues"), "$key.json").readText(Charsets.UTF_8))
        }.getOrDefault(JSONArray())
    }
}
