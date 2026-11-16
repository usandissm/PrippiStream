"""Optional Live policy from the dashboard, configured per installation."""
import json
import re
import threading
import time
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

URL = 'https://prippistream-live.prippistream-profiles.workers.dev/v1/catalog'
LOCK = threading.Lock()
STATE = {'rules': {}, 'due': 0.0, 'received': 0.0}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def refresh(reserved=False):
    with LOCK:
        current = time.monotonic()
        if not reserved and current < STATE['due']:
            return
        STATE['due'] = current + 15
    try:
        from platformcode import config
        token = (Path(config.get_data_path()) / 'live-catalog.token').read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return
        req = Request(URL, headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'PrippiStream-Live/1.0'})
        with build_opener(NoRedirect()).open(req, timeout=3) as r:
            payload = json.loads(r.read(524289))
        rules = payload['rules']
        channels = payload.get('channels', [])
        if payload['version'] != 1 or not isinstance(rules, dict) or not isinstance(channels, list):
            return
        with LOCK:
            STATE.update(rules=rules, channels=channels, received=time.monotonic(),
                         revision=payload.get('updated'))
    except (OSError, ValueError, KeyError, TypeError):
        pass


def channel_allowed(ch):
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


def revision():
    with LOCK:
        return STATE.get('revision')


def online_rows(group):
    with LOCK:
        if time.monotonic() - STATE['received'] >= 600:
            return []
        rows = list(STATE.get('channels', []))
    result = []
    for row in rows:
        if row.get('group') != group:
            continue
        kind = {'dedi': 'daddy', 'freeshot': 'freeshot', 'mediahosting': 'mediahosting', 'iptv': 'iptv_vm'}.get(row.get('route'))
        if not kind:
            continue
        if kind == 'iptv_vm':
            from platformcode.live_iptv_direct_local import play_token
            if not play_token():
                continue
        item = dict(title=row['title'], par=row['id'], kind=kind,
                    source_code=row['code'], _validated_code=row['code'],
                    _validated_route='iptv' if kind == 'iptv_vm' else kind)
        if not channel_allowed(item):
            continue
        if kind in ('daddy', 'freeshot'):
            item['par'] = row['code']
        item['_catalog_id'] = row['id']
        result.append(item)
    return result


def apply(rows):
    # Do not block home rendering or replace the native Live fallback.
    if time.monotonic() >= STATE['due']:
        with LOCK:
            if time.monotonic() >= STATE['due']:
                STATE['due'] = time.monotonic() + 15
                threading.Thread(target=refresh, args=(True,), daemon=True).start()
    return [ch for ch in rows if channel_allowed(ch)]
