# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Provider DEDICATO per One Piece (gestione speciale).
#
# One Piece e' un'eccezione: invece delle decine di voci sparse su SC/CB01/
# AnimeUnity, qui viene trattato come UN contenuto unificato con due versioni
# principali (ITA doppiata e Sub-ITA) + extra (OAV / special / spin-off).
#
# Fonte: la pagina CB01 di One Piece e' un indice auto-descrittivo: ogni blocco
# "sp-head" rimanda a una cartella uprot (Maxstream) che elenca TUTTI gli episodi
# con numerazione assoluta. Il blocco "SAGHE" da' la mappa saga -> range assoluti
# usata per la navigazione. I link Watch (uprot.net/msfi/...) sono gia' risolvibili
# dal server Maxstream esistente (servers/maxstream.py, lib/uprot_captcha.py).
#
# L'indice si aggiorna automaticamente UNA VOLTA AL GIORNO: build_index() usa una
# cache su disco (onepiece_cache.json, TTL 24h) come platformcode/_fourk.py ed e'
# lanciato in background dalla home onInit. Cosi' i nuovi episodi entrano da soli.
# ------------------------------------------------------------
import os
import re
import json
import time
import threading

try:
    from html import unescape as _html_unescape
except Exception:                       # pragma: no cover (py2 safety)
    try:
        from HTMLParser import HTMLParser as _HP
        _html_unescape = _HP().unescape
    except Exception:
        _html_unescape = lambda s: s

from core import httptools, servertools
from core.item import Item
from platformcode import logger, config

# ── Constants ────────────────────────────────────────────────────────────────
_CACHE_TTL     = 86400          # 24h: refresh once a day (checked at skin load)
_CACHE_VERSION = 4              # bump to invalidate old caches
_CACHE_NAME    = 'onepiece_cache.json'
_INDEX_PATH    = '/serietv/one-piece/'     # CB01 path of the One Piece index page
# Fallback poster (One Piece anime) if the CB01 og:image is missing.
_FALLBACK_POSTER = 'https://image.tmdb.org/t/p/w500/e3NBGiFh8m4yJjEvXLZQUFz4nPV.jpg'
# TMDB One Piece — used to enrich the main ITA/SUB episodes with Italian titles,
# plots and still images (the rich per-episode metadata the user wants).
_TMDB_ID  = '37854'
_TMDB_KEY = 'a1ab8b8669da03637a4b98fa39c39228'
_TMDB_STILL = 'https://image.tmdb.org/t/p/w300'
# One Piece ITA (dub) — sourced from AnimeUnity (vixcloud/scws) instead of the
# uprot/Maxstream folder, as requested. id/slug of www.animeunity.../anime/2998-one-piece-ita.
_AU_ITA_ID   = '2998'
_AU_ITA_SLUG = '2998-one-piece-ita'

# In-memory index (mirror of the on-disk cache). Shape:
#   { 'ts':float, 'ver':int, 'poster':str, 'sagas':[[start,end,name],...],
#     'folders': { KEY: {'url':str,'label':str,'eps':[[num,watch_url],...]} } }
# KEY in: ITA, SUB, OAV, FISHMAN, INLOVE, SPECIALE
_INDEX   = None
_lock    = threading.Lock()
_building = False

_HEADERS = [['User-Agent',
             'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/124.0 Safari/537.36']]


def _cb01_host():
    """CB01 host from channels.json (no findhost network call). Falls back to a
    known domain so One Piece keeps working even if the channel entry is stale."""
    try:
        h = config.get_channel_url(name='cineblog01') or ''
    except Exception:
        h = ''
    return (h or 'https://cb01uno.lol').rstrip('/')


def _cache_path():
    return os.path.join(config.get_data_path(), _CACHE_NAME)


# ── Low-level parsing ────────────────────────────────────────────────────────
def _clean(text):
    text = re.sub(r'<[^>]+>', ' ', text or '')
    return re.sub(r'\s+', ' ', _html_unescape(text)).strip()


