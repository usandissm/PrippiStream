# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# hls_downloader — pure-python HLS (m3u8) downloader
#
# Downloads an HLS variant to a single concatenated .ts file that plays
# offline with no ffmpeg dependency. Handles:
#   - master playlist parsing (quality variants + subtitle tracks)
#   - media playlist parsing (segments + AES-128 key)
#   - parallel segment download with strict in-order writing
#   - AES-128-CBC segment decryption (pycryptodome if present, else lib/pyaes)
#   - resume of an interrupted download (sidecar .dlmeta)
#
# This module is intentionally self-contained and Kodi-independent so it can
# be unit-tested standalone. The HTTP fetcher is injectable (http_get) — the
# download_manager passes one wired to the addon's httptools/headers; the
# default uses urllib from the stdlib.
# ------------------------------------------------------------

from __future__ import division

import os
import re
import json
import binascii
import struct
import threading

try:
    from urllib.parse import urljoin, urlsplit
    import urllib.request as _urllib_request
except ImportError:  # py2
    from urlparse import urljoin, urlsplit
    import urllib2 as _urllib_request

try:
    from concurrent import futures as _futures
except ImportError:
    from concurrent_py2 import futures as _futures


# ── AES-128-CBC backend (CDN segment decryption) ────────────────────────────
# Backend preference (all byte-identical, PKCS7 stripped manually):
#   1) pycryptodome  — C, fast, if some other addon provides it
#   2) native_aes    — Kodi's bundled OpenSSL via ctypes (no dependency, ~1 GB/s,
#                      releases the GIL → keeps the skin responsive)
#   3) pyaes         — pure-python last resort (~0.4 MB/s, holds the GIL)
_HAS_PYCRYPTO = False
try:
    from Crypto.Cipher import AES as _CAES
    _HAS_PYCRYPTO = True
except Exception:
    _CAES = None
try:
    from core import native_aes as _native_aes
except Exception:
    try:
        import native_aes as _native_aes
    except Exception:
        _native_aes = None
try:
    from lib import pyaes as _pyaes
except Exception:
    _pyaes = None


class TokenExpiredError(Exception):
    """Raised when segments repeatedly return 403/410 — the stream URL's token
    has likely expired and the caller should re-resolve the stream."""


class DownloadCancelled(Exception):
    """Raised cooperatively when the cancel event is set."""


def _pkcs7_unpad(data):
    if not data:
        return data
    pad = data[-1]
    if not isinstance(pad, int):
        pad = ord(pad)
    if 1 <= pad <= 16 and len(data) >= pad and data[-pad:] == (bytes(bytearray([pad])) * pad):
        return data[:-pad]
    return data


_BACKEND_LOGGED = False


def _log_backend():
    global _BACKEND_LOGGED
    if _BACKEND_LOGGED:
        return
    _BACKEND_LOGGED = True
    try:
        if _HAS_PYCRYPTO:
            msg = 'pycryptodome (C)'
        elif _native_aes is not None and getattr(_native_aes, 'AVAILABLE', False):
            msg = 'native_aes/OpenSSL [%s]' % getattr(_native_aes, 'LOADED_LIB', '?')
        elif _pyaes is not None:
            attempts = getattr(_native_aes, 'LOAD_ATTEMPTS', None) if _native_aes else None
            msg = 'pyaes PURE-PYTHON (SLOW, holds GIL!) native_aes failed: %r' % (attempts,)
        else:
            msg = 'NONE'
        import xbmc
        xbmc.log('[DLaes] backend=%s' % msg, xbmc.LOGINFO)
    except Exception:
        pass


def _aes_cbc_decrypt(data, key, iv):
    _log_backend()
    if _HAS_PYCRYPTO:
        return _pkcs7_unpad(_CAES.new(key, _CAES.MODE_CBC, iv).decrypt(data))
    if _native_aes is not None and getattr(_native_aes, 'AVAILABLE', False):
        return _pkcs7_unpad(_native_aes.aes_cbc_decrypt(key, iv, data))
    if _pyaes is None:
        raise RuntimeError('No AES backend available (pycryptodome / OpenSSL / pyaes missing)')
    dec = _pyaes.Decrypter(_pyaes.AESModeOfOperationCBC(key, iv),
                           padding=_pyaes.PADDING_NONE)
    out = dec.feed(data) + dec.feed()
    return _pkcs7_unpad(out)


