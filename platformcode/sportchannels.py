# -*- coding: utf-8 -*-
"""
Live-channel rows for the Netflix-style home.

Two rows, same mechanics (instant bundled list + background refresh from the
mandrakodi public backend, bundled portrait posters, direct play with no
detail/trailer window):

  'sport' → "Sport Live": SKY Sport (sky@@ / NowTV ClearKey, freeshot fallback),
            Zona DAZN (freeshot), FIFA+ (iptv-org).
  'sky'   → "SKY": SKY entertainment + Sky Cinema (sky@@ / NowTV ClearKey).  The
            two +24 timeshift cinema channels exist only via daddyCode (dlhd.pk)
            and are resolved through PrippiStream's DoH resolver to bypass the
            Piracy-Shield DNS block.

Resolver kinds: 'sky', 'freeshot', 'iptvorg', 'daddycode'.

Self-contained: depends only on xbmc/xbmcgui, the stdlib, platformcode.config/
logger and (for daddyCode) core.resolverdns + lib.requests.
"""

import json
import os
import random
import re
import string
import time

try:
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
    from urllib.parse import urlparse
    PY3 = True
except ImportError:  # py2
    from urllib2 import Request, urlopen, URLError, HTTPError
    from urlparse import urlparse
    PY3 = False

import xbmc
import xbmcgui

from platformcode import config, logger
from core.item import Item

# ── Backend / client identity ────────────────────────────────────────────────
_BACKEND = "https://test34344.herokuapp.com/filter.php"
_MANDRA_VERSION = "1.2.81"
_XOR_SECRET = "my_secret_key"

_CODE_SKY_RESOLVE = "A1A159"   # ?id=<channel> → encrypted manifest+keys
_CODE_SPORT_SKY = "A1A165"     # Sport SKY list (sky@@)
_CODE_SPORT_SKY2 = "A1A165A"   # Sport SKY 2 (freeshot/dazn)
_CODE_LIVE_SKY = "A1A260"      # LIVE → SKY list (sky@@)

_IPTVORG_IT = "https://iptv-org.github.io/iptv/countries/it.m3u"

# NowTV referer/UA used for the ClearKey DASH streams.
_NOWTV_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
_NOWTV_HOST = "https://www.nowtv.it"
_FREESHOT_REFERER = "https://thisnot.business/"

# Posters bundled inside the addon (portrait 4:5, logo centred on dark canvas).
_POSTER_DIR = ("special://home/addons/plugin.video.prippistream/"
               "resources/media/sport_posters/")


def _poster(par):
    fname = par.replace("+", "plus").replace(" ", "_")
    return _POSTER_DIR + fname + ".png"


def _logo_for(par, backend_logo=''):
    """Prefer our bundled portrait poster; fall back to the backend's logo for
    channels we don't ship art for (e.g. ones added upstream after release)."""
    return _poster(par) if par in _KNOWN_POSTERS else (backend_logo or '')


