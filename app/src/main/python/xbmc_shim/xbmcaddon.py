# -*- coding: utf-8 -*-
# Shim di `xbmcaddon` — Addon con settings (default da resources/settings.xml,
# override utente in un JSON in DATA_DIR). Solo l'API usata dal motore:
# getSetting, setSetting, getAddonInfo, getLocalizedString, getSettingBool/Int.
import json
import os
import re
import threading
import ast

import prippi_env

_DEFAULTS = None
_DEFAULTS_PATH = None
_DEFAULTS_LOCK = threading.Lock()
_STORE_LOCK = threading.Lock()
_LANGUAGE = None
_LANGUAGE_PATH = None
_LANGUAGE_LOCK = threading.Lock()

_SETTING_RE = re.compile(r'<setting\b([^>]*)/?>', re.IGNORECASE)
_ATTR_ID_RE = re.compile(r'\bid\s*=\s*"([^"]*)"')
_ATTR_DEF_RE = re.compile(r'\bdefault\s*=\s*"([^"]*)"')

# Kodi restituisce sempre stringhe da getSetting. Questi fallback permettono
# al motore di avviarsi anche se un aggiornamento trova uno store precedente
# con valori nulli o se settings.xml non è ancora stato copiato.
_SAFE_DEFAULTS = {
    'chrome_ua_version': '120.0.6099.225',
    'view_mode_channel': 'Default, 0',
    'view_mode_channels': 'Default, 0',
    'resolve_priority': '0',
}


def _load_defaults():
    """Parsa i default da resources/settings.xml (formato Kodi 'vecchio':
    <setting id="x" ... default="y"/>)."""
    global _DEFAULTS, _DEFAULTS_PATH
    with _DEFAULTS_LOCK:
        prippi_env._ensure()
        path = os.path.join(prippi_env.RUNTIME_DIR, 'resources', 'settings.xml')
        # Su Chaquopy un import può chiedere un setting prima che bridge.init
        # abbia assegnato il runtime filesystem. Non rendere permanente quella
        # lettura vuota: ricarica quando il path runtime diventa quello reale.
        if _DEFAULTS is not None and _DEFAULTS_PATH == path and _DEFAULTS:
            return _DEFAULTS
        _DEFAULTS = {}
        _DEFAULTS_PATH = path
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


def _load_language():
    """Carica le stringhe italiane Kodi dal PO sincronizzato con la v2."""
    global _LANGUAGE, _LANGUAGE_PATH
    with _LANGUAGE_LOCK:
        prippi_env._ensure()
        path = os.path.join(
            prippi_env.RUNTIME_DIR, 'resources', 'language',
            'resource.language.it_it', 'strings.po')
        if _LANGUAGE is not None and _LANGUAGE_PATH == path:
            return _LANGUAGE
        result = {}
        current_id = None
        chunks = None

        def flush():
            if current_id is not None and chunks:
                result[str(current_id)] = ''.join(chunks)

        try:
            with open(path, 'r', encoding='utf-8-sig', errors='replace') as handle:
                for raw in handle:
                    line = raw.strip()
                    if line.startswith('msgctxt '):
                        flush()
                        match = re.match(r'msgctxt\s+"#(\d+)"', line)
                        current_id = match.group(1) if match else None
                        chunks = None
                    elif current_id is not None and line.startswith('msgstr '):
                        chunks = []
                        quoted = line[len('msgstr '):]
                        try:
                            chunks.append(ast.literal_eval(quoted))
                        except Exception:
                            pass
                    elif current_id is not None and chunks is not None and line.startswith('"'):
                        try:
                            chunks.append(ast.literal_eval(line))
                        except Exception:
                            pass
                flush()
        except Exception:
            result = {}
        _LANGUAGE = result
        _LANGUAGE_PATH = path
        return result


class Addon(object):
    def __init__(self, id=None):
        self.id = id or 'plugin.video.prippistream'

    # ── settings ──
    def getSetting(self, key):
        with _STORE_LOCK:
            store = _load_store()
        if key in store and store[key] not in (None, ''):
            return str(store[key])
        value = _load_defaults().get(key, _SAFE_DEFAULTS.get(key, ''))
        if value in (None, ''):
            value = _SAFE_DEFAULTS.get(key, '')
        return str(value)

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
        return _load_language().get(str(code), str(code))

    def openSettings(self):
        pass