def _parse_folder(html, absolute=True):
    """Parse a uprot 'msfld' folder page → sorted [[num, watch_url, title], ...].

    absolute=True  (main ITA/SUB series): the episode number is the ABSOLUTE One
       Piece number parsed from the filename — handles BOTH styles
       (One.Piece.0926.ITA.WEB.mp4 and One.Piece.S01E0926.ITA.WEB.mkv); when an
       episode has several links it keeps the HIGHEST-QUALITY one (max quality).
    absolute=False (extras: OAV / Fish-Man / In Love): filenames have no absolute
       number, so episodes are numbered sequentially 1..N by row order and the
       cleaned filename is kept as the title.
    """
    rows = []
    best = {}        # absolute mode: num → (qscore, url) — keep the highest quality
    for row in re.split(r'<tr', html or ''):
        watch = re.search(r"https?://(?:www\.)?uprot\.net/msfi/[A-Za-z0-9]+", row)
        if not watch:
            continue
        url = watch.group(0)
        nm = re.search(r'<td>\s*([^<]+?)\s*<', row)
        name = _clean(nm.group(1)) if nm else ''
        if absolute:
            m = re.search(r'One[._ ]?Piece[._ ]?(?:S\d+E)?(\d{1,4})', name, re.I)
            if not m:
                continue
            num = int(m.group(1))
            if not num:
                continue
            # ALWAYS prefer the highest-quality link when an episode has several.
            q = _qscore(name)
            if num not in best or q > best[num][0]:
                best[num] = (q, url)
        else:
            # readable title: drop leading lang tokens, the extension, and the
            # trailing release/quality junk (WEBDL, 720p, x264, …).
            title = re.sub(r'^_?(?:SUB[- ]?ITA|ITA)[._ ]?', '', name, flags=re.I)
            title = re.sub(r'\.(?:mp4|mkv|avi)$', '', title, flags=re.I)
            title = re.sub(r'[._]+', ' ', title).strip()
            title = re.sub(r'\b(?:WEB[- ]?DL|WEBRip|WEB|BDRip|HDTV|'
                           r'\d{3,4}p|x?264|x?265|HEVC|AAC|HD|SD)\b.*$', '',
                           title, flags=re.I).strip(' -')
            rows.append([len(rows) + 1, url, title or name])
    if absolute:
        rows = [[num, u, ''] for num, (q, u) in sorted(best.items())]
    return rows


def _qscore(name):
    """Rough quality score from a filename (higher = better)."""
    m = re.search(r'(\d{3,4})\s*p', name or '', re.I)
    if m:
        return int(m.group(1))
    n = (name or '').upper()
    if '2160' in n or '4K' in n or 'UHD' in n:
        return 2160
    if '1080' in n or 'FHD' in n:
        return 1080
    if '720' in n or ' HD' in n or '.HD' in n:
        return 720
    return 0


def _parse_inline(html):
    """Parse a block whose episodes are inline uprot.net/msf|msfi links (e.g.
    SPECIALE) → [[idx, url, title], ...] numbered 1..N by order of appearance."""
    links = re.findall(r"https?://(?:www\.)?uprot\.net/ms(?:fi|f)/[A-Za-z0-9]+", html or '')
    seen, out = set(), []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append([len(out) + 1, u, u'Speciale %d' % (len(out) + 1)])
    return out


def _classify(header):
    h = (header or '').upper()
    if 'SERIE' in h and 'SUB' in h:
        return 'SUB', 'One Piece'
    if 'SERIE' in h and 'ITA' in h:
        return 'ITA', 'One Piece'
    if 'OAV' in h or 'OVA' in h:
        return 'OAV', 'One Piece — OAV'
    if 'FISH' in h:
        return 'FISHMAN', 'One Piece — Saga Fish-Man Island'
    if 'IN LOVE' in h:
        return 'INLOVE', 'One Piece in Love'
    if 'SPECIAL' in h:
        return 'SPECIALE', 'One Piece — Speciali'
    return None, None


