# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Canale per Mediaset Play
# ------------------------------------------------------------
import functools
import re
import time
from platformcode import logger, config
import uuid, datetime, xbmc

import requests, sys
from core import jsontools, support, httptools

if sys.version_info[0] >= 3:
    from concurrent import futures
    from urllib.parse import urlencode, quote
else:
    from concurrent_py2 import futures
    from urllib import urlencode, quote

host = 'https://www.mediasetplay.mediaset.it'
public_host = 'https://mediasetinfinity.mediaset.it'
loginUrl = 'https://api-ott-prod-fe.mediaset.net/PROD/play/idm/anonymous/login/v2.0'
graph_url = 'https://mediasetplay.api-graph.mediaset.it'
graph_search_hash = '0cbec614877306e7f2814d2c16163d510c8fc87f1677bc34f95f4f55dc027dce'
web_app_name = 'web//mediasetplay-web/1.3.0-h1-8d023f0'
web_app_version = '1.3.0-h1'

clientid = 'f66e2a01-c619-4e53-8e7c-4761449dd8ee'


loginData = {"client_id": clientid, "platform": "pc", "appName": web_app_name}
sessionUrl = "https://api.one.accedo.tv/session?appKey=59ad346f1de1c4000dfd09c5&uuid={uuid}&gid=default"

session = requests.Session()
session.request = functools.partial(session.request, timeout=httptools.HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT)
session.headers.update({'Content-Type': 'application/json', 'User-Agent': support.httptools.get_user_agent(), 'Referer': host})

entry = 'https://api.one.accedo.tv/content/entry/{id}?locale=it'
entries = 'https://api.one.accedo.tv/content/entries?id={id}&locale=it'

# login anonimo
res = session.post(loginUrl, json=loginData, verify=False)
Token = res.json()['response']['beToken']
sid = res.json()['response']['sid']
session.headers.update({'authorization': 'Bearer ' + Token})

# sessione
#sessionKey = session.get(sessionUrl.format(uuid=str(uuid.uuid4())), verify=False).json()['sessionKey']
#session.headers.update({'x-session': sessionKey})

pagination = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100][config.get_setting('pagination', 'mediasetplay')]


@support.menu
def mainlist(item):
    top =  [('Dirette {bold}', ['', 'live'])]

    menu = [('Film Più Visti {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmPiuVisti24H'}, 'movie']),
            ('Film ultimi arrivi {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmUltimiArrivi'}, 'movie']),
            ('Film Da Non Perdere {submenu}', ['/cinema', 'peliculas', {'uxReference':'filmClustering'}, 'movie']),
            ('Fiction e Serie Tv del momento {submenu}', ['/fiction', 'peliculas', {'uxReference':'fictionSerieTvDelMomento'}, 'tvshow']),
            ('Serie TV Piu Viste {submenu}', ['/fiction', 'peliculas', {'uxReference':'serieTvPiuViste24H'}, 'tvshow']),
            ('Soap del momento {submenu}', ['/cinema', 'peliculas', {'uxReference':'fictionSerieTvParamsGenre', 'params': 'genre≈Soap opera'}, 'tvshow']),
            ('Programmi TV Prima serata{ submenu}', ['/programmitv', 'peliculas', {'uxReference':'stagioniPrimaSerata'}, 'tvshow']),
            ('Programmi TV Daytime{ submenu}', ['/programmitv', 'peliculas', {'uxReference':'stagioniDaytime'}, 'tvshow']),
	    ('Talent e reality {submenu}', ['/talent', 'peliculas', {'uxReference':'multipleBlockProgrammiTv', 'userContext' :'iwiAeyJwbGF0Zm9ybSI6IndlYiJ9Aw'}, 'tvshow']),
            ('Kids Evergreen {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsMediaset' }, 'undefined']),
            ('Kids Boing {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsBoing' }, 'undefined']),
            ('Kids Cartoonito {submenu}', ['/kids', 'peliculas', {'uxReference':'kidsCartoonito' }, 'undefined']),
            ('Documentari più visti {submenu}', ['/documentari', 'peliculas', {'uxReference': 'documentariPiuVisti24H'}, 'undefined']),
            ]

    search = ''
    return locals()