# ── Static bundled lists — instant + resilient ───────────────────────────────
# 'fs' = freeshot fallback code (sport SKY only); None otherwise.
DEFAULT_SPORT = [
    {"title": u"Sky Sport 24",     "kind": "sky", "par": "skysport24",     "fs": "SkySport24IT"},
    {"title": u"Sky Sport Uno",    "kind": "sky", "par": "skysportuno",    "fs": "SkySportUnoIT"},
    {"title": u"Sky Sport Calcio", "kind": "sky", "par": "skysportcalcio", "fs": "SkySportCalcioIT"},
    {"title": u"Sky Sport Arena",  "kind": "sky", "par": "skysportarena",  "fs": "SkySportArenaIT"},
    {"title": u"Sky Sport Max",    "kind": "sky", "par": "skysportmax",    "fs": "SkySportMaxIT"},
    {"title": u"Sky Sport Tennis", "kind": "sky", "par": "skysporttennis", "fs": "SkySportTennisIT"},
    {"title": u"Sky Sport F1",     "kind": "sky", "par": "skysportf1",     "fs": "SkySportF1IT"},
    {"title": u"Sky Sport MotoGP", "kind": "sky", "par": "skysportmotogp", "fs": "SkySportMotoGPIT"},
    {"title": u"Sky Sport Basket", "kind": "sky", "par": "skysportbasket", "fs": "SkySportBasketIT"},
    {"title": u"Sky Sport Golf",   "kind": "sky", "par": "skysportgolf",   "fs": "SkySportGolfIT"},
    {"title": u"Sky Sport Legend", "kind": "sky", "par": "skysportlegend", "fs": None},
    {"title": u"Sky Sport Mix",    "kind": "sky", "par": "skysportmix",    "fs": None},
    {"title": u"Sky Sport 251",    "kind": "sky", "par": "skysport251",    "fs": None},
    {"title": u"Sky Sport 252",    "kind": "sky", "par": "skysport252",    "fs": None},
    {"title": u"Sky Sport 253",    "kind": "sky", "par": "skysport253",    "fs": None},
    {"title": u"Sky Sport 254",    "kind": "sky", "par": "skysport254",    "fs": None},
    {"title": u"Sky Sport 255",    "kind": "sky", "par": "skysport255",    "fs": None},
    {"title": u"Sky Sport 256",    "kind": "sky", "par": "skysport256",    "fs": None},
    {"title": u"Sky Sport 257",    "kind": "sky", "par": "skysport257",    "fs": None},
    {"title": u"Sky Sport 259",    "kind": "sky", "par": "skysport259",    "fs": None},
    {"title": u"Zona DAZN",        "kind": "freeshot", "par": "ZonaDAZN",  "fs": None},
    {"title": u"FIFA+ Italia",     "kind": "iptvorg",  "par": "FIFA+ Italy", "fs": None},
]

# LIVE SKY (entertainment) + Sky Cinema, all via the reliable sky@@ ClearKey
# resolver, except the two +24 timeshift cinema channels (daddyCode/dlhd).
DEFAULT_SKY = [
    {"title": u"Sky TG24",            "kind": "sky", "par": "tg24",             "fs": None},
    {"title": u"Sky Uno",             "kind": "sky", "par": "skyuno",           "fs": None},
    {"title": u"Sky Uno +1",          "kind": "sky", "par": "skyunoplus",       "fs": None},
    {"title": u"Sky Atlantic",        "kind": "sky", "par": "skyatlantic",      "fs": None},
    {"title": u"Sky Serie",           "kind": "sky", "par": "skyserie",         "fs": None},
    {"title": u"Sky Collection",      "kind": "sky", "par": "skycollection",    "fs": None},
    {"title": u"Sky Investigation",   "kind": "sky", "par": "skyinvestigation", "fs": None},
    {"title": u"Sky Adventure",       "kind": "sky", "par": "skyadventure",     "fs": None},
    {"title": u"Sky Crime",           "kind": "sky", "par": "skycrime",         "fs": None},
    {"title": u"Sky Documentaries",   "kind": "sky", "par": "skydocumentaries", "fs": None},
    {"title": u"Sky Nature",          "kind": "sky", "par": "skynature",        "fs": None},
    {"title": u"History",             "kind": "sky", "par": "historychannel",   "fs": None},
    {"title": u"Comedy Central",      "kind": "sky", "par": "comedycentral",    "fs": None},
    {"title": u"Sky Arte",            "kind": "sky", "par": "skyarte",          "fs": None},
    {"title": u"MTV",                 "kind": "sky", "par": "mtv",              "fs": None},
]

# Sky Cinema candidates.  The sky@@ backend frequently serves a ClearKey whose
# KID does NOT match the Cinema stream (DRM "Missing KeyId" → won't play).  So
# these are added to the SKY row ONLY when a load-time probe confirms the key is
# currently valid (see _sky_channel_valid).  They are placed FIRST in the row.
CINEMA_CANDIDATES = [
    {"title": u"Sky Cinema Uno",       "kind": "sky", "par": "skycinemauno",        "fs": None},
    {"title": u"Sky Cinema Action",    "kind": "sky", "par": "skycinemaaction",     "fs": None},
    {"title": u"Sky Cinema Collection","kind": "sky", "par": "skycinemacollection", "fs": None},
    {"title": u"Sky Cinema Comedy",    "kind": "sky", "par": "skycinemacomedy",     "fs": None},
    {"title": u"Sky Cinema Drama",     "kind": "sky", "par": "skycinemadrama",      "fs": None},
    {"title": u"Sky Cinema Family",    "kind": "sky", "par": "skycinemafamily",     "fs": None},
    {"title": u"Sky Cinema Romance",   "kind": "sky", "par": "skycinemaromance",    "fs": None},
    {"title": u"Sky Cinema Suspense",  "kind": "sky", "par": "skycinemasuspense",   "fs": None},
]

