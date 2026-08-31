package com.prippi.stream

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

data class AppUpdateInfo(
    val version: String,
    val downloadUrl: String,
    val assetName: String,
    val notes: String,
)

data class AppUpdateCheck(val info: AppUpdateInfo?, val message: String)

object AppUpdateManager {
    private const val LATEST_RELEASE =
        "https://api.github.com/repos/usandissm/PrippiStream/releases/latest"
    private const val MAX_APK_BYTES = 200L * 1024 * 1024
    private const val DOWNLOAD_HEADROOM_BYTES = 32L * 1024 * 1024

    suspend fun checkForUpdate(): AppUpdateCheck = withContext(Dispatchers.IO) {
        val response = requestText(LATEST_RELEASE)
        if (response.first == 404) {
            return@withContext AppUpdateCheck(
                null,
                "Repository collegato: manca ancora una GitHub Release con l'APK.",
            )
        }
        if (response.first !in 200..299) {
            return@withContext AppUpdateCheck(null, "Controllo aggiornamenti non riuscito (HTTP ${response.first}).")
        }
        val release = JSONObject(response.second)
        val assets = release.optJSONArray("assets")
        val apkCandidates = if (assets == null) emptyList() else (0 until assets.length())
            .map { assets.getJSONObject(it) }
            .filter { it.optString("name").endsWith(".apk", ignoreCase = true) }
            .filterNot { it.optString("name").contains("debug", ignoreCase = true) }
        val abiTags = preferredAssetTags()
        val apk = abiTags.firstNotNullOfOrNull { tag ->
            apkCandidates.firstOrNull {
                it.optString("name").contains(tag, ignoreCase = true)
            }
        } ?: apkCandidates.firstOrNull {
            it.optString("name").contains("universal", ignoreCase = true)
        }
        if (apk == null) {
            return@withContext AppUpdateCheck(
                null,
                "La release non contiene un APK compatibile con ${Build.SUPPORTED_ABIS.firstOrNull() ?: "questo dispositivo"}.",
            )
        }
        val remote = release.optString("tag_name").removePrefix("v")
        if (compareVersions(remote, BuildConfig.VERSION_NAME) <= 0) {
            return@withContext AppUpdateCheck(null, "PrippiStream è già aggiornato (${BuildConfig.VERSION_NAME}).")
        }
        val info = AppUpdateInfo(
            version = remote,
            downloadUrl = apk.optString("browser_download_url"),
            assetName = apk.optString("name", "PrippiStream-$remote.apk"),
            notes = release.optString("body"),
        )
        AppUpdateCheck(info, "Nuova versione $remote disponibile.")
    }

