# -*- coding: utf-8 -*-
# Shim di `xbmcaddon` — Addon con settings (default da resources/settings.xml,
# override utente in un JSON in DATA_DIR). Solo l'API usata dal motore:
# getSetting, setSetting, getAddonInfo, getLocalizedString, getSettingBool/Int.
import json
import os
import re
import threading

import prippi_env

_DEFAULTS = None
_DEFAULTS_LOCK = threading.Lock()
_STORE_LOCK = threading.Lock()

_SETTING_RE = re.compile(r'<setting\b([^>]*)/?>', re.IGNORECASE)
_ATTR_ID_RE = re.compile(r'\bid\s*=\s*"([^"]*)"')
_ATTR_DEF_RE = re.compile(r'\bdefault\s*=\s*"([^"]*)"')


def _load_defaults():
    """Parsa i default da resources/settings.xml (formato Kodi 'vecchio':
    <setting id="x" ... default="y"/>)."""
    global _DEFAULTS
    with _DEFAULTS_LOCK:
        if _DEFAULTS is not None:
            return _DEFAULTS
        prippi_env._ensure()
        _DEFAULTS = {}
        path = os.path.join(prippi_env.RUNTIME_DIR, 'resources', 'settings.xml')
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                txt = f.read()
            for m in _SETTING_RE.finditer(txt):
                attrs = m.group(1)
                mid = _ATTR_ID_RE.search(attrs)
                if not mid:
                    continue
                mdef = _ATTR_DEF_RE.search(attrs)
                _DEFAULTS[mid.group(1)] = mdef.group(1) if mdef else ''
        except Exception:
            pass
        return _DEFAULTS


def _store_path():
    prippi_env._ensure()
    return os.path.join(prippi_env.DATA_DIR, 'settings_store.json')


def _load_store():
    try:
        with open(_store_path(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_store(store):
    try:
        with open(_store_path(), 'w', encoding='utf-8') as f:
            json.dump(store, f)
    except Exception:
        pass


class Addon(object):
    def __init__(self, id=None):
        self.id = id or 'plugin.video.prippistream'

    # ── settings ──
    def getSetting(self, key):
        with _STORE_LOCK:
            store = _load_store()
        if key in store:
            return store[key]
        return _load_defaults().get(key, '')

    def setSetting(self, key, value):
        with _STORE_LOCK:
            store = _load_store()
            store[key] = '' if value is None else str(value)
            _save_store(store)

    def getSettingBool(self, key):
        v = self.getSetting(key)
        return str(v).lower() in ('true', '1', 'yes')

    def getSettingInt(self, key):
        try:
            return int(self.getSetting(key))
        except Exception:
            return 0

    def getSettingString(self, key):
        return self.getSetting(key)

    # ── info ──
    def getAddonInfo(self, key):
        prippi_env._ensure()
        k = (key or '').lower()
        return {
            'path': prippi_env.RUNTIME_DIR,
            'profile': prippi_env.DATA_DIR,
            'id': self.id,
            'name': 'PrippiStream',
            'version': '2.0.0',
            'author': 'usandissm',
            'icon': os.path.join(prippi_env.RUNTIME_DIR, 'resources', 'media', 'logo.png'),
            'fanart': os.path.join(prippi_env.RUNTIME_DIR, 'resources', 'media', 'fanart.jpg'),
        }.get(k, '')

    def getLocalizedString(self, code):
        # Nessuna tabella lingua headless: ritorna il codice come stringa.
        return str(code)

    def openSettings(self):
        pass
