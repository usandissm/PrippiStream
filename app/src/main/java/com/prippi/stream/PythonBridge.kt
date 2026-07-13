package com.prippi.stream

import android.content.Context
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

    /** Da chiamare una volta in Application/MainActivity.onCreate(). */
    fun start(context: Context) {
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        // I file-DATI del motore (settings.xml, channels.json, i vari *.json) sono
        // spediti come asset e vanno copiati su un percorso reale del filesystem:
        // Chaquopy mette i .py in una sua cartella ma NON i file-dati leggibili con open().
        val runtimeDir = File(context.filesDir, "pydata")
        copyAssetDir(context, "pydata", runtimeDir)

        val dataDir = context.filesDir.absolutePath          // storage privato scrivibile
        // runtime_dir = cartella dati copiata; import dei .py da Chaquopy (sys.path nel bridge).
        bridge.callAttr("init", runtimeDir.absolutePath, dataDir, null)
    }

    /** Copia ricorsiva assets/<assetPath> -> destDir (una volta; ricopia se cambia versione). */
    private fun copyAssetDir(context: Context, assetPath: String, destDir: File) {
        val am = context.assets
        val children = try { am.list(assetPath) } catch (e: Exception) { null }
        if (children.isNullOrEmpty()) {
            // È un file: copialo.
            try {
                destDir.parentFile?.mkdirs()
                am.open(assetPath).use { input ->
                    destDir.outputStream().use { output -> input.copyTo(output) }
                }
            } catch (e: Exception) { /* non è un file o già copiato */ }
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

    /** Chiama un metodo del canale con un item (episodios / findvideos / browse …). */
    fun channelCall(channel: String, method: String, item: JSONObject): List<JSONObject> =
        toList(bridge.callAttr("call_json", channel, method, item.toString(), null).toString())

    /** Item riproducibile → dati per il player nativo. */
    fun resolve(item: JSONObject): JSONObject =
        JSONObject(bridge.callAttr("resolve_json", item.toString()).toString())

    private fun toList(json: String): List<JSONObject> {
        val arr = JSONArray(json)
        return (0 until arr.length()).map { arr.getJSONObject(it) }
    }
}
