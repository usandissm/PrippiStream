# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# download_manager — background queue orchestrating offline downloads
#
# Resolves each title's HLS stream *just before* downloading it (so the CDN
# token is fresh), picks the requested quality variant from the master
# playlist, downloads + decrypts the CDN segments via core.hls_downloader, and
# re-encrypts the output on the fly with the device-bound soft-DRM cipher
# selected in settings. Progress is reported via a background dialog and
# persisted to downloads_db so the home "I miei download" row stays in sync.
# ------------------------------------------------------------

from __future__ import division

import os
import re
import ssl
import socket as _socket
import threading

try:
    from urllib.parse import urlsplit as _urlsplit
    import urllib.request as _urlreq
    import urllib.error as _urlerr
except ImportError:  # py2
    from urlparse import urlsplit as _urlsplit
    import urllib2 as _urlreq
    _urlerr = _urlreq

try:
    import queue as _queue
except ImportError:
    import Queue as _queue

try:
    _NOVERIFY_CTX = ssl._create_unverified_context()
except Exception:
    _NOVERIFY_CTX = None

from platformcode import logger, config, downloads_db
from core import hls_downloader, download_crypto

_SERVER = 'streamingcommunityws'
_RESOLVE_LOCK = threading.Lock()   # streamingcommunityws uses module globals

# Active-download flag. The home pauses its GIL-heavy background work (TMDB
# enrichment, YouTube trailer search) while a download runs, so the download
# threads aren't starved of the Python GIL. We mirror the counter into a Kodi
# window property (Window 10000) so the flag is reliably visible across modules
# and threads regardless of import identity — an in-memory module global proved
# not to be observed by the enrichment code path.
_active = [0]
_FLAG_PROP = 'prippistream_dl_active'


def _sync_flag():
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty(_FLAG_PROP, '1' if _active[0] > 0 else '')
    except Exception:
        pass


def is_downloading():
    try:
        import xbmcgui
        if xbmcgui.Window(10000).getProperty(_FLAG_PROP) == '1':
            return True
    except Exception:
        pass
    return _active[0] > 0


# ── DNS resolution cache + serializer ───────────────────────────────────────
# ROOT CAUSE of download hangs: with many worker threads each doing a fresh
# stdlib fetch, dozens of socket.getaddrinfo() calls fire concurrently. On
# Windows that resolver chokes under concurrent load and some lookups HANG with
# NO timeout (getaddrinfo ignores the socket timeout), so a segment fetch hangs
# forever — stalling the whole download. We wrap getaddrinfo to (a) cache each
# host once and (b) serialize the real lookups, eliminating the storm.
_gai_orig = _socket.getaddrinfo
_gai_cache = {}
_gai_lock = threading.Lock()
_dns_patched = [False]


def _cached_getaddrinfo(host, port, *args, **kwargs):
    # Cache only — do NOT hold the lock during the real lookup, or a single slow
    # lookup would block every thread. Concurrency is avoided instead by
    # pre-warming all segment hosts serially (prewarm_dns) before the parallel
    # fetch, so during the download these are all cache hits.
    key = (host, port)
    with _gai_lock:
        v = _gai_cache.get(key)
    if v is not None:
        return v
    v = _gai_orig(host, port, *args, **kwargs)
    with _gai_lock:
        _gai_cache[key] = v
    return v


def prewarm_dns(hosts):
    """Resolve *hosts* one at a time (no concurrency) to populate the cache, so
    the parallel segment fetch never fires concurrent getaddrinfo (which hangs
    on Windows). Each lookup is bounded by a worker thread with a timeout."""
    for h in hosts:
        if not h:
            continue
        with _gai_lock:
            if (h, 443) in _gai_cache:
                continue
        res = {}

        def _do():
            try:
                res['v'] = _gai_orig(h, 443, 0, _socket.SOCK_STREAM)
            except Exception as exc:
                res['e'] = exc

        t = threading.Thread(target=_do)
        t.daemon = True
        t.start()
        t.join(6)               # hard cap so a hung lookup can't block forever
        if 'v' in res:
            with _gai_lock:
                _gai_cache[(h, 443)] = res['v']


def _install_dns_cache():
    if _dns_patched[0]:
        return
    _dns_patched[0] = True
    try:
        _socket.getaddrinfo = _cached_getaddrinfo
        logger.info('[DLManager] getaddrinfo cache installed')
    except Exception as exc:
        logger.error('[DLManager] dns cache install: %s' % str(exc))


# ── HTTP fetcher ────────────────────────────────────────────────────────────
# CRITICAL: the vixcloud CDN (Cloudflare-fronted) throttles connections whose
# TLS fingerprint doesn't match, so a plain requests.get() crawls at a few KB/s.
# We must use the SAME session setup as core/httptools: a requests.Session with
# resolverdns.CipherSuiteAdapter mounted (custom cipher suite + DoH DNS). We
# cache one session per host so segment downloads reuse keep-alive connections.

_sessions = {}
_sessions_lock = threading.Lock()


def _session_for(url):
    """One session per host, mounted with the cipher adapter (same as httptools).
    The vix-content CDN tarpits when a single IP opens too many parallel
    connections, so we keep concurrency low; per-host sessions reuse keep-alive
    when a host repeats."""
    try:
        domain = _urlsplit(url).netloc
    except Exception:
        domain = ''
    with _sessions_lock:
        s = _sessions.get(domain)
        if s is None:
            from lib import requests
            s = requests.session()
            try:
                from core import resolverdns
                s.mount('https://', resolverdns.CipherSuiteAdapter(
                    domain=domain,
                    override_dns=config.get_setting('resolver_dns'),
                    pool_connections=24, pool_maxsize=24))
            except Exception as exc:
                logger.error('[DLManager] adapter mount failed: %s' % str(exc))
            s.verify = False
            _sessions[domain] = s
        return s


