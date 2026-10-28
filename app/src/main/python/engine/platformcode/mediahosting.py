# -*- coding: utf-8 -*-
"""Independent MediaHosting live source, as published by the installed provider.

The catalogue supplies the stream id on every refresh. No imports, plugin://
calls or file reads from Mandrakodi at runtime. A provider-side URL/token change
requires a resolver update; never pretend an expired source is still online.
"""
import re
from urllib.parse import urlencode

# Provider's published resolver snapshot, 2026-10-24. This is a source URL token,
# not a user's password/account or a DRM key. Do not log complete signed URLs.
STREAM_TEMPLATE = ('https://p7.streamhostingcdn.top/stream/{stream}/index.m3u8'
                   '?token=o_mnFDukW1rajOBK2cJPcw&ark_r=p7')
REFERER = 'https://prohostmedia.top/'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 OPR/133.0.0.0')


def source(code):
    code = str(code or '')
    if not re.fullmatch(r'[0-9]{1,6}', code):
        return None
    return dict(url=STREAM_TEMPLATE.format(stream=code), kind='hls',
                headers={'User-Agent': UA, 'Referer': REFERER, 'Origin': REFERER.rstrip('/')})


def online(code, probe=None):
    from platformcode import eventavailability
    value = source(code)
    if not value:
        return False
    return (probe or eventavailability.hls_reachable)(value) is True


def listitem(code, title, art=None):
    import xbmcgui
    value = source(code)
    if not value:
        return None
    li = xbmcgui.ListItem(path=value['url'], offscreen=True)
    li.setLabel(title)
    li.setContentLookup(False)
    li.setMimeType('application/x-mpegURL')
    li.setProperty('inputstream', 'inputstream.adaptive')
    li.setProperty('inputstream.adaptive.manifest_type', 'hls')
    headers = urlencode(value['headers'])
    li.setProperty('inputstream.adaptive.stream_headers', headers)
    li.setProperty('inputstream.adaptive.manifest_headers', headers)
    if art:
        li.setArt(art)
    return li
