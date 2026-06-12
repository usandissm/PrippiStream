# -*- coding: utf-8 -*-
"""
"In onda adesso" EPG for the live SKY/Sport rows.

Pulls the *currently airing* programme for the live channels shown on the
Netflix-style home, from Sky Italia's official guide API
(https://apid.sky.it/gtv/v1, env=DTH — no auth, no Cloudflare, plain GET).

Design goals (mirror sportchannels.py):
  * Only channels that are already ONLINE and visible in a row get enriched —
    the home passes us their titles; we never probe channels on our own.
  * All network work happens off the GUI thread.  The home prefetches a whole
    row in one batched /events call, fills an in-memory cache, and the hero
    reads it instantly (no per-focus network).
  * Graceful degradation: any channel we can't map (Zona DAZN, FIFA+, +1
    timeshifts, …) simply returns None and the hero falls back to its normal
    look — nothing breaks.

Public API:
  prefetch(titles)            -> fetch + cache "now on air" for these channels
  now_on(title)               -> cached {prog,start,end,synopsis} or None
"""

import json
import os
import re
import threading
import time

try:
    from urllib.request import Request, urlopen
    from urllib.parse import quote
except ImportError:  # py2
    from urllib2 import Request, urlopen
    from urllib import quote

from platformcode import config, logger

# ── Sky guide API ─────────────────────────────────────────────────────────────
_API = "https://apid.sky.it/gtv/v1"
_ENV = "DTH"                       # the only env value the API accepts
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")

# Channel name/number → Sky id map, cached on disk for a day (rarely changes).
_CHANNELS_TTL = 24 * 3600
_channels_file = None
_id_by_norm = {}     # normalized channel name -> sky id
_id_by_num = {}      # channel number (int)    -> sky id
_chan_loaded_ts = 0
_chan_lock = threading.Lock()

# "Now on air" cache: normalized title -> {prog,start,end,synopsis,until}
# 'until' is the programme's end epoch — entry is stale once we pass it.
_epg_cache = {}
_epg_lock = threading.Lock()

# Aliases for channels whose Sky guide name differs from our row title.
_NAME_ALIASES = {
    'mtv': 'mtv hd',
    'zonadazn': 'dazn 1',   # "Zona DAZN" in Sport row → "DAZN 1" in Sky EPG
}

# Channels whose EPG name changes dynamically (thematic branded slots).
# Map our normalised title directly to the fixed DTH channel number.
_NORM_TO_NUMBER = {
    'collection':       303,   # Sky Collection      → ch 303 (Sky Cinema Collection slot)
    'cinemacollection': 303,   # Sky Cinema Collection → ch 303
}


def _data_file():
    global _channels_file
    if _channels_file is None:
        try:
            _channels_file = os.path.join(config.get_data_path(), "skyepg_channels.json")
        except Exception:
            _channels_file = None
    return _channels_file


def _norm(name):
    """Normalize a channel name for matching: drop 'sky'/'hd'/punctuation."""
    if not name:
        return ''
    s = name.lower()
    s = s.replace('+', ' plus ')
    s = re.sub(r'\bhd\b', '', s)
    s = s.replace('sky', '').replace('channel', '')
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s


def _http_json(url, timeout=12):
    try:
        resp = urlopen(Request(url, headers={'User-Agent': _UA}), timeout=timeout)
        data = resp.read()
        resp.close()
        if isinstance(data, bytes):
            data = data.decode('utf-8', 'replace')
        return json.loads(data)
    except Exception as exc:
        logger.error('[SkyEPG] http_json %s: %s' % (url, str(exc)))
        return None


# ── channel map ───────────────────────────────────────────────────────────────
def _load_channels_disk():
    f = _data_file()
    if not f or not os.path.exists(f):
        return None
    try:
        if (time.time() - os.path.getmtime(f)) > _CHANNELS_TTL:
            return None
        with open(f, 'r') as fh:
            return json.load(fh)
    except Exception:
        return None


def _save_channels_disk(channels):
    f = _data_file()
    if not f:
        return
    try:
        with open(f, 'w') as fh:
            json.dump(channels, fh)
    except Exception as exc:
        logger.error('[SkyEPG] save channels: %s' % str(exc))


def _ensure_channels():
    """Populate _id_by_norm / _id_by_num from disk cache or the live API."""
    global _chan_loaded_ts
    with _chan_lock:
        if _id_by_norm and (time.time() - _chan_loaded_ts) < _CHANNELS_TTL:
            return True
        channels = _load_channels_disk()
        if channels is None:
            data = _http_json("%s/channels?env=%s" % (_API, _ENV))
            if not data or 'channels' not in data:
                return bool(_id_by_norm)  # keep whatever we had
            channels = [{'id': c.get('id'), 'name': c.get('name'),
                         'number': c.get('number')} for c in data['channels']]
            _save_channels_disk(channels)
            logger.info('[SkyEPG] channel map fetched: %d channels' % len(channels))
        _id_by_norm.clear()
        _id_by_num.clear()
        for c in channels:
            cid = c.get('id')
            if cid is None:
                continue
            nm = _norm(c.get('name'))
            if nm and nm not in _id_by_norm:
                _id_by_norm[nm] = cid
            num = c.get('number')
            if num is not None and num not in _id_by_num:
                _id_by_num[num] = cid
        _chan_loaded_ts = time.time()
        return bool(_id_by_norm)


