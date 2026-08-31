# PrippiStream App — checklist operativa

> Ultimo aggiornamento: 28 luglio 2026  
> Obiettivo: mantenere una sola app PrippiStream installabile su telefono,
> tablet, Android TV, Google TV e box Android, con UI touch e TV adattive e un
> solo motore Python autoritativo.

> Le sigle interne M0–M8 di questo file descrivono i pacchetti di sviluppo
> dell'app. Le milestone di prodotto autoritative, comuni ad addon e app, sono
> definite in `PrippiStream-v2/PROJECT_STATUS.md`.

## Decisione prodotto approvata — 26 luglio 2026

- Non verrà creata una seconda app TV: si evolve l'app esistente, conservando
  package `com.prippi.stream`, firma, dati, download e aggiornamenti in-place.
- Telefono e tablet mantengono l'esperienza touch.
- TV e box ricevono un'esperienza da salotto specifica, interamente navigabile
  con D-pad e telecomando.
- Kodi resta un fallback temporaneo finché la stessa box non supera la matrice
  funzionale e prestazionale dell'app nativa.
- Il motore condiviso continua a essere modificato in `PrippiStream-v2` e poi
  sincronizzato nell'app con la procedura esistente.
- Kodi 2.0 e la prima app adattiva partecipano alla stessa finestra di rilascio;
  la Milestone 2 prodotto e il gate RC si chiudono soltanto quando sono verdi
  sia la matrice Kodi sia quella app.

## Mappatura sulle milestone prodotto

| Milestone prodotto | Responsabilità dell'app |
|---|---|
| M0 Stabilizzazione | Baseline mobile 0.8.9 e correzioni adattive 0.9.x |
| M1 Fondamenta | Sync motore, Chaquopy, ABI, package/firma e separazione UI |
| M2 Prestazioni | Snapshot-first, Python post-frame, low-power, RAM/focus box |
| Gate RC | APK firmata, motore identificato, audit, update e regressione mobile/TV |
| M3 Affidabilità | Lifecycle, coroutine/WorkManager/Media3, download, cache e diagnostica |
| M4 Licenze | Stessa identità/protocollo Kodi, storage Android e UI touch/TV |
| M5 Protezione | Loader Chaquopy, Python 3.11, ARM32/ARM64 e payload autenticato |
| M6 Distribuzione | CI APK, firma, updater ABI-aware, registro e feed firmati |
| M7 Consolidamento | Dispositivi reali, accessibilità e parità documentata |
| M8 Evoluzione | Funzioni future comuni o specifiche dell'app |

Lo stato 0.9.9 non chiude da solo il gate prodotto: restano il test fisico sulla
box H313, una regressione breve mobile/tablet e il confronto con Kodi sulla
stessa box. Inoltre il controllo del 28 luglio contro la v2 1.9.986 sporca
rileva +1/~7 file motore e ~1 asset divergenti: la 0.9.9 corrente è una
candidate funzionale pre-sync, non ancora l'APK della coppia RC finale.

## Stato di partenza

- [x] Baseline pubblicata: 0.8.9, `versionCode 54`, package
  `com.prippi.stream`, APK ARM64 firmato.
- [x] Progetto Android nativo compilabile (Gradle 8.7, Kotlin 1.9.24, Compose).
- [x] Motore Python eseguito tramite Chaquopy.
- [x] Shim Kodi per l'esecuzione headless.
- [x] Ricerca StreamingCommunity.
- [x] Navigazione serie → episodi.
- [x] Risoluzione sorgente e riproduzione HLS con Media3.
- [x] MVP verificato su Samsung A16.
- [x] Parità mobile sostanziale con Kodi per Home, Sfoglia, ricerca, VOD, live,
  zapping, download, impostazioni e aggiornamenti.
- [ ] Parità TV con D-pad/telecomando e prestazioni validate sulla box.

## Regole di sviluppo

- Il motore autoritativo resta `PrippiStream-v2`.
- L'APK contiene una copia sincronizzata, mai modificata manualmente.
- Una sincronizzazione da una working tree v2 sporca deve essere esplicitamente
  autorizzata.
- UI, bridge Android, shim e player restano sorgenti native dell'APK e non
  vengono sovrascritti dalla sincronizzazione.
- Ogni milestone termina con test headless, build APK e prova sul dispositivo
  quando la funzionalità richiede Android reale.
- L'adattamento TV non deve trasformare la UI mobile in una schermata
  semplicemente ingrandita: focus, navigazione, OSD e ripristino posizione sono
  responsabilità specifiche del profilo TV.

