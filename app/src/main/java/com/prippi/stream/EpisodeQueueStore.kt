package com.prippi.stream

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Keeps long episode queues outside Binder. Each line is one self-contained
 * episode, so the TV player reads only the next record when autoplay advances.
 */
object EpisodeQueueStore {
    private const val DIRECTORY = "episode-queues"
    private const val MAX_AGE_MS = 48L * 60L * 60L * 1_000L
    private val validKey = Regex("^[a-f0-9-]{36}$")

    fun put(context: Context, queue: JSONArray): String {
        if (queue.length() == 0) return ""
        val directory = File(context.cacheDir, DIRECTORY).apply { mkdirs() }
        prune(directory)
        val key = UUID.randomUUID().toString()
        val pending = File(directory, "$key.tmp")
        pending.bufferedWriter().use { writer ->
            for (index in 0 until queue.length()) {
                val source = queue.optJSONObject(index) ?: continue
                val record = JSONObject(source.toString()).apply {
                    remove("_app_episode_queue")
                    remove("_app_episode_index")
                }
                writer.append(record.toString())
                writer.newLine()
            }
        }
        val destination = File(directory, "$key.ndjson")
        check(pending.renameTo(destination)) { "Impossibile salvare la coda episodi" }
        return key
    }

    fun get(context: Context, key: String, index: Int): JSONObject? {
        if (index < 0 || !validKey.matches(key)) return null
        val file = File(File(context.cacheDir, DIRECTORY), "$key.ndjson")
        if (!file.isFile) return null
        return file.bufferedReader().useLines { lines ->
            lines.drop(index).firstOrNull()?.let(::JSONObject)
        }
    }

    private fun prune(directory: File) {
        val oldestAllowed = System.currentTimeMillis() - MAX_AGE_MS
        directory.listFiles().orEmpty()
            .filter { it.lastModified() < oldestAllowed || it.extension == "tmp" }
            .forEach { it.delete() }
    }
}
