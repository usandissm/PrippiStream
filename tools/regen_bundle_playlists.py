# -*- coding: utf-8 -*-
"""Rebuild seekable byte-range HLS playlists for offline download bundles.

Bundles created before per-segment boundaries were recorded have a single
#EXTINF spanning the whole movie in v.m3u8 / a*.m3u8. HLS seeking is
segment-granular, so a single huge segment is NOT seekable: the player re-opens
segment 0 from the start on every timeline click and a separate audio rendition
stalls (no sound after an arrow-key skip).

This tool splits each concatenated .ts into TS-packet-aligned byte windows with
proportional durations and rewrites the playlist with EXT-X-BYTERANGE — giving
real seek granularity into the single file (the local stream server already
serves arbitrary byte ranges and decrypts by absolute offset). Durations come
from bundle.json. It is idempotent: a playlist already using EXT-X-BYTERANGE is
left untouched.

NOTE: durations here are proportional to bytes (approximate for VBR streams), so
seeks land within a few seconds of the target — good enough, and crucially it
fixes the restart-from-zero and audio-stall behaviour. New downloads record
exact per-segment boundaries and don't need this.

Usage:
  python tools/regen_bundle_playlists.py [BUNDLE_DIR | DOWNLOADS_DIR] ...
With no args, uses the default Kodi addon_data downloads path on this machine.
"""

from __future__ import division

import json
import math
import os
import sys

_TS_PACKET = 188
_TARGET_SEG = 6.0   # seconds; segment granularity for seeking


def _byterange_segments(size, duration, target=_TARGET_SEG):
    """Split *size* bytes / *duration* seconds into TS-packet-aligned windows.
    Returns [[seg_duration, byte_len], ...] in file order, summing to size."""
    duration = float(duration or 0) or float(max(1, size // 1000000))
    nseg = max(1, int(round(duration / target)))
    step = max(_TS_PACKET, (max(1, size // nseg) // _TS_PACKET) * _TS_PACKET)
    segs = []
    off = 0
    while off < size:
        length = min(step, size - off)
        if 0 < size - (off + length) < _TS_PACKET:   # absorb a sub-packet tail
            length = size - off
        segs.append([round(duration * (length / float(size)), 3), length])
        off += length
    return segs


def _m3u8_byterange(resource, segments):
    maxd = max((float(s[0]) for s in segments), default=1.0)
    td = max(1, int(math.ceil(maxd or 1)))
    lines = [u'#EXTM3U', u'#EXT-X-VERSION:4',
             u'#EXT-X-TARGETDURATION:%d' % td, u'#EXT-X-PLAYLIST-TYPE:VOD']
    offset = 0
    for dur, length in segments:
        length = int(length)
        lines.append(u'#EXTINF:%.3f,' % float(dur))
        lines.append(u'#EXT-X-BYTERANGE:%d@%d' % (length, offset))
        lines.append(resource)
        offset += length
    lines.append(u'#EXT-X-ENDLIST')
    return u'\n'.join(lines) + u'\n'


def _needs_regen(playlist_path):
    try:
        with open(playlist_path, 'r', encoding='utf-8') as f:
            txt = f.read()
    except Exception:
        return False
    return '#EXT-X-BYTERANGE' not in txt   # already byte-range → skip


def _regen_track(bundle_dir, playlist_name, ts_name, resource, duration):
    pl = os.path.join(bundle_dir, playlist_name)
    ts = os.path.join(bundle_dir, ts_name)
    if not os.path.exists(pl) or not os.path.exists(ts):
        return None
    if not _needs_regen(pl):
        print('    %-10s already byte-range, skipped' % playlist_name)
        return None
    size = os.path.getsize(ts)
    segs = _byterange_segments(size, duration)
    with open(pl, 'w', encoding='utf-8') as f:
        f.write(_m3u8_byterange(resource, segs))
    print('    %-10s -> %d segments (%d bytes, %.0fs)'
          % (playlist_name, len(segs), size, duration))
    return len(segs)


def regen_bundle(bundle_dir):
    """Rebuild the byte-range playlists for one bundle directory."""
    meta_path = os.path.join(bundle_dir, 'bundle.json')
    if not os.path.exists(meta_path):
        print('  %s: no bundle.json, skipped' % bundle_dir)
        return False
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    vdur = (meta.get('video') or {}).get('duration') or 0
    print('  %s' % os.path.basename(bundle_dir))
    _regen_track(bundle_dir, 'v.m3u8', 'video.ts', 'v', vdur)
    for a in meta.get('audio') or []:
        idx = a.get('idx')
        _regen_track(bundle_dir, 'a%d.m3u8' % idx, 'audio.%d.ts' % idx,
                     'a%d' % idx, a.get('duration') or vdur)
    return True


def _is_bundle(d):
    return os.path.isfile(os.path.join(d, 'master.m3u8'))


def _default_downloads_dir():
    base = os.environ.get('APPDATA', '')
    return os.path.join(base, 'Kodi', 'userdata', 'addon_data',
                        'plugin.video.prippistream', 'downloads')


def main(argv):
    targets = argv[1:] or [_default_downloads_dir()]
    n = 0
    for t in targets:
        if not os.path.isdir(t):
            print('not a directory: %s' % t)
            continue
        if _is_bundle(t):
            n += 1 if regen_bundle(t) else 0
        else:                       # a downloads root → scan for bundles
            print('scanning %s' % t)
            for name in sorted(os.listdir(t)):
                d = os.path.join(t, name)
                if os.path.isdir(d) and _is_bundle(d):
                    n += 1 if regen_bundle(d) else 0
    print('done: %d bundle(s) processed' % n)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
