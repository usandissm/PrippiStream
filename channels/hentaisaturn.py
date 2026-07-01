# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per HentaiSaturn (hentaisaturn.tv) — famiglia "saturn"
#
# Struttura (verificata live 2026-07-01):
#   - Elenco/filtro:   /filter               (card class="hs-card", ?page=N)
#   - Generi:          /genres  ->  /filter?categories=<id>
#   - A-Z:             /az-list
#   - Novità:          /newest
#   - In corso:        /ongoing
#   - Top:             /toplist
#   - Ricerca:         GET /api/search?q=<q>  (JSON: title,url,poster,year,type,genres,status)
#   - Serie -> episodi: pagina /hentai/<slug>  ->  link /episode/<slug>/ep-N
#   - Episodio -> player: /hentai/<slug>/ep-N  (iframe interno + mirror Streamtape)
#   - Video MAX QUALITÀ (server interno "HentaiSaturn"):
#       watch page -> iframe play.hentaisaturn.tv/embed/<id>?token=<k>&expires=<e>
#       GET /embed/<id>/playlist?token=<k>&expires=<e>  -> {"d": <blob>}
#       Cl(blob, k) = XOR(base64_decode(blob), k)  -> URL MP4 diretto (server.hcontent.net, seekable)
#     + mirror Streamtape (risolto dai server resolver dell'addon).
# ------------------------------------------------------------

import base64
import json as _json

from core import httptools, scrapertools, support
from core.item import Item
from platformcode import config, logger

__channel__ = 'hentaisaturn'

# Host is AUTO-UPDATING: read from channels.json (kept current by the addon's
# domain-update process, like the other "saturn" channels), with a hard fallback.
try:
    host = support.config.get_channel_url() or 'https://www.hentaisaturn.tv'
except Exception:
    host = 'https://www.hentaisaturn.tv'
host = host.rstrip('/')

# The player lives on the play.<domain> subdomain — derive it from the current
# host so it tracks the domain automatically too.
import re as _re_host
_m = _re_host.search(r'https?://(?:www\.)?([^/]+)', host)
play_host = 'https://play.' + (_m.group(1) if _m else 'hentaisaturn.tv')

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36')
headers = {'User-Agent': _UA, 'Referer': host + '/'}


# ── low-level helpers ────────────────────────────────────────────────────────
def _get(url, extra_headers=None):
    """GET *url* and return the response body (str).  extra_headers (list of
    [key, value]) OVERRIDE the base headers by key — the playlist endpoint needs
    its own Referer, so a second Referer must replace, not duplicate, the base one."""
    hh = dict(headers)
    if extra_headers:
        for k, v in extra_headers:
            hh[k] = v
    return httptools.downloadpage(url, headers=hh, follow_redirects=True).data or ''


def _abs(u):
    if not u:
        return u
    if u.startswith('http'):
        return u
    return host + u if u.startswith('/') else host + '/' + u


def _cl_decode(blob, key):
    """Replica di Cl() del player: XOR(base64_decode(blob), key-ripetuta)."""
    raw = base64.b64decode(blob)
    if isinstance(key, str):
        key = key.encode('latin1')
    return ''.join(chr(raw[i] ^ key[i % len(key)]) for i in range(len(raw)))


# ── menu ─────────────────────────────────────────────────────────────────────
def mainlist(item):
    support.info()
    itemlist = [
        Item(channel=__channel__, action='peliculas', title=support.typo('Elenco', 'bold'),
             url=host + '/filter', thumbnail=support.thumb()),
        Item(channel=__channel__, action='generi', title=support.typo('Generi', 'bold'),
             url=host + '/genres', thumbnail=support.thumb('genres')),
        Item(channel=__channel__, action='peliculas', title=support.typo('A-Z', 'bold'),
             url=host + '/az-list', thumbnail=support.thumb('az')),
        Item(channel=__channel__, action='peliculas', title=support.typo('Novità', 'bold'),
             url=host + '/newest', thumbnail=support.thumb('new')),
        Item(channel=__channel__, action='peliculas', title=support.typo('In corso', 'bold'),
             url=host + '/ongoing', thumbnail=support.thumb('ongoing')),
        Item(channel=__channel__, action='peliculas', title=support.typo('Più votati', 'bold'),
             url=host + '/toplist', thumbnail=support.thumb('top')),
        Item(channel=__channel__, action='search', title=support.typo('Cerca...', 'bold'),
             thumbnail=support.thumb('search')),
    ]
    return itemlist


