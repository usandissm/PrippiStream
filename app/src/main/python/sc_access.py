"""Optional authorized playback service. No account credentials or session cookies."""
import json
import re
import time
import ast
from urllib.parse import urlsplit, parse_qs, parse_qsl, urlencode, urlunsplit
from urllib.request import Request, urlopen

_endpoint = ''
_client_key = ''


def configure(endpoint, client_key):
    global _endpoint, _client_key
    _endpoint, _client_key = endpoint, client_key


def candidate(item, preferences):
    if not _endpoint or not _client_key or not content_ids(item):
        return {}
    result = dict(preferences)
    result.update({'url': 'sc-access://playback', 'bootstrap_url': '',
                   'manifest_type': 'sc_authorized', 'headers': {},
                   'label': 'SC', 'server': 'streamingcommunityws', 'fallback_enabled': True})
    return result


def content_ids(item):
    if item.get('channel') != 'streamingcommunity' or item.get('_app_live') or item.get('_app_event'):
        return None
    url = urlsplit(str(item.get('url') or ''))
    match = re.search(r'/(?:watch|iframe|titles)/([1-9][0-9]{0,8})(?:[-/]|$)', url.path)
    if not match:
        return None
    ids = {'title_id': match.group(1)}
    episode = parse_qs(url.query).get('episode_id', [''])[0]
    if episode:
        if not re.fullmatch(r'[1-9][0-9]{0,9}', episode):
            return None
        ids['episode_id'] = episode
    return ids


def playback(item, endpoint, client_key, preferences, opener=urlopen):
    ids = content_ids(item)
    if not ids or not client_key or not endpoint:
        return {}
    target = urlsplit(endpoint)
    if target.scheme != 'https' or target.hostname != 'prippistream-sc-access.prippistream-profiles.workers.dev' or target.path != '/v1/playback':
        return {}
    try:
        request = Request(endpoint, data=json.dumps(ids).encode('utf-8'), method='POST', headers={
            'Authorization': 'Bearer ' + client_key, 'Content-Type': 'application/json',
            'Accept': 'application/json', 'User-Agent': 'PrippiStream/1.0',
        })
        with opener(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            return {}
        data = json.loads(raw)
        embed = data.get('embed_url', '')
        url = urlsplit(embed)
        query = parse_qs(url.query)
        if (data.get('available') is not True or url.scheme != 'https' or
                not re.fullmatch(r'vixcloud\.[a-z]{2,10}', url.hostname or '') or
                not re.fullmatch(r'/embed/[0-9]+', url.path) or url.username or url.password or
                query.get('canPlayFHD') != ['1'] or not query.get('token') or
                int(query.get('expires', ['0'])[0]) <= time.time()):
            return {}
        result = dict(preferences)
        result.update({
            'url': embed, 'bootstrap_url': embed, 'manifest_type': 'hls',
            'headers': {'Referer': 'https://streamingunity-premium.to/it/iframe/' + ids['title_id'],
                        'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36'},
            'label': 'SC', 'server': 'streamingcommunityws', 'fallback_enabled': True,
        })
        return result
    except Exception:
        # Network errors, expired entitlement or service downtime are normal free fallbacks.
        # Never log signed URLs, authorization headers or upstream response bodies.
        return {}


def playlist_from_embed(embed, html):
    """Read the configuration the authorized player actually returned; never forge grants."""
    match = re.search(r"window\.masterPlaylist\s*=\s*{[^{]+({[^}]+}),\s*url:\s*['\"]([^'\"]+).*?canPlayFHD\s*=\s*(true|false)", html, re.S)
    if not match or match[3] != 'true':
        return ''
    params = ast.literal_eval(match[1])
    streams = re.search(r'window\.streams\s*=\s*(\[[^;]+\])\s*;', html, re.S)
    active = next((entry.get('url') for entry in json.loads(streams[1]) if entry.get('active') and entry.get('url')), '') if streams else ''
    parsed = urlsplit(active or match[2])
    if parsed.scheme != 'https' or not re.fullmatch(r'vixcloud\.[a-z]{2,10}', parsed.hostname or '') or not re.fullmatch(r'/playlist/[0-9]+', parsed.path):
        return ''
    params.update(parse_qsl(parsed.query))
    # Only after an explicit FHD grant, matching the official player.
    params['h'] = 1
    for key in ('b', 'scz'):
        value = parse_qs(urlsplit(embed).query).get(key)
        if value:
            params[key] = value[0]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ''))


def download_media(item, opener=urlopen):
    """Fresh authorization for NEW marked downloads, including queue/resume/token refresh."""
    result = playback(item, _endpoint, _client_key, {}, opener)
    if not result:
        return None
    try:
        headers = result['headers']
        with opener(Request(result['bootstrap_url'], headers=headers), timeout=15) as response:
            body = response.read(2097153)
        if len(body) > 2097152:
            return None
        playlist = playlist_from_embed(result['bootstrap_url'], body.decode('utf-8', 'replace'))
        if not playlist:
            return None
        return playlist, dict(headers, Referer=result['bootstrap_url'])
    except Exception:
        return None


def locked_download_height(item):
    try:
        return max(0, int(getattr(item, '_app_sc_download_height', 0) or 0))
    except (TypeError, ValueError):
        return 0


def validate_download_variant(item, variant):
    required = locked_download_height(item)
    if required and int(variant.get('height') or 0) != required:
        raise RuntimeError('La qualità originale del download non è disponibile. '
                           'Il file parziale è conservato: riprova più tardi.')
