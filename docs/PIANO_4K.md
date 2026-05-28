# Piano d'Azione: Integrazione Film 4K da Mandrakodi in PrippiStream

## Panoramica

Integrare i **320 film 4K** provenienti dall'IPTV Xtream Codes di Mandrakodi
(`marek2.myvisio.me:8000`) in PrippiStream, con:
- Check trasparente prima della riproduzione (priorità 4K)
- Badge "4K" nella scheda dettaglio
- Nessuna interazione utente aggiuntiva
- Cache automatica (6 ore)

---

## Fase 1 — Nuovo modulo `platformcode/_fourk.py`

### Struttura

```python
# platformcode/_fourk.py

_FOURK_API    = 'http://marek2.myvisio.me:8000/player_api.php'
_FOURK_USER   = 'rcorfro'
_FOURK_PASS   = 'sasy'
_FOURK_CAT_ID = 150           # FILM 4K
_CACHE_TTL    = 21600         # 6 ore
_CACHE_FILE   = 'fourk_cache.json'  # in data_path

_fourk_index_by_tmdb   = {}   # tmdb_id (int) → {"stream_url":..., "name":..., ...}
_fourk_index_ready     = False
_fourk_last_refresh    = 0
_fourk_lock            = threading.Lock()
```

### Funzioni

#### `_fetch_4k_movies()` → list[dict]
Chiama l'API Xtream Codes:
```
GET {API}?username={U}&password={P}&action=get_vod_streams&category_id=150
```
Restituisce la lista completa dei 320 film con tutti i campi (stream_id, name,
tmdb_id, rating, container_extension, stream_icon, ecc.).

Per ottenere il tmdb_id di ogni film, serve una seconda chiamata:
```
GET {API}?username={U}&password={P}&action=get_vod_info&vod_id={stream_id}
```
⚠️ **Attenzione**: `get_vod_info` va chiamato per OGNI film (320 chiamate).
**Ottimizzazione**: chiamare `get_vod_info` solo per i film senza TMDB nei
metadati di lista, oppure parallelizzare con ThreadPool (10 worker, ~5 sec).

#### `_build_stream_url(stream_id, ext)` → str
Formato Xtream Codes:
```
http://marek2.myvisio.me:8000/movie/rcorfro/sasy/{stream_id}.{ext}
```

#### `build_4k_index()` → None
1. Controlla se la cache JSON è valida (< 6 ore)
2. Se no → chiama `_fetch_4k_movies()`, normalizza i titoli, costruisce
   `_fourk_index_by_tmdb`, salva la cache
3. Setta `_fourk_index_ready = True`

Thread-safe con `_fourk_lock`.

#### `lookup_4k(tmdb_id)` → dict | None
Cerca `tmdb_id` in `_fourk_index_by_tmdb`. Restituisce il dict con
`stream_url`, `name`, `rating`, `poster` oppure None.

#### `lookup_4k_by_title(title, year)` → dict | None
Fallback: normalizza titolo e anno, cerca nell'indice.

#### `is_4k_available(tmdb_id)` → bool
Per il badge nella DetailWindow.

### Cache JSON (in `config.get_data_path()`)

```json
{
  "ts": 1715000000,
  "movies": {
    "333371": {
      "name": "10 Cloverfield Lane",
      "year": 2016,
      "stream_url": "http://marek2.myvisio.me:8000/movie/rcorfro/sasy/104914.mkv",
      "tmdb_id": 333371,
      "rating": 6.9,
      "poster": "http://..."
    },
    ...
  },
  "by_title": {
    "10cloverfieldlane2016": 333371,
    ...
  }
}
```

---

## Fase 2 — Integrazione in `platformcode/netflixhome.py`

### 2a — Avvio refresh in background

Nel metodo `__init__` di `NetflixHomeWindow`, aggiungere:

```python
# Avvia refresh indice 4K in background (non blocca l'avvio)
t_4k = threading.Thread(target=_fourk.build_4k_index, daemon=True)
t_4k.start()
```

### 2b — Priorità 4K nel playback (`_launch`)

Modificare `_launch()` (riga ~1202). PRIMA di chiamare SC, aggiungere:

```python
def _launch(self, item):
    # ... existing code ...
    
    # ── 4K check (solo per film) ──
    ct = getattr(item, 'contentType', '') or ''
    if ct == 'movie':
        tmdb_id_str = str(item.infoLabels.get('tmdb_id') or '').strip()
        if tmdb_id_str:
            f4k = _fourk.lookup_4k(int(tmdb_id_str))
            if f4k:
                # Riproduci direttamente in 4K
                stream_url = f4k['stream_url']
                logger.info('[NetflixHome] 4K HIT: %s → %s' % (item.fulltitle, stream_url[:80]))
                _play_4k_stream(item, stream_url)
                return
    # ... existing SC flow ...
```

