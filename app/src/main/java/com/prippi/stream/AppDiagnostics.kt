package com.prippi.stream

import android.app.Activity
import android.app.Application
import android.os.Build
import android.os.Bundle
import android.os.Debug
import coil.ImageLoader
import coil.ImageLoaderFactory
import coil.disk.DiskCache
import coil.imageLoader
import coil.memory.MemoryCache
import com.prippi.stream.diagnostics.DiagnosticSanitizer
import java.io.File
import java.io.PrintWriter
import java.io.RandomAccessFile
import java.io.StringWriter
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import kotlin.concurrent.thread

/**
 * Diagnostica persistente per box sulle quali ADB di rete non è disponibile.
 *
 * Il report resta nel sandbox dell'app e, mentre il processo è attivo, è
 * leggibile dalla sola rete locale su http://<ip-box>:18765/diagnostics.
 */
object AppDiagnostics {
    private const val PORT = 18765
    private const val MAX_EVENT_BYTES = 512 * 1024L
    private const val MAX_REPORT_BYTES = 900_000
    private val lock = Any()
    private val timestamp = SimpleDateFormat(
        "yyyy-MM-dd'T'HH:mm:ss.SSSXXX",
        Locale.ROOT,
    )

    @Volatile
    private var installed = false
    private lateinit var application: Application
    private lateinit var diagnosticsDir: File
    private lateinit var eventLog: File
    private lateinit var crashLog: File
    private lateinit var sessionMarker: File
    private var previousExceptionHandler: Thread.UncaughtExceptionHandler? = null
    private var sessionId = ""
    private var lastFocusWriteMs = 0L
    @Volatile
    private var lastFocus = ""

    fun install(app: Application) {
        if (installed) return
        synchronized(lock) {
            if (installed) return
            application = app
            diagnosticsDir = File(app.filesDir, "diagnostics").apply { mkdirs() }
            eventLog = File(diagnosticsDir, "app-events.log")
            crashLog = File(diagnosticsDir, "last-crash.log")
            sessionMarker = File(diagnosticsDir, "active-session.txt")
            sessionId = UUID.randomUUID().toString()

            val previousSession = runCatching {
                sessionMarker.takeIf(File::isFile)?.readText()?.trim()
            }.getOrNull()
            if (!previousSession.isNullOrBlank()) {
                appendEvent("previous_session_unclean marker=$previousSession")
            }
            runCatching {
                sessionMarker.writeText("$sessionId ${now()}")
            }

            previousExceptionHandler = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { crashedThread, throwable ->
                captureCrash(crashedThread, throwable)
                previousExceptionHandler?.uncaughtException(crashedThread, throwable)
            }
            registerLifecycleCallbacks(app)
            installed = true
            appendEvent(
                "process_start version=${BuildConfig.VERSION_NAME}/${BuildConfig.VERSION_CODE} " +
                    "device=${Build.MANUFACTURER}/${Build.MODEL} android=${Build.VERSION.RELEASE} " +
                    "api=${Build.VERSION.SDK_INT} abis=${Build.SUPPORTED_ABIS.joinToString()}",
            )
            startLocalServer()
        }
    }

    fun event(message: String, throwable: Throwable? = null) {
        if (!installed) return
        val details = throwable?.let { "\n${stackTrace(it)}" }.orEmpty()
        appendEvent(DiagnosticSanitizer.sanitize("$message$details"))
    }

    fun focus(page: String, rowId: String, itemKey: String) {
        if (!installed) return
        lastFocus = DiagnosticSanitizer.sanitize("$page row=$rowId item=$itemKey")
        val now = System.currentTimeMillis()
        if (now - lastFocusWriteMs >= 1_000) {
            lastFocusWriteMs = now
            appendEvent(DiagnosticSanitizer.sanitize("focus $lastFocus"))
        }
    }

    fun trimMemory(level: Int) {
        event("trim_memory level=$level ${memorySummary()}")
    }

    fun markCleanExit(reason: String) {
        if (!installed) return
        event("clean_exit reason=$reason")
        runCatching { sessionMarker.delete() }
    }

    fun report(): String {
        if (!installed) return "Diagnostica non inizializzata."
        val engineLog = File(application.filesDir, "logs/prippistream.log")
        val body = buildString {
            appendLine("PrippiStream diagnostics")
            appendLine("generated=${now()}")
            appendLine("session=$sessionId")
            appendLine("last_focus=${lastFocus.ifBlank { "unknown" }}")
            appendLine(memorySummary())
            appendLine()
            appendLine("--- LAST CRASH ---")
            appendLine(tail(crashLog, 300_000).ifBlank { "none" })
            appendLine("--- APP EVENTS ---")
            appendLine(tail(eventLog, 350_000).ifBlank { "none" })
            appendLine("--- PYTHON ENGINE ---")
            appendLine(tail(engineLog, 250_000).ifBlank { "none" })
        }
        return DiagnosticSanitizer.sanitize(body).takeLast(MAX_REPORT_BYTES)
    }

    private fun captureCrash(thread: Thread, throwable: Throwable) {
        val body = buildString {
            appendLine("timestamp=${now()}")
            appendLine("session=$sessionId")
            appendLine("thread=${thread.name} id=${thread.id}")
            appendLine("last_focus=${lastFocus.ifBlank { "unknown" }}")
            appendLine(memorySummary())
            appendLine(stackTrace(throwable))
        }
        runCatching {
            synchronized(lock) {
                crashLog.writeText(DiagnosticSanitizer.sanitize(body))
            }
        }
        appendEvent("uncaught_exception thread=${thread.name}\n${stackTrace(throwable)}")
    }

