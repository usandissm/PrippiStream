# -*- coding: utf-8 -*-
import sys
PY3 = False
if sys.version_info[0] >= 3: PY3 = True

from six.moves import urllib
    
import ast
import json
import xbmc

from core import httptools, support, filetools
from platformcode import logger, config

vttsupport = False if int(xbmc.getInfoLabel('System.BuildVersion').split('.')[0]) < 20 else True

def test_video_exists(page_url):
    global iframeParams
    global urlParams
    global bootstrap_url
    global activeStreamUrl
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
    bootstrap_url = server_url
    server_page = support.match(server_url, patron=r'''window\.masterPlaylist\s+=\s+{[^{]+({[^}]+}),\s+url:\s+'([^']+).*?canPlayFHD\s=\s(true|false)''', debug=False)
    iframeParams = server_page.match
    activeStreamUrl = ''
    streams_match = _re.search(r'window\.streams\s*=\s*(\[[^;]+\])\s*;', server_page.data or '', _re.S | _re.I)
    if streams_match:
        try:
            streams = json.loads(streams_match.group(1))
            activeStreamUrl = next((entry.get('url', '') for entry in streams
                                    if entry.get('active') and entry.get('url')), '')
        except Exception as exc:
            logger.debug('[SC-WS] active stream parse failed: %s' % str(exc))

    if not iframeParams or len(iframeParams) < 2:
        return 'StreamingCommunity', 'Prossimamente'

    urlParams = urllib.parse.parse_qs(urllib.parse.urlsplit(server_url).query)
    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = list()

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
    masterPlaylistParams = {k: v for k, v in masterPlaylistParams.items() if v is not None and v != ''}
    url =  '{}://{}{}?{}'.format(split_url.scheme,split_url.netloc,split_url.path,urllib.parse.urlencode(masterPlaylistParams))

    video_urls = [['hls [{}]'.format('FullHD' if canPlayFHD == 'true' else 'HD'), url]]

    return video_urls