def channel_id_for(title):
    """Sky channel id for one of our row titles, or None if not mappable."""
    if not _ensure_channels():
        return None
    nm = _norm(title)
    cid = _id_by_norm.get(nm)
    if cid is None and nm in _NAME_ALIASES:
        cid = _id_by_norm.get(_norm(_NAME_ALIASES[nm]))
    if cid is None:
        # numbered event channels: "Sky Sport 251".."259" -> number 251..259
        m = re.search(r'\b(2[0-9][0-9])\b', title or '')
        if m:
            cid = _id_by_num.get(int(m.group(1)))
    if cid is None:
        # channels with a dynamic EPG name (e.g. thematic/collection slots):
        # look up by the fixed DTH channel number instead
        override_num = _NORM_TO_NUMBER.get(nm)
        if override_num is not None:
            cid = _id_by_num.get(override_num)
    return cid


# ── events / "now on air" ─────────────────────────────────────────────────────
def _utc_now():
    return time.time()


def _parse_iso_utc(s):
    """'2026-06-12T09:30:00Z' -> epoch seconds (UTC)."""
    try:
        t = time.strptime(s.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
        # calendar.timegm avoids local-tz offset that time.mktime would apply
        import calendar
        return calendar.timegm(t)
    except Exception:
        return None


def _fmt_local(epoch):
    """epoch (UTC) -> 'HH:MM' in the box's local time."""
    try:
        return time.strftime('%H:%M', time.localtime(epoch))
    except Exception:
        return ''


def prefetch(titles):
    """Fetch the currently-airing programme for every mappable title in one
    batched /events call and store it in _epg_cache.  Safe to call from a
    background thread; returns the number of channels enriched."""
    if not titles:
        return 0
    # title -> sky id (skip unmappable channels silently)
    id_for = {}
    for t in titles:
        cid = channel_id_for(t)
        if cid:
            id_for[t] = cid
    if not id_for:
        return 0
    # The API returns events whose *starttime* falls in [from,to], so a tight
    # window misses the programme already on air (it started earlier).  Widen to
    # 6h back (covers long live sport) → 5min ahead, then filter to "now" below.
    now = _utc_now()
    frm = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now - 6 * 3600))
    to = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now + 300))
    ids = ','.join(str(v) for v in sorted(set(id_for.values())))
    url = ("%s/events?from=%sZ&to=%sZ&pageSize=400&pageNum=0&env=%s&channels=%s"
           % (_API, quote(frm), quote(to), _ENV, ids))
    data = _http_json(url, timeout=12)
    if not data or 'events' not in data:
        return 0
    # sky id -> currently-airing event
    cur_by_id = {}
    for ev in data['events']:
        ch = ev.get('channel') or {}
        cid = ch.get('id')
        st = _parse_iso_utc(ev.get('starttime') or '')
        en = _parse_iso_utc(ev.get('endtime') or '')
        if cid is None or st is None or en is None:
            continue
        if st <= now < en:
            cur_by_id[cid] = (ev, st, en)
    n = 0
    with _epg_lock:
        for t, cid in id_for.items():
            hit = cur_by_id.get(cid)
            if not hit:
                continue
            ev, st, en = hit
            epg_title = (ev.get('epgEventTitle') or '').strip()
            event_title = (ev.get('eventTitle') or '').strip()
            # epgEventTitle format: "S2 Ep7 - Show Name"  →  extract show name
            # For movies (no episode) epgEventTitle == eventTitle, no " - "
            if ' - ' in epg_title:
                # Part after last " - " is the show/series name
                show = epg_title.rsplit(' - ', 1)[-1].strip()
                ep_info = epg_title.rsplit(' - ', 1)[0].strip()  # e.g. "S2 Ep7"
                # ep_title is the episode name (eventTitle), shown below show name
                ep_title = event_title if event_title and event_title != show else ''
            else:
                show = event_title or epg_title
                ep_info = ''
                ep_title = ''
            if not show:
                continue
            _epg_cache[_norm(t)] = {
                'prog': show,           # main show/movie title
                'ep_info': ep_info,     # "S2 Ep7"
                'ep_title': ep_title,   # episode name
                'start': _fmt_local(st),
                'end': _fmt_local(en),
                'synopsis': (ev.get('eventSynopsis') or '').strip(),
                'until': en,
            }
            n += 1
    logger.info('[SkyEPG] prefetch: %d/%d channels now-on-air' % (n, len(id_for)))
    return n


def now_on(title):
    """Cached 'now on air' info for a channel title, or None.

    Returns {'prog','start','end','synopsis'} when a fresh programme is known;
    drops the entry once its end time has passed."""
    with _epg_lock:
        e = _epg_cache.get(_norm(title))
        if not e:
            return None
        if _utc_now() >= e.get('until', 0):
            _epg_cache.pop(_norm(title), None)
            return None
        return {'prog': e['prog'], 'ep_info': e.get('ep_info', ''),
                'ep_title': e.get('ep_title', ''), 'start': e['start'],
                'end': e['end'], 'synopsis': e['synopsis']}