## M0 — Fondamenta e sincronizzazione

- [x] Definire la roadmap dell'app.
- [x] Creare il manifest esplicito del payload motore.
- [x] Implementare `tools/sync_engine.py` con modalità check e apply.
- [x] Generare separatamente gli asset dati richiesti a runtime.
- [x] Implementare la registrazione di versione e commit della sorgente.
- [x] Aggiungere un controllo automatico contro divergenze accidentali.
- [x] Verificare anteprima e rifiuto sicuro di una sorgente Git sporca.
- [x] Eseguire la prima sincronizzazione completa dalla v2 (1.9.963).
- [x] Verificare test headless e build APK dopo la prima sincronizzazione.
- [x] Preservare l'adattatore Android `platformtools.py` durante il sync.
- [x] Sincronizzare anche le traduzioni italiane usate dai menu canale.

**Gate:** il motore può essere confrontato e aggiornato in modo ripetibile,
senza toccare bridge, shim o UI Android.

## M1 — Struttura app e Home nativa

- [x] Introdurre modelli Kotlin per contenuti, righe e stato UI.
- [x] Separare repository/ViewModel dalla UI Compose.
- [x] Creare la prima Home a righe orizzontali touch-first.
- [x] Aggiungere righe Film, Serie TV, Anime e K-Drama.
- [x] Gestire loading, empty state, errori e retry per singola riga.
- [x] Caricare poster e backdrop con placeholder coerenti.
- [x] Aggiungere navigazione Home → dettaglio → episodi → player.
- [x] Conservare correttamente lo stato tornando dal player.
- [x] Aggiungere navigazione inferiore Home / Sfoglia / Live / Download / Impostazioni.
- [x] Esporre il catalogo completo dei canali v2 e i menu ricorsivi.
- [x] Esporre le macro Sfoglia Film / Serie / K-Drama / Anime / Hentai e i relativi generi.
- [x] Conservare i cursori originali di Sfoglia, caricare altre pagine e cambiare ordinamento.

**Gate:** apertura app → Home popolata → dettaglio → playback su Samsung A16.

## M2 — Dettaglio e Continua a guardare

- [x] Creare scheda dettaglio per film e serie.
- [x] Mostrare trama, anno, generi e valutazione.
- [x] Aggiungere selezione stagione ed elenco episodi.
- [x] Salvare posizione, durata e ultimo episodio riprodotto.
- [x] Creare la riga Continua a guardare.
- [x] Implementare riprendi dall'ultima posizione e rimozione dalla cronologia.
- [x] Salvare i dati localmente con schema versionato.

**Gate:** avanzamento persistente dopo chiusura e riapertura dell'app.

## M3 — Ricerca globale e provider VOD

- [x] Trasformare la ricerca MVP in ricerca globale.
- [x] Ricavare dinamicamente i provider dai flag `include_in_global_search` dell'addon.
- [x] Eseguire provider in parallelo con timeout e cancellazione.
- [x] Deduplicare risultati e scegliere l'edizione migliore con le priorità dell'addon.
- [x] Aggiungere filtri Film / Serie / Anime.
- [x] Aggiungere cronologia delle ricerche nella UI con cancellazione.
- [x] Riutilizzare cache provider e cache finale dell'addon.
- [x] Gestire fallback tra sorgenti e messaggi di errore utili.
- [x] Testare un campione stabile di film, serie e anime (HD4Me, SC e AnimeUnity sul Samsung).

**Gate:** ricerca e playback affidabili su più provider senza dipendenze Kodi.

## M4 — Player completo

- [x] Gestire HLS, DASH e file diretti.
- [x] Propagare header, cookie, referer e user-agent.
- [x] Selezionare audio italiano e sottotitoli preferiti.
- [x] Aggiungere selettore qualità, audio e sottotitoli.
- [x] Implementare resume, avanzamento e fine episodio.
- [x] Implementare autoplay dell'episodio successivo.
- [x] Gestire errori Media3 e fallback automatico tra mirror/provider.
- [x] Aggiungere controlli e gesture touch essenziali (doppio tap ±10 secondi).

**Gate:** film e quattro episodi consecutivi senza perdita di lingua o stato.

## M5 — Live SKY / Sport / TV

