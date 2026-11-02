package com.prippi.stream

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.border
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
private fun ProfileButton(label: String, enabled: Boolean = true, first: FocusRequester? = null, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Button(onClick = onClick, enabled = enabled,
        modifier = Modifier.fillMaxWidth().then(if (first != null) Modifier.focusRequester(first) else Modifier)
            .onFocusChanged { focused = it.hasFocus }
            .border(if (focused) 3.dp else 0.dp, if (focused) Color.White else Color.Transparent, RoundedCornerShape(24.dp)),
        colors = ButtonDefaults.buttonColors(containerColor = if (focused) Color.White else Color(0xFFB30A2F),
            contentColor = if (focused) Color.Black else Color.White)) { Text(label) }
}

@Composable
internal fun ProfileAccessDialog(currentName: String, busy: Boolean, error: String?,
    onSelect: (String, String) -> Unit, onLocal: () -> Unit, onDismiss: () -> Unit, onboarding: Boolean = false) {
    var step by rememberSaveable { mutableStateOf("choose") }
    var draft by rememberSaveable { mutableStateOf(currentName) }
    var submitted by rememberSaveable { mutableStateOf(false) }
    val first = remember { FocusRequester() }
    LaunchedEffect(step) { runCatching { first.requestFocus() } }
    LaunchedEffect(busy) { if (submitted && !busy && error == null) onDismiss() }
    AlertDialog(
        onDismissRequest = { if (!busy && !onboarding) onDismiss() },
        title = { Text(if (step == "create") "Crea il tuo profilo" else if (step == "join") "Accedi al tuo profilo" else "Il tuo profilo PrippiStream") },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Un solo nome per ritrovare i tuoi Continua a guardare su telefono, TV e Kodi.")
            if (step == "choose") {
                ProfileButton("Ho già un profilo", !busy, first) { step = "join"; draft = currentName }
                ProfileButton("Crea un profilo", !busy) { step = "create"; draft = "" }
                ProfileButton("Solo su questo dispositivo", !busy) { submitted = true; onLocal() }
            } else {
                Text(if (step == "create") "Scegli un nome univoco, non già utilizzato. Lo userai anche sugli altri dispositivi."
                    else "Inserisci il nome del profilo già creato. I CW locali verranno uniti, mantenendo gli episodi più avanzati.")
                OutlinedTextField(value = draft, onValueChange = { draft = it.take(40); submitted = false },
                    modifier = Modifier.focusRequester(first), enabled = !busy, singleLine = true, label = { Text("Nome profilo") })
                Text("Senza password: chi conosce il nome può accedere ai CW. Non usare dati personali.", style = MaterialTheme.typography.bodySmall)
                if (step == "create") Text("I CW attuali verranno copiati nel nuovo profilo.", style = MaterialTheme.typography.bodySmall)
            }
            if (submitted && error != null) Text(error, color = MaterialTheme.colorScheme.error)
            if (busy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Collegamento del profilo…") }
        } },
        confirmButton = { if (step != "choose") ProfileButton(if (step == "create") "Crea profilo" else "Accedi",
            !busy && draft.trim().length >= 2) { submitted = true; onSelect(draft, step) } },
        dismissButton = { if (step != "choose") TextButton(enabled = !busy, onClick = { step = "choose"; submitted = false }) { Text("Indietro") }
            else if (!onboarding) TextButton(enabled = !busy, onClick = onDismiss) { Text("Annulla") } },
    )
}

@Composable
internal fun ProfilePanel(name: String, status: String, busy: Boolean, onSelect: (String, String) -> Unit,
    television: Boolean, error: String?) {
    var editing by rememberSaveable { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth().padding(vertical = 12.dp, horizontal = if (television) 0.dp else 16.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Profilo · Continua a guardare", style = MaterialTheme.typography.titleMedium)
            Text(if (name.isBlank()) "Solo questo dispositivo" else "Profilo: $name")
            Text(status, style = MaterialTheme.typography.bodySmall)
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            ProfileButton(if (name.isBlank()) "Collega un profilo" else "Cambia profilo", !busy) { editing = true }
        }
    }
    if (editing) ProfileAccessDialog(name, busy, error, onSelect,
        onLocal = { onSelect("", "auto") }, onDismiss = { editing = false })
}
