# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per HD4ME
# ------------------------------------------------------------
# hd4me.net è un'app React su WordPress: i vecchi scraper su HTML non funzionano
# più. Il sito espone però il catalogo e i dati dei film come FILE STATICI JSON
# (nessun login/nonce necessario), che l'app filtra lato-client:
#   - catalogo completo:  /wp-content/themes/mytheme/cache/posts_data.json
#       ogni voce: pid (id), twy/to (titolo IT/orig), y (anno), pa (poster TMDB),
#       iid (imdb), rt (rating)
#   - dati del film:      /wp-content/themes/mytheme/cache/posts/<pid>.json
#       movie.test = link Mega.nz del video (formato nuovo /file/ID#KEY)
# I video sono su Mega.nz → riprodotti in streaming (con seek) da servers/mega.py
# (lib/megaserver). Il link va convertito nel formato "vecchio" #!ID!KEY che il
# megaserver sa parsare.

import json as _json
import re as _re
import time as _time

from core import httptools, support

host = support.config.get_channel_url()
headers = [['Referer', host]]

_CACHE = host.rstrip('/') + '/wp-content/themes/mytheme/cache'

# Catalogo tenuto in memoria per non riscaricare 1.4 MB a ogni ricerca.
_catalog = {'data': None, 'ts': 0}
_CATALOG_TTL = 3600  # 1 ora


def _norm(s):
    s = _re.sub(r'\[/?[A-Za-z][^\]]*\]', '', s or '').strip().lower()
    s = _re.sub(r'[^a-z0-9 ]', '', s)
    return _re.sub(r'\s+', ' ', s).strip()


def _get_catalog():
    now = _time.time()
    if _catalog['data'] is not None and (now - _catalog['ts']) < _CATALOG_TTL:
        return _catalog['data']
    try:
        resp = httptools.downloadpage(_CACHE + '/posts_data.json',
                                      headers={'Referer': host})
        data = _json.loads(resp.data)
        if isinstance(data, list) and data:
            _catalog['data'] = data
            _catalog['ts'] = now
    except Exception as exc:
        support.logger.error('hd4me catalog: %s' % str(exc))
    return _catalog['data'] or []


@support.menu
def mainlist(item):
    # hd4me è usato solo dalla ricerca globale; il menu-browse non è più
    # supportato dal sito React. Voce minima per non rompere il caricamento.
    film = []
    return locals()


def search(item, text):
    support.info(text)
    try:
        q = _norm(text)
        if not q:
            return []
        itemlist = []
        for f in _get_catalog():
            try:
                twy = f.get('twy') or ''
                to = f.get('to') or ''
                if q not in _norm(twy) and q not in _norm(to):
                    continue
                pid = f.get('pid')
                if not pid:
                    continue
                title = twy or to
                pa = f.get('pa') or ''
                thumb = ('https://image.tmdb.org/t/p/w500/%s.jpg' % pa) if pa else ''
                it = item.clone(action='findvideos', title=title, fulltitle=title,
                                contentTitle=title, contentType='movie',
                                url='%s/posts/%s.json' % (_CACHE, pid),
                                thumbnail=thumb, fanart=thumb, infoLabels={})
                if f.get('y'):
                    it.infoLabels['year'] = str(f.get('y'))
                itemlist.append(it)
                if len(itemlist) >= 40:
                    break
            except Exception:
                continue
        support.logger.info('hd4me: %d risultati per %r' % (len(itemlist), text))
        return itemlist
    except Exception:
        import sys
        for line in sys.exc_info():
            support.logger.error("hd4me search except: %s" % line)
        return []


def _mega_to_old(url):
    """Converte il link Mega nuovo (/file/ID#KEY o /folder/ID#KEY) nel formato
    #!ID!KEY / #F!ID!KEY che lib/megaserver sa parsare."""
    url = (url or '').replace('\\/', '/')
    m = _re.match(r'https?://mega\.nz/file/([^#/]+)#(.+)', url)
    if m:
        return 'https://mega.nz/#!%s!%s' % (m.group(1), m.group(2))
    m = _re.match(r'https?://mega\.nz/folder/([^#/]+)#(.+)', url)
    if m:
        return 'https://mega.nz/#F!%s!%s' % (m.group(1), m.group(2))
    return url


def findvideos(item):
    try:
        resp = httptools.downloadpage(item.url, headers={'Referer': host})
        data = getattr(resp, 'data', '') or ''
        mega = ''
        try:
            j = _json.loads(data)
            mega = ((j.get('movie') or {}).get('test') or '') if isinstance(j, dict) else ''
        except Exception:
            pass
        if not mega:
            m = _re.search(r'https://mega\.nz/(?:file|folder)/[A-Za-z0-9_\-]+#[A-Za-z0-9_\-]+', data)
            mega = m.group(0) if m else ''
        if not mega:
            support.logger.info('hd4me findvideos: nessun link Mega in %s' % item.url)
            return []
        return support.server(item, _mega_to_old(mega))
    except Exception as exc:
        support.logger.error('hd4me findvideos: %s' % str(exc))
        return []
