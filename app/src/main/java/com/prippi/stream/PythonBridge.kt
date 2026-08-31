package com.prippi.stream

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Ponte verso il MOTORE Python (bridge.py) via Chaquopy.
 * Espone search / episodios / findvideos / resolve come chiamate Kotlin.
 * Tutto passa come JSON (l'engine ritorna dict serializzabili).
 */
object PythonBridge {

    private val py: Python by lazy { Python.getInstance() }
    private val bridge by lazy { py.getModule("bridge") }
    @Volatile private var initialized = false
    private const val PAYLOAD_MARKER = ".prippi-payload-version"

    /** Da chiamare una volta in Application/MainActivity.onCreate(). */
    @Synchronized
    fun start(context: Context) {
        if (initialized) return
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        // I file-DATI del motore (settings.xml, channels.json, i vari *.json) sono
        // spediti come asset e vanno copiati su un percorso reale del filesystem:
        // Chaquopy mette i .py in una sua cartella ma NON i file-dati leggibili con open().
        val runtimeDir = File(context.filesDir, "pydata")
        ensureRuntimePayload(context, runtimeDir)

        val dataDir = context.filesDir.absolutePath          // storage privato scrivibile
        // runtime_dir = cartella dati copiata; import dei .py da Chaquopy (sys.path nel bridge).
        bridge.callAttr("init", runtimeDir.absolutePath, dataDir, null)
        initialized = true
    }

    /** Anticipa il cold start senza occupare il main thread dell'Activity. */
    fun prewarm(context: Context) {
        if (initialized) return
        Thread({
            runCatching { start(context.applicationContext) }
                .onFailure { android.util.Log.e("Prippi", "Prewarm motore Python", it) }
        }, "PrippiEnginePrewarm").apply {
            isDaemon = true
            start()
        }
    }

    fun setDeviceProfile(profile: DeviceProfile) {
        bridge.callAttr(
            "set_device_profile",
            profile.isLowPower,
            profile.isTelevision,
        )
    }

    private fun ensureRuntimePayload(context: Context, runtimeDir: File) {
        val expectedVersion = BuildConfig.VERSION_CODE.toString()
        val currentVersion = runCatching {
            File(runtimeDir, PAYLOAD_MARKER).readText(Charsets.UTF_8).trim()
        }.getOrDefault("")
        if (currentVersion == expectedVersion) return

        val staging = File(context.filesDir, "pydata-installing")
        val backup = File(context.filesDir, "pydata-previous")
        staging.deleteRecursively()
        copyAssetDir(context, "pydata", staging)
        File(staging, PAYLOAD_MARKER).writeText(expectedVersion, Charsets.UTF_8)

        backup.deleteRecursively()
        if (runtimeDir.exists() && !runtimeDir.renameTo(backup)) {
            staging.deleteRecursively()
            error("Impossibile preparare l'aggiornamento del motore")
        }
        if (!staging.renameTo(runtimeDir)) {
            if (backup.exists()) backup.renameTo(runtimeDir)
            staging.deleteRecursively()
            error("Impossibile attivare il nuovo motore")
        }
        backup.deleteRecursively()
    }

    /** Copia ricorsiva assets/<assetPath> -> destDir nello staging atomico. */
    private fun copyAssetDir(context: Context, assetPath: String, destDir: File) {
        val am = context.assets
        val children = try {
            am.list(assetPath)
        } catch (error: Exception) {
            android.util.Log.e("Prippi", "Impossibile elencare asset $assetPath", error)
            throw error
        }
        if (children.isNullOrEmpty()) {
            // È un file: copialo.
            try {
                destDir.parentFile?.mkdirs()
                am.open(assetPath).use { input ->
                    destDir.outputStream().use { output -> input.copyTo(output) }
                }
            } catch (error: Exception) {
                android.util.Log.e("Prippi", "Impossibile copiare asset $assetPath", error)
                throw error
            }
            return
        }
        destDir.mkdirs()
        for (child in children) {
            copyAssetDir(context, "$assetPath/$child", File(destDir, child))
        }
    }

    /** Ricerca su un canale (MVP: streamingcommunity). */
    fun search(channel: String, query: String): List<JSONObject> =
        toList(bridge.callAttr("call_json", channel, "search", "{}", query).toString())

    fun globalSearch(query: String): List<JSONObject> =
        toList(bridge.callAttr("global_search_json", query, 18).toString())

    fun searchHistory(action: String = "load", query: String = ""): List<String> {
        val array = JSONArray(bridge.callAttr("search_history_json", action, query).toString())
        return (0 until array.length()).map { array.getString(it) }
    }

    /** Righe iniziali della Home nativa. */
    fun home(): List<JSONObject> =
        toList(bridge.callAttr("home_json").toString())

    fun liveRows(): List<JSONObject> =
        toList(bridge.callAttr("live_rows_json").toString())

    fun refreshScDomain(): JSONObject =
        JSONObject(bridge.callAttr("refresh_sc_domain_json").toString())

    fun detailMetadata(item: JSONObject): JSONObject =
        JSONObject(bridge.callAttr("detail_metadata_json", item.toString()).toString())

    fun playbackPolicyOptions(): JSONObject =
        JSONObject(bridge.callAttr("playback_policy_options_json").toString())

    /** Tutti i canali attivi dichiarati dalla v2, eventualmente filtrati per categoria. */
    fun channelCatalog(category: String? = null): List<JSONObject> =
        toList(bridge.callAttr("channel_catalog_json", category).toString())

    fun channelMethods(channel: String): Set<String> {
        val array = JSONArray(bridge.callAttr("channel_methods_json", channel).toString())
        return (0 until array.length()).mapTo(linkedSetOf()) { array.optString(it) }
    }

    fun browseMacros(): List<JSONObject> =
        toList(bridge.callAttr("browse_macros_json").toString())

    fun browseMacroCall(item: JSONObject): List<JSONObject> =
        toList(bridge.callAttr("browse_macro_call_json", item.toString()).toString())

    /** Schema e valori correnti delle impostazioni visibili dell'addon. */
    fun settingsSchema(): List<JSONObject> =
        toList(bridge.callAttr("settings_schema_json").toString())

    fun setSetting(id: String, value: Any, channel: String = "") {
        bridge.callAttr("set_setting_json", id, value, channel)
    }

    /** Coda e libreria offline gestite dal download_manager dell'addon 2.0. */
    fun downloads(resumeInterrupted: Boolean = false): List<JSONObject> =
        toList(bridge.callAttr("downloads_list_json", resumeInterrupted).toString())

    fun setDownloadNetworkAvailable(available: Boolean) {
        bridge.callAttr("download_network_state_json", available)
    }

    fun syncDownloadNetwork(context: Context): Boolean {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val network = manager?.activeNetwork
        val capabilities = network?.let(manager::getNetworkCapabilities)
        val validated =
            capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true
        setDownloadNetworkAvailable(validated)
        return validated
    }

    fun enqueueDownload(item: JSONObject, targetHeight: Int = 0): JSONObject =
        JSONObject(bridge.callAttr("download_enqueue_json", item.toString(), targetHeight).toString())

    fun enqueueResolvedDownload(
        item: JSONObject,
        mediaUrl: String,
        headers: Map<String, String>,
        targetHeight: Int = 0,
        subtitleUrls: List<String> = emptyList(),
    ): JSONObject = JSONObject(
        bridge.callAttr(
            "download_enqueue_resolved_json",
            item.toString(),
            mediaUrl,
            JSONObject(headers).toString(),
            targetHeight,
            org.json.JSONArray(subtitleUrls).toString(),
        ).toString(),
    )

    fun pauseDownload(key: String) {
        bridge.callAttr("download_pause_json", key)
    }

    fun resumeDownload(key: String) {
        bridge.callAttr("download_resume_json", key)
    }

    fun removeDownload(key: String) {
        bridge.callAttr("download_remove_json", key)
    }

    fun downloadPlayback(key: String): JSONObject =
        JSONObject(bridge.callAttr("download_playback_json", key).toString())

    /** Chiama un metodo del canale con un item (episodios / findvideos / browse …). */
    fun channelCall(channel: String, method: String, item: JSONObject): List<JSONObject> =
        toList(bridge.callAttr("call_json", channel, method, item.toString(), null).toString())

    /** Espande ricorsivamente stagioni/sottomenu ufficiali in episodi nativi. */
    fun seriesEpisodes(item: JSONObject): List<JSONObject> =
        toList(bridge.callAttr("series_episodes_json", item.toString()).toString())

    /** Item riproducibile → dati per il player nativo. */
    fun resolve(item: JSONObject): JSONObject =
        JSONObject(bridge.callAttr("resolve_json", item.toString()).toString())

    fun resolve4k(item: JSONObject): JSONObject =
        JSONObject(bridge.callAttr("resolve_4k_json", item.toString()).toString())

    fun fhdFor4k(item: JSONObject): JSONObject =
        JSONObject(bridge.callAttr("fhd_for_4k_json", item.toString()).toString())

    fun trailerUrl(item: JSONObject): String =
        JSONArray("[${bridge.callAttr("trailer_url_json", item.toString())}]").getString(0)

    fun trailerUrls(item: JSONObject): List<String> {
        val values = JSONArray(bridge.callAttr("trailer_urls_json", item.toString()).toString())
        return (0 until values.length()).map(values::getString)
    }

    private fun toList(json: String): List<JSONObject> {
        val arr = JSONArray(json)
        return (0 until arr.length()).map { arr.getJSONObject(it) }
    }
}