def _seq_to_iv(seq):
    """Default HLS IV when EXT-X-KEY has no IV attribute: 128-bit big-endian
    media sequence number of the segment."""
    return struct.pack('>QQ', 0, seq & 0xFFFFFFFFFFFFFFFF)


# ── Default HTTP fetcher (stdlib; overridable) ──────────────────────────────

def _default_http_get(url, headers=None, timeout=20):
    """Return raw bytes for *url*. Raises on HTTP error; the .code attribute is
    attached to HTTPError so callers can detect 403/410."""
    req = _urllib_request.Request(url, headers=headers or {})
    resp = _urllib_request.urlopen(req, timeout=timeout)
    try:
        return resp.read()
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _http_status(exc):
    """Best-effort extraction of an HTTP status code from an exception."""
    code = getattr(exc, 'code', None)
    if code is None:
        m = re.search(r'\b(40\d|41\d|5\d\d)\b', str(exc))
        if m:
            code = int(m.group(1))
    return code


# ── m3u8 parsing ────────────────────────────────────────────────────────────

_ATTR_RE = re.compile(r'([A-Z0-9\-]+)=("[^"]*"|[^,]*)')


def _parse_attrs(line):
    attrs = {}
    for k, v in _ATTR_RE.findall(line):
        attrs[k] = v.strip('"')
    return attrs


def _media_bool(attrs, name):
    return (attrs.get(name, 'NO') or 'NO').upper() == 'YES'


def parse_master(text, base_url):
    """Parse a master playlist.

    Returns dict:
      {'is_master': bool,
       'variants': [{'resolution','height','bandwidth','url','codecs',
                     'audio_group'}, ...] sorted desc,
       'audios':   [{'group','name','language','default','autoselect','url',
                     'channels'}, ...],
       'subtitles':[{'name','language','default','forced','url'}, ...]}

    HLS declares alternate audio (and subtitles) as #EXT-X-MEDIA renditions with
    their own URI; a video #EXT-X-STREAM-INF links to an audio group via its
    AUDIO="grp" attribute. When audio is a separate rendition the video segments
    are video-only — so to download a playable file we must fetch the audio
    rendition too. (Some streams instead MUX audio into the video segments; then
    there are no TYPE=AUDIO entries and the video variant already has sound.)
    """
    variants = []
    audios = []
    subtitles = []
    lines = text.splitlines()
    is_master = False
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith('#EXT-X-STREAM-INF:'):
            is_master = True
            attrs = _parse_attrs(line[len('#EXT-X-STREAM-INF:'):])
            uri = ''
            for j in range(i + 1, len(lines)):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith('#'):
                    uri = nxt
                    break
            if not uri:
                continue
            res = attrs.get('RESOLUTION', '')
            height = 0
            if 'x' in res:
                try:
                    height = int(res.split('x')[1])
                except Exception:
                    height = 0
            try:
                bw = int(attrs.get('BANDWIDTH', 0) or 0)
            except Exception:
                bw = 0
            variants.append({
                'resolution': res,
                'height': height,
                'bandwidth': bw,
                'codecs': attrs.get('CODECS', ''),
                'audio_group': attrs.get('AUDIO', ''),
                'url': urljoin(base_url, uri),
            })
        elif line.startswith('#EXT-X-MEDIA:') and 'TYPE=AUDIO' in line:
            attrs = _parse_attrs(line[len('#EXT-X-MEDIA:'):])
            uri = attrs.get('URI', '')
            if uri:  # an audio rendition with no URI is muxed into the video
                audios.append({
                    'group': attrs.get('GROUP-ID', ''),
                    'name': attrs.get('NAME', '') or attrs.get('LANGUAGE', 'audio'),
                    'language': attrs.get('LANGUAGE', ''),
                    'default': _media_bool(attrs, 'DEFAULT'),
                    'autoselect': _media_bool(attrs, 'AUTOSELECT'),
                    'channels': attrs.get('CHANNELS', ''),
                    'url': urljoin(base_url, uri),
                })
        elif line.startswith('#EXT-X-MEDIA:') and 'TYPE=SUBTITLES' in line:
            attrs = _parse_attrs(line[len('#EXT-X-MEDIA:'):])
            uri = attrs.get('URI', '')
            if uri:
                subtitles.append({
                    'name': attrs.get('NAME', '') or attrs.get('LANGUAGE', 'sub'),
                    'language': attrs.get('LANGUAGE', ''),
                    'default': _media_bool(attrs, 'DEFAULT'),
                    'forced': _media_bool(attrs, 'FORCED'),
                    'url': urljoin(base_url, uri),
                })

    # Sort variants best-first (by height, then bandwidth).
    variants.sort(key=lambda v: (v['height'], v['bandwidth']), reverse=True)
    return {'is_master': is_master, 'variants': variants,
            'audios': audios, 'subtitles': subtitles}


