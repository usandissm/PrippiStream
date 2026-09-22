# -*- coding: utf-8 -*-
"""Private IPTV catalog/slot dispatcher used as a fallback by Live rows.

The catalog is intentionally loaded from addon data (never from the bundled
source tree).  A future broker can implement the same ``acquire`` contract;
the local implementation provides deterministic best-effort selection for a
single trusted installation.
"""
import json
import os
import re
import threading
import time

from platformcode import config, logger

_TTL = 6 * 3600
_lock = threading.Lock()
_catalog = None
_loaded_at = 0
_leases = {}


def _path():
    try:
        return os.path.join(config.get_data_path(), "iptv_catalog.json")
    except Exception:
        return None


def _load():
    global _catalog, _loaded_at
    with _lock:
        if _catalog is not None and time.time() - _loaded_at < _TTL:
            return _catalog
        p = _path()
        if not p or not os.path.isfile(p):
            _catalog = []
            _loaded_at = time.time()
            return _catalog
        try:
            blob = json.load(open(p, 'r', encoding='utf-8'))
            _catalog = blob.get('items', []) if isinstance(blob, dict) else []
            _loaded_at = time.time()
        except Exception as exc:
            logger.error('[IPTV] catalog load: %s' % exc)
            _catalog = []
            _loaded_at = time.time()
        return _catalog


def invalidate():
    global _loaded_at
    with _lock:
        _loaded_at = 0


def channels(category=None):
    rows = list(_load())
    if category:
        rows = [x for x in rows if x.get('category') == category]
    return rows


def acquire(title, lease_id, ttl=900):
    """Acquire one source for *title*; returns URL or None.

    Source URLs remain in the private local catalog.  Lease accounting is
    conservative: one source URL may be held by only one active lease.
    """
    now = time.time()
    catalog = list(_load())
    with _lock:
        for key, exp in list(_leases.items()):
            if exp <= now:
                _leases.pop(key, None)
        wanted = str(title or '').casefold().strip()
        candidates = [x for x in catalog if str(x.get('title', '')).casefold().strip() == wanted]
        candidates.sort(key=lambda x: len(x.get('sources') or []), reverse=True)
        for item in candidates:
            for url in item.get('sources') or []:
                if url in _leases:
                    continue
                _leases[url] = now + max(60, int(ttl))
                return url
    return None


def release(url):
    if not url:
        return
    with _lock:
        _leases.pop(url, None)
