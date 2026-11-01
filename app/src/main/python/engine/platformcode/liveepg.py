"""Bounded row publication gate; missing EPG must never block live channels forever."""
import threading
import time
from platformcode import skyepg

_lock = threading.Lock()
_rows = {}
WAIT_SECONDS = 5.0


def reset():
    with _lock:
        _rows.clear()


def keys_for(items):
    return tuple(sorted({key for item in items for key in (
        getattr(item, 'sport_par', ''), getattr(item, 'fulltitle', '') or getattr(item, 'title', '')
    ) if key}))


def start(items):
    keys = keys_for(items)
    with _lock:
        previous = _rows.get(keys)
        if previous and time.monotonic() - previous < 180:
            return keys
        _rows[keys] = time.monotonic()
    threading.Thread(target=skyepg.prefetch, args=(keys,), daemon=True).start()
    return keys


def ready(items):
    keys = start(items)
    if skyepg.attempted(keys):
        return True
    if all(skyepg.now_on(getattr(item, 'sport_par', '')) or
           skyepg.now_on(getattr(item, 'fulltitle', '') or getattr(item, 'title', '')) for item in items):
        return True
    with _lock:
        return time.monotonic() - _rows[keys] >= WAIT_SECONDS


def wait(items, active=lambda: True):
    start(items)
    while active() and not ready(items):
        time.sleep(0.05)
    return active()
