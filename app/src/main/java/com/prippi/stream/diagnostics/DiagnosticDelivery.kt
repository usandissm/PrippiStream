package com.prippi.stream.diagnostics

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Base64
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.core.app.NotificationCompat
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.prippi.stream.AppDiagnostics
import com.prippi.stream.BuildConfig
import com.prippi.stream.R
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

object DiagnosticDelivery {
    private const val MAX_OUTBOX_REPORTS = 3
    private const val OUTBOX_TTL_MS = 3L * 24 * 60 * 60 * 1_000
    private const val CONNECT_TIMEOUT_MS = 8_000
    private const val READ_TIMEOUT_MS = 30_000
    private const val TELEGRAM_TOKEN_OBF =
        "WVh4Uzdtd2RrQXNLNnpYME1zZVhWallvN2dhaUY4ZWVGQUE6NDYzNjAxMzg4OA=="
    private const val TELEGRAM_CHAT_ID = "6021418937"

    fun deliverOrFallback(
        context: Context,
        sanitizedReport: String,
        fallbackFile: File,
        note: String = "",
    ) {
        val app = context.applicationContext
        Thread {
            val safeReport = truncateDiagnosticUtf8Tail(
                DiagnosticSanitizer.sanitize(sanitizedReport),
            )
            val outbox = persistOutbox(app, safeReport, note)
            val outcome = runCatching {
                sendTelegram(app, outbox, telegramCaption(app, outbox, note))
            }.getOrDefault(SendOutcome.RETRYABLE_FAILURE)

            if (outcome == SendOutcome.SUCCESS) {
                outbox.delete()
                AppDiagnostics.event("diagnostics_delivery success")
                android.os.Handler(app.mainLooper).post {
                    Toast.makeText(
                        context,
                        "Diagnostica inviata allo sviluppatore.",
                        Toast.LENGTH_LONG,
                    ).show()
                }
            } else {
                if (outcome == SendOutcome.RETRYABLE_FAILURE) enqueueRetry(app, outbox)
                else outbox.delete()
                AppDiagnostics.event(
                    "diagnostics_delivery outcome=$outcome channel=telegram",
                )
                android.os.Handler(app.mainLooper).post {
                    Toast.makeText(
                        context,
                        if (outcome == SendOutcome.RETRYABLE_FAILURE) {
                            "Telegram non raggiungibile: report accodato, nuovo tentativo automatico."
                        } else {
                            "Invio Telegram rifiutato: uso la condivisione di backup."
                        },
                        Toast.LENGTH_LONG,
                    ).show()
                    if (outcome == SendOutcome.PERMANENT_FAILURE) {
                        launchFallback(context, fallbackFile)
                    }
                }
            }
        }.start()
    }

