# -*- coding: utf-8 -*-
"""
4K Movie index — powered by Mandrakodi Xtream Codes API.

Data source:  marek2.myvisio.me:8000  (VOD IPTV 2 → category 150 → FILM 4K)
Cache TTL:    6 hours
Lookup key:   tmdb_id  (int → dict with stream_url, name, etc.)

Integration points (netflixhome.py):
  - NetflixHomeWindow.__init__:  background refresh thread
  - NetflixHomeWindow._launch(): 4K check before SC (movies only)
  - DetailWindow.onInit():       badge "4K" in meta1
  - NetflixSearchWindow._launch_item(): same 4K check
"""

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from platformcode import config, logger

try:
    from urllib.request import Request, urlopen, urlparse
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, HTTPError, URLError
    from urlparse import urlparse

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

_CACHE_TTL      = 21600       # 6 hours
_CACHE_VERSION   = 2            # bump to invalidate old caches
_MAX_WORKERS    = 5           # parallel vod_info fetches (keep low to avoid 503)
_UA             = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# Regex: must have a 4K indicator in the name (case-insensitive)
_RE_4K_NAME = re.compile(r'4[Kk]|2160[pP]|UHD', re.IGNORECASE)


# ── Module state ────────────────────────────────────────────────────────
_index_by_tmdb = {}        # int tmdb_id → {"stream_url","name","year","poster","rating"}
_ready         = False     # True after first successful build
_building      = False     # True while a build is in progress
_lock          = threading.Lock()


# ── Internal helpers ────────────────────────────────────────────────────

def _http_get(url, timeout=12):
    """Minimal HTTP GET returning (response_object, final_url) or (None, None)."""
    try:
        req = Request(url, headers={'User-Agent': _UA})
        resp = urlopen(req, timeout=timeout)
        return resp, resp.geturl()
    except Exception as exc:
        logger.error('[4K] HTTP error for %s: %s' % (url[:80], str(exc)))
        return None, None


def _http_get_body(url, timeout=12):
    """HTTP GET returning decoded string or None."""
    resp, _ = _http_get(url, timeout)
    if resp:
        return resp.read().decode('utf-8', errors='ignore')
    return None


def _resolve_stream_url(sid, ext):
    """Follow redirect on the stream URL to get the final CDN URL (with token).
    Returns final URL without pipe headers (clean URL for Kodi)."""
    # Check short-lived memory cache (this session only)
    cache_key = '%d.%s' % (sid, ext)
    if cache_key in _resolved_urls:
        return _resolved_urls[cache_key]

    url = '%s/%d.%s' % (_STREAM_BASE, sid, ext)
    try:
        req = Request(url, headers={'User-Agent': _UA})
        # Don't follow redirects — we want to capture the 302 Location header
        resp = urlopen(req, timeout=8)
        final_url = resp.geturl()
        resp.close()
        if final_url and final_url != url:
            _resolved_urls[cache_key] = final_url
            return final_url
    except Exception:
        pass
    # Fallback: return base URL (will likely fail with 401, but that's handled upstream)
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
    """Resolve the final CDN stream URL (follow redirect, get token).
    f4k is the dict returned by lookup_4k().  Returns URL with Kodi pipe headers."""
    sid = f4k.get('sid')
    ext = f4k.get('ext', 'mp4')
    url = f4k.get('stream_url', '')
    if sid:
        url = _resolve_stream_url(int(sid), ext)
    # CDN requires User-Agent — safe on final URL (no more redirects)
    if url and '|User-Agent=' not in url:
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
