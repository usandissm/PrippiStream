# -*- coding: utf-8 -*-
"""
"In onda adesso" EPG for the live SKY/Sport rows.

Pulls the *currently airing* programme for the live channels shown on the
Prippi-style home, from Sky Italia's official guide API
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
    from html import unescape as _html_unescape
except ImportError:  # py2
    from HTMLParser import HTMLParser
    _html_unescape = HTMLParser().unescape
try:
    from concurrent.futures import ThreadPoolExecutor
except ImportError:
    ThreadPoolExecutor = None

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

_SUPERGUIDE_URLS = (
    'https://www.superguidatv.it/ora-in-onda/',
    'https://www.superguidatv.it/ora-in-onda/sky-cinema/',
    'https://www.superguidatv.it/ora-in-onda/sky-intrattenimento/',
    'https://www.superguidatv.it/ora-in-onda/sky-doc-e-lifestyle/',
    'https://www.superguidatv.it/ora-in-onda/sky-sport/',
    'https://www.superguidatv.it/ora-in-onda/sky-news/',
    'https://www.superguidatv.it/ora-in-onda/dazn/',
)
_TVEPG_URLS = (
    'https://tvepg.eu/it/italia/c/eurosport-1',
    'https://tvepg.eu/it/italia/c/eurosport-2',
)
_RAIPLAY_NOW_URL = 'https://www.raiplay.it/palinsesto/onAir.json'
_MEDIASET_NOW_URL = 'https://static3.mediasetplay.mediaset.it/apigw/nownext/nownext.json'
_superguide_cache = {}
_superguide_loaded_at = 0
_superguide_lock = threading.Lock()
_SUPERGUIDE_TTL = 3 * 60
_GUIDE_ENTRY_TTL = 5 * 60
_prefetch_guard = threading.Lock()
_prefetch_running = False
_last_prefetch_at = 0

# Aliases for channels whose Sky guide name differs from our row title.
_NAME_ALIASES = {
    'mtv': 'mtv hd',
    'zonadazn': 'dazn 1',   # "Zona DAZN" in Sport row → "DAZN 1" in Sky EPG
}

_SUPERGUIDE_ALIASES = {
    'raiuno': 'rai1', 'raidue': 'rai2', 'raitre': 'rai3',
    'retequattro': 'rete4', 'canale5italia': 'canale5',
    'italiauno': 'italia1', 'la7d': 'la7d',
    'discoverygialloitalia': 'giallo', 'discoverygiallo': 'giallo',
    'skycomedycentral': 'comedycentral', 'crimeinv': 'crimeinvestigation',
    'skynba': 'skysportbasket', 'skybasket': 'skysportbasket',
    'dazn1': 'dazn', 'rmc': 'radiomontecarlo', 'tgcom': 'tgcom24',
    'la7d': 'la7cinema', 'motortrend': 'discoveryturbo',
    'homeandgardentv': 'hgtvhomegarden', 'hgtv': 'hgtvhomegarden',
    'warnertv': 'discovery',
}

# Channels whose EPG name changes dynamically (thematic branded slots).
# Map our normalised key directly to the fixed DTH channel number.
# NOTE: deliberately NO 'collection' → 303 entry. "Sky Collection" is a distinct
# pop-up ENTERTAINMENT channel (airs series, e.g. "Delitti ai Tropici"), NOT
# "Sky Cinema Collection" (303). It has no stable DTH-guide entry, so it gets no EPG
# — correct: better no data than another channel's data.
_NORM_TO_NUMBER = {
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


def _http_json(url, timeout=12, quiet=False):
    try:
        resp = urlopen(Request(url, headers={'User-Agent': _UA}), timeout=timeout)
        data = resp.read()
        resp.close()
        if isinstance(data, bytes):
            data = data.decode('utf-8', 'replace')
        return json.loads(data)
    except Exception as exc:
        if not quiet:
            logger.error('[SkyEPG] http_json %s: %s' % (url, str(exc)))
        return None


def _http_text(url, timeout=12, quiet=False):
    try:
        resp = urlopen(Request(url, headers={'User-Agent': _UA,
                                             'Accept-Language': 'it-IT,it;q=0.9'}), timeout=timeout)
        data = resp.read()
        resp.close()
        if isinstance(data, bytes):
            data = data.decode('utf-8', 'replace')
        return data
    except Exception as exc:
        if not quiet:
            logger.error('[SkyEPG] http_text %s: %s' % (url, str(exc)))
        return ''


_SG_CHANNEL_RE = re.compile(
    r'<a[^>]+href="/programmazione-canale/[^"]+/[^/]+/(\d+)/"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+href="/programmazione-canale/|$)',
    re.I | re.S)
_SG_NAME_RE = re.compile(r'<img[^>]+alt="([^"]+)"', re.I)
_SG_ITEM_RE = re.compile(
    r'<p[^>]*class="[^"]*font-bold[^"]*"[^>]*>\s*(\d{1,2}:\d{2})\s*</p>.*?'
    r'<p[^>]*class="[^"]*truncate[^"]*text-(?:lg|base)[^"]*"[^>]*>(.*?)</p>',
    re.I | re.S)
_TAG_RE = re.compile(r'<[^>]+>')
_TVEPG_NAME_RE = re.compile(r'<h3[^>]*>(.*?)</h3>', re.I | re.S)
_TVEPG_ROW_RE = re.compile(r'<tr>(.*?)</tr>', re.I | re.S)
_TVEPG_TITLE_RE = re.compile(r'<a[^>]+title="(\d{1,2}:\d{2})\s+([^"]+)"', re.I | re.S)


def _clean_html(value):
    return re.sub(r'\s+', ' ', _html_unescape(_TAG_RE.sub('', value or ''))).strip()


def _parse_superguide(html):
    result = {}
    for _cid, header, body in _SG_CHANNEL_RE.findall(html or ''):
        name_match = _SG_NAME_RE.search(header)
        if not name_match:
            continue
        programmes = [(clock, _clean_html(title)) for clock, title in _SG_ITEM_RE.findall(body)]
        programmes = [(clock, title) for clock, title in programmes if title]
        if not programmes:
            continue
        key = _norm(_clean_html(name_match.group(1)))
        current = programmes[0]
        entry = {'prog': current[1], 'start': current[0], 'end': '',
                 'synopsis': '', 'until': time.time() + _GUIDE_ENTRY_TTL,
                 'source': 'superguidatv'}
        # Some event channels expose simultaneous tiles with the same start:
        # they are alternatives, not a real "next" programme.
        if len(programmes) > 1 and programmes[1][0] != current[0]:
            entry['end'] = programmes[1][0]
            entry['next_start'] = programmes[1][0]
            entry['next_prog'] = programmes[1][1]
        result[key] = entry
    return result


def _parse_tvepg(html):
    """Parse the dedicated Eurosport schedule pages (current + next row)."""
    name_match = _TVEPG_NAME_RE.search(html or '')
    rows = _TVEPG_ROW_RE.findall(html or '')
    if not name_match or not rows:
        return {}
    current_index = next((i for i, row in enumerate(rows) if 'progress-bar' in row), None)
    if current_index is None:
        current_index = next((i for i, row in enumerate(rows) if 'id="now"' in row), None)
    if current_index is None:
        return {}
    current = _TVEPG_TITLE_RE.search(rows[current_index])
    following = (_TVEPG_TITLE_RE.search(rows[current_index + 1])
                 if current_index + 1 < len(rows) else None)
    if not current:
        return {}
    entry = {'prog': _clean_html(current.group(2)), 'start': current.group(1),
             'end': '', 'synopsis': '', 'until': time.time() + _GUIDE_ENTRY_TTL,
             'source': 'tvepg'}
    if following and following.group(1) != current.group(1):
        entry.update(end=following.group(1), next_start=following.group(1),
                     next_prog=_clean_html(following.group(2)))
    return {_norm(_clean_html(name_match.group(1))): entry}


def _clock_from_epoch(milliseconds):
    try:
        return time.strftime('%H:%M', time.localtime(float(milliseconds) / 1000.0))
    except Exception:
        return ''


def _official_free_entries():
    """Current/next data from the broadcasters themselves (Rai and Mediaset)."""
    result = {}
    rai = _http_json(_RAIPLAY_NOW_URL, quiet=True) or {}
    for channel in rai.get('on_air', []):
        current = channel.get('currentItem') or {}
        following = channel.get('nextItem') or {}
        name = channel.get('channel') or current.get('channel')
        if not name or not current.get('name'):
            continue
        result[_norm(name)] = {
            'prog': current.get('name'), 'start': current.get('hour', ''),
            'end': following.get('hour', ''), 'synopsis': current.get('description', ''),
            'next_start': following.get('hour', ''), 'next_prog': following.get('name', ''),
            'until': time.time() + _GUIDE_ENTRY_TTL, 'source': 'raiplay'
        }

    mediaset = (_http_json(_MEDIASET_NOW_URL, quiet=True) or {}).get('response', {})
    listings = mediaset.get('listings', {})
    for station in mediaset.get('stations', {}).values():
        callsign = station.get('callSign')
        guide = listings.get(callsign, {})
        current = guide.get('currentListing') or {}
        following = guide.get('nextListing') or {}
        name = station.get('title')
        title = current.get('mediasetlisting$epgTitle') or (current.get('program') or {}).get('title')
        if not name or not title:
            continue
        entry = {
            'prog': title, 'start': _clock_from_epoch(current.get('startTime')),
            'end': _clock_from_epoch(current.get('endTime')),
            'synopsis': current.get('description', ''),
            'next_start': _clock_from_epoch(following.get('startTime')),
            'next_prog': (following.get('mediasetlisting$epgTitle') or
                          (following.get('program') or {}).get('title', '')),
            'until': time.time() + _GUIDE_ENTRY_TTL, 'source': 'mediaset'
        }
        if _norm(name) not in result:
            result[_norm(name)] = entry
    return result


def _superguide_entries(force=False):
    global _superguide_cache, _superguide_loaded_at
    now = time.time()
    with _superguide_lock:
        if _superguide_cache and not force and now - _superguide_loaded_at < _SUPERGUIDE_TTL:
            return _superguide_cache
        merged = _official_free_entries()
        if ThreadPoolExecutor:
            pool = ThreadPoolExecutor(max_workers=4)
            try:
                urls = _SUPERGUIDE_URLS + _TVEPG_URLS
                pages = list(pool.map(lambda url: _http_text(url, quiet=True), urls))
            finally:
                pool.shutdown(wait=False)
        else:
            urls = _SUPERGUIDE_URLS + _TVEPG_URLS
            pages = [_http_text(url, quiet=True) for url in urls]
        # The broadcaster feeds above are authoritative. Public guide sites fill
        # only channels which those feeds do not expose.
        for index, page in enumerate(pages):
            parsed = (_parse_superguide(page) if index < len(_SUPERGUIDE_URLS)
                      else _parse_tvepg(page))
            for key, entry in parsed.items():
                if key not in merged:
                    merged[key] = entry
        if merged:
            _superguide_cache = merged
            _superguide_loaded_at = now
            logger.info('[SkyEPG] SuperGuidaTV: %d canali' % len(merged))
        return _superguide_cache


def _superguide_for(key, entries):
    nk = _norm(key)
    candidates = [nk, _SUPERGUIDE_ALIASES.get(nk, '')]
    for candidate in candidates:
        if candidate and candidate in entries:
            return entries[candidate]
    wanted_digits = re.findall(r'\d+', nk)
    matches = [(abs(len(name) - len(nk)), value) for name, value in entries.items()
               if len(nk) >= 5 and (name in nk or nk in name)
               and re.findall(r'\d+', name) == wanted_digits]
    return min(matches, key=lambda pair: pair[0])[1] if matches else None


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
        # numbered event channels: "Sky Sport 251".."259" / par "skysport251" -> 251..259.
        # No leading \b so it also matches the digits glued to the par ("skysport251").
        m = re.search(r'(?<!\d)(2\d\d)(?!\d)', title or '')
        if m:
            cid = _id_by_num.get(int(m.group(1)))
    if cid is None:
        # channels with a dynamic EPG name (e.g. thematic/collection slots):
        # look up by the fixed DTH channel number instead
        override_num = _NORM_TO_NUMBER.get(nm)
        if override_num is not None:
            cid = _id_by_num.get(override_num)
    return cid


def _resolve(key):
    """(guide_channel_id, time_offset_seconds) for a row channel *key* — its stable
    'par' (e.g. 'skycinemacomedy') or a display title. Mapping by the par is robust
    against the backend handing us a programme name instead of the channel name
    (which left some channels with no EPG). A '+1' timeshift channel (par
    'skyunoplus' / title 'Sky Uno +1') maps to its BASE channel with a -1h offset:
    it broadcasts the base channel's schedule one hour later."""
    if not key:
        return None, 0
    nk = _norm(key)
    if nk.endswith('plus1') or nk.endswith('plus') or '+1' in key:
        base = re.sub(r'plus1?$', '', nk)            # 'unoplus' -> 'uno'
        if not _ensure_channels():
            return None, -3600
        cid = _id_by_norm.get(base)
        if cid is None and base in _NAME_ALIASES:
            cid = _id_by_norm.get(_norm(_NAME_ALIASES[base]))
        return cid, -3600
    return channel_id_for(key), 0


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


