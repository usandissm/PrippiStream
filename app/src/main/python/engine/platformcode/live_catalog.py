"""Optional Live policy from the dashboard, configured per installation."""
import json
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

URL = 'https://prippistream-live.prippistream-profiles.workers.dev/v1/catalog'
LOCK = threading.Lock()
STATE = {'rules': {}, 'due': 0.0, 'received': 0.0, 'loading': False, 'status': None}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def start_refresh(force=False):
    with LOCK:
        if STATE['loading'] or (not force and time.monotonic() < STATE['due']):
            return
        STATE['loading'] = True
    threading.Thread(target=_refresh, daemon=True).start()


def _refresh():
    from platformcode import config, logger
    retry_after = 60
    status = ('not_configured',)
    try:
        token = (Path(config.get_data_path()) / 'live-catalog.token').read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return
        req = Request(URL, headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'PrippiStream-Live/1.0'})
        with build_opener(NoRedirect()).open(req, timeout=3) as r:
            payload = json.loads(r.read(524289))
        rules = payload['rules']
        channels = payload.get('channels', [])
        if payload['version'] != 1 or not isinstance(rules, dict) or not isinstance(channels, list):
            status = ('unexpected_format',)
            return
        status = ('ok', len(channels))
        with LOCK:
            STATE.update(rules=rules, channels=channels, received=time.monotonic())
    except HTTPError as error:
        status = ('http', error.code)
        if error.code not in (401, 403):
            retry_after = 8
        error.close()
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError) as error:
        status = ('error', type(error).__name__)
        retry_after = 8
    finally:
        with LOCK:
            changed = STATE['status'] != status
            STATE.update(loading=False, due=time.monotonic() + retry_after, status=status)
        if changed:
            logger.info('[LiveCatalog] ' + ' '.join(map(str, status)))


def channel_allowed(ch, rules=None):
    if rules is None:
        with LOCK:
            rules = STATE['rules'] if time.monotonic() - STATE['received'] < 86400 else {}
    title = str(ch.get('title') or '')
    for _ in range(6):
        title = re.sub(r'\s*(?:\((?:backup|buffering|fibra(?: top)?|serie [ab]|principale)\)|\[(?:fs|mh|fhd|flh|hd|sd|uhd|4k)\]|\b(?:fhd|flh|hd|sd|uhd|4k|hevc|hdr|backup|buffering|italy|italia)\b)\s*$', '', title, flags=re.I).strip()
    title = re.sub(r'^Sky Sports\b', 'Sky Sport', title, flags=re.I)
    family = re.sub(r'[^a-z0-9]', '', title.lower().replace('+','plus'))
    key = str(ch.get('par') or '').lower()
    route = ch.get('_validated_route') or ch.get('kind')
    route = 'dedi' if route in ('daddy', 'daddycode') else route
    markers = [key + ':channel', family + ':channel', 'family_' + family + ':channel']
    if route in ('dedi', 'freeshot', 'mediahosting', 'iptv'):
        markers.extend((key + ':' + route, family + ':' + route))
    return not any(rules.get(k) is False for k in markers)


def apply(rows):
    with LOCK:
        snapshot = dict(STATE['rules']) if time.monotonic() - STATE['received'] < 86400 else {}
    return [ch for ch in rows if channel_allowed(ch, snapshot)]


def online_rows(group):
    from platformcode.live_iptv_direct_local import device_hidden, play_token
    enabled = bool(play_token())
    with LOCK:
        if not STATE['received'] or time.monotonic() - STATE['received'] >= 600:
            return []
        channels = list(STATE.get('channels', []))
    result = []
    for row in channels:
        if not isinstance(row, dict) or row.get('group') != group:
            continue
        kind = {'iptv': 'iptv_vm', 'mediahosting': 'mediahosting',
                'freeshot': 'freeshot', 'dedi': 'daddy'}.get(row.get('route'))
        key, title, code = (row.get(k) for k in ('id', 'title', 'code'))
        if not kind or not all(isinstance(v, str) for v in (key, title, code)):
            continue
        if kind == 'iptv_vm' and (not enabled or device_hidden(key)):
            continue
        item = dict(title=title, par=key, kind=kind, _catalog_id=key,
                    source_code=code, _validated_code=code,
                    _validated_route=row['route'])
        if channel_allowed(item):
            if kind in ('freeshot', 'daddy'):
                item['par'] = code
            result.append(item)
    return result