- [x] Portare catalogo e menu dei provider live.
- [x] Mostrare soltanto sorgenti verificate nella sessione corrente.
- [x] Integrare HLS live con Media3 (Rai 1 provata sul dispositivo).
- [x] Integrare DRM ClearKey (Sky Cinema Uno provato sul dispositivo).
- [x] Aggiungere EPG, ora in onda e programma successivo.
- [x] Implementare cambio canale e zapping rapido.
- [x] Gestire retry, fallback e rimozione dei canali non più disponibili.

**Gate:** campione SKY/Sport/TV riproducibile e zapping stabile sul dispositivo.

## M6 — Download offline

- [x] Riutilizzare database e stati del download dell'addon 2.0.
- [x] Implementare foreground service e notifiche Android (provato con app in background).
- [x] Scaricare HLS con ripresa dopo interruzione (VixCloud provato fino al 100%); dalla 0.7.8 playlist autorizzata acquisita direttamente dal bootstrap WebView, retry 403/410 e stalli transitori con ripresa dal sidecar verificati sul Samsung A16.
- [x] Conservare le tracce audio disponibili; sottotitoli supportati dal motore.
- [x] Gestire cifratura/decrittazione e chiavi locali.
- [x] Gestire eliminazione e pulizia dei bundle e mostrare lo spazio libero.
- [x] Creare schermata I miei download.
- [x] Verificare playback da bundle locale cifrato (H.264 1080p + AAC).
- [x] Validare su dispositivo reale la stabilizzazione VixCloud 0.7.7–0.7.8: tre bootstrap immediati e download completati senza 403, `segment stalled`, retry residui o crash.

**Gate:** download interrotto/ripreso e riproduzione senza rete.

## M7 — Impostazioni, qualità e release

- [x] Aggiungere impostazioni per qualità, lingua, sottotitoli e provider.
- [x] Esporre e salvare le impostazioni specifiche dichiarate dai provider.
- [x] Aggiungere tema scuro, icona e splash screen; restano verifiche accessibilità TV.
- [x] Ridurre dimensione APK e rimuovere file vendor non runtime.
- [x] Gestire log diagnostici e invio log volontario.
- [x] Aggiungere smoke test automatici provider e catalogo canali; resta automazione UI Android.
- [x] Testare più dispositivi/ABI e Android 15 (Samsung A16 ARM64 + Pixel 6 virtuale x86_64): Home, Sfoglia, provider e Impostazioni caricati senza crash.
- [x] Creare firma release e gestione sicura delle chiavi.
- [x] Produrre APK release installabile e procedura di aggiornamento.
- [x] Implementare controllo/download/installazione da GitHub Releases.
- [x] Pubblicare la prima release GitHub con APK firmato (v0.5.2).
- [x] Completare la conferma Play Protect/PIN e verificare l'update reale 0.5.1 → 0.5.2.
- [x] Pubblicare la v0.5.3 e verificare installazione, dati e download conservati.
- [x] Pubblicare la v0.5.4 con propagazione sottotitoli resolver→player→download.
- [x] Pubblicare la v0.5.5 con stati Home/retry e placeholder immagini coerenti.
- [x] Pubblicare la v0.7.6 con loghi SKY/Sport/TV completi e card 2:3 non deformate.
- [x] Installare e validare in-place le v0.7.7 e 0.7.8 con correzioni download VixCloud.
- [x] Usare come icona Android lo stesso artwork ufficiale dell'addon.
- [x] Avviare all'apertura app il sync domini GitHub e il controllo parallelo SKY/Sport/TV.
- [x] Rendere il player immersivo edge-to-edge e nascondere i controlli tracce insieme alla timeline.
- [x] Aggiungere il pulsante Trailer alla scheda dettaglio usando la ricerca/cache dell'addon.

**Gate:** APK firmato, ripetibile, installabile e testato su più dispositivi.

## M8 — App unica adattiva: tablet, Android TV, Google TV e box

### M8.0 — Compatibilità di installazione

- [x] Produrre e verificare staticamente una build `armeabi-v7a` per box ARM 32 bit.
- [x] Verificare le wheel Chaquopy ARM32 di Pillow e PyCryptodome.
- [x] Conservare build ARM64 per telefoni/TV moderni e x86_64 per test.
- [x] Adeguare updater e naming asset per selezionare l'ABI corretta.
- [ ] Installare sulla box H313/Android TV 10 da 2 GB senza rimuovere Kodi.

### M8.1 — Architettura adattiva

- [x] Rilevare TV tramite `UI_MODE_TYPE_TELEVISION`, Leanback e capacità input,
  senza classificare un tablet landscape come TV.