# Series episode marker at the START of epgEventTitle: "S2 Ep7 - Show Name".
_EP_RE = re.compile(r'^(S\d+\s*Ep\.?\s*\d+)\s*-\s*(.+)$')


def _parse_event(ev):
    """(show, ep_info, ep_title) from a Sky event.

    epgEventTitle is "S2 Ep7 - Show Name" for series (the SxxEpyy marker is FIRST)
    or just the title for movies.  Split on the FIRST ' - ' (after the marker) —
    the old code split from the RIGHT, which truncated show names that themselves
    contain ' - ' (e.g. 'S1 Ep8 - Online - Connessioni Pericolose' wrongly became
    'Connessioni Pericolose'): that was the "in onda" showing the wrong title."""
    epg = (ev.get('epgEventTitle') or '').strip()
    evt = (ev.get('eventTitle') or '').strip()
    m = _EP_RE.match(epg)
    if m:
        ep_info = m.group(1).strip()
        show = m.group(2).strip()
        ep_title = evt if (evt and evt != show) else ''
    else:
        show = evt or epg
        ep_info = ''
        ep_title = ''
    return show, ep_info, ep_title


def _fetch_events(ids, now):
    """Fetch the events window, shrinking the look-back until the API accepts it.

    The /events endpoint returns events whose *starttime* is in [from,to] AND it
    rejects (HTTP 422) a 'from' earlier than the start of the current broadcast
    window (empirically ~3h back late at night / the midnight boundary).  The old
    fixed 6h look-back therefore returned NOTHING at those hours → the main cause of
    a missing 'in onda'.  Try widest first (catches long live events during the day),
    then fall back to narrower windows; +5h ahead so the 'next' programme is covered."""
    to = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now + 5 * 3600))
    for back_h in (6, 3, 2, 1):
        frm = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now - back_h * 3600))
        url = ("%s/events?from=%sZ&to=%sZ&pageSize=400&pageNum=0&env=%s&channels=%s"
               % (_API, quote(frm), quote(to), _ENV, ids))
        data = _http_json(url, timeout=12, quiet=(back_h != 1))
        if data and 'events' in data:
            return data
    return None


