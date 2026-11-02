"""Name-only CW sync protocol shared verbatim by Kodi and Android.

No network in playback/save callbacks. A durable, coalescing outbox keeps the
original event time through outages. Import is a separate adapter transaction.
"""
import hashlib
import html
import ipaddress
import json
import os
import re
import threading
import time
import unicodedata
import uuid
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SERVICE_URL = 'https://prippistream-profiles.prippistream-profiles.workers.dev'
_LOCK = threading.RLock()
_SYNC_LOCK = threading.Lock()
_ID = re.compile(r'^(movie|series):[a-z0-9:_-]{1,180}$')
_FIELDS = {'title', 'fulltitle', 'channel', 'action', 'contentType', 'contentTitle',
           'contentSerieName', 'show', 'contentSeason', 'contentEpisodeNumber', 'season',
           'episode', 'url', 'thumbnail', 'fanart', 'id', 'slug', 'contentId', 'series_id',
           'episode_id', 'video_id', 'program_id', 'season_id', '_search_type', '_search_channel',
           '_disp_season', '_disp_episode', '_app_series_tmdb_id', '_profile_id',
           '_app_offline_completed', '_cw_show_url', '_sc_id', '_sc_type', '_sc_episode_id',
           'tmdb_id', 'series_tmdb_id', 'tvshow_tmdb_id', 'tmdb_tv_id'}
_INFO = {'tmdb_id', 'mediatype', 'title', 'tvshowtitle', 'showtitle', 'season', 'episode',
         'year', 'plot', 'rating', 'genre', 'runtime', 'premiered'}


def name(value):
    value = ' '.join(unicodedata.normalize('NFKC', str(value or '')).strip().lower().split())
    if not 2 <= len(value) <= 40 or not all(c.isalnum() or c in ' ._-' for c in value):
        raise ValueError('Usa un nome profilo da 2 a 40 caratteri, con lettere o numeri')
    return value


def directory(profile):
    from platformcode import config
    return os.path.join(config.get_data_path(), 'cw_profiles', hashlib.sha256(name(profile).encode()).hexdigest())


def _text(value):
    return html.unescape(re.sub(r'\[/?(?:B|I|COLOR[^\]]*)\]', '', str(value or ''), flags=re.I)).strip()


def _url(value):
    value = str(value or '').split('|', 1)[0]
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return ''
        host = parsed.hostname.lower()
        if host in ('localhost',) or host.endswith('.local'):
            return ''
        try:
            if not ipaddress.ip_address(host).is_global:
                return ''
        except ValueError:
            pass
        if re.search(r'\.(m3u8|mpd|mp4|mkv|ts)$', parsed.path, re.I):
            return ''
        query = [(k, v) for k, v in parse_qsl(parsed.query) if not re.search(
            r'token|signature|cookie|password|auth|license|expires|secret|^key$', k, re.I)]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ''))[:2000]
    except ValueError:
        return ''


def clean_item(raw, parent=False):
    raw = raw if isinstance(raw, dict) else {}
    result = {}
    for key in _FIELDS:
        value = raw.get(key)
        if value is None or isinstance(value, (dict, list)):
            continue
        if key in ('url', 'thumbnail', 'fanart', '_cw_show_url'):
            value = _url(value)
        elif isinstance(value, str):
            value = _text(value)[:2000]
        result[key] = value
    info = raw.get('infoLabels') or {}
    result['infoLabels'] = {k: (_text(v)[:2000] if isinstance(v, str) else v)
                            for k, v in info.items() if k in _INFO and isinstance(v, (str, int, float, bool))}
    channel = str(result.get('channel') or '')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,60}', channel) or channel in {
            'setting', 'settings', 'profiles', 'downloads', 'channelselector', 'videolibrary', 'favorites'}:
        raise ValueError('Provider non valido nel profilo')
    if result.get('action') not in {'play', 'findvideos', 'episodios', 'epmenu', 'epMenu', 'seasons', 'get_seasons', 'check'}:
        result['action'] = 'findvideos'
    if not parent and isinstance(raw.get('_app_series_parent'), dict):
        parent_item = dict(raw['_app_series_parent'])
        parent_item.setdefault('channel', channel)
        result['_app_series_parent'] = clean_item(parent_item, parent=True)
    return result


