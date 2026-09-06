# PrippiStream 2.0 — Prestazioni addon Kodi e gate prodotto condiviso

> **Documento di lavoro** del progetto v2.0. Si aggiorna a ogni fase completata
> (checkbox + numeri `[PERF]` before/after). Questa cartella (`PrippiStream-v2`)
> è un clone locale **scollegato da GitHub**: nessun remote, nessun push possibile.
> Il repo pubblico (v1.5.x) resta intoccato fino al rilascio finale della 2.0.0.

> Le Fasi 0–10 e FASE 2 ARM di questo documento sono lo storico tecnico
> dell'addon Kodi. Lo stato autoritativo e le milestone comuni addon + app sono
> in `PROJECT_STATUS.md`; il dettaglio Android è in
> `PrippiStreamApp/APP_ROADMAP.md`. La release non è più Kodi-only.

## Obiettivo

Rendere l'addon fluido su hardware debole (Fire TV Stick, box Android S905,
Raspberry Pi, PC datati) **senza alcun cambiamento visibile** se non la velocità.
**Zero regressioni funzionali.** Include la pulizia del codice morto Stream4me
("Opzione 3").

Aree lente percepite: avvio/home, scorrimento righe/griglie, apertura
liste/ricerca/Sfoglia, avvio riproduzione.

Il gate prodotto aggiunge la stessa verifica per l'app adattiva: primo frame
Compose, bootstrap Chaquopy, RAM/frame persi, touch, D-pad, Media3, download e
ritorno focus su telefono, tablet/emulatore e box TV.

Vincoli:
- Cache disco generosa OK (100–300 MB).
- Fasi incrementali: dopo ogni fase → test su device reale, poi si prosegue.
- Build di test: versione `1.9.9xx` (mai sovrascritta dal repo pubblico 1.5.x;
  auto-aggiornata alla 2.0.0 finale quando uscirà dal repo Kodi).
- Packaging test: **solo** `python tools/make_addon_zip.py`.
  **MAI `release.ps1`** (fa commit+push su GitHub).

## Colli di bottiglia identificati (verificati sul codice)

| # | Problema | Dove |
|---|----------|------|
| 1 | Cache TMDB rotta per le risposte by-ID: `if not result.get('results')` scarta ogni hit di `/movie/{id}`, `/tv/{id}`, `/season/{n}` → rifetch+riscrittura sempre; solo le search sono cachate | core/tmdb.py:135-143 |
| 2 | Nuova `requests.session()` + nuovo adapter a ogni richiesta → handshake TLS ogni volta; cookies.dat risalvato a ogni richiesta | core/httptools.py:277-286, ~:460 |
| 3 | Enrich TMDB sincrono PRE-paint (8 righe × ~20 item prima del primo frame) | prippihome.py:1062 → :1213 |
| 4 | Cache righe home solo in memoria (TTL 30 min) → ogni riavvio Kodi = cold load | prippihome.py:24, :1023 |
| 5 | Progress bar = 10 controlli `<image>` per card × 40 slot × 2 layout ≈ 1.440 controlli, migliaia di condizioni di visibilità per frame | PrippiHome.xml:281-290 (1080i + 720p) |
| 6 | Settings per-canale/server letti da JSON su disco a ogni chiamata | channeltools.py:237+, servertools.py:545+ |
| 7 | db.sqlite autocommit + journal DELETE → ogni write crea/cancella un file journal su flash | core/__init__.py:34 |
| 8 | Nessun `reuselanguageinvoker` → interprete freddo a ogni click | addon.xml |
| 9 | Asset sovradimensionati (logo.png 1.06MB, logo_banner.png 613KB) | resources/media/ |
| 10 | `set_setting('show_once', True)` scritto a ogni invocazione | launcher.py:40 |
| 11 | Lavoro morto a runtime: `torrent.elementum_monitor` OGNI SECONDO; `viewmodeMonitor` 1Hz; `verify_directories_created` ricrea cartelle videolibrary + sources.xml a ogni boot | service.py:188-189, config.py:363-411 |
| 12 | BUG: `MAX_ROWS=50` ma l'XML ha 40 slot (id 2000-2390) → con >40 righe `getControl(2400+)` = RuntimeError | prippihome.py:473 |
| 13 | `_nuke_all_vixcloud_bookmarks`: SELECT+2 DELETE+commit su MyVideos.db a OGNI apertura home | prippihome.py:5099, lancio :1381 |
| 14 | Backdrop TMDB `/t/p/original` (fino a 3840px) per preloader CW e detail fanart — decode costoso su ARM | prippihome.py:167, :6978 |
| 15 | Cache module-level senza scadenza (`_trailer_cache`, `_plot_it_cache`) + invoker caldo (F6, processo persistente) = crescita RAM monotona | prippihome.py:135, :140 |
| 16 | `_get_it_overview` fetcha SEMPRE anche en-US pur con trama it-IT valida → 2 req TMDB al primo focus di ogni titolo | prippihome.py:5454, :5471 |
| 17 | db.sqlite ~100MB / 18,6k voci tmdb_cache mai potato (nota F4) — ogni lettura paga su flash | core/__init__.py |
| 18 | Asset: ~670KB ORFANI (2 loghi 400×400 nelle cartelle skin + sm/dark/light) + logo_prippistream 204KB e logo_banner 136KB malcompressi (un 512² analogo pesa 11KB) + ~1,5MB screenshot store inclusi nello zip | resources/ |
| 19 | Design: overlay hero = rettangolo piatto `900D0D0D` con bordo verticale NETTO a x=1050 che taglia la fanart; poster non-focus a piena luminosità (la card a fuoco non "stacca"); micro-copy inglese SET/EXIT in una UI italiana | PrippiHome.xml 1080i:40-44, :102, :119 |

Fatti verificati da NON ri-derivare:
- `CipherSuiteAdapter.__init__` non usa `domain`; il DoH è un monkey-patch globale
  di `urllib3.util.connection.create_connection` (resolverdns.py:43-63) → adapter
  condivisibile tra domini.
- `Item.tojson(path="")` → stringa JSON; `Item().fromjson(str)` ricostruisce (item.py:390/407).
- `lib/sqlitedict.py` accetta kwarg `journal_mode` (:112, PRAGMA :430).
- `lib/httplib2` USATO (checkhost.py ← service.py:313); `lib/sambatools` USATO
  (filetools.py:36) → non rimuovere.
- `$INFO[...]` dentro `<texture>` già usato nello skin (`fanart_image`) → tecnica sicura.
- Updater interno permanentemente disabilitato (updater.py:52-55); aggiornamenti
  solo via repo Kodi (mai downgrade).
- Pattern sessione persistente di riferimento: animeunity.py:34-56.
- **`720p/PrippiHome.xml` NON è più sorgente fedele del 1080i** (30 righe/27
  wraplist vs 40/36; mancano i group 7000-7290; drift presente già da v1.5.0).
  **MAI eseguire `tools/scale_1080i.py`**: ha il path hardcoded al repo v1 e
  rigenerare il 1080i dal 720p attuale DISTRUGGEREBBE 10 righe. Ogni edit XML
  va fatto TESTUALMENTE su ENTRAMBI i file, con i valori pixel propri di
  ciascuno (scala 1.5×; colordiffuse/label identici).
- Le 40 coppie zoom Focus/Unfocus del 1080i (30 nel 720p) sono testualmente
  UNIFORMI (`start="100" end="105" time="150"` / `start="105" end="100"
  time="110"`) → replace testuale sicuro. La coppia 100↔110 del bottone EXIT
  (1080i:124-125) è a parte: NON toccarla.
- `_sc_rows_cache` è un alias di `_cache['data']` (assegnati sempre insieme:
  prippihome.py:1208, :1319-1320, :1575-1576).
