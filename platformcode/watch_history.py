# -*- coding: utf-8 -*-
"""
Continue Watching — watch-progress storage.

JSON file: {addon_data_path}/continue_watching.json

Each entry (keyed by a stable content key):
{
    'key':          str,    # e.g. 'movie_12345' or 'ep_12345_s1_e3'
    'title':        str,    # display title
    'thumbnail':    str,    # poster URL
    'fanart':       str,    # backdrop URL
    'time_watched': float,  # seconds at which user stopped
    'total_time':   float,  # total duration in seconds
    'timestamp':    float,  # Unix timestamp of last update (for ordering)
    'item_url':     str,    # item.tourl() — enough to re-launch the content
}
"""

import json
import os
import threading
import time as _time

from platformcode import logger

_lock = threading.Lock()
_FILENAME = 'continue_watching.json'


def _get_path():
    from platformcode import config
    return os.path.join(config.get_data_path(), _FILENAME)


def _read():
    try:
        path = _get_path()
        if not os.path.exists(path):
            return {}
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as exc:
        logger.error('[WatchHistory] read: %s' % str(exc))
        return {}


def _write(data):
    try:
        with open(_get_path(), 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error('[WatchHistory] write: %s' % str(exc))


def save_progress(key, title, thumbnail, fanart, time_watched, total_time, item_url, show_url='', played_url=''):
    """Save or update a watch-progress entry."""
    with _lock:
        data = _read()
        entry = {
            'key':          key,
            'title':        title,
            'thumbnail':    thumbnail,
            'fanart':       fanart,
            'time_watched': float(time_watched),
            'total_time':   float(total_time),
            'timestamp':    _time.time(),
            'item_url':     item_url,
            'show_url':     show_url,
        }
        # Preserve existing played_url if we don't have a new one
        if played_url:
            entry['played_url'] = played_url
        elif key in data and data[key].get('played_url'):
            entry['played_url'] = data[key]['played_url']
        data[key] = entry
        _write(data)
    logger.info('[WatchHistory] saved "%s" at %.0fs/%.0fs' % (title, time_watched, total_time))


def remove(key):
    """Remove a completed (or deleted) entry."""
    with _lock:
        data = _read()
        if key in data:
            title = data[key].get('title', key)
            del data[key]
            _write(data)
            logger.info('[WatchHistory] removed "%s"' % title)


def get(key):
    """Return the entry for *key*, or None."""
    with _lock:
        return _read().get(key)


def get_all():
    """Return all entries sorted by timestamp descending (most recent first)."""
    with _lock:
        data = _read()
    entries = list(data.values())
    entries.sort(key=lambda e: e.get('timestamp', 0), reverse=True)
    return entries
