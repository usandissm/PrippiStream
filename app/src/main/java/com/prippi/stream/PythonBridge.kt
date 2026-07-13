package com.prippi.stream

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject

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
        val dataDir = context.filesDir.absolutePath          // storage privato scrivibile
        // runtime_dir = null → bridge usa la cartella 'engine' impacchettata da Chaquopy
        bridge.callAttr("init", null, dataDir, null)
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
