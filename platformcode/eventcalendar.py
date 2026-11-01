# -*- coding: utf-8 -*-
"""Dated calendar metadata, lazy source discovery and conservative fixture merge."""
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode
from urllib.request import Request, urlopen
from platformcode import config, eventpresentation as art
from platformcode import eventtime

CATALOGUE = 'https://test34344.herokuapp.com/filter.php?numTest=A1A170&writeKodi=1&mode=11'
_LOCK = threading.Lock()
_LAST_ATTEMPT = 0
_SOURCE_LOCK = threading.RLock()
_SOURCE_CACHE = {}
_SOURCE_RESULTS = {}
_SOURCE_TTL = 120
_MONTHS = {'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4, 'maggio': 5,
           'giugno': 6, 'luglio': 7, 'agosto': 8, 'settembre': 9, 'ottobre': 10,
           'novembre': 11, 'dicembre': 12}


def _get(url, timeout=10):
    with urlopen(Request(url, headers={'User-Agent': 'PrippiStream-calendar/1.0'}), timeout=timeout) as response:
        return json.loads(response.read(6 * 1024 * 1024).decode('utf-8-sig'))


def _path():
    return os.path.join(config.get_data_path(), 'football_calendar.json')


def cached():
    try:
        with open(_path(), encoding='utf-8') as stream:
            return [eventtime.normalize_calendar(event) for event in json.load(stream).get('events') or []]
    except Exception:
        return []


def parse(doc, now=None):
    now = now or eventtime.now_rome()
    result, seen = [], set()
    for group in doc.get('channels') or []:
        match = re.search(r'(\d{1,2})\s+(' + '|'.join(_MONTHS) + ')', group.get('name', ''), re.I)
        if not match:
            continue
        month, day = _MONTHS[match[2].lower()], int(match[1])
        try:
            date = min((datetime(now.year + d, month, day) for d in (-1, 0, 1)),
                       key=lambda value: abs((value - now).total_seconds()))
        except ValueError:
            continue
        for item in group.get('items') or []:
            title = re.sub(r'\[/?(?:COLOR[^\]]*|B|I)\]', '', item.get('title', ''), flags=re.I).strip()
            event = re.match(r'^(\d{1,2}:\d{2})\s+(.+?)\s*\[([^\]]+)\]\s*$', title)
            if not event:
                continue
            clock, teams, league = event.groups()
            route = item.get('externallink') or ''
            if not route.startswith('https://'):
                continue
            identity = (date.strftime('%d/%m/%Y'), clock, art.canonical(teams), art.canonical(league))
            if identity in seen:
                continue
            seen.add(identity)
            result.append(dict(date=identity[0], time=clock, teams=teams.strip(), league=league.strip(),
                               fulltitle='%s %s %s (%s)' % (date.strftime('%d/%m'), clock, teams, league),
                               calendar_url=route, sources=[], calendar_only=True))
    return [eventtime.normalize_calendar(event) for event in result]


def refresh():
    global _LAST_ATTEMPT
    with _LOCK:
        if time.time() - _LAST_ATTEMPT < 1800:
            return cached()
        _LAST_ATTEMPT = time.time()
        try:
            events = parse(_get(CATALOGUE))
            if events:
                path = _path()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + '.tmp', 'w', encoding='utf-8') as stream:
                    json.dump({'ts': time.time(), 'events': events}, stream, ensure_ascii=False)
                os.replace(path + '.tmp', path)
                return events
        except Exception:
            pass
        return cached()


