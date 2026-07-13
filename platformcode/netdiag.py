# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------------
# Diagnostica di RETE (solo build di test, gated sul setting 'perf_log')
#
# Serve a distinguere "l'addon/il device e' lento" da "la LINEA e' lenta o
# bloccata". Due fonti incrociate nel log:
#
#   1. [NET] probe  — all'avvio e poi ogni PROBE_INTERVAL secondi misura su
#      endpoint NEUTRI (fuori dai siti dell'addon): latenza TCP verso un IP
#      fisso (1.1.1.1, senza DNS), tempo di risoluzione DNS, velocita' di
#      download reale (timeboxed, max ~4s). Chiude con un verdetto sintetico
#      (LINEA OK / LENTA / BLOCCATA/ASSENTE).
#   2. [NET] http   — riassunto del traffico REALE dell'addon dall'ultimo
#      probe (richieste, errori per tipo, ttfb medio, KB/s), alimentato da
#      httptools.downloadpage via record().
#
# Lettura: probe lento => e' la linea; probe ok ma richieste addon lente =>
# codice o sito/blocco specifico (vedi le singole righe [PERF] http/[NET]).
# Best-effort: ogni errore viene ingoiato, gira in un thread demone.
# --------------------------------------------------------------------------------
import socket
import ssl
import threading
import time

import xbmc

PROBE_INTERVAL = 600   # secondi tra un probe e l'altro
DL_TIMEBOX = 4.0       # secondi massimi dedicati alla misura di velocita'
DL_MAX_BYTES = 1500000 # tetto byte della misura (protegge la linea lenta)

# Endpoint neutri: non c'entrano con i siti dell'addon, cosi' un loro blocco
# ISP non falsa la misura della linea "pura".
LATENCY_IP = ('1.1.1.1', 443)          # IP fisso: nessun DNS di mezzo
DNS_HOST = 'themoviedb.org'            # dominio usato davvero dall'addon
DL_URLS = ('https://speed.cloudflare.com/__down?bytes=%d' % DL_MAX_BYTES,
           'http://cachefly.cachefly.net/1mb.test')

_started = False
_lock = threading.Lock()
_stats = None


def _reset_stats():
    global _stats
    _stats = {'n': 0, 'err': {}, 'ttfb_sum': 0.0, 'ttfb_n': 0,
              'bytes': 0, 'body_s': 0.0, 'slow_dom': '', 'slow_ms': 0.0,
              't0': time.time()}


_reset_stats()


def _log(text):
    try:
        xbmc.log('[NET] %s' % text, xbmc.LOGWARNING)
    except Exception:
        pass


def record(domain, ok, ttfb_ms, total_ms, nbytes, err=''):
    """Chiamata da httptools per OGNI downloadpage (solo se perf_log attivo).
    Accumula il traffico reale dell'addon per il riassunto del probe."""
    try:
        with _lock:
            s = _stats
            s['n'] += 1
            if not ok:
                name = err or 'errore'
                s['err'][name] = s['err'].get(name, 0) + 1
            else:
                if ttfb_ms > 0:
                    s['ttfb_sum'] += ttfb_ms
                    s['ttfb_n'] += 1
                if nbytes > 0 and total_ms > ttfb_ms:
                    s['bytes'] += nbytes
                    s['body_s'] += (total_ms - ttfb_ms) / 1000.0
            if total_ms > s['slow_ms']:
                s['slow_ms'] = total_ms
                s['slow_dom'] = domain
    except Exception:
        pass


def _summary_and_reset():
    with _lock:
        s = _stats
        _reset_stats()
    span = max(int(time.time() - s['t0']), 1)
    if not s['n']:
        return 'http ultimi %ds: nessuna richiesta' % span
    nerr = sum(s['err'].values())
    parts = ['http ultimi %ds: %d richieste' % (span, s['n'])]
    if nerr:
        det = ', '.join('%s=%d' % kv for kv in sorted(s['err'].items()))
        parts.append('%d ERRORI (%s)' % (nerr, det))
    if s['ttfb_n']:
        parts.append('ttfb medio %.0f ms' % (s['ttfb_sum'] / s['ttfb_n']))
    if s['bytes'] and s['body_s'] > 0:
        parts.append('%.1f MB @ %.0f KB/s' % (s['bytes'] / 1048576.0,
                                              s['bytes'] / 1024.0 / s['body_s']))
    if s['slow_dom']:
        parts.append('piu lenta %s %.0f ms' % (s['slow_dom'], s['slow_ms']))
    return ', '.join(parts)


