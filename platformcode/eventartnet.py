"""Polite image/metadata HTTP reads: rate limits are NOT missing crests."""
import json
import os
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

_LOCK = threading.Lock()
_BACKOFF = None
_NEXT = {}


class TemporaryError(BlockingIOError):
    pass


def _path():
    from platformcode import config
    return os.path.join(config.get_data_path(), 'event_art_backoff.json')


def _load():
    global _BACKOFF
    if _BACKOFF is None:
        try:
            with open(_path(), encoding='utf-8') as stream:
                values = json.load(stream)
            _BACKOFF = {host: float(until) for host, until in values.items()
                        if float(until) > time.time()}
        except (OSError, ValueError, TypeError, AttributeError):
            _BACKOFF = {}


def _pause(host, seconds):
    with _LOCK:
        _load()
        _BACKOFF[host] = max(_BACKOFF.get(host, 0), time.time() + seconds)
        try:
            path = _path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + '.tmp', 'w', encoding='utf-8') as stream:
                json.dump(_BACKOFF, stream)
            os.replace(path + '.tmp', path)
        except OSError:
            pass


def read(request, limit, timeout=5):
    url = request.full_url if hasattr(request, 'full_url') else request
    host = (urlsplit(url).hostname or '').lower()
    # All language Wikipedias share one request budget. Image CDNs are separate.
    key = 'wikipedia.org' if host.endswith('.wikipedia.org') else host
    with _LOCK:
        _load()
        if _BACKOFF.get(key, 0) > time.time():
            raise TemporaryError('artwork provider cooling down')
        delay = max(0, _NEXT.get(key, 0) - time.monotonic())
        if delay:
            time.sleep(min(delay, 1.0))
        _NEXT[key] = time.monotonic() + (1.0 if key == 'wikipedia.org' else 0.3)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(limit)
    except HTTPError as exc:
        if exc.code != 429 and exc.code < 500:
            exc.close()
            raise
        seconds = 900 if exc.code == 429 else 120
        retry = (exc.headers or {}).get('Retry-After')
        if retry:
            try:
                seconds = max(seconds, float(retry))
            except ValueError:
                try:
                    seconds = max(seconds, parsedate_to_datetime(retry).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError):
                    pass
        _pause(key, seconds)
        exc.close()
        raise TemporaryError('artwork provider temporarily unavailable') from exc
    except (URLError, TimeoutError, OSError) as exc:
        _pause(key, 60)
        raise TemporaryError('artwork connection temporarily unavailable') from exc