def _session_get(url, headers=None, timeout=30):
    """Addon path (DoH + cipher) — for the master/media playlist + AES key, which
    live on vixcloud.co (Cloudflare, frequently ISP-DNS-blocked)."""
    s = _session_for(url)
    r = s.get(url, headers=headers or {}, timeout=timeout)
    if r.status_code in (403, 410):
        err = Exception('HTTP %d' % r.status_code)
        err.code = r.status_code
        raise err
    r.raise_for_status()
    return r.content


_STALL_DEADLINE = 12   # max seconds for one segment before we abandon+retry


def _stdlib_get(url, headers=None, timeout=30):
    """Plain stdlib fetch (system DNS, default fast TLS) for the .ts segments on
    the OVH CDN.

    Critical robustness: some connections in the Kodi process trickle data so
    slowly that the socket read-timeout never fires (each recv returns a few
    bytes < timeout), which would hang the in-order writer forever on a single
    segment. We therefore enforce a HARD TOTAL DEADLINE and read in chunks: a
    stalled connection is abandoned and the caller retries with a fresh one.
    We also use a private opener (build_opener) so a global opener installed
    elsewhere can't serialize concurrent fetches."""
    import time as _t
    h = {k: v for k, v in (headers or {}).items()
         if k.lower() != 'accept-encoding'}
    req = _urlreq.Request(url, headers=h)
    sock_timeout = min(timeout, 8)
    _step = _dbg_seg[0] < 30
    def _slog(s):
        if _step:
            try:
                import xbmc; xbmc.log('[DLstep] %s' % s, xbmc.LOGINFO)
            except Exception:
                pass
    _slog('A build_opener')
    if _NOVERIFY_CTX is not None:
        opener = _urlreq.build_opener(_urlreq.HTTPSHandler(context=_NOVERIFY_CTX))
    else:
        opener = _urlreq.build_opener()
    try:
        _slog('B open ' + url[:60])
        resp = opener.open(req, timeout=sock_timeout)
        _slog('C connected')
    except _urlerr.HTTPError as e:
        code = getattr(e, 'code', None)
        if code in (403, 410):
            err = Exception('HTTP %d' % code)
            err.code = code
            raise err
        raise
    try:
        deadline = _t.time() + _STALL_DEADLINE
        chunks = []
        while True:
            chunk = resp.read(131072)
            if not chunk:
                break
            chunks.append(chunk)
            if _t.time() > deadline:
                raise IOError('segment stalled (> %ds)' % _STALL_DEADLINE)
        _slog('D read done %dKB' % (sum(len(c) for c in chunks) // 1024))
        return b''.join(chunks)
    finally:
        try:
            resp.close()
        except Exception:
            pass


_dbg_seg = [0]   # diagnostic: log timing for the first N segment fetches


def _is_dns_error(exc):
    """True only for genuine name-resolution failures (host blocked/unknown)."""
    import socket as _sock
    if isinstance(exc, _sock.gaierror):
        return True
    s = str(exc).lower()
    return ('getaddrinfo' in s or 'name or service not known' in s or
            'name resolution' in s or 'nodename nor servname' in s or
            'no address associated' in s)


def _http_get(url, headers=None, timeout=30):
    host = (_urlsplit(url).netloc or '').lower()
    # Playlist + key (vixcloud.co, Cloudflare/ISP-blocked) → DoH+cipher session.
    if 'vixcloud' in host or 'streamingcommunit' in host:
        return _session_get(url, headers, timeout)
    # Segments (OVH CDN) → stdlib. stdlib parallelizes well in Kodi (the addon's
    # requests+DoH adapter serializes connection creation to ~1). The only
    # hazard was concurrent getaddrinfo hanging — eliminated by prewarm_dns()
    # which resolves every host once, serially, before the parallel fetch.
    import time as _t
    _dbg = _dbg_seg[0] < 500
    t0 = _t.time()
    try:
        data = _stdlib_get(url, headers, timeout)
        if _dbg:
            _dbg_seg[0] += 1
            logger.info('[DLseg] stdlib OK %s %.2fs %dKB' % (host, _t.time() - t0, len(data) // 1024))
        return data
    except Exception as e:
        if getattr(e, 'code', None) in (403, 410):
            raise
        if _is_dns_error(e):
            return _session_get(url, headers, timeout)
        raise


def _default_headers(referer_url=''):
    ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
    try:
        from core import httptools
        ua = httptools.default_headers.get('User-Agent', ua)
    except Exception:
        pass
    headers = {'User-Agent': ua}
    if referer_url:
        m = re.match(r'(https?://[^/]+)', referer_url)
        if m:
            headers['Referer'] = m.group(1) + '/'
    return headers


# ── Stream resolution ───────────────────────────────────────────────────────

def _resolve_master(page_url):
    """Resolve a content page to its HLS master playlist URL. Serialized
    because the streamingcommunityws connector keeps state in module globals."""
    from core import servertools
    with _RESOLVE_LOCK:
        urls, ok, err = servertools.resolve_video_urls_for_playing(_SERVER, page_url)
    if not urls:
        raise RuntimeError('resolve failed: %s' % (err or 'no urls'))
    # streamingcommunityws returns a single ['hls [..]', master_url] entry.
    return urls[-1][1]


# ── Generic (any VOD channel) resolution: HLS or progressive file ───────────

_IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
_HLS_PREF_SERVERS = ('maxstream',)   # prefer these (HLS) over progressive hosts
# A URL is a progressive file ONLY if its path ends with one of these. Tokenized
# HLS URLs (e.g. vixcloud.co/playlist/NNN?token=…) have NO .m3u8 suffix, so we
# must NOT classify "no .m3u8" as a file — default to HLS instead.
_PROGRESSIVE_EXT = ('.mp4', '.mkv', '.avi', '.webm', '.m4v', '.mov', '.flv')


def _kind_for(url):
    path = (url or '').split('?')[0].lower()
    return 'file' if path.endswith(_PROGRESSIVE_EXT) else 'hls'


def _is_image(url):
    u = (url or '').split('?')[0].lower()
    return any(u.endswith(ext) for ext in _IMAGE_EXT)


def _media_ext(url):
    u = (url or '').split('?')[0].lower()
    for ext in ('.mkv', '.mp4', '.webm', '.avi', '.m4v'):
        if u.endswith(ext):
            return ext
    return '.mp4'


def _media_headers(server, url):
    srv = (server or '').lower()
    h = _default_headers(url)
    if srv == 'maxstream':
        # host-cdn.net segments validate against the embed origin, not the CDN host.
        h['Referer'] = 'https://maxstream.video/'
        h['Origin'] = 'https://maxstream.video'
    return h


def _channel_server_items(item):
    """Call the item's channel findvideos()/action → list of server items
    (mirrors prippihome's search prefetch _fetch_servers)."""
    ch_name = (getattr(item, 'channel', '') or '').lower()
    if not ch_name:
        return []
    try:
        ch = __import__('channels.' + ch_name, fromlist=[ch_name])
        act = getattr(item, 'action', '') or 'findvideos'
        if act == 'check' and hasattr(ch, 'check'):
            sv = ch.check(item)
        elif act and act not in ('play', 'findvideos') and hasattr(ch, act):
            sv = getattr(ch, act)(item)
        elif hasattr(ch, 'findvideos'):
            sv = ch.findvideos(item)
        else:
            return []
        return [i for i in (sv or []) if getattr(i, 'server', None)]
    except Exception as exc:
        logger.error('[DLManager] _channel_server_items ch=%s: %s'
                     % (ch_name, str(exc)[:160]))
        return []


def _order_dl_servers(items):
    """HLS-capable servers first (better seeking/quality), then favorite order."""
    try:
        from core.servertools import sort_servers
        items = sort_servers(list(items))
    except Exception:
        items = list(items)
    return sorted(items, key=lambda s: 0 if (getattr(s, 'server', '') or '').lower()
                  in _HLS_PREF_SERVERS else 1)


def _resolve_media(page_url, channel='', item=None):
    """Resolve a content reference to a final media URL.
    Returns (media_url, kind, headers) with kind in {'hls','file'}.
    SC keeps the streamingcommunityws path; other channels resolve via their
    findvideos() server items + servertools.resolve_video_urls_for_playing."""
    from core import servertools
    ch = (channel or '').lower()
    logger.info('[DLManager] _resolve_media ch=%r page=%.80s' % (ch, page_url or ''))
    if ch in ('', 'streamingcommunity'):
        u = _resolve_master(page_url)
        return u, _kind_for(u), _default_headers(u)
    if item is None:
        raise RuntimeError('non-SC resolve needs the source item')
    server_items = _channel_server_items(item)
    logger.info('[DLManager] _resolve_media ch=%s -> %d server items: %s'
                % (ch, len(server_items),
                   [getattr(s, 'server', '?') for s in server_items][:6]))
    if not server_items:
        raise RuntimeError('channel %s returned no server links' % ch)
    last_err = ''
    for si in _order_dl_servers(server_items):
        srv = (getattr(si, 'server', '') or '').lower()
        try:
            urls, ok, _ = servertools.resolve_video_urls_for_playing(srv, si.url)
            if ok and urls:
                u = urls[-1][1]
                if _is_image(u):
                    continue
                logger.info('[DLManager] resolved %s via %s -> %.60s'
                            % (ch, srv, u))
                return u, _kind_for(u), _media_headers(srv, u)
        except Exception as exc:
            last_err = str(exc)[:120]
    raise RuntimeError('no playable url for %s (%s)' % (ch, last_err or 'none'))


def probe_qualities(page_url):
    """Resolve *page_url* and return its available variants (best-first):
    [{'height','resolution','bandwidth','url'}, ...]. [] on failure."""
    try:
        master_url = _resolve_master(page_url)
        headers = _default_headers(master_url)
        text = _http_get(master_url, headers=headers).decode('utf-8', 'ignore')
        info = hls_downloader.parse_master(text, master_url)
        if info['is_master']:
            return info['variants']
        # Single-rendition stream — expose one pseudo-variant.
        return [{'height': 0, 'resolution': 'auto', 'bandwidth': 0, 'url': master_url}]
    except Exception as exc:
        logger.error('[DLManager] probe_qualities: %s' % str(exc)[:160])
        return []


def _pick_variant(variants, target_height):
    """Choose the variant matching *target_height* (0 = best available)."""
    if not variants:
        return None
    if not target_height:
        return variants[0]
    exact = [v for v in variants if v['height'] == target_height]
    if exact:
        return exact[0]
    # Highest variant not exceeding the target, else the lowest available.
    le = [v for v in variants if v['height'] and v['height'] <= target_height]
    if le:
        return max(le, key=lambda v: v['height'])
    return variants[-1]


# ── Multi-track (audio/subtitle) helpers ────────────────────────────────────

_LANG_NAMES = {
    'it': u'Italiano', 'ita': u'Italiano', 'en': u'English', 'eng': u'English',
    'ja': u'Giapponese', 'jpn': u'Giapponese', 'jp': u'Giapponese',
    'es': u'Spagnolo', 'spa': u'Spagnolo', 'fr': u'Francese', 'fra': u'Francese',
    'de': u'Tedesco', 'deu': u'Tedesco', 'ger': u'Tedesco', 'pt': u'Portoghese',
    'ru': u'Russo', 'zh': u'Cinese', 'ko': u'Coreano', 'ar': u'Arabo',
}


def _lang_label(track):
    """Human label for an audio/sub track (for the selector + HLS NAME)."""
    name = (track.get('name') or '').strip()
    lang = (track.get('language') or '').strip().lower()
    if name and name.lower() not in ('audio', 'sub', 'und', ''):
        return name
    return _LANG_NAMES.get(lang, name or (lang.upper() if lang else u'Traccia'))


def probe_tracks(page_url, channel='', item=None):
    """Resolve *page_url* (channel-aware) and return the track set for the SCARICA
    dialog: {'variants':[...], 'audios':[...], 'subtitles':[...], 'master_url',
    'kind':'hls'|'file', 'media_url', 'headers'}. {} on failure.
    For a progressive (non-HLS) source the result has kind='file' and a single
    pseudo-variant; for a plain HLS without #EXT-X-STREAM-INF a pseudo-variant is
    synthesized so the UI doesn't treat it as 'no stream'."""
    try:
        media_url, kind, headers = _resolve_media(page_url, channel, item)
        if kind == 'file':
            return {'variants': [{'height': 0, 'resolution': 'auto',
                                  'bandwidth': 0, 'url': media_url}],
                    'audios': [], 'subtitles': [], 'master_url': media_url,
                    'kind': 'file', 'media_url': media_url, 'headers': headers}
        text = _http_get(media_url, headers=headers).decode('utf-8', 'ignore')
        info = hls_downloader.parse_master(text, media_url)
        if not info.get('variants'):
            # Single-rendition media playlist (no master) — expose one variant.
            info['variants'] = [{'height': 0, 'resolution': 'auto',
                                 'bandwidth': 0, 'url': media_url}]
        for a in info.get('audios', []):
            a['label'] = _lang_label(a)
        for s in info.get('subtitles', []):
            s['label'] = _lang_label(s)
        info['master_url'] = media_url
        info['kind'] = 'hls'
        info['headers'] = headers
        return info
    except Exception as exc:
        logger.error('[DLManager] probe_tracks: %s' % str(exc)[:160])
        return {}


def _select_tracks(tracks, wanted_langs):
    """Filter audio/sub track dicts by a list of language codes. None = keep all.
    Matching is by 'language' prefix (it/ita) or exact label."""
    if wanted_langs is None:
        return list(tracks)
    want = set(l.lower() for l in wanted_langs)
    out = []
    for t in tracks:
        lang = (t.get('language') or '').lower()
        if lang in want or any(lang.startswith(w) or w.startswith(lang)
                               for w in want if lang) or (t.get('label', '') in wanted_langs):
            out.append(t)
    return out


def _m3u8_media(resource, duration):
    """A single-segment VOD media playlist: the whole track file is one segment.
    Fallback only — HLS seeking is segment-granular, so a single huge segment is
    NOT seekable (the player re-opens segment 0 from the start on every seek, and
    a separate audio rendition stalls). Use _m3u8_byterange whenever per-segment
    boundaries are known."""
    import math
    td = max(1, int(math.ceil(duration or 1)))
    return (u'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:%d\n'
            u'#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:%.3f,\n%s\n#EXT-X-ENDLIST\n'
            % (td, float(duration or td), resource))


def _m3u8_byterange(resource, segments):
    """A seekable VOD media playlist describing one concatenated track file as
    many byte-range sub-segments. *segments* is [[duration, byte_len], ...] in
    file order. Every entry points at the same *resource*; #EXT-X-BYTERANGE gives
    each its offset, so the player has real seek granularity into the single .ts
    while the local server still decrypts each range by absolute offset."""
    import math
    maxd = max((float(s[0]) for s in segments), default=1.0)
    td = max(1, int(math.ceil(maxd or 1)))
    lines = [u'#EXTM3U', u'#EXT-X-VERSION:4',
             u'#EXT-X-TARGETDURATION:%d' % td, u'#EXT-X-PLAYLIST-TYPE:VOD']
    offset = 0
    for dur, length in segments:
        length = int(length)
        lines.append(u'#EXTINF:%.3f,' % float(dur))
        lines.append(u'#EXT-X-BYTERANGE:%d@%d' % (length, offset))
        lines.append(resource)
        offset += length
    lines.append(u'#EXT-X-ENDLIST')
    return u'\n'.join(lines) + u'\n'


def _media_playlist(resource, segments, duration):
    """Seekable byte-range playlist when per-segment boundaries are known,
    else a single-segment fallback."""
    if segments:
        return _m3u8_byterange(resource, segments)
    return _m3u8_media(resource, duration)


def _write_bundle_playlists(bundle_dir, video, audios, subs):
    """Write the static local-HLS playlists (relative URIs) into *bundle_dir*.
    video={'duration','codecs','resolution','bandwidth','segments'}
    audios=[{'idx','label','language','default','duration','segments'}]
    subs=[{'idx','label','language'}]  (durations default to the video's).
    'segments' (when present) is [[dur, byte_len], ...] → a seekable byte-range
    playlist; absent → single-segment fallback."""
    vdur = video.get('duration') or 0
    # Media playlists per track. Segment resource names: v, a<i>, s<i>.vtt.
    _wfile(bundle_dir, 'v.m3u8', _media_playlist('v', video.get('segments'), vdur))
    for a in audios:
        _wfile(bundle_dir, 'a%d.m3u8' % a['idx'],
               _media_playlist('a%d' % a['idx'], a.get('segments'),
                               a.get('duration') or vdur))
    for s in subs:
        # The .vtt is a plaintext sidecar served by its real filename.
        _wfile(bundle_dir, 's%d.m3u8' % s['idx'],
               _m3u8_media('sub.%d.vtt' % s['idx'], vdur))

    # Master playlist.
    lines = [u'#EXTM3U', u'#EXT-X-VERSION:3']
    if audios:
        adef = next((a for a in audios if a.get('default')), audios[0])
        for a in audios:
            lines.append(
                u'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="%s",LANGUAGE="%s",'
                u'DEFAULT=%s,AUTOSELECT=YES,URI="a%d.m3u8"'
                % (a['label'], a.get('language') or 'und',
                   'YES' if a is adef else 'NO', a['idx']))
    if subs:
        for s in subs:
            lines.append(
                u'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub",NAME="%s",LANGUAGE="%s",'
                u'DEFAULT=NO,AUTOSELECT=YES,FORCED=NO,URI="s%d.m3u8"'
                % (s['label'], s.get('language') or 'und', s['idx']))
    stream = u'#EXT-X-STREAM-INF:BANDWIDTH=%d' % int(video.get('bandwidth') or 4000000)
    if video.get('resolution'):
        stream += u',RESOLUTION=%s' % video['resolution']
    if video.get('codecs'):
        stream += u',CODECS="%s"' % video['codecs']
    if audios:
        stream += u',AUDIO="aud"'
    if subs:
        stream += u',SUBTITLES="sub"'
    lines.append(stream)
    lines.append(u'v.m3u8')
    _wfile(bundle_dir, 'master.m3u8', u'\n'.join(lines) + u'\n')


def _wfile(d, name, text):
    with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
        f.write(text)


# ── Filesystem helpers ──────────────────────────────────────────────────────

def _download_dir():
    path = config.get_setting('downloadpath') or ''
    if not path:
        path = os.path.join(config.get_data_path(), 'downloads')
    try:
        if not os.path.exists(path):
            os.makedirs(path)
    except Exception as exc:
        logger.error('[DLManager] mkdir %s: %s' % (path, str(exc)))
    return path


def _sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or 'download').strip()
    return (name or 'download')[:120]


# ── Manager singleton ───────────────────────────────────────────────────────

class DownloadManager(object):

    def __init__(self):
        self._q = _queue.Queue()
        self._workers = []
        self._started = False
        self._lock = threading.Lock()
        self._cancels = {}      # key -> threading.Event
        self._bg = None
        self._bg_lock = threading.Lock()
        self.on_change = None   # optional callback fired when downloads change
        self._last_notify = 0
        self._poller_started = False
        self._spd = None        # (time, total_bytes) for live MB/s on the bar

    # -- public API --

    def enqueue(self, item, target_height, protection=None, db_entry=None,
                audio_langs=None, sub_langs=None):
        """Queue a single download. *db_entry* (dict) provides the metadata for
        downloads_db; if omitted it is built from *item*.

        audio_langs/sub_langs: optional lists of language codes to include
        (None = all available). Selected at the SCARICA dialog; persisted so a
        resumed download keeps the same track selection.
        """
        if protection is None:
            # Protection is forced to XOR for every download (device-bound
            # anti-copy, fast on every platform). No user-facing setting — the
            # 'download_protection' option was removed. Existing downloads keep
            # whatever mode is stored in their DB entry, so they still play back.
            protection = 'xor'
        entry = db_entry or _entry_from_item(item)
        entry['protection'] = protection
        entry['target_height'] = int(target_height or 0)
        entry['status'] = 'queued'
        entry['progress'] = entry.get('progress', 0)
        entry['item_url'] = item.tourl()
        if audio_langs is not None:
            entry['audio_langs'] = audio_langs
        if sub_langs is not None:
            entry['sub_langs'] = sub_langs
        downloads_db.upsert(entry)
        _install_dns_cache()
        _active[0] += 1
        _sync_flag()
        self._ensure_poller()
        self._ensure_workers()
        self._q.put({'key': entry['key'], 'item': item,
                     'target_height': int(target_height or 0),
                     'protection': protection,
                     'audio_langs': entry.get('audio_langs'),
                     'sub_langs': entry.get('sub_langs')})
        # The BG bar is shown by the poller thread (no GUI on this path).

    def enqueue_many(self, jobs, target_height, protection=None,
                     audio_langs=None, sub_langs=None):
        """jobs: list of (item, db_entry). One quality applies to all."""
        for item, db_entry in jobs:
            self.enqueue(item, target_height, protection=protection,
                         db_entry=db_entry, audio_langs=audio_langs,
                         sub_langs=sub_langs)

    def _ensure_poller(self):
        """Start (once) a background thread that drives ALL GUI updates for
        downloads — the background progress bar and the home 'I miei download'
        row. Keeping GUI work OFF the download writer thread means a busy Kodi
        GUI can never block/stall the download itself."""
        with self._lock:
            if self._poller_started:
                return
            self._poller_started = True

        def _poll():
            import time as _t
            while _active[0] > 0:
                # Only the lightweight BG progress bar during the download. We do
                # NOT refresh the home row here: rebuilding it (reset+addItems+
                # setInfo) is heavy GUI work that contends for the GIL/GUI and
                # was throttling the download. The row is refreshed once at the
                # end (and on completion of each job).
                try:
                    self._update_bg()
                except Exception:
                    pass
                _t.sleep(3)
            try:
                self._update_bg()      # close the bar once nothing is active
                self._notify(force=True)   # final row refresh
            except Exception:
                pass
            with self._lock:
                self._poller_started = False

        t = threading.Thread(target=_poll)
        t.daemon = True
        t.start()

    def cancel(self, key):
        ev = self._cancels.get(key)
        if ev:
            ev.set()
        downloads_db.update_fields(key, status='paused')
        self._update_bg()

    def resume_pending(self):
        """Re-enqueue downloads left unfinished by a previous session."""
        from core.item import Item
        for e in downloads_db.get_active():
            try:
                item = Item().fromurl(e['item_url'])
                self.enqueue(item, e.get('target_height', 0),
                             protection=e.get('protection'), db_entry=e)
            except Exception as exc:
                logger.error('[DLManager] resume %s: %s' % (e.get('key'), str(exc)))

    # -- worker plumbing --

    def _ensure_workers(self):
        with self._lock:
            if self._started:
                return
            try:
                n = int(config.get_setting('download_concurrency') or 1)
            except Exception:
                n = 1
            n = max(1, min(3, n))
            for _ in range(n):
                t = threading.Thread(target=self._worker)
                t.daemon = True
                t.start()
                self._workers.append(t)
            self._started = True

    def _worker(self):
        while True:
            job = self._q.get()
            try:
                if job is not None:
                    self._run_job(job)
            except Exception as exc:
                logger.error('[DLManager] worker: %s' % str(exc)[:200])
                try:
                    downloads_db.update_fields(job['key'], status='error',
                                               error=str(exc)[:200])
                except Exception:
                    pass
            finally:
                # No GUI work here — the poller thread owns all UI updates so a
                # busy GUI can't block the download worker.
                _active[0] = max(0, _active[0] - 1)
                _sync_flag()
                self._q.task_done()

    def _notify(self, force=False):
        cb = self.on_change
        if not cb:
            return
        import time as _t
        now = _t.time()
        if not force and (now - self._last_notify) < 4:
            return
        self._last_notify = now
        try:
            cb()
        except Exception as exc:
            logger.error('[DLManager] on_change: %s' % str(exc))

    def _run_job(self, job):
        key = job['key']
        item = job['item']
        cancel_evt = threading.Event()
        self._cancels[key] = cancel_evt
        downloads_db.update_fields(key, status='downloading', error='')

        entry = downloads_db.get(key) or {}
        page_url = item.url
        channel = (getattr(item, 'channel', '') or '')

        # Full resolve (channel-aware): video variants + separate audio + subs.
        info = probe_tracks(page_url, channel=channel, item=item)
        variants = info.get('variants') or []
        if not variants:
            raise RuntimeError('no playable variant (resolve failed)')
        variant = _pick_variant(variants, job['target_height'])
        if not variant:
            raise RuntimeError('no playable variant')
        headers = info.get('headers') or _default_headers(variant['url'])
        quality_lbl = ('%dp' % variant['height']) if variant.get('height') else 'auto'

        out_dir = _download_dir()
        fname = _output_basename(entry)
        cipher = download_crypto.get_cipher(job['protection'])

        # Progressive (non-HLS) source (e.g. mixdrop .mp4): stream the file,
        # encrypt-on-write, single output file. No separate audio/subtitle tracks.
        if info.get('kind') == 'file':
            self._run_file(job, key, entry, variant['url'], headers, out_dir,
                           fname, quality_lbl, cipher, cancel_evt)
            return

        audios = info.get('audios') or []
        subs = info.get('subtitles') or []
        chosen_audios = _select_tracks(audios, job.get('audio_langs'))
        want_subs = True   # always download all subtitle tracks (no prompt)
        chosen_subs = _select_tracks(subs, job.get('sub_langs')) if want_subs else []

        try:
            import xbmc
            xbmc.log('[DLcrypto] encrypt protection=%s keyfp=%s audios=%d subs=%d' % (
                job['protection'], download_crypto.key_fingerprint(),
                len(chosen_audios), len(chosen_subs)), xbmc.LOGINFO)
        except Exception:
            pass

        # A bundle (local multi-track HLS) is built whenever there is a SEPARATE
        # audio rendition to fetch (video segments would otherwise be silent) or
        # subtitles to offer for selection. Otherwise the variant already carries
        # muxed audio → a single .ts is simpler and plays directly.
        if chosen_audios or chosen_subs:
            self._run_bundle(job, key, entry, page_url, variant, chosen_audios,
                             chosen_subs, headers, out_dir, fname, quality_lbl,
                             cipher, cancel_evt)
            return

        out_path = os.path.join(out_dir, fname + '.ts')
        downloads_db.update_fields(key, file_path=out_path, quality=quality_lbl,
                                   bundle=False)
        import time as _t
        prog_state = {'t': 0.0}

        def _progress(done, total, nbytes):
            # CRITICAL: this runs on the download's writer thread. It must do NO
            # GUI work — GUI calls from a non-GUI thread BLOCK when Kodi's GUI is
            # busy (e.g. the home populating rows), which would stall the writer.
            # The BG bar + home row are driven by a separate poller thread.
            now = _t.time()
            if (now - prog_state['t']) < 1.0 and done < total:
                return
            prog_state['t'] = now
            pct = (done * 100.0 / total) if total else 0
            downloads_db.update_fields(key, progress=round(pct, 1),
                                       total_bytes=nbytes)

        try:
            self._dl_one(variant['url'], headers, out_path, cipher, cancel_evt,
                         _progress, job, 'video', 0, None)
        except hls_downloader.DownloadCancelled:
            downloads_db.update_fields(key, status='paused')
            return
        finally:
            self._cancels.pop(key, None)

        downloads_db.update_fields(key, status='done', progress=100.0, sub_path='')
        self._notify_done(entry)

    def _fresh_url(self, job, kind, idx):
        """Re-resolve (channel-aware) and return a fresh (url, headers) for the
        given track after a token expiry."""
        item = job['item']
        info = probe_tracks(item.url, channel=getattr(item, 'channel', '') or '',
                            item=item)
        hdrs = info.get('headers')
        if kind == 'audio':
            a = (info.get('audios') or [])[idx]
            return a['url'], hdrs or _default_headers(a['url'])
        variants = info.get('variants') or []
        v = _pick_variant(variants, job['target_height'])
        if not v:
            raise RuntimeError('no variant on re-resolve')
        return v['url'], hdrs or _default_headers(v['url'])

    def _run_file(self, job, key, entry, url, headers, out_dir, fname,
                  quality_lbl, cipher, cancel_evt):
        """Download a progressive media file (mp4/mkv), encrypting on write, into a
        single output file played back via the local server (range-decrypt)."""
        from core import file_downloader
        ext = _media_ext(url)
        out_path = os.path.join(out_dir, fname + ext)
        downloads_db.update_fields(key, file_path=out_path, quality=quality_lbl,
                                   bundle=False)
        try:
            import xbmc
            xbmc.log('[DLcrypto] encrypt(file) protection=%s keyfp=%s ext=%s' % (
                job['protection'], download_crypto.key_fingerprint(), ext),
                xbmc.LOGINFO)
        except Exception:
            pass
        import time as _t
        prog_state = {'t': 0.0}

        def _progress(done, total, nbytes):
            now = _t.time()
            if (now - prog_state['t']) < 1.0 and done < total:
                return
            prog_state['t'] = now
            pct = (done * 100.0 / total) if total else 0
            downloads_db.update_fields(key, progress=round(pct, 1),
                                       total_bytes=nbytes)

        try:
            file_downloader.download_file(
                url, headers, out_path, progress_cb=_progress,
                cancel_evt=cancel_evt, encrypt=cipher.process)
        except file_downloader.DownloadCancelled:
            downloads_db.update_fields(key, status='paused')
            return
        finally:
            self._cancels.pop(key, None)

        downloads_db.update_fields(key, status='done', progress=100.0, sub_path='')
        self._notify_done(entry)

    def _dl_one(self, url, headers, out_path, cipher, cancel_evt, progress_cb,
                job, kind, idx, meta_out):
        """Download one track (video or audio media playlist) with a single
        token-expiry re-resolve. Returns when the track is fully written."""
        max_workers = self._segment_workers()
        try:
            hls_downloader.download_stream(
                url, headers, out_path, progress_cb=progress_cb,
                cancel_evt=cancel_evt, max_workers=max_workers,
                http_get=_http_get, encrypt=cipher.process,
                prewarm=prewarm_dns, meta_out=meta_out)
        except hls_downloader.TokenExpiredError:
            logger.info('[DLManager] token expired (%s/%s), re-resolving' % (kind, idx))
            url2, headers2 = self._fresh_url(job, kind, idx)
            hls_downloader.download_stream(
                url2, headers2, out_path, progress_cb=progress_cb,
                cancel_evt=cancel_evt, max_workers=max_workers,
                http_get=_http_get, encrypt=cipher.process,
                prewarm=prewarm_dns, meta_out=meta_out)

    def _run_bundle(self, job, key, entry, page_url, variant, audios, subs,
                    headers, out_dir, fname, quality_lbl, cipher, cancel_evt):
        """Download video + each selected audio rendition + subtitles into a
        per-download directory, then write the local HLS playlists that Kodi
        muxes at playback (native audio/subtitle selection)."""
        import os as _os
        bundle_dir = _os.path.join(out_dir, _sanitize(key))
        try:
            _os.makedirs(bundle_dir)
        except OSError:
            pass
        master_pl = _os.path.join(bundle_dir, 'master.m3u8')
        downloads_db.update_fields(key, quality=quality_lbl, bundle=True,
                                   bundle_dir=bundle_dir, file_path=master_pl)

        import time as _t
        prog_state = {'t': 0.0, 'bytes': 0}
        n_audio = len(audios)

        def _progress(done, total, nbytes):
            now = _t.time()
            if (now - prog_state['t']) < 1.0 and done < total:
                return
            prog_state['t'] = now
            # Video is ~95% of the bytes; map it to 0-97% so audio/subs finish 100.
            pct = (done * 97.0 / total) if total else 0
            prog_state['bytes'] = nbytes
            downloads_db.update_fields(key, progress=round(pct, 1),
                                       total_bytes=nbytes)

        def _audio_progress(track_i):
            # Map each audio rendition into its slice of the 97→100% tail so the
            # bar keeps moving while the (large) audio tracks download instead of
            # sitting frozen at 97%.
            span = 3.0 / max(1, n_audio)
            base = 97.0 + track_i * span

            def cb(done, total, nbytes):
                now = _t.time()
                if (now - prog_state['t']) < 1.0 and done < total:
                    return
                prog_state['t'] = now
                frac = (done / total) if total else 1.0
                downloads_db.update_fields(
                    key, progress=round(min(99.9, base + span * frac), 1),
                    total_bytes=prog_state['bytes'] + nbytes)
            return cb

        try:
            # 1) Video track (the bulk; drives the progress bar).
            vmeta = {}
            self._dl_one(variant['url'], headers,
                         _os.path.join(bundle_dir, 'video.ts'), cipher,
                         cancel_evt, _progress, job, 'video', 0, vmeta)
            vdur = vmeta.get('duration') or 0

            # 2) Audio renditions (separate, video-only-segment streams).
            audio_metas = []
            for i, a in enumerate(audios):
                am = {}
                self._dl_one(a['url'], _default_headers(a['url']),
                             _os.path.join(bundle_dir, 'audio.%d.ts' % i), cipher,
                             cancel_evt, _audio_progress(i), job, 'audio', i, am)
                prog_state['bytes'] += am.get('bytes', 0)
                audio_metas.append({
                    'idx': i, 'label': _lang_label(a),
                    'language': a.get('language', ''),
                    'default': bool(a.get('default')),
                    'duration': am.get('duration') or vdur,
                    'segments': am.get('segments')})

            # 3) Subtitles (plaintext WebVTT sidecars; not encrypted).
            sub_metas = []
            for i, s in enumerate(subs):
                ok = hls_downloader.download_subtitle(
                    s['url'], _default_headers(s['url']),
                    _os.path.join(bundle_dir, 'sub.%d.vtt' % i), http_get=_http_get)
                if ok:
                    sub_metas.append({'idx': i, 'label': _lang_label(s),
                                      'language': s.get('language', '')})
        except hls_downloader.DownloadCancelled:
            downloads_db.update_fields(key, status='paused')
            return
        finally:
            self._cancels.pop(key, None)

        # 4) Local HLS playlists (static, relative URIs) + bundle manifest.
        video_pl = {'duration': vdur, 'codecs': variant.get('codecs', ''),
                    'resolution': variant.get('resolution', ''),
                    'bandwidth': variant.get('bandwidth', 0),
                    'segments': vmeta.get('segments')}
        _write_bundle_playlists(bundle_dir, video_pl, audio_metas, sub_metas)
        try:
            import json as _json
            with open(_os.path.join(bundle_dir, 'bundle.json'), 'w',
                      encoding='utf-8') as f:
                _json.dump({'video': video_pl, 'audio': audio_metas,
                            'subs': sub_metas, 'protection': job['protection']}, f)
        except Exception:
            pass

        # The DB row only needs track labels/languages for the UI — keep the
        # bulky per-segment lists out of it (they live in the playlists +
        # bundle.json).
        db_audio = [{k: v for k, v in a.items() if k != 'segments'}
                    for a in audio_metas]
        downloads_db.update_fields(key, status='done', progress=100.0,
                                   bundle=True, bundle_dir=bundle_dir,
                                   file_path=master_pl, tracks={'audio': db_audio,
                                                                'subs': sub_metas})
        self._notify_done(entry)

    def _download_subs(self, page_url, out_dir, fname, headers):
        try:
            master_url = _resolve_master(page_url)
            text = _http_get(master_url, headers=headers).decode('utf-8', 'ignore')
            info = hls_downloader.parse_master(text, master_url)
            subs = info.get('subtitles') or []
            if not subs:
                return ''
            # Prefer an Italian track, else the first.
            sub = next((s for s in subs if 'it' in (s.get('language', '').lower())), subs[0])
            sub_path = os.path.join(out_dir, fname + '.it.vtt')
            ok = hls_downloader.download_subtitle(sub['url'], headers, sub_path,
                                                  http_get=_http_get)
            return sub_path if ok else ''
        except Exception as exc:
            logger.error('[DLManager] subs: %s' % str(exc)[:120])
            return ''

    def _segment_workers(self):
        # With native OpenSSL AES (GIL released, ~1 GB/s) the download is now
        # network-bound, not CPU-bound. Benchmarks show throughput scaling with
        # connections (3.1 MB/s @16, 4.4 @32) with no CDN tarpitting. 16 is a
        # strong default that saturates most home links; tunable via the hidden
        # download_segment_workers setting.
        try:
            n = int(config.get_setting('download_segment_workers') or 0)
        except Exception:
            n = 0
        return n if n >= 1 else 16

    # -- background progress dialog --

    def _update_bg(self):
        try:
            import xbmcgui
        except Exception:
            return
        active = [e for e in downloads_db.get_all()
                  if e.get('status') in ('queued', 'downloading')]
        with self._bg_lock:
            if not active:
                if self._bg is not None:
                    try:
                        self._bg.close()
                    except Exception:
                        pass
                    self._bg = None
                return
            cur = next((e for e in active if e.get('status') == 'downloading'), active[0])
            pct = int(cur.get('progress', 0) or 0)
            # Live speed (MB/s) from the total downloaded-bytes delta over time.
            import time as _t
            tot_bytes = sum(int(e.get('total_bytes', 0) or 0) for e in active)
            now = _t.time()
            speed = 0.0
            if self._spd is not None:
                dt = now - self._spd[0]
                if dt > 0.5:
                    speed = max(0.0, (tot_bytes - self._spd[1]) / dt / 1048576.0)
                    self._spd = (now, tot_bytes)
            else:
                self._spd = (now, tot_bytes)
            spd_txt = (u'  %.1f MB/s' % speed) if speed > 0.05 else u''
            heading = u'Download (%d)%s' % (len(active), spd_txt)
            msg = u'%s — %s%s' % (cur.get('title', ''), cur.get('quality', ''), spd_txt)
            if self._bg is None:
                self._bg = xbmcgui.DialogProgressBG()
                self._bg.create(heading, msg)
            self._bg.update(pct, heading, msg)

    def _notify_done(self, entry):
        try:
            import xbmcgui
            xbmcgui.Dialog().notification(
                u'PrippiStream',
                u'Download completato: %s' % entry.get('title', ''),
                xbmcgui.NOTIFICATION_INFO, 4000)
        except Exception:
            pass


# ── Entry builders ──────────────────────────────────────────────────────────

def _entry_from_item(item):
    ct = getattr(item, 'contentType', '') or ''
    title = (getattr(item, 'fulltitle', '') or getattr(item, 'show', '') or
             getattr(item, 'contentTitle', '') or getattr(item, 'title', '') or '')
    title = re.sub(r'\[/?[A-Za-z][^\]]*\]', '', title).strip()
    if ct == 'episode':
        season = int(getattr(item, 'contentSeason', 0) or 0)
        episode = int(getattr(item, 'contentEpisodeNumber', 0) or
                      getattr(item, 'episode', 0) or 0)
        show = (getattr(item, 'contentSerieName', '') or getattr(item, 'show', '') or title)
        show = re.sub(r'\[/?[A-Za-z][^\]]*\]', '', show).strip()
        show_key = 'dlshow_' + _sanitize(show).lower().replace(' ', '_')
        key = '%s_s%de%d' % (show_key, season, episode)
        ep_title = getattr(item, 'contentTitle', '') or (u'Episodio %d' % episode)
        return {
            'key': key, 'type': 'episode', 'title': ep_title,
            'show_title': show, 'show_key': show_key,
            'season': season, 'episode': episode,
            'thumbnail': getattr(item, 'thumbnail', '') or '',
            'fanart': getattr(item, 'fanart', '') or getattr(item, 'thumbnail', '') or '',
        }
    return {
        'key': 'dlmovie_' + _sanitize(title).lower().replace(' ', '_'),
        'type': 'movie', 'title': title, 'show_title': '', 'show_key': '',
        'season': 0, 'episode': 0,
        'thumbnail': getattr(item, 'thumbnail', '') or '',
        'fanart': getattr(item, 'fanart', '') or getattr(item, 'thumbnail', '') or '',
    }


def _output_basename(entry):
    if entry.get('type') == 'episode':
        return _sanitize('%s S%02dE%02d' % (entry.get('show_title', 'serie'),
                                            int(entry.get('season', 0) or 0),
                                            int(entry.get('episode', 0) or 0)))
    return _sanitize(entry.get('title', 'film'))


_manager = None
_manager_lock = threading.Lock()


def get_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = DownloadManager()
        return _manager