- `_fetch_cw_backdrops` (prippihome.py:167) alimenta SIA il preloader home
  (:1107) SIA lo slideshow del DetailWindow (:6913): le URL devono restare
  IDENTICHE nei due punti o il preload non scalda la texture giusta.

---

## Stato fasi

- [x] **SETUP** — workspace scollegato, versione 1.9.900, questo documento
- [x] **FASE 0** — strumentazione `[PERF]` implementata (commit `0979cc4`); baseline PC raccolta 2026-07-03 (vedi tabella Misure) — ⏳ baseline Fire Stick prevista settimana prossima
- [x] **Port v1.5.3** — merge da v1 (commit `e2977c8`): feature 4K/FHD + fix live setting + domini; build test 1.9.901
- [x] **FASE 1** — fix cache TMDB (hit by-ID + niente cache di errori/{}) + expire 15gg + pool enrich max 8; build 1.9.903 — ✅ TESTATA 2026-07-03: miss 40%→7,8%, richieste TMDB -41%, rete -32%. Nota: `_tmdb_get_trailer` (prippihome:5489) chiama TMDB /videos direttamente via httptools senza cache — micro-win possibile in F2/F3
- [x] **FASE 2** — riuso trasporto HTTP (adapter condiviso, gate `http_session_reuse`) + cookie-save solo su cambiamento + infobox saltato a debug off; build 1.9.904 — ✅ TESTATA 2026-07-03: nessuna regressione (play SC/AnimeUnity ok), pooling corretto (Session non chiude l'adapter). Su PC guadagno nel rumore (handshake TLS CPU-cheap su x86); payoff atteso su Fire Stick (handshake costoso su ARM) → confermare con baseline FS
- [x] **FASE 3** — snapshot su disco (home_rows_snapshot.json, TTL 12h) → riapertura = fast path istantaneo; revalidate silenzioso; cold enrich_sync capato 8→3; gate `home_snapshot`; build 1.9.905 — ✅ TESTATA 2026-07-03: riapertura paint ~0,6-0,75s vs ~5s cold (~7×), 0 errori snapshot, play da snapshot ok
- [x] **FASE 4** — memoizzazione settings per-canale/per-server (cache mtime) + mkdir fuori dal path caldo + SQLite WAL; build 1.9.906 — ✅ TESTATA 2026-07-03: WAL attivo (sidecar ok, DB integro post-kill, 0 lock/traceback), play cross-canale ok, snapshot ok. NOTE: (a) `Last_searched` prefill non ha MAI funzionato (bug preesistente dalla nascita di PrippiStream, fuori scope, → backlog v1); (b) db.sqlite già ~100MB / 18,6k voci tmdb_cache → aggiungere potatura periodica (voci >30gg + VACUUM) come item opzionale F7
- [x] **FASE 8a** — pulizia rischio zero: rimosso monitor Elementum 1Hz + watch elementum_on_seed; viewmodeMonitor 1s→3s; eliminato platformcode/backup.py (0 importatori); rimosso import INUTILIZZATO `specials.videolibrary` da paramount.py (~2.400 righe fuori dal path ricerca); settings orfane infoplus/only_channel_icons rimosse. **NOTA: specials/videolibrary.py NON cancellato** (importers vivi: autorenumber lazy :115, xbmc_videolibrary lazy ×4 → spostato a 8c); build 1.9.907 — ✅ TESTATA 2026-07-03: boot pulito, ricerca globale ok, animeunity ok; unico errore = streamingita WebErrorException PREESISTENTE (sito down, gestito)
- [x] **FASE 8b** — import lazy xbmc_videolibrary in service.py; verify_directories_created gated su `videolibrary_kodi`; update_sources(downloads) gated su `downloadenabled`; build 1.9.907 — ✅ TESTATA 2026-07-03: gate verificato (cartelle videolibrary NON ricreate — mtime 30/06, run 03/07; residue vuote eliminate a mano)
- [x] **FASE 5** — progress bar: 10 controlli/card → 1 (texture `$INFO[ListItem.Property(bar_step),progress/bar_,.png]`, 9 PNG pre-renderizzati 708×12 con colori identici — track 44FFFFFF, fill E50914; 140 blocchi collassati = **1.260 controlli in meno**: 1080i 800→80, 720p 600→60); asset: logo_banner 599→136KB (2000×416→960×200 = 2× del box 480×100), logo.png 1037→255KB (1254²→512²); rimossi PrippiHome_v7.xml (non referenziati, già esclusi dallo zip); build 1.9.908 — ✅ TESTATA 2026-07-03: "va una scheggia", barra e loghi ok, 0 errori skin nel log
- [x] **FASE 6** — `reuselanguageinvoker` + guardia `show_once` + pausa enrich bg durante play (wrapper `_wait_and_restore` con finally); build 1.9.909 — ✅ TESTATA 2026-07-03: play consecutivi ok "tutto regolare e svelto"; invoker caldo visibile nei numeri (1° play SC 2,5s → successivi 1,19-1,33s); 0 errori da stato persistente
- [x] **FASE 7** — ~~extra opzionali gated~~ **ASSORBITA nelle FASI 9-10** (2026-07-07): `hd_backdrops` → risolto in 9b senza gate (w780/w1280 fissi, impercettibile a 1080p); trim slot 40→38 → sostituito dal fix `MAX_ROWS=40` in 9a; potatura db.sqlite → promossa a FASE 9c; drop cartella 720p → follow-up post-2.0 (richiede prima la riconciliazione del drift, vedi Fatti verificati)
- [x] **FASE 8c** — chirurgia motore videolibrary (build 1.9.910): **riscritta `mark_auto_as_watched`** — il thread legacy girava per TUTTA la riproduzione in un BUSY-LOOP SENZA SLEEP (is_playing+getTime a ciclo continuo = CPU rubata al decoder, il peggio proprio su ARM) → ora campiona a 500ms; restano identici prefs lingua post-AV, soglia "visto" e salvataggio posizione in db['viewed'] (letto dal resume legacy platformtools:1549); eliminati dal path play: import di specials.videolibrary (mark_content_as_watched2), macchina next-episode legacy (next_ep() faceva un listdir della videolibrary a OGNI play di episodio — default next_ep=1!), sync Trakt, popup post-play. Rimosse `next_ep()`+classe `NextDialog` (~105 righe) e `add_next_to_playlist` (platformtools); autorenumber non chiama più update_videolibrary (ultimo import raggiungibile di specials.videolibrary — il file resta ma non viene mai più parsato nell'uso normale, import residui solo in funzioni library-gated); settings orfane next_ep/next_ep_type/next_ep_seconds rimosse (0 letture; launcher:479 legge l'ATTRIBUTO item.next_ep, non il setting) — ⏳ **DA TESTARE (zip 1.9.910)**. Checklist: (1) titolo guardato oltre l'80% → riaperto NON deve proporre resume da fine; (2) titolo a metà → resume ok (tile CW e riavvio); (3) episodio serie quasi alla fine → overlay next-episode Prippi ok; (4) lingua audio ITA ok all'avvio; (5) play CB01 multiserver → nessun popup post-play; (6) play cross-canale generale
- [x] **PRE-9 (2026-07-07, per la box di test)**: drop cartella skin 720p stale (build **1.9.929**, `f1fd194` — con GUI 720p Kodi caricava la 720p degradata: era l'item F7); diagnostica test logpush box→PC + perf_log default true (build **1.9.930**, DA REVERTARE prima della 2.0). *Le build 1.9.911-928 erano del lavoro parallelo hd4me/ricerca (già in v1.5.5).*
- [x] **FASE 9a** (build 1.9.931-932, `765acad`+`49a6f9e`) — strumentazione PERF grafica (home.hero_ms, home.row_populate_ms, home.mem_mb) + MAX_ROWS 50→40 + rimosso stub `_fetch_videos_for_rows` + `_sc_rows_cache` unificato in `_cache['data']` + throttle vixnuke 1×/24h (marker `.vixnuke_last`) — ⏳ da validare su Kodi PC
- [x] **FASE 9b** (1.9.933-935, `bae811f`+`0cd7933`+`8fcf403`) — **ESTESA a tmdb.py** (il vero punto F7): `set_infoLabels` poster/profile→**w500**, backdrop→**w1280** (le tile decodificavano original 2000×3000 e l'hero 4K a ogni focus!); CW preload→w780; detail fanart→w1280; cap FIFO 400 voci (`_cache_put`) su _trailer/_plot_it/_cw_backdrops cache; skip fetch en-US con `_looks_italian` (test standalone 10/10 su trame reali) — ⏳ da validare su Kodi PC
- [x] **FASE 9c** (1.9.936, `ecebd22`) — `_prune_tmdb_cache` nel service (voci >30gg + VACUUM se freelist>8MB, marker 24h, rispetta no-expire). **Testato su COPIA del db reale (98MB/19,2k voci): scan 1,4s, integrity ok; oggi 0 voci >30gg (db giovane, TTL 15gg ricicla) → payoff su installazioni datate**
- [x] **FASE 10a** (1.9.937, `42639bf`) — asset: quantize-256 dei 3 loghi (204→41, 136→28, 255→17 KB; verifica visiva ok), 5 orfani rimossi (~670KB), screenshot fuori dallo zip, rimosso tools/scale_1080i.py (morto: la 720p non esiste più). **Zip installabile 7,8→5,4MB**
- [x] **FASE 10b** (1.9.938, `367c659`) — hero scrim `hgrad.png` (182 byte, via lo spigolo a x=1050), dim non-focus E0FFFFFF (40 itemlayout), SET→OPZIONI / EXIT→ESCI, setting **"Animazioni ridotte (per dispositivi lenti)"** con condition sulle 80 animation zoom + `_apply_reduced_anim` live — ⏳ da validare su Kodi PC (in particolare: la condition dentro focusedlayout — piano B = doppio focusedlayout condizionale; degrado comunque graceful)
- [x] **FASE 10c** (1.9.939, `fce89e0`) — angoli arrotondati r=12 via diffuse mask (4 maschere alle dimensioni esatte dei controlli, seguono lo zoom), frame di selezione E hover box: 4 strisce → 1 anello 9-slice (masks/ring.png), barre rosse 4px rimosse, plate landscape → fill arrotondato. **Controlli: 1140→863 (-277)**, +6,4KB di maschere — ⏳ da validare VISIVAMENTE su Kodi PC (raggio 12 / anello stroke 4 regolabili a gusto)
- [x] **Giro di validazione Kodi PC delle FASI 9-10** — 2026-07-08, build 1.9.939/940 "va tutto alla grande"; fix riga TV ciclica in 1.9.940 (`3ed00d0`): slot FISSI per identità (CW=2000/DL=2010/SKY=2020/Sport=2030/TV=2040 sempre, spenta/vuota = [] al suo slot; 2040 wraplist→list; guardie sui refresh; focus su prima riga non vuota)
- [x] **Tier-3 nav-pause** (1.9.941, `52152f5`, richiesta utente dopo l'outlier 2-2,9s nei [PERF]): evento `_nav_idle` clearato a ogni onAction/onFocus + watcher daemon unico che lo ri-setta ~1,2s dopo l'ultima azione; `_bg_gate()` (pausa-dura + nav-pause, timeout anti-stallo) usato da enrich in-place, extra-source, trailer dispatcher, preload CW, refresh poster, rerender/append live. Semantica play/dialoghi invariata. Il defer "a tempo" non serve più: la pausa è guidata dal comportamento — ✅ VALIDATA su Kodi PC 2026-07-08: outlier addItems 2,9s→0,95s (1 volta), tipico 3-50ms su 30+ righe scrollate di fila, hero mediana 5ms, 0 errori
- [ ] Revert diagnostica test (perf_log default, logpush) prima del merge
- [ ] **Verifica finale end-to-end** (BOX: baseline con zip 1.9.930 archiviato vs build finale; FS quando arriva) → riporto nel repo principale → release 2.0.0

## Misure `[PERF]` (compilare)

**PC** = Windows dev (baseline 2026-07-03, build 1.9.902). **FS** = Fire Stick (non ancora disponibile). **BOX** = vecchia Android box cinese ~10$ dell'utente (2026-07-07: DISPONIBILE SUBITO — è il caso peggiore reale: con le prime versioni di PrippiStream era quasi/totalmente inutilizzabile nei menù, video però fluido = decodifica hw ok, collo di bottiglia tutto su GUI/CPU → banco di prova ideale per il progetto; requisito: Kodi 19+ sul dispositivo). Piano misure: baseline BOX con build 1.9.928 PRIMA delle FASI 9-10, poi re-test BOX a fasi finite per il delta su ARM reale; FS quando arriva.

| Metrica | Baseline (F0) | Post F1 | Post F2 | Post F3 | Post F4+8ab | Post F5 | Post F6 |
|---|---|---|---|---|---|---|---|
| Home cold: click→paint (PC) | **~4,9 s** (fetch_main 1,0-1,1s + assemble 0,04-0,08s + enrich_sync 3,5s + paint 0,2-0,3s) | ~5,1-5,3 s (invariato: enrich_sync ora CPU/SqliteDict-bound, non rete — atteso; si abbatte con F3) | | | | | |
| Home warm/snapshot: click→paint | **N/A — ogni riapertura è cold** (processo muore, cache in-memory persa: confermato, 2° open = cold identico) | idem (atteso, fix in F3) | idem | **~0,6-0,75 s** (assemble 435-495ms + paint 154-255ms; snapshot loaded, no enrich_sync) → **~7× vs cold** | | | |
| Archive fetch 21 righe (bg) | 3,7-4,1 s | 3,2-4,3 s (14-15 righe) | | | | | |
| TMDB hit-rate cache | **599 hit / 401 miss (40% miss)**; 1.291 richieste HTTP, 247 s rete cumulativi, avg 192 ms | **1.843 hit / 157 miss (7,8% miss)**; 758 req HTTP (-41%), 168 s rete (-32%), con giro più ricco (play cineblog01+trailer) | 2.089 hit / 161 miss (7,2%); 483 req TMDB, 92,7 s; latenza TMDB avg 192/mediana 149 ms (≈baseline su PC) | | | | |
| Click card→video (1° play, PC) | 1,7 s (launcher findvideos SC) | 6,8 s ma canale cineblog01 (catena uprot/maxstream) — non confrontabile con SC | SC 1,4-1,7 s · AnimeUnity 1,6 s · nessuna regressione | | | | 1° play sessione SC 2,5s (import) → **successivi 1,19-1,33s** (invoker caldo); AnimeUnity 1,28s; cineblog01 4,6s (era 6,8-8s) |
| Click card→video (play successivi) | (non misurato, 1 solo play nel giro) | | | | | | |
| Fluidità scroll (soggettiva 1-5) | PC: fluido (non indicativo — misurare su FS) | | | | | | |

Note baseline PC: workers.dev (proxy CF live) 2,7-2,8 s/richiesta; youtube (trailer) 21 req/21,6 s; SC 31 req avg 560 ms.

### Misure `[PERF]` grafica/RAM (nuove — baseline da raccogliere con la build 1.9.929 PRIMA di applicare 9a.2+)

| Metrica | Come si misura | PC (post 9-10, build 1.9.939/940, 2026-07-08) | BOX | FS |
|---|---|---|---|---|
| Focus→hero aggiornato (ms) | mark `home.hero_ms` in `_update_hero` | n=123: mediana **8 ms**, max 126 (fetch trama 1° focus ~90) | 1.9.948: mediana 55, p90 179, max 1470 ms → **1.9.949: mediana 32, p90 70, max 762 ms** | |
| Popolamento riga addItems (ms) | mark `home.row_populate_ms` | tipico **0-15 ms** (anche riga 4K da 251 item: 14 ms); outlier 2-2,9 s su 1 riga durante il flood enrich post-paint (contesa GIL/rete — candidato Tier-3 defer, da guardare su ARM) | 1.9.948: mediana 352, p90 6988, max 29417 ms → **1.9.949: 202 / 357 / 1108 ms** | |
| RAM sistema al paint / post-enrich | mark `home.mem_mb` (System.Memory used — su PC rumorosa, significativa sul BOX 2GB) | 12,4→13,2 GB (PC 32GB, delta ~0,2-0,45 GB con tutto il sistema) | 1.9.948: 855 / 1064 MB → **1.9.949: 821 / 827 MB** (1976 MB totali) | |
| Warm reopen (assemble+paint) | mark esistenti F3 | 0,55-1,2 s (3 riaperture: 387+164 / 805+125 / 673+414 ms) ≈ baseline F3 | 1.9.947 ~14,06 s; 1.9.948 primo 9,42 s, seconda 3,16 s → **1.9.949 primo post-riavvio 2,873 s** | |
| FPS durante scroll righe | overlay debug Kodi, zoom on/off | n/a su PC | | |
| Peso zip installabile (MB) | file in docs/ | **5,4 MB** (era 7,8) | = | = |

Note validazione PC 2026-07-08 (build 1.9.939 "funziona tutto" + 1.9.940 fix riga TV): throttle vixnuke ATTIVO nel log ("throttled <24h, skipping"); prune eseguito e rispettoso del setting utente (`no_expire=True` → 0 potate, VACUUM saltato con 0MB liberi); tmdb cache ~3% miss; zero errori getControl/skin; gli errori nel log sono i preesistenti (titoli assenti su TMDB, probe live flaky).

Procedura FS per gli FPS: attivare l'overlay debug, scorrere 10 righe su/giù a
velocità costante, annotare FPS min/typ; ripetere con "Animazioni ridotte" ON.
Confronto anche RAM totale Kodi da Impostazioni→Info sistema durante lo scroll.

---

## FASE 0 — Strumentazione di misura

- Nuovo `platformcode/perf.py`: `ENABLED` da setting nascosto `perf_log`
  (default false); `mark(tag, t0=None)` logga `[PERF] tag: N ms` a `LOGWARNING`
  (visibile senza debug Kodi). Overhead ~zero da spento.
- Setting `perf_log` in resources/settings.xml (nascosto, come `tmdb_cache`).
- Punti misurati: `_bg_load_inner` (enter → fetch → assemble → enrich → paint),
  `_bg_load_archive` (fine fetch), `tmdb.cache_response` (hit/miss ogni 50),
  `httptools.downloadpage` (per-richiesta, usa `inicio` esistente),
  `launcher.run()` (ingresso/fine dispatch).

**Test**: `perf_log=true` → cold start + 1 play → raccogliere kodi.log (baseline).
Con setting off: comportamento identico. **Rollback**: setting off.

## FASE 1 — Fix cache TMDB + pool enrich limitato

File: core/tmdb.py, resources/settings.xml

1. `cache_response.wrapper` (:123-143) — hit = riga esiste + non scaduta +
   payload valido:
```python
def _cacheable(res):
    return (bool(res) and isinstance(res, dict)
            and 'status_code' not in res
            and ('results' not in res or res.get('results')))

row = db['tmdb_cache'].get(url)
if row and check_expired(row[1]) and _cacheable(row[0]):
    result = row[0]
else:
    result = fn(*args)
    if _cacheable(result):
        db['tmdb_cache'][url] = [result, datetime.datetime.now()]
```
2. `tmdb_cache_expire` default `"4"`→`"2"` (15 giorni) in settings.xml:71.
3. `set_infoLabels_itemlist` (:220): `ThreadPoolExecutor(max_workers=max(2, min(8, (os.cpu_count() or 4))))`.

**Test**: cold start (metadati identici); 5+ schede dettaglio; riavvio Kodi →
più veloce + hit-count `[PERF]`; ricerca titolo senza TMDB; play da CW.
**Rollback**: revert blocco wrapper.

## FASE 2 — Riuso trasporto HTTP + cookie dirty-check

File: core/httptools.py, resources/settings.xml

- Pool module-level di `CipherSuiteAdapter` condivisi, chiave
  `(verify, override_dns)`, `pool_connections=16, pool_maxsize=8`;
  `requests.session()` resta fresca per chiamata. Gate: setting nascosto
  `http_session_reuse` (default true), ramo legacy intatto per rollback.
- Percorsi cloudscraper / `use_requests` / directIP / proxytranslate invariati.
- `save_cookies` solo se la firma del jar è cambiata
  (hash di `(domain,path,name,value,expires)` ordinati).
- Skip `fill_fields_pre/post` (info_dict) quando `debug` è false.

**Test**: cold load, scroll, Sfoglia, Ricerca; play SC film/episodio, AnimeUnity,
live, 4K; toggle `resolver_dns`; offline; `http_session_reuse=false`;
delete cookies.dat → ricompare. **Rollback**: `http_session_reuse=false`.

## FASE 3 — Snapshot disco righe home + cold paint economico

File: platformcode/prippihome.py, settings.xml (gate `home_snapshot` default true)

1. `<data_path>/home_rows_snapshot.json`: `{"version","ts","host","rows":[[label,[item.tojson(),...]]]}`
   — solo righe SC main+archive (CW/download/live/4K/anime sempre fresche).
   Scrittura atomica temp+rename in thread bg. Stima 2-6 MB.
2. Scrittura: dove oggi si setta `_cache['data']` (`_bg_load_archive` :1092/:1120)
   + a fine passata `_bg_enrich_inplace(0)`.
3. Lettura in `_bg_load_inner` (se `_cache['data'] is None`):
   - età<1800s → alimenta `_cache` → fast path esistente;
   - 1800s–24h (o host diverso) → **paint-then-revalidate**: render SUBITO da
     snapshot (salta enrich sync, righe già `_enr`), refresh in bg + riconcilia;
   - ≥24h/corrotto → cancella file, cold path attuale.
4. `_swap_refreshed_rows(fresh_rows)`: enrich → match per label → se diversa,
   swap sotto `_rows_lock` + `_refresh_row_cards(idx)` (:1309, primitiva esistente);
   nuove label → append; sparite → resta la stale.
5. Cold puro: `_enrich_visible_rows_sync` `max_rows=8`→`3`.

**Test**: primo avvio = come oggi; riapertura >30min → paint quasi immediato,
poster HD corretti, refresh bg (log), click+play immediato durante il load;
CW aggiornato al riavvio; senza rete → paint da snapshot.
**Rollback**: `home_snapshot=false`; auto-delete file su errore.

## FASE 4 — Memoizzazione settings + SQLite WAL

File: core/channeltools.py, core/servertools.py, core/__init__.py

1. `get_channel_setting`/`get_server_setting`: cache `{nome:(mtime,dict)}`,
   validata con `getmtime` (stat); `set_*` invalida. `exists/mkdir` di
   settings_servers solo nel ramo miss. Nota: granularità mtime 2s su FAT —
   unico rischio è `Last_searched`, accettabile (documentare).
2. `SqliteDict(db_name, table, 'c', True, journal_mode='WAL')`.

**Test**: cambio setting canale da UI (effetto+persistenza); blacklist server;
play + ricerca; presenza `db.sqlite-wal`; comportamento post kill duro.
**Rollback**: revert (SQLite riconverte da solo).

## FASE 8a — Pulizia Stream4me: rischio zero

1. Eliminare `specials/videolibrary.py` + `platformcode/backup.py`
   (prima: grep dispatch `'videolibrary'`/`'backup'` nei percorsi vivi; ripulire
   import lazy nei blocchi morti di launcher.py :123-135, :434 leggendo il contesto).
2. Rimuovere scheduling `torrent.elementum_monitor` (service.py:189) + watch
   `elementum_on_seed` (:138-140). La funzione resta in torrent.py.
3. `viewmodeMonitor`: `every().second` → `every(3).seconds`.
4. Settings orfane via da settings.xml: `infoplus`, `only_channel_icons`,
   `s4me_menu` (ri-verificare 0 refs).

**Test**: boot pulito; home+play; animeunity episodi (autorenumber intatto);
grep import dei file eliminati = 0.

## FASE 8b — Pulizia Stream4me: lavoro morto all'avvio

1. `service.py:28`: `xbmc_videolibrary` da import module-level → lazy dentro
   `onNotification` (:165) e blocco migrazione (:283/:301).
2. `config.verify_directories_created`: ramo videolibrary gated da
   `videolibrary_kodi` (niente `search_library_path` JSON-RPC, niente ricreazione
   `videolibrary/Film/Serie TV`, niente `update_sources(videolibrarypath)`).
   Parti downloads INTATTE.

**Test**: riavvio ×2 (service ok, keymap ok); cartelle videolibrary non ricreate;
download offline ok; play+CW normali.

## FASE 5 — Skin: progress bar collassata + dieta asset

1. 9 PNG `resources/skins/Default/media/progress/bar_1..9.png` (708×12, track
   bianco 0x44 + fill `E50914` al N×10%). Nei template riga: i 10 controlli
   itemlayout (:281-290) → 1 solo:
   `<texture>$INFO[ListItem.Property(bar_step),progress/bar_,.png]</texture>`
   (left 8/top 197/width 354/height 6); focusedlayout uguale (left 4/width 362).
   Stessa edit su 720p. Zero modifiche Python.
2. Re-export: logo_banner.png→960×200; logo_prippistream.png→2× box;
   logo.png→512×512. NON toccare screenshot-*.
3. Cancellare `PrippiHome_v7.xml` (legacy non referenziato).

**Test**: titolo al ~37% → barra identica (focused/unfocused, CW e righe normali);
step 1 e 9; item senza progresso; scroll più fluido; loghi identici.
**Rollback**: git revert XML+asset.

## FASE 6 — Play path: riuso interprete + micro-stop

1. `<reuselanguageinvoker>true</reuselanguageinvoker>` in addon.xml (rischio
   medio: stato module-level persistente — cj, adapters, otmdb_global, dict
   servertools, host canali, core.db si auto-ripristinano; documentare che
   DEBUG_ENABLED/timeout restano quelli d'import).
2. `launcher.py:40` (e :313): `set_setting('show_once', True)` solo se non già true.
3. Pausa enrich bg durante lancio play: `_bg_ui_pause.clear()` in `_launch`
   (:2377), `set()` in `finally` di `_wait_and_restore` (:2601) con timeout 60s;
   wait-pattern nei due loop di enrich.

**Test**: 5 play consecutivi cross-canale; resume/next-episode/lingue;
focus restore; cambio setting → re-render; exit durante playback senza freeze.
**Rollback**: revert riga addon.xml.

## FASE 7 — ASSORBITA (vedi Stato fasi)

Gli item sono confluiti in: 9a (MAX_ROWS al posto del trim slot), 9b (backdrop
w780/w1280 senza gate), 9c (potatura db). Drop cartella 720p → post-2.0.

---

# FASI 9-10 — Alleggerimento + estetica HOME (aggiunte 2026-07-07)

> Derivate dall'analisi senior grafica/design/funzionale della home (colli di
> bottiglia 12-19). Si implementano SUBITO in attesa del test Fire Stick della
> 1.9.910: il giro FS validerà poi 8c+9+10 tutto insieme. Ordine ottimizzato:
> prima il py (9a→9b→9c, raggruppato per file), poi asset (10a), poi estetica
> (10b→10c). Ogni fase = 1-2 commit, bump build, test su Kodi PC.

## FASE 9a — Home: PERF grafica + fix sicuri + igiene runtime (build 1.9.929-930)

File: platformcode/prippihome.py, platformcode/perf.py

1. **PERF grafica** (commit 1, build 1.9.929 — raccogliere la baseline PC PRIMA
   del resto): mark `home.hero_ms` in `_update_hero`; `home.row_populate_ms`
   attorno ad addItems in `_populate_single_row`; `home.mem_mb` via
   `xbmc.getInfoLabel('System.Memory(used)')` al paint e a fine
   `_bg_enrich_inplace`. Compilare la tabella "Misure grafica/RAM".
2. **MAX_ROWS 50→40** (:473) + commento corretto ("40 slot statici nel 1080i,
   id 2000-2390 step 10"). Usi verificati tutti `min()`/`range()` → sicuro.
3. **Rimuovere `_fetch_videos_for_rows`** (:6074-6076, stub `pass`, 0 chiamanti).
4. **Unificare `_sc_rows_cache` → `_cache['data']`**: eliminare la global :204,
   sostituire le letture :1239-1241 e :2537, rimuovere assegnazioni
   (:1208, :1317-1319, :1550, :1575) e `global` orfani (`_cache` è solo mutato,
   mai ribindato → nessun `global _cache` necessario).
5. **Throttle `_nuke_all_vixcloud_bookmarks`** (commit 2, build 1.9.930):
   guardia a inizio funzione con marker `.vixnuke_last` in
   `config.get_data_path()` (pattern `_purge_legacy_videolibrary` :10799);
   skip se mtime <24h, touch a fine corsa. La pulizia puntuale per-play
   `_clear_kodi_resume` (:5087) resta e copre i bookmark in-sessione.

**Test**: `py -m py_compile`; `grep -c _sc_rows_cache`=0; scroll completo 40
righe; toggle live righe SKY/Sport/TV a home aperta (esercita :2537); riapertura
warm <30min; guardare a metà un episodio SC → riaprirlo senza dialog resume
Kodi; 2ª apertura → log skip vixnuke; log senza errori getControl.
**Rollback**: revert per punto.

## FASE 9b — Home: rete/RAM più leggere (build 1.9.931-933)

File: platformcode/prippihome.py

1. **Backdrop ridimensionati** (1.9.931): :167 `t/p/original`→`w780`
   (URL CONDIVISA preloader/slideshow — vedi Fatti verificati); :6978
   `_load_hd_fanart` `original`→`w1280`. Se la resa TV non convince in test:
   ripiego w1280 anche su :167.
2. **Cap cache module-level** (1.9.932): helper
   `_cache_put(d, key, val, cap=400)` con eviction FIFO (dict ordinati Py3.7+)
   sui punti di scrittura di `_trailer_cache` (:6059), `_plot_it_cache`
   (:2138, :2145, :6995, :6999), `_cw_backdrops_cache` (:171). NON toccare i
   `pop()` esistenti (:2143, :2155). Nota: `_plot_it_cache[tid]=''` è
   sentinella "fetch in corso" — l'eviction = al più un doppio fetch, innocuo.
3. **Skip fetch en-US hero plot** (1.9.933): in `_get_it_overview`, dopo
   :5470: `if it_ov and _looks_italian(it_ov): return it_ov`. Helper
   `_looks_italian` = ≥2 stopword italiane distinte (' il ',' la ',' di ',
   ' che ',' un ',' una ',' della ',' gli ',' più ',' è ',' anche ',' nel ')
   E nessun marker inglese forte (' the ',' and ',' with ',' his ',' her ').
   Check fallito → percorso attuale invariato (fetch en-US + translate).
   **Test standalone PRIMA nello scratchpad** con ~10 trame reali it/en
   (incluse trame en con "di" nei nomi propri).

**Test**: trama hero in italiano su vari titoli; 1 titolo senza traduzione IT
su TMDB → deve ancora passare da `_translate_to_it` (log); slideshow detail CW
istantaneo (conferma URL preload coerenti); `home.mem_mb` ≤ baseline; sfondo
detail nitido a distanza-divano. **Rollback**: revert per punto.

## FASE 9c — service: potatura giornaliera db.sqlite (build 1.9.934)

File: service.py

Nuova `_prune_tmdb_cache()`: (a) marker `.tmdb_prune_last` <24h → return;
(b) attesa iniziale ~120s con `Monitor.waitForAbort` (non competere col boot);
(c) se `tmdb_cache_expire == 4` ("no expire", core/tmdb.py:128-130) → NIENTE
potatura (scelta utente), solo VACUUM condizionale; (d) potatura voci >30gg via
`db['tmdb_cache'].iteritems()` (streaming; formato voce `[result, datetime]`,
tmdb.py:168) con try/except per-entry e `xbmc.sleep(0)` ogni ~500 voci;
(e) VACUUM con connessione raw `sqlite3.connect(db_path, timeout=30)` +
`PRAGMA busy_timeout=30000`, SOLO se `freelist_count*page_size > 8MB`
(WAL-compatibile; SQLITE_BUSY tollerato → log e riprova domani); (f) touch
marker a fine corsa. Registrazione: `schedule.every().day.do(run_threaded,
_prune_tmdb_cache, ())` accanto a :324 + run al boot (il marker rate-limita);
`run_threaded` è già tracciato da `join_threads()` pre-reload (:369).

**Test standalone PRIMA**: copia del db.sqlite reale (~100MB) nello scratchpad
+ script con lib.sqlitedict del repo → voci potate e size before/after VACUUM.
In Kodi: riavvio → dopo ~2min log riepilogo prune; cache TMDB funzionante
(`[PERF] tmdb.cache` hit); 2° riavvio → skip da marker.
**Rollback**: rimuovere la schedulazione.

## FASE 10a — Asset & packaging (build 1.9.935)

File: resources/media/, resources/skins/, tools/

1. **Ricompressione** (script Pillow one-off nello scratchpad, NON committato):
   `media/logo_prippistream.png` 204KB→≤30KB e `logo_banner.png` 136KB→≤40KB
   via `quantize(colors=256, method=FASTOCTREE)` + `optimize=True` (fondi scuri
   → quantizzazione invisibile); `logo.png` 255KB: prima SOLO optimize lossless
   (è l'icona dello store — quantizzare solo se indistinguibile a zoom 200%);
   mai ridimensionare (Kodi vuole 512×512).
2. **Eliminare 5 orfani** (~670KB, zero refs ri-verificati fuori da docs/):
   `skins/Default/1080i/logo_prippistream.png`,
   `skins/Default/720p/logo_prippistream.png`,
   `media/logo_prippistream_sm.png`, `media/dark-logo.png`,
   `media/light-logo.png`.
3. **make_addon_zip.py**: aggiungere screenshot-1/2/3.png a `exclude_names`
   (:25) — lo store GitHub li legge dal repo git, non dallo zip (~1,5MB).
4. **scale_1080i.py**: path relativi allo script (pattern make_addon_zip) +
   guardia anti-disastro (conta wraplist 2xxx in SRC e DST; SRC<DST → exit con
   messaggio) + commento-warning sul drift 720p/1080i. NON eseguirlo.

**Test**: confronto visivo before/after dei 3 PNG; `git status` pulito; zip
-~2,5MB, listato senza screenshot/orfani/tools; in Kodi overlay caricamento,
banner (Home/Browse/Search/EpisodePicker) e icona ok. Se un logo appare
"vecchio" → è la texture cache di Kodi (Textures13.db), non un bug.
**Rollback**: git revert asset.

## FASE 10b — Estetica: hero scrim + micro-polish + "Animazioni ridotte" (build 1.9.936-937)

File: PrippiHome.xml (1080i E 720p, edit testuali — MAI scale_1080i),
resources/settings.xml, platformcode/prippihome.py, changelog.txt

1. **Hero scrim a gradiente** (il miglioramento visivo più forte): Pillow
   genera `hgrad.png` (~480×8, nero con rampa alpha 230→0, <1KB) in
   `skins/Default/media/`; sostituisce l'overlay piatto `900D0D0D` 1050×486
   (1080i:40-44 + equivalente 720p) con il gradiente stretchato (width ~1250
   nel 1080i) → sparisce lo spigolo verticale a x=1050, hero stile Netflix.
   Costo runtime identico (1 texture come prima). Opzionale: sottile fade
   verticale sul bordo basso dell'hero verso le righe.
2. **Dim poster non a fuoco**: `colordiffuse="E0FFFFFF"` sulle texture
   poster/fanart_image degli `itemlayout` (portrait+landscape, entrambi i
   file) → la card a fuoco (100% + zoom + frame) stacca di più. Se troppo
   scuro in test → alzare a E8/F0.
3. **Micro-copy italiano**: `[B]SET[/B]`→`[B]OPZIONI[/B]` (1080i:102, 120px ok
   con font10) e `[B]EXIT[/B]`→`[B]ESCI[/B]` (1080i:119) — coerenza con
   "Ricerca…"/"Sfoglia".
4. **Setting "Animazioni ridotte (per device lenti)"** (`reduced_animations`,
   bool, default false) in settings.xml sezione Personalizzazione (niente
   emoji). prippihome.py: aggiungere a `_LIVE_SETTING_KEYS` (:209); set/clear
   `self.setProperty('reduced_anim','1')` in onInit (FUORI dal blocco
   first-run) e in `_apply_live_settings` (:2524) → effetto immediato senza
   riavvio (regola live-settings; `_read_live_settings` usa già
   `xbmcaddon.Addon()` fresco). XML: aggiungere
   `condition="String.IsEmpty(Window.Property(reduced_anim))"` alle 40+30
   coppie zoom (replace testuale delle 2 righe uniformi; NON toccare la coppia
   del bottone EXIT). **Test empirico obbligatorio** della condition dentro
   focusedlayout; piano B se ignorata = doppio `<focusedlayout condition>`
   (Kodi 18+); degrado comunque graceful (condition ignorata = zoom sempre
   attivo, zero crash).
5. changelog.txt: nota utente in `## Prossima`.

**Test**: well-formedness (`ET.parse` su entrambi gli XML); conteggi condition
= 80 nel 1080i / 60 nel 720p, totale zoom invariato; toggle a home aperta →
zoom sparisce/torna SUBITO; fanart chiara a fuoco → titolo/trama leggibili
senza spigolo; contrasto focus/non-focus gradevole; OPZIONI/ESCI.
Gotcha noto: cambiando il toggle con un poster zoomato, il primo movimento può
fare uno scatto secco — si normalizza subito, nessuna azione.
**Rollback**: revert commit.

## FASE 10c — Estetica: angoli arrotondati card (build 1.9.938, OPZIONALE)

File: PrippiHome.xml ×2 + nuove maschere PNG

Le card sono rettangoli vivi; le UI streaming moderne usano raggi 8-12px.
Tecnica Kodi = **diffuse mask**: Pillow genera maschere rounded-rect bianche
alle dimensioni ESATTE dei controlli immagine (poster 262×330 / 268×330,
landscape 362×200 / 258×160…, <1KB l'una, in `skins/Default/media/masks/`) —
la diffuse si stretcha sul controllo, quindi la maschera deve avere lo stesso
aspect per non deformare i raggi. Applicare `diffuse="masks/<nome>.png"` alle
texture card (itemlayout + focusedlayout). Il frame di selezione a 4 strisce
dritte (1080i:346-349) stonerebbe sugli angoli tondi → sostituirlo con UNA
image con `<bordertexture border="N">` a cornice arrotondata 9-slice =
**-3 controlli/riga ≈ -120 controlli nel 1080i** (estetica E alleggerimento).

**Test**: iterazione visiva su Kodi PC (raggio, spessore cornice, resa su
poster scuri SKY/Sport); FPS/scroll su FS al giro di validazione.
**Rollback**: revert del singolo commit (nessuna dipendenza dalle altre fasi).

## FASE 2 ARM — Alleggerimento guidato dai log BOX (build 1.9.949)

Baseline: log BOX 1.9.948 del 2026-07-14/15. La GUI è veloce quando il
background è quieto; il collo di bottiglia è la partenza simultanea di
popolamento, enrichment, TMDB, trailer e probe live. Implementazione completata
e validata sulla BOX con la 1.9.949 (log del 2026-07-15).

1. **Popolamento su richiesta sui dispositivi non touch**: dopo il primo paint
   non vengono più creati i `ListItem` di tutte le 36 righe. `onFocus` prepara
   solo la riga raggiunta e le vicine. Il populater completo resta esclusivamente
   per il touch, dove lo swipe verticale non genera focus.
2. **Profilo automatico low-power (RAM <= 3 GB)**: enrichment pesante in una
   sola corsia, massimo 2 worker TMDB e 3 worker nella ricerca globale. Sul PC
   rimangono i valori validati. Fetch dei pool film/serie seriale e dedup delle
   richieste identiche già in corso.
3. **Canali live dopo il paint**: mostra subito la cache; probe solo dopo il
   primo disegno e 5 secondi senza navigazione. Sulla BOX le tre righe vengono
   controllate in sequenza con 4 worker bounded, senza cambiare resolver o
   DaddyLive. Un HTTP 403 Daddy resta distinto dal precedente errore SSL.
4. **Trailer lazy**: eliminato il prefetch YouTube/proxy della home. La
   `DetailWindow` continua a cercare il singolo trailer su richiesta. Sulla BOX
   è disattivato anche il preload texture dei backdrop CW; il dettaglio li
   recupera quando serve.
5. **ListItem leggeri**: le card home usano proprietà skin + `InfoTagVideo`
   diretto; rimosso il `setInfo('video')` per-card che generava centinaia di
   warning Kodi 21. Resume point e playcount CW restano sull'InfoTag.
6. **Cache persistente e negativa**: pool extra-source serializzati per 6 ore;
   query TMDB valide con zero risultati cachate per 6 ore; richieste TMDB
   identiche in-flight condivise. Errori di rete e payload vuoti non vengono
   cachati, quindi continuano ad auto-ripararsi.
7. **Riga 4K opzionale**: nuova impostazione live `show_4k_row`, default OFF.
   L'indice e il lookup 4K restano attivi per film normali e ricerca, ma la home
   non aspetta più fino a 8 s e non crea oltre 250 card. Se attivata, la riga si
   inserisce senza bloccare il paint e si riempie appena l'indice è pronto.
8. **Cronologia ricerca**: ultime 10 query locali, deduplicate senza distinzione
   maiuscole/minuscole, selezionabili prima della tastiera e cancellabili con
   conferma. Scrittura JSON atomica nel profilo Kodi, mai nel pacchetto addon.

**Checklist BOX 1.9.949**: Debug OFF e `perf_log` ON; riavvio; home ferma 2 min;
scroll completo; seconda apertura; toggle riga 4K OFF/ON/OFF senza riavvio;
due ricerche nuove + riuso recente + cancellazione; dettaglio/trailer; un film
SC; 5 episodi consecutivi per autoplay/lingua; live SKY/Sport/TV. Inviare i log
solo alla fine e confrontare assemble/paint, p90 righe, picco RAM e richieste
TMDB con la tabella BOX sopra.

**Esito BOX 1.9.949**: home warm completa **2,873 s** (assemble 2,408 s +
paint 465 ms), contro 9,42 s sulla 1.9.948 e ~14,06 s sulla 1.9.947. RAM
post-enrich **827 MB** contro 1064 MB; righe mediana **202 ms**, p90 **357 ms**,
massimo **1,108 s** contro 352 ms / 6,99 s / 29,4 s. Nessun popolamento totale
in background, nessun crash/OOM/errore apertura codec. Autoplay The Office
1→2→3→4 e preferenze lingua/sottotitoli validati; trailer lazy e live differiti
confermati. La riga 4K è nascosta e l'indice da 252 film resta disponibile;
rimane da provare il toggle live OFF/ON/OFF. Daddy restituisce HTTP 403, non un
errore CA; prova su altra rete differita. I messaggi MediaCodec coincidono con
seek manuali e non hanno interrotto la riproduzione.

**Passo 1.9.950 — quiet logging e riuso ricerca**:
- `debug` resta default OFF e una migrazione una tantum spegne il valore legacy
  che il vecchio invio-log aveva lasciato attivo; il pulsante non lo riaccende
  più. `perf_log`, `[PERF]` e `[NET]` restano indipendenti e attivi nella build.
- Rimossi i vecchi `xbmc.log(... LOGINFO)` diagnostici della schermata ricerca.
- Cache per-sessione e per-provider delle stesse query, TTL 15 minuti, massimo
  80 coppie provider/query. Anche un risultato vuoto viene riusato per la stessa
  query, evitando di martellare una fonte guasta quando si sceglie la cronologia;
  query diverse continuano a interrogare tutte le fonti. Gli `Item` vengono
  serializzati e ricostruiti per non condividere stato mutabile.
- Misura dedicata: `[PERF] search.provider_cache hit=N miss=N query=...`.

## Sequenza attiva: Kodi 1.9.988 + app 0.9.11 → RC combinata → linea 2.x

Il documento di design chiamato storicamente “V3” non è una codebase separata:
è assorbito in questa stessa linea v2, che diventa 2.0 e cresce a 2.1/2.2/2.3.

### Gate 1 — Validazione Kodi 1.9.988 sulla box

1. Installazione esclusivamente da zip locale e riavvio Kodi.
2. Debug generico OFF; errori/traceback/warning e `[PERF]/[NET]` presenti.
3. Home e scroll; ricerca nuova e riuso dalla cronologia; cancellazione storia;
   riga 4K OFF→ON→OFF; trailer, VOD, live e invio log senza riaccendere debug.
4. Raccogliere log `(5)` e confrontare home/RAM/righe/cache ricerca. Fare una
   1.9.987 solo se i log dimostrano una regressione.

### Gate 2 — Freeze e release candidate ZIP + APK

1. Test end-to-end Kodi PC + box e app telefono + box TV; tablet/emulatore e
   Xiaomi Stick consigliati se disponibili.
2. `perf_log` default false; rimuovere/disattivare logpush verso IP locale e
   TouchProbe. Il codice PERF può restare inerte e il debug manuale resta utile.
3. Audit `.claude`, log, credenziali, IP test, URL, import, JSON/XML, ZIP e APK;
   per l'app verificare anche manifest, permessi, ABI, firma e revisione motore.
   Nessun errore deve dipendere dal debug generico per essere visibile.
4. Audit v1→v2 e trasferimento selettivo v2→v1, preservando i `git rm` del
   cleanup. Vietata una copia additiva che resusciti file eliminati.
5. Kodi 2.0.0 più versione app adattiva approvata, changelog comune con sezioni
   client, ZIP/APK finali e installazione su dispositivi reali. Prima della
   pubblicazione mostrare e far approvare note e hash all'utente.

### Gate 3 — Deploy coordinato Kodi 2.0 + app adattiva

Solo su comando esplicito: staging dei file nominati (mai `git add -A`), commit,
push, verifica CI, feed Kodi, ZIP, APK, firma e aggiornamenti reali dei due
client. Rollback indipendente e monitoraggio dei primi log.

### Dopo 2.0, sempre nella stessa v2→2.x

- **2.1 prestazioni residue:** DB a soglia/VACUUM, skin `<include>`, lazy import,
  audit `lib`, circuit breaker solo su errori certi, SSL `popcdn.day`; bytecode
  soltanto dopo verifica delle ABI Python Kodi e con fallback sicuro.
- **2.2 sicurezza fondamentale:** fingerprint device, verifica Ed25519, stato
  monotono, policy/revoche firmate, grazia offline fail-open, attivazione e
  registrazione Telegram. Nessun blocco per semplice timeout rete.
- **2.3+ protezione/distribuzione:** consegna e wrapping device-bound di
  `K_engine`, loader/build `.pye` con decifratura in RAM, sorgente privata e feed
  pubblico separato con migrazione sicura degli utenti esistenti.
- **App adattiva:** non è lavoro “dopo 2.0”; partecipa alla stessa finestra di
  rilascio. Dopo la baseline combinata proseguono copertura dispositivi,
  accessibilità e parità avanzata in `PrippiStreamApp`.
- Prima della cifratura/protezione proprietaria: decisione esplicita sulla
  licenza del codice proprio e conservazione delle attribuzioni di terzi.

## FASE 8c — Chirurgia motore videolibrary (DIFFERITA)

Solo dopo la validazione di tutte le fasi perf, con giro di test dedicato:
1. Severare rami `strm`/`next_ep` in `platformtools.set_player`/`add_next_to_playlist`.
2. Rimuovere funzioni morte in `xbmc_videolibrary.py` (tenere `set_watched_on_addon`,
   `execute_sql_kodi`, `update_sources`, `search_library_path`).
3. Potare `videolibrarytools.save_tvshow` + import lazy residui (generictools
   :952/:1583/:1286 — verificare prima i path NFO dei canali vivi).
4. Infine: via le settings videolibrary nascoste, letture → default hardcoded.

## NON-goals (protezione zero-regressioni)

- NON toccare: regex scraper, findvideos/play dei canali, resolver `servers/*`,
  unshortenit, captcha OCR, crypto download/native_aes, catene live
  (sportchannels/skyepg/DaddyLive), tier proxytranslate/cloudscraper, proxy CF.
- NON rimuovere `lib/httplib2` / `lib/sambatools` (usati).
- NON toccare `support.py:callAds` (inerte).
- Mantenere gli sleep tattici (80ms/130ms/600ms/250ms): correttezza su ARM.
- Nessuna ri-architettura del dispatch RunPlugin / `_wait_and_restore`.
- `autorenumber` è VIVO (animeunity/aniplay/vvvvid/paramount) → non toccare.

## Workflow per fase

1. Implementazione in questa cartella; un commit git locale per fase.
2. Build: bump `1.9.9xx` in addon.xml → `python tools/make_addon_zip.py`
   (o copia diretta in `%APPDATA%\Kodi\addons\plugin.video.prippistream` sul PC).
3. Se cambia il motore condiviso: controllare/sincronizzare l'app, eseguire
   test Android, Gradle/lint e identificare l'APK risultante.
4. Test con la checklist Kodi + app pertinente e confronto delle misure.
5. Checkbox e numeri nei documenti tecnici e nel master, poi fase successiva.

## Verifica finale end-to-end

1. Kodi Windows: cold/warm start, snapshot path, scroll completo, Sfoglia,
   Ricerca, 5 play cross-canale, download offline, live, One Piece, gate 18+.
2. Estetica (FASI 10b/10c): hero senza spigolo con fanart chiare, contrasto
   focus/non-focus, OPZIONI/ESCI, toggle "Animazioni ridotte" live, angoli
   tondi uniformi portrait+landscape (se 10c tenuta).
3. Igiene runtime (FASI 9x): log skip vixnuke alla 2ª apertura; riepilogo
   prune db nel log del service + skip al riavvio successivo.
4. Device lento (Fire Stick): valida 8c + FASI 9-10 TUTTO INSIEME — confronto
   `[PERF]` vs baseline, incluse le metriche grafiche/RAM nuove e gli FPS
   overlay con zoom on/off.
5. `tools/test_*.py` verdi dove applicabili.
6. App: regressione telefono/tablet, stress D-pad box, VOD/live/download,
   updater, diagnostica, RAM/frame/focus e confronto sulla stessa box.
7. Riporto nel repo principale (prima: allineamento fix v1.5.x → v2 con
   `git fetch <path-v1>` + cherry-pick, vedi memoria di progetto) →
   versione 2.0.0 + APK approvata → release coordinata.

## Addendum 26 luglio 2026 — box 1.9.970–1.9.973 e passaggio app TV

- 1.9.970: popolamento eager e righe da 55–70 card bloccavano la GUI per minuti.
- 1.9.971: corretto falso touch ed espansione extra, ma snapshot storico e
  rivalidazione continuavano a saturare la box.
- 1.9.972: massimo 20 card/riga low-power, niente popolamento globale,
  rivalidazione o TMDB Home; miglioramento netto percepito sulla box.
- Problema residuo live 1.9.972: i 20 secondi di quiete continua causavano
  starvation; nella sessione non è partito alcun probe.
- 1.9.973: margine fisso 8 secondi e ordine TV → SKY → Sport.
- 1.9.973: retry automatico unico SC/VixCloud se il manifest cade prima
  dell'avvio A/V, con nuova risoluzione e token fresco.
- Build e server Range verificati; test reale box 1.9.973 pendente.

Decisione prodotto: Kodi resta fallback mentre l'app Android esistente
`com.prippi.stream` viene estesa a tablet, Android TV, Google TV e box con UI
D-pad dedicata. Il motore v2 resta autorevole e condiviso. La roadmap operativa
TV è in `PrippiStreamApp/APP_ROADMAP.md` (M8) e `TV_APP_HANDOFF.md`.
## Candidate di chiusura Milestone 2 — 1.9.986

La 1.9.986 è la build unica da usare per l'ultimo confronto box. Il gate PC è
superato: mapper, seek VOD e chiusura ordinaria; prima apertura pulita 1,91 s
durante la generazione bytecode, poi ingresso normale 1,10 s, assemble warm
807 ms e paint 151 ms. Il caricamento della cache Film 4K,
misurato a circa 354 ms, è ora differito dopo il primo paint quando la riga
opzionale è disattivata. Il
packaging è stato reso deterministico e non include più log di laboratorio,
materiale Codex, APK o bytecode. Due build consecutive hanno prodotto lo stesso
SHA-256:
`3D13D176055BB8C6FFF4B2BF0CB1A47FE79BDE87C1C89483C93A1CC1B40C820D`.

Gate statico completato:

- 887 Python attivi compilabili con Python 3;
- 28 XML e 140 JSON validi;
- test changelog, download crypto, HLS, download manager e local stream server;
- ZIP da 5.420.451 byte, 1.269 entry, CRC valido e nessun duplicato;
- misure `[PERF]` degli import Home aggiunte;
- versione Python aggiunta automaticamente ai report diagnostici.

I primi gate fisici della stessa finestra sono ora parzialmente completati:

1. Kodi box: Home navigabile durante enrich, RAM/Python, live e telecomando;
2. app 0.9.11 sulla stessa box: installazione ARM32, Home/focus, Live/audio,
   VOD SC e sessione superiore a 71 minuti senza nuovi crash/ANR superati;
   restano stress D-pad reale, download e updater;
3. regressione breve app su telefono e tablet/emulatore.

Nota sync: la 0.9.11 corrente precede ancora alcune modifiche motore 1.9.988.
`sync_engine.py --check` rileva +1/~7 file motore e ~1 asset divergenti. Dopo
la validazione della sorgente v2 sporca serviranno sincronizzazione autorizzata,
nuova APK e ripetizione dei test toccati prima della coppia RC.
