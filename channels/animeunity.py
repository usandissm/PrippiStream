# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per AnimeUnity
# ------------------------------------------------------------

import json, copy, inspect
from core import jsontools, support, httptools, scrapertools
from platformcode import autorenumber, logger, config

# support.dbg()

def findhost(url):
    # url is a stable redirector (e.g. animeunity.to) that redirects to current domain
    # follow_redirects=True so we get the final URL after all hops. verify=False:
    # animeunity edges sometimes serve an incomplete cert chain.
    resp = httptools.downloadpage(url, follow_redirects=True, verify=False)
    final = getattr(resp, 'url', '') or ''
    return final.rstrip('/') if final and not final.startswith('https://animeunity.to') else url.rstrip('/')

host = config.get_channel_url(name='animeunity')  # explicit name avoids inspect-stack mis-detection when imported from netflixhome

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# AnimeUnity is Cloudflare-fronted. A browser keeps the cookies it gets on the
# first page (cf_clearance, XSRF-TOKEN, laravel_session) and replays them on the
# get-animes XHR. We therefore use ONE PERSISTENT session for both the /archivio
# GET and the get-animes POST so the cookie jar carries over — the old code used
# two separate requests and forwarded cookies by hand, which Cloudflare rejects
# (403). The session mounts the same DoH + browser-cipher adapter as the rest of
# the addon (so blocked DNS still resolves) with verify disabled (animeunity
# edges sometimes serve an incomplete cert chain). Everything is lazy so importing
# the module triggers no network.
_session = None
_headers = None        # headers for the get-animes XHR (built after a successful init)
_archivio_data = None  # raw /archivio HTML (genres/years parse it)


def _get_session():
    global _session
    if _session is not None:
        return _session
    from lib import requests
    s = requests.session()
    try:
        from core import resolverdns
        netloc = host.split('://', 1)[-1].split('/', 1)[0]
        s.mount('https://', resolverdns.CipherSuiteAdapter(
            domain=netloc, override_dns=config.get_setting('resolver_dns'),
            verify_ssl=False))
    except Exception as exc:
        logger.error('[AnimeUnity] adapter mount failed: %s' % str(exc))
    s.verify = False
    s.headers.update({'User-Agent': _UA, 'Accept-Language': 'it-IT,it;q=0.9'})
    _session = s
    return s


def _reset_session():
    global _session, _headers, _archivio_data
    _session = None
    _headers = None
    _archivio_data = None


def _refresh_host():
    """Re-discover the current AnimeUnity domain via the findhost redirector and
    update the module-level *host*. Called lazily on a fetch failure so a changed
    domain self-heals on the next attempt (no network at import time)."""
    global host
    try:
        new_host = config.get_channel_url(findhost, name='animeunity', forceFindhost=True)
        if new_host:
            if new_host != host:
                logger.info('[AnimeUnity] host re-discovered: %s' % new_host)
            host = new_host
            _reset_session()   # rebuild the session against the new domain
            return True
    except Exception as exc:
        logger.error('[AnimeUnity] host refresh failed: %s' % str(exc))
    return False


def _ensure_init(_retry=True):
    """GET /archivio once on the persistent session to grab the CSRF token and the
    Cloudflare/session cookies (kept in the session jar for the XHR). Self-healing:
    on failure it re-discovers the domain via findhost and retries once. Leaves
    _headers None (falsy) on terminal failure so a later call retries instead of
    caching the broken state."""
    global _headers, _archivio_data
    if _headers:   # truthy only after a successful init
        return
    try:
        s = _get_session()
        r = s.get(host + '/archivio', timeout=20)
        data = r.text or ''
        token = support.match(data, patron='name="csrf-token" content="([^"]+)"').match
        logger.info('[AnimeUnity] /archivio code=%s csrf=%s cookies=%s len=%d'
                    % (r.status_code, 'yes' if token else 'NO',
                       [c.name for c in s.cookies], len(data)))
        if r.status_code >= 400 or not token:
            raise Exception('archivio code=%s csrf=%s' % (r.status_code, bool(token)))
        _archivio_data = data
        _headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'X-CSRF-TOKEN': token,
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': host + '/archivio',
            'Origin': host,
        }
    except Exception as exc:
        logger.error('[AnimeUnity] _ensure_init failed: %s' % str(exc))
        if _retry and _refresh_host():
            return _ensure_init(_retry=False)
        _headers = None
        _archivio_data = None