def menu(item):
    logger.debug()
    itemlist = []
    res = get_from_id(item)
    for it in res:
        if 'uxReference' in it:
            itemlist.append(item.clone(title=support.typo(it['title'], 'bullet bold'),
                            url= it['landingUrl'],
                            args={'uxReference':it.get('uxReferenceV2', ''), 'params':it.get('uxReferenceV2Params', ''), 'feed':it.get('feedurlV2','')},
                            action='peliculas'))
    return itemlist


def live(item):
    itemlist = []

    epg_url = "https://api-ott-prod-fe.mediaset.net/PROD/play/feed/allListingFeedEpg/v2.0?byListingTime={0}~{0}&byCallSign={1}"
    res = session.get('https://static3.mediasetplay.mediaset.it/apigw/nownext/nownext.json').json()['response']
    allguide = res['listings']
    stations = res['stations']

    def find_high_res_image(arts, prefix):
        return max(
            (item for key, item in arts.items() if key.startswith(prefix)),
            key=lambda x: x.get('width', 0),
            default=None
        )
    
    def itArt(it):
        current_time_millis = int(time.time() * 1000)
        arts = ""
        try:
            response = session.get(epg_url.format(current_time_millis, it['callSign'])).json()
            listings = response.get('response', {}).get('entries', [{}])[0].get('listings', [{}])

            for listing in listings: # for some reason, sometimes, the API returns multiple listings
                if listing['startTime'] < current_time_millis < listing['endTime']:
                    arts = listing.get('program', {}).get('thumbnails', {})
                    break

            poster = find_high_res_image(arts, "image_horizontal_cover") or find_high_res_image(arts, "image_keyframe_poster")

            it['fanart'] = poster.get('url')
        except Exception as e:
            logger.debug(f"could not get art for {it['callSign']}: {e}")
            it['fanart'] = ""
    
    with futures.ThreadPoolExecutor() as executor:
        itlist = [executor.submit(itArt, it) for it in stations.values()]
        for res in futures.as_completed(itlist):
            pass

    for it in stations.values():
        logger.debug(jsontools.dump(it))
        plot = ''
        title = it['title']
        url = 'https:' + it['mediasetstation$pageUrl']
        if 'SVOD' in it['mediasetstation$channelsRights']: continue
        thumb = it.get('thumbnails',{}).get('channel_logo-100x100',{}).get('url','')

        if it['callSign'] in allguide:

            guide = allguide[it['callSign']]
            plot = '[B]{}[/B]\n{}'.format(guide.get('currentListing', {}).get('mediasetlisting$epgTitle', ''),guide.get('currentListing', {}).get('description', ''))
            if 'nextListing' in guide.keys():
                plot += '\n\nA Seguire:\n[B]{}[/B]\n{}'.format(guide.get('nextListing', {}).get('mediasetlisting$epgTitle', ''),guide.get('nextListing', {}).get('description', ''))
            itemlist.append(item.clone(title=support.typo(title, 'bold'),
                                       fulltitle=title, callSign=it['callSign'],
                                    #    urls=[guide['publicUrl']],
                                       plot=plot,
                                       url=url,
                                       action='findvideos',
                                       thumbnail=thumb,
                                       fanart = it['fanart'],
                                       forcethumb=True))

    itemlist.sort(key=lambda it: support.channels_order.get(it.fulltitle, 999))
    support.thumb(itemlist, live=True)
    return itemlist


def _graph_items(data):
    """Extract unique content cards from the current search response."""
    found = []
    seen = set()

    def walk(value):
        if isinstance(value, dict):
            kind = value.get('__typename')
            guid = value.get('guid')
            if kind in ('SeriesItem', 'VideoItem') and guid and guid not in seen:
                seen.add(guid)
                found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return found


