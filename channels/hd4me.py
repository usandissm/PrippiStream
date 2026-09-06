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
_catalog = {'data': None, 'idx': None, 'ts': 0}
_CATALOG_TTL = 3600  # 1 ora

# Articoli/preposizioni (it+en) ignorati nel confronto: i titoli hd4me non
# sempre coincidono con quelli correnti ("I pirati DI Silicon Valley" vs
# "i pirati DELLA silicon valley").
_STOPWORDS = {
    'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una',
    'di', 'del', 'dello', 'della', 'dei', 'degli', 'delle',
    'a', 'ad', 'al', 'allo', 'alla', 'ai', 'agli', 'alle',
    'da', 'dal', 'dallo', 'dalla', 'dai', 'dagli', 'dalle',
    'in', 'nel', 'nello', 'nella', 'nei', 'negli', 'nelle',
    'con', 'col', 'coi', 'su', 'sul', 'sullo', 'sulla', 'sui', 'sugli', 'sulle',
    'per', 'tra', 'fra', 'e', 'ed', 'o', 'od',
    'the', 'an', 'of', 'and', 'or', 'to', 'on', 'at',
}


def _norm(s):
    s = _re.sub(r'\[/?[A-Za-z][^\]]*\]', '', s or '').strip().lower()
    s = _re.sub(r'[^a-z0-9 ]', '', s)
    return _re.sub(r'\s+', ' ', s).strip()


def _sig(s):
    """Parole significative di una stringa già normalizzata (via gli stopword)."""
    return [t for t in s.split() if t not in _STOPWORDS]


def _match(q, qsig, tnorm, tsig):
    """True se la query trova il titolo: prima a sottostringa sul testo
    normalizzato, poi confrontando le sole parole significative in sequenza
    (l'ultima parola della query può essere un prefisso, per le digitazioni
    parziali). Il confronto a parole richiede almeno 2 parole significative:
    con una sola ("la la land" -> "land") produrrebbe troppi falsi positivi,
    e i casi a una parola li copre già la sottostringa su titolo IT e orig."""
    if q in tnorm:
        return True
    m = len(qsig)
    if m < 2 or m > len(tsig):
        return False
    last = m - 1
    for i in range(len(tsig) - m + 1):
        for j in range(m):
            tj = tsig[i + j]
            qj = qsig[j]
            if (tj != qj) and not (j == last and tj.startswith(qj)):
                break
        else:
            return True
    return False


def _get_catalog():
    now = _time.time()
    if _catalog['data'] is not None and (now - _catalog['ts']) < _CATALOG_TTL:
        return _catalog['data']
    try:
        resp = httptools.downloadpage(_CACHE + '/posts_data.json',
                                      headers={'Referer': host})
        data = _json.loads(resp.data)
        if isinstance(data, list) and data:
            # Titoli pre-normalizzati una volta sola: il confronto in search
            # gira su ~7000 voci, niente regex ripetute a ogni ricerca.
            idx = []
            for f in data:
                ntwy = _norm(f.get('twy') or '')
                nto = _norm(f.get('to') or '')
                idx.append((f, ntwy, _sig(ntwy), nto, _sig(nto)))
            _catalog['data'] = data
            _catalog['idx'] = idx
            _catalog['ts'] = now
    except Exception as exc:
        support.logger.error('hd4me catalog: %s' % str(exc))
    return _catalog['data'] or []


def _catalog_item(parent, movie):
    """Convert one static catalog row into a normal navigable movie Item."""
    pid = movie.get('pid')
    if not pid:
        return None
    title = movie.get('twy') or movie.get('to') or ''
    if not title:
        return None
    poster_id = movie.get('pa') or ''
    thumb = ('https://image.tmdb.org/t/p/w500/%s.jpg' % poster_id) if poster_id else ''
    result = parent.clone(
        action='findvideos', title=title, fulltitle=title,
        contentTitle=title, contentType='movie', folder=True,
        url='%s/posts/%s.json' % (_CACHE, pid),
        thumbnail=thumb, fanart=thumb, infoLabels={},
    )
    if movie.get('y'):
        result.infoLabels['year'] = str(movie.get('y'))
    if movie.get('rt'):
        result.infoLabels['rating'] = movie.get('rt')
    if movie.get('iid'):
        result.infoLabels['imdb_id'] = str(movie.get('iid'))
    return result


@support.menu
def mainlist(item):
    # Il sito React non espone più pagine HTML navigabili; peliculas() usa il
    # suo catalogo JSON statico, quindi il canale resta sfogliabile anche fuori
    # dalla ricerca globale.
    film = []
    return locals()


def peliculas(item):
    """Catalogo HD4Me paginato, alimentato dallo stesso JSON della web app."""
    data = _get_catalog()
    try:
        page = max(1, int(getattr(item, 'page', 1) or 1))
    except Exception:
        page = 1
    page_size = 40
    start = (page - 1) * page_size
    itemlist = []
    for movie in data[start:start + page_size]:
        result = _catalog_item(item, movie)
        if result:
            itemlist.append(result)
    if start + page_size < len(data):
        itemlist.append(item.clone(
            action='peliculas', title='Pagina successiva',
            page=page + 1, thumbnail='', folder=True,
        ))
    return itemlist


def search(item, text):
    support.info(text)
    try:
        q = _norm(text)
        if not q:
            return []
        qsig = _sig(q)
        itemlist = []
        _get_catalog()
        for f, ntwy, stwy, nto, sto in (_catalog['idx'] or []):
            try:
                twy = f.get('twy') or ''
                to = f.get('to') or ''
                if not (_match(q, qsig, ntwy, stwy) or _match(q, qsig, nto, sto)):
                    continue
                it = _catalog_item(item, f)
                if not it:
                    continue
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


