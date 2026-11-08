# -*- coding: utf-8 -*-
import sys
PY3 = False
if sys.version_info[0] >= 3: PY3 = True

from six.moves import urllib
    
import ast
import json
import ssl
import xbmc

from core import httptools, support, filetools
from platformcode import logger, config

vttsupport = False if int(xbmc.getInfoLabel('System.BuildVersion').split('.')[0]) < 20 else True
iframeParams = None
urlParams = {}
bootstrap_url = ''
activeStreamUrl = ''


def _player_page(server_url, referer):
    """Same verified HTTPS transport as Kodi; required for background renewals."""
    parsed = urllib.parse.urlsplit(server_url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname:
        raise ValueError('Indirizzo player non valido')
    headers = {key: value for key, value in httptools.default_headers.items()
               if key.lower() in ('user-agent', 'accept', 'accept-language')}
    headers.update({'Referer': referer, 'Accept-Encoding': 'identity'})
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(urllib.request.Request(server_url, headers=headers), timeout=15) as response:
        body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError('Risposta player troppo grande')
        if response.headers.get('Content-Encoding', '').lower() == 'gzip':
            import gzip
            body = gzip.decompress(body)
    return body.decode('utf-8', 'replace')

def test_video_exists(page_url):
    global iframeParams
    global urlParams
    global bootstrap_url
    global activeStreamUrl
    iframeParams = None
    urlParams = {}
    bootstrap_url = ''
    activeStreamUrl = ''
    import re as _re
    _raw_match = support.match(page_url, patron=['<iframe [^>]+src="([^"]+)', 'embed_url="([^"]+)']).match
    if not _raw_match:
        logger.info('[SC-WS] direct fetch empty, trying proxytranslate for %s' % page_url)
        try:
            from lib import proxytranslate
            _proxy = proxytranslate.process_request_proxy(page_url)
            if _proxy and _proxy.get('data'):
                for _pat in [r'<iframe [^>]+src="([^"]+)"', r'embed_url="([^"]+)"']:
                    _m = _re.search(_pat, _proxy['data'])
                    if _m:
                        _raw_match = _m.group(1)
                        break
        except Exception as _pte:
            logger.error('[SC-WS] proxytranslate failed: %s' % str(_pte))
    server_url = support.scrapertools.decodeHtmlentities(_raw_match or '')
    if not server_url:
        return False, 'Pagina del player non disponibile'
    server_url = urllib.parse.urljoin(page_url, server_url)
    bootstrap_url = server_url
    try:
        player_data = _player_page(server_url, page_url)
    except Exception as exc:
        logger.error('[SC-WS] player transport: %s' % type(exc).__name__)
        return False, 'Player video momentaneamente non disponibile'
    parsed_config = _re.search(r'''window\.masterPlaylist\s+=\s+{[^{]+({[^}]+}),\s+url:\s+'([^']+).*?canPlayFHD\s=\s(true|false)''', player_data, _re.S)
    iframeParams = parsed_config.groups() if parsed_config else None
    streams_match = _re.search(r'window\.streams\s*=\s*(\[[^;]+\])\s*;', player_data or '', _re.S | _re.I)
    if streams_match:
        try:
            streams = json.loads(streams_match.group(1))
            activeStreamUrl = next((entry.get('url', '') for entry in streams
                                    if entry.get('active') and entry.get('url')), '')
        except Exception as exc:
            logger.debug('[SC-WS] active stream parse failed: %s' % str(exc))

    if not iframeParams or len(iframeParams) < 2:
        return False, 'Configurazione del player non disponibile'

    urlParams = urllib.parse.parse_qs(urllib.parse.urlsplit(server_url).query)
    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = list()
    if not iframeParams or len(iframeParams) != 3:
        return video_urls

    params, url, canPlayFHD = iframeParams
    split_url = urllib.parse.urlsplit(activeStreamUrl or url)
    url_params = urllib.parse.parse_qsl(split_url.query)
    logger.debug(url_params)
    masterPlaylistParams = ast.literal_eval(params)
    if canPlayFHD == 'true':
        masterPlaylistParams['h'] = 1
    for _p in ('b', 'scz'):
        if _p in urlParams:
            masterPlaylistParams[_p] = urlParams[_p][0]
    
    masterPlaylistParams.update(url_params)
    if canPlayFHD == 'true':
        masterPlaylistParams['h'] = 1
    else:
        masterPlaylistParams.pop('h', None)
    masterPlaylistParams = {k: v for k, v in masterPlaylistParams.items() if v is not None and v != ''}
    url =  '{}://{}{}?{}'.format(split_url.scheme,split_url.netloc,split_url.path,urllib.parse.urlencode(masterPlaylistParams))

    video_urls = [['hls [{}]'.format('FullHD' if canPlayFHD == 'true' else 'HD'), url]]

    return video_urls
