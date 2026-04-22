import sys
if sys.version_info[0] >= 3:
    import urllib.parse as urlparse
else:
    import urlparse
from core import httptools, scrapertools, support
from platformcode import logger, config

# Cache iframe_url between test_video_exists and get_video_url (keyed by page_url)
_cache = {}

def _get_iframe_url(page_url):
    """
    Resolve /uprots/ID  →  (via redirect chain)  .../watchfree/RAND/MOVIE_ID/TOKEN
    Extract MOVIE_ID (2nd-to-last path segment) and build /emhuih/MOVIE_ID.

    We follow redirects and read the final URL from resp.url, because Cloudflare
    often intercepts 302s and returns a 200 response, making the Location header
    unavailable when follow_redirects=False.
    """
    resp1 = httptools.downloadpage(page_url, follow_redirects=True)
    final_url = getattr(resp1, 'url', '') or ''
    # Try Location header as fallback (in case the response is a bare 302)
    if not final_url or final_url.rstrip('/') == page_url.rstrip('/'):
        headers1 = getattr(resp1, 'headers', None) or {}
        final_url = headers1.get('Location', '').strip()
    if not final_url:
        return None
    # e.g. https://maxsun435.online/watchfree/RAND/MOVIE_ID/TOKEN
    parts = [p for p in final_url.split('?')[0].rstrip('/').split('/') if p]
    if len(parts) < 2:
        return None
    movie_id = parts[-2]
    return 'https://maxstream.video/emhuih/' + movie_id


def test_video_exists(page_url):
    logger.debug("(page_url='%s')" % page_url)
    iframe_url = _get_iframe_url(page_url)
    if not iframe_url:
        return False, config.get_localized_string(70449) % "Maxstream"
    _cache[page_url] = iframe_url
    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = []

    # Retrieve iframe_url (preferably from cache set by test_video_exists)
    iframe_url = _cache.pop(page_url, None)
    if not iframe_url:
        iframe_url = _get_iframe_url(page_url)
    if not iframe_url:
        return video_urls

    # Step 3: Download the embed page and extract HLS m3u8
    html = httptools.downloadpage(iframe_url, headers={'Referer': page_url}).data
    m3u8 = scrapertools.find_single_match(html, r'(https?://[^\s"\']+\.m3u8[^\s"\']*)')
    if m3u8:
        video_urls.append(["[Maxstream]", m3u8])
    return video_urls
