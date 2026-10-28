# -*- coding: utf-8 -*-
"""Small real-network availability checks, not a claim of video decoding.

No player is opened: read the HLS manifest and at most 1 KiB of one segment.
HTTP authorization failures are failures; no challenge/auth/TLS bypasses.
"""
import http.cookiejar
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, build_opener, HTTPCookieProcessor


def hls_reachable(source, open_url=None, active=lambda: True, deadline=None):
    """True=manifest+segment reachable; False=rejected/broken; None=inconclusive."""
    deadline = deadline if deadline is not None else time.monotonic() + 8
    headers = dict(source.get('headers') or {})
    headers.setdefault('User-Agent', 'Mozilla/5.0')
    open_url = open_url or build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar())).open

    def read(url, segment=False):
        if not active() or time.monotonic() >= deadline:
            raise TimeoutError('availability budget exhausted')
        request_headers = dict(headers)
        if segment:
            request_headers['Range'] = 'bytes=0-1023'
        timeout = min(3, max(0.1, deadline - time.monotonic()))
        with open_url(Request(url, headers=request_headers), timeout=timeout) as response:
            status = getattr(response, 'status', 200)
            if status not in (200, 206):
                raise HTTPError(url, status, 'unavailable', response.headers, None)
            return response.geturl(), response.headers.get('Content-Type', '').lower(), response.read(1024 if segment else 256 * 1024)

    def manifest(url, depth=0):
        if depth > 2:
            return None
        final, kind, data = read(url)
        text = data.decode('utf-8-sig', 'replace').strip()
        if not text.startswith('#EXTM3U') or 'text/html' in kind:
            return False
        # SAMPLE-AES/DRM can require a real player. Do not label it offline merely
        # because this bounded, non-playing check cannot establish availability.
        if re.search(r'#EXT-X-KEY:[^\r\n]*(?:METHOD=SAMPLE-AES|KEYFORMAT=)', text):
            return None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if '#EXT-X-STREAM-INF:' in text:
            variants = [lines[i + 1] for i, line in enumerate(lines[:-1])
                        if line.startswith('#EXT-X-STREAM-INF:') and not lines[i + 1].startswith('#')]
            unknown = False
            for value in variants[:3]:
                try:
                    result = manifest(urljoin(final, value), depth + 1)
                except (TimeoutError, ssl.SSLError):
                    result = None
                except (HTTPError, URLError, OSError):
                    result = False
                if result is True:
                    return True
                unknown = unknown or result is None
            return None if unknown or len(variants) > 3 else False
        segments = [line for line in lines if not line.startswith('#')]
        if not segments:
            return False
        _, kind, fragment = read(urljoin(final, segments[-1]), segment=True)
        return bool(fragment and 'text/html' not in kind and 'application/json' not in kind
                    and not fragment.lstrip().lower().startswith((b'<html', b'<!doctype', b'{"error')))

    try:
        return manifest(source['url'])
    except HTTPError:
        return False
    except (TimeoutError, ssl.SSLError):
        return None
    except URLError as exc:
        return None if isinstance(exc.reason, ssl.SSLError) else False
    except (OSError, ValueError, KeyError):
        return False


def check(sources, resolve, active=lambda: True, budget=18, probe=hls_reachable):
    """Try alternatives within a bounded budget; do not mistake untested for dead."""
    deadline = time.monotonic() + budget
    unknown = False
    for source in sources:
        if not active() or time.monotonic() >= deadline:
            return None
        try:
            candidates = ([source] if source.get('kind') == 'hls' else
                          resolve(source, min(8, max(0.1, deadline - time.monotonic()))))
            for candidate in candidates:
                if not active() or time.monotonic() >= deadline:
                    return None
                result = probe(candidate, active=active, deadline=deadline)
                if result is True:
                    return True
                unknown = unknown or result is None
        except Exception:
            unknown = True
    return None if unknown else False