def identity(item):
    if _ID.fullmatch(str(item.get('_profile_id') or '')):
        return item['_profile_id']
    info = item.get('infoLabels') or {}
    series = (info.get('mediatype') or item.get('contentType')) in ('episode', 'tvshow', 'season', 'serie') or bool(
        info.get('episode') or item.get('contentEpisodeNumber') or item.get('episode'))
    kind = 'series' if series else 'movie'
    parent = item.get('_app_series_parent') or {}
    parent_info = parent.get('infoLabels') or {}
    tmdb = ((parent_info.get('tmdb_id') or parent.get('tmdb_id') or item.get('_app_series_tmdb_id') or
             item.get('series_tmdb_id') or item.get('tvshow_tmdb_id') or item.get('tmdb_tv_id')) if series else '') or info.get('tmdb_id') or item.get('tmdb_id')
    if str(tmdb or '').isdigit() and int(tmdb) > 0:
        return '%s:tmdb:%s' % (kind, int(tmdb))
    title = ((info.get('tvshowtitle') or info.get('showtitle') or item.get('contentSerieName') or
              parent.get('fulltitle') or parent.get('title') or item.get('show')) if series else '') or item.get('fulltitle') or item.get('title') or info.get('title')
    if not title:
        raise ValueError('Contenuto senza identità')
    title = unicodedata.normalize('NFKD', _text(title)).lower()
    title = ''.join(c for c in title if c.isalnum())
    year = str((parent_info.get('year') if series else info.get('year')) or '')
    return kind + ':title:' + hashlib.sha256((title + '|' + year).encode()).hexdigest()


