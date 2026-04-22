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
    Resolve /uprots/ID to /emhuih/MOVIE_ID.

    Strategy (most-to-least reliable):
      1. Parse the response HTML for any /emhuih/<digits> path (works when we
         landed on the watchfree page after redirect).
      2. Extract MOVIE_ID from resp.url (the final URL after all redirects).
      3. Look for a /watchfree/ path in the HTML (meta-refresh / JS redirect).
      4. Fall back to Location header (only set when follow_redirects=False,
         kept here as belt-and-suspenders for older httptools variants).
    """
    resp1 = httptools.downloadpage(page_url, follow_redirects=True)
    data = getattr(resp1, 'data', '') or ''

    # ── Strategy 1: /emhuih/<id> anywhere in the response body ──────────────
    emhuih = scrapertools.find_single_match(data, r'[/"\']emhuih[/"\']?(\d+)')
    if not emhuih:
        emhuih = scrapertools.find_single_match(data, r'/emhuih/(\d+)')
    if emhuih:
        logger.debug('maxstream._get_iframe_url: found emhuih id=%s in HTML' % emhuih)
        return 'https://maxstream.video/emhuih/' + emhuih

    # ── Strategy 2: MOVIE_ID from resp.url (final URL after redirect) ────────
    final_url = getattr(resp1, 'url', '') or ''
    if final_url and final_url.rstrip('/') != page_url.rstrip('/') and '/watchfree/' in final_url:
        parts = [p for p in final_url.split('?')[0].rstrip('/').split('/') if p]
        if len(parts) >= 2 and parts[-2].isdigit():
            logger.debug('maxstream._get_iframe_url: movie_id=%s from resp.url' % parts[-2])
            return 'https://maxstream.video/emhuih/' + parts[-2]

    # ── Strategy 3: /watchfree/ path in HTML (meta-refresh / JS window.location) ─
    wf_match = scrapertools.find_single_match(data, r'["\']([^"\']+/watchfree/[^"\']+)["\']')
    if wf_match:
        parts = [p for p in wf_match.split('?')[0].rstrip('/').split('/') if p]
        if len(parts) >= 2 and parts[-2].isdigit():
            logger.debug('maxstream._get_iframe_url: movie_id=%s from HTML watchfree ref' % parts[-2])
            return 'https://maxstream.video/emhuih/' + parts[-2]

    # ── Strategy 4: Location header (legacy / non-CF proxy path) ─────────────
    headers1 = getattr(resp1, 'headers', None) or {}
    loc = headers1.get('Location', '').strip()
    if loc and '/watchfree/' in loc:
        parts = [p for p in loc.split('?')[0].rstrip('/').split('/') if p]
        if len(parts) >= 2 and parts[-2].isdigit():
            logger.debug('maxstream._get_iframe_url: movie_id=%s from Location header' % parts[-2])
            return 'https://maxstream.video/emhuih/' + parts[-2]

    logger.debug('maxstream._get_iframe_url: could not extract iframe_url. resp.url=%r data_snippet=%r' % (
        final_url, data[:200] if data else ''))
    return None


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
