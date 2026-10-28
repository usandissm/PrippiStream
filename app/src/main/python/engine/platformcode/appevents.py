"""Android adapter over the same calendar, artwork and resolvers as Kodi.

No dependency on installed Kodi add-ons, no IPTV accounts and no signed URL
disk cache. Network work never runs in row rendering or Compose focus handlers.
"""
import hashlib
import json
import os
import threading
import time
from urllib.parse import urlencode
from platformcode import (config, eventcalendar, eventpresentation, eventtime,
                          eventavailability, eventresolver, eventquality, tgevents, logger)

_LOCK = threading.Lock()
_ART_LOCK = threading.Lock()
_LAST_REFRESH = 0


def _events():
    return tgevents.load_cached() or []


def _warm_art():
    if not _ART_LOCK.acquire(False):
        return
    def worker():
        try:
            eventpresentation.warm_badges(eventcalendar.cached() + _events())
        except Exception as exc:
            logger.debug('[AppEvents] artwork: %s' % type(exc).__name__)
        finally:
            _ART_LOCK.release()
    threading.Thread(target=worker, daemon=True).start()


def _refresh_sources_if_due():
    # Persist attempts too: reopening the app must not hammer a rate-limited page.
    path = os.path.join(config.get_data_path(), 'app_events_attempt.json')
    try:
        with open(path, encoding='utf-8') as stream:
            last = float(json.load(stream).get('ts', 0))
    except (OSError, ValueError, TypeError):
        last = 0
    age = tgevents.cache_age()
    if time.time() - last < tgevents.FETCH_COOLDOWN_S or (
            age is not None and age < tgevents.FETCH_COOLDOWN_S):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as stream:
        json.dump({'ts': time.time()}, stream)
    os.replace(path + '.tmp', path)
    tgevents.fetch_events()


def start_refresh():
    global _LAST_REFRESH
    if time.time() - _LAST_REFRESH < 60 or not _LOCK.acquire(False):
        return
    _LAST_REFRESH = time.time()
    def worker():
        try:
            eventcalendar.refresh()
            _refresh_sources_if_due()
            # Independent of user focus, same real manifest/segment checks as Kodi.
            eventcalendar.precheck_serie_a(_events())
            _warm_art()
        except Exception as exc:
            logger.debug('[AppEvents] refresh: %s' % type(exc).__name__)
        finally:
            _LOCK.release()
    threading.Thread(target=worker, daemon=True).start()


def build_items():
    items = tgevents.build_row_items(_events())
    for item in items:
        fixture = item.event_fixture
        identity = '|'.join(str(fixture.get(k) or '') for k in ('date', 'time', 'teams', 'league'))
        item.event_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        item._app_event = True
        item._app_live = True
        item.action = 'event_play'
        item.infoLabels['plot'] = item.event_status + '\n' + item.event_league
    return items


def playback_candidates(item):
    """Quality-ordered alternatives, native player retries actual decode failures."""
    route = item.get('event_calendar_url') or ''
    fixture = item.get('event_fixture') or {}
    date = fixture.get('date') or ''
    today = eventtime.now_rome().strftime('%d/%m/%Y')
    if not date or date not in (today, today[:5]):
        return []
    sources = [dict(s, _origin='primary') for s in item.get('_tg_event_sources') or []
               if isinstance(s, dict) and s.get('kind') in ('hls', 'web') and s.get('url')]
    # Prefer refreshed primary metadata to stale URL copies carried by a card.
    for fresh in eventcalendar.merge(_events()):
        if (eventpresentation.canonical(fresh.get('teams')) == eventpresentation.canonical(fixture.get('teams'))
                and eventpresentation.competition_key(fresh.get('league')) ==
                    eventpresentation.competition_key(fixture.get('league'))
                and fresh.get('time') == fixture.get('time')):
            sources = [dict(s, _origin='primary') for s in fresh.get('sources') or []]
            break
    if route:
        try:
            known = {s.get('url') for s in sources}
            sources.extend(dict(s, _origin='calendar') for s in eventcalendar.sources(route, force=True, timeout=4)
                           if s.get('url') not in known)
        except Exception:
            pass
    sources = [s for s in sources if s.get('kind') in ('hls', 'web') and
               str(s.get('url') or '').startswith(('https://', 'http://'))]
    sources.sort(key=lambda s: s.get('kind') != 'hls')
    def resolve(source):
        if source.get('kind') == 'hls':
            values = [source]
        else:
            path = eventcalendar.resolve_embed(source, timeout=3) if source.get('calendar_embed') else source['url']
            values = eventresolver.resolve(path, source.get('headers') or {}, budget=6, request_timeout=3) if path else []
        source['_app_resolved'] = values
        if not values:
            return None
        import xbmcgui
        value = values[0]
        li = xbmcgui.ListItem(path=value['url'])
        headers = urlencode(value.get('headers') or {})
        li.setProperty('inputstream.adaptive.manifest_headers', headers)
        return li
    ranked = eventquality.prepare(sources, resolve, budget=12)
    reachable, uncertain, seen = [], [], set()
    untested = False
    deadline = time.monotonic() + 8
    for source, li, quality in ranked:
        values = source.get('_app_resolved') or ([source] if source.get('kind') == 'hls' else [])
        if li is None and not values:
            # A slow source stays lazy in the shared quality module. Resolve it
            # only within the remaining click budget, not an unbounded second scan.
            if time.monotonic() >= deadline:
                untested = True
                continue
            try:
                resolve(source)
                values = source.get('_app_resolved') or []
            except Exception:
                untested = True
                continue
        for value in values:
            identity = (value.get('url'), tuple(sorted((value.get('headers') or {}).items())))
            if identity in seen:
                continue
            seen.add(identity)
            state = eventavailability.hls_reachable(value, deadline=deadline) if time.monotonic() < deadline else None
            if state is False:
                continue
            request = dict(url=value['url'], bootstrap_url='', manifest_type='hls',
                           headers=value.get('headers') or {}, drm_type='', license_key='', subtitles=[],
                           label=item.get('title') or fixture.get('teams') or 'Evento', server='events')
            (reachable if state is True else uncertain).append(request)
    if route:
        eventcalendar.report_source_result(route, True if reachable else None if uncertain or untested else False)
    return reachable + uncertain