def _prefetch(keys):
    """Fetch the currently-airing programme (plus the previous and next ones) for
    every mappable channel *key* (its stable 'par', or a title) in one batched
    /events call and store it in _epg_cache.  Safe to call from a background thread;
    returns the number of channels enriched."""
    if not keys:
        return 0
    # key -> (sky id, time offset).  Skip unmappable channels silently.
    res = {}
    for k in keys:
        cid, off = _resolve(k)
        if cid:
            res[k] = (cid, off)
    now = _utc_now()
    ids = ','.join(str(c) for c in sorted({cid for cid, _o in res.values()}))
    data = _fetch_events(ids, now) if ids else None
    if not data or 'events' not in data:
        data = {'events': []}
    # sky id -> [(start, end, event), …] sorted by start
    by_id = {}
    for ev in data['events']:
        cid = (ev.get('channel') or {}).get('id')
        st = _parse_iso_utc(ev.get('starttime') or '')
        en = _parse_iso_utc(ev.get('endtime') or '')
        if cid is None or st is None or en is None:
            continue
        by_id.setdefault(cid, []).append((st, en, ev))
    n = 0
    superguide = _superguide_entries()
    with _epg_lock:
        for k, (cid, off) in res.items():
            evs = by_id.get(cid)
            if not evs:
                continue
            evs.sort(key=lambda x: x[0])
            # 'eff' = the moment we treat as "now" on this channel (shifted back 1h
            # for a +1 timeshift). 'off' is subtracted from every displayed/expiry
            # time so the +1 channel shows ITS own air times, not the base's.
            eff = now + off
            # current = the on-air event with the LATEST start (most specific when
            # the schedule has overlapping entries)
            cur = None
            for st, en, ev in evs:
                if st <= eff < en and (cur is None or st > cur[0]):
                    cur = (st, en, ev)
            if not cur:
                continue
            cs, ce, cev = cur
            show, ep_info, ep_title = _parse_event(cev)
            if not show:
                continue
            entry = {
                'prog': show, 'ep_info': ep_info, 'ep_title': ep_title,
                'start': _fmt_local(cs - off), 'end': _fmt_local(ce - off),
                'synopsis': (cev.get('eventSynopsis') or '').strip(),
                'until': ce - off,
            }
            # next = first event starting at/after the current one ends
            nxt = next((x for x in evs if x[0] >= ce), None)
            if nxt:
                nshow, _ni, _nt = _parse_event(nxt[2])
                if nshow:
                    entry['next_prog'] = nshow
                    entry['next_start'] = _fmt_local(nxt[0] - off)
            # prev = last event ending at/before the current one starts
            prv = None
            for st, en, ev in evs:
                if en <= cs:
                    prv = (st, en, ev)
            if prv:
                pshow, _pi, _pt = _parse_event(prv[2])
                if pshow:
                    entry['prev_prog'] = pshow
                    entry['prev_start'] = _fmt_local(prv[0] - off)
            _epg_cache[_norm(k)] = entry
            n += 1
        for k in keys:
            nk = _norm(k)
            existing = _epg_cache.get(nk)
            fallback = _superguide_for(k, superguide)
            # RaiPlay/Mediaset describe their own transmission and therefore
            # take precedence over the satellite schedule for those channels.
            authoritative = fallback and fallback.get('source') in ('raiplay', 'mediaset')
            if existing and now < existing.get('until', 0) and not authoritative:
                continue
            if fallback:
                _epg_cache[nk] = dict(fallback)
                n += 1
    logger.info('[SkyEPG] prefetch: %d/%d channels now-on-air' % (n, len(res)))
    return n


