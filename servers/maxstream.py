import sys
if sys.version_info[0] >= 3:
    import urllib.parse as urlparse
else:
    import urlparse
from core import httptools, scrapertools
from platformcode import logger, config

# Cache between test_video_exists and get_video_url
_cache = {}


def _resolve_watchfree_url(page_url):
    """
    Resolve /uprots/TOKEN via 302 Location header to /watchfree/MOVIE_ID/...
    Returns the watchfree URL, or None.
    """
    resp = httptools.downloadpage(page_url, follow_redirects=False,
                                  headers={'Referer': 'https://uprot.net/'})
    loc = (getattr(resp, 'headers', None) or {}).get('Location', '').strip()
    logger.info('maxstream._resolve_watchfree code=%r loc=%r' % (getattr(resp, 'code', '?'), loc))
    if loc and '/watchfree/' in loc:
        return loc
    # Fallback: follow redirects and search body
    resp2 = httptools.downloadpage(page_url, follow_redirects=True,
                                   headers={'Referer': 'https://uprot.net/'})
    data = getattr(resp2, 'data', '') or ''
    wf = scrapertools.find_single_match(data, r'https?://[^\s"\']+/watchfree/[^\s"\']+')
    logger.info('maxstream._resolve_watchfree fallback wf=%r snippet=%r' % (wf, data[:200]))
    return wf or None


def _movie_id_from_watchfree(wf_url):
    """Extract MOVIE_ID (first path segment after /watchfree/) from a watchfree URL."""
    try:
        path = urlparse.urlparse(wf_url).path
        parts = [p for p in path.split('/') if p]
        if len(parts) >= 2 and parts[0] == 'watchfree':
            return parts[1]
    except Exception:
        pass
    return None


def test_video_exists(page_url):
    logger.info("maxstream.test_video_exists page_url='%s'" % page_url)
    wf_url = _resolve_watchfree_url(page_url)
    if not wf_url:
        return False, config.get_localized_string(70449) % "Maxstream"
    movie_id = _movie_id_from_watchfree(wf_url)
    if not movie_id:
        return False, config.get_localized_string(70449) % "Maxstream"
    emhuih_url = 'https://maxstream.video/emhuih/' + movie_id
    # Verify the file is actually available (not expired/deleted)
    html = httptools.downloadpage(emhuih_url, headers={'Referer': page_url}).data or ''
    logger.info("maxstream.test_video_exists emhuih_url=%r snippet=%r" % (emhuih_url, html[:200]))
    if 'not longer available' in html or 'expired or has been deleted' in html:
        logger.info("maxstream.test_video_exists: file expired/deleted")
        return False, config.get_localized_string(70449) % "Maxstream"
    _cache[page_url] = (emhuih_url, html)
    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = []
    cached = _cache.pop(page_url, None)
    if cached:
        emhuih_url, html = cached
    else:
        wf_url = _resolve_watchfree_url(page_url)
        if not wf_url:
            return video_urls
        movie_id = _movie_id_from_watchfree(wf_url)
        if not movie_id:
            return video_urls
        emhuih_url = 'https://maxstream.video/emhuih/' + movie_id
        html = httptools.downloadpage(emhuih_url, headers={'Referer': page_url}).data or ''

    logger.info("maxstream.get_video_url emhuih_url=%r" % emhuih_url)
    logger.info("maxstream.get_video_url emhuih html_snippet=%r" % html[:300])

    cdn_url = scrapertools.find_single_match(html, r'href="(https://[^"]+/cdn-cgi/content[^"]+)"')
    if cdn_url:
        logger.info("maxstream.get_video_url cdn_url=%r" % cdn_url)
        html2 = httptools.downloadpage(cdn_url, headers={'Referer': emhuih_url}).data or ''
        logger.info("maxstream.get_video_url cdn html_snippet=%r" % html2[:300])
        m3u8 = scrapertools.find_single_match(html2, r'(https?://[^\s"\']+\.m3u8[^\s"\']*)')
        if m3u8:
            video_urls.append(["[Maxstream]", m3u8])
            return video_urls

    m3u8 = scrapertools.find_single_match(html, r'(https?://[^\s"\']+\.m3u8[^\s"\']*)')
    if m3u8:
        video_urls.append(["[Maxstream]", m3u8])

    return video_urls