def parse_media(text, base_url):
    """Parse a media (variant) playlist.

    Returns dict:
      {'segments': [{'url', 'seq'}, ...],
       'key': {'method','uri','iv'} or None,
       'map': abs_url or None,   # EXT-X-MAP init segment (fMP4)
       'duration': float}        # sum of EXTINF (total media seconds)
    Key/IV are resolved per the EXT-X-KEY that precedes each segment; for
    simplicity we assume a single key for the whole playlist (the common case).
    """
    segments = []
    key = None
    init_map = None
    media_seq = 0
    duration = 0.0
    lines = text.splitlines()
    cur_key = None
    seq = None
    pending_dur = 0.0
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            try:
                pending_dur = float(line[len('#EXTINF:'):].split(',', 1)[0])
                duration += pending_dur
            except Exception:
                pending_dur = 0.0
        elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            try:
                media_seq = int(line.split(':', 1)[1])
            except Exception:
                media_seq = 0
            seq = media_seq
        elif line.startswith('#EXT-X-KEY:'):
            attrs = _parse_attrs(line[len('#EXT-X-KEY:'):])
            method = attrs.get('METHOD', 'NONE')
            if method == 'NONE':
                cur_key = None
            else:
                cur_key = {
                    'method': method,
                    'uri': urljoin(base_url, attrs.get('URI', '')),
                    'iv': attrs.get('IV', ''),
                }
                if key is None:
                    key = cur_key
        elif line.startswith('#EXT-X-MAP:'):
            attrs = _parse_attrs(line[len('#EXT-X-MAP:'):])
            if attrs.get('URI'):
                init_map = urljoin(base_url, attrs['URI'])
        elif line and not line.startswith('#'):
            if seq is None:
                seq = media_seq
            segments.append({'url': urljoin(base_url, line), 'seq': seq,
                             'dur': pending_dur})
            seq += 1
            pending_dur = 0.0
    return {'segments': segments, 'key': key, 'map': init_map,
            'duration': duration}


def _resolve_key(key_info, http_get, headers):
    """Fetch the AES key bytes and compute the IV per segment lazily.
    Returns (key_bytes, iv_hex_or_empty)."""
    key_bytes = http_get(key_info['uri'], headers=headers)
    if isinstance(key_bytes, str):
        key_bytes = key_bytes.encode('latin-1')
    iv_attr = key_info.get('iv') or ''
    return key_bytes, iv_attr


def _iv_for(seq, iv_attr):
    if iv_attr:
        h = iv_attr[2:] if iv_attr.lower().startswith('0x') else iv_attr
        try:
            return binascii.unhexlify(h.zfill(32))
        except Exception:
            pass
    return _seq_to_iv(seq)


# ── Sidecar resume metadata ─────────────────────────────────────────────────

def _meta_path(out_path):
    return out_path + '.dlmeta'


def _load_meta(out_path):
    try:
        with open(_meta_path(out_path), 'r') as f:
            return json.load(f)
    except Exception:
        return None


def _save_meta(out_path, meta):
    try:
        with open(_meta_path(out_path), 'w') as f:
            json.dump(meta, f)
    except Exception:
        pass


def _clear_meta(out_path):
    try:
        os.remove(_meta_path(out_path))
    except Exception:
        pass


# ── Main download routine ───────────────────────────────────────────────────

