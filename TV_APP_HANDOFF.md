# PrippiStream — handoff app unica Android TV/mobile

> Documento operativo TV. Le milestone prodotto comuni ad addon e app sono
> autoritative in `PrippiStream-v2/PROJECT_STATUS.md`; `APP_ROADMAP.md` contiene
> la checklist tecnica Android. La candidate corrente 0.9.9 partecipa al gate
> combinato con Kodi 2.0 e non è più un percorso futuro post-Kodi. È però una
> candidate pre-sync: prima della RC finale va rigenerata dal motore v2
> validato, perché il controllo contro 1.9.986 rileva ancora divergenze.

Ultimo aggiornamento: 28 luglio 2026.

## Decisione approvata

Evolvere l'app Android esistente, senza creare una seconda app, affinché lo
stesso package `com.prippi.stream` funzioni su:

- smartphone;
- tablet;
- Android TV;
- Google TV;
- box Android, incluse quelle ARM32 low-power.

Telefono e tablet mantengono touch e layout responsive. TV e box ricevono una
UI da salotto dedicata, completamente utilizzabile con telecomando e D-pad.
Stessa firma, dati, download, updater, motore e repository.

## Baseline da non perdere

- App: **0.8.9**, `versionCode 54`, firmata e pubblicata.
- APK pubblico corrente: solo `arm64-v8a`; preview TV `armeabi-v7a` prodotta
  localmente e non pubblicata.
- Stack: Kotlin 1.9.24, Compose, Chaquopy/Python 3.11, Media3 1.4.1.
- Motore autorevole: `C:\Users\Michele Santeramo\Desktop\PROGETTI\PrippiStream-v2`.
- App: `C:\Users\Michele Santeramo\Desktop\PROGETTI\PrippiStreamApp`.
- Memoria completa:
  `C:\Users\Michele Santeramo\Desktop\PROGETTI\PrippiStream\PRIPPISTREAM_MEMORIA_COMPLETA.md`.
- Roadmap app: `APP_ROADMAP.md`.
- Parità: `ADDON_PARITY.md`.

La 0.8.9 mobile comprende Home, Sfoglia, ricerca globale, dettaglio, episodi,
autoplay, lingua/sottotitoli, trailer, SKY/Sport/TV, ClearKey/Widevine, zapping,
download cifrati, Continua a guardare, diagnostica e aggiornamenti firmati.

## Stato implementato il 26 luglio 2026

- aggiunti `DeviceProfile` e `TvActivity`, registrata come
  `LEANBACK_LAUNCHER`, senza separare package o dati dall'app mobile;
- rilevamento TV/low-RAM e layout landscape adattivo, con card e barra più
  leggere a 720p;
- focus D-pad visibile e deterministico su Home e Live, con ripristino della
  stessa riga/card dopo dettaglio e player;
- dettaglio TV orizzontale e controlli player focalizzabili;
- MediaSession Media3 attiva; tasti media e zapping live già instradati;
- avvio low-power Home-first, live ritardati, enrich TMDB e rebuild 4K esclusi
  dal boot;
- refresh live seriale TV → SKY → Sport sui device low-power, parallelo sugli
  altri dispositivi;
- updater reso ABI-aware, con fallback soltanto a un APK universale;
- build release ARM32 firmata:
  `PrippiStream-0.8.9-tv-preview-armeabi-v7a.apk`;
- SHA-256 APK:
  `2FB3D5B0A7DEBC3CF680DF88443990E8E919ED9159E0EC37AF3404C770D1802B`;