    internal fun sendTelegram(context: Context, archive: File, caption: String): SendOutcome {
        // Context is intentionally part of this boundary: it keeps the sender
        // testable and ready for device/network metadata without touching startup.
        context.applicationContext
        if (!archive.isFile || archive.length() <= 0L) return SendOutcome.PERMANENT_FAILURE
        val boundary = UUID.randomUUID().toString().replace("-", "")
        val prefix = buildString {
            appendMultipartField(boundary, "chat_id", TELEGRAM_CHAT_ID)
            appendMultipartField(boundary, "caption", caption.take(1024))
            append("--$boundary\r\n")
            append(
                "Content-Disposition: form-data; name=\"document\"; " +
                    "filename=\"${archive.name}\"\r\n",
            )
            append("Content-Type: application/zip\r\n\r\n")
        }.toByteArray(Charsets.UTF_8)
        val suffix = "\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8)
        val contentLength = prefix.size.toLong() + archive.length() + suffix.size
        if (contentLength > Int.MAX_VALUE) return SendOutcome.PERMANENT_FAILURE

        val endpoint = URL("https://api.telegram.org/bot${telegramToken()}/sendDocument")
        val connection = endpoint.openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.doOutput = true
            connection.instanceFollowRedirects = false
            connection.setFixedLengthStreamingMode(contentLength)
            connection.setRequestProperty(
                "Content-Type",
                "multipart/form-data; boundary=$boundary",
            )
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty(
                "User-Agent",
                "PrippiStream/${BuildConfig.VERSION_NAME} Android",
            )
            connection.outputStream.use { output ->
                output.write(prefix)
                archive.inputStream().use { input -> input.copyTo(output) }
                output.write(suffix)
            }
            val status = connection.responseCode
            val classified = classifyDiagnosticHttpStatus(status)
            if (classified != SendOutcome.SUCCESS) {
                classified
            } else {
                val response = runCatching {
                    connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                }.getOrDefault("")
                if (runCatching { JSONObject(response).optBoolean("ok") }.getOrDefault(false)) {
                    SendOutcome.SUCCESS
                } else {
                    SendOutcome.PERMANENT_FAILURE
                }
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun telegramToken(): String =
        String(Base64.decode(TELEGRAM_TOKEN_OBF, Base64.DEFAULT), Charsets.UTF_8).reversed()

    private fun StringBuilder.appendMultipartField(
        boundary: String,
        name: String,
        value: String,
    ) {
        append("--$boundary\r\n")
        append("Content-Disposition: form-data; name=\"$name\"\r\n\r\n")
        append(value.replace("\r", " ").replace("\n", " "))
        append("\r\n")
    }

    private fun installId(context: Context): String {
        val preferences = context.getSharedPreferences("diagnostics_delivery", Context.MODE_PRIVATE)
        return preferences.getString("install_id", null) ?: UUID.randomUUID().toString().also {
            preferences.edit().putString("install_id", it).apply()
        }
    }

    private fun persistOutbox(context: Context, report: String, note: String): File {
        val directory = File(context.filesDir, "diagnostic-outbox").apply { mkdirs() }
        val now = System.currentTimeMillis()
        directory.listFiles()
            .orEmpty()
            .filter(File::isFile)
            .forEach { if (now - it.lastModified() > OUTBOX_TTL_MS) it.delete() }
        directory.listFiles()
            .orEmpty()
            .filter(File::isFile)
            .sortedByDescending(File::lastModified)
            .drop(MAX_OUTBOX_REPORTS - 1)
            .forEach(File::delete)
        val archive = File(
            directory,
            "prippi-${SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(Date(now))}.zip",
        )
        ZipOutputStream(archive.outputStream().buffered()).use { zip ->
            zip.putNextEntry(ZipEntry("diagnostics.txt"))
            zip.write(report.toByteArray(Charsets.UTF_8))
            zip.closeEntry()
            zip.putNextEntry(ZipEntry("info.txt"))
            zip.write(diagnosticInfo(context, note).toByteArray(Charsets.UTF_8))
            zip.closeEntry()
        }
        return archive
    }

    private fun diagnosticInfo(context: Context, note: String): String = buildString {
        appendLine("PrippiStream ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
        appendLine("Dispositivo ${Build.MANUFACTURER} ${Build.MODEL}")
        appendLine("Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
        appendLine("ID ${installId(context)}")
        appendLine(
            "Inviato ${
                SimpleDateFormat("yyyy-MM-dd HH:mm:ss Z", Locale.ROOT).format(Date())
            }",
        )
        appendLine("Nota ${DiagnosticSanitizer.sanitize(note).trim().ifBlank { "anonimo" }}")
    }

    private fun telegramCaption(context: Context, archive: File, note: String): String =
        buildString {
            appendLine("PrippiStream ${BuildConfig.VERSION_NAME} | Android ${Build.VERSION.RELEASE}")
            appendLine("${Build.MANUFACTURER} ${Build.MODEL}")
            appendLine("ID: ${installId(context)}")
            appendLine("Log: ${archive.name} (${archive.length() / 1024} KB)")
            append("Da: ${DiagnosticSanitizer.sanitize(note).trim().ifBlank { "anonimo" }}")
        }.take(1024)

    private fun enqueueRetry(context: Context, report: File) {
        val request = OneTimeWorkRequestBuilder<DiagnosticUploadWorker>()
            .setInputData(Data.Builder().putString(DiagnosticUploadWorker.REPORT_PATH, report.path).build())
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "diagnostic-upload:${report.name}",
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    private fun launchFallback(context: Context, report: File) {
        runCatching {
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                report,
            )
            val sendIntent = Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(Intent.EXTRA_SUBJECT, "Diagnostica PrippiStream ${BuildConfig.VERSION_NAME}")
                putExtra(Intent.EXTRA_STREAM, uri)
                clipData = android.content.ClipData.newRawUri("Diagnostica PrippiStream", uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            val chooser = Intent.createChooser(sendIntent, "Condividi diagnostica").apply {
                if (context !is android.app.Activity) addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(chooser)
        }.onFailure {
            Toast.makeText(
                context,
                "Impossibile aprire la condivisione: ${it.message}",
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    internal fun notifyManualBackup(context: Context, report: File) {
        if (!report.isFile) return
        runCatching {
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                report,
            )
            val share = Intent(Intent.ACTION_SEND).apply {
                type = if (report.extension.equals("zip", ignoreCase = true)) {
                    "application/zip"
                } else {
                    "text/plain"
                }
                putExtra(Intent.EXTRA_SUBJECT, "Diagnostica PrippiStream ${BuildConfig.VERSION_NAME}")
                putExtra(Intent.EXTRA_STREAM, uri)
                clipData = android.content.ClipData.newRawUri("Diagnostica PrippiStream", uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            val chooser = Intent.createChooser(share, "Condividi diagnostica")
            val pending = PendingIntent.getActivity(
                context,
                report.name.hashCode(),
                chooser,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val manager = context.getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                manager.createNotificationChannel(
                    NotificationChannel(
                        BACKUP_CHANNEL,
                        "Diagnostica PrippiStream",
                        NotificationManager.IMPORTANCE_DEFAULT,
                    ),
                )
            }
            manager.notify(
                report.name.hashCode(),
                NotificationCompat.Builder(context, BACKUP_CHANNEL)
                    .setSmallIcon(R.drawable.prippistream_icon)
                    .setContentTitle("Diagnostica pronta per il backup")
                    .setContentText("Telegram non è raggiungibile. Tocca per condividere il report.")
                    .setContentIntent(pending)
                    .setAutoCancel(true)
                    .build(),
            )
        }.onFailure {
            AppDiagnostics.event("diagnostics_backup_notification_failed", it)
        }
    }

    private const val BACKUP_CHANNEL = "prippi_diagnostics_backup"
}

class DiagnosticUploadWorker(
    context: Context,
    parameters: WorkerParameters,
) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val report = inputData.getString(REPORT_PATH)?.let(::File)
            ?: return@withContext Result.failure()
        if (!report.isFile) return@withContext Result.success()
        val outcome = runCatching {
            DiagnosticDelivery.sendTelegram(
                applicationContext,
                report,
                "PrippiStream ${BuildConfig.VERSION_NAME} | reinvio automatico\n${report.name}",
            )
        }.getOrDefault(SendOutcome.RETRYABLE_FAILURE)
        if (outcome == SendOutcome.SUCCESS) {
            report.delete()
            Result.success()
        } else if (outcome == SendOutcome.PERMANENT_FAILURE) {
            DiagnosticDelivery.notifyManualBackup(applicationContext, report)
            Result.failure()
        } else if (runAttemptCount >= 5) {
            DiagnosticDelivery.notifyManualBackup(applicationContext, report)
            Result.failure()
        } else {
            Result.retry()
        }
    }

    companion object {
        const val REPORT_PATH = "report_path"
    }
}
