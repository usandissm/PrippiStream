# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
# Strumentazione prestazioni (v2.0)
#
# Attiva col setting nascosto 'perf_log'. Da spento l'overhead e' una singola
# lettura di variabile per chiamata. Le righe [PERF] usano LOGWARNING perche'
# su Kodi 19+ LOGINFO non compare in kodi.log senza il debug logging globale.
# --------------------------------------------------------------------------------
import time

import xbmc

from platformcode import config

ENABLED = config.get_setting('perf_log', default=False)


def refresh():
    """Rilegge il flag con un'istanza Addon FRESCA (l'istanza cachata in config
    e' stantia dopo un salvataggio impostazioni su Kodi 21 — vedi il pattern di
    _read_live_settings in prippihome). Chiamata da _on_settings_changed della
    home cosi' il toggle visibile nel build di test ha effetto immediato."""
    global ENABLED
    try:
        import xbmcaddon
        ENABLED = xbmcaddon.Addon('plugin.video.prippistream').getSetting('perf_log') == 'true'
    except Exception:
        pass
    return ENABLED


def mark(tag, t0=None):
    """Segna un punto di misura.

    Uso:  t0 = perf.mark('fase')        # avvia il timer (nessun log)
          perf.mark('fase', t0)         # logga '[PERF] fase: N ms'
    Ritorna sempre time.time() cosi' puo' fare da t0 per la misura successiva.
    """
    now = time.time()
    if ENABLED and t0 is not None:
        try:
            xbmc.log('[PERF] %s: %.0f ms' % (tag, (now - t0) * 1000), xbmc.LOGWARNING)
        except Exception:
            pass
    return now


def note(tag, text=''):
    """Logga un evento puntuale senza durata (contatori, stati)."""
    if ENABLED:
        try:
            xbmc.log('[PERF] %s %s' % (tag, text), xbmc.LOGWARNING)
        except Exception:
            pass