- [x] Introdurre `TvActivity` come entry point Leanback mantenendo
  `MainActivity` per telefono/tablet.
- [x] Condividere `MainViewModel`, repository, modelli, bridge, database,
  cronologia, resolver e player.
- [x] Introdurre un coordinatore lavori per profilo hardware: snapshot → TV →
  SKY → Sport → archivio/anime/enrich.

### M8.2 — UI e telecomando

- [x] Menu laterale TV per Home / Cerca / Sfoglia / Live / Download /
  Impostazioni, separato dalla navigazione inferiore mobile.
- [x] Focus sempre visibile con bordo, scala e contrasto verificati su emulatore TV.
- [x] Navigazione del verticale Home → dettaglio → player con D-pad, Back, OK
  e tasti media; matrice completa delle pagine ancora pendente.
- [x] Ripristinare pagina, riga e card tramite chiavi stabili tornando da
  dettaglio e player.
- [ ] Completare i dialog qualità/audio/sottotitoli con una superficie TV
  nativa; ricerca e shell TV sono già focalizzabili.
- [ ] Conservare touch, gesture e layout responsive su telefono e tablet.

### M8.3 — Player TV

- [x] Integrare MediaSession.
- [x] Adattare player e overlay live alla navigazione D-pad.
- [x] Sostituire il controller mobile su TV con OSD dedicato, Play/Pausa,
  seek VOD, guida Live e azioni focalizzabili.
- [ ] Verificare sulla box Play/Pausa, seek VOD, Back e selezione tracce.
- [x] Conservare zapping circolare con CHANNEL_UP/DOWN e fallback
  PAGE_UP/DOWN/media next/previous.
- [ ] Rendere configurabili i tasti canale non standard.
- [ ] Portare nell'app il retry VOD con nuova risoluzione e token fresco.

### M8.4 — Prestazioni low-power

- [x] Home snapshot-first e navigabile prima dei lavori secondari.
- [x] Limite adattivo di refresh, dimensioni card e worker sulle box lente.
- [x] TV prima di SKY e Sport, serializzati sul profilo low-power.
- [x] Saltare enrich TMDB e ricostruzione indice 4K durante l'avvio low-power.
- [x] Stabilizzare il ripristino focus senza rilanciare scroll/requestFocus a
  ogni movimento del telecomando.
- [x] Limitare cache immagini e crossfade sui dispositivi low-power.
- [x] Salvare crash/eventi in modo persistente ed esporre la diagnostica sulla
  rete locale durante i test box.
- [ ] Misurare cold/warm start, RAM, frame persi e tempi focus sulla box H313.

### M8.5 — Parità e uscita dal fallback Kodi

- [ ] Validare Home, ricerca, Sfoglia, film, episodi, autoplay, lingua e trailer.
- [ ] Validare SKY, Sport, TV, DRM Widevine/ClearKey e zapping.
- [ ] Validare download, aggiornamento in-place e sessioni lunghe.
- [ ] Validare telefono, tablet, Android TV/Google TV, ARM32 e ARM64.
- [ ] Ritirare Kodi come percorso principale soltanto dopo confronto misurato
  sulla stessa box; fino ad allora resta disponibile come fallback.

**Gate:** la stessa app firmata funziona con touch su telefono/tablet e solo
telecomando su TV/box, risultando almeno equivalente a Kodi e più fluida sulla
box low-power reale.

### Gate app per la finestra di rilascio combinata

- [ ] Identificare versioneName/versionCode, revisione motore e SHA-256 APK.
- [ ] Sincronizzare da una v2 validata/autorizzata e ricostruire la candidate;
  non applicare automaticamente da una working tree sporca.
- [ ] Verificare che `sync_engine.py --check` non rilevi divergenze.
- [ ] Superare unit test, lint, invarianti release e controllo ABI/firma.
- [ ] Auditare manifest, permessi, librerie native, dati di backup e segreti.
- [ ] Installare/aggiornare senza perdita di dati su telefono reale.
- [ ] Eseguire regressione touch su telefono e tablet/emulatore.
- [ ] Installare e validare la candidate sulla box con solo telecomando.
- [ ] Verificare Home, ricerca, Sfoglia, dettaglio, trailer, VOD, autoplay,
  lingua, sottotitoli, live/EPG/zapping, download, updater e diagnostica.
- [ ] Misurare avvio, RAM, frame persi, latenza focus e sessione lunga.
- [ ] Registrare differenze intenzionali rispetto alla RC Kodi.