    suspend fun download(context: Context, info: AppUpdateInfo): File = withContext(Dispatchers.IO) {
        val directory = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            ?: File(context.cacheDir, "updates")
        directory.mkdirs()
        val safeName = info.assetName.replace(Regex("[^A-Za-z0-9._-]"), "_")
        val target = File(directory, safeName)
        val partial = File(directory, "$safeName.part")
        if (target.isFile) {
            if (runCatching { verifyArchive(context, target) }.isSuccess) {
                return@withContext target
            }
            target.delete()
        }
        partial.delete()
        val connection = open(info.downloadUrl)
        try {
            if (connection.responseCode !in 200..299) {
                error("Download APK fallito: HTTP ${connection.responseCode}")
            }
            val declaredBytes = connection.contentLengthLong
            require(declaredBytes <= 0 || declaredBytes <= MAX_APK_BYTES) {
                "APK troppo grande (${declaredBytes / 1048576} MB)"
            }
            require(
                declaredBytes <= 0 ||
                    directory.usableSpace >= declaredBytes + DOWNLOAD_HEADROOM_BYTES,
            ) {
                "Spazio insufficiente per scaricare e verificare l'aggiornamento"
            }
            connection.inputStream.use { input ->
                partial.outputStream().use { output ->
                    val buffer = ByteArray(128 * 1024)
                    var received = 0L
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        received += count
                        require(received <= MAX_APK_BYTES) {
                            "APK oltre il limite di sicurezza"
                        }
                        output.write(buffer, 0, count)
                    }
                }
            }
            require(partial.length() > 0) { "APK scaricato vuoto" }
            verifyArchive(context, partial)
            target.delete()
            require(partial.renameTo(target)) { "Impossibile completare il file APK" }
            target
        } catch (error: Throwable) {
            partial.delete()
            throw error
        } finally {
            connection.disconnect()
        }
    }

    /** Ritorna false quando Android deve prima concedere "installa app sconosciute". */
    fun requestInstall(context: Context, apk: File): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}"),
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return false
        }
        val uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            apk,
        )
        context.startActivity(Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        })
        return true
    }

    private fun requestText(url: String): Pair<Int, String> {
        val connection = open(url)
        return try {
            val code = connection.responseCode
            val stream = if (code in 200..399) connection.inputStream else connection.errorStream
            code to (stream?.bufferedReader()?.use { it.readText() }.orEmpty())
        } finally {
            connection.disconnect()
        }
    }

    private fun open(url: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = true
            connectTimeout = 12_000
            readTimeout = 30_000
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("User-Agent", "PrippiStream-Android/${BuildConfig.VERSION_NAME}")
        }

    private fun compareVersions(left: String, right: String): Int {
        fun parts(value: String) = Regex("\\d+").findAll(value).map { it.value.toInt() }.toList()
        val a = parts(left)
        val b = parts(right)
        for (index in 0 until maxOf(a.size, b.size)) {
            val compared = (a.getOrElse(index) { 0 }).compareTo(b.getOrElse(index) { 0 })
            if (compared != 0) return compared
        }
        return 0
    }

    private fun preferredAssetTags(): List<String> {
        val supported = Build.SUPPORTED_ABIS.map(String::lowercase)
        return when {
            supported.any { it == "arm64-v8a" } -> listOf("arm64-v8a", "arm64")
            supported.any { it == "armeabi-v7a" } -> listOf("armeabi-v7a", "arm32")
            supported.any { it == "x86_64" } -> listOf("x86_64")
            supported.any { it == "x86" } -> listOf("x86")
            else -> emptyList()
        }
    }

    @Suppress("DEPRECATION")
    private fun verifyArchive(context: Context, apk: File) {
        val flags = signatureQueryFlags(Build.VERSION.SDK_INT)
        val manager = context.packageManager
        val archive = manager.getPackageArchiveInfo(apk.absolutePath, flags)
            ?: error("Il file scaricato non è un APK Android valido")
        require(archive.packageName == context.packageName) {
            "L'APK appartiene a un'altra applicazione (${archive.packageName})"
        }

        val installed = manager.getPackageInfo(context.packageName, flags)
        val archiveCode = archive.versionCodeCompat()
        val installedCode = installed.versionCodeCompat()
        require(archiveCode > installedCode) {
            "La versione scaricata non è più recente ($archiveCode ≤ $installedCode)"
        }
        require(
            archive.signerDigests("scaricato") ==
                installed.signerDigests("installato"),
        ) {
            "Firma APK non valida: aggiornamento rifiutato"
        }
    }

    @Suppress("DEPRECATION")
    private fun PackageInfo.versionCodeCompat(): Long =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) longVersionCode else versionCode.toLong()

    @Suppress("DEPRECATION")
    private fun PackageInfo.signerDigests(label: String): Set<String> {
        val modern = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            signingInfo?.apkContentsSigners?.toList()
        } else {
            null
        }
        val certificates = preferSigningCertificates(modern, signatures?.toList())
        require(certificates.isNotEmpty()) { "APK $label privo di firma leggibile" }
        return certificates.mapTo(linkedSetOf()) { signature ->
            MessageDigest.getInstance("SHA-256")
                .digest(signature.toByteArray())
                .joinToString("") { "%02x".format(it) }
        }
    }
}

@Suppress("DEPRECATION")
internal fun signatureQueryFlags(sdkInt: Int): Int =
    PackageManager.GET_SIGNATURES or
        if (sdkInt >= Build.VERSION_CODES.P) PackageManager.GET_SIGNING_CERTIFICATES else 0

internal fun <T> preferSigningCertificates(
    modern: List<T>?,
    legacy: List<T>?,
): List<T> = modern.orEmpty().ifEmpty { legacy.orEmpty() }
