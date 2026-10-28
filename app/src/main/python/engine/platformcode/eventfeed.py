# -*- coding: utf-8 -*-
"""Configurable, cache-first feed for scheduled live events.

The module intentionally knows nothing about third-party add-ons or private
resolvers.  An owner-controlled HTTPS JSON feed supplies event cards and the
candidate, direct playback URLs.  Cards are cached locally; candidates are
always read again at click time, because live URLs often expire.
"""
from __future__ import absolute_import

import json
import os
import threading
import time
from urllib.request import Request, urlopen

from core.item import Item
from platformcode import config, logger

_LOCK = threading.Lock()
_MEM = {'events': [], 'ts': 0.0, 'url': ''}
_UA = 'PrippiStream/2.0 (+event-feed)'


def _feed_url():
    return str(config.get_setting('event_feed_url', default='') or '').strip()


def enabled():
    return bool(config.get_setting('show_events_row', default=True) and _feed_url())


def _ttl():
    try:
        return max(300, int(config.get_setting('event_feed_refresh_minutes', default=20)) * 60)
    except Exception:
        return 20 * 60


def _cache_path():
    return os.path.join(config.get_data_path(), 'scheduled_events_cache.json')


def _read_disk():
    try:
        with open(_cache_path(), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get('events'), list):
            return data
    except Exception:
        pass
    return {'events': [], 'ts': 0.0, 'url': ''}


def _write_disk(events, source_url):
    try:
        path = _cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'version': 1, 'ts': time.time(), 'url': source_url,
                       'events': events}, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        logger.error('[EventFeed] cache write: %s' % str(exc))


def _normalise(raw):
    values = raw.get('events', raw) if isinstance(raw, dict) else raw
    if not isinstance(values, list):
        raise ValueError('il feed deve contenere una lista "events"')
    events, seen = [], set()
    for pos, value in enumerate(values):
        if not isinstance(value, dict):
            continue
        event_id = str(value.get('id') or value.get('event_id') or pos).strip()
        title = str(value.get('title') or value.get('name') or '').strip()
        if not event_id or not title or event_id in seen:
            continue
        seen.add(event_id)
        sources = value.get('sources') or value.get('links') or []
        if not isinstance(sources, list):
            sources = []
        events.append({
            'id': event_id, 'title': title,
            'subtitle': str(value.get('subtitle') or value.get('time') or '').strip(),
            'starts_at': str(value.get('starts_at') or value.get('start') or '').strip(),
            'thumbnail': str(value.get('thumbnail') or value.get('image') or '').strip(),
            'fanart': str(value.get('fanart') or value.get('thumbnail') or value.get('image') or '').strip(),
            'sources': sources,
        })
    return sorted(events, key=lambda item: (item.get('starts_at') or '9999', item['title'].casefold()))


def refresh(force=False):
    """Return catalogue, using cache unless stale.  Never raises to the UI."""
    source_url = _feed_url()
    if not source_url:
        return []
    now = time.time()
    with _LOCK:
        if not _MEM['events'] or _MEM['url'] != source_url:
            _MEM.update(_read_disk())
        if (not force and _MEM['url'] == source_url and _MEM['events'] and
                now - float(_MEM['ts'] or 0) < _ttl()):
            return list(_MEM['events'])
    try:
        req = Request(source_url, headers={'User-Agent': _UA, 'Accept': 'application/json'})
        with urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode('utf-8-sig'))
        events = _normalise(payload)
        with _LOCK:
            _MEM.update({'events': events, 'ts': now, 'url': source_url})
        _write_disk(events, source_url)
        logger.info('[EventFeed] refreshed: %d events' % len(events))
        return list(events)
    except Exception as exc:
        logger.error('[EventFeed] refresh: %s' % str(exc))
        with _LOCK:
            return list(_MEM['events']) if _MEM['url'] == source_url else []


def cached():
    return refresh(force=False)


def build_items():
    items = []
    for event in cached():
        try:
            item = Item(title=event['title'], fulltitle=event['title'],
                        thumbnail=event['thumbnail'], fanart=event['fanart'],
                        contentType='live', action='event_play',
                        infoLabels={'_enr': 1, 'mediatype': 'video',
                                    'plot': event.get('subtitle', '') or event.get('starts_at', '')})
            item.is_event_stream = True
            item.event_id = event['id']
            item.event_subtitle = event.get('subtitle', '') or event.get('starts_at', '')
            items.append(item)
        except Exception as exc:
            logger.error('[EventFeed] card: %s' % str(exc))
    return items


def _headers(source):
    raw = source.get('headers') if isinstance(source, dict) else {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _source_url(source):
    return str(source.get('url') or source.get('stream_url') or '').strip() if isinstance(source, dict) else str(source or '').strip()


def _is_online(url, headers):
    """Small GET probe.  It runs only after the user clicks a card."""
    if not url.startswith(('https://', 'http://')):
        return False
    probe_headers = {'User-Agent': _UA, 'Range': 'bytes=0-1023'}
    probe_headers.update(headers)
    try:
        with urlopen(Request(url, headers=probe_headers), timeout=6) as response:
            return 200 <= int(getattr(response, 'status', response.getcode())) < 400
    except Exception as exc:
        logger.info('[EventFeed] unavailable %s: %s' % (url.split('?', 1)[0], str(exc)))
        return False


def resolve(event_id):
    """Refresh event metadata, then return the first currently reachable source."""
    event_id = str(event_id or '')
    events = refresh(force=True)
    event = next((value for value in events if value['id'] == event_id), None)
    if event is None:
        raise RuntimeError('Evento non più disponibile')
    for source in event.get('sources') or []:
        url = _source_url(source)
        headers = _headers(source)
        if _is_online(url, headers):
            manifest = str(source.get('manifest_type') or source.get('manifest') or '').lower() if isinstance(source, dict) else ''
            if manifest not in ('hls', 'dash', 'progressive'):
                path = url.split('?', 1)[0].lower()
                manifest = 'dash' if path.endswith('.mpd') else ('hls' if '.m3u8' in path else 'progressive')
            return {'url': url, 'headers': headers, 'manifest_type': manifest,
                    'label': event['title'], 'event': event}
    raise RuntimeError('Nessuna sorgente disponibile per questo evento')