Questo gate è parte della Milestone 2 e della RC prodotto: non è rinviato alla
successiva Milestone 7 di consolidamento.

### Preview TV 0.9.1 — 27 luglio 2026

- [x] Shell 10-foot con rail laterale, safe area e fullscreen.
- [x] Home TV con hero statico, metadati, righe e card landscape.
- [x] Live TV con loghi `Fit`, EPG visibile e card landscape.
- [x] Dettaglio TV con backdrop, azioni e riga episodi.
- [x] ID Live univoci per evitare collisioni di focus.
- [x] Aggiornamenti Live differiti soltanto durante il movimento D-pad.
- [x] EPG Sky richiesto a blocchi invece della singola pagina da 400 eventi.
- [x] Preferenza AAC automatica sui live quando la box offre anche E-AC3.
- [x] Diagnostica Media3 delle tracce audio e del formato selezionato.
- [x] Build ARM32 firmata `0.9.1` / code 56; lint e build release superati.
- [ ] Test reale sulla box di audio SKY/Sport, EPG, OSD e ritorno dal player.

### Stabilizzazione adattiva 0.9.2 — 27 luglio 2026

- [x] Rendere il hero Home realmente fisso fuori dalla lista verticale.
- [x] Correggere il crash Compose da riuso/pinning durante D-pad rapido.
- [x] Stress-testare tutte le 30 righe senza crash o ANR.
- [x] Rimuovere provider e `channel_config` dalla UI impostazioni conservando
  i relativi dati per il motore.
- [x] Separare `FormFactor`, `InputMode` e `PerformanceTier`.
- [ ] Ripetere lo stress test sulla box H313 con la release ARM32 firmata.

## Ordine immediato — nuova chat TV

1. Leggere integralmente `TV_APP_HANDOFF.md` e questa roadmap.
2. Verificare working tree e baseline 0.8.9 senza reset o pulizie distruttive.
3. Costruire una build diagnostica `armeabi-v7a` senza cambiare il package.
4. Verificare installazione e avvio sulla box H313.
5. Introdurre lo scheletro TV con focus D-pad prima di portare tutte le pagine.
6. Aggiungere coordinatore low-power e misurare Home vuota/snapshot.
7. Validare Home → dettaglio → player con telecomando.
8. Portare MediaSession, OSD e zapping.
9. Estendere a Sfoglia, ricerca, download e impostazioni.
10. Conservare come backlog il playback Android del bundle reale con
    sottotitoli HLS separati; non deve bloccare il primo prototipo TV.

### Release candidate adattiva 0.9.3 — 27 luglio 2026

- [x] Introdurre design system condiviso phone/tablet/TV.
- [x] Completare Search e Browse dedicati TV con focus D-pad.
- [x] Rendere il dettaglio TV leggibile e navigabile a distanza.
- [x] Sostituire player e trailer mobile su TV con OSD fullscreen dedicati.
- [x] Rimuovere provider dalle Impostazioni Android conservando il motore.
- [x] Sanitizzare i report prima di rete/condivisione.
- [x] Introdurre policy qualità/4K condivisa con 21 scenari automatici.
- [x] Verificare lint debug/release e regressione phone/tablet/TV emulata.
- [x] Costruire un'unica APK firmata ARM32+ARM64 0.9.3/code58.
- [ ] Installare la 0.9.3 sulla box e ripetere stress Home/Browse.
- [ ] Validare sulla box audio SKY/Sport, EPG, OSD, trailer e zapping.
- [ ] Misurare cold/warm start, RAM e fluidità sulla box reale.

APK locale non pubblicato:
`PrippiStream-0.9.3-adaptive-universal-arm.apk`, SHA-256
`A622AAF47956E7DD05F048CDC12E2705F7366BA0CF1788CBF7D5816A3B5F3BE2`.

### Release candidate adattiva 0.9.4 — 28 luglio 2026

- [x] Rendere asincrona e sempre terminante la raccolta diagnostica.
- [x] Correggere il costo patologico della sanitizzazione IPv6 sui log reali.
- [x] Limitare coda, TTL, tentativi e concorrenza dei report.
- [x] Escludere diagnostica e identificatore dai backup Android.
- [x] Preparare e testare il relay HTTPS → Telegram senza credenziali client,
  con report ID, deduplicazione atomica e rate-limit per IP.