@support.menu
def mainlist(item):
    top =  [('Ultimi Episodi', ['', 'news'])]

    menu = [('Anime {bullet bold}',['', 'menu', {}, 'tvshow']),
            ('Film {submenu}',['', 'menu', {'type': 'Movie'}]),
            ('TV {submenu}',['', 'menu', {'type': 'TV'}, 'tvshow']),
            ('OVA {submenu} {tv}',['', 'menu', {'type': 'OVA'}, 'tvshow']),
            ('ONA {submenu} {tv}',['', 'menu', {'type': 'ONA'}, 'tvshow']),
            ('Special {submenu} {tv}',['', 'menu', {'type': 'Special'}, 'tvshow'])]
    search =''
    return locals()

def menu(item):
    item.action = 'peliculas'
    ITA = copy.copy(item.args)
    ITA['title'] = '(ita)'
    InCorso = copy.copy(item.args)
    InCorso['status'] = 'In Corso'
    Terminato = copy.copy(item.args)
    Terminato['status'] = 'Terminato'
    itemlist = [item.clone(title=support.typo('Tutti','bold')),
                item.clone(title=support.typo('ITA','bold'), args=ITA),
                item.clone(title=support.typo('Genere','bold'), action='genres'),
                item.clone(title=support.typo('Anno','bold'), action='years')]
    if item.contentType == 'tvshow':
        itemlist += [item.clone(title=support.typo('In Corso','bold'), args=InCorso),
                     item.clone(title=support.typo('Terminato','bold'), args=Terminato)]
    itemlist +=[item.clone(title=support.typo('Cerca...','bold'), action='search', thumbnail=support.thumb('search'))]
    return itemlist


def genres(item):
    support.info()
    _ensure_init()
    itemlist = []

    genres = json.loads(support.match(_archivio_data, patron='genres="([^"]+)').match.replace('&quot;','"'))

    for genre in genres:
        item.args['genres'] = [genre]
        itemlist.append(item.clone(title=support.typo(genre['name'],'bold'), action='peliculas'))
    return support.thumb(itemlist)

def years(item):
    support.info()
    _ensure_init()
    itemlist = []

    from datetime import datetime
    next_year = datetime.today().year + 1
    oldest_year = int(support.match(_archivio_data, patron='anime_oldest_date="([^"]+)').match)

    for year in list(reversed(range(oldest_year, next_year + 1))):
        item.args['year']=year
        itemlist.append(item.clone(title=support.typo(year,'bold'), action='peliculas'))
    return itemlist


def search(item, text):
    support.info('search', item)
    if not item.args:
        item.args = {'title':text}
    else:
        item.args['title'] = text
    item.search = text

    try:
        return peliculas(item)
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            support.info('search log:', line)
        return []


def newest(categoria):
    support.info(categoria)
    itemlist = []
    item = support.Item()
    item.url = host

    try:
        itemlist = news(item)

        if itemlist[-1].action == 'news':
            itemlist.pop()
    # Continua la ricerca in caso di errore
    except:
        import sys
        for line in sys.exc_info():
            support.info(line)
        return []

    return itemlist

def news(item):
    support.info()
    _ensure_init()
    item.contentType = 'episode'
    itemlist = []

    fullJs = json.loads(support.match(httptools.downloadpage(item.url).data, headers=_headers, patron=r'items-json="([^"]+)"').match.replace('&quot;','"'))
    js = fullJs['data']

    for it in js:
        if it.get('anime', {}).get('title') or it.get('anime', {}).get('title_eng'):
            title_name = it['anime']['title'] if it.get('anime', {}).get('title') else it['anime']['title_eng']
            pattern = r'[sS](?P<season>\d+)[eE](?P<episode>\d+)'
            match = scrapertools.find_single_match(it['file_name'], pattern)
            full_episode = ''
            if match:
                season, episode = match
                full_episode = ' - S' + season + ' E' + episode
            else:
                pattern = r'[._\s]Ep[._\s]*(?P<episode>\d+)'
                episode = scrapertools.find_single_match(it['file_name'], pattern)
                if episode:
                    full_episode = ' - E' + episode
            itemlist.append(
                item.clone(title = support.typo(title_name + full_episode, 'bold'),
                           fulltitle = it['anime']['title'],
                           thumbnail = it['anime']['imageurl'],
                           forcethumb = True,
                           scws_id = it.get('scws_id', ''),
                           url = '{}/anime/{}-{}'.format(item.url, it['anime']['id'],it['anime']['slug']),
                           plot = it['anime']['plot'],
                           action = 'findvideos')
            )
    if 'next_page_url' in fullJs:
        itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'),thumbnail=support.thumb(), url=fullJs['next_page_url']))
    return itemlist