def merge(events, calendar=None, home=True, now=None):
    """Match only unambiguous same teams/competition/time; otherwise keep apart."""
    now = now or eventtime.now_rome()
    calendar = cached() if calendar is None else calendar
    result = [dict(value) for value in calendar]
    for value in events or []:
        matches = [e for e in result if art.canonical(e.get('teams')) == art.canonical(value.get('teams'))
                   and art.competition_key(e.get('league')) == art.competition_key(value.get('league'))
                   and value.get('time') in (e.get('time'), e.get('source_time'))
                   and (not value.get('date') or e['date'].startswith(value['date']))]
        if len(matches) == 1:
            matches[0]['sources'] = value.get('sources') or []
            matches[0]['calendar_only'] = False
        elif value.get('sources'):
            result.append(dict(value))
    result = art.prepare(result, now=now)
    if home:
        today = now.date()
        # An undated source entry is not proof the match is today. It can
        # contribute playback sources through an unambiguous calendar match,
        # but must never be published on its own in the daily row.
        result = [e for e in result if not e['_start'].startswith('9999') and
                  datetime.fromisoformat(e['_start']).date() == today]
    return result


def source_state(route):
    """Known candidate availability, not a promise that a stream is playable."""
    with _SOURCE_LOCK:
        value = _SOURCE_CACHE.get(route)
        if not value or time.time() - value['ts'] >= _SOURCE_TTL:
            return None
        return bool(value['sources'])


def report_source_result(route, success):
    """Remember an actual resolution/playback failure instead of trusting a label."""
    if not route:
        return
    with _SOURCE_LOCK:
        if len(_SOURCE_RESULTS) >= 256:
            oldest = min(_SOURCE_RESULTS, key=lambda key: _SOURCE_RESULTS[key]['ts'])
            _SOURCE_RESULTS.pop(oldest, None)
        _SOURCE_RESULTS[route] = {'ts': time.time(), 'success': success}


def verified_state(route):
    """Fresh verification only. Published candidates never imply availability."""
    with _SOURCE_LOCK:
        value = _SOURCE_RESULTS.get(route)
        if not value or time.time() - value['ts'] >= _SOURCE_TTL:
            return None
        if value.get('checking'):
            return 'checking'
        if value['success'] is True:
            return 'available'
        if value['success'] is False:
            return 'unavailable'
        return 'unknown'


def begin_source_check(route):
    with _SOURCE_LOCK:
        if verified_state(route) is not None:
            return None
        token = object()
        report_source_result(route, None)
        _SOURCE_RESULTS[route].update(checking=True, token=token)
        return token


def finish_source_check(route, token, success, cancelled=False):
    with _SOURCE_LOCK:
        # A concurrent successful real playback wins over an older probe.
        value = _SOURCE_RESULTS.get(route)
        if not value or value.get('token') is not token:
            return
        if cancelled:
            _SOURCE_RESULTS.pop(route, None)
        else:
            report_source_result(route, success)


def source_failed(route):
    return verified_state(route) == 'unavailable'


def verify_event(event, active=lambda: True):
    """Shared startup/focus probe, with the same single-flight and playback guard."""
    route = event.get('calendar_url') or ''
    if not route or not active():
        return None
    token = begin_source_check(route)
    if token is None:
        return verified_state(route)
    try:
        candidates = list(event.get('sources') or [])
        try:
            extra = sources(route, timeout=3)
            known = {source.get('url') for source in candidates}
            candidates.extend(source for source in extra if source.get('url') not in known)
        except Exception:
            if not candidates:
                raise
        from platformcode import eventavailability, eventresolver
        def resolve(source, budget):
            path = (resolve_embed(source, timeout=3) if source.get('calendar_embed')
                    else source['url'])
            return eventresolver.resolve(path, source.get('headers') or {}, budget=budget,
                                         active=active, request_timeout=3) if path else []
        result = eventavailability.check(candidates, resolve, active=active)
        finish_source_check(route, token, result, cancelled=not active())
    except Exception:
        finish_source_check(route, token, None, cancelled=not active())
    return verified_state(route)


def precheck_serie_a(events, active=lambda: True, on_result=lambda event, state: None):
    """Today's Italian Serie A only; never scan the monthly playback catalogue."""
    for event in merge(events):
        if not active():
            break
        if art.competition_key(event.get('league')) != ('Italia', 'seriea'):
            continue
        if not event.get('calendar_url'):
            continue
        state = verify_event(event, active=active)
        if active():
            on_result(event, state)