def download_stream(variant_url, headers, out_path,
                    progress_cb=None, cancel_evt=None,
                    max_workers=5, http_get=None, timeout=20, encrypt=None,
                    prewarm=None, meta_out=None):
    """Download an HLS *variant* playlist to a single concatenated .ts file.

    Segments are fetched in parallel but written strictly in order, so the
    output is a valid concatenation and memory stays bounded to ~max_workers
    segments. Supports resume via a .dlmeta sidecar.

    Args:
        variant_url: URL of the media playlist (a specific quality), or a
            master playlist (we then auto-pick the highest variant).
        headers: dict of HTTP headers (Accept-Encoding gzip should be absent).
        out_path: destination .ts file.
        progress_cb: optional callable(done_segments, total_segments, bytes_written).
        cancel_evt: optional threading.Event; when set the download aborts.
        max_workers: parallel segment connections.
        http_get: optional callable(url, headers=, timeout=) -> bytes.
        encrypt: optional callable(data, offset) -> data applied to every byte
            written (offset = position in the output file). Used for soft-DRM;
            must be a stream cipher so length is preserved and resume works.

    Returns the number of bytes written. Raises TokenExpiredError on persistent
    403/410, DownloadCancelled on cancel, or other exceptions on hard failure.
    """
    http_get = http_get or _default_http_get
    headers = dict(headers or {})
    # ISA forwards gzip and chokes; for raw download gzip would also corrupt
    # binary segments via transparent decode — strip it to be safe.
    headers.pop('Accept-Encoding', None)
    headers.pop('accept-encoding', None)

    def _check_cancel():
        if cancel_evt is not None and cancel_evt.is_set():
            raise DownloadCancelled()

    # Fetch the playlist; if it's a master, descend into the best variant.
    text = http_get(variant_url, headers=headers, timeout=timeout)
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'ignore')
    master = parse_master(text, variant_url)
    if master['is_master'] and master['variants']:
        variant_url = master['variants'][0]['url']
        text = http_get(variant_url, headers=headers, timeout=timeout)
        if isinstance(text, bytes):
            text = text.decode('utf-8', 'ignore')

    media = parse_media(text, variant_url)
    segments = media['segments']
    total = len(segments)
    if total == 0:
        raise RuntimeError('HLS playlist has no segments')
    if meta_out is not None:
        meta_out['duration'] = media.get('duration', 0.0)

    # Pre-resolve all unique segment hosts serially BEFORE the parallel fetch.
    # Concurrent getaddrinfo across 16 workers hangs on Windows (no timeout),
    # stalling the download; warming the cache first makes them all cache hits.
    if prewarm is not None:
        try:
            seen = set()
            hosts = []
            for s in segments:
                h = urlsplit(s['url']).hostname
                if h and h not in seen:
                    seen.add(h)
                    hosts.append(h)
            prewarm(hosts)
        except Exception:
            pass

    key_bytes = None
    iv_attr = ''
    if media['key'] and media['key']['method'].startswith('AES-128'):
        key_bytes, iv_attr = _resolve_key(media['key'], http_get, headers)

    # Resume: validate sidecar against the existing partial file.
    start_idx = 0
    meta = _load_meta(out_path)
    if meta and os.path.exists(out_path):
        try:
            if (meta.get('total') == total and
                    os.path.getsize(out_path) == meta.get('bytes', -1)):
                start_idx = int(meta.get('done', 0))
        except Exception:
            start_idx = 0
    if start_idx == 0:
        # Fresh start — truncate any stale partial.
        try:
            open(out_path, 'wb').close()
        except Exception:
            pass

    bytes_written = meta.get('bytes', 0) if (meta and start_idx) else 0
    fmode = 'ab' if start_idx else 'wb'

    # Per-segment (duration, on-disk byte length), accumulated as we write, so a
    # seekable local HLS playlist can be built later via EXT-X-BYTERANGE. None
    # means unavailable — a resume whose sidecar predates this data, or an fMP4
    # EXT-X-MAP prefix we don't model — and the caller then falls back to a
    # single-segment playlist.
    track_segs = []
    if start_idx:
        prev = (meta or {}).get('segs')
        if isinstance(prev, list) and len(prev) == start_idx:
            track_segs = list(prev)
        else:
            track_segs = None
    if media['map']:
        track_segs = None

    # Optional fMP4 init segment goes first (only on a fresh download).
    out = open(out_path, fmode)
    try:
        if media['map'] and start_idx == 0:
            init_bytes = http_get(media['map'], headers=headers, timeout=timeout)
            if isinstance(init_bytes, str):
                init_bytes = init_bytes.encode('latin-1')
            if encrypt:
                init_bytes = encrypt(init_bytes, bytes_written)
            out.write(init_bytes)
            bytes_written += len(init_bytes)

        def _fetch(idx):
            _check_cancel()
            if idx < 60:
                try:
                    import xbmc
                    xbmc.log('[DLstart] idx=%d' % idx, xbmc.LOGINFO)
                except Exception:
                    pass
            seg = segments[idx]
            attempts = 0
            while True:
                try:
                    data = http_get(seg['url'], headers=headers, timeout=timeout)
                    if isinstance(data, str):
                        data = data.encode('latin-1')
                    break
                except Exception as exc:
                    code = _http_status(exc)
                    if code in (403, 410):
                        raise TokenExpiredError('segment %d -> HTTP %s' % (idx, code))
                    attempts += 1
                    try:
                        import xbmc
                        xbmc.log('[DLfetch] idx=%d attempt=%d EXC: %s' % (
                            idx, attempts, str(exc)[:120]), xbmc.LOGINFO)
                    except Exception:
                        pass
                    if attempts >= 5:
                        raise
            if key_bytes is not None:
                iv = _iv_for(seg['seq'], iv_attr)
                data = _aes_cbc_decrypt(data, key_bytes, iv)
            return idx, data

        # Parallel fetch, in-order write. We keep a sliding window of completed
        # segments and flush consecutively from the write pointer.
        ready = {}
        write_ptr = start_idx
        with _futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            pending = {}
            next_submit = start_idx
            # Prime the pool.
            while next_submit < total and len(pending) < max_workers * 2:
                pending[ex.submit(_fetch, next_submit)] = next_submit
                next_submit += 1
            import time as _t_hb
            _hb = [_t_hb.time()]
            while pending:
                _check_cancel()
                _now_hb = _t_hb.time()
                if _now_hb - _hb[0] >= 3:
                    _hb[0] = _now_hb
                    try:
                        import xbmc
                        xbmc.log('[DLwriter] write_ptr=%d ready=%d pending=%d '
                                 'next=%d/%d bytes=%d' % (write_ptr, len(ready),
                                 len(pending), next_submit, total, bytes_written),
                                 xbmc.LOGINFO)
                    except Exception:
                        pass
                done_set, _ = _futures.wait(
                    pending, return_when=_futures.FIRST_COMPLETED)
                for fut in done_set:
                    idx = pending.pop(fut)
                    i, data = fut.result()    # propagates TokenExpiredError etc.
                    ready[i] = data
                    if next_submit < total:
                        pending[ex.submit(_fetch, next_submit)] = next_submit
                        next_submit += 1
                # Flush any consecutive ready segments.
                while write_ptr in ready:
                    chunk = ready.pop(write_ptr)
                    if encrypt:
                        chunk = encrypt(chunk, bytes_written)
                    out.write(chunk)
                    if track_segs is not None:
                        track_segs.append(
                            [round(segments[write_ptr].get('dur', 0.0), 3),
                             len(chunk)])
                    bytes_written += len(chunk)
                    write_ptr += 1
                    if progress_cb:
                        try:
                            progress_cb(write_ptr, total, bytes_written)
                        except Exception:
                            pass
                    _save_meta(out_path, {'total': total, 'done': write_ptr,
                                          'bytes': bytes_written,
                                          'segs': track_segs})
    finally:
        try:
            out.close()
        except Exception:
            pass

    _clear_meta(out_path)
    if meta_out is not None:
        meta_out['bytes'] = bytes_written
        meta_out['segments'] = track_segs   # [[dur, byte_len], ...] or None
    return bytes_written


def download_subtitle(sub_url, headers, out_path, http_get=None, timeout=20):
    """Best-effort: download a WebVTT subtitle track to out_path. If the URL is
    itself an m3u8 sub playlist, concatenate its segments. Returns True/False."""
    http_get = http_get or _default_http_get
    headers = dict(headers or {})
    headers.pop('Accept-Encoding', None)
    headers.pop('accept-encoding', None)
    try:
        data = http_get(sub_url, headers=headers, timeout=timeout)
        text = data.decode('utf-8', 'ignore') if isinstance(data, bytes) else data
        if '#EXTM3U' in text[:64]:
            media = parse_media(text, sub_url)
            parts = []
            for seg in media['segments']:
                d = http_get(seg['url'], headers=headers, timeout=timeout)
                parts.append(d.decode('utf-8', 'ignore') if isinstance(d, bytes) else d)
            text = '\n'.join(parts)
        with open(out_path, 'w') as f:
            f.write(text)
        return True
    except Exception:
        return False
