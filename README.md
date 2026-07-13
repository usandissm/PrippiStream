# PrippiStream — App Android (APK sideload)

App Android nativa touch che **riusa il motore Python** di PrippiStream (scraping/resolver/
download) via **Chaquopy**, con UI **Compose** e player **Media3/ExoPlayer**. Non va su store:
installazione manuale.

## Stato: MVP verticale (StreamingCommunity: cerca → episodi → riproduci)

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
  sync_engine.py     (TODO) risincronizza engine/ da PrippiStream-v2
```

### Build (Android Studio)
1. Apri la cartella in Android Studio (Giraffe+). Adegua le versioni in
   `build.gradle.kts`/`app/build.gradle.kts` a quelle installate (AGP/Kotlin/Compose/Chaquopy/Media3).
2. Serve un JDK 17 e l'NDK (Chaquopy lo richiede).
3. `Run` sull'A16 (sideload) oppure `./gradlew assembleDebug` → APK in `app/build/outputs/apk/`.

### Regola motore
Il motore si modifica in **PrippiStream-v2**, poi si **risincronizza** qui (`tools/sync_engine.py`).
Non fare fork del motore nell'app.

### Prossimi passi (dopo l'MVP)
Home a righe · tutti i canali VOD · live (ClearKey) · download in background (pycryptodome
= veloce) · impostazioni. Piano completo: `.claude/plans/apk-android-piano.md`.