def _parse_sagas(page):
    """Extract the SAGHE block → [[start, end, name], ...] (absolute ranges)."""
    sagas = []
    for chunk in re.split(r'sp-head[^>]*>', page)[1:]:
        head = _clean(chunk[:60])
        if not head.upper().startswith('SAGHE'):
            continue
        body = chunk.split('spdiv')[0]
        for a, b, name in re.findall(
                r'(\d{3,4})\s*/\s*(\d{3,4})\s*(?:&#8211;|–|-)\s*([^<\r\n]+?)\s*(?:<br|</p>|<)',
                body):
            sagas.append([int(a), int(b), _clean(name)])
        break
    return sagas


def _tmdb_json(url):
    try:
        return json.loads(httptools.downloadpage(url, headers=_HEADERS).data or 'null')
    except Exception:
        return None


def _fetch_tmdb_meta(max_abs):
    """Build absolute-episode → Italian metadata from TMDB One Piece.

    TMDB organises One Piece into saga-seasons with per-season episode numbering
    and Italian names/overviews/stills. We concatenate the seasons in broadcast
    order to get an absolute-numbered flat list, so episode N (uprot absolute) maps
    to the N-th TMDB episode. Returns { "N": [title, plot, still_url] }.

    Only display metadata — playback always uses the uprot link, so a few episodes
    of drift near the latest saga (TMDB carries some extra recaps) never affects
    which episode actually plays. Never raises.
    """
    meta = {}
    try:
        show = _tmdb_json('%s/3/tv/%s?api_key=%s&language=it-IT'
                          % ('https://api.themoviedb.org', _TMDB_ID, _TMDB_KEY))
        if not show:
            return meta
        seasons = sorted(s.get('season_number', 0) for s in show.get('seasons', [])
                         if s.get('season_number', 0) > 0)
        # Fetch the seasons in parallel (build runs once a day in the background,
        # but parallel keeps it quick), then assemble in broadcast order so the
        # flat index == absolute episode number.
        from concurrent.futures import ThreadPoolExecutor
        def _season(sn):
            return sn, _tmdb_json('%s/3/tv/%s/season/%d?api_key=%s&language=it-IT'
                                  % ('https://api.themoviedb.org', _TMDB_ID, sn, _TMDB_KEY))
        with ThreadPoolExecutor(max_workers=8) as pool:
            sdata = dict(pool.map(_season, seasons))
        abs_n = 0
        for sn in seasons:
            if abs_n >= max_abs:
                break
            sd = sdata.get(sn) or {}
            for ep in sd.get('episodes', []):
                abs_n += 1
                title = (ep.get('name') or '').strip()
                plot  = (ep.get('overview') or '').strip()
                still = ep.get('still_path') or ''
                meta[str(abs_n)] = [title, plot,
                                    (_TMDB_STILL + still) if still else '']
        logger.info('[OnePiece] TMDB meta: %d episodi' % len(meta))
    except Exception as exc:
        logger.error('[OnePiece] TMDB meta failed: %s' % str(exc))
    return meta


def _fetch_animeunity_ita():
    """Fetch the One Piece ITA episode list from AnimeUnity (id 2998).

    Returns (anime_url, [[abs_num, episode_url], ...]) using AnimeUnity's
    info_api (absolute numbering). The episodes will play through the AnimeUnity
    (streamingcommunityws/vixcloud) resolver — more reliable than Maxstream for
    the dub. Returns ('', []) on any failure → caller keeps the uprot ITA folder.
    """
    try:
        import channels.animeunity as au
        try:
            au._ensure_init()
        except Exception:
            pass
        host = au.host.rstrip('/')
        anime_url = '%s/anime/%s' % (host, _AU_ITA_SLUG)
        out, start, limit = [], 1, 120
        while True:
            url = '%s/info_api/%s/1?start_range=%d&end_range=%d' % (
                host, _AU_ITA_ID, start, start + limit - 1)
            raw = httptools.downloadpage(url, headers=getattr(au, '_headers', '')).data
            full = json.loads(raw or '{}')
            count = int(full.get('episodes_count') or 0)
            for ep in full.get('episodes', []):
                try:
                    num = int(ep.get('number') or 0)
                except Exception:
                    num = 0
                eid = ep.get('id')
                if num and eid:
                    out.append([num, '%s/%s' % (anime_url, eid)])
            if count > start + limit - 1:
                start += limit
            else:
                break
        # de-dup by episode number, keep ascending order
        seen, uniq = set(), []
        for num, u in sorted(out, key=lambda x: x[0]):
            if num not in seen:
                seen.add(num)
                uniq.append([num, u])
        return anime_url, uniq
    except Exception as exc:
        logger.error('[OnePiece] AnimeUnity ITA fetch failed: %s' % str(exc))
        return '', []


