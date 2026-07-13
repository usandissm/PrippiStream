package com.prippi.stream

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

// MVP verticale: Cerca su StreamingCommunity → episodi → Play (player nativo).
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PythonBridge.start(applicationContext)
        setContent { MaterialTheme { Screen() } }
    }
}

private const val CH = "streamingcommunity"

private fun clean(s: String?): String =
    (s ?: "").replace(Regex("\\[/?(B|I|COLOR[^\\]]*)\\]"), "").trim()

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Screen() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("the office") }
    var items by remember { mutableStateOf(listOf<JSONObject>()) }
    var loading by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("") }

    fun run(block: suspend () -> Unit) {
        scope.launch {
            loading = true; status = ""
            try {
                block()
            } catch (e: Exception) {
                // Logga l'errore COMPLETO (con traceback Python di Chaquopy) in Logcat,
                // tag "Prippi", così è visibile filtrando i log.
                android.util.Log.e("Prippi", "errore chiamata motore", e)
                status = "Errore: ${e.message}"
            }
            loading = false
        }
    }

    Column(Modifier.fillMaxSize().padding(12.dp)) {
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            OutlinedTextField(
                value = query, onValueChange = { query = it },
                label = { Text("Cerca") }, modifier = Modifier.weight(1f)
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = {
                run { items = withContext(Dispatchers.IO) { PythonBridge.search(CH, query) } }
            }) { Text("Vai") }
        }
        Spacer(Modifier.height(8.dp))
        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (status.isNotEmpty()) Text(status, color = MaterialTheme.colorScheme.error)

        LazyColumn(Modifier.fillMaxSize()) {
            items(items) { it ->
                val title = clean(it.optString("title").ifEmpty { it.optString("fulltitle") })
                val action = it.optString("action")
                ListItem(
                    headlineContent = { Text(title) },
                    supportingContent = { Text(action) },
                    modifier = Modifier.clickable {
                        when (action) {
                            "episodios", "seasons", "get_seasons" ->
                                run { items = withContext(Dispatchers.IO) { PythonBridge.channelCall(CH, "episodios", it) } }
                            else -> // findvideos → resolve → play
                                run {
                                    val play = withContext(Dispatchers.IO) {
                                        val srcs = PythonBridge.channelCall(CH, "findvideos", it)
                                        if (srcs.isNotEmpty()) PythonBridge.resolve(srcs[0]) else null
                                    }
                                    if (play != null) {
                                        ctx.startActivity(Intent(ctx, PlayerActivity::class.java).apply {
                                            putExtra("url", play.optString("url"))
                                            putExtra("manifest", play.optString("manifest_type"))
                                            putExtra("audio", play.optString("audio_language"))
                                            putExtra("headers", play.optJSONObject("headers")?.toString() ?: "{}")
                                        })
                                    } else status = "Nessuna sorgente."
                                }
                        }
                    }
                )
                HorizontalDivider()
            }
        }
    }
}
