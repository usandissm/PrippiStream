# -*- coding: utf-8 -*-
"""Local, atomic and bounded storage for recent PrippiStream searches."""

import json
import os
import threading

from platformcode import config, logger

_LOCK = threading.Lock()
_FILE = 'search_history.json'


def _path():
    return os.path.join(config.get_data_path(), _FILE)


def load(limit=10):
    try:
        with _LOCK:
            with open(_path(), 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
        values = payload.get('queries', []) if isinstance(payload, dict) else []
        return [str(value).strip() for value in values if str(value).strip()][:max(1, int(limit))]
    except (IOError, OSError, ValueError, TypeError):
        return []
    except Exception as exc:
        logger.error('[SearchHistory] load: %s' % str(exc)[:100])
        return []


def save(query, limit=10):
    query = str(query or '').strip()
    if not query:
        return load(limit)
    values = load(limit)
    folded = query.casefold()
    values = [value for value in values if value.casefold() != folded]
    values.insert(0, query)
    values = values[:max(1, int(limit))]
    try:
        path = _path()
        tmp = path + '.tmp'
        payload = {'version': 1, 'queries': values}
        with _LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(',', ':'))
            os.replace(tmp, path)
    except Exception as exc:
        logger.error('[SearchHistory] save: %s' % str(exc)[:100])
    return values


def clear():
    try:
        with _LOCK:
            path = _path()
            if os.path.isfile(path):
                os.remove(path)
            tmp = path + '.tmp'
            if os.path.isfile(tmp):
                os.remove(tmp)
    except Exception as exc:
        logger.error('[SearchHistory] clear: %s' % str(exc)[:100])
