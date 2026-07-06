# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per HD4ME
# ------------------------------------------------------------
# hd4me.net è diventato un'app React su WordPress: i vecchi scraper su HTML
# (<article>) non funzionano più perché la pagina è renderizzata dal JavaScript.
# La ricerca per titolo passa dall'API REST /wp-json/mytheme/v1/text-search
# (accessibile agli ospiti da IP "normali"; l'app non richiede login).
# I contenuti sono su Mega.nz → riprodotti in streaming da servers/mega.py
# (lib/megaserver, con seek). Questa versione è DIAGNOSTICA: chiama l'API e
# salva le risposte grezze in <data_path>/hd4me_dump/ (se la cartella esiste)
# per rifinire il parser dei risultati e il recupero del link Mega.

import json as _json

try:
    import urllib.parse as _up
except ImportError:
    import urllib as _up

from core import httptools, support

host = support.config.get_channel_url()
headers = [['Referer', host]]

_API = host.rstrip('/') + '/wp-json/mytheme/v1'
_API_HEADERS = {
    'Referer': host.rstrip('/') + '/search',
    'Origin': host.rstrip('/'),
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': 'application/json',
}


def _dump(name, text):
    """Salva una risposta grezza in <data_path>/hd4me_dump/ (solo se la cartella
    esiste). Diagnostico per costruire il parser dell'API React/WordPress."""
    try:
        import os
        import time
        d = os.path.join(support.config.get_data_path(), 'hd4me_dump')
        if not os.path.isdir(d):
            return
        with open(os.path.join(d, '%s_%d.txt' % (name, int(time.time() * 1000))),
                  'w', encoding='utf-8') as f:
            f.write(text or '')
    except Exception:
        pass


@support.menu
def mainlist(item):
    film = [('Genere', ['', 'genre'])]
    return locals()


@support.scrape
def genre(item):
    action = 'peliculas'
    blacklist = ['prova ', 'Wall', 'Forum', 'Accedi', 'Lista film']
    patronMenu = r'<li\sid="menu-item.*?href="(?P<url>[^#"]+)">(?P<title>.*?)<'
    return locals()


def search(item, text):
    support.info(text)
    try:
        url = '%s/text-search?%s' % (_API, _up.urlencode({'q': text, 'page': '1'}))
        resp = httptools.downloadpage(url, headers=_API_HEADERS)
        data = getattr(resp, 'data', '') or ''
        _dump('search_%s' % text.replace(' ', '_')[:30],
              'URL: %s\nCODE: %s\n\n%s' % (url, getattr(resp, 'code', '?'), data[:40000]))
        return _parse_search(item, data)
    except Exception:
        import sys
        for line in sys.exc_info():
            support.logger.error("hd4me search except: %s" % line)
        return []


def _parse_search(item, data):
    """Best-effort parse della risposta text-search. I nomi campo definitivi si
    fissano dopo aver letto il primo dump reale dal Kodi dell'utente."""
    itemlist = []
    try:
        j = _json.loads(data)
    except Exception:
        return itemlist
    posts = (j.get('posts') or j.get('results') or j.get('items')
             or j.get('data') or []) if isinstance(j, dict) else (j if isinstance(j, list) else [])
    for p in posts:
        try:
            if not isinstance(p, dict):
                continue
            pid = p.get('id') or p.get('ID') or p.get('post_id') or p.get('postId')
            title = (p.get('title') or p.get('name') or p.get('post_title') or '')
            if isinstance(title, dict):
                title = title.get('rendered') or title.get('raw') or ''
            title = support.scrapertools.htmlclean(title).strip() if title else ''
            thumb = (p.get('poster') or p.get('thumbnail') or p.get('image')
                     or p.get('locandina') or p.get('img') or p.get('cover')
                     or p.get('featured_image') or '')
            link = p.get('link') or p.get('url') or p.get('permalink') or ''
            url = ('%s/%s' % (host.rstrip('/'), pid)) if pid else link
            if not (title and url):
                continue
            it = item.clone(action='findvideos', title=title, fulltitle=title,
                            contentTitle=title, contentType='movie',
                            url=url, thumbnail=thumb, fanart=thumb,
                            infoLabels={})
            it.hd4me_id = str(pid) if pid else ''
            y = p.get('year') or p.get('anno') or p.get('release_year')
            if y:
                it.infoLabels['year'] = str(y)
            tm = p.get('tmdb_id') or p.get('tmdb') or p.get('tmdbId')
            if tm:
                it.infoLabels['tmdb_id'] = tm
            itemlist.append(it)
        except Exception:
            continue
    support.logger.info('hd4me: parsed %d results' % len(itemlist))
    # Poster/metadati via TMDB quando mancano (necessario per la card in ricerca).
    try:
        support.tmdb.set_infoLabels_itemlist(itemlist, seekTmdb=True)
    except Exception:
        pass
    return itemlist


def findvideos(item):
    # Diagnostico: la struttura della pagina-film (dove sta il link Mega) nella
    # nuova app va letta dal dump. Provo gli endpoint candidati e salvo tutto.
    pid = getattr(item, 'hd4me_id', '') or ''
    candidates = []
    if pid:
        candidates = [
            '%s/wp-json/wp/v2/posts/%s' % (host.rstrip('/'), pid),
            '%s/related/%s' % (_API, pid),
        ]
    candidates.append(item.url)
    mega = ''
    for cu in candidates:
        try:
            resp = httptools.downloadpage(cu, headers=_API_HEADERS)
            body = getattr(resp, 'data', '') or ''
            _dump('film_%s' % (pid or 'x'),
                  'URL: %s\nCODE: %s\n\n%s' % (cu, getattr(resp, 'code', '?'), body[:40000]))
            m = support.scrapertools.find_single_match(
                body, r'(https://mega\.nz/(?:file|folder)/[^\s"\'<>]+)')
            if m:
                mega = m.replace('\\/', '/')
                break
        except Exception as exc:
            support.logger.error('hd4me findvideos %s: %s' % (cu, str(exc)))
    if not mega:
        support.logger.info('hd4me findvideos: nessun link Mega trovato (vedi dump)')
        return []
    return support.server(item, mega)