# ── Index build / cache (mirror of platformcode/_fourk.py) ───────────────────
def build_index(force=False):
    """(Re)build the One Piece index. Call from a background thread at startup.

    Cache-first: if onepiece_cache.json is < 24h old and same version, just load
    it (instant, no network). Otherwise re-scrape the CB01 index + uprot folders
    and persist. Never raises.
    """
    global _INDEX, _building

    with _lock:
        if _building:
            return _INDEX
        _building = True
    try:
        cache_path = _cache_path()
        old_cache = None
        try:
            if not force and os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                if (time.time() - cache.get('ts', 0) < _CACHE_TTL
                        and cache.get('ver') == _CACHE_VERSION
                        and cache.get('folders')):
                    with _lock:
                        _INDEX = cache
                    logger.info('[OnePiece] cache hit: %d folders' % len(cache.get('folders', {})))
                    return _INDEX
                old_cache = cache
        except Exception as exc:
            logger.error('[OnePiece] cache read error: %s' % str(exc))

        logger.info('[OnePiece] building index from CB01…')
        index_url = _cb01_host() + _INDEX_PATH
        try:
            page = httptools.downloadpage(index_url, headers=_HEADERS).data or ''
        except Exception as exc:
            logger.error('[OnePiece] index page fetch failed: %s' % str(exc))
            page = ''
        if not page:
            if old_cache:
                with _lock:
                    _INDEX = old_cache
                logger.info('[OnePiece] using expired cache as fallback')
            return _INDEX

        poster = re.search(r'<meta property="og:image"\s+content="([^"]+)"', page)
        poster = poster.group(1) if poster else _FALLBACK_POSTER
        sagas  = _parse_sagas(page)

        folders = {}
        for chunk in re.split(r'sp-head[^>]*>', page)[1:]:
            header = _clean(chunk[:120])
            key, label = _classify(header)
            if not key or key in folders:
                continue
            body = chunk.split('spdiv')[0]
            fmatch = re.search(r'https?://(?:www\.)?uprot\.net/msfld/[A-Za-z0-9]+', body)
            try:
                if fmatch:
                    furl = fmatch.group(0)
                    fhtml = httptools.downloadpage(furl, headers=_HEADERS).data or ''
                    # main series use ABSOLUTE numbering; extras are sequential
                    eps = _parse_folder(fhtml, absolute=(key in ('ITA', 'SUB')))
                else:
                    # inline-link block (e.g. SPECIALE): episodes are right here
                    furl = index_url
                    eps = _parse_inline(body)
                if eps:
                    folders[key] = {'url': furl, 'label': label,
                                    'eps': eps, 'source': 'uprot'}
                    logger.info('[OnePiece] %s: %d episodi' % (key, len(eps)))
            except Exception as exc:
                logger.error('[OnePiece] folder %s parse failed: %s' % (key, str(exc)))

        if not folders:
            if old_cache:
                with _lock:
                    _INDEX = old_cache
            return _INDEX

        # ITA dub: prefer AnimeUnity (vixcloud) over the uprot/Maxstream folder.
        # Falls back to the uprot ITA folder above if AnimeUnity is unreachable.
        try:
            au_url, au_eps = _fetch_animeunity_ita()
            if au_eps:
                folders['ITA'] = {'url': au_url, 'label': 'One Piece',
                                  'eps': au_eps, 'source': 'animeunity'}
                logger.info('[OnePiece] ITA from AnimeUnity: %d episodi' % len(au_eps))
        except Exception as exc:
            logger.error('[OnePiece] ITA AnimeUnity override failed: %s' % str(exc))

        # TMDB Italian per-episode metadata (titles / plots / stills) for the two
        # main series, mapped by absolute episode number.
        max_abs = 0
        for k in ('SUB', 'ITA'):
            if folders.get(k) and folders[k]['eps']:
                max_abs = max(max_abs, int(folders[k]['eps'][-1][0]))
        ep_meta = _fetch_tmdb_meta(max_abs) if max_abs else {}

        new_index = {'ts': time.time(), 'ver': _CACHE_VERSION,
                     'poster': poster, 'sagas': sagas, 'folders': folders,
                     'ep_meta': ep_meta}
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(new_index, f, ensure_ascii=False)
        except Exception as exc:
            logger.error('[OnePiece] cache write error: %s' % str(exc))
        with _lock:
            _INDEX = new_index
        total = sum(len(f['eps']) for f in folders.values())
        logger.info('[OnePiece] index rebuilt: %d folders, %d episodi' % (len(folders), total))
        return _INDEX
    finally:
        with _lock:
            _building = False