def peliculas(item, _retry=True):
    support.info()
    _ensure_init()
    itemlist = []
    if not _headers:
        logger.error('[AnimeUnity] peliculas: init failed (no CSRF/session)')
        return itemlist

    page = item.page if item.page else 0
    item.args['offset'] = page * 30

    order = support.config.get_setting('order', item.channel)
    if order:
        order_list = [ "Standard", "Lista A-Z", "Lista Z-A", u"Popolarità", "Valutazione" ]
        item.args['order'] = order_list[order]

    payload = json.dumps(item.args)
    records = None
    code = '?'
    try:
        s = _get_session()
        r = s.post(host + '/archivio/get-animes', data=payload, headers=_headers, timeout=20)
        code = r.status_code
        if code < 400:
            jdata = r.json()
            records = jdata.get('records') if isinstance(jdata, dict) else None
    except Exception as exc:
        logger.error('[AnimeUnity] get-animes request failed: %s' % str(exc)[:160])
    if not records:
        logger.error('[AnimeUnity] peliculas: no records (code=%s)' % code)
        if _retry:
            # blocked/stale session → rebuild it (and re-discover the domain via
            # _ensure_init's findhost fallback), then retry once.
            _reset_session()
            return peliculas(item, _retry=False)
        return itemlist

    for it in records:
        if not it['title']:
            it['title'] = it['title_eng']

        lang = support.match(it['title'], patron=r'\(([It][Tt][Aa])\)').match
        title = support.re.sub(r'\s*\([^\)]+\)', '', it['title'])

        if 'ita' in lang.lower():
            language = 'ITA'
        else:
            language = 'Sub-ITA'

        if title:
            itm = item.clone(title=support.typo(title,'bold') + support.typo(language,'_ [] color std') + (support.typo(it['title_eng'],'_ ()') if it['title_eng'] else ''))
        else:
            itm = item.clone(title=support.typo(it['title_eng'],'bold') + support.typo(language,'_ [] color std'))
        itm.contentLanguage = language
        itm.type = it['type']
        itm.thumbnail = it['imageurl']
        itm.plot = it['plot']
        itm.url = '{}/anime/{}-{}'.format(host, it.get('id'), it.get('slug'))

        if it['episodes_count'] == 1:
            itm.contentType = 'movie'
            itm.fulltitle = itm.show = itm.contentTitle = title
            itm.contentSerieName = ''
            itm.action = 'findvideos'

        else:
            itm.api_ep_url = '{}/info_api/{}/'.format(host, it.get('id'))
            itm.contentType = 'tvshow'
            itm.contentTitle = ''
            itm.fulltitle = itm.show = itm.contentSerieName = title
            itm.action = 'episodios'

        itemlist.append(itm)

    autorenumber.start(itemlist)
    if len(itemlist) >= 30:
        itemlist.append(item.clone(title=support.typo(support.config.get_localized_string(30992), 'color std bold'), thumbnail=support.thumb(), page=page + 1))

    return itemlist

def episodios(item):
    support.info()
    _ensure_init()
    itemlist = []
    title = 'Parte' if item.type.lower() == 'movie' else 'Episodio'
    start=1
    limit=120

    # Ensure URLs are absolute regardless of how the item was constructed
    api_url = item.api_ep_url if (item.api_ep_url or '').startswith('http') else host.rstrip('/') + (item.api_ep_url or '')
    item_url = item.url if (item.url or '').startswith('http') else host.rstrip('/') + (item.url or '')

    while True:
        full = json.loads(httptools.downloadpage('{}1?start_range={}&end_range={}'.format(api_url, start, start + (limit -1)), headers=_headers).data)
        count = full['episodes_count']
        episodes = full['episodes']
        for it in episodes:
            itemlist.append(
                item.clone(title=support.typo('{}. {} {}'.format(it['number'], title, it['number']), 'bold'),
                       episode = it['number'],
                       fulltitle=item.title,
                       show=item.title,
                       contentTitle='',
                       contentSerieName=item.contentSerieName,
                       thumbnail=item.thumbnail,
                       plot=item.plot,
                       action='findvideos',
                       contentType='episode',
                       url = '{}/{}'.format(item_url, it['id'])
                      )
            )
        if count > start:
            start = start + limit
        else:
            break

    if inspect.stack(0)[1][3] not in ['find_episodes']:
        autorenumber.start(itemlist, item)
    support.videolibrary(itemlist, item)

    return itemlist


def findvideos(item):
    from core import channeltools
    itemlist = [item.clone(title=channeltools.get_channel_parameters(item.channel)['title'],
                           url=item.url, server='streamingcommunityws')]
    return support.server(item, itemlist=itemlist, referer=False)
