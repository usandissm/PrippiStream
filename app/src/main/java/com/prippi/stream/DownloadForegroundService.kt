package com.prippi.stream

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Mantiene vivo il processo mentre il download_manager Python lavora.
 * La coda, il resume e i file restano quelli dell'addon: questo servizio è il
 * solo adattatore di lifecycle/notifica richiesto da Android.
 */
class DownloadForegroundService : Service() {
    private val executor = Executors.newSingleThreadExecutor()
    private val monitoring = AtomicBoolean(false)
    private val networkValidated = AtomicBoolean(false)
    @Volatile private var pythonReady = false
    private lateinit var connectivity: ConnectivityManager

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) = refreshNetworkState()
        override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) =
            publishNetworkState(
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED),
            )
        override fun onLost(network: Network) = refreshNetworkState()
    }

    override fun onCreate() {
        super.onCreate()
        createChannel()
        connectivity = getSystemService(ConnectivityManager::class.java)
        refreshNetworkState()
        connectivity.registerDefaultNetworkCallback(networkCallback)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, notification("Preparazione download", 0, true))
        if (monitoring.compareAndSet(false, true)) {
            val restoreAfterRestart = intent == null || intent.getBooleanExtra(EXTRA_RESTORE, false)
            executor.execute { monitor(restoreAfterRestart) }
        }
        return START_STICKY
    }

    private fun monitor(restoreAfterRestart: Boolean) {
        var first = true
        var idlePolls = 0
        try {
            PythonBridge.start(applicationContext)
            pythonReady = true
            PythonBridge.setDownloadNetworkAvailable(networkValidated.get())
            while (true) {
                val entries = PythonBridge.downloads(resumeInterrupted = first && restoreAfterRestart)
                    .map { DownloadEntry.fromJson(it) }
                first = false
                val active = entries.filter { it.isActive }
                if (active.isEmpty()) {
                    // Piccola finestra: il comando UI che accoda/riprende e il
                    // servizio possono partire nello stesso istante.
                    idlePolls++
                    if (idlePolls >= 3) break
                } else {
                    idlePolls = 0
                    val current = active.firstOrNull { it.status == "downloading" } ?: active.first()
                    val label = when (current.status) {
                        "queued" -> "In coda: ${current.displayTitle}"
                        "waiting_network" -> "In attesa della rete · ${current.displayTitle}"
                        else -> "${current.displayTitle} · ${current.progress.toInt()}%"
                    }
                    val average = active.map { it.progress }.average().toInt().coerceIn(0, 100)
                    val indeterminate = active.all { it.progress <= 0f }
                    (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(
                        NOTIFICATION_ID,
                        notification(label, average, indeterminate),
                    )
                }
                Thread.sleep(2_000)
            }
        } catch (error: Exception) {
            android.util.Log.e("Prippi", "Monitor download in background", error)
        } finally {
            pythonReady = false
            monitoring.set(false)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun refreshNetworkState() {
        val network = connectivity.activeNetwork
        val capabilities = network?.let(connectivity::getNetworkCapabilities)
        publishNetworkState(
            capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true,
        )
    }

    private fun publishNetworkState(validated: Boolean) {
        networkValidated.set(validated)
        if (pythonReady) {
            runCatching { PythonBridge.setDownloadNetworkAvailable(validated) }
                .onFailure {
                    android.util.Log.e("Prippi", "Aggiornamento stato rete download", it)
                }
        }
    }

    private fun notification(text: String, progress: Int, indeterminate: Boolean) =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("PrippiStream · Download")
            .setContentText(text)
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .setProgress(100, progress, indeterminate)
            .setContentIntent(
                PendingIntent.getActivity(
                    this,
                    0,
                    Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                ),
            )
            .build()

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Download offline",
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = "Avanzamento dei download PrippiStream" }
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        runCatching { connectivity.unregisterNetworkCallback(networkCallback) }
        executor.shutdownNow()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL_ID = "prippi_downloads"
        private const val NOTIFICATION_ID = 2102
        private const val EXTRA_RESTORE = "restore"

        fun start(context: Context, restoreInterrupted: Boolean = false) {
            ContextCompat.startForegroundService(
                context,
                Intent(context, DownloadForegroundService::class.java)
                    .putExtra(EXTRA_RESTORE, restoreInterrupted),
            )
        }
    }
}