# Row definitions (label + bundled default + backend source).
_ROWS = {
    'sport': {'label': u'Sport Live', 'default': DEFAULT_SPORT},
    'sky':   {'label': u'SKY',        'default': DEFAULT_SKY},
}

# Pars for which we ship a bundled poster.
_KNOWN_POSTERS = set(c["par"] for c in DEFAULT_SPORT + DEFAULT_SKY + CINEMA_CANDIDATES) | {
    "skysport258",  # backend returns this par for Sky Sport Calcio (same logo as 257)
}

# ── per-row cache (memory + disk) ────────────────────────────────────────────
_CACHE_TTL = 6 * 3600
_mem_cache = {'sport': {"data": None, "ts": 0}, 'sky': {"data": None, "ts": 0}}


def _cache_file(row):
    try:
        return os.path.join(config.get_data_path(), "sportchannels_%s.json" % row)
    except Exception:
        return None


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def _device_id():
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(6))


def _mandra_ua():
    return "MandraKodi2@@%s@@@@%s" % (_MANDRA_VERSION, _device_id())


def _http_get(url, headers=None, timeout=15):
    try:
        resp = urlopen(Request(url, headers=headers or {}), timeout=timeout)
        data = resp.read()
        resp.close()
        if isinstance(data, bytes):
            data = data.decode('utf-8', 'replace')
        return data
    except Exception as exc:
        logger.error('[Sport] http_get %s: %s' % (url, str(exc)))
        return None


def _doh_get(url, headers=None, timeout=15):
    """GET via PrippiStream's DoH resolver (bypasses Piracy-Shield DNS blocks).
    Used for dlhd.pk (daddyCode).  Returns text or None."""
    try:
        from lib import requests as _requests
        from core import resolverdns
        domain = urlparse(url).netloc
        sess = _requests.session()
        sess.mount('https://', resolverdns.CipherSuiteAdapter(domain=domain, override_dns=True))
        r = sess.get(url, headers=headers or {}, timeout=timeout, verify=False)
        return r.text
    except Exception as exc:
        logger.error('[Sport] doh_get %s: %s' % (url, str(exc)))
        return None


def _backend_get(num_test, extra=''):
    url = "%s?numTest=%s%s" % (_BACKEND, num_test, extra)
    return _http_get(url, headers={'User-Agent': _mandra_ua()}, timeout=20)


def _xor_decrypt(data_b64, key=_XOR_SECRET):
    import base64
    raw = base64.b64decode(data_b64)
    kb = key.encode('utf-8')
    out = bytearray(len(raw))
    for i in range(len(raw)):
        out[i] = raw[i] ^ kb[i % len(kb)]
    return out.decode('utf-8', 'replace')


def _strip_color(s):
    return re.sub(r'\[/?COLOR[^\]]*\]', '', s or '').strip()


