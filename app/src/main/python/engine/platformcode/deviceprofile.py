# -*- coding: utf-8 -*-
"""Small, cached hardware profile used to keep background work proportional.

The profile is intentionally conservative: Kodi devices with at most 3 GB of
RAM are treated as low-power.  This catches the 2 GB Android box without
changing the behaviour of the development PC.  Detection is best-effort and
always falls back to the existing desktop behaviour.
"""

import re
import threading
import platform

_lock = threading.Lock()
_cached = None


def _memory_mb():
    try:
        import xbmc
        label = xbmc.getInfoLabel('System.Memory(total)') or ''
        match = re.search(r'([0-9]+(?:[.,][0-9]+)?)\s*(GB|MB)', label, re.I)
        if not match:
            return 0
        value = float(match.group(1).replace(',', '.'))
        return int(value * 1024) if match.group(2).upper() == 'GB' else int(value)
    except Exception:
        return 0


def profile(refresh=False):
    """Return a stable dict with ``low_power`` and recommended worker counts."""
    global _cached
    with _lock:
        if _cached is not None and not refresh:
            return dict(_cached)
        memory_mb = _memory_mb()
        machine = (platform.machine() or '').lower()
        try:
            import xbmc
            android = bool(xbmc.getCondVisibility('System.Platform.Android'))
        except Exception:
            android = False
        # Memory is the primary signal. Android+ARM is a safe fallback when a
        # skin/build does not expose System.Memory(total).
        low_power = bool((memory_mb and memory_mb <= 3072)
                         or (not memory_mb and android
                             and ('arm' in machine or 'aarch' in machine)))
        _cached = {
            'memory_mb': memory_mb,
            'machine': machine,
            'android': android,
            'low_power': low_power,
            'tmdb_workers': 2 if low_power else 8,
            'search_workers': 3 if low_power else 6,
            'live_probe_workers': 4 if low_power else 10,
        }
        return dict(_cached)


def is_low_power():
    return bool(profile().get('low_power'))


def worker_count(kind, normal):
    return max(1, int(profile().get(kind + '_workers') or normal))