def _index():
    """Return the in-memory index, building from cache/network if needed."""
    global _INDEX
    if _INDEX and _INDEX.get('folders'):
        return _INDEX
    return build_index() or {'folders': {}, 'sagas': [], 'poster': _FALLBACK_POSTER}


# ── Item builders ────────────────────────────────────────────────────────────
def _make_show_item(key, idx):
    folder = idx['folders'].get(key)
    if not folder:
        return None
    lang = 'ITA' if key == 'ITA' else 'Sub-ITA'
    label = folder.get('label', 'One Piece')
    if key in ('ITA', 'SUB'):
        title = u'One Piece [%s]' % lang
    else:
        title = label                       # extras keep their descriptive label
    it = Item(
        channel='onepiece', action='episodios', contentType='tvshow',
        title=title, fulltitle=title, show=title, contentSerieName=title,
        contentTitle='', url=folder['url'],
        op_key=key, op_folder=folder['url'], op_lang=lang,
        contentLanguage=lang,
        thumbnail=idx.get('poster', _FALLBACK_POSTER),
        fanart=idx.get('poster', _FALLBACK_POSTER),
        plot=u'One Piece — serie animata. Versione %s.' % lang,
    )
    try:
        it.infoLabels['_enr'] = 1           # keep our poster, skip TMDB enrichment
        it.infoLabels['mediatype'] = 'tvshow'
    except Exception:
        pass
    return it


def get_curated_items(want_extras=True):
    """The curated One Piece set: 2 main series (SUB first, then ITA) + extras."""
    idx = _index()
    folders = (idx or {}).get('folders', {})
    logger.info('[OnePiece] get_curated_items: index folders=%s' % list(folders.keys()))
    out = []
    for key in ('SUB', 'ITA'):
        it = _make_show_item(key, idx)
        if it:
            out.append(it)
        else:
            logger.error('[OnePiece] get_curated_items: %s folder missing' % key)
    if want_extras:
        for key in ('OAV', 'FISHMAN', 'INLOVE', 'SPECIALE'):
            it = _make_show_item(key, idx)
            if it:
                out.append(it)
    return out


# ── Channel API (search / episodios / findvideos / get_sagas) ────────────────
def search(item, text):
    """Intentionally returns nothing for the GLOBAL search.

    One Piece is handled specially by netflixhome._onepiece_curate (it injects the
    curated provider items in a controlled order). If this channel also fed raw
    items into the global search they would (a) pollute the result dedup — the
    [ITA]/[Sub-ITA] tags get stripped by the title-normaliser, collapsing both
    main series onto a single "one piece" key — and (b) trip the curation's
    'already present' guard. So we stay out of the global search entirely.
    """
    return []


def _resolve_folder(item):
    idx = _index()
    key = getattr(item, 'op_key', '') or ''
    if key and key in idx['folders']:
        return key, idx['folders'][key], idx
    fu = getattr(item, 'op_folder', '') or getattr(item, 'url', '') or ''
    for k, f in idx['folders'].items():
        if f['url'] == fu:
            return k, f, idx
    return None, None, idx


