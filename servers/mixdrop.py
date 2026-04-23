# -*- coding: utf-8 -*-
# --------------------------------------------------------
# Conector Mixdrop By Alfa development Group
# --------------------------------------------------------

import re as _re
import json as _json
from core import httptools, servertools
from core import scrapertools
from lib import jsunpack
from platformcode import logger, config


def _resolve_stayonline(page_url):
    """Resolve a stayonline.pro link to the real URL via AJAX bypass."""
    try:
        m = _re.search(r'stayonline\.pro/[^/]+/([^/?#]+)', page_url)
        if not m:
            return None
        link_id = m.group(1).strip('/')
        logger.info('mixdrop._resolve_stayonline linkId=%r' % link_id)
        resp = httptools.downloadpage(
            'https://stayonline.pro/ajax/linkView.php',
            post={'id': link_id, 'reCaptchaResponse': '', 'ref': ''},
            headers={
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': page_url,
                'Origin': 'https://stayonline.pro',
                'Accept': 'application/json',
            })
        raw = getattr(resp, 'data', '') or ''
        logger.info('mixdrop._resolve_stayonline response=%r' % raw[:200])
        j = _json.loads(raw)
        if j.get('status') == 'success':
            real_url = j['data']['value']
            logger.info('mixdrop._resolve_stayonline resolved=%r' % real_url)
            return real_url
    except Exception as e:
        logger.error('mixdrop._resolve_stayonline error: %s' % e)
    return None


def test_video_exists(page_url):
    logger.debug("(page_url='%s')" % page_url)
    global data

    # stayonline.pro wraps links in an reCaptcha modal, but posting with
    # an empty token bypasses server-side validation.
    if 'stayonline.pro' in page_url:
        real_url = _resolve_stayonline(page_url)
        if not real_url:
            logger.info('mixdrop.test_video_exists stayonline.pro: could not resolve')
            return False, 'stayonline.pro link cannot be resolved automatically'
        logger.info('mixdrop.test_video_exists stayonline resolved -> %r' % real_url)
        page_url = real_url

    resp = httptools.downloadpage(page_url)
    data = getattr(resp, 'data', '') or ''
    # If the plain request didn't get the packed JS (CF challenge), retry with cloudscraper
    if 'eval(function(' not in data:
        logger.info('mixdrop.test_video_exists: no packed JS on plain request, retrying with cloudscraper')
        resp = httptools.downloadpage(page_url, cloudscraper=True)
        data = getattr(resp, 'data', '') or ''
    # Also check final URL after redirect (mixdrop.ag may redirect to m1xdrop.click etc.)
    final_url = getattr(resp, 'url', page_url) or page_url
    if final_url != page_url:
        logger.info('mixdrop.test_video_exists followed redirect -> %r' % final_url)
        page_url = final_url

    if "<h2 style=\"color:#068af0\">WE ARE SORRY</h2>" in data or "<h2 style=\"color:#068af0\">ALMOST THERE</h2>" in data or '<title>404 Not Found</title>' in data:
        return False, config.get_localized_string(70449) % "MixDrop"

    # Cloudflare challenge page: no packed JS means we can't extract video
    if 'eval(function(' not in data:
        logger.info('mixdrop.test_video_exists: no packed JS (CF challenge?), marking as unavailable')
        return False, config.get_localized_string(70449) % "MixDrop"

    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    logger.debug("url=" + page_url)
    video_urls = []
    ext = '.mp4'

    global data

    packed = scrapertools.find_single_match(data, r'(eval\(function\(.+)')
    if not packed or not jsunpack.detect(packed):
        logger.info('mixdrop.get_video_url: no packed JS found, cannot extract video')
        return video_urls

    try:
        unpacked = jsunpack.unpack(packed)
    except Exception as e:
        logger.error('mixdrop.get_video_url jsunpack error: %s' % e)
        return video_urls

    # mixdrop like to change var name very often, hoping that will catch every
    list_vars = scrapertools.find_multiple_matches(unpacked, r'MDCore\.\w+\s*=\s*"([^"]+)"')
    media_url = ''
    for var in list_vars:
        if '.mp4' in var or var.startswith('//'):
            media_url = var
            break

    if not media_url:
        logger.info('mixdrop.get_video_url: MDCore vars found but no video URL: %s' % list_vars)
        return video_urls

    if not media_url.startswith('http'):
        media_url = 'http:%s' % media_url
    video_urls.append(["%s [Mixdrop]" % ext, media_url])

    return video_urls


def get_filename(page_url):
    title = httptools.downloadpage(page_url.replace('/e/', '/f/')).data.split('<title>')[1].split('</title>')[0]
    prefix = 'MixDrop - Watch '
    if title.startswith(prefix):
        return title[len(prefix):]
    return ""