- [ ] Pubblicare il relay con segreti server-side e configurare l'endpoint APK.
- [x] Ridisegnare i controlli aggiuntivi del player telefono.
- [x] Rilevare display fisico e decoder hardware per la policy 4K.
- [x] Superare test JVM, lint e build release ARM32+ARM64.
- [ ] Installare 0.9.4 sulla box e ripetere stress, live, audio, EPG e zapping.

APK locale non pubblicato:
`PrippiStream-0.9.4-adaptive-universal-arm.apk`, SHA-256
`19D97490445ED73324CFC0002EB8E6E6E2B48599CBF6B25EA7690A4B4F427202`.

### Release candidate adattiva 0.9.5 — 28 luglio 2026

- [x] Aggiungere preview trailer automatica, muta e non focalizzabile nel
  dettaglio TV dopo 2,5 secondi.
- [x] Conservare il trailer fullscreen manuale e l'intera UI telefono.
- [x] Disabilitare automaticamente la WebView su low-RAM e heap inferiori a
  384 MB, privilegiando box economiche.
- [x] Verificare lifecycle con cicli dettaglio/Home e rilascio WebView.
- [x] Gestire renderer terminato, pausa app e timeout playback con fallback al
  backdrop, senza lasciare richieste o WebView attive in background.
- [x] Superare 12 test JVM, lint release e build universale ARM.
- [ ] Installare 0.9.5 e verificare trailer, stress Home, live, audio, EPG e
  zapping sulla box reale.

APK locale non pubblicato:
`PrippiStream-0.9.5-adaptive-universal-arm.apk`, SHA-256
`4AFCA3B0481323E85EBFAF396DC8B491A55CEC902B4E151E36AE57DF15BD8266`.

### Release candidate adattiva 0.9.6 — 28 luglio 2026

- [x] Rendere Search e Sfoglia adattive con griglie editoriali su telefono,
  tablet e TV.
- [x] Conservare il logo PrippiStream anche nei player video e trailer.
- [x] Correggere il crash di apertura trailer e validare fullscreen/background.
- [x] Ripristinare il player dopo `onStop` dalla posizione salvata.
- [x] Estendere l'autoplay all'intera stagione tramite coda persistente fuori
  da Binder, leggendo un episodio alla volta.
- [x] Applicare capacità decoder specifiche per AVC/HEVC/VP9/AV1, rete validata,
  hotspot a consumo e profilo low-power fino a 256 MB.
- [x] Rimuovere le credenziali Telegram dal motore incluso nell'APK e
  irrobustire hash e sanitizzazione del relay.
- [x] Superare unit test, 13 scenari relay, invarianti release, build firmata e
  stress D-pad TV senza crash/ANR.
- [ ] Pubblicare/configurare il relay HTTPS con segreti server-side.
- [ ] Nella milestone sicurezza successiva, sostituire token proxy e
  credenziali legacy Trakt/TVDB incluse nel motore con servizi server-side o
  flussi senza segreti client, senza rompere i fallback Cloudflare.
- [ ] Installare e validare 0.9.6 sulla box reale.

APK locale non pubblicato:
`PrippiStream-0.9.6-adaptive-universal-arm.apk`, code61, 55.654.639 byte,
SHA-256
`3DF8C71CB6608D917E4E4D57354B2E3B8F7EEB23FD13849CF4BD994EE1A62A60`.

### Release candidate adattiva 0.9.7 — 28 luglio 2026

- [x] Arricchire Detail con runtime, certificazione, regia, cast, studio,
  paese e data, caricando TMDB soltanto all'apertura della scheda.
- [x] Proteggere player e zapping da callback tardive, code illimitate,
  doppi comandi e ritorni dal background.
- [x] Completare la policy 4K per sorgenti adattive, codec sconosciuti, 480p e
  Wi-Fi trattabile come hotspot/rete a consumo.
- [x] Rendere i fallimenti temporanei del relay totalmente autonomi: report
  accodato e retry WorkManager, senza aprire finestre sulla TV.
- [x] Aggiungere un gate di build che rifiuta una release dichiarata
  Telegram-primary quando manca l'endpoint HTTPS.
- [x] Superare unit test, 13 scenari relay, invarianti, lint release, firma,
  controllo ABI e stress D-pad runtime senza crash/ANR.
- [ ] Pubblicare/configurare il relay HTTPS con segreti server-side; senza
  endpoint la candidate usa correttamente il backup manuale.
- [ ] Installare e validare 0.9.7 sulla box reale.

APK locale non pubblicato:
`PrippiStream-0.9.7-adaptive-universal-arm.apk`, code62, 55.671.019 byte,
SHA-256
`A3E5D09156F5DE54EAF4FF78EF36F75A1493AA785C1A4F1175FD08561B2DF766`.