# ── generi ───────────────────────────────────────────────────────────────────
def generi(item):
    support.info()
    itemlist = []
    data = _get(item.url)
    seen = set()
    # The genre CARDS carry the name in the title="" attribute (e.g.
    #   <a href="/filter?categories=61" class="hs-gcard group" title="Uncensored">).
    # An older markup exposed only the ~17 "pill" tags whose name was the text
    # content — matching by title="" now yields the FULL list (62 genres incl.
    # Uncensored, Futanari, Harem, Loli, NTR, Tentacle, Yaoi, Yuri…). The pill
    # links have NO title attribute, so requiring one selects exactly the cards.
    matches = scrapertools.find_multiple_matches(
        data, r'/filter\?categories=(\d+)"[^>]*\stitle="([^"]+)"')
    if not matches:
        # Fallback to the legacy text-content markup if the site is redesigned.
        matches = scrapertools.find_multiple_matches(
            data, r'/filter\?categories=(\d+)"[^>]*>\s*([A-Za-z][^<]+?)\s*<')
    for gid, name in matches:
        gid = gid.strip()
        name = name.strip()
        if not gid or gid in seen or not name:
            continue
        seen.add(gid)
        itemlist.append(Item(channel=__channel__, action='peliculas',
                             title=support.typo(name, 'bold'),
                             url='%s/filter?categories=%s' % (host, gid)))
    itemlist.sort(key=lambda it: it.title.lower())
    support.thumb(itemlist, genre=True)
    return itemlist


# ── ricerca (JSON API) ─────────────────────────────────────────────────────────
def search(item, texto):
    support.info(texto)
    try:
        return _search_items(texto)
    except Exception:
        import sys
        for line in sys.exc_info():
            logger.error('[HentaiSaturn] search: %s' % str(line))
        return []


def _search_items(texto):
    import urllib.parse as _up
    url = '%s/api/search?q=%s' % (host, _up.quote(texto))
    raw = _get(url, extra_headers=[['X-Requested-With', 'XMLHttpRequest'],
                                   ['Accept', 'application/json']])
    itemlist = []
    try:
        data = _json.loads(raw)
    except Exception:
        return itemlist
    results = data if isinstance(data, list) else (
        data.get('results') or data.get('data') or data.get('hits') or [])
    for r in results:
        if not isinstance(r, dict):
            continue
        title = (r.get('title') or '').strip()
        url = _abs(r.get('url') or '')
        if not title or '/hentai/' not in url:
            continue
        itemlist.append(_make_serie(title, url, r.get('poster'),
                                    year=r.get('year'), typ=r.get('type')))
    return itemlist


# ── elenco / filtro (card scraping) ────────────────────────────────────────────
_CARD = (r'<a href="(?P<url>/hentai/[^"]+)" class="hs-card.*?'
         r'<img src="(?P<thumb>[^"]+)" alt="(?P<title>[^"]+)"'
         r'(?:.*?hs-card__tag hs-card__tag--p">(?P<type>[^<]+)<)?'
         r'(?:.*?hs-card__score">.*?(?P<score>[0-9.]+)\s*</span>)?')


def peliculas(item):
    support.info()
    itemlist = []
    data = _get(item.url)
    for m in support.re.finditer(_CARD, data, support.re.DOTALL):
        url = _abs(m.group('url'))
        # a series URL is /hentai/<slug> with NO trailing /ep-N
        if support.re.search(r'/ep-\d+$', url):
            continue
        it = _make_serie(m.group('title'), url, m.group('thumb'),
                         typ=m.groupdict().get('type'), score=m.groupdict().get('score'))
        itemlist.append(it)

    # Pagination: ?page=N — stop when a page yields nothing.
    if itemlist:
        base = item.url.split('#')[0]
        cur = item.page if item.page else 1
        nxt = int(cur) + 1
        sep = '&' if '?' in base else '?'
        page_url = '%s%spage=%d' % (support.re.sub(r'[?&]page=\d+', '', base), sep, nxt)
        itemlist.append(Item(channel=__channel__, action='peliculas',
                             title=support.typo(config.get_localized_string(30992), 'color std bold'),
                             url=page_url, page=nxt, thumbnail=support.thumb()))
    return itemlist


