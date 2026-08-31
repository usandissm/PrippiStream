# Parità addon Kodi → app Android

Inventario ricavato direttamente da `PrippiStream-v2`, aggiornato il 28 luglio 2026.

Legenda: **OK** disponibile e provato; **PARZIALE** collegato ma non ancora
equivalente all'addon; **DA FARE** non ancora portato.

## Navigazione e funzioni

| Area addon 2.0 | App Android | Stato |
|---|---|---|
| Home a caroselli | slider principali e archivio StreamingCommunity, Anime popolari e Continua a guardare, caricamento progressivo e snapshot | OK |
| Continua a guardare | posizione/durata persistenti, resume e rimozione | OK |
| Scheda film/serie | trama, anno, generi, rating, stagioni ed episodi | OK |
| Trailer | ricerca/cache YouTube, preview TV muta protetta e player fullscreen interno su ogni form factor | OK |
| Ricerca globale multi-provider | provider dinamici, cache, cronologia, filtri Film/Serie/Anime, deduplica e fallback player; SC, HD4Me e AnimeUnity provati sul Samsung | OK |
| Sfoglia Film / Serie / K-Drama / Anime / Hentai | data-layer originale, generi, paginazione e ordinamento recenti/meno recenti | OK |
| Canali/provider | 21/21 menu attivi raggiungibili; One Piece e catalogo paginato HD4Me inclusi | OK |
| Player VOD | HLS Media3, cookie/header, VixCloud, resume e fallback automatico mirror/provider; SC, HD4Me/Mega e Naruto/AnimeUnity provati con video e audio sul Samsung | OK |
| Qualità 4K / fallback FHD | indice 4K dell'addon, riga Home opzionale, scelta 4K/FHD e fallback StreamingCommunity | OK |
| Audio/sottotitoli/qualità | preferenza IT, tracce esterne e selettori Media3 qualità/audio/sottotitoli provati | OK |
| Autoplay episodio successivo | coda episodi, passaggio manuale e avvio automatico a fine episodio; 1x01→1x02 provato | OK |
| SKY / Sport Live / TV | probe sessione addon, righe SKY/Sport/TV, HLS e ClearKey; Sky Cinema Uno, SPORT UNO e Rai 2 provati sul Samsung; card live uniformate a rapporto 2:3 senza stretching e catalogo loghi SKY/Sport/TV completato nella 0.7.6 | OK |
| EPG e zapping touch | EPG ora in onda/prossimo programma, loghi completi e non deformati, cambio canale tramite pulsanti nell'app | OK |
| Download offline | coda, pausa/ripresa, scelta qualità, scelta memoria, spazio libero, foreground service, cifratura, audio, UI e playback locale provati; Naruto/AnimeUnity 480p scaricato e riprodotto dal server locale cifrato sul Samsung; propagazione resolver→player→download coperta da regressione; master Apple Bip Bop reale rilevato con WebVTT separato e traccia scaricata (37.540 byte). Nelle 0.7.7–0.7.8 il download VixCloud è stato irrobustito con deadline segmento 45 s, tre retry con ripresa da sidecar, rigenerazione su 403/410 e bootstrap WebView che usa subito playlist/cookie autorizzati senza accodare fallback scaduti. Test reali 0.7.8 sul Samsung: tre bootstrap immediati, download video/tracce completati, nessun 403, stallo, retry o crash | PARZIALE (resta il playback Android di un bundle reale multi-traccia con sottotitoli separati) |
| Impostazioni | preferenze globali qualità/audio/sub e diagnostica; pannelli provider rimossi dall'app | OK |
| Aggiornamento app | release pubblica invariata; candidate locale 0.9.11 code66 firmata in-place, senza pubblicazione remota | OK |
| Aggiornamento domini | app e addon usano lo stesso `remote_registry.py` e la stessa sorgente `channels.json`; validazione, limite 64 KiB, lock, throttle, staging, fsync, sostituzione atomica e fallback bundled sono comuni | OK |
| Avvio Live | controllo parallelo SKY/Sport/TV ed EPG avviato già durante la Home; risultati pronti entrando in Live | OK |
| Compatibilità dispositivi | Samsung A16 ARM64 e Pixel 6 virtuale x86_64/Android 15: motore, Home, Sfoglia, provider e Impostazioni verificati senza crash | OK |
| Android TV / Google TV / box | riconoscimento anche di box non certificate, profilo low-power seriale, focus D-pad visibile, Home → dettaglio → player, ripristino focus, MediaSession, zapping, snapshot-first e preview trailer protetta presenti; 0.9.11 ARM32 verificata sulla H313 con Home, Live/audio, VOD SC e sessione superiore a 71 minuti senza nuovi crash/ANR | PARZIALE — restano stress D-pad reale, download e updater |
| Tablet | stessa app Compose con breakpoint expanded, griglie adattive Search/Sfoglia e player touch; regressione emulata completata | OK |
| ABI ARM32 | La box H313 esegue Android ARM 32 bit; la candidate 0.9.11 include `armeabi-v7a` e `arm64-v8a` ed è stata avviata realmente | OK |

