# PrippiStream 2.0 — Roadmap ottimizzazione prestazioni

> **Documento di lavoro** del progetto v2.0. Si aggiorna a ogni fase completata
> (checkbox + numeri `[PERF]` before/after). Questa cartella (`PrippiStream-v2`)
> è un clone locale **scollegato da GitHub**: nessun remote, nessun push possibile.
> Il repo pubblico (v1.5.x) resta intoccato fino al rilascio finale della 2.0.0.

## Obiettivo

Rendere l'addon fluido su hardware debole (Fire TV Stick, box Android S905,
Raspberry Pi, PC datati) **senza alcun cambiamento visibile** se non la velocità.
**Zero regressioni funzionali.** Include la pulizia del codice morto Stream4me
("Opzione 3").

Aree lente percepite: avvio/home, scorrimento righe/griglie, apertura
liste/ricerca/Sfoglia, avvio riproduzione.

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

---

## Stato fasi

- [x] **SETUP** — workspace scollegato, versione 1.9.900, questo documento
- [x] **FASE 0** — strumentazione `[PERF]` implementata (commit `0979cc4`); baseline PC raccolta 2026-07-03 (vedi tabella Misure) — ⏳ baseline Fire Stick prevista settimana prossima
- [x] **Port v1.5.3** — merge da v1 (commit `e2977c8`): feature 4K/FHD + fix live setting + domini; build test 1.9.901
- [x] **FASE 1** — fix cache TMDB (hit by-ID + niente cache di errori/{}) + expire 15gg + pool enrich max 8; build 1.9.903 — ✅ TESTATA 2026-07-03: miss 40%→7,8%, richieste TMDB -41%, rete -32%. Nota: `_tmdb_get_trailer` (prippihome:5489) chiama TMDB /videos direttamente via httptools senza cache — micro-win possibile in F2/F3
- [x] **FASE 2** — riuso trasporto HTTP (adapter condiviso, gate `http_session_reuse`) + cookie-save solo su cambiamento + infobox saltato a debug off; build 1.9.904 — ✅ TESTATA 2026-07-03: nessuna regressione (play SC/AnimeUnity ok), pooling corretto (Session non chiude l'adapter). Su PC guadagno nel rumore (handshake TLS CPU-cheap su x86); payoff atteso su Fire Stick (handshake costoso su ARM) → confermare con baseline FS
- [x] **FASE 3** — snapshot su disco (home_rows_snapshot.json, TTL 12h) → riapertura = fast path istantaneo; revalidate silenzioso per la prossima apertura; cold enrich_sync capato 8→3 righe; gate `home_snapshot`; build 1.9.905 — ⏳ da testare dall'utente (checklist FASE 3)
- [ ] **FASE 4** — memoizzazione settings + SQLite WAL
- [ ] **FASE 8a** — pulizia Stream4me: rimozioni a rischio zero
- [ ] **FASE 8b** — pulizia Stream4me: lavoro morto all'avvio
- [ ] **FASE 5** — skin XML: progress bar collassata + dieta asset
- [ ] **FASE 6** — percorso play: riuso interprete + micro-stop
- [ ] **FASE 7** — extra opzionali gated (solo se i numeri li giustificano)
- [ ] **FASE 8c** — chirurgia motore videolibrary (DIFFERITA, mini-progetto a parte)
- [ ] **Verifica finale end-to-end** → riporto nel repo principale → release 2.0.0

## Misure `[PERF]` (compilare)

**PC** = Windows dev (baseline 2026-07-03, build 1.9.902). **FS** = Fire Stick (baseline prevista settimana prossima).

| Metrica | Baseline (F0) | Post F1 | Post F2 | Post F3 | Post F4+8ab | Post F5 | Post F6 |
|---|---|---|---|---|---|---|---|
| Home cold: click→paint (PC) | **~4,9 s** (fetch_main 1,0-1,1s + assemble 0,04-0,08s + enrich_sync 3,5s + paint 0,2-0,3s) | ~5,1-5,3 s (invariato: enrich_sync ora CPU/SqliteDict-bound, non rete — atteso; si abbatte con F3) | | | | | |
| Home warm/snapshot: click→paint | **N/A — ogni riapertura è cold** (processo muore, cache in-memory persa: confermato, 2° open = cold identico) | idem (atteso, fix in F3) | | | | | |
| Archive fetch 21 righe (bg) | 3,7-4,1 s | 3,2-4,3 s (14-15 righe) | | | | | |
| TMDB hit-rate cache | **599 hit / 401 miss (40% miss)**; 1.291 richieste HTTP, 247 s rete cumulativi, avg 192 ms | **1.843 hit / 157 miss (7,8% miss)**; 758 req HTTP (-41%), 168 s rete (-32%), con giro più ricco (play cineblog01+trailer) | 2.089 hit / 161 miss (7,2%); 483 req TMDB, 92,7 s; latenza TMDB avg 192/mediana 149 ms (≈baseline su PC) | | | | |
| Click card→video (1° play, PC) | 1,7 s (launcher findvideos SC) | 6,8 s ma canale cineblog01 (catena uprot/maxstream) — non confrontabile con SC | SC 1,4-1,7 s · AnimeUnity 1,6 s · nessuna regressione | | | | |
| Click card→video (play successivi) | (non misurato, 1 solo play nel giro) | | | | | | |
| Fluidità scroll (soggettiva 1-5) | PC: fluido (non indicativo — misurare su FS) | | | | | | |

Note baseline PC: workers.dev (proxy CF live) 2,7-2,8 s/richiesta; youtube (trailer) 21 req/21,6 s; SC 31 req avg 560 ms.

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

## FASE 7 — Extra opzionali (gated, solo se i numeri li giustificano)

- `hd_backdrops` (default true): a false → backdrop `w1280` invece di `original`
  (tmdb.py:1717/1760, prippihome.py:93/6524).
- Trim slot riga 40→38; drop cartella 720p.

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
3. Test con la checklist della fase + confronto `[PERF]`.
4. Checkbox + numeri in questo file, poi fase successiva.

## Verifica finale end-to-end

1. Kodi Windows: cold/warm start, snapshot path, scroll completo, Sfoglia,
   Ricerca, 5 play cross-canale, download offline, live, One Piece, gate 18+.
2. Device lento: confronto `[PERF]` vs baseline.
3. `tools/test_*.py` verdi dove applicabili.
4. Riporto nel repo principale → versione 2.0.0 → release standard.
