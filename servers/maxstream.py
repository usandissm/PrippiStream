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
        # CB01/uprot flow: maxstream.video/uprots/TOKEN 302-redirects to
        # maxweXXX.site/watch_free/VIEW_ID/FILE_ID/TOKEN. We only need that redirect
        # URL (to read FILE_ID); the watch_free body itself is a Cloudflare challenge.
        # Modes, tried in order until one yields the watch_free URL:
        #   'plain'  – use_requests=True: a vanilla requests session WITHOUT the custom
        #              cipher/DNS adapter. CF returns a clean 302 to this fingerprint,
        #              so this is the one that actually works. Try it first.
        #   'cs'     – cloudscraper (may solve a JS challenge).
        #   'default'– the cipher adapter / CF worker proxy (often CF-challenged here).
        # Dead files return "File id error" text → detected by _is_dead().
        def _try_uprots(mode):
            if mode == 'raw':
                # Bypass httptools entirely: a vanilla requests session (browser UA,
                # system DNS, default TLS, NO custom cipher adapter, NO Cloudflare
                # worker-proxy retry) gets a clean 302 from maxstream.video to the
                # watch_free URL. httptools' own modes get a CF 403 and then bounce
                # through the (also CF-blocked) worker proxy, losing the redirect.
                try:
                    from lib import requests as _rq
                    _ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
                    sess = _rq.Session()
                    rr = sess.get(page_url, headers={'User-Agent': _ua,
                                                     'Referer': 'https://uprot.net/'},
                                  timeout=20, allow_redirects=True)
                    html = rr.text or ''
                    furl = rr.url or ''
                except Exception as e:
                    logger.info('maxstream._get_embed_page uprots[raw] error: %s' % e)
                    return None, None, False
                logger.info('maxstream._get_embed_page uprots[raw] final_url=%r snippet=%r'
                            % (furl, html[:100]))
                if _is_dead(html):
                    return None, None, True
                if not _re.search(r'/watch_?free/', furl) and html:
                    m = scrapertools.find_single_match(
                        html, r'(https?://[^\s"\'<>]+/watch_?free/[^\s"\'<>]+)')
                    if m:
                        furl = m
                return html, furl, False

            kw = dict(follow_redirects=True, headers={'Referer': 'https://uprot.net/'})
            if mode == 'plain':
                kw['use_requests'] = True
            elif mode == 'cs':
                kw['cloudscraper'] = True
            try:
                r = httptools.downloadpage(page_url, **kw)
            except Exception as e:
                # cloudscraper/DNS can raise; let the caller fall back to the next mode.
                logger.info('maxstream._get_embed_page uprots[%s] download error: %s'
                            % (mode, e))
                return None, None, False
            html = getattr(r, 'data', '') or ''
            furl = getattr(r, 'url', '') or ''
            logger.info('maxstream._get_embed_page uprots[%s] final_url=%r snippet=%r'
                        % (mode, furl, html[:100]))
            if _is_dead(html):
                return None, None, True  # (html, final_url, is_dead)
            # Find watchfree URL: either resp.url (when redirect was followed),
            # or inside the HTML body (meta-refresh / JS redirect / iframe from proxy).
            # The host now uses the path "/watch_free/" (underscore); accept both.
            if not _re.search(r'/watch_?free/', furl) and html:
                m = scrapertools.find_single_match(
                    html, r'(https?://[^\s"\'<>]+/watch_?free/[^\s"\'<>]+)')
                if m:
                    furl = m
                    logger.info('maxstream._get_embed_page uprots watchfree in HTML: %r' % furl)
            return html, furl, False

        final_url = ''
        for mode in ('raw', 'plain', 'cs', 'default'):
            html_uprots, final_url, dead = _try_uprots(mode)
            if dead:
                return None
            if _re.search(r'/watch_?free/', final_url or ''):
                break

        if _re.search(r'/watch_?free/', final_url or ''):
            # watchfree path: /watch_free/VIEW_ID/FILE_ID/TOKEN
            # FILE_ID (parts[2]) is the id used by emhuih, NOT the view/movie id (parts[1]).
            # parts[1] is session-specific and changes per request; parts[2] is stable.
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
        # uprot.net/msf/TOKEN now gates the real maxstream.video/uprots/ links
        # behind a 3-digit numeric image captcha (validated in the PHP session).
        # lib.uprot_captcha solves it with a pure-stdlib OCR (decode+segment+match)
        # and POSTs the answer, returning the HTML that embeds the /uprots/ links.
        from lib import uprot_captcha
        html_uprot = uprot_captcha.solve_uprot(page_url, httptools.downloadpage) or ''
        if not html_uprot:
            logger.info('maxstream._get_embed_page uprot/msf: captcha not solved')
            return None
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

