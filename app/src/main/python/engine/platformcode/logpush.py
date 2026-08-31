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
#
# Invio INCREMENTALE + gzip (per hotspot/linee lente): dopo il primo invio
# parte solo il DELTA dal byte gia' consegnato (header X-Log-Offset; il
# collector ricompone). Se il log si accorcia (rotazione) si riparte da 0;
# il primo invio e' comunque limitato agli ultimi FIRST_TAIL_MAX byte.
# --------------------------------------------------------------------------------
import gzip
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
FIRST_TAIL_MAX = 2 * 1024 * 1024   # primo invio: al massimo la coda da 2MB
_started = False
_offset = 0            # byte del log gia' consegnati con successo


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
    global _offset
    monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        try:
            data = _read_log()
            if data:
                total = len(data)
                if total < _offset:
                    _offset = 0        # log ruotato/azzerato: riparti
                start = _offset
                if start == 0 and total > FIRST_TAIL_MAX:
                    start = total - FIRST_TAIL_MAX
                chunk = data[start:]
                if chunk:
                    body = gzip.compress(chunk)
                    req = Request(dest, data=body,
                                  headers={'Content-Type': 'text/plain',
                                           'Content-Encoding': 'gzip',
                                           'X-Log-Offset': str(start),
                                           'X-Log-Total': str(total)})
                    try:
                        urlopen(req, timeout=10).read()
                        _offset = total    # consegnato: al giro dopo solo il delta
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
