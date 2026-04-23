import sys
import re as _re
if sys.version_info[0] >= 3:
    import urllib.parse as urlparse
    import json as _json
else:
    import urlparse
    import json as _json
from core import httptools, scrapertools
from lib import jsunpack
from platformcode import logger, config

# Cache between test_video_exists and get_video_url
_cache = {}

# Text that appears when a maxstream file is expired/deleted
_DEAD_TEXT = ('File is no longer available', 'File is not longer available',
              'expired or has been deleted', 'File id error')


def _is_dead(html):
    for t in _DEAD_TEXT:
        idx = html.find(t)
        if idx < 0:
            continue
        # The emhuih player page contains a hidden fallback div:
        # <div style="display: none;">File is no longer available</div>
        # Skip matches that appear inside a "display: none" element (false positive).
        context_before = html[max(0, idx - 200):idx]
        if 'display: none' in context_before or 'display:none' in context_before:
            continue
        return True
    return False


def _resolve_stayonline(page_url):
    """
    stayonline.pro hides the real URL behind a reCaptcha modal.
    However, posting to /ajax/linkView.php with an EMPTY reCaptchaResponse
    returns status=success with the real URL (server-side validation only
    fires when the token is non-empty but invalid).
    """
    try:
        m = _re.search(r'stayonline\.pro/[^/]+/([^/?#]+)', page_url)
        if not m:
            return None
        link_id = m.group(1).strip('/')
        logger.info('maxstream._resolve_stayonline linkId=%r' % link_id)
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
        logger.info('maxstream._resolve_stayonline response=%r' % raw[:200])
        j = _json.loads(raw)
        if j.get('status') == 'success':
            real_url = j['data']['value']
            logger.info('maxstream._resolve_stayonline resolved=%r' % real_url)
            return real_url
    except Exception as e:
        logger.error('maxstream._resolve_stayonline error: %s' % e)
    return None


def _get_embed_page(page_url):
    """
    Given a maxstream URL (either /uprots/TOKEN or /emhuih/ID or /e/ID),
    return the HTML of the player embed page, or None if file is dead.

    Strategy:
    - /uprots/ URL: cloudscraper to bypass CF → redirect to watchfree → extract SESSION_ID (parts[2]) → /emhuih/SESSION_ID
    - uprot.net/msf/ URL: parse page HTML → try all unique /uprots/ tokens in reverse order
    - /emhuih/ or /e/ URL: download directly (from altadefinizione, watchfree, etc.)
    """
    url_lower = page_url.lower()

    # stayonline.pro wraps the real URL behind a (bypassable) reCaptcha
    if 'stayonline.pro' in url_lower:
        real_url = _resolve_stayonline(page_url)
        if not real_url:
            return None
        return _get_embed_page(real_url)

    if '/uprots/' in url_lower:
        # CB01/uprot flow: follow redirect to maxthuXXX.site/watchfree/MOVIE_ID/SESSION_ID/TOKEN.
        # Strategy: try two passes.
        #   Pass 1 – with cloudscraper (may solve CF JS challenge).
        #   Pass 2 – without cloudscraper (uses CF worker proxy; proxy follows redirect but
        #            httptools forcibly resets resp.url to the original uprots URL, so we must
        #            scan the response HTML for the watchfree URL instead of using resp.url).
        # Dead files return "File id error" text (no CF block) → detected by _is_dead().
        def _try_uprots(use_cloudscraper):
            kw = dict(follow_redirects=True, headers={'Referer': 'https://uprot.net/'})
            if use_cloudscraper:
                kw['cloudscraper'] = True
            r = httptools.downloadpage(page_url, **kw)
            html = getattr(r, 'data', '') or ''
            furl = getattr(r, 'url', '') or ''
            logger.info('maxstream._get_embed_page uprots[cs=%s] final_url=%r snippet=%r'
                        % (use_cloudscraper, furl, html[:100]))
            if _is_dead(html):
                return None, None, True  # (html, final_url, is_dead)
            # Find watchfree URL: either resp.url (when redirect was followed),
            # or inside the HTML body (meta-refresh / JS redirect / iframe from proxy).
            if '/watchfree/' not in furl and html:
                m = scrapertools.find_single_match(
                    html, r'(https?://[^\s"\'<>]+/watchfree/[^\s"\'<>]+)')
                if m:
                    furl = m
                    logger.info('maxstream._get_embed_page uprots watchfree in HTML: %r' % furl)
            return html, furl, False

        html_uprots, final_url, dead = _try_uprots(use_cloudscraper=True)
        if dead:
            return None

        # If cloudscraper gave nothing, retry via the CF worker proxy (no cloudscraper)
        if not html_uprots and not final_url:
            html_uprots, final_url, dead = _try_uprots(use_cloudscraper=False)
            if dead:
                return None

        if '/watchfree/' in (final_url or ''):
            # watchfree path: /watchfree/MOVIE_ID/SESSION_ID/TOKEN
            # SESSION_ID (parts[2]) is the file_id used by emhuih, NOT the movie_id (parts[1])
            try:
                parts = [p for p in urlparse.urlparse(final_url).path.split('/') if p]
                session_id = parts[2] if len(parts) >= 3 else None
            except Exception:
                session_id = None
            if session_id:
                page_url = 'https://maxstream.video/emhuih/' + session_id
                logger.info('maxstream._get_embed_page uprots→emhuih: %r' % page_url)
            else:
                logger.info('maxstream._get_embed_page uprots: no session_id in %r' % final_url)
                return None
        else:
            logger.info('maxstream._get_embed_page uprots: no watchfree after both passes, final=%r' % final_url)
            return None
        # fall through to direct download of page_url (now emhuih/SESSION_ID)

    elif 'uprot.net' in url_lower:
        # uprot.net/msf/TOKEN — the page is NOT a 302 redirect but an HTML page that
        # embeds the real maxstream.video/uprots/ links in anchor tags.
        # Download the HTML and try all tokens in reverse order (last tends to be live).
        html_uprot = (httptools.downloadpage(
            page_url, headers={'Referer': 'https://uprot.net/'}).data or '')
        logger.info('maxstream._get_embed_page uprot/msf html_snippet=%r' % html_uprot[:400])

        # Real tokens are long base64; filter out the fake placeholder '123456789012'
        all_tokens = scrapertools.find_multiple_matches(
            html_uprot,
            r'href="(https://(?:www\.)?maxstream\.video/uprots/[A-Za-z0-9+/=]{10,})"')
        seen = set()
        unique_tokens = [t for t in all_tokens
                         if t and '123456789012' not in t and not (t in seen or seen.add(t))]

        if not unique_tokens:
            logger.info('maxstream._get_embed_page uprot/msf: no /uprots/ tokens found')
            return None

        logger.info('maxstream._get_embed_page uprot/msf: trying %d tokens reversed' % len(unique_tokens))
        # Try tokens in reverse order — the last distinct token is usually the live one
        for token_url in reversed(unique_tokens):
            result = _get_embed_page(token_url)
            if result is not None:
                return result
        return None

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