def _graph_image(card, image_type, width, height):
    image = next((value for value in (card.get('cardImages') or [])
                  if value.get('type') == image_type
                  or value.get('sourceType') == image_type), None)
    if not image or not image.get('engine') or not image.get('id'):
        return ''
    url = ('https://img-prod-api2.mediasetplay.mediaset.it/api/images/'
           '{}/v5/ita/{}/{}/{}/{}').format(
               image['engine'], image['id'],
               image.get('sourceType') or image_type, width, height)
    if image.get('r'):
        url += '?r=' + str(image['r'])
    return url


def _season_number(season, fallback):
    value = ((season.get('cardLink') or {}).get('value') or '').lower()
    match = re.search(r'(?:stagione|season)[-_]?(\d+)', value)
    return int(match.group(1)) if match else fallback


def _free_media_selector(content_id):
    """Return the selector only when the anonymous user can really play it."""
    payload = {
        'contentId': content_id, 'streamType': 'VOD',
        'delivery': 'Streaming', 'createDevice': 'true',
        'overrideAppName': web_app_name,
    }
    try:
        data = session.post(
            'https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0?sid=' + sid,
            json=payload,
        ).json()
        return (data.get('response') or {}).get('mediaSelector')
    except Exception:
        return None


def search(item, text):
    """Search Mediaset Infinity through its current GraphQL catalogue."""
    query = str(text or '').strip()
    if not query:
        return []
    variables = {
        'after': None, 'first': 24, 'property': 'search', 'query': query,
        'uxReference': 'main', 'variant': None,
    }
    extensions = {
        'persistedQuery': {'version': 1, 'sha256Hash': graph_search_hash}
    }
    headers = {
        'x-m-platform': 'WEB', 'x-m-property': 'MPLAY',
        'x-m-app-version': web_app_version,
        'User-Agent': support.httptools.get_user_agent(),
        'Referer': public_host + '/',
    }
    try:
        response = requests.get(
            graph_url,
            params={'extensions': jsontools.dump(extensions),
                    'variables': jsontools.dump(variables)},
            headers=headers,
            timeout=httptools.HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT,
        )
        response.raise_for_status()
        cards = _graph_items(response.json())
    except Exception as exc:
        logger.error('[mediasetplay] GraphQL search failed: %s' % str(exc))
        return []

    itemlist = []
    for card in cards:
        kind = card.get('__typename')
        if kind == 'VideoItem' and (card.get('editorialType') or '').lower() != 'movie':
            continue
        title = card.get('cardTitle') or ''
        if not title:
            continue
        link = (card.get('cardLink') or {}).get('value') or public_host
        if kind == 'SeriesItem':
            seasons = []
            for index, season in enumerate(reversed(card.get('seasons') or []), 1):
                number = _season_number(season, index)
                seasons.append({
                    'id': season.get('guid') or '',
                    'title': season.get('seasonTitle') or 'Stagione %d' % number,
                    'url': (season.get('cardLink') or {}).get('value') or link,
                    'number': number,
                })
            seasons = [season for season in seasons if season['id']]
            seasons.sort(key=lambda season: season['number'])
            action, content_type = 'epmenu', 'tvshow'
            series_id, video_id, content_series = seasons, '', title
        else:
            action, content_type = 'findvideos', 'movie'
            series_id, video_id, content_series = '', card.get('guid') or '', ''
            if not _free_media_selector(video_id):
                continue

        itemlist.append(item.clone(
            title=support.typo(title, 'bold'), fulltitle=title,
            contentTitle=title, contentSerieName=content_series,
            action=action, contentType=content_type,
            thumbnail=_graph_image(card, 'image_vertical', 400, 600),
            fanart=_graph_image(card, 'image_header_poster', 1200, 630),
            plot=card.get('cardText') or card.get('description') or '',
            url=link, video_id=video_id, seriesid=series_id,
            msp_type='series' if kind == 'SeriesItem' else 'movie',
            disable_videolibrary=True, forcethumb=True,
        ))
    return itemlist


