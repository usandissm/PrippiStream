import sys
if sys.version_info[0] >= 3:
    import urllib.parse as urlparse
else:
    import urlparse
from core import httptools, scrapertools
from lib import jsunpack
from platformcode import logger, config

# Cache between test_video_exists and get_video_url
_cache = {}

# Text that appears when a maxstream file is expired/deleted
_DEAD_TEXT = ('File is no longer available', 'File is not longer available',
              'expired or has been deleted')


def _is_dead(html):
    return any(t in html for t in _DEAD_TEXT)


def _get_embed_page(page_url):
    """
    Given a maxstream URL (either /uprots/TOKEN or /emhuih/ID or /e/ID),
    return the HTML of the player embed page, or None if file is dead.

    Strategy:
    - /uprots/ URL: use follow_redirects=False to capture 302 Location
                    → watchfree → extract movie_id → /emhuih/movie_id
    - /emhuih/ or /e/ URL: download directly (from altadefinizione etc.)
    """
    url_lower = page_url.lower()

    if '/uprots/' in url_lower:
        # CB01/uprot flow: get 302 redirect Location
        resp = httptools.downloadpage(page_url, follow_redirects=False,
                                      headers={'Referer': 'https://uprot.net/'})
        loc = (getattr(resp, 'headers', None) or {}).get('Location', '').strip()
        logger.info('maxstream._get_embed_page uprots code=%r loc=%r' % (getattr(resp, 'code', '?'), loc))
        if loc and '/watchfree/' in loc:
            # extract movie_id from /watchfree/MOVIE_ID/session/token
            try:
                parts = [p for p in urlparse.urlparse(loc).path.split('/') if p]
                movie_id = parts[1] if len(parts) >= 2 else None
            except Exception:
                movie_id = None
            if movie_id:
                emhuih_url = 'https://maxstream.video/emhuih/' + movie_id
                logger.info('maxstream._get_embed_page emhuih_url=%r' % emhuih_url)
                page_url = emhuih_url
            # If we couldn't parse the movie_id, fall through and try original URL
        else:
            # No 302 or no watchfree — try following redirects and use whatever page we get
            resp2 = httptools.downloadpage(page_url, follow_redirects=True,
                                           headers={'Referer': 'https://uprot.net/'})
            html2 = getattr(resp2, 'data', '') or ''
            logger.info('maxstream._get_embed_page no-redirect fallback snippet=%r' % html2[:200])
            return None if _is_dead(html2) else html2

    # Direct download (for /emhuih/, /e/, or after uprots resolution)
    html = httptools.downloadpage(page_url).data or ''
    logger.info('maxstream._get_embed_page direct snippet=%r' % html[:200])
    if _is_dead(html):
        return None

    # If no eval() here, try an iframe src one level deep
    if not scrapertools.find_single_match(html, r'(eval\(.+)'):
        iframe_src = scrapertools.find_single_match(html, r'<iframe [^>]+src="([^"]+)"')
        if iframe_src:
            logger.info('maxstream._get_embed_page following iframe: %r' % iframe_src)
            html = httptools.downloadpage(iframe_src).data or ''
            logger.info('maxstream._get_embed_page iframe snippet=%r' % html[:200])
            if _is_dead(html):
                return None

    return html or None


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
    html = _get_embed_page(page_url)
    if html is None:
        logger.info("maxstream.test_video_exists: file dead or unreachable")
        return False, config.get_localized_string(70449) % "Maxstream"
    _cache[page_url] = html
    return True, ""


def get_video_url(page_url, premium=False, user="", password="", video_password=""):
    video_urls = []
    html = _cache.pop(page_url, None)
    if html is None:
        html = _get_embed_page(page_url)
    if not html:
        return video_urls

    logger.info("maxstream.get_video_url html_snippet=%r" % html[:300])

    # Strategy 1: jsunpack (packed JS player)
    js = scrapertools.find_single_match(html, r'(eval\(.+)')
    if js and jsunpack.detect(js):
        try:
            unpacked = jsunpack.unpack(js)
            logger.info("maxstream.get_video_url unpacked=%r" % unpacked[:200])
            video = scrapertools.find_single_match(unpacked, r'src:"([^"]+)",type')
            if video:
                video_urls.append(["[Maxstream]", video])
                return video_urls
        except Exception as e:
            logger.error("maxstream jsunpack error: %s" % str(e))

    # Strategy 2: direct m3u8 in page
    m3u8 = scrapertools.find_single_match(html, r'(https?://[^\s"\']+\.m3u8[^\s"\']*)')
    if m3u8:
        video_urls.append(["[Maxstream]", m3u8])

    return video_urls

