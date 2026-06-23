# -*- coding: utf-8 -*-
"""
Downloads index — offline-download library storage.

JSON file: {addon_data_path}/downloads.json

Mirrors the structure/locking discipline of watch_history.py. Each entry is
keyed by a stable download key:

{
    'key':         str,    # 'dl_movie_<id>' or 'dl_ep_<showid>_s<S>_e<E>'
    'type':        str,    # 'movie' | 'episode'
    'title':       str,    # display title (episode title for episodes)
    'show_title':  str,    # series name (episodes); '' for movies
    'show_key':    str,    # groups episodes of the same series; '' for movies
    'season':      int,    # episodes only
    'episode':     int,    # episodes only
    'thumbnail':   str,
    'fanart':      str,
    'file_path':   str,    # local .ts file (possibly encrypted)
    'sub_path':    str,    # local subtitle file or ''
    'quality':     str,    # e.g. '1080p'
    'protection':  str,    # 'aes' | 'xor' | 'none' (cipher the file was written with)
    'status':      str,    # 'queued'|'downloading'|'done'|'error'|'paused'
    'progress':    float,  # 0..100
    'total_bytes': int,
    'error':       str,    # last error message (status='error')
    'item_url':    str,    # item.tourl() — re-launch / metadata
    'timestamp':   float,  # last update (ordering)
}
"""

import io
import os
import json
import threading
import time as _time

from platformcode import logger

_lock = threading.Lock()
_FILENAME = 'downloads.json'

_READ_ERROR = object()


def _get_path():
    from platformcode import config
    return os.path.join(config.get_data_path(), _FILENAME)


def _read(safe=False):
    path = _get_path()
    try:
        if not os.path.exists(path):
            return {}
        with io.open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.error('[Downloads] read: %s' % str(exc))
        return _READ_ERROR if safe else {}


def _write(data):
    try:
        with io.open(_get_path(), 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as exc:
        logger.error('[Downloads] write: %s' % str(exc))


def upsert(entry):
    """Insert or replace an entry (must contain 'key'). Stamps timestamp."""
    key = entry.get('key')
    if not key:
        return
    entry['timestamp'] = _time.time()
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR:
            logger.error('[Downloads] upsert aborted: file unreadable')
            return
        # Merge over any existing entry so partial updates don't drop fields.
        merged = data.get(key, {})
        merged.update(entry)
        data[key] = merged
        _write(data)


def update_fields(key, **fields):
    """Patch specific fields of an existing entry (used for progress/status)."""
    if not key:
        return
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR:
            return
        if key not in data:
            return
        data[key].update(fields)
        data[key]['timestamp'] = _time.time()
        _write(data)


def get(key):
    with _lock:
        return _read().get(key)


def get_all():
    """All entries, most-recent first."""
    with _lock:
        data = _read()
    entries = list(data.values())
    entries.sort(key=lambda e: e.get('timestamp', 0), reverse=True)
    return entries


def get_by_show(show_key):
    """All episode entries for a series, sorted by season/episode ascending."""
    with _lock:
        data = _read()
    eps = [e for e in data.values() if e.get('show_key') == show_key]
    eps.sort(key=lambda e: (int(e.get('season', 0) or 0), int(e.get('episode', 0) or 0)))
    return eps


def get_active():
    """Entries still queued or downloading (for resume on startup)."""
    with _lock:
        data = _read()
    return [e for e in data.values() if e.get('status') in ('queued', 'downloading', 'paused')]


def exists_done(key):
    e = get(key)
    return bool(e and e.get('status') == 'done')


def _safe_remove_file(path):
    if not path:
        return
    for p in (path, path + '.dlmeta', path + '.part'):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception as exc:
            logger.error('[Downloads] remove file %s: %s' % (p, str(exc)))


def remove(key, delete_files=True):
    """Remove an entry and (by default) its on-disk files."""
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR:
            return
        entry = data.pop(key, None)
        if entry is not None:
            _write(data)
    if entry and delete_files:
        # A multi-track bundle is a whole directory (video/audio/subs + m3u8).
        if entry.get('bundle') and entry.get('bundle_dir'):
            try:
                import shutil
                if os.path.isdir(entry['bundle_dir']):
                    shutil.rmtree(entry['bundle_dir'], ignore_errors=True)
            except Exception as exc:
                logger.error('[Downloads] remove bundle %s: %s'
                             % (entry.get('bundle_dir'), str(exc)))
        else:
            _safe_remove_file(entry.get('file_path'))
            _safe_remove_file(entry.get('sub_path'))


def remove_show(show_key, delete_files=True):
    """Remove every episode entry of a series."""
    for e in get_by_show(show_key):
        remove(e['key'], delete_files=delete_files)
