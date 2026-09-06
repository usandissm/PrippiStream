# -*- coding: utf-8 -*-
"""Updater comune del registro remoto usato da Kodi e Android.

Il file remoto resta l'unica fonte di verità per domini e seed findhost.
La copia inclusa nella build è soltanto il fallback offline. Il refresh deve
sempre essere avviato fuori dal percorso del primo paint.
"""
from __future__ import absolute_import

import json
import os
import threading
import time

try:
    from urllib.parse import urlparse
    from urllib.request import Request, urlopen
except ImportError:  # pragma: no cover - compatibilità Kodi/Python legacy
    from urlparse import urlparse
    from urllib2 import Request, urlopen


REGISTRY_URL = (
    'https://raw.githubusercontent.com/usandissm/PrippiStream/main/channels.json'
)
MAX_REGISTRY_BYTES = 64 * 1024
MIN_REFRESH_INTERVAL_SECONDS = 5 * 60
_lock = threading.RLock()
_last_attempt = 0.0


def _now():
    return getattr(time, 'monotonic', time.time)()


def _validate_mapping(name, value):
    if not isinstance(value, dict):
        raise ValueError('%s deve essere un oggetto' % name)
    for channel, raw_url in value.items():
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError('%s contiene un nome canale non valido' % name)
        if not isinstance(raw_url, str):
            raise ValueError('%s.%s non è una URL' % (name, channel))
        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValueError('%s.%s usa una URL non valida' % (name, channel))


def validate(raw_text):
    if not isinstance(raw_text, str):
        raise ValueError('registro non testuale')
    encoded = raw_text.encode('utf-8')
    if not encoded or len(encoded) > MAX_REGISTRY_BYTES:
        raise ValueError('dimensione registro non valida')
    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError('radice registro non valida')
    direct = parsed.get('direct')
    findhost = parsed.get('findhost')
    _validate_mapping('direct', direct)
    _validate_mapping('findhost', findhost)
    if 'streamingcommunity' not in direct or 'streamingcommunity' not in findhost:
        raise ValueError('seed StreamingCommunity mancanti')
    return parsed


def _atomic_write(path, raw_text):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    staging = '%s.tmp.%s.%s' % (path, os.getpid(), threading.current_thread().ident)
    try:
        with open(staging, 'w', encoding='utf-8') as handle:
            handle.write(raw_text)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        replace = getattr(os, 'replace', None)
        if replace:
            replace(staging, path)
        else:  # pragma: no cover - solo interpreti Python molto vecchi
            if os.path.exists(path):
                os.remove(path)
            os.rename(staging, path)
    finally:
        try:
            if os.path.exists(staging):
                os.remove(staging)
        except Exception:
            pass


def sync(config, logger=None, timeout=6, force=False):
    """Aggiorna atomicamente channels.json e invalida la cache in memoria."""
    global _last_attempt
    with _lock:
        now = _now()
        if not force and now - _last_attempt < MIN_REFRESH_INTERVAL_SECONDS:
            return {'ok': True, 'status': 'throttled', 'changed': False}
        _last_attempt = now
        local_path = os.path.join(config.get_runtime_path(), 'channels.json')
        try:
            request = Request(
                REGISTRY_URL,
                headers={'User-Agent': 'PrippiStream domain-registry/1'},
            )
            payload = urlopen(request, timeout=timeout).read(MAX_REGISTRY_BYTES + 1)
            if len(payload) > MAX_REGISTRY_BYTES:
                raise ValueError('registro remoto troppo grande')
            remote_text = payload.decode('utf-8-sig')
            validate(remote_text)
            try:
                with open(local_path, 'r', encoding='utf-8') as handle:
                    local_text = handle.read()
            except Exception:
                local_text = ''
            if remote_text.strip() == local_text.strip():
                return {'ok': True, 'status': 'current', 'changed': False}
            _atomic_write(local_path, remote_text)
            config.channels_data = dict()
            if logger:
                logger.info('[domain_registry] registro aggiornato dalla fonte comune')
            return {'ok': True, 'status': 'updated', 'changed': True}
        except Exception as error:
            if logger:
                logger.error('[domain_registry] refresh fallito: %s' % str(error))
            return {
                'ok': False,
                'status': 'fallback',
                'changed': False,
                'error': str(error),
            }
