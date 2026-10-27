# -*- coding: utf-8 -*-
"""Bounded metadata-only HLS quality inspection. Never fetch video segments."""
import queue
import re
import threading
import time
from urllib.parse import unquote_plus
from urllib.request import Request, urlopen


def parse_hls(text):
    """Maximum declared rendition height/bitrate, not a claim of playback."""
    if not text.lstrip('\ufeff\r\n ').startswith('#EXTM3U'):
        return 0, 0
    variants = []
    for line in text.splitlines():
        if not line.startswith('#EXT-X-STREAM-INF:'):
            continue
        size = re.search(r'RESOLUTION\s*=\s*(\d+)x(\d+)', line, re.I)
        bandwidth = re.search(r'(?:^|[:,])\s*(?:AVERAGE-)?BANDWIDTH\s*=\s*(\d+)', line)
        variants.append((int(size[2]) if size else 0,
                         int(bandwidth[1]) if bandwidth else 0))
    return max(variants, default=(0, 0))


def inspect(path, timeout=4):
    url, _, suffix = path.partition('|')
    headers = {'User-Agent': 'Mozilla/5.0'}
    for pair in suffix.split('&'):
        key, sep, value = pair.partition('=')
        key = unquote_plus(key).lstrip('!')
        if sep and key.casefold() in ('referer', 'origin', 'user-agent', 'cookie', 'authorization'):
            headers[key] = unquote_plus(value)
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            content_type = response.headers.get('Content-Type', '').lower()
            # No progressive-video reads: quality is unknown without a manifest.
            if '.m3u8' not in url.lower() and not any(x in content_type for x in ('mpegurl', 'text/plain')):
                return 0, 0
            return parse_hls(response.read(256 * 1024).decode('utf-8', 'replace'))
    except Exception:
        return 0, 0


def prepare(sources, resolve, active=lambda: True, budget=18, probe=inspect):
    """Resolve/probe with two daemon workers; unfinished sources stay lazy.

    Results are local to this click: no signed URL is persisted. The original
    master playlist is retained, preserving external audio/subtitle groups and
    the player's adaptive bitrate rather than forcing a silent child playlist.
    """
    jobs = queue.Queue()
    for index, source in enumerate(sources):
        jobs.put((index, source))
    results, lock, stop = {}, threading.Lock(), threading.Event()

    def worker():
        while not stop.is_set() and active():
            try:
                index, source = jobs.get_nowait()
            except queue.Empty:
                return
            try:
                li = resolve(source)
                probe_path = li.getPath() if li else ''
                if li and '|' not in probe_path:
                    stream_headers = li.getProperty('inputstream.adaptive.manifest_headers')
                    if stream_headers:
                        probe_path += '|' + stream_headers
                quality = probe(probe_path) if li and not stop.is_set() else (0, 0)
            except Exception:
                li, quality = None, (0, 0)
            with lock:
                results[index] = (source, li, quality)

    workers = [threading.Thread(target=worker, daemon=True) for _ in range(min(2, len(sources)))]
    for thread in workers:
        thread.start()
    deadline = time.monotonic() + budget
    while any(t.is_alive() for t in workers) and active() and time.monotonic() < deadline:
        stop.wait(0.1)
    stop.set()
    with lock:
        snapshot = dict(results)
    ranked = []
    for index, source in enumerate(sources):
        if index in snapshot:
            src, li, quality = snapshot[index]
            if li:
                ranked.append((src, li, quality))
        else:
            ranked.append((source, None, (0, 0)))
    ranked.sort(key=lambda value: (-value[2][0], -value[2][1],
                                  1 if value[0].get('_origin') == 'calendar' else 0))
    return ranked