## Decisione adattiva

L'app Android esistente diventa l'unico prodotto Android per telefono, tablet,
Android TV, Google TV e box. Non nasce un secondo package. La parità TV richiede
una UI da salotto dedicata ma condivide motore, repository, modelli, database,
resolver, player, firma e aggiornamenti con la UI mobile.

## Canali dichiarati dalla v2

Attivi: `1337x`, `accuradio`, `animesaturn`, `animeunity`, `animeworld`,
`cineblog01`, `cinetecadibologna`, `discoveryplus`, `hd4me`, `hentaisaturn`,
`ilcorsaronero`, `la7`, `mediasetplay`, `onepiece`, `plutotv`, `raiplay`,
`streamingcommunity`, `streamingita`, `toonitalia`, `tunein`, `videosky`.

Presente ma disattivato nell'addon: `altadefinizione01`.

Impostazioni specifiche dichiarate dai canali:

- `1337x`: ricerca contenuti in italiano;
- `animeunity`: ordine di visualizzazione;
- `animeworld`: lingua e ordine;
- `mediasetplay`: preferenza MPD e paginazione.

## Home dell'addon

Dal codice `platformcode/prippihome.py` risultano:

- Continua a guardare;
- I miei download;
- SKY;
- Sport Live;
- TV;
- Film in 4K opzionale;
- righe principali e archivio StreamingCommunity;
- Anime popolari;
- ricerca, scheda dettaglio, trailer e righe speciali One Piece.

## Sfoglia dell'addon

Le macro ufficiali sono Film, Serie, K-Drama, Anime e Hentai. Hentai è
controllato da `show_adult_anime`; Film/Serie/K-Drama usano generi SC con CB01
come sorgente aggiuntiva, Anime usa AnimeUnity, Hentai unisce HentaiSaturn e i
generi adult/suggestive di AnimeUnity.

## Impostazioni visibili da adattare

- Generale: DNS override, provider DNS, debug;
- Download: percorso, concorrenza 1–3, visibilità riga download;
- Personalizzazione: loop righe, Hentai, riga 4K, scelta 4K/FHD, animazioni
  ridotte, visibilità SKY/Sport/TV, zapping e overlay;
- Supporto: log prestazioni e invio log;
- `autostart` e apprendimento tasti Kodi richiedono equivalenti Android, non una
  copia letterale delle azioni Kodi.

## Aggiornamento APK

Endpoint previsto: `usandissm/PrippiStream` → GitHub Releases → primo asset
`.apk`. L'app confronta il tag della release con `BuildConfig.VERSION_NAME`,
scarica l'APK e apre l'installer Android. Perché gli aggiornamenti sostituiscano
l'app installata, tutte le release devono essere firmate sempre con la stessa
chiave e avere un `versionCode` crescente.
