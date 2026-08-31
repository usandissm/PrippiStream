# PrippiStream — App Android (APK sideload)

Unica app Android nativa PrippiStream per telefono, tablet, Android TV,
Google TV e box. Riusa il motore Python dell'addon via **Chaquopy**, con UI
**Compose** adattiva e player **Media3/ExoPlayer**. Distribuzione tramite
sideload e aggiornamento firmato in-place.

## Stato: 0.9.11 adattiva ARM32+ARM64 in validazione sulla box reale

La stessa app include Home, Sfoglia, ricerca globale, dettaglio, episodi,
player, SKY/Sport/TV, zapping, download e aggiornamento su telefono, tablet e
TV. La UI salotto aggiunge launcher Leanback, focus D-pad persistente,
MediaSession, layout adattivo, profilo low-power e preview trailer protetta da
soglia RAM. La release universale include ARM32 e ARM64. La 0.9.11 mostra la
Home nativa dallo snapshot prima di avviare Python, protegge il primo paint sui
box lenti, invia la diagnostica a Telegram con coda e fallback manuale e usa lo
stesso registro remoto validato di siti/domìni dell'addon Kodi.
Sulla box H313 sono stati verificati avvio ARM32, Home/D-pad, Live/audio,
playback SC reale e una sessione 0.9.11 superiore a 71 minuti senza nuovi
crash o ANR; restano stress D-pad, download e updater. Kodi
rimane temporaneamente disponibile come fallback.

La candidate locale include inoltre CW canonico per serie e coda episodi su
tutte le stagioni. Audio e sottotitoli scelti nel player vengono conservati per
il singolo film oppure per l'intera serie, inclusa la scelta sottotitoli OFF, e
riapplicati automaticamente agli episodi successivi. I canali live sono esclusi
da questa persistenza.

L'app partecipa alla stessa finestra di rilascio dell'addon Kodi 2.0. Le
milestone prodotto comuni e il gate ZIP+APK sono definiti nel master
`PrippiStream-v2/PROJECT_STATUS.md`; i pacchetti M0–M8 di `APP_ROADMAP.md`
restano il dettaglio tecnico dell'app.

### ✅ Fatto e VERIFICATO sul PC (senza Android)
Il motore gira headless dietro gli shim `xbmc_shim/`. Prova end-to-end:
```
py tools/test_headless.py "the office"
# search → 21 risultati · episodios → 193 episodi · findvideos → sorgente
# resolve → https://vixcloud.cc/playlist/...  (manifest=hls, audio=it)  ← URL riproducibile
```

### Struttura
```
app/src/main/python/
  bridge.py          facade Kotlin↔motore (search/channel_call/resolve, JSON in/out)
  engine/            MOTORE copiato da PrippiStream-v2 (channels, servers, core, lib, *.json)
  xbmc_shim/         stub xbmc/xbmcaddon/xbmcvfs/xbmcgui/xbmcplugin + prippi_env (path)
app/src/main/java/com/prippi/stream/
  PythonBridge.kt    avvia Chaquopy e chiama bridge.py
  MainActivity.kt    UI Compose: ricerca → lista → drill-down → Play
  PlayerActivity.kt  Media3: HLS/DASH + header + traccia audio ITA
tools/
  test_headless.py   prova il motore sul PC (nessun Android richiesto)
  sync_engine.py     confronta/sincronizza engine/ da PrippiStream-v2
```

La checklist completa è in [`APP_ROADMAP.md`](APP_ROADMAP.md); il passaggio
operativo per la nuova chat TV è in [`TV_APP_HANDOFF.md`](TV_APP_HANDOFF.md).

### Sincronizzazione motore

```powershell
# Anteprima: non modifica file
python tools/sync_engine.py

# Controllo per script/CI: exit code 1 se le copie divergono
python tools/sync_engine.py --check

# Applica soltanto da una sorgente Git pulita
python tools/sync_engine.py --apply
```

Il manifest `tools/engine_sync_manifest.json` definisce esplicitamente codice e
asset gestiti. Bridge Android, shim Kodi e UI nativa non vengono toccati.

### Build (Android Studio)
1. Apri la cartella in Android Studio (Giraffe+). Adegua le versioni in
   `build.gradle.kts`/`app/build.gradle.kts` a quelle installate (AGP/Kotlin/Compose/Chaquopy/Media3).
2. Serve un JDK 17 e l'NDK (Chaquopy lo richiede).
3. `Run` sull'A16 (sideload) oppure `./gradlew assembleDebug` → APK in `app/build/outputs/apk/`.

La release pubblica non è stata aggiornata. La candidate locale 0.9.11 è firmata
e include `armeabi-v7a` e `arm64-v8a`, launcher Leanback dedicato, profilo
low-power e selezione ABI nell'updater. Il gate ancora aperto è l'installazione
e la matrice funzionale sulla box reale. Il controllo contro la v2 1.9.988
segnala ancora divergenze del payload: prima della RC combinata serviranno
sincronizzazione autorizzata da una sorgente validata, nuova APK e regressione.

### Regola motore
Il motore si modifica in **PrippiStream-v2**, poi si **risincronizza** qui (`tools/sync_engine.py`).
Non fare fork del motore nell'app.

### Prossimi passi

Validazione della 0.9.11 sulla box H313 → completare misure cold/warm, RAM,
frame e focus → matrice VOD/live/download/updater → regressione breve su
telefono e tablet/emulatore → confronto con Kodi 1.9.988 sulla stessa box →
gate combinato di rilascio.
