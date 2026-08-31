# -*- coding: utf-8 -*-
"""Smoke test headless dei provider VOD richiesti dall'app.

Non usa API parallele: importa lo stesso ``bridge.py`` e gli stessi canali che
Chaquopy include nell'APK. Il test arriva fino al resolver e stampa soltanto
host/manifest, senza avviare o scaricare il contenuto.
"""
from __future__ import print_function

import os
import json
import re
import sys
import traceback
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


HERE = os.path.dirname(os.path.abspath(__file__))
PYROOT = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
sys.path.insert(0, PYROOT)

import bridge  # noqa: E402


CASES = (
    ('streamingcommunity', 'silo'),
    ('hd4me', 'dune'),
    ('cineblog01', 'dunkirk'),
)
DRILL_ACTIONS = ('episodios', 'seasons', 'get_seasons')


def _title(item):
    return (item.get('fulltitle') or item.get('title') or '').strip()


def _pick(values, actions=()):
    if actions:
        for value in values:
            if value.get('action') in actions:
                return value
    return values[0] if values else None


def _is_media_response(playback):
    """Scarta pagine HTML che un resolver non riuscito lascia come URL."""
    if playback.get('server') == 'streamingcommunityws':
        # Verifica il manifest vero con un token ricavato dall'embed diretto.
        # Un semplice URL non basta: i token generati via proxy danno HTTP 403
        # quando vengono poi usati dal telefono.
        embed = playback.get('bootstrap_url') or ''
        browser_headers = {
            'User-Agent': ('Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/137.0 Mobile Safari/537.36'),
            'Accept': '*/*',
        }
        request = Request(embed, headers=browser_headers)
        with urlopen(request, timeout=15) as response:
            html = response.read().decode('utf-8', 'replace')
        streams_match = re.search(r'window\.streams\s*=\s*(\[[^;]+\])', html, re.S | re.I)
        master_match = re.search(
            r"window\.masterPlaylist\s*=\s*\{.*?params\s*:\s*\{(.*?)\}.*?url\s*:\s*['\"]([^'\"]+)",
            html, re.S | re.I,
        )
        if not master_match:
            return False
        base = master_match.group(2)
        if streams_match:
            streams = json.loads(streams_match.group(1))
            base = next((entry.get('url') for entry in streams
                         if entry.get('active') and entry.get('url')), base)
        params = dict(parse_qsl(urlsplit(base).query, keep_blank_values=True))
        params.update(dict(re.findall(
            r"['\"]?(token|expires|asn)['\"]?\s*:\s*['\"]([^'\"]*)",
            master_match.group(1), re.I,
        )))
        params = {key: value for key, value in params.items() if value}
        if re.search(r'window\.canPlayFHD\s*=\s*true', html, re.I):
            params['h'] = '1'
        embed_query = dict(parse_qsl(urlsplit(embed).query))
        for key in ('b', 'scz'):
            if embed_query.get(key):
                params[key] = embed_query[key]
        parsed = urlsplit(base)
        playlist = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ''))
        headers = dict(browser_headers)
        headers['Referer'] = embed
        with urlopen(Request(playlist, headers=headers), timeout=15) as response:
            return response.read(16).startswith(b'#EXTM3U')
    if playback.get('manifest_type') == 'bootstrap':
        # Challenge browser esplicita: non è un falso URL diretto.
        return bool(playback.get('bootstrap_url'))
    headers = dict(playback.get('headers') or {})
    headers['Range'] = 'bytes=0-4095'
    request = Request(playback.get('url') or '', headers=headers)
    with urlopen(request, timeout=15) as response:
        content_type = (response.headers.get('Content-Type') or '').lower()
        prefix = response.read(4096).lstrip()
    if content_type.startswith(('video/', 'audio/')) or 'mpegurl' in content_type:
        return True
    if 'octet-stream' in content_type:
        return True
    return (prefix.startswith(b'#EXTM3U') or prefix.startswith(b'<MPD') or
            b'ftyp' in prefix[:64])


def resolve_case(channel, query):
    results = bridge.channel_call(channel, 'search', {}, text=query)
    if not results:
        raise RuntimeError('ricerca senza risultati')

    item = _pick(results, DRILL_ACTIONS + ('findvideos', 'play'))
    if item is None:
        raise RuntimeError('nessun risultato navigabile')

    for _ in range(4):
        action = item.get('action') or ''
        if action in DRILL_ACTIONS:
            children = bridge.channel_call(channel, action, item)
            item = _pick(children, ('findvideos', 'play') + DRILL_ACTIONS)
            if item is None:
                raise RuntimeError('%s senza elementi' % action)
            continue
        if action == 'findvideos' or not item.get('server'):
            sources = bridge.channel_call(channel, 'findvideos', item)
            if not sources:
                raise RuntimeError('findvideos senza sorgenti')
            errors = []
            for source in sources:
                try:
                    playback = bridge.resolve(source)
                    if playback.get('url') and _is_media_response(playback):
                        return item, sources, playback
                except Exception as exc:
                    errors.append(str(exc))
            raise RuntimeError('resolver falliti: %s' % '; '.join(errors[:3]))
        playback = bridge.resolve(item)
        if playback.get('url') and _is_media_response(playback):
            return item, [item], playback
        raise RuntimeError('resolver senza risposta multimediale')
    raise RuntimeError('navigazione troppo profonda')


def main():
    bridge.init()
    failed = 0
    for channel, query in CASES:
        print('\n=== %s · %s ===' % (channel, query))
        try:
            item, sources, playback = resolve_case(channel, query)
            parsed = urlsplit(playback.get('url') or '')
            print('OK risultato=%r sorgenti=%d server=%s manifest=%s host=%s' % (
                _title(item), len(sources), playback.get('server') or '',
                playback.get('manifest_type') or '', parsed.netloc or parsed.scheme,
            ))
        except Exception:
            failed += 1
            traceback.print_exc()
    print('\nESITO: %d/%d provider risolti' % (len(CASES) - failed, len(CASES)))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