def peliculas(item):
    itemlist = []
    res = get_programs(item)
    video_id= ''

    for it in (res.get('items') or []):
        if not 'MediasetPlay_ANY' in it.get('mediasetprogram$channelsRights',['MediasetPlay_ANY']): continue
        thumb = ''
        fanart = ''
        contentSerieName = ''
        url = 'https:'+ it.get('mediasettvseason$pageUrl', it.get('mediasetprogram$videoPageUrl', it.get('mediasetprogram$pageUrl')))
        title = it.get('mediasetprogram$brandTitle', it.get('title'))
        title2 = it['title']
        if title != title2:
            title = '{} - {}'.format(title, title2)
        plot = it.get('longDescription', it.get('description', it.get('mediasettvseason$brandDescription', '')))

        if it.get('seriesTitle') or it.get('seriesTvSeasons'):
            contentSerieName = it.get('seriesTitle', it.get('title'))
            contentType = 'tvshow'
            action = 'epmenu'
        else:
            contentType = 'movie'
            video_id = it['guid']
            action = 'findvideos'
        for k, v in it['thumbnails'].items():
            if 'image_vertical' in k and not thumb:
                thumb = v['url'].replace('.jpg', '@3.jpg')
            if 'image_header_poster' in k and not fanart:
                fanart = v['url'].replace('.jpg', '@3.jpg')
            if thumb and fanart:
                break

        itemlist.append(item.clone(title=support.typo(title, 'bold'),
                                   fulltitle=title,
                                   contentTitle=title,
                                   contentSerieName=contentSerieName,
                                   action=action,
                                   contentType=contentType,
                                   thumbnail=thumb,
                                   fanart=fanart,
                                   plot=plot,
                                   url=url,
                                   video_id=video_id,
                                   seriesid = it.get('seriesTvSeasons', it.get('id','')),
                                   # il nome del campo varia con la forma della
                                   # risposta: 'programType' nelle entries dei
                                   # blocks di ricerca, 'type' altrove
                                   msp_type = it.get('programType') or it.get('programtype') or it.get('type', ''),
                                   disable_videolibrary = True,
                                   forcethumb=True))
    if res['next']:
        item.page = res['next']
        support.nextPage(itemlist, item)

    return itemlist

def epmenu(item):
    logger.debug()
    itemlist = []

    epUrl = 'https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-subbrands-v2?byTvSeasonId={}&sort=mediasetprogram$order'

    if item.seriesid:
        if type(item.seriesid) == list:
            res = []
            seasons = list(item.seriesid)
            # L'API elenca le stagioni dalla più recente ("R.I.S. 5" per
            # prima): ordina per numero nel titolo (l'ULTIMO numero; la base
            # senza numero = stagione 1) così l'ordine è 1, 2, 3…
            def _snum(s):
                import re as _re_s
                m = _re_s.search(r'(\d+)(?!.*\d)', s.get('title') or '')
                return int(m.group(1)) if m else 0
            if any(_snum(s) for s in seasons):
                seasons.sort(key=_snum)
            else:
                seasons.reverse()
            for s in seasons:
                itemlist.append(
                    item.clone(seriesid = s['id'],
                               title=support.typo(s['title'], 'bold'),
                               url=s.get('url', item.url),
                               action='episodios'))
            if len(itemlist) == 1: return episodios(itemlist[0])
        else:
            res = requests.get(epUrl.format(item.seriesid)).json()['entries']
            for it in res:
                itemlist.append(
                    item.clone(seriesid = '',
                               title=support.typo(it['description'], 'bold'),
                               subbrand=it['mediasetprogram$subBrandId'],
                               action='episodios'))
            itemlist = sorted(itemlist, key=lambda it: it.title, reverse=True)
            if len(itemlist) == 1: return episodios(itemlist[0])

    return itemlist