def prefetch(keys):
    global _prefetch_running, _last_prefetch_at
    now = time.time()
    with _prefetch_guard:
        if _prefetch_running or (now - _last_prefetch_at) < 3 * 60:
            return 0
        _prefetch_running = True
    try:
        return _prefetch(list(dict.fromkeys(k for k in keys if k)))
    finally:
        with _prefetch_guard:
            _prefetch_running = False
            _last_prefetch_at = time.time()


def now_on(title):
    """Cached 'now on air' info for a channel title, or None.

    Returns {'prog','ep_info','ep_title','start','end','synopsis', plus
    'next_prog'/'next_start' and 'prev_prog'/'prev_start'} when a fresh programme is
    known; drops the entry once its end time has passed."""
    with _epg_lock:
        e = _epg_cache.get(_norm(title))
        if not e:
            return None
        if _utc_now() >= e.get('until', 0):
            _epg_cache.pop(_norm(title), None)
            return None
        return {'prog': e['prog'], 'ep_info': e.get('ep_info', ''),
                'ep_title': e.get('ep_title', ''), 'start': e['start'],
                'end': e['end'], 'synopsis': e['synopsis'],
                'next_prog': e.get('next_prog', ''), 'next_start': e.get('next_start', ''),
                'prev_prog': e.get('prev_prog', ''), 'prev_start': e.get('prev_start', '')}
