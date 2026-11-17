package com.prippi.stream

import android.content.Context
import android.os.Build
import android.util.AtomicFile
import android.util.Base64
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom

object LiveDeviceAccess {
    private const val BASE = "https://prippistream-live.prippistream-profiles.workers.dev/v1/devices"
    private val format = Regex("[A-Za-z0-9_-]{43}")

    data class Status(val state: String, val hint: String = "")

    fun check(context: Context): Status = communicate(context, false, false)

    fun request(context: Context, replace: Boolean): Status = communicate(context, true, replace)

    private fun communicate(context: Context, request: Boolean, replace: Boolean): Status {
        val file = AtomicFile(File(context.filesDir, "live-device.pending.token"))
        fun read(target: AtomicFile) =
            runCatching { target.readFully().toString(Charsets.US_ASCII).trim() }
                .getOrDefault("").takeIf(format::matches)
        val saved = read(file) ?: read(AtomicFile(File(context.filesDir, "live-device.token")))
        if (!request && saved == null) return Status("not_requested")
        val token = saved?.takeUnless { replace } ?: ByteArray(32).also(SecureRandom()::nextBytes).let {
            Base64.encodeToString(it, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        }
        val conn = URL(BASE + if (request) "/request" else "/status").openConnection() as HttpURLConnection
        try {
            conn.instanceFollowRedirects = false
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            conn.setRequestProperty("User-Agent", "PrippiStream-Live/1.0")
            conn.setRequestProperty("Authorization", "Bearer $token")
            if (request) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                val label = "${Build.MANUFACTURER} ${Build.MODEL}"
                    .replace(Regex("[^\\p{L}\\p{N} ._()-]"), " ").trim().take(60).ifBlank { "Android" }
                conn.outputStream.use { it.write(JSONObject().put("label", label).toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            if (code == 429) return Status("busy")
            if (code != 200) throw IOException("Servizio accesso Live non disponibile")
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            val data = JSONObject(body)
            val status = Status(data.getString("state"), data.getString("hint"))
            if (request && status.state in setOf("pending", "approved") &&
                (token != saved || status.state == "pending") && read(file) != token) {
                val stream = file.startWrite()
                try {
                    stream.write(token.toByteArray(Charsets.US_ASCII))
                    file.finishWrite(stream)
                } catch (error: IOException) {
                    file.failWrite(stream)
                    throw error
                }
            }
            return status
        } finally {
            conn.disconnect()
        }
    }
}
