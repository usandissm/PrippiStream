# -*- coding: utf-8 -*-
"""
4K Movie index — powered by Mandrakodi Xtream Codes API.

Data source:  marek2.myvisio.me:8000  (VOD IPTV 2 → category 150 → FILM 4K)
Cache TTL:    6 hours
Lookup key:   tmdb_id  (int → dict with stream_url, name, etc.)

Integration points (prippihome.py):
  - PrippiHomeWindow.__init__:  background refresh thread
  - PrippiHomeWindow._launch(): 4K check before SC (movies only)
  - DetailWindow.onInit():       badge "4K" in meta1
  - PrippiSearchWindow._launch_item(): same 4K check
"""

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from platformcode import config, logger

try:
    from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
    from urllib.parse import urlparse, urlunparse
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, build_opener, HTTPRedirectHandler, HTTPError, URLError
    from urlparse import urlparse, urlunparse

# ── API config ──────────────────────────────────────────────────────────
_API_BASE   = 'http://marek2.myvisio.me:8000/player_api.php'
_API_USER   = 'rcorfro'
_API_PASS   = 'sasy'
_API_CAT_ID = 150          # FILM 4K
_API_AUTH   = 'username=%s&password=%s' % (_API_USER, _API_PASS)

# Base stream URL (NO pipe headers — they break redirect tokens!)
_STREAM_BASE = 'http://marek2.myvisio.me:8000/movie/%s/%s' % (_API_USER, _API_PASS)
# Resolved stream URL cache: stream_id → final CDN URL (with token)
_resolved_urls = {}

_CACHE_TTL      = 86400       # 24 hours
_CACHE_VERSION   = 2            # bump to invalidate old caches
_MAX_WORKERS    = 10          # parallel vod_info fetches
_UA             = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# Regex: must have a 4K indicator in the name (case-insensitive)
_RE_4K_NAME = re.compile(r'4[Kk]|2160[pP]|UHD', re.IGNORECASE)


# ── Module state ────────────────────────────────────────────────────────
_index_by_tmdb = {}        # int tmdb_id → {"stream_url","name","year","poster","rating"}
_ready         = False     # True after first successful build
_building      = False     # True while a build is in progress
_lock          = threading.Lock()


# ── DNS fallback via DoH ────────────────────────────────────────────────

_doh_cache = {}   # hostname → ip (in-memory, reset per session)

# DoH providers tried in order. Google may refuse domains blocked by Piracy Shield (IT),
# Cloudflare and Quad9 are used as fallbacks.
_DOH_PROVIDERS = [
    ('Cloudflare', 'https://1.1.1.1/dns-query?name=%s&type=A'),
    ('Quad9',      'https://dns.quad9.net:5053/dns-query?name=%s&type=A'),
    ('Google',     'https://dns.google/resolve?name=%s&type=A'),
]

def _resolve_via_doh(hostname):
    """Resolve hostname via DNS-over-HTTPS, bypassing system DNS.
    Tries Google, Cloudflare and Quad9 in order (Italian Piracy Shield blocks
    Google's response for some domains; Cloudflare/Quad9 usually still resolve).
    Returns an IP string or None on failure. Result is cached per session."""
    if hostname in _doh_cache:
        return _doh_cache[hostname]
    for provider_name, doh_tpl in _DOH_PROVIDERS:
        try:
            doh_url = doh_tpl % hostname
            req = Request(doh_url, headers={'User-Agent': _UA, 'Accept': 'application/dns-json'})
            resp = urlopen(req, timeout=6)
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            for answer in data.get('Answer', []):
                if answer.get('type') == 1:   # A record
                    ip = answer['data'].strip()
                    _doh_cache[hostname] = ip
                    logger.info('[4K] DoH resolved %s → %s (via %s)' % (hostname, ip, provider_name))
                    return ip
            logger.info('[4K] DoH %s returned no A record for %s (Status=%s), trying next' % (
                provider_name, hostname, data.get('Status', '?')))
        except Exception as exc:
            logger.error('[4K] DoH %s failed for %s: %s' % (provider_name, hostname, str(exc)))
    logger.error('[4K] All DoH providers failed to resolve %s' % hostname)
    return None


def _url_with_ip(url, ip):
    """Replace the hostname in url with a resolved IP, keeping Host header intact."""
    parsed = urlparse(url)
    netloc_ip = ip if ':' not in parsed.netloc else ('%s:%s' % (ip, parsed.netloc.split(':')[1]))
    return urlunparse(parsed._replace(netloc=netloc_ip))


# ── Internal helpers ────────────────────────────────────────────────────

