# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
# Log push diagnostico (solo build di test, gated sul setting 'perf_log')
#
# Il webserver di Kodi non puo' servire special://logs/kodi.log (il suo /vfs/ e'
# ristretto ai media source) e su questa box non c'e' adb. Per raccogliere i log
# di prova da un PC sulla stessa rete, l'addon (che ha pieno accesso al
# filesystem) legge il kodi.log con xbmcvfs e lo INVIA periodicamente al PC.
#
# Solo connessione IN USCITA dalla box verso il PC: nessuna porta aperta sulla
# box, nessun server locale. Best-effort: ogni errore viene ingoiato e la
# frequenza (ogni ~25s) e' bassa per non falsare le misure [PERF].
# --------------------------------------------------------------------------------
import threading

import xbmc

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen

# PC di raccolta sulla rete locale (hotspot 172.20.10.x: il PC e' .2).
DEST = 'http://172.20.10.2:8199/log'
INTERVAL = 25          # secondi tra un invio e l'altro
_started = False


def _read_log():
    if xbmcvfs is None:
        return b''
    try:
        f = xbmcvfs.File('special://logs/kodi.log')
        try:
            data = f.readBytes()
        finally:
            f.close()
        return data or b''
    except Exception:
        return b''


def _loop(dest, interval):
    monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        try:
            body = _read_log()
            if body:
                req = Request(dest, data=body,
                              headers={'Content-Type': 'text/plain'})
                try:
                    urlopen(req, timeout=4).read()
                except Exception:
                    pass  # PC spento/irraggiungibile: riprova al giro dopo
        except Exception:
            pass
        if monitor.waitForAbort(interval):
            break


def start(dest=DEST, interval=INTERVAL):
    """Avvia l'invio periodico del log in un thread demone. Idempotente."""
    global _started
    if _started:
        return
    _started = True
    try:
        t = threading.Thread(target=_loop, args=(dest, interval))
        t.daemon = True
        t.start()
        xbmc.log('[PERF] logpush -> %s ogni %ds' % (dest, interval),
                 xbmc.LOGWARNING)
    except Exception as exc:
        try:
            xbmc.log('[PERF] logpush non avviato: %s' % exc, xbmc.LOGWARNING)
        except Exception:
            pass
