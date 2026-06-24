# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# local_stream_server — on-the-fly decryption proxy for offline playback
#
# Encrypted downloads are never written to disk in the clear. To play one we
# start a tiny loopback HTTP server (127.0.0.1) that decrypts the requested
# byte range on the fly and streams it to Kodi. HTTP Range is supported so
# seeking/scrubbing works without decrypting the whole file.
#
# Playback URL:  http://127.0.0.1:<port>/<download_id>
# The handler resolves <download_id> -> (file_path, protection_mode) via a
# lookup function (defaults to downloads_db), builds the device-bound cipher
# and decrypts with cipher.process(ciphertext, absolute_offset).
#
# Files saved with protection 'none' play directly from disk and do not need
# this server.
# ------------------------------------------------------------

from __future__ import division

import os
import threading

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # very old py3 / py2 — addon requires py3 so this is rare
    from BaseHTTPServer import BaseHTTPRequestHandler
    try:
        from socketserver import ThreadingMixIn
    except ImportError:
        from SocketServer import ThreadingMixIn
    from BaseHTTPServer import HTTPServer

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

from core import download_crypto

try:
    from platformcode import logger
except Exception:  # standalone/testing
    class logger(object):
        @staticmethod
        def error(m):
            print('[ERROR] %s' % m)

        @staticmethod
        def info(m):
            print('[INFO] %s' % m)


_CHUNK = 256 * 1024            # streaming/decrypt window
_CONTENT_TYPE = 'video/mp2t'   # concatenated MPEG-TS


def _default_lookup(download_id):
    """Resolve a download id to a serving descriptor via downloads_db:
      {'bundle':bool, 'protection':str, 'file_path':str, 'dir':str}
    A bundle is a per-download directory of separate tracks + local HLS
    playlists; a non-bundle is a single concatenated .ts file."""
    try:
        from platformcode import downloads_db
        entry = downloads_db.get(download_id)
        if not entry:
            return None
        prot = entry.get('protection', 'none')
        if entry.get('bundle') and entry.get('bundle_dir'):
            return {'bundle': True, 'protection': prot,
                    'dir': entry['bundle_dir'], 'file_path': ''}
        return {'bundle': False, 'protection': prot,
                'file_path': entry.get('file_path'), 'dir': ''}
    except Exception as exc:
        logger.error('[LocalServer] lookup failed: %s' % str(exc))
        return None


_MIME = {'.m3u8': 'application/vnd.apple.mpegurl', '.vtt': 'text/vtt'}
_MIME_VIDEO = {'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mkv': 'video/x-matroska',
               '.webm': 'video/webm', '.avi': 'video/x-msvideo', '.ts': 'video/mp2t'}


def _bundle_track_file(bundle_dir, resource):
    """Map a track resource name to its encrypted file in the bundle dir:
    'v' -> video.ts, 'a<n>' -> audio.<n>.ts. Returns abs path or None."""
    if resource == 'v':
        return os.path.join(bundle_dir, 'video.ts')
    if resource.startswith('a') and resource[1:].isdigit():
        return os.path.join(bundle_dir, 'audio.%s.ts' % resource[1:])
    return None