def _tcp_latency():
    """Latenza TCP verso un IP fisso (no DNS). Mediana su 3 tentativi, in ms.
    Ritorna None se non si connette (linea giu' o blocco totale)."""
    times = []
    for _ in range(3):
        t0 = time.time()
        try:
            sk = socket.create_connection(LATENCY_IP, timeout=5)
            times.append((time.time() - t0) * 1000)
            sk.close()
        except Exception:
            pass
    if not times:
        return None
    times.sort()
    return times[len(times) // 2]


def _dns_ms():
    """Tempo di risoluzione DNS del dominio TMDB. None = DNS rotto/bloccato."""
    t0 = time.time()
    try:
        socket.getaddrinfo(DNS_HOST, 443)
        return (time.time() - t0) * 1000
    except Exception:
        return None


def _download_speed():
    """Scarica per al massimo DL_TIMEBOX secondi da un endpoint neutro.
    Ritorna (KB/s, KB letti, secondi) oppure None se nessun endpoint risponde."""
    try:
        from urllib.request import urlopen
    except ImportError:
        from urllib2 import urlopen
    ctx = None
    try:
        ctx = ssl._create_unverified_context()
    except Exception:
        pass
    for url in DL_URLS:
        try:
            t0 = time.time()
            kwargs = {'timeout': 6}
            if ctx is not None and url.startswith('https'):
                kwargs['context'] = ctx
            resp = urlopen(url, **kwargs)
            got = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                got += len(chunk)
                if time.time() - t0 > DL_TIMEBOX or got >= DL_MAX_BYTES:
                    break
            resp.close()
            secs = max(time.time() - t0, 0.001)
            if got > 0:
                return (got / 1024.0 / secs, got / 1024.0, secs)
        except Exception:
            continue
    return None


def probe(reason=''):
    """Esegue una misura completa della linea e la logga con un verdetto."""
    tcp = _tcp_latency()
    dns = _dns_ms()
    dl = _download_speed()

    parts = []
    parts.append('tcp %.0f ms' % tcp if tcp is not None else 'tcp FALLITO')
    parts.append('dns %.0f ms' % dns if dns is not None else 'dns FALLITO')
    if dl is not None:
        parts.append('download %.0f KB/s (%.0f KB in %.1fs)' % dl)
    else:
        parts.append('download FALLITO')

    if tcp is None and dl is None:
        verdict = 'LINEA ASSENTE O BLOCCATA'
    elif dns is None:
        verdict = 'DNS ROTTO/BLOCCATO (linea su, nomi non risolti)'
    elif dl is None:
        verdict = 'HTTP BLOCCATO (tcp ok ma download fallito)'
    elif dl[0] < 100 or (tcp is not None and tcp > 500):
        verdict = 'LINEA LENTA: le attese sono colpa della rete, non del codice'
    elif dl[0] < 400:
        verdict = 'LINEA MEDIOCRE'
    else:
        verdict = 'LINEA OK: se l\'addon e\' lento non e\' la rete'
    tag = (' [%s]' % reason) if reason else ''
    _log('probe%s %s => %s' % (tag, ', '.join(parts), verdict))


def _sys_line():
    """Riga [SYS] una tantum: identikit del device per leggere i log a distanza."""
    try:
        import xbmcaddon
        ver = xbmcaddon.Addon('plugin.video.prippistream').getAddonInfo('version')
    except Exception:
        ver = '?'
    try:
        info = []
        info.append('addon %s' % ver)
        info.append('kodi %s' % xbmc.getInfoLabel('System.BuildVersion'))
        info.append('res %s' % xbmc.getInfoLabel('System.ScreenResolution'))
        info.append('mem libera %s / tot %s' % (
            xbmc.getInfoLabel('System.Memory(free)'),
            xbmc.getInfoLabel('System.Memory(total)')))
        if xbmc.getCondVisibility('System.Platform.Android'):
            info.append('android')
        xbmc.log('[SYS] %s' % ', '.join(info), xbmc.LOGWARNING)
    except Exception:
        pass


def _loop():
    monitor = xbmc.Monitor()
    # lascia respirare il boot prima della prima misura
    if monitor.waitForAbort(15):
        return
    _sys_line()
    probe('avvio')
    while not monitor.waitForAbort(PROBE_INTERVAL):
        try:
            _log(_summary_and_reset())
            probe('periodico')
        except Exception:
            pass


def start():
    """Avvia il probe periodico in un thread demone. Idempotente."""
    global _started
    if _started:
        return
    _started = True
    try:
        t = threading.Thread(target=_loop)
        t.daemon = True
        t.start()
        _log('netdiag attivo: probe linea ogni %ds' % PROBE_INTERVAL)
    except Exception:
        pass