- firma v2 confermata, certificato SHA-256:
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`.

Verifica emulatore x86_64: Home → dettaglio → player → ritorno alla stessa
card completato con D-pad, nessun crash o ANR e MediaSession registrata. Il
contenuto scelto per il test player ha restituito un manifest scaduto/HTTP 403:
il percorso nativo è stato esercitato, ma un playback completo con sorgente
fresca resta parte del test sulla box.

Timestamp del refresh low-power osservati sull'emulatore:

- TV: 48 canali pronti alle 22:12:37;
- SKY: 17 canali pronti alle 22:13:06;
- Sport: 18 canali pronti alle 22:13:34.

Il prossimo gate è l'installazione autorizzata sulla box H313 e la misura reale
di cold/warm start, RAM, focus, playback, DRM e zapping. Kodi non è stato
avviato e la preview non è stata installata o pubblicata.

### Aggiornamento diagnostico 0.9.0 — 27 luglio 2026

Il primo test reale ARM32 ha mostrato una terminazione dell'app mentre si
scorreva la Home; il vecchio APK conservava soltanto il log Python, non lo
stack Kotlin/Compose.

La preview 0.9.0/versionCode 55 aggiunge:

- crash handler persistente e cronologia lifecycle/focus/memoria;
- endpoint locale `http://IP-BOX:18765/diagnostics`;
- rilevamento della sessione precedente terminata senza uscita pulita;
- ripristino focus eseguito soltanto entrando nella pagina, non a ogni card;
- cache Coil ridotta al 6% sulle box low-power, crossfade disabilitato e
  svuotamento cache quando Android segnala memoria bassa;
- aggiornamenti Home/Live ignorati quando il contenuto non è cambiato.

APK ARM32:
`PrippiStream-0.9.0-tv-preview-armeabi-v7a.apk`.
SHA-256:
`6F2998F42957C3657B2867A902897CE7095C7B28FC1AFC27E0186D34A09AF034`.

Il ponte Kodi è stato aggiornato alla 1.9.975 per scaricare e verificare questa
versione. Build, lint, test motore 21/21 e stress D-pad emulatore superati.

## Hardware TV iniziale

Box reale di riferimento:

- Google QUAD-CORE H313 P1;
- Android TV 10 / API 29;
- ARM 32 bit (`armv8l`);
- 4 core;
- RAM totale 1976 MB;
- GUI 1280×720;
- decoder Mali-G31/Allwinner.

La prima incognita è l'ABI: costruire `armeabi-v7a` con Python 3.11 e verificare
le wheel ARM32 di Pillow e PyCryptodome. Non cambiare package o firma.

## Cosa è già predisposto

- `LEANBACK_LAUNCHER`;
- banner TV;
- touchscreen non obbligatorio;
- Home Compose a righe;
- pagina Live;
- Media3 HLS/DASH/progressive;
- Widevine e ClearKey;
- tasti CHANNEL_UP/DOWN, PAGE_UP/DOWN e media next/previous;
- zapping circolare, overlay live, retry e fallback;
- repository/ViewModel separati dalla UI;
- bridge Kotlin/Python e motore sincronizzabile.

## Architettura richiesta

Preferenza corrente:

- `MainActivity` per telefono/tablet;
- `TvActivity` o entry point equivalente per TV/box;
- selezione tramite `UI_MODE_TYPE_TELEVISION`, Leanback e capacità input;
- ViewModel, repository, modelli, bridge, database, cronologia, resolver e
  player condivisi;
- coordinatore lavori per profilo hardware.

Ordine low-power:

1. snapshot Home;
2. prime righe immediatamente navigabili;
3. TV ufficiale;
4. SKY;
5. Sport;
6. archivio, Anime ed enrich;
7. sospensione dei lavori non indispensabili durante playback.

## Primo verticale della nuova chat

1. Leggere completamente questo file, `APP_ROADMAP.md`, `ADDON_PARITY.md` e le
   sezioni finali della memoria completa.
2. Ispezionare `git status` senza resettare o cancellare nulla.
3. Verificare la build 0.8.9 corrente.
4. Tentare una build diagnostica `armeabi-v7a`.
5. Installarla sulla box soltanto con autorizzazione dell'utente.
6. Confermare launcher, avvio Python, Home e Media3.
7. Implementare lo scheletro TV e un solo percorso completo:
   Home → focus card → dettaglio → player → ritorno alla stessa card.
8. Misurare cold/warm start, RAM e reattività D-pad prima di ampliare le pagine.

## Requisiti TV non negoziabili