    private fun registerLifecycleCallbacks(app: Application) {
        app.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityCreated(activity: Activity, state: Bundle?) {
                event("activity_created ${activity.javaClass.simpleName}")
            }

            override fun onActivityResumed(activity: Activity) {
                event("activity_resumed ${activity.javaClass.simpleName} ${memorySummary()}")
            }

            override fun onActivityPaused(activity: Activity) {
                event("activity_paused ${activity.javaClass.simpleName}")
            }

            override fun onActivityDestroyed(activity: Activity) {
                event("activity_destroyed ${activity.javaClass.simpleName} finishing=${activity.isFinishing}")
            }

            override fun onActivityStarted(activity: Activity) = Unit
            override fun onActivityStopped(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) = Unit
        })
    }

    private fun appendEvent(message: String) {
        runCatching {
            synchronized(lock) {
                diagnosticsDir.mkdirs()
                if (eventLog.isFile && eventLog.length() > MAX_EVENT_BYTES) {
                    val bytes = eventLog.readBytes()
                    val start = (bytes.size - MAX_EVENT_BYTES / 2).coerceAtLeast(0).toInt()
                    eventLog.writeBytes(bytes.copyOfRange(start, bytes.size))
                }
                eventLog.appendText("${now()} $message\n")
            }
        }
    }

    private fun memorySummary(): String {
        val runtime = Runtime.getRuntime()
        val javaUsed = runtime.totalMemory() - runtime.freeMemory()
        return "memory java_used_mb=${javaUsed / 1048576} " +
            "java_max_mb=${runtime.maxMemory() / 1048576} " +
            "native_mb=${Debug.getNativeHeapAllocatedSize() / 1048576}"
    }

    private fun startLocalServer() {
        thread(name = "PrippiDiagnosticsServer", isDaemon = true) {
            runCatching {
                ServerSocket().use { server ->
                    server.reuseAddress = true
                    server.bind(InetSocketAddress(PORT))
                    appendEvent("diagnostics_server listening=$PORT")
                    while (!server.isClosed) {
                        val socket = server.accept()
                        runCatching { handleClient(socket) }
                            .onFailure { appendEvent("diagnostics_client_error ${it.message}") }
                    }
                }
            }.onFailure {
                appendEvent("diagnostics_server_error ${it.javaClass.simpleName}: ${it.message}")
            }
        }
    }

    private fun handleClient(socket: Socket) {
        socket.use { client ->
            client.soTimeout = 3_000
            val requestLine = readLimitedRequestLine(client)
            val path = requestLine.split(' ').getOrNull(1).orEmpty()
            val (status, body) = when (path.substringBefore('?')) {
                "/health" -> "200 OK" to "ok ${BuildConfig.VERSION_NAME}\n"
                "/diagnostics" -> "200 OK" to report()
                else -> "404 Not Found" to "Use /health or /diagnostics\n"
            }
            val payload = body.toByteArray(StandardCharsets.UTF_8)
            val output = client.getOutputStream()
            output.write(
                (
                    "HTTP/1.1 $status\r\n" +
                        "Content-Type: text/plain; charset=utf-8\r\n" +
                        "Content-Length: ${payload.size}\r\n" +
                        "Connection: close\r\n\r\n"
                    ).toByteArray(StandardCharsets.US_ASCII),
            )
            output.write(payload)
            output.flush()
        }
    }

    private fun readLimitedRequestLine(client: Socket, maxBytes: Int = 4_096): String {
        val input = client.getInputStream()
        val buffer = ByteArray(maxBytes)
        var count = 0
        while (count < buffer.size) {
            val value = input.read()
            if (value < 0 || value == '\n'.code) break
            if (value != '\r'.code) buffer[count++] = value.toByte()
        }
        return String(buffer, 0, count, StandardCharsets.US_ASCII)
    }

    private fun tail(file: File, maxChars: Int): String = runCatching {
        if (!file.isFile) return@runCatching ""
        RandomAccessFile(file, "r").use { input ->
            val length = input.length()
            val count = minOf(length, maxChars.toLong()).toInt()
            input.seek(length - count)
            ByteArray(count).also(input::readFully).toString(Charsets.UTF_8)
        }
    }.getOrDefault("")

    private fun stackTrace(throwable: Throwable): String {
        val writer = StringWriter()
        throwable.printStackTrace(PrintWriter(writer))
        return writer.toString()
    }

    private fun now(): String = synchronized(timestamp) { timestamp.format(Date()) }
}

class PrippiApplication : Application(), ImageLoaderFactory {
    private val profile by lazy { DeviceProfile.detect(this) }

    override fun onCreate() {
        super.onCreate()
        AppDiagnostics.install(this)
    }

    override fun newImageLoader(): ImageLoader = ImageLoader.Builder(this)
        .memoryCache {
            MemoryCache.Builder(this)
                .maxSizePercent(if (profile.isLowPower) 0.06 else 0.20)
                .build()
        }
        .diskCache {
            DiskCache.Builder()
                .directory(File(cacheDir, "coil"))
                .maxSizeBytes(if (profile.isLowPower) 64L * 1024 * 1024 else 160L * 1024 * 1024)
                .build()
        }
        .build()

    override fun onTrimMemory(level: Int) {
        AppDiagnostics.trimMemory(level)
        if (level >= TRIM_MEMORY_RUNNING_LOW) {
            runCatching { imageLoader.memoryCache?.clear() }
            AppDiagnostics.event("image_memory_cache_cleared level=$level")
        }
        super.onTrimMemory(level)
    }
}