def sources(route, force=False, timeout=10):
    """Resolve only the selected fixture's catalogue. Never probe all 500 pages."""
    if not route:
        return []
    with _SOURCE_LOCK:
        cached_value = _SOURCE_CACHE.get(route)
        if not force and cached_value and time.time() - cached_value['ts'] < _SOURCE_TTL:
            return [dict(value, headers=dict(value.get('headers') or {})) for value in cached_value['sources']]
    doc = _get(route, timeout=timeout)
    result = []
    for entry in doc.get('items') or []:
        resolver = entry.get('myresolve') or ''
        direct = entry.get('link') or ''
        if resolver.startswith('lvtv@@'):
            value = resolver.split('@@', 1)[1]
            params = parse_qs(urlsplit(value).query)
            special_embed = False
            # The published webplayer route may lack a hostname. Convert its
            # supported provider descriptor to the real embed, not to a fake URL.
            if params.get('t', [''])[0] == 'alieztv':
                code = params.get('c', [''])[0]
                if code.isdigit():
                    value = 'https://emb.apl620.online/player/live.php?' + urlencode({'id': code, 'w': 700, 'h': 480})
                    special_embed = True
                else:
                    continue
            elif urlsplit(value).hostname in ('webplayer.php', 'webplayer2.php'):
                # The upstream catalogue sometimes loses the host and produces
                # https://webplayer.php?... . Its published flag artwork carries
                # the actual provider CDN origin. Recover ONLY that known origin,
                # never invent a server or hard-code today's numbered domain.
                origin = urlsplit(entry.get('thumbnail') or '')
                descriptor = urlsplit(value)
                if (origin.scheme != 'https' or not re.fullmatch(
                        r'cdn\.livetv\d+\.(?:me|net|sx)', origin.hostname or '')):
                    continue
                value = urlunsplit(('https', origin.netloc, '/' + descriptor.hostname,
                                    descriptor.query, ''))
            elif not urlsplit(value).hostname:
                continue
            # Ordinary iframe players must reach the native iframe resolver.
            # The alieztv-only pl.init extractor cannot parse these HTML wrappers.
            result.append({'url': value, 'kind': 'web', 'headers': {}, 'calendar_embed': special_embed})
        elif direct.startswith(('http://', 'https://')):
            result.append({'url': direct, 'kind': 'hls' if '.m3u8' in direct else 'web', 'headers': {}})
    with _SOURCE_LOCK:
        # Memory only: no signed media links are persisted to the badge/calendar cache.
        if len(_SOURCE_CACHE) >= 256:
            oldest = min(_SOURCE_CACHE, key=lambda key: _SOURCE_CACHE[key]['ts'])
            _SOURCE_CACHE.pop(oldest, None)
        _SOURCE_CACHE[route] = {'ts': time.time(), 'sources': result}
    return [dict(value, headers=dict(value.get('headers') or {})) for value in result]


def resolve_embed(source, timeout=8):
    """Extract a media target from the supported calendar embed descriptor."""
    import html
    url = source['url']
    if not source.get('calendar_embed'):
        return url
    with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=timeout) as response:
        page = response.read(2 * 1024 * 1024).decode('utf-8', 'replace')
    patterns = (r"pl\.init\(['\"]([^'\"]+)",
                r"(?:source|file)\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)")
    for pattern in patterns:
        found = re.search(pattern, page)
        if found:
            value = html.unescape(found[1]).replace('\\/', '/')
            if value.startswith('//'):
                value = 'https:' + value
            if value.startswith(('http://', 'https://')):
                return value
    return ''


def status_key(item):
    raw = item.__dict__
    return hashlib.sha256((raw.get('fulltitle', '') + raw.get('event_calendar_url', '')).encode()).hexdigest()