- ogni funzione raggiungibile senza touch;
- focus sempre visibile;
- focus iniziale deterministico;
- ripristino di pagina/riga/card;
- Back coerente;
- nessun crop video: FIT;
- seek VOD normale e tasti canale soltanto sui live;
- zapping circolare con debounce, blocco durante avvio e salto offline;
- dialog qualità/audio/sottotitoli focalizzabili;
- UI leggibile a distanza e sicura a 720p;
- nessuna saturazione da Home, enrich e tre parser live simultanei.

## Stato addon Kodi collegato

- Build candidata: **1.9.973**.
- La 1.9.972 ha migliorato nettamente la Home sulla box.
- I live non comparivano perché attendevano 20 secondi consecutivi di completa
  inattività: nessun probe era partito.
- La 1.9.973 usa attesa fissa e ordine TV → SKY → Sport.
- Un primo play SC è fallito perché VixCloud ha chiuso il manifest; il secondo
  token ha funzionato. La 1.9.973 esegue un retry automatico con risoluzione e
  token freschi prima dell'avvio A/V.
- Kodi resta fallback finché l'app TV non supera la matrice completa.

## Regole operative

- Non avviare Kodi senza autorizzazione esplicita.
- L'utente ha autorizzato installazione APK, avvio e test autonomi dell'app
  sulla box anche prolungati. Kodi può essere usato come ponte tecnico
  autonomo, purché non richieda controllo dell'utente; non usarlo per test
  funzionali dell'addon estranei all'app.
- Non pubblicare release senza conferma.
- Non sincronizzare alla cieca una working tree sporca.
- Non usare reset, clean o checkout distruttivi.
- Modificare il motore in v2 e sincronizzarlo nell'app; gli adattatori Android
  restano nativi dell'app.
- Conservare firma e aggiornamento in-place.

## Prompt breve per aprire la nuova chat

> Lavoriamo sull'unica app PrippiStream Android per telefono, tablet, Android
> TV, Google TV e box. Leggi integralmente
> `C:\Users\Michele Santeramo\Desktop\PROGETTI\PrippiStreamApp\TV_APP_HANDOFF.md`,
> `APP_ROADMAP.md`, `ADDON_PARITY.md` e la memoria completa indicata lì.
> Verifica i repository senza resettare nulla. Parti dalla 0.8.9 e dal primo
> verticale M8: build ARM32 per la box H313, poi Home → dettaglio → player
> completamente navigabile con D-pad. Non installare o pubblicare senza mia
> autorizzazione.

## Aggiornamento 0.9.1 TV preview — 27 luglio 2026

La prima UI TV adattiva è stata sostituita da una presentazione dedicata:
rail laterale, hero Home, card landscape, Live con EPG, dettaglio 10-foot e OSD
Media3 separato dal controller mobile. Telefono e tablet continuano a usare la
UI precedente nella stessa app e con lo stesso package.

Correzioni funzionali incluse:

- chiave stabile Live `live:<provider/kind>:<id>`;
- aggiornamenti strutturali Live applicati dopo 800 ms di inattività D-pad;
- EPG Sky scaricato in blocchi per evitare il limite di 400 eventi;
- preferenza AAC sui live quando sono presenti anche tracce E-AC3;
- fallback decoder Media3 e diagnostica persistente di codec/lingua/supporto;
- recupero del crash Compose su coordinate focus staccate.

Artefatto box:

- `PrippiStream-0.9.1-tv-preview-armeabi-v7a.apk`;
- package `com.prippi.stream`, versionCode 56;
- SHA-256 `44A8632519D093E4F3BE2F8AB8365EDB6B137023813CE000D23CB32B06FAD2A2`;
- certificato invariato
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`.

## Aggiornamento 0.9.9 — 28 luglio 2026

La candidate corrente è la 0.9.9/code64. È la stessa app per telefono, tablet,
Android TV, Google TV e box; non è stato creato un secondo package.

- Home snapshot-first: massimo 6 righe × 12 elementi nel seed nativo, TTL 12 h,
  primo contenuto Compose prima dell'inizializzazione Python;
- barriera del primo paint tramite `SideEffect`, poi 500 ms prima di Chaquopy;
- diagnostica Telegram diretta con ZIP sanificato, retry WorkManager, massimo
  tre report per tre giorni e condivisione manuale dopo il fallimento definitivo;
- app e addon usano una copia byte-identica di `platformcode/remote_registry.py`
  e la stessa sorgente GitHub per `channels.json`;
- updater comune con limite 64 KiB, validazione JSON/URL, lock, throttle,
  staging, `fsync`, `os.replace` e fallback bundled;
- Kodi delega l'aggiornamento al servizio; Android lo avvia dal bridge nativo
  dopo il primo paint, evitando doppie scritture concorrenti.

Validazione emulatore TV stabilizzato: `Displayed` in 4,819 s, snapshot prima
del frame e Python dopo il frame; nessun crash o ANR. Test unitari, invarianti,
lint release, firma e ABI superati.

Artefatto locale non pubblicato:

- `PrippiStream-0.9.9-adaptive-universal-arm.apk`;
- versionCode 64, `armeabi-v7a` + `arm64-v8a`;
- 55.709.607 byte;
- SHA-256 `A320215222EE70B848108533BF0FC239AE2DF33A3BCAE5BFFFFA62D73B72C9FE`;
- firma v2, certificato SHA-256
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`.

Ponte Kodi locale: 1.9.984. Test box reale ancora pendente. Per una futura
release pubblica va ruotato il bot Telegram e spostata la credenziale in un
relay server-side; il registro remoto dovrà inoltre ricevere firma/versione.

## Aggiornamento 0.9.10–0.9.11 — 28 luglio 2026

La prima APK 0.9.9 servita alla box era stata compilata prima delle ultime
modifiche TV/player. La numerazione è stata resa nuovamente monotona:
0.9.10/code65 ha consolidato la UI corrente; 0.9.11/code66 aggiunge il fallback
SC verso il bootstrap WebView quando il resolver Python non ricava la playlist
VixCloud.

Validazione reale H313/Android 10 ARM32:

- avvio 0.9.11 e riconoscimento TV/low-power;
- Home 30 righe/570 item e navigazione D-pad;
- Live TV/SKY, selezione AAC al posto di E-AC3 incompatibile;
- `President Curtis` risolto e avviato in `PlayerActivity`, audio italiano
  rilevato da Media3;
- nessun nuovo crash; il crash Compose conservato nel report è storico del
  27 luglio.

Artefatto corrente:

- `PrippiStream-0.9.11-adaptive-universal-arm.apk`;
- versionCode 66, `armeabi-v7a` + `arm64-v8a`;
- 55.725.999 byte;
- SHA-256 `227C5D6DB2CF0FCD66507D789F6155EC342A60D73BC0ACA1696132E25B9D061E`;
- ponte Kodi locale 1.9.988.

## Aggiornamento 0.9.8 — 28 luglio 2026

La candidate 0.9.8 è il nuovo artefatto da provare sulla box. Il payload Python
viene installato atomicamente soltanto al cambio versione e riutilizzato ai
warm start; l'avvio del motore avviene su thread I/O dietro una schermata
bootstrap. Sui dispositivi low-power l'archivio Home usa un solo worker e non
aggiunge più di tre righe differite per ciclo.

Sono stati inoltre corretti riconoscimento delle box TV non certificate,
identità delle card, ripristino focus fuori viewport, task concorrenti Home,
griglie adattive Search/Sfoglia, timeout zapping, resume live, cleanup WebView,
backup diagnostico e limiti dell'updater.

Verifica emulatore TV 1920x1200: Activity/bootstrap visibile in circa 4,1 s,
Home completa e 74 pressioni D-pad rapide senza crash/ANR. Il runtime Python
x86 dell'emulatore ha richiesto oltre 12 s anche al warm start: la misura ARM
reale resta quindi obbligatoria e non viene dichiarato un miglioramento
definitivo prima della box. Cerca e Detail sono stati verificati visivamente.
Build, test, lint, invarianti e 13 scenari relay sono verdi.

Artefatti locali non pubblicati e serviti su `172.20.10.2:8765`:

