# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# platformtools — STUB headless per l'APK.
#
# Nel motore reale questo modulo faceva dialoghi Kodi + riproduzione via ISA.
# Nell'app nativa la UI (Compose) e il player (Media3) prendono il suo posto:
# qui restano solo firme sicure e non bloccanti, così i moduli-motore che lo
# importano funzionano headless. Le funzioni interattive NON vengono chiamate
# durante search/resolve; se lo fossero, ritornano default innocui.
# ------------------------------------------------------------
import xbmc  # lo shim
from platformcode import logger

PY3 = True


# ── dialoghi: no-op / default non bloccanti ──────────────────────────────────
def dialog_ok(heading='', *lines, **kw):
    logger.info('[stub] dialog_ok: %s %s' % (heading, ' '.join(str(l) for l in lines)))
    return None


def dialog_notification(heading='', message='', **kw):
    logger.info('[stub] notify: %s - %s' % (heading, message))


def dialog_yesno(heading='', *lines, **kw):
    return False


def dialog_info(item=None):
    return None


def dialog_select(heading='', options=None, **kw):
    return -1


def dialog_select_group(*a, **k):
    return -1, -1


def dialog_browse(*a, **k):
    return ''


def dialog_register(*a, **k):
    return {}


def dialog_numeric(*a, **k):
    return ''


class _ProgressStub(object):
    def create(self, *a, **k): return self
    def update(self, *a, **k): pass
    def iscanceled(self): return False
    def isFinished(self): return True
    def close(self): pass


def dialog_progress(heading='', *lines, **kw):
    return _ProgressStub()


def dialog_progress_bg(heading='', message='', **kw):
    return _ProgressStub()


# ── playback / stato: gestiti dal player NATIVO ──────────────────────────────
def is_playing():
    return False


def play_video(*a, **k):
    # La riproduzione la fa Media3 lato Kotlin (via bridge.resolve). No-op qui.
    logger.info('[stub] play_video chiamato headless — ignorato (player nativo)')
    return None


def stop_video(*a, **k):
    pass


def play_canceled(*a, **k):
    return False


def install_inputstream(*a, **k):
    return True


def torrent_client_installed(*a, **k):
    return False


# ── UI varie: no-op ──────────────────────────────────────────────────────────
def itemlist_refresh(*a, **k):
    pass


def show_video_info(*a, **k):
    return None


def show_recaptcha(*a, **k):
    return None


def show_channel_settings(*a, **k):
    return None


def calcResolution(quality='', *a, **k):
    # Rank numerico della qualità (int, non tupla): più alto = migliore.
    # Usato da servertools.sort_servers con l'operatore unario '-'.
    q = str(quality or '').lower()
    for needle, rank in (('2160', 2160), ('4k', 2160), ('1080', 1080), ('fhd', 1080),
                         ('720', 720), ('hd', 720), ('480', 480), ('360', 360)):
        if needle in q:
            return rank
    return 0


def render_items(*a, **k):
    pass


def get_dialogo_opciones(*a, **k):
    return None