# ── channel-list refresh (background) ────────────────────────────────────────
def _parse_sport_backend():
    """Rebuild the Sport list from the live backend (A1A165 + A1A165A)."""
    raw_sky = _backend_get(_CODE_SPORT_SKY)
    if not raw_sky:
        return None
    try:
        sky_items = json.loads(raw_sky).get('items', [])
    except Exception:
        return None

    fs_map = {}
    dazn = None
    raw_sky2 = _backend_get(_CODE_SPORT_SKY2)
    if raw_sky2:
        try:
            for it in json.loads(raw_sky2).get('items', []):
                mr = it.get('myresolve', '') or ''
                if mr.startswith('freeshot@@'):
                    code = mr.split('@@', 1)[1]
                    if code == 'ZonaDAZN':
                        dazn = {"title": u"Zona DAZN", "kind": "freeshot",
                                "par": "ZonaDAZN", "fs": None,
                                "logo": _logo_for("ZonaDAZN", it.get('thumbnail', ''))}
                        continue
                    norm = code.lower()
                    if norm.endswith('it'):
                        norm = norm[:-2]
                    fs_map[norm] = code
        except Exception:
            pass

    channels = []
    for it in sky_items:
        mr = it.get('myresolve', '') or ''
        if not mr.startswith('sky@@'):
            continue
        par = mr.split('@@', 1)[1]
        channels.append({
            "title": _strip_color(it.get('info') or it.get('title') or par),
            "kind": "sky", "par": par, "fs": fs_map.get(par),
            "logo": _logo_for(par, it.get('thumbnail', '')),
        })
    if not channels:
        return None
    if dazn:
        channels.append(dazn)
    channels.append({"title": u"FIFA+ Italia", "kind": "iptvorg",
                     "par": "FIFA+ Italy", "fs": None, "logo": _poster("FIFA+ Italy")})
    return channels


def _sky_channel_valid(par):
    """True if a sky@@ channel is currently playable: the backend returns a
    non-expired manifest whose default_KID matches the ClearKey it provides.
    This is exactly what decides whether inputstream.adaptive can decrypt it."""
    raw = _backend_get(_CODE_SKY_RESOLVE, "&id=" + par)
    if not raw:
        return False
    try:
        obj = json.loads(_xor_decrypt(json.loads(raw).get('data')))
        man = obj['manifest']
        bkid = (obj.get('kid') or '').replace('-', '').lower()
        if not bkid:
            return False
        e = re.search(r'_e~(\d+)', man)
        if e and int(e.group(1)) < time.time():
            return False  # expired manifest → segments 403
        mpd = _http_get(man, headers={'User-Agent': _NOWTV_UA,
                                      'Referer': _NOWTV_HOST + '/'}, timeout=10)
        if not mpd:
            return False
        m = re.search(r'default_KID="([^"]+)"', mpd)
        if not m:
            return False
        return m.group(1).replace('-', '').lower() == bkid
    except Exception:
        return False


def _parse_sky_backend():
    """Rebuild the SKY list.  Sky Cinema channels that are currently playable go
    FIRST, then LIVE SKY (A1A260, sky@@) which auto-updates from the backend."""
    raw = _backend_get(_CODE_LIVE_SKY)
    if not raw:
        return None
    try:
        items = json.loads(raw).get('items', [])
    except Exception:
        return None

    live = []
    for it in items:
        mr = it.get('myresolve', '') or ''
        if not mr.startswith('sky@@'):
            continue
        par = mr.split('@@', 1)[1]
        live.append({
            "title": _strip_color(it.get('info') or it.get('title') or par),
            "kind": "sky", "par": par, "fs": None,
            "logo": _logo_for(par, it.get('thumbnail', '')),
        })
    if not live:
        return None

    # Probe Sky Cinema candidates; include only the ones playable right now.
    cinema = []
    for c in CINEMA_CANDIDATES:
        try:
            if _sky_channel_valid(c["par"]):
                d = dict(c)
                d["logo"] = _logo_for(c["par"])
                cinema.append(d)
        except Exception:
            pass
    logger.info('[Sport] sky cinema online: %d/%d' % (len(cinema), len(CINEMA_CANDIDATES)))

    return cinema + live   # cinema first, then LIVE SKY


_PARSERS = {'sport': _parse_sport_backend, 'sky': _parse_sky_backend}


def _load_disk_cache(row):
    f = _cache_file(row)
    if not f or not os.path.isfile(f):
        return None
    try:
        with open(f, 'r') as fh:
            blob = json.load(fh)
        if time.time() - blob.get('ts', 0) < _CACHE_TTL:
            return blob.get('data')
    except Exception:
        pass
    return None


def _save_disk_cache(row, data):
    f = _cache_file(row)
    if not f:
        return
    try:
        with open(f, 'w') as fh:
            json.dump({"ts": time.time(), "data": data}, fh)
    except Exception as exc:
        logger.error('[Sport] save cache %s: %s' % (row, str(exc)))