- `PrippiStream-0.9.8-adaptive-universal-arm.apk`, code63, 55.703.839 byte,
  SHA-256 `FD20CFE26C39207E53D801EC71C0B1A8D1EC65699540CB4F107B1F6C23528D97`;
- `plugin.video.prippistream-1.9.983.zip`, 6.993.266 byte,
  SHA-256 `48D0B3E97329630F1E9C3A7CDE42D288FE77D26F563469AD468CFE834AA29030`.

Kodi è autorizzato come ponte autonomo. Al controllo la box
`172.20.10.11` era fuori rete e nessun host alternativo della subnet esponeva
diagnostica app, JSON-RPC Kodi, ADB o SSH; installazione e matrice hardware
restano quindi pendenti.

## Aggiornamento 0.9.6 — 28 luglio 2026

La candidate 0.9.6 completa l'interfaccia adattiva unica: Search e Sfoglia
usano griglie editoriali, le card TV espongono metadati, il logo resta visibile
nei player e l'apertura trailer non può più crashare prima della creazione
della finestra.

Il player riparte dalla posizione salvata dopo il background; l'autoplay usa
una coda persistente esterna a Binder e può attraversare tutta la stagione
leggendo un solo episodio alla volta. La policy 4K distingue i limiti hardware
per codec, riconosce AVC/HEVC/VP9/AV1 dalla sorgente e tratta hotspot, rete non
validata e box fino a 256 MB in modo prudente.

Sicurezza diagnostica: rimosse le credenziali Telegram dal motore APK; il relay
verifica che `report_id` sia lo SHA-256 del report e applica una sanitizzazione
server-side più forte senza alterare gli orari nei log. Il relay pubblico con
segreti server-side resta da configurare.

Artefatti locali non pubblicati:

- `PrippiStream-0.9.6-adaptive-universal-arm.apk`, code61, 55.654.639 byte,
  SHA-256 `3DF8C71CB6608D917E4E4D57354B2E3B8F7EEB23FD13849CF4BD994EE1A62A60`;
- firma v2 e certificato invariato
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`;
- ponte `plugin.video.prippistream-1.9.981.zip`, 6.992.888 byte,
  SHA-256 `4FBA79C481F0B1DC8AFF8C73BBDBD0358F0650371C8F088874F026663384F93A`.

Entrambi sono serviti su `172.20.10.2:8765`. Il ponte 1.9.981 può scaricare e
verificare l'APK senza UI; Android stock continua a richiedere una conferma
esterna per installarla.

## Aggiornamento 0.9.7 — 28 luglio 2026

La candidate 0.9.7 mantiene un solo APK adattivo e chiude i punti emersi dagli
audit runtime:

- Detail arricchito a richiesta con runtime, certificazione, regia, cast,
  studio, paese e data, senza aggiungere lavoro al primo paint della Home;
- zapping live con debounce 650 ms, massimo quattro candidati, budget di
  risoluzione, blocco fino a `STATE_READY` e cancellazione delle callback
  tardive quando l'activity va in background;
- policy 4K prudente anche per manifest adattivi e codec non dichiarati, con
  opzioni separate per 4K su rete a consumo e Wi-Fi/hotspot;
- diagnostica che, su errore temporaneo del relay, resta accodata e ritenta in
  autonomia senza aprire la share sheet o interrompere il player TV;
- gate Gradle opzionale che impedisce di produrre una release dichiarata
  Telegram-primary se manca l'endpoint HTTPS.

Verifiche completate: unit test, 13 scenari relay, invarianti statici, lint
release, firma v2, ABI ARM32+ARM64, installazione runtime 0.9.7 su emulatore,
health-check 18765 e stress D-pad TV senza crash/ANR.

Artefatti locali non pubblicati:

- `PrippiStream-0.9.7-adaptive-universal-arm.apk`, code62, 55.671.019 byte,
  SHA-256 `A3E5D09156F5DE54EAF4FF78EF36F75A1493AA785C1A4F1175FD08561B2DF766`;
- certificato invariato
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`;
- ponte `plugin.video.prippistream-1.9.982.zip`, 6.992.934 byte,
  SHA-256 `2CC693D1926E9EDA7A77D310C1EA8EAB1A39C2CE465E373376641E9B59127D83`.