### Release candidate adattiva 0.9.8 — 28 luglio 2026

- [x] Evitare la ricopia del payload Python a ogni avvio e inizializzare il
  motore fuori dal thread UI con bootstrap visivo.
- [x] Sulle box low-power serializzare l'archivio Home, limitandolo a tre righe
  differite per ciclo, e rinviare il preload Live.
- [x] Riconoscere come TV anche box non certificate prive di touch.
- [x] Rendere univoche le chiavi Compose e ripristinare il focus dopo aver
  portato la riga fuori schermo in viewport.
- [x] Rendere Search e Sfoglia griglie TV realmente adattive e mostrare il
  filtro selezionato.
- [x] Cancellare task foreground obsoleti, sospendere la Home durante il player
  e proteggere lo stato da risultati concorrenti tardivi.
- [x] Applicare allo zapping un timeout reale, non riprendere la timeline sui
  live e cancellare le callback WebView alla fine della sessione.
- [x] Conservare i report diagnostici dopo l'esaurimento dei retry e offrire
  un backup esplicito; imporre limiti di spazio/dimensione agli aggiornamenti.
- [x] Superare build, unit test, lint, invarianti, 13 scenari relay, installazione
  firmata e stress D-pad emulato senza crash o ANR.
- [ ] Pubblicare/configurare il relay HTTPS con segreti server-side.
- [ ] Installare e validare 0.9.8 sulla box reale.

APK locale non pubblicato:
`PrippiStream-0.9.8-adaptive-universal-arm.apk`, code63, 55.703.839 byte,
SHA-256
`FD20CFE26C39207E53D801EC71C0B1A8D1EC65699540CB4F107B1F6C23528D97`.

### Release candidate adattiva 0.9.9 — 28 luglio 2026

- [x] Portare nell'app l'invio diagnostica Telegram con report sanificato,
  archivio ZIP, WorkManager, limiti di coda/età e fallback manuale.
- [x] Verificare un invio reale: risposta Telegram `ok: true` e outbox vuota.
- [x] Unificare app e addon sullo stesso `remote_registry.py` e sulla stessa
  sorgente remota `channels.json`, con scrittura atomica e fallback locale.
- [x] Mostrare la Home dallo snapshot prima di inizializzare Chaquopy e
  posticipare Python fino al primo frame Compose realmente applicato.
- [x] Validare su emulatore TV stabilizzato: snapshot caricato, Home mostrata
  in 4,819 s e primo log Python successivo al paint; nessun crash o ANR.
- [x] Superare unit test, invarianti release, lint e build firmata ARM32+ARM64.
- [ ] Installare e validare 0.9.9 sulla box reale.
- [ ] Migrare in una fase successiva il token Telegram dal client a un relay
  server-side e firmare il registro remoto.

APK locale non pubblicato:
`PrippiStream-0.9.9-adaptive-universal-arm.apk`, code64, 55.709.607 byte,
SHA-256
`A320215222EE70B848108533BF0FC239AE2DF33A3BCAE5BFFFFA62D73B72C9FE`.

### Validazione box e fallback SC 0.9.10–0.9.11 — 28 luglio 2026

- [x] Correggere la distribuzione ambigua della prima 0.9.9: l'APK servita
  precedeva le ultime modifiche TV/player pur condividendo lo stesso code64.
- [x] Generare e installare 0.9.10/code65 dai sorgenti TV più recenti, senza
  logo persistente nel player, ARM32+ARM64 e firma invariata.
- [x] Verificare sulla box H313 Home, D-pad, Live, override E-AC3 → AAC e
  diagnostica locale; nessun nuovo crash.
- [x] Riprodurre il fallimento SC: iframe VixCloud valido, worker esterno non
  valido e bridge senza fallback verso il bootstrap WebView.
- [x] Aggiungere fallback SC ristretto agli embed HTTP(S) VixCloud/worker e
  testare il ramo completo `bridge.resolve`.
- [x] Generare e installare 0.9.11/code66; verificare `President Curtis`:
  `PlayerActivity` aperta e traccia audio italiana disponibile dopo 2,7 s.
- [x] Verificare una sessione lunga 0.9.11 sulla H313: oltre 71 minuti di
  processo e oltre 46 minuti nel secondo playback, senza nuovi crash o ANR;
  memoria finale 49 MB Java su 128 MB e 61 MB nativa.