# Classi di risoluzione (in "larghezza" convenzionale, serve solo l'ordine)
# riconosciute nel nome release, es. "Titanic (1997) BDRip 1080p ... 8.49 GB".
_RES_TOKENS = [
    (_re.compile(r'2160p|4k', _re.I), 3840),
    (_re.compile(r'1080p', _re.I), 1920),
    (_re.compile(r'm?720p', _re.I), 1280),
    (_re.compile(r'576p', _re.I), 1000),
    (_re.compile(r'480p', _re.I), 850),
]
_SIZE_RE = _re.compile(r'(\d+(?:[.,]\d+)?)\s*(gb|mb)', _re.I)


def _quality_score(title):
    """(classe risoluzione, MB) estratti dal nome release; (0, 0) se ignoto."""
    t = title or ''
    res = 0
    for rx, width in _RES_TOKENS:
        if rx.search(t):
            res = width
            break
    size = 0.0
    m = _SIZE_RE.search(t)
    if m:
        size = float(m.group(1).replace(',', '.'))
        if m.group(2).lower() == 'gb':
            size *= 1024
    return (res, size)


# Lista A-Z di TUTTI i post (~8200: un post per release/edizione, anche quelli
# fuori dal catalogo di ricerca). Voce: id, t (titolo release con qualità e
# peso), o (1 = link offline). Indicizzata per (titolo-base, anno).
_alphabet = {'idx': None, 'ts': 0}

_TITLE_YEAR_RE = _re.compile(r'^(.*?)\((\d{4})\)')


def _base_year(release_title):
    """Da "Titanic (1997) BDRip 1080p ..." -> ("titanic", "1997")."""
    m = _TITLE_YEAR_RE.match(release_title or '')
    if not m:
        return '', ''
    return _norm(m.group(1)), m.group(2)


def _get_alphabet_index():
    now = _time.time()
    if _alphabet['idx'] is not None and (now - _alphabet['ts']) < _CATALOG_TTL:
        return _alphabet['idx']
    try:
        resp = httptools.downloadpage(_CACHE + '/alphabet.json',
                                      headers={'Referer': host})
        j = _json.loads(resp.data)
        idx = {}
        for g in (j.get('data') or []):
            for it in (g.get('items') or []):
                b, y = _base_year(it.get('t') or '')
                if b and y:
                    idx.setdefault((b, y), []).append(it)
        if idx:
            _alphabet['idx'] = idx
            _alphabet['ts'] = now
    except Exception as exc:
        support.logger.error('hd4me alphabet: %s' % str(exc))
    return _alphabet['idx'] or {}


def _best_edition(post_url, base_title):
    """hd4me pubblica un post per release: lo stesso film può avere più
    edizioni (720p/1080p/REMASTERED...) e il catalogo di ricerca punta a
    quella "canonica", che non sempre è la migliore. Cerca in alphabet.json
    le altre edizioni — stesso titolo base e stesso ANNO (i remake
    condividono il titolo!) — e ritorna il link Mega di quella con
    (risoluzione, peso) maggiore, oppure '' se il canonico resta il migliore."""
    m = _re.search(r'/posts/(\d+)\.json', post_url or '')
    base, year = _base_year(base_title)
    if not m or not base:
        return ''
    pid = m.group(1)
    base_score = _quality_score(base_title)
    cands = []
    for it in _get_alphabet_index().get((base, year), []):
        if str(it.get('id')) == pid or it.get('o'):  # sé stesso / offline
            continue
        score = _quality_score(it.get('t') or '')
        if score > base_score:
            cands.append((score, it))
    # Prova le candidate dalla migliore: deve avere il link Mega e risultare
    # ancora online nel proprio JSON (alphabet può essere stantio).
    for score, it in sorted(cands, key=lambda c: c[0], reverse=True)[:3]:
        try:
            resp = httptools.downloadpage(_CACHE + '/posts/%s.json' % it['id'],
                                          headers={'Referer': host})
            j2 = _json.loads(getattr(resp, 'data', '') or '')
            if not isinstance(j2, dict) or j2.get('online') is False:
                continue
            alt = (j2.get('movie') or {}).get('test') or ''
            if alt:
                support.logger.info('hd4me: edizione migliore di %r -> %r'
                                    % (base_title, j2.get('title')))
                return alt
        except Exception:
            continue
    return ''


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
        mega, title = '', ''
        try:
            j = _json.loads(data)
            if isinstance(j, dict):
                title = j.get('title') or ''
                mega = (j.get('movie') or {}).get('test') or ''
        except Exception:
            pass
        if not mega:
            m = _re.search(r'https://mega\.nz/(?:file|folder)/[A-Za-z0-9_\-]+#[A-Za-z0-9_\-]+', data)
            mega = m.group(0) if m else ''
        # Se esiste un'edizione con risoluzione/peso maggiore, usa quella.
        # Qualsiasi errore qui non deve MAI rompere il play del canonico.
        try:
            alt = _best_edition(item.url, title)
            if alt:
                mega = alt
        except Exception as exc:
            support.logger.info('hd4me best-edition skip: %s' % str(exc))
        if not mega:
            support.logger.info('hd4me findvideos: nessun link Mega in %s' % item.url)
            return []
        return support.server(item, _mega_to_old(mega))
    except Exception as exc:
        support.logger.error('hd4me findvideos: %s' % str(exc))
        return []