Entrambi sono serviti su `172.20.10.2:8765`. Al controllo successivo la box non
era presente sulla subnet (porte 8080, 9090, 18765, 5555 e 22 tutte chiuse);
appena ricompare, Kodi può scaricare e verificare l'APK in autonomia. Android
stock continua però a richiedere conferma del Package Installer per sostituire
l'app, salvo root o device-owner.

## Aggiornamento 0.9.3 adattivo — 27 luglio 2026

La stessa APK ora copre ARM32 e ARM64 e mantiene tre profili verificati:
telefono touch, tablet e TV D-pad. Su TV sono stati completati:

- design system 10-foot, logo persistente, hero Home fisso e card più ricche;
- Search dedicata con IME Search e griglia poster;
- Browse con macro, generi e griglia a cinque colonne;
- dettaglio con backdrop, metadati, trailer, download ed episodi;
- Impostazioni TV senza provider;
- OSD Media3 TV e trailer fullscreen senza controller mobile;
- diagnostica sanitizzata per credenziali, DRM, rete e percorsi utente;
- policy condivisa rete/dispositivo/4K, con protezione dei box low-power e
  distinzione corretta tra manifest adattivi e file progressivi.

Verifiche: 21 scenari JVM, lint debug/release, build release, stress D-pad Home
e Browse, regressione telefono e profilo tablet. Il crash Browse da chiave
Compose duplicata è stato trovato nel test runtime e corretto.

Artefatto:

- `PrippiStream-0.9.3-adaptive-universal-arm.apk`;
- package `com.prippi.stream`, versionCode 58;
- ABI `armeabi-v7a` e `arm64-v8a`;
- SHA-256 `A622AAF47956E7DD05F048CDC12E2705F7366BA0CF1788CBF7D5816A3B5F3BE2`;
- certificato invariato
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`.

Ponte locale: Kodi 1.9.978, SHA-256
`EAB78BFCDC7F64A27871E36DBBDB0882D048870047633D67482355BA3D868899`.
La box espone JSON-RPC Kodi su 9090 e diagnostica app su 18765, ma monta ancora
il ponte 1.9.976. Senza root/device-owner Android richiede una conferma di
Package Installer almeno per il primo aggiornamento; nessuna release remota è
stata pubblicata.

Il prossimo test reale deve verificare: avvio/focus, Home → dettaglio → player →
ritorno, Live TV/SKY/Sport, EPG Sky, audio AAC, OSD e zapping CHANNEL+/−.

## Aggiornamento 0.9.4 — 28 luglio 2026

La release adattiva successiva completa tre parti rimaste aperte:

- player telefono senza barra tecnica: controlli Media3 nativi più capsula
  contestuale per episodio/canale e menu Tracce;
- policy 4K collegata a modalità fisica del display e decoder hardware
  AVC/HEVC/VP9/AV1, mantenendo il limite Full HD sui profili low-power in Auto;
- diagnostica asincrona con sanitizzazione veloce, timeout del motore Python,
  guard contro invii concorrenti, coda WorkManager limitata/temporizzata e
  fallback Android.

Il relay Telegram è implementato e testato in `diagnostics-relay/`, senza token
nell'APK. Ogni report usa un ID SHA-256 stabile; un Durable Object applica
rate-limit IP e prenotazione/commit atomici, evitando invii doppi dopo risposte
perse. I 12 scenari relay coprono successo, duplicato, payload errato,
configurazione incompleta, rate-limit ed errore Telegram con retry. La build di
consegna non contiene ancora un endpoint pubblico: servono deployment HTTPS e
segreti server-side prima che Telegram diventi effettivamente il percorso
primario; fino ad allora resta attivo il fallback di condivisione.

Artefatto locale non pubblicato:

- `PrippiStream-0.9.4-adaptive-universal-arm.apk`;
- package `com.prippi.stream`, versionCode 59;
- ABI `armeabi-v7a` e `arm64-v8a`;
- SHA-256 `19D97490445ED73324CFC0002EB8E6E6E2B48599CBF6B25EA7690A4B4F427202`;
- firma v2, certificato
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`.