### 2c — Funzione `_play_4k_stream(item, url)`

```python
def _play_4k_stream(item, url):
    """Riproduce uno stream 4K diretto."""
    li = xbmcgui.ListItem(item.fulltitle or '', path=url)
    li.setArt({'thumb': item.thumbnail or '', 'fanart': item.fanart or ''})
    li.setInfo('video', item.infoLabels)
    li.setProperty('IsPlayable', 'true')
    
    _pre_play_set_lang(item)
    
    player = xbmc.Player()
    player.play(url, li)
    
    # CW tracking (stesso pattern di SC)
    t = threading.Thread(target=self._wait_and_restore, args=(item,), daemon=True)
    t.start()
```

### 2d — Badge "4K" nella DetailWindow

In `DetailWindow.onInit()`, dopo aver impostato i metadati, aggiungere:

```python
# ── Badge 4K ──
if ct == 'movie':
    tmdb_id_str = str(item.infoLabels.get('tmdb_id') or '').strip()
    if tmdb_id_str and _fourk.is_4k_available(int(tmdb_id_str)):
        try:
            self.getControl(DW_META1).setLabel(
                self.getControl(DW_META1).getLabel() + '  •  [COLOR FFE50914]4K[/COLOR]')
        except:
            pass
```

Oppure usare un controllo label dedicato se disponibile nell'XML.

### 2e — Integrazione in `NetflixSearchWindow._launch_item`

Stesso pattern: controllare l'indice 4K prima di chiamare `parent._launch(item)`.
Aggiungere dopo il prefetch path:

```python
# ── 4K check ──
ct = getattr(item, 'contentType', '') or ''
if ct == 'movie':
    tmdb_id_str = str(item.infoLabels.get('tmdb_id') or '').strip()
    if tmdb_id_str:
        f4k = _fourk.lookup_4k(int(tmdb_id_str))
        if f4k:
            _play_4k_stream(item, f4k['stream_url'])
            return
```

---

## Fase 3 — Ordine delle operazioni

1. ✅ Completata: Analisi/Esplorazione API Mandrakodi
2. ⏳ **Creare `platformcode/_fourk.py`** — fetch + cache + lookup
3. ⏳ **Testare `_fourk.py` standalone** — verificare che l'indice venga popolato
4. ⏳ **Integrare in `netflixhome.py`** — 4 modifiche:
   - Import e init refresh
   - `_launch()` con check 4K
   - `_play_4k_stream()` helper
   - Badge in `DetailWindow.onInit()`
5. ⏳ **Integrare in `NetflixSearchWindow._launch_item`**
6. ⏳ **Deploy + test su Kodi**
7. ⏳ **Push su GitHub**

---

## Note tecniche

### Performance `get_vod_info`
La chiamata `get_vod_info` per ogni film è costosa (320 richieste HTTP).
Soluzione ibrida:
- Prima fetch: chiama `get_vod_info` solo per i film dove `tmdb_id` non è
  presente nella lista (la lista `get_vod_streams` potrebbe già includerlo)
- Oppure: 10 thread paralleli, ~5-8 secondi totali per 320 film
- Alla fine: cache JSON salvata, refresh successivi sono istantanei

### Stream URL — verifica formato
Il formato Xtream Codes standard per VOD movie è:
```
http://{server}:{port}/movie/{username}/{password}/{stream_id}.{container_extension}
```
Da testare: la prima volta che si riproduce un film 4K, verificare che l'URL
funzioni. In caso contrario, provare il formato:
```
http://{server}:{port}/{username}/{password}/{stream_id}
```

### Timeout e fallback
Se l'API Xtream Codes è down → `_fourk_index_ready` resta False → nessun
check 4K → PrippiStream funziona normalmente con SC.

### Riproduzione diretta vs RunPlugin
Lo stream 4K è un URL diretto (HTTP) → si usa `xbmc.Player().play(url, li)`
invece di `RunPlugin`. Il CW tracking funziona uguale perché usa
`_wait_and_restore`.

---

## Riepilogo file da modificare

| File | Azione |
|---|---|
| `platformcode/_fourk.py` | **NUOVO** — modulo fetch/cache/lookup 4K |
| `platformcode/netflixhome.py` | **MODIFICA** — 5 punti di integrazione |

### Punti di modifica in `netflixhome.py`

1. **Import** (top del file): `from platformcode import _fourk`
2. **`NetflixHomeWindow.__init__`**: `threading.Thread(target=_fourk.build_4k_index).start()`
3. **`NetflixHomeWindow._launch()`**: check 4K prima di SC, + nuova funzione `_play_4k_stream`
4. **`DetailWindow.onInit()`**: badge "4K" nella riga meta1
5. **`NetflixSearchWindow._launch_item()`**: check 4K prima del fallback