def refresh_background():
    """Refresh both rows' lists from the backend and persist.  Daemon-safe."""
    for row, parser in _PARSERS.items():
        try:
            fresh = parser()
            if fresh:
                _mem_cache[row]['data'] = fresh
                _mem_cache[row]['ts'] = time.time()
                _save_disk_cache(row, fresh)
                logger.info('[Sport] %s list refreshed: %d channels' % (row, len(fresh)))
        except Exception as exc:
            logger.error('[Sport] refresh %s: %s' % (row, str(exc)))


def get_channels(row):
    """Current channel list for a row: memory → disk → bundled default.
    Bundled defaults get their poster path filled in."""
    mc = _mem_cache.get(row)
    if mc and mc['data'] and (time.time() - mc['ts']) < _CACHE_TTL:
        return mc['data']
    disk = _load_disk_cache(row)
    if disk:
        if mc is not None:
            mc['data'] = disk
            mc['ts'] = time.time()
        return disk
    # Bundled default → attach posters.
    out = []
    for c in _ROWS[row]['default']:
        d = dict(c)
        d["logo"] = _poster(c["par"])
        out.append(d)
    return out


# ── row building ─────────────────────────────────────────────────────────────
def build_items(row):
    """Build the Item list for a row.  Items carry the channel poster and a
    sport_* payload used by the home's click handler to play them directly.
    infoLabels['_enr']=1 makes the home's TMDB-enrichment loops skip them."""
    items = []
    for ch in get_channels(row):
        try:
            it = Item(
                fulltitle=ch['title'], title=ch['title'],
                thumbnail=ch.get('logo', ''), fanart=ch.get('logo', ''),
                contentType='video', action='live_channel',
                infoLabels={'_enr': 1, 'mediatype': 'video', 'plot': ch['title']},
            )
            it.is_live_channel = True
            it.sport_kind = ch['kind']
            it.sport_par = ch['par']
            it.sport_fs = ch.get('fs')
            items.append(it)
        except Exception as exc:
            logger.error('[Sport] build_items %s: %s' % (ch.get('title'), str(exc)))
    return items


def row_label(row):
    return _ROWS[row]['label']


# ── resolvers ────────────────────────────────────────────────────────────────
def resolve_sky(channel_id):
    """Return (manifest, kid, key) for a SKY channel, or None."""
    raw = _backend_get(_CODE_SKY_RESOLVE, "&id=" + channel_id)
    if not raw:
        return None
    try:
        data = json.loads(_xor_decrypt(json.loads(raw).get('data')))
        return data['manifest'], data['kid'], data['key']
    except Exception as exc:
        logger.error('[Sport] resolve_sky %s: %s' % (channel_id, str(exc)))
        return None


def resolve_freeshot(code):
    """Return an HLS m3u8 URL for a freeshot channel, or None."""
    page = _http_get("https://popcdn.day/player/" + code,
                     headers={'User-Agent': _NOWTV_UA, 'Referer': _FREESHOT_REFERER},
                     timeout=15)
    if not page:
        return None
    m = re.search(r'currentToken:\s*"(.*?)"', page)
    if not m:
        logger.error('[Sport] resolve_freeshot %s: no token' % code)
        return None
    return "https://lovely.lovetier.bz/%s/tracks-v1a1/mono.m3u8?token=%s" % (code, m.group(1))


def resolve_daddycode(code):
    """Resolve a dlhd.pk daddyCode channel to an HLS m3u8.  Routed through DoH
    to bypass the Piracy-Shield DNS block.  Returns (url, referer) or None."""
    hdr = {'User-Agent': _NOWTV_UA, 'Referer': 'https://dlhd.pk/', 'Accept': '*/*'}
    page1 = _doh_get("https://dlhd.pk/stream/stream-%s.php" % code, headers=hdr, timeout=15)
    if not page1:
        return None
    m = re.search(r'<iframe src="(.*?)"', page1)
    if not m:
        logger.error('[Sport] daddycode %s: no iframe' % code)
        return None
    iframe = m.group(1)
    ref = '%s://%s/' % (urlparse(iframe).scheme, urlparse(iframe).netloc)
    page2 = _doh_get(iframe, headers={'User-Agent': _NOWTV_UA, 'Referer': 'https://dlhd.pk/'}, timeout=15)
    if not page2:
        return None
    m2 = re.search(r"window\.atob\('(.*?)'\)", page2)
    if not m2:
        logger.error('[Sport] daddycode %s: no atob' % code)
        return None
    import base64
    try:
        link = base64.b64decode(m2.group(1)).decode('utf-8')
    except Exception:
        return None
    return link, ref


