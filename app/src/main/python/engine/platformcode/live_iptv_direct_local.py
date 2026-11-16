"""Authorized HTTPS slot assignment. Kodi receives media from the provider."""
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


_slot_lock = threading.Lock()
_bad_slots = {}
_unlisted = {}
_device_offline = {}
_next_probe = 0.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def channel_unlisted(channel_id):
    with _slot_lock:
        return _unlisted.get(channel_id, 0) > time.monotonic()


def device_hidden(channel_id):
    with _slot_lock:
        now = time.monotonic()
        return max(_device_offline.get(channel_id, 0), _unlisted.get(channel_id, 0)) > now


def start_row_probe(channel_ids):
    global _next_probe
    targets = list(dict.fromkeys(channel_ids))
    if not targets or not play_token():
        return
    with _slot_lock:
        if _next_probe > time.monotonic():
            return
        _next_probe = time.monotonic() + 300
    from concurrent.futures import ThreadPoolExecutor
    def run():
        deadline = time.monotonic() + 10
        def check(channel):
            result = probe_on_device(channel, lambda: time.monotonic() < deadline)
            if result is False:
                with _slot_lock:
                    _device_offline[channel] = time.monotonic() + 300
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(check, targets))
    threading.Thread(target=run, daemon=True).start()


def _https_grant(key, channel_id, rejected, release, timeout):
    body = json.dumps({'channel': channel_id, 'rejected': rejected, 'release': release}).encode()
    req = Request('https://prippistream-live.prippistream-profiles.workers.dev/v1/play',
                  data=body, headers={'Authorization': 'Bearer ' + key,
                                      'Content-Type': 'application/json',
                                      'User-Agent': 'PrippiStream-Live/1.0'})
    try:
        with build_opener(_NoRedirect()).open(req, timeout=timeout) as response:
            return json.loads(response.read(8193))
    except HTTPError as exc:
        try:
            if exc.code == 409 and json.loads(exc.read(1024)).get('status') == 'not_listed':
                with _slot_lock:
                    _unlisted[channel_id] = time.monotonic() + 30
        except (OSError, ValueError, AttributeError):
            pass
        finally:
            exc.close()
    except (OSError, ValueError):
        pass
    return None


def mark_slot_rejected(slot):
    if slot and re.fullmatch(r'[0-9a-f]{64}', slot):
        with _slot_lock:
            _bad_slots[slot] = time.monotonic() + 120


def _recent_rejections():
    now = time.monotonic()
    with _slot_lock:
        for slot in tuple(_bad_slots):
            if _bad_slots[slot] <= now:
                del _bad_slots[slot]
        return tuple(sorted(_bad_slots, key=_bad_slots.get, reverse=True)[:24])


def assigned_grant(channel_id, rejected=(), release=None, timeout=11):
    if channel_id != '-' and not re.fullmatch(r'[a-z0-9_]{1,128}', channel_id):
        return None
    rejected = [x for x in rejected if re.fullmatch(r'[0-9a-f]{64}', x)][:26]
    release = release if release and re.fullmatch(r'[A-Za-z0-9_-]{32}', release) else None
    key = play_token()
    return _valid_grant(_https_grant(key, channel_id, rejected, release, timeout)) if key else None


def play_token():
    try:
        from platformcode import config
        key = (Path(config.get_data_path()) / 'live-play.token').read_text(encoding='ascii').strip()
    except (ImportError, OSError, UnicodeError):
        return ''
    return key if re.fullmatch(r'[A-Za-z0-9_-]{43}', key) else ''


def _valid_grant(grant):
    try:
        url = grant['url']
        if not isinstance(url, str) or any(c.isspace() or c in '|\\' for c in url):
            return None
        p = urlsplit(url)
        if (p.scheme in ('http', 'https') and p.hostname and not p.username and not p.fragment
                and re.fullmatch(r'[0-9a-f]{64}', grant['slot'])
                and re.fullmatch(r'[A-Za-z0-9_-]{32}', grant['lease'])):
            return grant
    except (ValueError, KeyError, TypeError):
        pass
    return None


def probe_on_device(channel_id, active):
    """Small probe from this PC. No grant or inconclusive response is not an outage."""
    rejected = set()
    lease = None
    try:
        for _ in range(2):
            if not active():
                return None
            grant = assigned_grant(channel_id, rejected, lease, timeout=3)
            if not grant:
                return None
            lease = grant['lease']
            try:
                with urlopen(Request(grant['url'], headers={'User-Agent': 'Kodi/21.3'}),
                             timeout=2) as response:
                    data = response.read(1024)
                    if any(data[i:i+1] == data[i+188:i+189] == data[i+376:i+377] == b'G'
                           for i in range(min(188, len(data) - 376))):
                        return True
                    return None
            except HTTPError as error:
                error.close()
                if error.code not in (401, 403, 404, 410):
                    return None
                rejected.add(grant['slot'])
                mark_slot_rejected(grant['slot'])
            except (OSError, ValueError):
                return None
        return False if len(rejected) == 2 else None
    finally:
        if lease:
            assigned_grant('-', (), lease, timeout=2)


def redirect_url(url):
    path = '/' + secrets.token_urlsafe(24) + '.ts'

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_HEAD(self):
            self.send_response(200 if self.path == path else 404)
            self.send_header('Content-Type', 'video/mp2t')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def do_GET(self):
            if self.path != path:
                self.send_error(404)
                return
            self.send_response(302)
            self.send_header('Location', url)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', '0')
            self.end_headers()

    try:
        http = HTTPServer(('127.0.0.1', 0), Redirect)
    except OSError:
        return None
    http.timeout = 1

    def serve():
        deadline = time.monotonic() + 20
        with http:
            while time.monotonic() < deadline:
                http.handle_request()

    threading.Thread(target=serve, daemon=True).start()
    return 'http://127.0.0.1:%d%s' % (http.server_port, path)


def open_grant(channel_id, rejected=(), release=None):
    grant = assigned_grant(channel_id, dict.fromkeys((*rejected, *_recent_rejections())), release)
    if not grant:
        return None
    url = redirect_url(grant['url'])
    return (url, grant['slot'], grant['lease']) if url else None


def open_url(channel_id):
    rejected = []
    lease = None
    for _ in range(2):
        grant = assigned_grant(channel_id, [*rejected, *_recent_rejections()], lease)
        if not grant:
            return None
        lease = grant['lease']
        try:
            with urlopen(Request(grant['url'], headers={'User-Agent': 'PrippiStream/Android'}),
                         timeout=1.2):
                pass
        except HTTPError as exc:
            exc.close()
            if exc.code in (401, 403, 404, 410):
                rejected.append(grant['slot'])
                mark_slot_rejected(grant['slot'])
                continue
        except (OSError, ValueError):
            pass  # Inconclusive: let Media3 try instead of dropping a good stream.
        return redirect_url(grant['url'])
    if lease:
        assigned_grant('-', release=lease, timeout=2)
    with _slot_lock:
        _device_offline[channel_id] = time.monotonic() + 300
    return None