def _make_serie(title, url, thumb, year=None, typ=None, score=None):
    it = Item(channel=__channel__, action='episodios', url=url,
              contentType='tvshow', contentSerieName=title, fulltitle=title,
              show=title, thumbnail=_abs(thumb) if thumb else '',
              title=support.typo(title, 'bold'))
    # Everything on HentaiSaturn is episode-based (/episode/<slug>/ep-N), even the
    # "Movie"/"OVA" entries — always route through episodios so the episode picker
    # works and playback is consistent.
    try:
        if year:
            it.infoLabels['year'] = str(year)
        if score:
            it.infoLabels['rating'] = float(score)
    except Exception:
        pass
    return it


# ── episodi ────────────────────────────────────────────────────────────────────
def episodios(item):
    support.info()
    itemlist = []
    data = _get(item.url)
    eps = {}
    for url, num in scrapertools.find_multiple_matches(
            data, r'href="(/episode/[^"]+/ep-(\d+))"'):
        try:
            n = int(num)
        except ValueError:
            continue
        # watch page = /hentai/<slug>/ep-N  (same path, /episode -> /hentai)
        watch = _abs(url).replace('/episode/', '/hentai/')
        eps[n] = watch
    for n in sorted(eps):
        itemlist.append(Item(channel=__channel__, action='findvideos', url=eps[n],
                             title=support.typo('Episodio %d' % n, 'bold'),
                             contentType='episode',
                             fulltitle=item.fulltitle, show=item.show,
                             contentSerieName=item.contentSerieName,
                             contentEpisodeNumber=n, thumbnail=item.thumbnail))
    support.videolibrary(itemlist, item)
    return itemlist


# ── video (max qualità: MP4 interno + mirror Streamtape) ───────────────────────
def findvideos(item):
    support.info()
    itemlist = []
    watch = item.url if '/ep-' in item.url else item.url
    data = _get(watch)

    # 1) Server interno "HentaiSaturn" → MP4 diretto (massima qualità).
    m = support.re.search(
        r'play\.hentaisaturn\.tv/embed/(\d+)\?token=([^&"\']+)&(?:amp;)?expires=(\d+)', data)
    if m:
        try:
            vid, token, expires = m.group(1), m.group(2), m.group(3)
            pl = _get('%s/embed/%s/playlist?token=%s&expires=%s' % (play_host, vid, token, expires),
                      extra_headers=[['Referer', '%s/embed/%s?token=%s&expires=%s'
                                      % (play_host, vid, token, expires)],
                                     ['Accept', 'application/json']])
            blob = _json.loads(pl).get('d')
            decoded = _cl_decode(blob, token) if blob else ''
            for vurl in support.re.findall(r'https?://[^\s"\']+\.(?:mp4|m3u8)[^\s"\']*', decoded):
                itemlist.append(item.clone(action='play', server='directo',
                                           title='HentaiSaturn', quality='HD',
                                           url=vurl, video_url=vurl))
        except Exception as exc:
            logger.error('[HentaiSaturn] internal resolve: %s' % str(exc)[:160])

    # 2) Mirror Streamtape (risolto dai server dell'addon).
    st = scrapertools.find_single_match(data, r'(https?://streamtape\.com/[ev]/[A-Za-z0-9]+)')
    links = [st] if st else []

    return support.server(item, data=links, itemlist=itemlist)


def play(item):
    # Il server interno "directo" ha già l'URL MP4 pronto.
    if getattr(item, 'server', '') == 'directo' or getattr(item, 'video_url', ''):
        item.url = getattr(item, 'video_url', '') or item.url
        return [item]
    return [item]