def _parse_range(header, size):
    """Parse a 'bytes=start-end' header. Returns (start, end_inclusive) clamped
    to the file size, or None for an unsatisfiable/absent range."""
    if not header or not header.startswith('bytes='):
        return None
    spec = header[len('bytes='):].split(',')[0].strip()
    try:
        if spec.startswith('-'):
            # suffix length
            n = int(spec[1:])
            if n <= 0:
                return None
            start = max(0, size - n)
            return start, size - 1
        parts = spec.split('-')
        start = int(parts[0])
        end = int(parts[1]) if len(parts) > 1 and parts[1] else size - 1
        if start >= size:
            return None
        return start, min(end, size - 1)
    except Exception:
        return None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass  # silence default stderr logging

    def _route(self):
        """Split the path into (descriptor, resource). For a bundle the URL is
        /<id>/<resource> (master.m3u8, v.m3u8, v, a0, s0.vtt, ...); for a single
        file it is just /<id>. Returns (info, resource) or (None, '')."""
        raw = self.path.split('?', 1)[0].lstrip('/')
        try:
            from urllib.parse import unquote
        except Exception:
            unquote = lambda x: x
        parts = raw.split('/', 1)
        did = unquote(parts[0])
        resource = unquote(parts[1]) if len(parts) > 1 else ''
        info = self.server.lookup(did)
        if not info:
            self.send_error(404)
            return None, ''
        return info, resource

    def _send_headers(self, size, rng, content_type):
        if rng:
            start, end = rng
            length = end - start + 1
            self.send_response(206)
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
        else:
            start, length = 0, size
            self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(length))
        self.end_headers()
        return start, length

    # -- resolve the request to a concrete (path, decrypt?, content_type) --
    def _target(self, info, resource):
        if info['bundle']:
            bdir = info['dir']
            if resource in ('', 'master.m3u8'):
                return os.path.join(bdir, 'master.m3u8'), False, _MIME['.m3u8']
            ext = os.path.splitext(resource)[1]
            if ext in _MIME:               # a playlist or a .vtt subtitle (plaintext)
                return os.path.join(bdir, resource), False, _MIME[ext]
            tf = _bundle_track_file(bdir, resource)   # 'v' / 'a<n>' -> decrypt
            if tf:
                return tf, True, _CONTENT_TYPE
            return None, False, ''
        fp = info['file_path']
        ctype = _MIME_VIDEO.get(os.path.splitext(fp)[1].lower(), _CONTENT_TYPE)
        return fp, True, ctype

    def do_HEAD(self):
        info, resource = self._route()
        if not info:
            return
        path, decrypt, ctype = self._target(info, resource)
        if not path or not os.path.exists(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        rng = _parse_range(self.headers.get('Range'), size) if decrypt else None
        self._send_headers(size, rng, ctype)

    def do_GET(self):
        info, resource = self._route()
        if not info:
            return
        path, decrypt, ctype = self._target(info, resource)
        if not path or not os.path.exists(path):
            self.send_error(404)
            return

        # Plaintext small assets (playlists, subtitles) — serve whole, no decrypt.
        if not decrypt:
            data = open(path, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionError):
                pass
            return

        # Encrypted media track — decrypt the requested byte range on the fly.
        mode = info['protection']
        size = os.path.getsize(path)
        rng = _parse_range(self.headers.get('Range'), size)
        start, length = self._send_headers(size, rng, ctype)
        cipher = download_crypto.get_cipher(mode)
        remaining = length
        offset = start
        _logged = False
        try:
            with open(path, 'rb') as f:
                f.seek(start)
                while remaining > 0:
                    chunk = f.read(min(_CHUNK, remaining))
                    if not chunk:
                        break
                    out = cipher.process(chunk, offset)
                    if not _logged and offset == 0 and out:
                        _logged = True
                        logger.info('[LocalServer] serve %s mode=%s first4=%s '
                                    'TSsync=%s keyfp=%s' % (
                                        os.path.basename(path), mode,
                                        ' '.join('%02x' % b for b in out[:4]),
                                        out[0] == 0x47,
                                        download_crypto.key_fingerprint()))
                    self.wfile.write(out)
                    offset += len(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionError):
            pass  # client (Kodi) seeked away or stopped — normal
        except Exception as exc:
            logger.error('[LocalServer] stream error: %s' % str(exc))


class LocalStreamServer(object):
    """Singleton loopback decrypt-and-stream server."""

    def __init__(self, lookup=None):
        self._lookup = lookup or _default_lookup
        self._httpd = None
        self._thread = None
        self._port = 0
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._httpd is not None:
                return self._port
            self._httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
            self._httpd.daemon_threads = True
            self._httpd.lookup = self._lookup
            self._port = self._httpd.server_address[1]
            self._thread = threading.Thread(target=self._httpd.serve_forever)
            self._thread.daemon = True
            self._thread.start()
            logger.info('[LocalServer] listening on 127.0.0.1:%d' % self._port)
            return self._port

    def url_for(self, download_id):
        """Return the loopback playback URL for *download_id*, starting the
        server lazily if needed. Bundles play via their local HLS master."""
        port = self.start()
        try:
            from urllib.parse import quote
            did = quote(str(download_id), safe='')
        except Exception:
            did = str(download_id)
        suffix = ''
        try:
            info = self._lookup(download_id)
            if info and info.get('bundle'):
                suffix = '/master.m3u8'
        except Exception:
            pass
        return 'http://127.0.0.1:%d/%s%s' % (port, did, suffix)

    def is_bundle(self, download_id):
        try:
            info = self._lookup(download_id)
            return bool(info and info.get('bundle'))
        except Exception:
            return False

    def stop(self):
        with self._lock:
            if self._httpd is not None:
                try:
                    self._httpd.shutdown()
                    self._httpd.server_close()
                except Exception:
                    pass
                self._httpd = None
                self._port = 0


_server = None
_server_lock = threading.Lock()


def get_server(lookup=None):
    """Return the process-wide LocalStreamServer singleton."""
    global _server
    with _server_lock:
        if _server is None:
            _server = LocalStreamServer(lookup=lookup)
        return _server


def url_for(download_id):
    return get_server().url_for(download_id)


def is_bundle(download_id):
    return get_server().is_bundle(download_id)