def pack(entry):
    raw = entry.get('item') or {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    if raw.get('_app_live') or raw.get('is_live_channel'):
        return None
    item = clean_item(raw)
    key = identity(item)
    item['_profile_id'] = key
    value = {'item': item, 'position_ms': max(0, int(entry.get('position_ms') or 0)),
             'duration_ms': max(0, int(entry.get('duration_ms') or 0))}
    return dict(id=key, value=value, deleted=bool(entry.get('deleted')),
                modified_at=int(entry.get('updated_at') or 0))


def _path(profile):
    return os.path.join(directory(profile), 'sync.json')


def _load(profile):
    path = _path(profile)
    if not os.path.isfile(path):
        return {'pending': {}, 'seen': {}, 'joined': False, 'offset': 0, 'records': []}
    with open(path, encoding='utf-8') as stream:
        state = json.load(stream)
    if not isinstance(state.get('pending'), dict) or not isinstance(state.get('seen'), dict):
        raise ValueError('Cache profilo non leggibile: nessun dato sovrascritto')
    return state


def _save(profile, state):
    path = _path(profile)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pending = path + '.tmp'
    with open(pending, 'w', encoding='utf-8') as stream:
        json.dump(state, stream, ensure_ascii=False)
    os.replace(pending, path)


def _fingerprint(record):
    if record.get('deleted'):
        return 'deleted'
    value = record.get('value') or {}
    item = value.get('item') or {}
    info = item.get('infoLabels') or {}
    # URL/domain/artwork repair alone is not a new viewing event.
    return json.dumps([record.get('deleted'), value.get('position_ms'), value.get('duration_ms'),
                       info.get('season') or item.get('contentSeason') or item.get('season'),
                       info.get('episode') or item.get('contentEpisodeNumber') or item.get('episode'),
                       item.get('_app_offline_completed', False)])


def _stage(state, entries):
    newest = {}
    for entry in entries:
        record = pack(entry)
        if record and (record['id'] not in newest or record['modified_at'] >= newest[record['id']]['modified_at']):
            newest[record['id']] = record
    for key, record in newest.items():
        fingerprint = _fingerprint(record)
        seen = state['seen'].get(key)
        stamp = record['modified_at'] + int(state.get('offset', 0))
        if seen and seen['fingerprint'] == fingerprint and seen['stamp'] == stamp:
            continue
        state['seen'][key] = {'fingerprint': fingerprint, 'stamp': stamp}
        record.update(modified_at=stamp, op_id=str(uuid.uuid4()))
        if record['deleted']:
            record['value'] = None
        state['pending'][key] = record


def _merge_seed(state, entries, remote):
    """One-time device linking: union titles and prefer the furthest episode.

    Afterwards ordinary viewing is last-event-wins, allowing rewind/rewatch.
    Old device histories cannot resurrect a newer explicit cloud removal.
    """
    current = {record['id']: record for record in remote['records']}
    merged = []
    for entry in entries or []:
        local = pack(entry)
        if local is None:
            continue
        previous = current.get(local['id'])
        if previous is None:
            merged.append(entry)
            continue
        stamp = local['modified_at'] + int(state.get('offset', 0))
        if previous['deleted']:
            if stamp > previous['modified_at']:
                merged.append(entry)
            continue
        def progress(record):
            value = record.get('value') or {}
            item = value.get('item') or {}
            info = item.get('infoLabels') or {}
            number = lambda v: int(v or 0) if str(v or 0).isdigit() else 0
            return (number(info.get('season') or item.get('contentSeason') or item.get('season')),
                    number(info.get('episode') or item.get('contentEpisodeNumber') or item.get('episode')),
                    int(value.get('position_ms') or 0))
        if progress(local) > progress(previous):
            # Linking is an explicit merge event. Its chosen result must survive
            # even when the furthest local episode was watched on an older date.
            merged.append(dict(entry, updated_at=int(time.time() * 1000)))
    _stage(state, merged)


def _request(profile, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(SERVICE_URL + '/v1/profiles/' + quote(name(profile), safe=''), data=data,
                      headers={'Content-Type': 'application/json', 'User-Agent': 'PrippiStream-profile/1'})
    try:
        with urlopen(request, timeout=6) as response:
            result = json.loads(response.read(2 * 1024 * 1024))
    except HTTPError as exc:
        if exc.code == 409:
            raise ValueError('Nome già utilizzato: scegline uno diverso oppure accedi al profilo esistente') from None
        raise
    if result.get('schema') != 1 or not isinstance(result.get('records'), list):
        raise ValueError('Risposta profilo non valida')
    return result


def _output(profile, state):
    offset = int(state.get('offset', 0))
    entries = []
    for record in state.get('records') or []:
        if not record.get('deleted'):
            value = record['value']
            entries.append(dict(item=clean_item(value['item']), position_ms=value['position_ms'], duration_ms=value['duration_ms'],
                                updated_at=record['modified_at'] - offset))
    return {'profile': name(profile), 'entries': entries, 'complete': not state['pending'],
            'pending': len(state['pending']), 'status': 'Sincronizzato', 'revision': state.get('revision', 0)}


def exchange(profile, entries, connect=False, seed=None, mode='auto'):
    profile = name(profile)
    if mode not in ('auto', 'create', 'join'):
        raise ValueError('Operazione profilo non valida')
    if not _SYNC_LOCK.acquire(False):
        return {'profile': profile, 'complete': False, 'status': 'Sincronizzazione in corso', 'entries': []}
    try:
        with _LOCK:
            state = _load(profile)
            if state['joined']:
                _stage(state, entries)
                _save(profile, state)  # durable BEFORE doing any network work
        start = int(time.time() * 1000)
        remote = _request(profile)
        if connect and mode == 'join' and not remote['exists']:
            raise ValueError('Profilo non trovato: controlla il nome oppure scegli Crea un profilo')
        created = False
        if connect and mode == 'create':
            if remote['exists']:
                raise ValueError('Nome già utilizzato: scegline uno diverso oppure accedi al profilo esistente')
            # Atomic reservation prevents two people creating the same name.
            remote = _request(profile, {'schema': 1, 'create': True, 'require_new': True, 'operations': []})
            created = True
        offset = int(remote['server_time']) - (start + int(time.time() * 1000)) // 2
        with _LOCK:
            state = _load(profile)
            if not state['joined']:
                if not connect:
                    raise ValueError('Collega prima il profilo')
                state['offset'] = offset
                if created or not remote['exists']:
                    _stage(state, seed if seed is not None else entries)
                state['joined'] = True
            # Keep the offset used by already queued events stable through retry.
            state['offset'] = state.get('offset', offset)
            if connect and mode == 'join':
                _merge_seed(state, seed if seed is not None else entries, remote)
            _save(profile, state)
        for _ in range(100):
            with _LOCK:
                state = _load(profile)
                batch = list(state['pending'].values())[:10]
            if not remote['exists'] or batch:
                remote = _request(profile, {'schema': 1, 'create': bool(connect), 'operations': batch})
            with _LOCK:
                state = _load(profile)
                sent = {op['op_id'] for op in batch}
                state['pending'] = {k: op for k, op in state['pending'].items() if op['op_id'] not in sent}
                state['records'] = remote['records']
                state['revision'] = remote['revision']
                for record in remote['records']:
                    if record['id'] not in state['pending']:
                        state['seen'][record['id']] = {'stamp': record['modified_at'], 'fingerprint': _fingerprint(record)}
                _save(profile, state)
                if not state['pending']:
                    return _output(profile, state)
        return _output(profile, state)
    finally:
        _SYNC_LOCK.release()