# ── playable ListItem construction ───────────────────────────────────────────
def _clearkey_listitem(manifest, kid, key, title, art):
    li = xbmcgui.ListItem(path=manifest, offscreen=True)
    li.setLabel(title)
    li.setContentLookup(False)
    li.setProperty("inputstream", "inputstream.adaptive")
    li.setProperty("inputstream.adaptive.drm_legacy", "org.w3.clearkey|%s:%s" % (kid, key))
    hdr = ('User-Agent=%s&Referer=%s/&Origin=%s&verifypeer=false'
           % (_NOWTV_UA, _NOWTV_HOST, _NOWTV_HOST))
    li.setProperty("inputstream.adaptive.stream_headers", hdr)
    li.setProperty("inputstream.adaptive.manifest_headers", hdr)
    if art:
        li.setArt(art)
    return li


def _hls_listitem(url, title, art, referer=None):
    li = xbmcgui.ListItem(path=url, offscreen=True)
    li.setLabel(title)
    li.setContentLookup(False)
    li.setMimeType("application/x-mpegURL")
    li.setProperty("inputstream", "inputstream.adaptive")
    li.setProperty("inputstream.adaptive.manifest_type", "hls")
    if referer:
        hdr = 'User-Agent=%s&Referer=%s&Origin=%s' % (_NOWTV_UA, referer, referer.rstrip('/'))
        li.setProperty("inputstream.adaptive.stream_headers", hdr)
        li.setProperty("inputstream.adaptive.manifest_headers", hdr)
    if art:
        li.setArt(art)
    return li


def resolve_listitem(item):
    """Resolve a live-channel Item to a playable xbmcgui.ListItem.

    Hybrid for SKY: try the heroku 'sky' ClearKey endpoint first, then fall back
    to freeshot if it fails and a fallback code exists.  Returns a ListItem or
    None.
    """
    kind = getattr(item, 'sport_kind', '')
    par = getattr(item, 'sport_par', '')
    title = item.fulltitle or item.title or par
    art = {'thumb': item.thumbnail or '', 'icon': item.thumbnail or '',
           'poster': item.thumbnail or '', 'fanart': item.fanart or ''}

    if kind == 'sky':
        sky = resolve_sky(par)
        if sky:
            return _clearkey_listitem(sky[0], sky[1], sky[2], title, art)
        fs = getattr(item, 'sport_fs', None)
        if fs:
            logger.info('[Sport] sky %s failed → freeshot fallback %s' % (par, fs))
            url = resolve_freeshot(fs)
            if url:
                return _hls_listitem(url, title, art, referer=_FREESHOT_REFERER)
        return None

    if kind == 'freeshot':
        url = resolve_freeshot(par)
        if url:
            return _hls_listitem(url, title, art, referer=_FREESHOT_REFERER)
        return None

    if kind == 'daddycode':
        res = resolve_daddycode(par)
        if res:
            url, ref = res
            return _hls_listitem(url, title, art, referer=ref)
        return None

    if kind == 'iptvorg':
        url = resolve_iptvorg(par)
        if url:
            return _hls_listitem(url, title, art)
        return None

    return None


def resolve_iptvorg(display_name):
    """Resolve a channel from the iptv-org Italy list by matching its name."""
    m3u = _http_get(_IPTVORG_IT, timeout=20)
    if not m3u:
        return None
    lines = m3u.splitlines()
    needle = display_name.lower().split('(')[0].strip()
    for i, line in enumerate(lines):
        if line.startswith('#EXTINF') and needle in line.lower():
            for j in range(i + 1, min(i + 3, len(lines))):
                u = lines[j].strip()
                if u and not u.startswith('#'):
                    return u
    return None
