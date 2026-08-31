# -*- coding: utf-8 -*-
# Shim minimale del modulo `xbmc` di Kodi — solo l'API usata dal MOTORE
# (scraping/resolver). Nessuna UI. Vedi superficie reale: translatePath, sleep,
# getCondVisibility, log, LOG*, makeLegalFilename, executebuiltin, getInfoLabel,
# getSkinDir, executeJSONRPC, Player, KodiStub.
import os
import re
import sys
import time
import threading
from datetime import datetime

import prippi_env

# ── Livelli di log Kodi ──
LOGDEBUG = 0
LOGINFO = 1
LOGNOTICE = 2      # deprecato in Kodi ma il motore lo referenzia
LOGWARNING = 3
LOGERROR = 4
LOGFATAL = 6
LOGNONE = 7

# Marcatore usato da alcuni moduli per capire se sono sotto uno stub
KodiStub = True
_log_lock = threading.Lock()


def log(msg, level=LOGINFO):
    try:
        prefix = {LOGERROR: 'ERROR', LOGWARNING: 'WARN', LOGDEBUG: 'DEBUG'}.get(level, 'INFO')
        timestamp = datetime.now().astimezone().isoformat(timespec='milliseconds')
        line = '%s [xbmc:%s] %s\n' % (timestamp, prefix, msg)
        sys.stderr.write(line)
        prippi_env._ensure()
        log_dir = os.path.join(prippi_env.DATA_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, 'prippistream.log')
        with _log_lock:
            if os.path.isfile(path) and os.path.getsize(path) > 512 * 1024:
                with open(path, 'rb') as handle:
                    tail = handle.read()[-256 * 1024:]
                # Rotate on a complete line: reports must never begin with an
                # arbitrary fragment of a tokenized URL or traceback.
                first_newline = tail.find(b'\n')
                if first_newline >= 0:
                    tail = tail[first_newline + 1:]
                with open(path, 'wb') as handle:
                    handle.write(tail)
            with open(path, 'a', encoding='utf-8', errors='replace') as handle:
                handle.write(line)
    except Exception:
        pass


def translatePath(path):
    """Mappa gli special:// di Kodi su percorsi reali dell'app."""
    prippi_env._ensure()
    if not path or '://' not in path:
        return path
    p = path.replace('\\', '/')
    # profilo/userdata/addon_data → DATA_DIR ; home → RUNTIME_DIR ; temp → TEMP_DIR
    for prefix in ('special://profile/', 'special://userdata/', 'special://masterprofile/'):
        if p.startswith(prefix):
            return os.path.normpath(os.path.join(prippi_env.DATA_DIR, p[len(prefix):]))
    if p.startswith('special://home/'):
        return os.path.normpath(os.path.join(prippi_env.RUNTIME_DIR, p[len('special://home/'):]))
    if p.startswith('special://temp/'):
        return os.path.normpath(os.path.join(prippi_env.TEMP_DIR, p[len('special://temp/'):]))
    if p.startswith('special://logs/'):
        return os.path.normpath(os.path.join(prippi_env.DATA_DIR, 'logs', p[len('special://logs/'):]))
    # sconosciuto: togli lo schema special:// e ancora a DATA_DIR
    if p.startswith('special://'):
        return os.path.normpath(os.path.join(prippi_env.DATA_DIR, p[len('special://'):]))
    return path


def validatePath(path):
    return path


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def makeLegalFilename(path):
    # Mantiene la cartella, sanifica solo il nome file.
    d, name = os.path.split(path)
    name = _ILLEGAL.sub('_', name)
    return os.path.join(d, name) if d else name


def sleep(ms):
    try:
        time.sleep(ms / 1000.0)
    except Exception:
        pass


def getCondVisibility(cond):
    # Il motore lo usa per rilevare la piattaforma (System.Platform.*).
    c = (cond or '').lower()
    if 'platform.android' in c or 'platform.linux' in c:
        return True   # Chaquopy gira su Android (kernel Linux)
    return False


def getInfoLabel(label):
    l = (label or '').lower()
    if 'buildversion' in l:
        return '21.0'          # target Kodi-equivalente
    if 'system.memory' in l:
        return '0'
    return ''


def getSkinDir():
    return 'skin.estuary'


def executebuiltin(cmd, wait=False):
    # Nessuna UI: no-op (Container.Refresh, Addon.OpenSettings, ecc. non servono headless).
    log('executebuiltin ignorato: %s' % cmd, LOGDEBUG)


def executeJSONRPC(payload):
    # Nessun motore JSON-RPC: risposta vuota valida.
    return '{"jsonrpc":"2.0","id":1,"result":{}}'


class Monitor(object):
    def abortRequested(self):
        return False

    def waitForAbort(self, timeout=0):
        try:
            time.sleep(timeout)
        except Exception:
            pass
        return False


class Player(object):
    # Stub inerte: la riproduzione la fa il player NATIVO (Media3), non il motore.
    def __init__(self, *a, **k):
        pass

    def play(self, *a, **k):
        pass

    def stop(self, *a, **k):
        pass

    def isPlaying(self):
        return False

    def isPlayingVideo(self):
        return False


class Keyboard(object):
    def __init__(self, default='', heading='', hidden=False):
        self._text = default
        self._confirmed = False

    def doModal(self):
        pass

    def isConfirmed(self):
        return self._confirmed

    def getText(self):
        return self._text