def episodios(item):
    """Flat episode list for a One Piece show item (absolute numbering)."""
    key, folder, idx = _resolve_folder(item)
    if not folder:
        logger.error('[OnePiece] episodios: folder not resolved (key=%r url=%r)'
                     % (getattr(item, 'op_key', ''), getattr(item, 'url', '')[:80]))
        return []
    lang = getattr(item, 'op_lang', '') or ('ITA' if key == 'ITA' else 'Sub-ITA')
    show = u'One Piece [%s]' % lang if key in ('ITA', 'SUB') else folder.get('label', u'One Piece')
    is_main = key in ('ITA', 'SUB')
    source = folder.get('source', 'uprot')
    # All episodes keep channel='onepiece' so the picker / Continue-Watching /
    # up-next always route through THIS episodios() — i.e. saga navigation and the
    # Italian TMDB enrichment apply uniformly (ITA + SUB). Playback source is kept
    # in op_source: 'animeunity' episodes are delegated to the AnimeUnity resolver
    # by findvideos() below; 'uprot' episodes resolve through Maxstream.
    ep_server  = '' if source == 'animeunity' else 'maxstream'
    poster = getattr(item, 'thumbnail', '') or idx.get('poster', _FALLBACK_POSTER)
    ep_meta = idx.get('ep_meta') or {}
    out = []
    for ep_row in folder['eps']:
        num = int(ep_row[0])
        url = ep_row[1]
        ep_title = ep_row[2] if len(ep_row) > 2 else ''
        ep_plot = ''
        ep_thumb = poster
        # Main ITA/SUB episodes: overlay the Italian TMDB title / plot / still.
        if is_main:
            m = ep_meta.get(str(num))
            if m:
                ep_title = m[0] or ep_title
                ep_plot  = m[1] or ''
                if m[2]:
                    ep_thumb = m[2]
        label = ep_title if ep_title else (u'Episodio %d' % num)
        ep = item.clone(
            channel='onepiece', op_source=source, action='findvideos', contentType='episode',
            url=url, server=ep_server, folder=False, type='series',
            episode=num, contentEpisodeNumber=num, contentSeason=1,
            title=label, contentEpisodeTitle=ep_title,
            fulltitle=show, show=show, contentSerieName=show, contentTitle='',
            contentLanguage=lang, op_key=key, op_lang=lang, plot=ep_plot,
            thumbnail=ep_thumb, _cw_show_url=folder['url'],
        )
        out.append(ep)
    return out


def findvideos(item):
    """Resolve an episode to playable stream items.

    ITA episodes (op_source='animeunity') are delegated to the AnimeUnity
    resolver (vixcloud/scws); everything else (uprot) goes through Maxstream.
    """
    if getattr(item, 'op_source', '') == 'animeunity':
        try:
            import channels.animeunity as au
            return au.findvideos(item.clone(channel='animeunity'))
        except Exception as exc:
            logger.error('[OnePiece] animeunity findvideos failed: %s' % str(exc))
            return []
    return servertools.find_video_items(item, data=item.url)


# CB01 'serieFolder'/findvid paths are not used by this provider.
def play(item):
    return servertools.find_video_items(item, data=item.url)


def get_sagas(item):
    """Saga tabs for the EpisodePicker: [{'name','start','end'}, ...] clipped to
    the episodes actually present, plus a trailing 'Altri episodi' if needed."""
    key, folder, idx = _resolve_folder(item)
    sagas = []
    if not folder or not folder['eps']:
        return sagas
    maxep = int(folder['eps'][-1][0])
    minep = int(folder['eps'][0][0])
    # Saga navigation only makes sense for the MAIN series (absolute numbering).
    # Extras (OAV / specials / spin-offs) are a single flat list.
    if key in ('ITA', 'SUB'):
        for start, end, name in idx.get('sagas', []):
            if start > maxep:
                break
            sagas.append({'name': name, 'start': int(start), 'end': int(min(end, maxep))})
        last = sagas[-1]['end'] if sagas else 0
        if maxep > last:
            sagas.append({'name': u'Altri episodi', 'start': last + 1, 'end': maxep})
    if not sagas:
        sagas.append({'name': u'Serie completa', 'start': minep, 'end': maxep})
    return sagas