def episodios(item):
    # create month list
    months = []
    try:
        for month in range(21, 33): months.append(xbmc.getLocalizedString(month))
    except:  # per i test, xbmc.getLocalizedString non è supportato
        for month in range(21, 33): months.append('dummy')

    # i programmi tv vanno ordinati per data decrescente, gli episodi delle serie per data crescente
    order = 'desc' if '/programmi-tv/' in item.url else 'asc'

    itemlist = []

    if not getattr(item, 'subbrand', '') and getattr(item, 'url', ''):
        try:
            page_response = requests.get(
                item.url,
                headers={'User-Agent': support.httptools.get_user_agent(),
                         'Referer': public_host + '/'},
                timeout=httptools.HTTPTOOLS_DEFAULT_DOWNLOAD_TIMEOUT,
            )
            page = page_response.content.decode('utf-8', 'replace')
            full_episode_ids = set(re.findall(
                r'editorialType\\?":\\?"Full Episode\\?",\\?"guid\\?":\\?"(F[A-Z0-9]+)',
                page, re.I))
            pattern = re.compile(
                r'href="(?P<url>/video/[^"]+_(?P<id>[A-Z0-9]+))"'
                r'.{0,5000}?<img[^>]+alt="(?P<title>[^"]+)"'
                r'[^>]+src="(?P<thumb>[^"]+)"',
                re.I | re.S,
            )
            seen = set()
            for match in pattern.finditer(page):
                video_id = match.group('id')
                if video_id in seen:
                    continue
                seen.add(video_id)
                import html as _html
                title = _html.unescape(match.group('title'))
                itemlist.append(item.clone(
                    title=support.typo(title, 'bold'), fulltitle=title,
                    contentTitle=title, contentType='episode',
                    action='findvideos',
                    url=public_host + match.group('url'),
                    video_id=video_id,
                    thumbnail=match.group('thumb').replace('&amp;', '&'),
                    forcethumb=True,
                ))
            if itemlist:
                return itemlist

            card_pattern = re.compile(
                r'<a[^>]+href="(?P<url>[^"]*(?P<id>F[A-Z0-9]{14,}))"'
                r'.{0,6000}?<h4[^>]*>(?P<title>.*?)</h4>',
                re.I | re.S,
            )
            for match in card_pattern.finditer(page):
                video_id = match.group('id')
                if video_id not in full_episode_ids or video_id in seen:
                    continue
                seen.add(video_id)
                import html as _html
                title = _html.unescape(re.sub(r'<[^>]+>', '', match.group('title'))).strip()
                itemlist.append(item.clone(
                    title=support.typo(title, 'bold'), fulltitle=title,
                    contentTitle=title, contentType='episode',
                    action='findvideos', url=match.group('url'),
                    video_id=video_id,
                    thumbnail=_graph_image({
                        'cardImages': [{
                            'engine': 'mp', 'id': video_id,
                            'sourceType': 'image_keyframe_poster',
                            'type': 'image_keyframe_poster',
                        }]
                    }, 'image_keyframe_poster', 360, 203),
                    forcethumb=True,
                ))
            if itemlist:
                return itemlist
        except Exception as exc:
            logger.error('[mediasetplay] season page failed: %s' % str(exc))

    if not getattr(item, 'subbrand', ''):
        return []
    res = requests.get('https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-programs-v2?byCustomValue={subBrandId}{' + item.subbrand +'}&range=0-10000&sort=:publishInfo_lastPublished|' + order + ',tvSeasonEpisodeNumber').json()['entries']

    for it in res:
        thumb = ''
        titleDate = ''
        if 'mediasetprogram$publishInfo_lastPublished' in it:
            date = datetime.date.fromtimestamp(it['mediasetprogram$publishInfo_lastPublished'] / 1000)
            titleDate ='  [{} {}]'.format(date.day, months[date.month-1])
        title = '[B]{}[/B]{}'.format(it['title'], titleDate)
        for k, v in it['thumbnails'].items():
            if 'image_keyframe' in k and not thumb:
                thumb = v['url'].replace('.jpg', '@3.jpg')
                break
        if not thumb: thumb = item.thumbnail

        itemlist.append(item.clone(title=title,
                                   thumbnail=thumb,
                                   forcethumb=True,
                                   contentType='episode',
                                   action='findvideos',
                                   video_id=it['guid']))

    return itemlist


