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
    'status':      str,    # 'queued'|'downloading'|'waiting_network'|'done'|'error'|'paused'
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


def update_fields_unless_done(key, **fields):
    """Patch an unfinished entry without ever downgrading a completed file.

    A stale/duplicated worker must not turn a valid offline download from
    ``done`` into ``error`` or ``paused``.
    """
    if not key:
        return False
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR or key not in data:
            return False
        if data[key].get('status') == 'done':
            return False
        data[key].update(fields)
        data[key]['timestamp'] = _time.time()
        _write(data)
        return True


def _has_playable_file(entry):
    path = entry.get('file_path') or ''
    if not path or not os.path.isfile(path):
        return False
    try:
        return os.path.getsize(path) > 0
    except Exception:
        return False


def repair_completed():
    """Recover rows which were completed and later overwritten by an old job.

    Version 0.8.3 could enqueue the same key twice. The second copy sometimes
    changed a 100% row to ``error`` although its encrypted file was intact.
    Progress at 100% plus a non-empty target is the durable completion marker.
    """
    repaired = 0
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR:
            return 0
        for entry in data.values():
            try:
                complete = float(entry.get('progress', 0) or 0) >= 99.9
            except Exception:
                complete = False
            if entry.get('status') != 'done' and complete and _has_playable_file(entry):
                entry['status'] = 'done'
                entry['progress'] = 100.0
                entry['error'] = ''
                entry['timestamp'] = _time.time()
                repaired += 1
        if repaired:
            _write(data)
    return repaired


def migrate_legacy_network_errors():
    """Turn 0.8.3's explicit offline failures back into resumable jobs."""
    migrated = 0
    markers = ('network is unreachable', 'network unreachable', '[errno 101]')
    with _lock:
        data = _read(safe=True)
        if data is _READ_ERROR:
            return 0
        for entry in data.values():
            error = str(entry.get('error') or '').lower()
            if entry.get('status') == 'error' and any(m in error for m in markers):
                entry['status'] = 'waiting_network'
                entry['error'] = ''
                entry['timestamp'] = _time.time()
                migrated += 1
        if migrated:
            _write(data)
    return migrated


def get(key):
    repair_completed()
    with _lock:
        return _read().get(key)


def get_all():
    """All entries, most-recent first."""
    repair_completed()
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


def get_resumable():
    """Jobs interrupted by a process stop; deliberately paused jobs stay paused."""
    with _lock:
        data = _read()
    return [e for e in data.values()
            if e.get('status') in ('queued', 'downloading', 'waiting_network')]


def get_active():
    """Backward-compatible alias for callers which restore interrupted jobs."""
    return get_resumable()


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