def _http_get(url, timeout=12):
    """Minimal HTTP GET returning (response_object, final_url) or (None, None).
    On DNS failure (errno 7) retries once using Google DoH to resolve the host."""
    try:
        req = Request(url, headers={'User-Agent': _UA})
        resp = urlopen(req, timeout=timeout)
        return resp, resp.geturl()
    except Exception as exc:
        exc_str = str(exc)
        # errno 7 = DNS failure on Linux; errno 11001 = WSAHOST_NOT_FOUND on Windows
        if ('Errno 7' in exc_str or 'Errno 11001' in exc_str
                or 'Name or service not known' in exc_str
                or 'nodename nor servname' in exc_str
                or 'getaddrinfo failed' in exc_str):
            parsed = urlparse(url)
            ip = _resolve_via_doh(parsed.hostname)
            if ip:
                try:
                    url_ip = _url_with_ip(url, ip)
                    req2 = Request(url_ip, headers={'User-Agent': _UA, 'Host': parsed.hostname})
                    resp2 = urlopen(req2, timeout=timeout)
                    logger.info('[4K] DNS fallback succeeded for %s' % parsed.hostname)
                    return resp2, resp2.geturl()
                except Exception as exc2:
                    logger.error('[4K] DoH fallback request failed for %s: %s' % (url[:80], str(exc2)))
        logger.error('[4K] HTTP error for %s: %s' % (url[:80], exc_str))
        return None, None


def _http_get_body(url, timeout=12):
    """HTTP GET returning decoded string or None."""
    resp, _ = _http_get(url, timeout)
    if resp:
        return resp.read().decode('utf-8', errors='ignore')
    return None


