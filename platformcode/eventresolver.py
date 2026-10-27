# -*- coding: utf-8 -*-
"""Prippi-owned event-page resolver. No imports or files from other add-ons.

Handles direct HLS, ordinary iframe chains, packed player scripts and the
public player configuration delivered to a browser. It does not bypass DRM,
CAPTCHAs or HTTP authorization failures.
"""
import base64
import html
import http.cookiejar
import json
import math
import re
import time
from urllib.parse import urljoin, urlsplit, unquote_plus
from urllib.request import Request, build_opener, HTTPCookieProcessor

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/116.0'


def unpack_scripts(page):
    try:
        try:
            from lib import jsunpack
        except ImportError:
            import jsunpack
        for script in re.findall(r'<script[^>]*>(.*?)</script>', page, re.I | re.S):
            if jsunpack.detect(script):
                try:
                    page += '\n' + jsunpack.unpack(script)
                except Exception:
                    pass
    except ImportError:
        pass
    return page


def _decode64(value):
    value = re.sub(r'[^A-Za-z0-9+/=]', '', value)
    return base64.b64decode(value + '=' * (-len(value) % 4))


def page_streams(page):
    """Extract declared media URLs, never execute page-supplied JavaScript."""
    page = unpack_scripts(page).replace('\\/', '/')
    found = re.findall(r'''["'](https?://[^"'<>\s]+\.m3u8[^"'<>\s]*)["']''', page, re.I)
    for payload in re.findall(r'''(?:window\.)?atob\(\s*["']([A-Za-z0-9+/=]+)["']\s*\)''', page):
        try:
            value = _decode64(payload).decode('utf-8')
            if value.startswith(('https://', 'http://')) and '.m3u8' in value:
                found.append(value)
        except Exception:
            pass
    for payload in re.findall(r'''window\._econfig\s*=\s*["']([A-Za-z0-9+/=]+)["']''', page):
        try:
            outer = _decode64(payload).decode('latin-1')
            width = int(math.ceil(len(outer) / 4.0))
            slots = [b''] * 4
            for index, target in enumerate((2, 0, 3, 1)):
                part = outer[index * width:(index + 1) * width]
                slots[target] = _decode64(part[:3] + part[4:])
            config = json.loads(_decode64(b''.join(slots).decode('latin-1')).decode('utf-8'))
            for key in ('stream_url', 'stream_url_nop2p', 'src', 'url', 'file', 'hls', 'source'):
                value = config.get(key)
                if isinstance(value, str) and value.startswith(('http://', 'https://')):
                    found.append(value)
        except Exception:
            pass
    return list(dict.fromkeys(html.unescape(value) for value in found))


def resolve(url, headers=None, fetch=None, budget=14, active=lambda: True, request_timeout=5):
    """Return media candidates with the final embed's referer and cookies."""
    url, _, pipe = url.partition('|')
    initial_headers = dict(headers or {})
    for pair in pipe.split('&'):
        key, sep, value = pair.partition('=')
        if sep:
            initial_headers[unquote_plus(key).lstrip('!')] = unquote_plus(value)
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    initial_headers.setdefault('User-Agent', UA)

    def load(target, request_headers):
        with opener.open(Request(target, headers=request_headers),
                         timeout=min(request_timeout, max(0.1, deadline - time.monotonic()))) as response:
            data = response.read(2 * 1024 * 1024).decode('utf-8', 'replace')
            return response.geturl(), data

    fetch = fetch or load
    pending, seen = [(url, initial_headers.get('Referer', ''))], set()
    deadline = time.monotonic() + budget
    while pending and len(seen) < 6 and time.monotonic() < deadline and active():
        target, ref = pending.pop(0)
        if target in seen or not target.startswith(('http://', 'https://')):
            continue
        seen.add(target)
        request_headers = dict(initial_headers)
        if ref:
            request_headers['Referer'] = ref
            parsed = urlsplit(ref)
            request_headers['Origin'] = parsed.scheme + '://' + parsed.netloc
        if '.m3u8' in target.lower().split('?', 1)[0]:
            return [dict(url=target, headers=request_headers, kind='hls')]
        try:
            final, page = fetch(target, request_headers)
        except Exception:
            continue
        if page.lstrip().startswith('#EXTM3U'):
            return [dict(url=final, headers=request_headers, kind='hls')]
        media = page_streams(page)
        if media:
            parsed = urlsplit(final)
            stream_headers = {'User-Agent': request_headers['User-Agent'], 'Referer': final,
                              'Origin': parsed.scheme + '://' + parsed.netloc}
            cookie_request = Request(media[0])
            jar.add_cookie_header(cookie_request)
            if cookie_request.get_header('Cookie'):
                stream_headers['Cookie'] = cookie_request.get_header('Cookie')
            return [dict(url=value, kind='hls', headers=dict(stream_headers)) for value in media]
        embeds = re.findall(r'''<iframe[^>]+\bsrc\s*=\s*["']([^"']+)["']''', page, re.I | re.S)
        # Main player is conventionally last; preserve alternative embeds too.
        pending = [(urljoin(final, html.unescape(value)), final) for value in reversed(embeds)] + pending
    return []
