# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# file_downloader — progressive (non-HLS) media downloader
#
# Streams a direct media file (e.g. mixdrop's .mp4) to a single output file,
# applying the device-bound soft-DRM stream cipher on write exactly like
# core.hls_downloader does for HLS segments (encrypt(chunk, byte_offset)). The
# resulting file is range-addressable, so platformcode.local_stream_server can
# serve arbitrary byte ranges and decrypt them by absolute offset at playback.
#
# Supports HTTP Range resume via a sidecar .dlmeta and cooperative cancellation.
# Self-contained / Kodi-independent (stdlib urllib only).
# ------------------------------------------------------------

from __future__ import division

import os
import ssl
import json

try:
    import urllib.request as _urlreq
    import urllib.error as _urlerr
except ImportError:  # py2
    import urllib2 as _urlreq
    _urlerr = _urlreq

try:
    _NOVERIFY_CTX = ssl._create_unverified_context()
except Exception:
    _NOVERIFY_CTX = None


class DownloadCancelled(Exception):
    """Raised cooperatively when the cancel event is set."""


def _open(url, headers, rng_from=0, timeout=30):
    req = _urlreq.Request(url)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if rng_from:
        req.add_header('Range', 'bytes=%d-' % rng_from)
    kw = {'timeout': timeout}
    if _NOVERIFY_CTX is not None:
        kw['context'] = _NOVERIFY_CTX
    return _urlreq.urlopen(req, **kw)


def download_file(url, headers, out_path, progress_cb=None, cancel_evt=None,
                  encrypt=None, timeout=30, chunk=1 << 20, http_get=None):
    """Stream *url* to *out_path*, encrypting on write. Returns bytes written.

    encrypt(data, byte_offset) -> bytes  (offset-keyed soft-DRM cipher; identity
    if None). progress_cb(done, total, nbytes) is called ~1x/s by the caller's
    throttling. Raises DownloadCancelled if cancel_evt is set.
    """
    meta_path = out_path + '.dlmeta'

    # ── Resume? ──
    resume = 0
    if os.path.exists(out_path) and os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, 'r'))
            if meta.get('url') == url:
                resume = int(os.path.getsize(out_path))
                # never trust a written count past the actual file size
                resume = min(resume, int(meta.get('written', resume)))
        except Exception:
            resume = 0

    try:
        resp = _open(url, headers, rng_from=resume, timeout=timeout)
    except _urlerr.HTTPError as e:
        if resume and getattr(e, 'code', None) in (416, 200):
            resume = 0
            resp = _open(url, headers, rng_from=0, timeout=timeout)
        else:
            raise

    status = getattr(resp, 'status', None) or resp.getcode()
    # If we asked for a range but got a full 200, the server ignores Range →
    # restart from byte 0 (truncate) to avoid a corrupt file.
    if resume and status == 200:
        resume = 0

    try:
        clen = int(resp.headers.get('Content-Length') or 0)
    except Exception:
        clen = 0
    total = (resume + clen) if clen else 0

    mode = 'ab' if resume else 'wb'
    offset = resume
    first = (resume == 0)
    with open(out_path, mode) as f:
        while True:
            if cancel_evt is not None and cancel_evt.is_set():
                raise DownloadCancelled()
            data = resp.read(chunk)
            if not data:
                break
            if first:
                first = False
                # Safety: if a "progressive" URL actually returns an HLS playlist
                # (mis-classification), do NOT save the text as a video file.
                if data[:7] == b'#EXTM3U':
                    raise ValueError('expected a media file but got an HLS playlist')
            if encrypt is not None:
                data = encrypt(data, offset)
            f.write(data)
            offset += len(data)
            try:
                json.dump({'url': url, 'written': offset}, open(meta_path, 'w'))
            except Exception:
                pass
            if progress_cb:
                try:
                    progress_cb(offset, total or offset, offset)
                except Exception:
                    pass

    try:
        os.remove(meta_path)
    except Exception:
        pass
    return offset