class _NoRedirectHandler(HTTPRedirectHandler):
    """Redirect handler that raises HTTPError instead of following redirects.
    This lets us capture the Location header without consuming the CDN token."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _resolve_stream_url(sid, ext):
    """Capture the CDN redirect URL from the IPTV server WITHOUT following it.

    The IPTV server issues a 302 to a CDN URL that carries a one-time token.
    Following the redirect ourselves (via urlopen) would consume the token before
    Kodi gets a chance to play it.  Instead we:
      1. Resolve the IPTV hostname via DoH (Cloudflare) to bypass Piracy Shield.
      2. Send one request using the IP with a Host header — server sends 302.
      3. Capture the Location header and return that CDN URL to get_resolved_url.
      4. Kodi opens the CDN URL directly (no Host override needed; CDN resolves fine)."""
    cache_key = '%d.%s' % (sid, ext)
    if cache_key in _resolved_urls:
        return _resolved_urls[cache_key]

    url = '%s/%d.%s' % (_STREAM_BASE, sid, ext)
    parsed = urlparse(url)
    ip = _doh_cache.get(parsed.hostname) or _resolve_via_doh(parsed.hostname)

    try:
        if ip:
            req_url = _url_with_ip(url, ip)
            port = parsed.port
            host_hdr = ('%s:%d' % (parsed.hostname, port)) if port else parsed.hostname
            req = Request(req_url, headers={'User-Agent': _UA, 'Host': host_hdr})
        else:
            req = Request(url, headers={'User-Agent': _UA})

        opener = build_opener(_NoRedirectHandler)
        try:
            resp = opener.open(req, timeout=8)
            # Server returned 200 directly — no redirect, use this URL
            resp.close()
            logger.info('[4K] No redirect for sid=%d, using base URL' % sid)
        except HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get('Location') or e.headers.get('location')
                if location:
                    _resolved_urls[cache_key] = location
                    logger.info('[4K] Captured CDN redirect for sid=%d: %s' % (sid, location[:80]))
                    return location
    except Exception as exc:
        logger.error('[4K] _resolve_stream_url failed for sid=%d: %s' % (sid, str(exc)))

    # Fallback: return the hostname URL; get_resolved_url will rewrite host to IP
    return url


def _api(action, params=''):
    """Call Xtream Codes API, return parsed JSON or None."""
    url = '%s?%s&action=%s%s' % (_API_BASE, _API_AUTH, action, params)
    body = _http_get_body(url)
    if not body:
        return None
    try:
        return json.loads(body)
    except Exception as exc:
        logger.error('[4K] JSON parse error for %s: %s' % (action, str(exc)))
        return None


def _fetch_vod_info(stream_id):
    """Fetch vod_info for a single stream_id, return (stream_id, tmdb_id_or_None).
    Retries once on failure, parses tmdb_url as fallback."""
    for attempt in range(2):
        try:
            data = _api('get_vod_info', '&vod_id=%s' % stream_id)
            if data and 'info' in data:
                info = data['info']
                tmdb_id = info.get('tmdb_id')
                # Fallback: parse tmdb_id from tmdb_url
                if not tmdb_id:
                    tmdb_url = info.get('tmdb_url', '')
                    m = re.search(r'/movie/(\d+)', tmdb_url)
                    if m:
                        tmdb_id = int(m.group(1))
                if tmdb_id:
                    return (int(stream_id), int(tmdb_id))
            break  # success or no data, don't retry
        except Exception:
            if attempt == 0:
                time.sleep(0.5)  # brief pause before retry
            else:
                logger.error('[4K] vod_info failed for stream %s after retry' % stream_id)
    return (int(stream_id), None)


def _extract_year(name):
    """Extract (clean_name, year) from a movie name like '10 Cloverfield Lane (2016)'.
    Also strips trailing '4K'/'4k' suffix."""
    import re
    m = re.search(r'\((\d{4})\)', name)
    year = int(m.group(1)) if m else 0
    clean = re.sub(r'\s*\(\d{4}\)\s*', '', name).strip()
    # Remove trailing 4K / 4k
    clean = re.sub(r'\s*4[Kk]\s*$', '', clean).strip()
    return clean, year


# ── Public API ──────────────────────────────────────────────────────────

def build_4k_index():
    """(Re)build the 4K index. Call from a background thread at startup."""
    global _index_by_tmdb, _ready, _building

    # Prevent concurrent builds
    with _lock:
        if _building:
            logger.info('[4K] Build already in progress, skipping')
            return
        _building = True

    try:
        # ── Check cache first ──
        cache_path = os.path.join(config.get_data_path(), 'fourk_cache.json')
        _old_cache = None
        try:
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                if (time.time() - cache.get('ts', 0) < _CACHE_TTL
                        and cache.get('ver') == _CACHE_VERSION):
                    with _lock:
                        _index_by_tmdb = {int(k): v for k, v in cache.get('movies', {}).items()}
                        _ready = True
                    logger.info('[4K] Cache hit: %d movies' % len(_index_by_tmdb))
                    return
                # Cache expired but keep it as fallback
                _old_cache = cache
        except Exception as exc:
            logger.error('[4K] Cache read error: %s' % str(exc))

        logger.info('[4K] Building index from API…')

        # ── Step 1: fetch all streams in category 150 ──
        streams = _api('get_vod_streams', '&category_id=%d' % _API_CAT_ID)
        if not streams:
            logger.error('[4K] No streams returned from API')
            # Fallback: use expired cache if available
            if _old_cache:
                logger.info('[4K] Using expired cache as fallback (%d movies)' % len(_old_cache.get('movies', {})))
                with _lock:
                    _index_by_tmdb = {int(k): v for k, v in _old_cache.get('movies', {}).items()}
                    _ready = True
            return

        logger.info('[4K] Fetched %d streams, resolving tmdb_ids…' % len(streams))

        # ── Step 2: resolve tmdb_id for each stream (parallel) ──
        stream_ids = [
            int(s['stream_id']) for s in streams
            if s.get('name', '') != '----- 4K ONDEMAND -----'  # skip header row
        ]

        tmdb_map = {}  # stream_id → tmdb_id
        completed = 0
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_vod_info, sid): sid for sid in stream_ids}
            for future in as_completed(futures):
                try:
                    sid, tmdb = future.result()
                    if tmdb:
                        tmdb_map[sid] = tmdb
                    completed += 1
                    if completed % 50 == 0:
                        logger.info('[4K] … %d/%d streams resolved' % (completed, len(stream_ids)))
                except Exception as exc:
                    logger.error('[4K] thread error: %s' % str(exc))

        logger.info('[4K] Resolved %d tmdb_ids out of %d streams' % (len(tmdb_map), len(stream_ids)))

        # ── Step 3: build index ──
        new_index = {}
        for s in streams:
            sid = int(s.get('stream_id', 0))
            name = (s.get('name') or '').strip()
            if not name or name.startswith('-----'):
                continue
            tmdb_id = tmdb_map.get(sid)
            if not tmdb_id:
                continue  # skip movies without tmdb_id (can't match)

            # Only include movies that actually have a 4K indicator in the name
            if not _RE_4K_NAME.search(name):
                continue

            clean_name, year = _extract_year(name)
            ext = s.get('container_extension', 'mkv')
            stream_url = '%s/%d.%s' % (_STREAM_BASE, sid, ext)

            new_index[tmdb_id] = {
                'name':       clean_name,
                'year':       year,
                'stream_url': stream_url,
                'sid':        sid,
                'ext':        ext,
                'poster':     s.get('stream_icon', ''),
                'rating':     float(s.get('rating', 0) or 0),
            }

        # ── Step 4: save cache ──
        try:
            cache = {
                'ts':     time.time(),
                'ver':    _CACHE_VERSION,
                'movies': {str(k): v for k, v in new_index.items()},
            }
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception as exc:
            logger.error('[4K] Cache write error: %s' % str(exc))

        with _lock:
            _index_by_tmdb = new_index
            _ready = True

        logger.info('[4K] Index ready: %d movies with tmdb_id' % len(new_index))

    finally:
        with _lock:
            _building = False


def _ensure_loading():
    """Start background build if not yet ready and not already building."""
    global _ready
    if not _ready and not getattr(_ensure_loading, '_started', False):
        _ensure_loading._started = True
        t = threading.Thread(target=build_4k_index, daemon=True)
        t.start()


def lookup_4k(tmdb_id):
    """Return 4K movie dict or None.  tmdb_id can be int or str."""
    if not _ready:
        _ensure_loading()
        return None
    try:
        tid = int(tmdb_id) if not isinstance(tmdb_id, int) else tmdb_id
    except (ValueError, TypeError):
        return None
    return _index_by_tmdb.get(tid)


def get_resolved_url(f4k):
    """Return a playable URL for Kodi.

    If _resolve_stream_url captured a CDN redirect URL (different host from the
    IPTV server), return it directly — no Host override needed, CDN resolves fine.
    If we only have the raw IPTV URL (no redirect captured), substitute the
    DoH-resolved IP + Host header so Kodi's libcurl can connect despite DNS block.
    f4k is the dict returned by lookup_4k()."""
    sid = f4k.get('sid')
    ext = f4k.get('ext', 'mp4')
    url = f4k.get('stream_url', '')
    if sid:
        url = _resolve_stream_url(int(sid), ext)
    if not url:
        return ''

    parsed = urlparse(url)
    iptv_host = urlparse(_STREAM_BASE).hostname  # marek2.myvisio.me

    if parsed.hostname == iptv_host:
        # Redirect was not captured — fall back to IP substitution + Host header.
        # Kodi will get the redirect token on its first request.
        ip = _doh_cache.get(parsed.hostname) or _resolve_via_doh(parsed.hostname)
        if ip:
            port = parsed.port
            host_hdr = ('%s:%d' % (parsed.hostname, port)) if port else parsed.hostname
            url_ip = urlunparse(parsed._replace(netloc=('%s:%d' % (ip, port)) if port else ip))
            logger.info('[4K] Fallback IP rewrite for Kodi: %s (Host: %s)' % (url_ip[:80], host_hdr))
            return '%s|User-Agent=Mozilla/5.0&Host=%s' % (url_ip, host_hdr)

    # CDN URL (or non-blocked host) — pass directly to Kodi, no Host override.
    logger.info('[4K] CDN URL passed to Kodi: %s' % url[:80])
    if '|User-Agent=' not in url:
        url += '|User-Agent=Mozilla/5.0'
    return url


def is_4k_available(tmdb_id):
    """Quick bool check (cheap, no dict copy)."""
    if not _ready or not tmdb_id:
        _ensure_loading()
        return False
    try:
        return int(tmdb_id) in _index_by_tmdb
    except (ValueError, TypeError):
        return False


# ── Eager cache load at import time ─────────────────────────────────────
# Load the disk cache immediately (even if expired) so that _ready=True
# before prippihome._bg_load() calls _build_4k_row().  This eliminates
# the race condition where the 4K carousel is missing on first launch
# (especially on TVs that restart Kodi each time).
# The background build_4k_index() thread will still run and refresh the
# index if the cache is stale.
def _try_load_cache():
    global _index_by_tmdb, _ready
    try:
        cache_path = os.path.join(config.get_data_path(), 'fourk_cache.json')
        if not os.path.exists(cache_path):
            return
        with open(cache_path, 'r', encoding='utf-8') as _f:
            _cache = json.load(_f)
        # Accept any version that has movies data (stale is better than missing)
        if _cache.get('movies'):
            with _lock:
                _index_by_tmdb = {int(k): v for k, v in _cache['movies'].items()}
                _ready = True
            logger.info('[4K] Eagerly loaded %d movies from cache (age %.1fh)' % (
                len(_index_by_tmdb),
                (time.time() - _cache.get('ts', 0)) / 3600.0
            ))
    except Exception as _exc:
        logger.error('[4K] Eager cache load failed: %s' % str(_exc))


_try_load_cache()
