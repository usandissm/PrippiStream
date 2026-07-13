# -*- coding: utf-8 -*-
# Test headless sul PC: prova che il MOTORE (StreamingCommunity) gira senza Kodi,
# solo con gli shim. Simula ciò che farà la UI nativa via Chaquopy.
#   uso:  py tools/test_headless.py "the office"
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PYROOT = os.path.join(HERE, '..', 'app', 'src', 'main', 'python')
sys.path.insert(0, os.path.abspath(PYROOT))

import bridge

query = sys.argv[1] if len(sys.argv) > 1 else 'the office'


def step(name, fn):
    print('\n=== %s ===' % name)
    try:
        r = fn()
        print('OK')
        return r
    except Exception:
        print('FALLITO:')
        traceback.print_exc()
        return None


def main():
    step('init', lambda: bridge.init())
    step('import canale + metodi', lambda: print(bridge.channel_methods('streamingcommunity')))

    res = step('search "%s"' % query,
               lambda: bridge.channel_call('streamingcommunity', 'search', {}, text=query))
    if res:
        print('risultati: %d' % len(res))
        for it in res[:5]:
            print('  - [%s] %s  (action=%s, url=%s)' % (
                it.get('contentType', it.get('type', '')),
                it.get('title', it.get('fulltitle', ''))[:60],
                it.get('action', ''), (it.get('url', '') or '')[:70]))

    # se il primo risultato è una serie, prova episodios
    if res:
        first = res[0]
        if first.get('action') in ('episodios', 'get_seasons', 'seasons') or first.get('contentType') in ('tvshow', 'season', 'serie'):
            eps = step('episodios sul 1° risultato',
                       lambda: bridge.channel_call('streamingcommunity', 'episodios', first))
            if eps:
                print('episodi: %d' % len(eps))
                for e in eps[:5]:
                    print('  - %s (action=%s, url=%s)' % (
                        e.get('title', '')[:60], e.get('action', ''), (e.get('url', '') or '')[:70]))

                # findvideos sul 1° episodio → sorgenti riproducibili
                ep1 = eps[0]
                srcs = step('findvideos sul 1° episodio',
                            lambda: bridge.channel_call('streamingcommunity', 'findvideos', ep1))
                if srcs:
                    print('sorgenti: %d' % len(srcs))
                    for s in srcs[:6]:
                        print('  - server=%s title=%s url=%s' % (
                            s.get('server', ''), (s.get('title', '') or '')[:40],
                            (s.get('url', '') or '')[:80]))
                    # resolve della 1ª sorgente → dati per il player nativo
                    play = step('resolve 1ª sorgente (dati player)',
                                lambda: bridge.resolve(srcs[0]))
                    if play:
                        print('PLAY -> manifest=%s audio=%s url=%s' % (
                            play.get('manifest_type'), play.get('audio_language'),
                            (play.get('url') or '')[:90]))
                        print('       headers=%s drm=%s' % (
                            play.get('headers'), play.get('drm_type')))


if __name__ == '__main__':
    main()
