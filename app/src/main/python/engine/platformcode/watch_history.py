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
import io

from platformcode import logger

_lock = threading.Lock()
_FILENAME = 'continue_watching.json'


def _get_path():
    from platformcode import config
    return os.path.join(config.get_data_path(), _FILENAME)


# Sentinel returned by _read() when the file exists but could not be parsed.
# Callers that WRITE must treat this as "unknown" and abort the write, so a
# transient read error never wipes the whole CW database.
_READ_ERROR = object()


def _read(safe=False):
    """Load the CW dict from disk.

    Always opens as UTF-8: the file is written with ensure_ascii=False, so it
    can contain non-Latin titles (e.g. Korean). Without an explicit encoding,
    Python on Windows uses the locale codepage (cp1252) and raises
    UnicodeDecodeError on those bytes.

    @param safe: when True, return _READ_ERROR (not {}) if the file exists but
        cannot be parsed, so a follow-up write does not overwrite good data.
    """
    path = _get_path()
    try:
        if not os.path.exists(path):
            return {}
        with io.open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.error('[WatchHistory] read: %s' % str(exc))
        return _READ_ERROR if safe else {}


def _write(data):
    try:
        with io.open(_get_path(), 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as exc:
        logger.error('[WatchHistory] write: %s' % str(exc))


def save_progress(key, title, thumbnail, fanart, time_watched, total_time, item_url,
                  show_url='', played_url='',
                  season=None, episode=None, episode_title=''):
    """Save or update a watch-progress entry.

    Optional season/episode/episode_title track the current episode for TV series.
    The watched_episodes list (list of [season, episode] pairs) is preserved from
    any existing entry so partial saves don't wipe the history.
    """
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR:
            logger.error('[WatchHistory] save_progress aborted: CW file unreadable, refusing to overwrite')
            return
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
        if season is not None:
            entry['season'] = int(season)
        if episode is not None:
            entry['episode'] = int(episode)
        if episode_title:
            entry['episode_title'] = str(episode_title)
        # Preserve existing played_url if we don't have a new one
        if played_url:
            entry['played_url'] = played_url
        elif key in data and data[key].get('played_url'):
            entry['played_url'] = data[key]['played_url']
        # Preserve existing watched_episodes list (never overwrite with empty)
        if key in data and 'watched_episodes' in data[key]:
            entry['watched_episodes'] = data[key]['watched_episodes']
        data[key] = entry
        _write(data)
    logger.info('[WatchHistory] saved "%s" at %.0fs/%.0fs' % (title, time_watched, total_time))


def remove(key):
    """Remove a completed (or deleted) entry."""
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR:
            logger.error('[WatchHistory] remove aborted: CW file unreadable')
            return
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


def mark_episode_watched(show_key, season, episode):
    """Mark a specific episode as fully watched in the show's CW entry.

    Creates the entry shell (without play data) if it doesn't exist yet.
    The [season, episode] pair is added to watched_episodes if not already present.
    """
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR:
            logger.error('[WatchHistory] mark_episode_watched aborted: CW file unreadable, refusing to overwrite')
            return
        entry = data.get(show_key, {'key': show_key})
        watched = entry.get('watched_episodes', [])
        pair = [int(season), int(episode)]
        if pair not in watched:
            watched.append(pair)
            entry['watched_episodes'] = watched
            data[show_key] = entry
            _write(data)
    logger.info('[WatchHistory] marked watched S%02dE%02d for %s' % (season, episode, show_key))


def get_watched_episodes(show_key):
    """Return list of [season, episode] pairs for fully watched episodes of a show."""
    with _lock:
        data = _read()
        return list(data.get(show_key, {}).get('watched_episodes', []))


def get_episode_info(show_key):
    """Return current episode info for a show, or None if not tracked.

    Returns a dict with keys: season, episode, episode_title, time_watched, total_time.
    """
    with _lock:
        entry = _read().get(show_key)
    if not entry:
        return None
    season  = entry.get('season')
    episode = entry.get('episode')
    if season is None or episode is None:
        return None
    return {
        'season':        int(season),
        'episode':       int(episode),
        'episode_title': entry.get('episode_title', ''),
        'time_watched':  float(entry.get('time_watched', 0)),
        'total_time':    float(entry.get('total_time', 0)),
    }