def findvideos(item):
    logger.debug()
    item.no_return=True
    # support.dbg()
    mpd = config.get_setting('mpd', item.channel)


    lic_url = 'https://widevine.entitlement.theplatform.eu/wv/web/ModularDrm/getRawWidevineLicense?releasePid={pid}&account=http://access.auth.theplatform.com/data/Account/2702976343&schema=1.0&token={token}|Accept=*/*&Content-Type=&User-Agent={ua}|R{{SSM}}|'
    url = ''
    # support.dbg()
    if item.urls:
        url = ''
        pid = ''
        # Format = 'dash+xml' if mpd else 'x-mpegURL'
        # for it in item.urls:
        #     if Format in it['format']:
        item.url = requests.head(item.urls[0], headers={'User-Agent': support.httptools.get_user_agent()}).headers['Location']
        # pid = it['releasePids'][0]
        # if mpd and 'widevine' in it['assetTypes']:
        #     break

        if mpd:
            item.manifest = 'mpd'
            item.drm = 'com.widevine.alpha'
            item.license = lic_url.format(pid=pid, token=Token, ua=support.httptools.get_user_agent())

        else:
            item.manifest = 'hls'
        return support.server(item, itemlist=[item], Download=False, Videolibrary=False)

    elif item.video_id:
        res = _free_media_selector(item.video_id)
        if not res:
            logger.info('[mediasetplay] content unavailable to anonymous playback: %s'
                        % item.video_id)
            return []

    else:
        payload = {"channelCode":item.callSign, "streamType":"LIVE", "delivery":"Streaming", "createDevice":"true", "overrideAppName":web_app_name}
        res = session.post('https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0?sid=' + sid, json=payload).json()['response']['mediaSelector']

    url = res['url']
    mpd = True if 'dash' in res['formats'].lower() else False

    if url:

        sec_data = support.match(url + '?' + urlencode(res)).data
        item.url = support.match(sec_data, patron=r'<video src="([^"]+)').match  + '|User-Agent=' + support.httptools.get_user_agent()
        pid = support.match(sec_data, patron=r'pid=([^|]+)').match

        if mpd and pid:
            item.manifest = 'mpd'
            item.drm = 'com.widevine.alpha'
            item.license = lic_url.format(pid=pid, token=Token, ua=support.httptools.get_user_agent())
        else:
            item.manifest = 'hls'

        return support.server(item, itemlist=[item], Download=False, Videolibrary=False)


def get_from_id(item):
    #sessionKey = session.get(sessionUrl.format(uuid=str(uuid.uuid4())), verify=False).json()['sessionKey']
    #session.headers.update({'x-session': sessionKey})
    res = session.get(entry.format(id=item.args)).json()
    if 'components' in res:
        id = quote(",".join(res["components"]))
        res = session.get(entries.format(id=id)).json()
    if 'entries' in res:
        return res['entries']
    return {}

def get_programs(item):
    url = ''
    pag = item.page if item.page else 1
    ret = {}

    if item.args.get('feed'):
        pag = item.page if item.page else 1
        url='{}&range={}-{}'.format(item.args.get('feed'), pag, pag + pagination - 1)
        ret['next'] = pag + pagination
        res = requests.get(url).json()

    else:
        args = {key:value for key, value in item.args.items()}
        args['context'] = 'platform≈web'
        args['sid'] = sid
        args['sessionId'] = sid
        args['hitsPerPage'] = pagination
        args['property'] = 'search' if args.get('query') else 'play'
        args['tenant'] = 'play-prod-v2'
        args['page'] = pag
        args['deviceId'] = '017ac511182d008322c989f3aac803083002507b00bd0'
        url="https://api-ott-prod-fe.mediaset.net/PROD/play/reco/anonymous/v2.0?" + urlencode(args)

        res = session.get(url).json()

    if res:
        res = res.get('response', res)
        if 'entries' in res:
            ret['items'] = res['entries']
        elif 'blocks' in res:
            items = []
            for block in res['blocks']:
                items += block['items']
            ret['items'] = items
        if not 'next' in ret:
            next = res.get('pagination',{}).get('hasNextPage', False)
            ret['next'] = pag + 1 if next else 0
    return ret