Ponte Kodi preparato: `plugin.video.prippistream-1.9.979.zip`, SHA-256
`966010A259832CA68147741C54601B68CFB3F205D7F76C230764F8893AC7D0BB`.
Entrambi gli artefatti sono serviti sulla rete test. L'installazione Android non
può essere resa silenziosa su una box stock priva di root/device-owner: Kodi può
scaricare e aprire Package Installer, ma la conferma di sistema resta esterna.
Verifica autonoma del 28 luglio: box raggiungibile, app installata `0.9.1`,
Kodi `21.2`, ponte installato `1.9.976`; porte ADB 5555 e SSH 22 chiuse.

## Aggiornamento 0.9.5 — 28 luglio 2026

La scheda dettaglio TV ora può avviare automaticamente, dopo 2,5 secondi, una
preview trailer YouTube muta e non focalizzabile. Il player trailer fullscreen
manuale resta invariato e con audio. Per non sacrificare fluidità e memoria, la
preview automatica viene abilitata soltanto sui dispositivi non low-RAM con
heap Android di almeno 384 MB; sulle box economiche restano backdrop e pulsante
Trailer, senza creare una WebView.

Verifiche: 12 test JVM, zero failure/error; lint release con zero errori; build
release ARM32+ARM64; inizializzazione IFrame e quattro cicli dettaglio/Home su
emulatore TV senza crash o ANR, con WebView rilasciata al ritorno alla Home.
Un audit indipendente ha inoltre portato gestione della morte del renderer,
cleanup tramite `AndroidView.onRelease`, blocco fuori dallo stato RESUMED e
fallback al backdrop dopo 10 secondi senza playback.

Artefatti locali non pubblicati:

- `PrippiStream-0.9.5-adaptive-universal-arm.apk`, code60, 55.654.639 byte,
  SHA-256 `4AFCA3B0481323E85EBFAF396DC8B491A55CEC902B4E151E36AE57DF15BD8266`;
- firma v2 e certificato invariato
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`;
- ponte `plugin.video.prippistream-1.9.980.zip`, SHA-256
  `56DF304B15725A79962BD99CA2B18361C3A8945055CD2B001F3B01F29C477322`.

APK e ZIP sono serviti su `172.20.10.2:8765`. Il deploy silenzioso dell'APK
resta impossibile sulla box stock: Kodi può fare da ponte fino a Package
Installer, ma non può concedere autonomamente la conferma Android.

## Aggiornamento 0.9.2 — 27 luglio 2026

Il crash osservato sulla box durante lo scorrimento verticale rapido era una
`IllegalStateException` Compose (`Release should only be called once`) nel
riuso di un nodo focusable di una lazy list annidata. Non era un OOM: al crash
la box usava circa 36 MB Java e 32 MB native.

Correzioni:

- hero Home spostato definitivamente fuori dalla `LazyColumn`, quindi fisso;
- `FocusRequester` di ripristino congelato al target del ciclo, senza
  trasferirlo tra card riciclate durante la navigazione;
- `contentType` distinto per ogni riga Home e tipi card espliciti;
- provider rimossi dal contratto impostazioni Android e azioni
  `channel_config` filtrate, lasciando intatta la configurazione del motore;
- profilo dispositivo separato in form factor, input e performance tier.

Stress test emulatore TV: attraversamento rapido delle 30 righe in discesa e
risalita, nessun crash, ANR o nuova eccezione focus. Resta obbligatoria la
conferma sulla box reale.

Artefatto firmato:

- `PrippiStream-0.9.2-tv-stabilization-armeabi-v7a.apk`;
- package `com.prippi.stream`, versionCode 57;
- solo ABI `armeabi-v7a`;
- SHA-256 `47EEBBC2166E4A2C4B7EC1C558BDCBA911CF056C5F5F7A98B66C2179B48813A5`;
- certificato invariato
  `8b064d1e0389f33edfb5ad924fa00e9d1004be918dd0274b2e6e39184aeecdf3`.