- [x] Misurare la Home progressiva: primo focus navigabile dopo 7,49 s e
  18 spostamenti D-pad durante il caricamento; Home completa con 30 righe e
  570 elementi dopo 34,30 s.
- [ ] Ridurre o mascherare ulteriormente la latenza delle righe Live: TV pronta
  in circa 45,56 s, SKY 17/24 in 137,19 s e Sport 21/26 in 194,23 s. I log
  mostrano timeout/probe degradati delle fonti esterne, senza bloccare Home o
  player.
- [x] Rieseguire le invarianti release 0.9.11 e i test locali SC, sottotitoli
  offline, pipeline low-power, stato download e catalogo canali.
- [x] Rieseguire `testReleaseUnitTest` e `lintRelease` con Gradle 8.7:
  build riuscita, 37 task (4 eseguiti e 33 aggiornati).
- [ ] Completare stress D-pad reale, download, updater e regressione breve
  telefono/tablet prima del gate RC.

Report sanitizzato:
`reports/m2-box-20260728-app-0911.txt`.

APK locale non pubblicato:
`PrippiStream-0.9.11-adaptive-universal-arm.apk`, code66, 55.725.999 byte,
SHA-256
`227C5D6DB2CF0FCD66507D789F6155EC342A60D73BC0ACA1696132E25B9D061E`.

### CW cross-season e preferenze media globali — 5 agosto 2026

- [x] Usare una sola chiave CW per tutti gli episodi e le stagioni della stessa
  serie, migrando e deduplicando le voci precedenti.
- [x] Costruire una coda episodio ordinata su tutte le stagioni e supportare il
  passaggio automatico dall'ultimo episodio di una stagione al primo della
  successiva.
- [x] Salvare audio e sottotitoli per singolo film o per l'intera serie.
- [x] Rendere persistente anche la scelta sottotitoli `OFF`.
- [x] Riapplicare la scelta quando Media3 pubblica le tracce e dopo ogni cambio
  episodio, senza scegliere tracce non correlate se quella preferita manca.
- [x] Escludere i live da CW e preferenze media persistenti.
- [x] Superare unit test, `lintDebug` e `assembleRelease` (97 task).
- [x] Installare in-place sul telefono la 0.9.11/code66 firmata, senza perdita
  dati e senza eccezioni fatali nei log post-installazione.
- [ ] Eseguire il test manuale audio/sub tra episodi e stagioni sul telefono e
  sulla box Android TV.

APK finale del passaggio:
`app/build/outputs/apk/release/app-release.apk`, 44.818.231 byte, SHA-256
`E5E501757423B4C1B67817997625F39614D12F3FA10AED8B28DFD8A05A1EABDF`.

### Primo layout player dopo rotazione — 5 agosto 2026

- [x] Eliminare il taglio del titolo/stato al primo avvio del player mobile.
- [x] Calcolare scala e larghezza dal viewport landscape realmente misurato.
- [x] Rendere l'header espandibile mantenendo 112 dp come altezza minima.
- [x] Superare 39 test, lint e build release.
- [x] Installare in-place sul telefono senza cancellare dati.
- [ ] Confermare visivamente il primo ingresso con un titolo lungo.

APK aggiornata: `app/build/outputs/apk/release/app-release.apk`, SHA-256
`5007FFDF59E7AE5E53FDE91EBDAC399B97A7535E60EC881E45A23CD50AB912AF`.

### Bug aperto — seek D-pad sulla timeline TV — 6 agosto 2026

- [ ] Riprodurre con diagnostica dedicata il caso osservato sulla box ARM32 con
  app 0.9.13: il cursore della timeline si sposta, ma la riproduzione non
  avanza oppure torna subito alla posizione precedente.
- [ ] Registrare `seek_requested`, posizione target, `seek_processed` e
  discontinuità Media3, distinguendo pressione singola e tasto mantenuto.
- [ ] Verificare la causa probabile: `televisionSeeking` viene attivato dai
  callback touch ma non dal D-pad, mentre `updateTelevisionTimeline` riscrive
  progress e thumb ogni 500 ms dalla posizione ancora precedente del player.
- [ ] Validare la futura correzione su HLS StreamingCommunity, DASH e file
  progressivo, includendo box low-power e telecomando reale.

Stato: segnalazione registrata, **nessuna correzione applicata**. I log della
sessione mostrano l'avvio HLS e le tracce audio ma non contengono eventi seek,
perciò la causa resta probabile finché non viene aggiunta telemetria mirata.
