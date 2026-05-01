# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Netflix-style Home Window for StreamingCommunity + multi-source
# v4 — lazy-load extra rows from other VOD channels.
# ------------------------------------------------------------

import os
import re
import sys
import time
import threading
import xbmc
import xbmcaddon
import xbmcgui

from core.item import Item
from platformcode import config, logger, watch_history, platformtools

PY3 = sys.version_info[0] >= 3

_cache = {'data': None, 'ts': 0}
_CACHE_TTL = 1800   # 30 minutes

# Timeout (seconds) per each external channel fetch
_EXTRA_TIMEOUT = 18

# Valid actions that indicate a real playable/browsable item
_VALID_ACTIONS = frozenset(['findvideos', 'episodios', 'check', 'findvideos_findhost',
                             'play', 'seasons', 'temporadas', 'check_series'])

# Sources used to enrich each SC row by content type.
# Items are fetched ONCE per type (cached); per-row dedup runs at enrichment time.
# SC items always come first; extra items are appended only if not already in that row.
_ENRICH_SOURCE_MAP = {
    'peliculas': [
        ('cineblog01',            'peliculas'),
        ('altadefinizione01',     'peliculas'),
        ('filmpertutti',          'peliculas'),
        ('filmstreaming',         'peliculas'),
        ('ilgeniodellostreaming', 'peliculas'),
        ('piratestreaming',       'peliculas'),
        ('mondoserietv',          'peliculas'),
        ('casacinema',            'peliculas'),
        ('cinemalibero',          'peliculas'),
        ('dinostreaming',         'peliculas'),
    ],
    'series': [
        ('eurostreaming',         'series'),
        ('ilgeniodellostreaming', 'series'),
        ('mondoserietv',          'series'),
        ('piratestreaming',       'series'),
        ('cineblog01',            'series'),
        ('italiaserie',           'series'),
        ('guardaserieclick',      'series'),
        ('filmstreaming',         'series'),
    ],
    'anime': [
        ('animesaturn',           'anime'),
        ('animeunity',            'anime'),
        ('animeworld',            'anime'),
        ('cb01anime',             'anime'),
        ('animeforce',            'anime'),
        ('dreamsub',              'anime'),
        ('animealtadefinizione',  'anime'),
        ('aniplay',               'anime'),
        ('animeuniverse',         'anime'),
        ('piratestreaming',       'anime'),
    ],
}

# Per-type cache: ctype -> {'items': [Item, ...], 'ts': float}
_enrich_cache = {}

# Persistent trailer cache across window instances: tmdb_id -> url (str) or False (no trailer).
# Never expires — trailer links are stable YouTube IDs.
_trailer_cache = {}

# Shutdown event: set by open_netflix_home() the moment the user closes the home screen
# AND by _AppShutdownMonitor.onAbortRequested() the instant Kodi sends the global abort
# signal to our invoker.  ALL background network threads check this flag before starting
# a new HTTP request so they exit within the current request's socket timeout (≤3 s).
# Using a PUSH callback (onAbortRequested) instead of relying solely on polling guarantees
# the flag is set the moment Kodi signals our CPythonInvoker — regardless of whether
# open_netflix_home()'s while loop has had a chance to detect it yet.
_shutdown_event = threading.Event()


class _AppShutdownMonitor(xbmc.Monitor):
    """Receives Kodi's abort signal immediately via callback and sets _shutdown_event.

    Kodi processes invokers sequentially during shutdown: our invoker may not receive
    the signal for several seconds after "Stopping the application".  When it finally
    does, onAbortRequested() fires instantly — before the polling loop in
    open_netflix_home() even gets a chance to check.  This eliminates the window where
    background trailer threads run unchecked after the user has closed Kodi.
    """

    def onAbortRequested(self):
        _shutdown_event.set()


# Singleton registered at import time so it is always listening.
_app_monitor = _AppShutdownMonitor()

# SC rows cache: populated on first home load, reused on subsequent opens without refetch.
_sc_rows_cache = None


class _AvReadyPlayer(xbmc.Player):
    """xbmc.Player subclass that signals via threading.Event when onAVStarted fires.
    onAVStarted is called by Kodi exactly once per stream, after the A/V pipeline is
    fully initialised and all audio/subtitle tracks are enumerated — the correct and
    earliest moment to safely call setAudioStream() / setSubtitleStream().
    """
    def __init__(self):
        super(_AvReadyPlayer, self).__init__()
        self.av_started = threading.Event()

    def onAVStarted(self):
        self.av_started.set()


def _restore_lang_after_av_started(orig_audio, orig_sub, timeout=20):
    """Keep the temporary locale settings active for the ENTIRE playback duration,
    then restore the originals.

    Previous approach used xbmc.Monitor.onAVStarted() — which does NOT exist on
    Monitor (only on xbmc.Player) — so it always timed out after 20 s and restored
    'Italian'.  On Android, inputstream.adaptive re-reads locale.audiolanguage on
    every ABR quality-switch (bitrate adaptation); with 'Italian' already restored
    at t=20 s, any quality switch at t=60-120 s would silently switch the audio to
    Italian.

    New approach:
      Phase 1 — wait up to *timeout* seconds for the new item to START playing
                (the previous trailer/content is already stopped by the time this
                function is called from _pre_play_set_lang → _launch).
      Phase 2 — wait until playback ENDS.
      Restore  — always restore, even on timeout or exception.
    """
    try:
        import time as _time
        player  = xbmc.Player()
        monitor = xbmc.Monitor()

        # Phase 1: wait for the new content to start playing (up to 'timeout' s).
        t0 = _time.time()
        while not player.isPlaying():
            if monitor.abortRequested() or (_time.time() - t0) > timeout:
                break
            _time.sleep(0.2)

        # Phase 2: wait for playback to END — locale.audiolanguage stays at the
        # preferred language so every ISA ABR re-init picks the right track.
        while player.isPlaying() and not monitor.abortRequested():
            _time.sleep(0.5)

    except Exception as exc:
        logger.error('[CW] _restore_lang_after_av_started (wait): %s' % str(exc))

    # Restore global settings — always, outside the try so it's guaranteed
    try:
        def _rpc_set(setting, value):
            if value is None:
                return
            xbmc.executeJSONRPC(
                '{"jsonrpc":"2.0","method":"Settings.SetSettingValue",'
                '"params":{"setting":"%s","value":"%s"},"id":1}'
                % (setting, str(value).replace('"', '')))

        if orig_audio is not None:
            _rpc_set('locale.audiolanguage', orig_audio)
            logger.info('[CW] restored locale.audiolanguage -> %s' % orig_audio)
        if orig_sub is not None:
            _rpc_set('locale.subtitlelanguage', orig_sub)
            logger.info('[CW] restored locale.subtitlelanguage -> %s' % orig_sub)
    except Exception as exc:
        logger.error('[CW] _restore_lang_after_av_started (restore): %s' % str(exc))


def _pre_play_set_lang(item):
    """Read audio/sub preference for *item* and temporarily set the Kodi global
    locale settings so ISA picks the right track from frame 0.
    Starts a background thread that restores the originals after onAVStarted fires.
    Safe to call for any item — does nothing if no preference is saved."""
    try:
        import json as _json
        addon   = xbmcaddon.Addon()
        infolabels = getattr(item, 'infoLabels', None) or {}
        tmdb    = str(infolabels.get('tmdb_id') or '').strip()
        key     = tmdb or re.sub(r'[^a-z0-9]', '',
                                 (getattr(item, 'fulltitle', '') or
                                  getattr(item, 'show', '') or '').lower())
        if not key:
            return

        ap = addon.getSetting('audiolang_%s' % key) or ''
        sp = addon.getSetting('sublang_%s'   % key) or ''
        logger.info('[CW] pre-play key=%r tmdb=%r ap=%r sp=%r' % (key, tmdb, ap, sp))

        if not ap and not sp:
            return  # no preference → nothing to do

        def _rpc_get(setting):
            r = xbmc.executeJSONRPC(
                '{"jsonrpc":"2.0","method":"Settings.GetSettingValue",'
                '"params":{"setting":"%s"},"id":1}' % setting)
            return _json.loads(r).get('result', {}).get('value', '')

        def _rpc_set(setting, value):
            xbmc.executeJSONRPC(
                '{"jsonrpc":"2.0","method":"Settings.SetSettingValue",'
                '"params":{"setting":"%s","value":"%s"},"id":1}'
                % (setting, str(value).replace('"', '')))

        def _disk_get(setting):
            try:
                import re as _re2
                gui = xbmc.translatePath('special://userdata/guisettings.xml')
                with open(gui, 'r', encoding='utf-8') as _f:
                    txt = _f.read()
                m = _re2.search(r'<setting id="%s">([^<]*)</setting>' % setting, txt)
                return m.group(1) if m else ''
            except Exception:
                return ''

        _safe_defaults = {'locale.audiolanguage': 'Italian',
                          'locale.subtitlelanguage': 'default'}

        def _get_orig(setting):
            v = _disk_get(setting)
            if not v:
                v = _rpc_get(setting)
            # Sanity: avoid perpetuating a previously contaminated value
            if setting == 'locale.audiolanguage' and v in ('English', 'en', 'eng'):
                return _safe_defaults[setting]
            if setting == 'locale.subtitlelanguage' and v in ('Italian', 'it', 'ita'):
                return _safe_defaults[setting]
            return v or _safe_defaults.get(setting, '')

        orig_audio = None
        orig_sub   = None

        if ap and ap != u'Originale (non cambiare)':
            orig_audio = _get_orig('locale.audiolanguage')
            lang = 'Italian' if 'Italiano' in ap else 'English'
            _rpc_set('locale.audiolanguage', lang)
            logger.info('[CW] pre-play audio: %s → %s' % (orig_audio, lang))

        if sp and sp not in (u'Nessun sottotitolo', ''):
            orig_sub = _get_orig('locale.subtitlelanguage')
            slang = 'Italian' if ('Italiano' in sp or 'Come audio' in sp) else 'English'
            _rpc_set('locale.subtitlelanguage', slang)
            logger.info('[CW] pre-play sub: %s → %s' % (orig_sub, slang))

        if orig_audio is not None or orig_sub is not None:
            t = threading.Thread(
                target=_restore_lang_after_av_started,
                args=(orig_audio, orig_sub))
            t.daemon = True
            t.start()

    except Exception as exc:
        logger.error('[CW] _pre_play_set_lang: %s' % str(exc))


# Label for the Continue Watching row (must match what _refresh_cw_row checks).
_CW_ROW_LABEL = u'\u25b6  Continua a guardare'

# CW lookup tables — populated by _build_cw_items(), used by _apply_cw_to_item().
_cw_lookup_by_tmdb  = {}   # tmdb_id (str) -> CW Item
_cw_lookup_by_title = {}   # normalized show name -> CW Item

BG_FANART          = 100
HERO_CATEG         = 102
HERO_TITLE         = 103
HERO_META          = 104
HERO_PLOT          = 105
CLOSE_BTN          = 108
SETTINGS_BTN       = 107   # ⚙ settings button in top bar
BTN_PLAY           = 110   # PLAY CTA button in hero
BTN_INFO           = 111   # MORE INFO CTA button in hero
BTN_LIST           = 112   # MY LIST CTA button in hero
LOADING_LBL        = 200

ROW_WRAPLIST_BASE  = 2000
ROW_LABEL_BASE     = 3000   # category label above each row
ROW_LEFT_BASE      = 4000   # left arrow button per row
ROW_RIGHT_BASE     = 4001   # right arrow button per row
ROW_OVERLAY_BASE   = 5000   # transparent mouse-blocker overlay per row
HOVER_BOX_BASE     = 6000   # hover-frame group per row (moved by setPosition)
ROW_STEP           = 10
# SC_MAX_ROWS: how many rows StreamingCommunity is allowed to fill
# MAX_ROWS: total wraplist slots in the XML (must match generator MAX_ROWS)
SC_MAX_ROWS        = 20
MAX_ROWS           = 50
ARROW_PAGE_SIZE    = 1
UPNEXT_COUNTDOWN   = 60   # seconds before episode end: show Up Next overlay

# ── Detail window control IDs ──────────────────────────────────
DW_BG_FANART   = 201
DW_VIDEO       = 202
DW_TITLE       = 204
DW_META1       = 205
DW_META2       = 206
DW_META3       = 207
DW_TAGLINE     = 208
DW_PLOT        = 209
DW_BTN_PLAY      = 210
DW_BTN_AUDIO_SUB = 211   # formerly LIST — now opens audio/subtitle picker
DW_BTN_CLOSE     = 212
DW_BTN_REMOVE_CW = 213   # remove item from CW (visible only for CW items)
DW_BTN_LIST      = 211   # alias kept for any remaining references
DW_CAST_PANEL    = 220   # horizontal cast cards panel
DW_CAST_HDR      = 221   # "CAST" section header label
DW_EP_INFO       = 223   # "▶ Continua S02E05" episode info label (tvshow only)
DW_BTN_EP_SEL    = 215   # "STAGIONI & EPISODI" selector button (tvshow only)
DW_OVERLAY_GROUP = 230   # cinema-mode group (fades out when trailer plays)

# ── EpisodePicker dialog control IDs ─────────────────────────────────────────
EP_SEASON_LIST   = 310   # horizontal panel of season tabs
EP_EP_LIST       = 311   # vertical list of episode rows
EP_BTN_CANCEL    = 321   # close / cancel button

ACTION_EXIT         = 10
ACTION_BACK         = 92
ACTION_LEFT         = 1
ACTION_RIGHT        = 2
ACTION_UP           = 3
ACTION_DOWN         = 4
ACTION_WHEEL_UP     = 104
ACTION_WHEEL_DOWN   = 105
ACTION_MOUSE_MOVE   = 107

# ── Search window control IDs ────────────────────────────────
SEARCH_BTN_HOME    = 109   # search button in NetflixHome top bar
SEARCH_BTN_BACK    = 109   # same id reused in NetflixSearch (back ←)
SEARCH_QUERY_BTN   = 120   # clickable query display / re-search button
SEARCH_PROGRESS    = 121   # progress label
SEARCH_CLOSE       = 122   # close ✕ button
SEARCH_PLAY        = 135   # GUARDA button
SEARCH_INFO        = 136   # INFO  button
SEARCH_BADGE_SC    = 150   # result count badge for SC row
SEARCH_BADGE_FILM  = 151   # result count badge for Film row
SEARCH_BADGE_TV    = 152   # result count badge for TV row
SEARCH_WL_SC       = 160   # wraplist: SC results
SEARCH_WL_FILM     = 161   # wraplist: Film (altri canali)
SEARCH_WL_TV       = 162   # wraplist: Serie TV (altri canali)
SEARCH_LOADING     = 170   # loading indicator group
SEARCH_NORESULTS   = 171   # no-results label
SEARCH_STATUS_LBL  = 172   # "Ricerca in corso..." text inside loading group


# ── Continue Watching helpers ────────────────────────────────

def _cw_key(item):
    """Return a stable string key that uniquely identifies this content in the CW db.
    TV series (contentType=='episode') share a single series-level key so that all
    episodes of the same show are tracked under one CW entry.
    """
    tmdb = str(item.infoLabels.get('tmdb_id') or '').strip()
    ct   = getattr(item, 'contentType', '') or ''
    if ct == 'episode':
        base = tmdb or re.sub(r'[^a-z0-9]', '',
                               (item.show or item.contentSerieName or '').lower())
        return 'tv_%s' % base
    else:
        base = tmdb or re.sub(r'[^a-z0-9]', '',
                               (item.fulltitle or item.show or '').lower())
        return 'movie_%s' % base


def _fix_cw_url_domain(it):
    """Replace a stale channel domain in a CW item's URL with the current one from channels.json.

    CW items store the full URL at watch-time. When the channel migrates to a new domain
    (e.g. streamingcommunityz.ooo → streamingcommunityz.organic) the stored URL becomes
    unreachable. This function rewrites the netloc to match the live channel host so that
    playback and data-fetching work correctly without the user having to re-add the item.
    """
    ch = getattr(it, 'channel', '') or ''
    if not ch:
        return
    try:
        current_host = config.get_channel_url(name=ch)
    except Exception:
        return
    if not current_host:
        return
    try:
        if PY3:
            from urllib.parse import urlsplit, urlunsplit
        else:
            from urlparse import urlsplit, urlunsplit
        current_netloc = urlsplit(current_host).netloc
        for attr in ('url', '_cw_show_url'):
            old_url = getattr(it, attr, '') or ''
            if not old_url:
                continue
            parsed = urlsplit(old_url)
            if parsed.netloc and parsed.netloc != current_netloc:
                logger.info('[CW] domain updated %s → %s (%s)' % (
                    parsed.netloc, current_netloc, getattr(it, 'fulltitle', '')))
                new_url = urlunsplit((parsed.scheme, current_netloc,
                                     parsed.path, parsed.query, parsed.fragment))
                setattr(it, attr, new_url)
    except Exception as exc:
        logger.error('[CW] _fix_cw_url_domain: %s' % str(exc))


def _build_cw_items():
    """Build Items from the Continue Watching DB.
    Entries >= 97% watched are treated as completed and auto-removed.
    Also rebuilds the module-level CW lookup tables used by _apply_cw_to_item().
    """
    global _cw_lookup_by_tmdb, _cw_lookup_by_title
    _cw_lookup_by_tmdb  = {}
    _cw_lookup_by_title = {}

    entries = watch_history.get_all()
    if not entries:
        return []
    items = []
    completed_keys = []
    for e in entries:
        try:
            cw_time  = float(e.get('time_watched', 0))
            cw_total = float(e.get('total_time', 0))
            if cw_total > 0 and (cw_time / cw_total) >= 0.97:
                completed_keys.append(e['key'])
                logger.info('[CW] auto-removing completed: %s' % e.get('title', e['key']))
                continue
            it = Item().fromurl(e['item_url'])
            it.cw_time_watched = cw_time
            it.cw_total_time   = cw_total
            it._cw_show_url    = e.get('show_url', '') or ''
            _fix_cw_url_domain(it)  # update stale domains after migration
            items.append(it)
        except Exception as exc:
            logger.error('[CW] build item: %s' % str(exc))
    for key in completed_keys:
        try:
            watch_history.remove(key)
        except Exception as exc:
            logger.error('[CW] remove completed: %s' % str(exc))

    # Build lookup tables for cross-row sync
    for it in items:
        tmdb = str(it.infoLabels.get('tmdb_id') or '').strip()
        if tmdb and tmdb not in _cw_lookup_by_tmdb:
            _cw_lookup_by_tmdb[tmdb] = it
        show_name = (getattr(it, 'show', '') or
                     getattr(it, 'contentSerieName', '') or
                     getattr(it, 'fulltitle', '') or '')
        norm = _normalize_title(show_name)
        if norm and norm not in _cw_lookup_by_title:
            _cw_lookup_by_title[norm] = it

    return items


class NetflixHomeWindow(xbmcgui.WindowXML):

    def __init__(self, *args, **kwargs):
        self.rows_data = []
        self._num_rows = 0
        self._alive = True
        self._last_focused_row = 0
        self._populated = set()  # track which row indices have had addItems() called
        self._hover_slot = {}    # row_idx -> last slot (throttle guard)
        self._hover_base = {}    # row_idx -> wraplist selectedPosition when mouse entered
        self._hover_item = {}    # row_idx -> item index last hovered by mouse
        self._hover_box_row = -1  # row whose hover-frame is currently visible
        self._rows_lock = threading.Lock()  # protects rows_data + _num_rows extension
        # Cleared while a modal dialog is open — background thread must NOT modify the UI
        self._bg_ui_pause = threading.Event()
        self._bg_ui_pause.set()   # initially NOT paused
        # Set by background threads to request a CW row refresh on the GUI thread.
        # Checked (and drained) in onFocus, which always runs on the GUI thread.
        self._cw_refresh_pending = False
        # When set to (wl_id, pos, remaining_attempts), onFocus will call
        # selectItem(pos) every time that wl_id gains focus, until attempts run out.
        # This defeats the skin's post-animation focus reset on Android TV.
        self._pending_select_pos = None
        # Lock to prevent concurrent _enforce_scroll_pos threads.
        self._scroll_lock = threading.Lock()

    def onInit(self):
        try:
            if config.get_platform(True)['num_version'] < 18:
                self.setCoordinateResolution(3)  # 1920x1080
        except Exception:
            pass
        # Loading overlay starts visible in XML — just start background fetch.
        t = threading.Thread(target=self._bg_load)
        t.daemon = True
        t.start()

    def _bg_load(self):
        """Run in background thread: fetch SC rows, prepend CW row, then update UI."""
        global _sc_rows_cache
        # ── Sync channels.json BEFORE loading rows so domains are always current ──
        _CHANNELS_REMOTE = 'https://raw.githubusercontent.com/usandissm/PrippiStream/main/channels.json'
        try:
            if PY3:
                import urllib.request as _urllib_req
            else:
                import urllib as _urllib_req
            _remote = _urllib_req.urlopen(_CHANNELS_REMOTE, timeout=6).read().decode('utf-8')
            _local_path = os.path.join(config.get_runtime_path(), 'channels.json')
            try:
                with open(_local_path, 'r', encoding='utf-8') as _f:
                    _local = _f.read()
            except Exception:
                _local = ''
            if _remote.strip() != _local.strip():
                with open(_local_path, 'w', encoding='utf-8') as _f:
                    _f.write(_remote)
                config.channels_data = dict()
                logger.info('[NetflixHome] channels.json updated from GitHub')
        except Exception as _e:
            logger.error('[NetflixHome] channels.json sync failed: %s' % str(_e))

        try:
            sc_rows = _fetch_rows()
            _sc_rows_cache = sc_rows  # keep a copy for fast refresh
        except Exception as exc:
            logger.error('[NetflixHome] fetch error: %s' % str(exc))
            sc_rows = _sc_rows_cache or []

        if not self._alive:
            return

        # CW row is ALWAYS rows_data[0] (even when empty) so that SC rows i>=1
        # always map to the same control IDs (2010, 2020, ...) regardless of CW state.
        cw_items = _build_cw_items()
        self.rows_data = [(_CW_ROW_LABEL, cw_items)] + list(sc_rows)

        # Fire-and-forget: nuke stale vixcloud bookmarks from prior sessions
        # so Kodi never shows a "Resume from" dialog for our managed content.
        _t_nuke = threading.Thread(target=_nuke_all_vixcloud_bookmarks)
        _t_nuke.daemon = True
        _t_nuke.start()

        # Sync CW progress to matching items in all SC rows
        if cw_items:
            for row_label, row_items in self.rows_data:
                if row_label != _CW_ROW_LABEL:
                    for it in row_items:
                        _apply_cw_to_item(it)

        try:
            self.getControl(LOADING_LBL).setVisible(False)
        except Exception:
            pass

        self._num_rows = min(len(self.rows_data), MAX_ROWS)
        logger.debug('[NetflixHome] rows loaded: %d (CW: %d)' % (self._num_rows, len(cw_items)))

        if self._num_rows > 0 and self._alive:
            xbmc.sleep(80)
            for i in range(min(4, self._num_rows)):
                self._populate_single_row(i)
            first_row_fid = ROW_WRAPLIST_BASE if cw_items else ROW_WRAPLIST_BASE + ROW_STEP
            self._update_hero(0 if cw_items else 1)
            self.setFocusId(first_row_fid)

        # Kick off background enrichment of SC rows with extra-source items (non-blocking)
        if self._alive:
            t = threading.Thread(target=self._bg_enrich_rows)
            t.daemon = True
            t.start()

    def _bg_enrich_rows(self):
        """
        Background: enrich each SC row with extra items from matching sources.
        SC items keep priority - extras are appended only if not already in that row.
        Dedup is per-row only; the same title CAN appear in different rows.
        If a row is already visible, new items are appended live (no reset/flicker).
        If not yet visible, items are queued in rows_data for lazy population.
        """
        try:
            _monitor_bg = xbmc.Monitor()

            # Step 1: collect which content types are needed across all SC rows
            needed_types = set()
            for label, _ in list(self.rows_data):
                ct = _row_content_type(label)
                if ct:
                    needed_types.add(ct)
            if not needed_types or not self._alive or _monitor_bg.abortRequested():
                return

            # Step 2: pre-fetch all needed types concurrently
            fetch_threads = []
            for ct in needed_types:
                t = threading.Thread(target=_fetch_enrich_items, args=(ct,))
                t.daemon = True
                fetch_threads.append(t)
                t.start()
            # Join each fetch thread, but bail out immediately if Kodi is closing.
            # threading.join() uses a C-level semaphore wait that ignores Python's
            # interrupt flag — so we must check abort BEFORE each join, not during.
            for t in fetch_threads:
                if not self._alive or _monitor_bg.abortRequested():
                    return
                t.join(timeout=_EXTRA_TIMEOUT + 5)

            if not self._alive or _monitor_bg.abortRequested():
                return

            # Step 3: enrich each SC row using the now-cached pools
            for i in range(len(self.rows_data)):
                if not self._alive or _monitor_bg.abortRequested():
                    return
                with self._rows_lock:
                    if i >= len(self.rows_data):
                        break
                    label, items = self.rows_data[i]

                ct = _row_content_type(label)
                if not ct:
                    continue

                extra_pool = _fetch_enrich_items(ct)   # instant (already cached)
                if not extra_pool:
                    continue

                # Build dedup set from this row's existing SC items (they have priority)
                row_norms = set()
                for it in items:
                    n = _normalize_title(_extract_item_title(it))
                    if n:
                        row_norms.add(n)

                # Keep only extra items not already present in this row
                new_items = []
                for it in extra_pool:
                    n = _normalize_title(_extract_item_title(it))
                    if n and n not in row_norms:
                        row_norms.add(n)
                        new_items.append(it)

                if not new_items:
                    continue

                # Apply CW data to enrichment items before adding to rows
                for it in new_items:
                    _apply_cw_to_item(it)

                with self._rows_lock:
                    if not self._alive:
                        return
                    items.extend(new_items)

                xbmc.sleep(30)
                self._live_append_row(i, new_items)
                logger.error('[NetflixHome enrich] row "%s" (#%d) +%d items (total=%d)'
                             % (label, i, len(new_items), len(items)))

            # Final step: fetch trailers for first 20 visible items.
            # Runs AFTER all enrichment threads have completed, so thread count is low.
            # Uses 2 workers max and a lightweight /videos endpoint — safe for Kodi.
            if self._alive and not _monitor_bg.abortRequested():
                _fetch_trailers_small(list(self.rows_data))

        except Exception as exc:
            logger.error('[NetflixHome] _bg_enrich_rows: %s' % str(exc))

    def _live_append_row(self, i, new_items):
        """
        Append new_items to wraplist for row i only if the row is already on-screen.
        If not yet populated, items are already in rows_data and will be included
        when lazy-populated on scroll — no action needed here.
        """
        if i not in self._populated:
            return
        # Wait until no modal dialog is open (avoids C++ render-engine collision).
        # Timeout ensures we never block forever if something goes wrong.
        self._bg_ui_pause.wait(timeout=15)
        if not self._alive:
            return
        wl_id = ROW_WRAPLIST_BASE + i * ROW_STEP
        try:
            self.getControl(wl_id).addItems([_item_to_li(it) for it in new_items])
        except Exception as exc:
            logger.error('[NetflixHome] _live_append_row %d: %s' % (i, str(exc)))

    def _populate_single_row(self, i):
        """Populate wraplist for row i. Safe to call multiple times (no-op if already done)."""
        if i in self._populated or i >= len(self.rows_data):
            return
        wl_id    = ROW_WRAPLIST_BASE + i * ROW_STEP
        lbl_id   = ROW_LABEL_BASE   + i * ROW_STEP
        cat_name, items = self.rows_data[i]
        # Row 0 is always the CW row (control 2000). Hide it when empty.
        if i == 0 and not items:
            try:
                self.getControl(wl_id).setVisible(False)
                self.getControl(lbl_id).setVisible(False)
            except Exception:
                pass
            self._populated.add(i)
            return
        # Mark populated BEFORE addItems so that onFocus re-entrant calls
        # see this row as already done and skip it.
        self._populated.add(i)
        try:
            wl = self.getControl(wl_id)
            # No reset() here: this is FIRST-TIME population — the wraplist is
            # already empty, so reset() + sleep would waste time and cause the
            # skin to scroll back to the top. The sleep is only needed when
            # RE-rendering an already-populated wraplist (done in _refresh_cw_row).
            wl.setVisible(True)
            wl.addItems([_item_to_li(it) for it in items])
        except Exception as exc:
            self._populated.discard(i)  # allow retry on error
            logger.error('[NetflixHome] populate row %d wraplist: %s' % (i, str(exc)))
        try:
            lbl = self.getControl(lbl_id)
            lbl.setVisible(True)
            lbl.setLabel('[B]%s[/B]' % cat_name.upper())
        except Exception as exc:
            logger.error('[NetflixHome] populate row %d label: %s' % (i, str(exc)))

    def _update_hero(self, row_idx, pos=None):
        if row_idx >= len(self.rows_data):
            return
        _, items = self.rows_data[row_idx]
        if not items:
            return
        if pos is None:
            try:
                pos = int(self.getControl(ROW_WRAPLIST_BASE + row_idx * ROW_STEP).getSelectedPosition() or 0)
                if pos < 0 or pos >= len(items):
                    pos = 0
            except Exception:
                pos = 0
        it = items[min(pos, len(items) - 1)]
        thumb  = it.thumbnail or ''
        fanart = it.fanart or thumb
        title  = it.fulltitle or it.show or it.contentSerieName or ''
        year      = str(it.year or '')
        lang      = getattr(it, 'language', '') or ''
        plot      = (it.infoLabels.get('plot') or getattr(it, 'plot', '') or '').strip()
        rating    = it.infoLabels.get('rating') or ''
        genre     = it.infoLabels.get('genre') or ''
        ctype_lbl = 'Film' if getattr(it, 'contentType', '') == 'movie' else (
                    'Serie TV' if getattr(it, 'contentType', '') == 'tvshow' else '')
        # Rating formatted as "★ 7.5"
        rating_str = ''
        if rating:
            try:
                rating_str = '\u2605 %.1f' % float(str(rating))
            except Exception:
                pass
        # First genre only (TMDB returns slash-separated list)
        genre_str = str(genre).split('/')[0].strip() if genre else ''
        try:
            img = fanart or thumb
            if img:
                self.getControl(BG_FANART).setImage(img)
            self.getControl(HERO_TITLE).setLabel('[B]' + title + '[/B]')
            meta = '  •  '.join(p for p in [year, ctype_lbl, lang, rating_str, genre_str] if p)
            self.getControl(HERO_META).setLabel(meta)
            self.getControl(HERO_CATEG).setLabel(self.rows_data[row_idx][0])
            try:
                self.getControl(HERO_PLOT).setText(plot)
            except Exception:
                pass
        except Exception as exc:
            logger.error('[NetflixHome] hero: %s' % str(exc))

    def _row_from_fid(self, fid):
        """Returns row index if fid is a wraplist or overlay for that row, else -1."""
        for i in range(self._num_rows):
            if fid in (ROW_WRAPLIST_BASE + i * ROW_STEP, ROW_OVERLAY_BASE + i * ROW_STEP):
                return i
        return -1

    def _hide_hover_box(self, row_idx):
        """Move hover-frame off-screen for the given row."""
        try:
            # ROW 00 (CW) uses wider cards (370px) → park further left
            off_x = -400 if row_idx == 0 else -278
            self.getControl(HOVER_BOX_BASE + row_idx * ROW_STEP).setPosition(off_x, 54)
        except Exception:
            pass

    def onFocus(self, control_id):
        """Fires when a control gains focus — always on the Kodi GUI thread."""
        # Drain any pending CW refresh requested by a background thread.
        # Must run here (GUI thread) because wl.reset()/addItems() require it.
        if self._cw_refresh_pending:
            self._cw_refresh_pending = False
            self._refresh_cw_row()
            # After CW refresh (which may take 100-300ms and re-render rows),
            # re-apply the pending position so any scroll caused by the refresh
            # is overwritten.
            if self._pending_select_pos is not None:
                pending_wl_id, pending_pos, _ = self._pending_select_pos
                self._pending_select_pos = None
                xbmc.sleep(50)
                try:
                    self.getControl(pending_wl_id).selectItem(pending_pos)
                except Exception:
                    pass
            return  # onFocus will fire again from the selectItem call above

        # Restore saved wraplist position exactly when the wraplist gains focus.
        # We keep the flag alive for several consecutive onFocus calls so that
        # the skin's post-animation reset (which fires a second focus event and
        # snaps the scroll back to 0 on Android TV) is also intercepted and
        # overwritten.
        if self._pending_select_pos is not None:
            pending_wl_id, pending_pos, pending_left = self._pending_select_pos
            if control_id == pending_wl_id:
                pending_left -= 1
                if pending_left > 0:
                    self._pending_select_pos = (pending_wl_id, pending_pos, pending_left)
                else:
                    self._pending_select_pos = None
                try:
                    self.getControl(pending_wl_id).selectItem(pending_pos)
                except Exception:
                    pass

        i = self._row_from_fid(control_id)
        if i >= 0:
            # Keyboard navigation to a different row: hide old hover frame
            if self._hover_box_row >= 0 and self._hover_box_row != i:
                self._hide_hover_box(self._hover_box_row)
                self._hover_box_row = -1
            self._last_focused_row = i
            for j in range(max(0, i-1), min(self._num_rows, i+4)):
                self._populate_single_row(j)
            # Snapshot wraplist position when mouse enters this row overlay
            if control_id == ROW_OVERLAY_BASE + i * ROW_STEP:
                try:
                    sel = int(self.getControl(ROW_WRAPLIST_BASE + i * ROW_STEP).getSelectedPosition() or 0)
                    self._hover_base[i] = max(0, sel)
                except Exception:
                    self._hover_base[i] = 0
                self._hover_slot[i] = -1
                self._hover_item[i] = None
            else:
                # Wraplist focused by keyboard: clear mouse-hover state so
                # _hero_item() uses wraplist selectedPosition instead.
                self._hover_item[i] = None
                self._hide_hover_box(i)
                self._hover_box_row = -1
            self._update_hero(i)
        else:
            # Focus moved outside the rows (to hero buttons, EXIT…): hide hover frame
            if self._hover_box_row >= 0:
                self._hide_hover_box(self._hover_box_row)
                self._hover_box_row = -1

    def onAction(self, action):
        aid = action.getId()
        if aid in (ACTION_EXIT, ACTION_BACK):
            self._alive = False
            self.close()
            return

        # Mouse wheel → navigate between rows
        if aid == ACTION_WHEEL_UP:
            new_row = max(0, self._last_focused_row - 1)
            # Skip row 0 (CW) if it is empty
            if new_row == 0 and self.rows_data and not self.rows_data[0][1]:
                new_row = 0 if self._last_focused_row == 0 else self._last_focused_row
            self.setFocusId(ROW_WRAPLIST_BASE + new_row * ROW_STEP)
            self._last_focused_row = new_row
            self._update_hero(new_row)
            return
        if aid == ACTION_WHEEL_DOWN:
            new_row = min(self._num_rows - 1, self._last_focused_row + 1)
            self.setFocusId(ROW_WRAPLIST_BASE + new_row * ROW_STEP)
            self._last_focused_row = new_row
            self._update_hero(new_row)
            return

        # Full remote-control navigation (onAction replaces XML nav entirely)
        if aid == ACTION_UP:
            fid = self.getFocusId()
            i = self._row_from_fid(fid)
            if i >= 0:
                if i > 0:
                    new_row = i - 1
                    # Skip row 0 (CW) if it is empty
                    cw_empty = self.rows_data and not self.rows_data[0][1]
                    if new_row == 0 and cw_empty:
                        self.setFocusId(CLOSE_BTN)
                        return
                    for j in range(max(0, new_row - 1), min(self._num_rows, new_row + 3)):
                        self._populate_single_row(j)
                    self.setFocusId(ROW_WRAPLIST_BASE + new_row * ROW_STEP)
                    self._last_focused_row = new_row
                    self._update_hero(new_row)
                else:
                    self.setFocusId(CLOSE_BTN)   # first row → EXIT button
                return
            return

        if aid == ACTION_DOWN:
            fid = self.getFocusId()
            i = self._row_from_fid(fid)
            if i >= 0:
                if i < self._num_rows - 1:
                    new_row = i + 1
                    for j in range(max(0, new_row - 1), min(self._num_rows, new_row + 3)):
                        self._populate_single_row(j)
                    self.setFocusId(ROW_WRAPLIST_BASE + new_row * ROW_STEP)
                    self._last_focused_row = new_row
                    self._update_hero(new_row)
                return
            # DOWN from EXIT → first row
            if fid == CLOSE_BTN:
                self._populate_single_row(0)
                self.setFocusId(ROW_WRAPLIST_BASE)
                self._last_focused_row = 0
                self._update_hero(0)
                return
        # Mouse move: compute hovered card slot, update hero + hover frame
        if aid == ACTION_MOUSE_MOVE:
            fid = self.getFocusId()
            for i in range(self._num_rows):
                if fid == ROW_OVERLAY_BASE + i * ROW_STEP:
                    try:
                        mx   = int(action.getAmount1())
                        # action.getAmount1/2 returns physical screen pixels, not skin coords.
                        # Convert to skin space (skin is 1920px wide for 1080i).
                        try:
                            screen_w = xbmcgui.getScreenWidth()
                            skin_x = mx * 1920 // max(1, screen_w)
                        except Exception:
                            skin_x = mx
                        slot = max(0, min(6, skin_x // 278))
                        if slot != self._hover_slot.get(i, -1):
                            self._hover_slot[i] = slot
                            n_items = len(self.rows_data[i][1]) if i < len(self.rows_data) else 0
                            if n_items > 0:
                                base    = self._hover_base.get(i, 0)
                                raw_idx = base + slot
                                if raw_idx >= n_items:
                                    # Ghost slot — hide hover box and do nothing else
                                    self._hide_hover_box(i)
                                    self._hover_box_row = -1
                                    self._hover_item[i] = -1
                                    return
                                else:
                                    new_idx = raw_idx % n_items
                                    self._hover_item[i] = new_idx
                                cur_sel = int(self.getControl(ROW_WRAPLIST_BASE + i * ROW_STEP).getSelectedPosition() or 0)
                                # Move hover-frame to the correct card slot (y=42 = label_h)
                                if self._hover_box_row >= 0 and self._hover_box_row != i:
                                    self._hide_hover_box(self._hover_box_row)
                                try:
                                    self.getControl(HOVER_BOX_BASE + i * ROW_STEP).setPosition(slot * 278, 54)
                                    self._hover_box_row = i
                                except Exception:
                                    pass
                                # Update hero directly - wraplist NOT touched, no scroll
                                self._update_hero(i, pos=new_idx)
                    except Exception:
                        pass
                    return
            return

        # LEFT/RIGHT on wraplist: native Kodi handles item selection; Python refreshes hero.
        # On overlay (mouse parked): transfer focus to wraplist for next keypress.
        # On hero buttons: XML <onleft>/<onright> already handles it — Python stays out.
        if aid in (ACTION_LEFT, ACTION_RIGHT):
            fid = self.getFocusId()
            for i in range(self._num_rows):
                if fid == ROW_OVERLAY_BASE + i * ROW_STEP:
                    self.setFocusId(ROW_WRAPLIST_BASE + i * ROW_STEP)
                    return
                if fid == ROW_WRAPLIST_BASE + i * ROW_STEP:
                    self._last_focused_row = i
                    self._update_hero(i)
                    return
            return

    def _hero_item(self):
        """Return the currently highlighted Item from the hero row, or None."""
        i = self._last_focused_row
        if i >= len(self.rows_data):
            return None
        _, items = self.rows_data[i]
        if not items:
            return None
        # Mouse hover takes priority over wraplist keyboard selection.
        # _hover_item[i] is set by ACTION_MOUSE_MOVE and reflects the card
        # the user is actually looking at in the hero.
        pos = self._hover_item.get(i)
        if pos is None:
            try:
                pos = int(self.getControl(ROW_WRAPLIST_BASE + i * ROW_STEP).getSelectedPosition() or 0)
                if pos < 0 or pos >= len(items):
                    pos = 0
            except Exception:
                pos = 0
        elif pos < 0 or pos >= len(items):
            pos = 0
        return items[pos]

    def onClick(self, control_id):
        if control_id == CLOSE_BTN:
            self._alive = False
            self.close()
            return

        # ── Settings button → open addon settings dialog ──
        if control_id == SETTINGS_BTN:
            xbmcaddon.Addon().openSettings()
            return

        # ── Search button → open Netflix-style search overlay ──
        if control_id == SEARCH_BTN_HOME:
            xbmc.log('[NetflixHome] onClick SEARCH_BTN_HOME (109) triggered', xbmc.LOGINFO)
            xbmcgui.Dialog().notification('PrippiStream', 'Aprendo ricerca...', xbmcgui.NOTIFICATION_INFO, 1500)
            _open_search(parent_window=self)
            return

        # ── Overlay button click (mouse click on card) → open detail window ──
        for i in range(self._num_rows):
            if control_id == ROW_OVERLAY_BASE + i * ROW_STEP:
                try:
                    item_idx = self._hover_item.get(i)
                    if item_idx is None:
                        item_idx = int(self.getControl(ROW_WRAPLIST_BASE + i * ROW_STEP).getSelectedPosition() or 0)
                    items = self.rows_data[i][1]
                    if 0 <= item_idx < len(items):
                        self._open_detail(items[item_idx])
                except Exception as exc:
                    logger.error('[NetflixHome] overlay click row %d: %s' % (i, str(exc)))
                return

        # ── Per-row left/right arrow buttons ──
        for i in range(self._num_rows):
            la_id = ROW_LEFT_BASE  + i * ROW_STEP
            ra_id = ROW_RIGHT_BASE + i * ROW_STEP
            if control_id in (la_id, ra_id):
                wl_id = ROW_WRAPLIST_BASE + i * ROW_STEP
                try:
                    wl      = self.getControl(wl_id)
                    pos     = int(wl.getSelectedPosition() or 0)
                    n_items = len(self.rows_data[i][1]) if i < len(self.rows_data) else 0
                    if n_items > 0:
                        if control_id == la_id:
                            new_pos = (pos - ARROW_PAGE_SIZE) % n_items
                        else:
                            new_pos = (pos + ARROW_PAGE_SIZE) % n_items
                        wl.selectItem(new_pos)
                except Exception:
                    pass
                return

        # ── Wraplist item click (ENTER) → open detail window ──
        for i in range(self._num_rows):
            wl_id = ROW_WRAPLIST_BASE + i * ROW_STEP
            if control_id == wl_id:
                try:
                    pos = int(self.getControl(wl_id).getSelectedPosition() or 0)
                    if 0 <= pos < len(self.rows_data[i][1]):
                        self._open_detail(self.rows_data[i][1][pos])
                except Exception as exc:
                    logger.error('[NetflixHome] onClick row %d: %s' % (i, str(exc)))
                break

    def _launch(self, item):
        # Suppress the server-selection popup that mark_auto_as_watched would
        # otherwise show after playback ends.  We manage resume/next-ep ourselves.
        try:
            from core import db as _db_launch
            _db_launch['player']['suppress_server_popup'] = True
            _db_launch.close()
        except Exception:
            pass

        if item.action == 'findvideos':
            # SC movie or episode: direct play via RunPlugin.
            # Pre-clear any Kodi bookmark for this episode BEFORE RunPlugin.
            _purl = ''
            try:
                _purl = (watch_history.get(_cw_key(item)) or {}).get('played_url', '')
            except Exception:
                pass
            if _purl:
                _t_pre = threading.Thread(target=_clear_kodi_resume, args=(_purl,))
                _t_pre.daemon = True
                _t_pre.start()

            # Set locale.audiolanguage/subtitlelanguage before RunPlugin so Kodi
            # picks the right track from frame 0 (restored immediately after onAVStarted).
            _pre_play_set_lang(item)

            xbmc.executebuiltin('RunPlugin(plugin://plugin.video.prippistream/?%s)' % item.tourl())
            t = threading.Thread(target=self._wait_and_restore, args=(item,))
            t.daemon = True
            t.start()
        elif item.action == 'episodios':
            # SC TV show: show inline season/episode selector without leaving
            # the Netflix home (avoids all container/window navigation issues).
            # _select_episode is SC-specific; only call it for SC items.
            t = threading.Thread(target=self._select_episode, args=(item,))
            t.daemon = True
            t.start()
        else:
            # Non-SC item or any other action (e.g. 'check' from altadefinizione,
            # cineblog01, etc.): dispatch via RunPlugin → launcher.actions/findvideos
            # which handles all custom actions correctly without opening a container.
            _pre_play_set_lang(item)
            xbmc.executebuiltin('RunPlugin(plugin://plugin.video.prippistream/?%s)' % item.tourl())
            t = threading.Thread(target=self._wait_and_restore, args=(item,))
            t.daemon = True
            t.start()

    def _open_detail(self, item):
        """Open the detail window for item (called on the main Kodi GUI thread)."""
        # Save exact focus position before entering modal dialog
        saved_row = self._last_focused_row
        saved_pos = 0
        try:
            wl = self.getControl(ROW_WRAPLIST_BASE + saved_row * ROW_STEP)
            saved_pos = int(wl.getSelectedPosition() or 0)
        except Exception:
            pass

        self._bg_ui_pause.clear()
        try:
            win = DetailWindow('DetailWindow.xml', config.get_runtime_path(), item=item)
            win.doModal()
            result    = win._result
            sel_s     = getattr(win, '_selected_season',  None)
            sel_e     = getattr(win, '_selected_episode', None)
            del win
        finally:
            self._bg_ui_pause.set()

        # Restore focus to the exact row + item position.
        # When the DetailWindow was hosting a trailer (YouTube player), self.close()
        # was called from a background thread; the window transition may not be
        # complete by the time doModal() returns.  Mirror _restore_home()'s approach:
        # self.show() to bring the window to front, a brief wait, then bounce focus
        # through CLOSE_BTN before landing on the wraplist — this guarantees a real
        # focus change even if the wraplist was already focused before the dialog.
        try:
            wl_id = ROW_WRAPLIST_BASE + saved_row * ROW_STEP
            self._last_focused_row = saved_row
            self._last_focused_pos = saved_pos
            # Do NOT call self.show() here — the NetflixHome window never went away
            # (DetailWindow was a dialog on top). On Android TV, self.show() re-activates
            # the window and triggers the XML <defaultcontrol>2000</defaultcontrol> which
            # resets focus to row 0, overwriting everything we do afterwards.
            # Instead, just wait briefly for the dialog transition to finish and set focus.
            xbmc.sleep(300)
            self._pending_select_pos = (wl_id, saved_pos, 5)
            try:
                self.setFocusId(CLOSE_BTN)
            except Exception:
                pass
            xbmc.sleep(80)
            try:
                self.setFocusId(wl_id)
            except Exception:
                pass
        except Exception:
            pass
        if result == 'play':
            if sel_s is not None and sel_e is not None:
                # User picked a specific episode in the EpisodePicker.
                # Works for SC tvshow items (action='episodios') AND
                # for CW episode items that have a stored show URL.
                _show_url = (getattr(item, '_cw_show_url', '') or
                             (item.url if getattr(item, 'action', '') == 'episodios' else ''))
                if _show_url:
                    t_ep = threading.Thread(target=self._play_episode_direct,
                                            args=(item, sel_s, sel_e))
                    t_ep.daemon = True
                    t_ep.start()
                else:
                    self._launch(item)
            else:
                self._launch(item)
        elif result == 'removed_cw':
            # Item was removed from CW — refresh the CW row immediately
            self._refresh_cw_row()
        elif result == 'list':
            try:
                title = item.fulltitle or item.show or item.contentSerieName or ''
                if item.contentType == 'movie':
                    action_item = item.clone(action='add_pelicula_to_library')
                else:
                    action_item = item.clone(action='add_serie_to_library')
                xbmc.executebuiltin('RunPlugin(plugin://plugin.video.prippistream/?%s)' % action_item.tourl())
                xbmcgui.Dialog().notification(
                    'My List', '[B]%s[/B] aggiunto alla libreria' % title,
                    xbmcgui.NOTIFICATION_INFO, 2500)
            except Exception as exc:
                logger.error('[NetflixHome] MY LIST: %s' % str(exc))

    def _enforce_scroll_pos(self, wl_id, pos):
        """Background thread: hammer selectItem every 80ms for 1.5s to defeat skin scroll animations."""
        with self._scroll_lock:
            deadline = time.time() + 1.5
            while self._alive and time.time() < deadline:
                try:
                    cur = self.getControl(wl_id).getSelectedPosition()
                    if cur != pos:
                        self.getControl(wl_id).selectItem(pos)
                except Exception:
                    break
                xbmc.sleep(80)

    def _restore_home(self):
        """Bring this dialog back to front and restore keyboard focus to the last row+position."""
        try:
            self.show()
            row   = self._last_focused_row
            wl_id = ROW_WRAPLIST_BASE + row * ROW_STEP
            try:
                xbmc.sleep(600)
                # Give focus to wraplist so CW refresh triggers via onFocus.
                self._pending_select_pos = (wl_id, self._last_focused_pos, 5)
                self.setFocusId(CLOSE_BTN)
                xbmc.sleep(100)
                self.setFocusId(wl_id)
                # Also launch background thread that keeps enforcing the position
                # for 1.5s — defeats any skin animation that resets scroll to 0.
                t = threading.Thread(
                    target=self._enforce_scroll_pos,
                    args=(wl_id, self._last_focused_pos))
                t.daemon = True
                t.start()
            except Exception:
                try:
                    self.setFocusId(CLOSE_BTN)
                except Exception:
                    pass
        except Exception as exc:
            logger.error('[NetflixHome] _restore_home: %s' % str(exc))

    def _wait_and_restore(self, item=None, next_ep_ctx=None):
        """Wait for playback to start/end, track progress for CW, then restore home."""
        player  = _AvReadyPlayer()
        monitor = xbmc.Monitor()

        # ── Start audio/sub preference thread IMMEDIATELY ──
        # Must be launched BEFORE we wait for isPlaying() so the thread is already
        # blocking on av_started.wait() when onAVStarted fires (~1-2s into startup).
        # If called after isPlaying() is True, onAVStarted has already fired and
        # the event would never be received (15s timeout → silent failure).
        t_audio = threading.Thread(
            target=_apply_audio_sub_pref,
            args=(player, item),
            kwargs={'av_started_event': player.av_started})
        t_audio.daemon = True
        t_audio.start()

        # ── Wait up to 20 s for playback to actually start ──
        for _ in range(40):
            if not self._alive or monitor.abortRequested():
                return
            if player.isPlaying():
                break
            xbmc.sleep(500)
        else:
            return  # playback never started

        # ── Capture the actual played URL (vixcloud/CDN) for clean CW removal later ──
        _played_url = ''
        try:
            _played_url = player.getPlayingFile() or ''
        except Exception:
            pass

        # ── Seek to saved resume position if available ──
        cw_key = _cw_key(item) if item is not None else None
        if cw_key:
            entry = watch_history.get(cw_key)
            if entry:
                resume_t = float(entry.get('time_watched', 0))
                # For TV shows, only resume if the saved episode matches the one playing.
                # If the user picked a different episode, start from the beginning.
                if resume_t > 10 and entry.get('season') is not None:
                    _entry_s = int(entry.get('season', 0))
                    _entry_e = int(entry.get('episode', 0))
                    _item_s  = int(getattr(item, 'contentSeason', 0) or 0)
                    _item_e  = int(getattr(item, 'contentEpisodeNumber', 0) or 0)
                    if (_item_s or _item_e) and (_entry_s != _item_s or _entry_e != _item_e):
                        resume_t = 0  # different episode → start from the beginning
                if resume_t > 10:
                    # Wait for the A/V pipeline to be fully ready (onAVStarted) before
                    # seeking.  This is more reliable than a fixed 2 s sleep because it
                    # fires exactly when the decoder has enumerated all tracks — the
                    # earliest moment seekTime() is guaranteed to work.
                    # Fall back to 8 s timeout for streams that never raise onAVStarted
                    # (e.g. non-adaptive streams or old Kodi versions).
                    player.av_started.wait(timeout=8)
                    xbmc.sleep(500)   # brief settling pause after pipeline init
                    try:
                        player.seekTime(resume_t)
                        logger.info('[CW] resumed "%s" at %.0fs' %
                                    (entry.get('title', ''), resume_t))
                    except Exception as exc:
                        logger.error('[CW] seekTime: %s' % str(exc))
                    # After seek, getTotalTime() briefly returns a small value
                    # (only the buffered range), which can falsely trigger the
                    # 97%-completed check and delete the CW entry.  Wait up to
                    # 6 s for total_time to stabilise at the real episode length.
                    for _ in range(12):
                        xbmc.sleep(500)
                        if not player.isPlaying():
                            break
                        try:
                            _tt = player.getTotalTime()
                        except Exception:
                            _tt = 0
                        if _tt > resume_t + 30:
                            break   # total_time looks reliable

        # ── Reconstruct next_ep_ctx for episodes resumed from CW ──
        # _rebuild_ctx_from_cw makes 2 HTTP calls; runs here in the background thread
        # well before UPNEXT_COUNTDOWN is reached, so no user-visible delay.
        if next_ep_ctx is None and item is not None:
            next_ep_ctx = _rebuild_ctx_from_cw(item)

        logger.info('[UpNext] next_ep_ctx=%s  cw_show_url=%r  url=%r' % (
            'OK' if next_ep_ctx else 'None',
            getattr(item, '_cw_show_url', '') if item else '',
            getattr(item, 'url', '') if item else ''))

        # ── Track progress while playing ──
        actual_time            = 0.0
        total_time             = 0.0
        last_save              = -30.0
        _upnext_triggered      = False
        _upnext_user_cancelled = False
        _overlay               = None    # UpNextOverlayWindow instance
        _overlay_np_item       = None    # next episode item
        _overlay_np_ctx        = None    # next episode context
        _overlay_secs_left     = 0       # Python countdown (seconds)
        _overlay_total_secs    = 1       # initial value (avoid div-by-zero)

        while player.isPlaying() and self._alive and not monitor.abortRequested():
            try:
                actual_time = player.getTime()
                total_time  = player.getTotalTime()
            except Exception:
                pass

            # ── CW save ──
            if cw_key and total_time > 60 and actual_time > 60:
                if actual_time - last_save >= 30:
                    last_save = actual_time
                    if actual_time >= total_time * 0.97:
                        # Episode completed — advance TV series to next episode,
                        # or remove the CW entry if this was the last episode.
                        ct = getattr(item, 'contentType', '') or ''
                        # Mark current episode as watched before advancing/removing
                        if ct == 'episode' and cw_key:
                            _ep_s = int(getattr(item, 'contentSeason', 0) or 0)
                            _ep_e = int(getattr(item, 'contentEpisodeNumber', 0) or 0)
                            if _ep_s and _ep_e:
                                try:
                                    watch_history.mark_episode_watched(cw_key, _ep_s, _ep_e)
                                except Exception:
                                    pass
                        if ct == 'episode' and next_ep_ctx is not None:
                            # Use already-computed next ep if overlay built it,
                            # otherwise build it now.
                            if _overlay_np_item is not None and _overlay_np_ctx is not None:
                                _advance_item = _overlay_np_item
                                _advance_ctx  = _overlay_np_ctx
                            else:
                                _advance_item, _advance_ctx = _build_next_ep(next_ep_ctx)
                            if _advance_item is not None:
                                # Save the series key pointing at the next episode (position 0)
                                _advance_item._cw_show_url = getattr(item, '_cw_show_url', '')
                                _save_cw(_advance_item, cw_key, 0, 0)
                                logger.info('[CW] advanced series to S%02dE%02d' % (
                                    getattr(_advance_item, 'contentSeason', 0),
                                    getattr(_advance_item, 'contentEpisodeNumber', 0)))
                            else:
                                # Last episode of last season — series is done
                                watch_history.remove(cw_key)
                                logger.info('[CW] series fully watched, removed key %s' % cw_key)
                            cw_key = None
                        else:
                            # Movie, OR episode where we couldn't determine
                            # next-ep context (e.g. show_url missing).
                            # For movies: remove since there's no next episode.
                            # For episodes without context: DON'T remove — keep
                            # the entry so the user can resume if needed.
                            ct = getattr(item, 'contentType', '') or ''
                            if ct != 'episode':
                                watch_history.remove(cw_key)
                                cw_key = None
                            else:
                                # No next-ep context: advance to time=0 just as
                                # a marker that this ep was completed, but keep
                                # the entry until context is rebuilt on next launch.
                                _save_cw(item, cw_key, total_time, total_time,
                                         played_url=_played_url)
                                cw_key = None
                    else:
                        _save_cw(item, cw_key, actual_time, total_time, played_url=_played_url)

            # ── Trigger Up Next overlay ──
            if (not _upnext_triggered
                    and next_ep_ctx is not None
                    and actual_time > 60):
                remaining = (total_time - actual_time) if total_time > 60 else float('inf')
                if 0 < remaining <= UPNEXT_COUNTDOWN:
                    logger.info('[UpNext] triggering at %.0fs / %.0fs (%.0fs left)' % (
                        actual_time, total_time, remaining))
                    _upnext_triggered = True
                    np_item, np_ctx = _build_next_ep(next_ep_ctx)
                    if np_item is not None:
                        _overlay_np_item    = np_item
                        _overlay_np_ctx     = np_ctx
                        _overlay_secs_left  = max(10, int(remaining))
                        _overlay_total_secs = _overlay_secs_left
                        s_n  = getattr(np_item, '_upnext_season',  0)
                        e_n  = getattr(np_item, '_upnext_episode', 0)
                        e_nm = (getattr(np_item, '_upnext_name', '') or '').strip()
                        ep_lbl = u'[B]S%02dE%02d[/B]' % (s_n, e_n)
                        if e_nm:
                            ep_lbl += u'  \u2014  ' + e_nm
                        try:
                            _overlay = UpNextOverlayWindow(
                                'UpNextOverlay.xml', config.get_runtime_path(),
                                ep_label=ep_lbl)
                            _overlay.show()
                        except Exception as exc:
                            logger.error('[UpNext] overlay show: %s' % str(exc))
                            _overlay = None

            # ── Update / check overlay ──
            if _overlay is not None:
                if _overlay.is_done():
                    # User clicked a button
                    result = _overlay._result
                    try:
                        _overlay.close()
                    except Exception:
                        pass
                    _overlay = None
                    if result == 'play':
                        if cw_key and total_time > 60:
                            watch_history.remove(cw_key)
                            cw_key = None
                        try:
                            if player.isPlaying():
                                player.stop()
                                xbmc.sleep(600)
                        except Exception:
                            pass
                        _pre_play_set_lang(_overlay_np_item)
                        xbmc.executebuiltin(
                            'RunPlugin(plugin://plugin.video.prippistream/?%s)'
                            % _overlay_np_item.tourl())
                        t_nx = threading.Thread(
                            target=self._wait_and_restore,
                            args=(_overlay_np_item,),
                            kwargs={'next_ep_ctx': _overlay_np_ctx})
                        t_nx.daemon = True
                        t_nx.start()
                        return
                    else:
                        _upnext_user_cancelled = True
                        _overlay_np_item = _overlay_np_ctx = None
                else:
                    # Still showing — update countdown
                    pct = max(0, min(100, int(
                        (_overlay_total_secs - _overlay_secs_left) * 100
                        / _overlay_total_secs)))
                    _overlay.update(_overlay_secs_left, pct)
                    _overlay_secs_left -= 1
                    if _overlay_secs_left < 0:
                        # Countdown expired → auto-play
                        try:
                            _overlay.close()
                        except Exception:
                            pass
                        _overlay = None
                        if cw_key and total_time > 60:
                            watch_history.remove(cw_key)
                            cw_key = None
                        try:
                            if player.isPlaying():
                                player.stop()
                                xbmc.sleep(600)
                        except Exception:
                            pass
                        _pre_play_set_lang(_overlay_np_item)
                        xbmc.executebuiltin(
                            'RunPlugin(plugin://plugin.video.prippistream/?%s)'
                            % _overlay_np_item.tourl())
                        t_nx = threading.Thread(
                            target=self._wait_and_restore,
                            args=(_overlay_np_item,),
                            kwargs={'next_ep_ctx': _overlay_np_ctx})
                        t_nx.daemon = True
                        t_nx.start()
                        return

            xbmc.sleep(1000)

        # ── Video ended (while loop exited) ──

        # Determine if the episode finished naturally or was manually stopped.
        # Any stop before 97% of the total duration is treated as a manual stop:
        # no Up Next popup, no auto-play — just save CW and restore home.
        _finished_naturally = total_time > 60 and actual_time >= total_time * 0.97

        # Close overlay if still visible
        if _overlay is not None:
            try:
                _overlay.close()
            except Exception:
                pass
            _overlay = None
            # Only auto-play if the episode actually ended (not manually stopped)
            if _finished_naturally and _overlay_np_item is not None and not _upnext_user_cancelled:
                if cw_key and total_time > 60:
                    watch_history.remove(cw_key)
                    cw_key = None
                if not self._alive or monitor.abortRequested():
                    return
                xbmc.sleep(800)
                _pre_play_set_lang(_overlay_np_item)
                xbmc.executebuiltin(
                    'RunPlugin(plugin://plugin.video.prippistream/?%s)'
                    % _overlay_np_item.tourl())
                t_nx = threading.Thread(
                    target=self._wait_and_restore,
                    args=(_overlay_np_item,),
                    kwargs={'next_ep_ctx': _overlay_np_ctx})
                t_nx.daemon = True
                t_nx.start()
                return

        # ── Final CW save ──
        if cw_key and total_time > 60:
            if _finished_naturally:
                watch_history.remove(cw_key)
            elif actual_time > 60:
                _save_cw(item, cw_key, actual_time, total_time, played_url=_played_url)

        if not self._alive or monitor.abortRequested():
            return

        xbmc.sleep(800)

        # ── Fallback: overlay never shown (e.g. total_time was unreliable) ──
        # Only fires when the episode ended naturally AND ≥80% was watched.
        # Never fires on manual stop.
        _watched_enough = (
            total_time <= 60                          # total_time unknown → trust actual_time
            or actual_time >= total_time * 0.80       # watched ≥80 %
        )
        if (_finished_naturally
                and next_ep_ctx is not None
                and not _upnext_triggered
                and not _upnext_user_cancelled
                and actual_time >= UPNEXT_COUNTDOWN
                and _watched_enough):
            np_item, np_ctx = _build_next_ep(next_ep_ctx)
            if np_item is not None:
                s_n  = getattr(np_item, '_upnext_season',  0)
                e_n  = getattr(np_item, '_upnext_episode', 0)
                e_nm = (getattr(np_item, '_upnext_name', '') or '').strip()
                ep_lbl = u'[B]S%02dE%02d[/B]' % (s_n, e_n)
                if e_nm:
                    ep_lbl += u'  \u2014  ' + e_nm
                win_fb = None
                try:
                    win_fb = UpNextOverlayWindow(
                        'UpNextOverlay.xml', config.get_runtime_path(),
                        ep_label=ep_lbl)
                    fb_secs = 10
                    win_fb.show()
                    while fb_secs >= 0 and not win_fb.is_done():
                        mins = fb_secs // 60
                        secs = fb_secs % 60
                        pct = int((10 - fb_secs) * 100 / 10)
                        win_fb.update(fb_secs, pct)
                        xbmc.sleep(1000)
                        fb_secs -= 1
                    if not win_fb.is_done():
                        win_fb._result = 'play'
                    result = win_fb._result
                    win_fb.close()
                    win_fb = None
                except Exception as exc:
                    logger.error('[UpNext] fallback overlay: %s' % str(exc))
                    result = 'play'  # default to play on error
                if result == 'play':
                    _pre_play_set_lang(np_item)
                    xbmc.executebuiltin(
                        'RunPlugin(plugin://plugin.video.prippistream/?%s)'
                        % np_item.tourl())
                    t_nx = threading.Thread(
                        target=self._wait_and_restore,
                        args=(np_item,),
                        kwargs={'next_ep_ctx': np_ctx})
                    t_nx.daemon = True
                    t_nx.start()
                    return

        # Set the pending flag BEFORE _restore_home() / setFocusId() so that
        # onFocus (which fires when setFocusId posts its message to the GUI thread)
        # always finds the flag already True — eliminating the race condition where
        # onFocus fired before the flag was set and missed the refresh.
        if self._alive:
            self._cw_refresh_pending = True

        self._restore_home()

        # Always clear Kodi's own bookmark after watching — we manage resume
        # ourselves via CW. Wait 1.5s so Kodi finishes its own final-bookmark
        # write before we delete it.
        if _played_url and self._alive:
            xbmc.sleep(1500)
            try:
                _clear_kodi_resume(_played_url)
            except Exception as exc:
                logger.error('[CW] post-watch _clear_kodi_resume: %s' % str(exc))

        # Refresh the CW row + genre row progress bars.
        # _restore_home() bounces focus through CLOSE_BTN so onFocus always fires
        # and drains _cw_refresh_pending on the GUI thread. The sleep+check below
        # is a last-resort safety net: if onFocus still didn't fire (e.g. window
        # not yet active), poke focus again to trigger it. Never call
        # _refresh_cw_row() directly from this BG thread — all wl.reset()/
        # addItems() calls MUST run on the GUI thread via onFocus.
        xbmc.sleep(600)
        if self._alive and self._cw_refresh_pending:
            logger.warning('[CW] pending flag still set 600ms after restore — retrying focus bounce')
            try:
                self.setFocusId(CLOSE_BTN)  # triggers onFocus on GUI thread
            except Exception:
                pass

    def _refresh_cw_row(self):
        """Rebuild the Continue Watching row in-place without full home reload.
        rows_data[0] is always the CW row — just update its items list.
        Also re-applies CW progress data to any SC rows already rendered, so
        that progress bars appear in genre carousels even when CW was empty at load.
        """
        try:
            logger.info('[CW] _refresh_cw_row: start (populated=%s)' % sorted(self._populated))
            cw_items = _build_cw_items()   # also rebuilds _cw_lookup_by_tmdb/title
            logger.info('[CW] _refresh_cw_row: cw_items=%d tmdb_keys=%d title_keys=%d' % (
                len(cw_items), len(_cw_lookup_by_tmdb), len(_cw_lookup_by_title)))
            with self._rows_lock:
                self.rows_data[0] = (_CW_ROW_LABEL, cw_items)

            # Refresh CW row itself.
            # Must reset() the wraplist explicitly here because _populate_single_row
            # no longer calls reset() (removing it fixed the scroll-to-top bug on TV).
            wl_cw_id = ROW_WRAPLIST_BASE  # row 0 → base id, no offset
            try:
                self.getControl(wl_cw_id).reset()
                xbmc.sleep(100)
            except Exception:
                pass
            self._populated.discard(0)
            self._populate_single_row(0)

            # Re-apply (or clear) CW data on all SC rows already rendered.
            # SC rows start at index 1.
            # We always do this — even when cw_items is empty — so that items
            # removed from CW lose their progress bar immediately.
            rows_changed = []
            for i in range(1, len(self.rows_data)):
                row_label, row_items = self.rows_data[i]
                changed = False
                n_matched = 0
                n_cleared = 0
                for it in row_items:
                    # Use __dict__.get — Item.__getattr__ returns '' for unknowns,
                    # causing '' > 0 TypeError.
                    old_time = float(it.__dict__.get('cw_time_watched', 0) or 0)
                    matched = _apply_cw_to_item(it)
                    new_time = float(it.__dict__.get('cw_time_watched', 0) or 0)
                    if matched:
                        n_matched += 1
                        if new_time != old_time:
                            changed = True
                    elif old_time > 0:
                        _clear_cw_from_item(it)
                        n_cleared += 1
                        changed = True
                if changed:
                    rows_changed.append(i)
                    logger.info('[CW] row %d "%s": matched=%d cleared=%d → re-render(in_populated=%s)' % (
                        i, row_label, n_matched, n_cleared, i in self._populated))
                if changed and i in self._populated:
                    # Re-render the wraplist for this row to update bar steps.
                    # SKIP if a position restore is pending: the reset() would zero out
                    # the wraplist's internal scroll position, fighting the restore.
                    # The updated item data is already in rows_data[i]; the re-render
                    # will happen naturally next time the user focuses that row.
                    wl_id = ROW_WRAPLIST_BASE + i * ROW_STEP
                    if self._pending_select_pos is not None and self._pending_select_pos[0] == wl_id:
                        logger.info('[CW] row %d re-render SKIPPED (position restore pending)' % i)
                        self._populated.discard(i)  # force re-render next time row is focused
                        continue
                    try:
                        currently_focused = (self.getFocusId() == wl_id)
                        if currently_focused:
                            try:
                                self.setFocusId(CLOSE_BTN)
                            except Exception:
                                pass
                        wl = self.getControl(wl_id)
                        cur_pos = int(wl.getSelectedPosition() or 0)
                        wl.reset()
                        xbmc.sleep(100)  # let the UI flush on slow ARM devices before addItems
                        wl.addItems([_item_to_li(it) for it in row_items])
                        if cur_pos > 0:
                            try:
                                wl.selectItem(cur_pos)
                            except Exception:
                                pass
                        if currently_focused:
                            try:
                                self.setFocusId(wl_id)
                            except Exception:
                                pass
                        logger.info('[CW] row %d re-render done (items=%d pos=%d)' % (
                            i, len(row_items), cur_pos))
                    except Exception as exc:
                        logger.error('[CW] _refresh_cw_row re-render row %d: %s' % (i, str(exc)))

            logger.info('[CW] _refresh_cw_row: done (rows_changed=%s)' % rows_changed)

        except Exception as exc:
            logger.error('[NetflixHome] _refresh_cw_row: %s' % str(exc))

    def _select_episode(self, item):
        """Episode picker for TV shows (runs in a background thread)."""
        try:
            # --- Fetch title page (has props.title.seasons) ---
            try:
                busy = xbmcgui.DialogBusy()
                busy.create()
            except Exception:
                busy = None
            try:
                data = _get_data(item.url)
            finally:
                if busy:
                    busy.close()

            seasons = (data.get('props') or {}).get('title', {}).get('seasons', [])
            if not seasons:
                xbmcgui.Dialog().notification(
                    'Errore', 'Nessuna stagione trovata',
                    xbmcgui.NOTIFICATION_WARNING, 3000)
                return

            # --- Season selection (skip if only 1) ---
            if len(seasons) == 1:
                season_idx = 0
                chosen = seasons[0]
            else:
                sl = ['Stagione %d  (%s ep.)' % (
                    s['number'], s.get('episodes_count', '?')) for s in seasons]
                season_idx = xbmcgui.Dialog().select('[B]%s[/B]' % item.fulltitle, sl)
                if season_idx < 0:
                    return
                chosen = seasons[season_idx]

            # --- Fetch episode list for chosen season ---
            try:
                busy = xbmcgui.DialogBusy()
                busy.create()
            except Exception:
                busy = None
            try:
                sdata = _get_data(item.url + '/season-%d' % chosen['number'])
            finally:
                if busy:
                    busy.close()

            episodes = (sdata.get('props') or {}).get('loadedSeason', {}).get('episodes', [])
            if not episodes:
                xbmcgui.Dialog().notification(
                    'Errore', 'Nessun episodio trovato',
                    xbmcgui.NOTIFICATION_WARNING, 3000)
                return

            # --- Episode selection ---
            el = ['%dx%02d  %s' % (
                chosen['number'], e['number'], e.get('name') or '') for e in episodes]
            ei = xbmcgui.Dialog().select(
                '[B]%s[/B]  –  Stagione %d' % (item.fulltitle, chosen['number']), el)
            if ei < 0:
                return

            ep = episodes[ei]
            title_id = str(chosen.get('title_id', ''))

            next_ep_ctx = {
                'show_item':  item,
                'seasons':    seasons,
                'season_idx': season_idx,
                'episodes':   episodes,
                'ep_idx':     ei,
                'title_id':   title_id,
            }

            import channels.streamingcommunity as _sc
            ep_item = item.clone(
                action='findvideos',
                contentType='episode',
                season=chosen['number'],
                episode=ep['number'],
                contentSeason=chosen['number'],
                contentEpisodeNumber=ep['number'],
                contentTitle='',
                url='%s/it/iframe/%s?episode_id=%s' % (_sc.host, title_id, ep['id'])
            )
            ep_item._cw_show_url = item.url   # preserve show URL for overlay when resumed from CW
            _pre_play_set_lang(ep_item)
            xbmc.executebuiltin('RunPlugin(plugin://plugin.video.prippistream/?%s)' % ep_item.tourl())
            t2 = threading.Thread(target=self._wait_and_restore, args=(ep_item,),
                                  kwargs={'next_ep_ctx': next_ep_ctx})
            t2.daemon = True
            t2.start()

        except Exception as exc:
            logger.error('[NetflixHome] _select_episode: %s' % str(exc))

    def _play_episode_direct(self, item, season_num, ep_num):
        """Play a specific episode (season_num, ep_num) directly from the show item.

        Mirrors _select_episode but skips the interactive dialogs, using the
        pre-selected season/episode from EpisodePickerDialog instead.
        Only works for StreamingCommunity items (action='episodios').
        """
        try:
            try:
                busy = xbmcgui.DialogBusy()
                busy.create()
            except Exception:
                busy = None
            # For CW episode items use the stored show URL; fall back to item.url
            _show_url = getattr(item, '_cw_show_url', '') or item.url
            try:
                data = _get_data(_show_url)
            finally:
                if busy:
                    busy.close()

            seasons = (data.get('props') or {}).get('title', {}).get('seasons', [])
            if not seasons:
                xbmcgui.Dialog().notification(
                    u'Errore', u'Nessuna stagione trovata',
                    xbmcgui.NOTIFICATION_WARNING, 3000)
                return

            # Find requested season
            chosen     = None
            season_idx = 0
            for _si, _s in enumerate(seasons):
                if _s.get('number') == season_num:
                    chosen     = _s
                    season_idx = _si
                    break
            if not chosen:
                chosen     = seasons[0]
                season_idx = 0

            # Fetch episode list for chosen season — use _show_url (show page), NOT item.url
            try:
                busy = xbmcgui.DialogBusy()
                busy.create()
            except Exception:
                busy = None
            try:
                sdata = _get_data(_show_url + '/season-%d' % chosen['number'])
            finally:
                if busy:
                    busy.close()

            episodes = (sdata.get('props') or {}).get('loadedSeason', {}).get('episodes', [])
            if not episodes:
                xbmcgui.Dialog().notification(
                    u'Errore', u'Nessun episodio trovato',
                    xbmcgui.NOTIFICATION_WARNING, 3000)
                return

            # Find requested episode
            ep     = None
            ep_idx = 0
            for _ei, _ep in enumerate(episodes):
                if _ep.get('number') == ep_num:
                    ep     = _ep
                    ep_idx = _ei
                    break
            if not ep:
                # Fall back to first episode
                ep     = episodes[0]
                ep_idx = 0

            title_id   = str(chosen.get('title_id', ''))
            next_ep_ctx = {
                'show_item':  item,
                'seasons':    seasons,
                'season_idx': season_idx,
                'episodes':   episodes,
                'ep_idx':     ep_idx,
                'title_id':   title_id,
            }

            import channels.streamingcommunity as _sc
            ep_item = item.clone(
                action='findvideos',
                contentType='episode',
                season=chosen['number'],
                episode=ep['number'],
                contentSeason=chosen['number'],
                contentEpisodeNumber=ep['number'],
                contentTitle='',
                url='%s/it/iframe/%s?episode_id=%s' % (_sc.host, title_id, ep['id'])
            )
            ep_item._cw_show_url = _show_url  # show page URL, never the iframe URL
            _pre_play_set_lang(ep_item)
            xbmc.executebuiltin(
                'RunPlugin(plugin://plugin.video.prippistream/?%s)' % ep_item.tourl())
            t2 = threading.Thread(target=self._wait_and_restore, args=(ep_item,),
                                  kwargs={'next_ep_ctx': next_ep_ctx})
            t2.daemon = True
            t2.start()
        except Exception as exc:
            logger.error('[NetflixHome] _play_episode_direct: %s' % str(exc))

# ── Continue Watching save helper ────────────────────────────────

def _save_cw(item, key, actual_time, total_time, played_url=''):
    """Persist a watch-progress entry for *item* to the CW database."""
    try:
        title = (getattr(item, 'fulltitle', '') or
                 getattr(item, 'show', '') or
                 getattr(item, 'contentSerieName', '') or '')
        ct    = getattr(item, 'contentType', '') or ''
        s     = 0
        e_num = 0
        ep_title = ''
        if ct == 'episode':
            s     = int(getattr(item, 'contentSeason', 0) or 0)
            e_num = int(getattr(item, 'contentEpisodeNumber', 0) or 0)
            ep_title = (getattr(item, 'contentTitle', '') or
                        getattr(item, '_upnext_name', '') or '')
            if s or e_num:
                title = '%s  S%02dE%02d' % (title, s, e_num)
        thumb    = getattr(item, 'thumbnail', '') or ''
        fanart   = getattr(item, 'fanart', '') or thumb
        show_url = getattr(item, '_cw_show_url', '') or ''
        watch_history.save_progress(
            key, title, thumb, fanart,
            actual_time, total_time,
            item.tourl(),
            show_url=show_url,
            played_url=played_url,
            season=s if (ct == 'episode' and s) else None,
            episode=e_num if (ct == 'episode' and e_num) else None,
            episode_title=ep_title,
        )
    except Exception as exc:
        logger.error('[CW] _save_cw: %s' % str(exc))


# ── Up Next helpers ────────────────────────────────────────────────────────────

def _rebuild_ctx_from_cw(item):
    """
    Reconstruct next_ep_ctx for an episode item that was launched from the CW row.
    Requires item._cw_show_url to be set (the SC titles page URL for the series).
    Makes 2 HTTP calls; called from the background _wait_and_restore thread.
    Returns a next_ep_ctx dict, or None on failure / non-episode.
    """
    try:
        show_url = getattr(item, '_cw_show_url', '') or ''
        if getattr(item, 'contentType', '') != 'episode':
            return None
        cur_s = int(getattr(item, 'contentSeason', 0) or 0)
        cur_e = int(getattr(item, 'contentEpisodeNumber', 0) or 0)
        url   = getattr(item, 'url', '') or ''
        m = re.search(r'/iframe/(\d+)', url)
        if not m:
            return None
        title_id = m.group(1)

        # If show_url is missing, reconstruct it from the iframe URL + SC host.
        # show_url is like  https://streamingcommunityz.ooo/it/titles/1243-new-girl
        # SC REQUIRES the slug — /it/titles/1243 alone returns no data-page.
        # We build the slug from item.show / item.fulltitle (e.g. "New Girl" → "new-girl").
        if not show_url:
            try:
                import channels.streamingcommunity as _sc_mod
                _sc_host = _sc_mod.host
            except Exception:
                _m = re.match(r'(https?://[^/]+)', url)
                _sc_host = _m.group(1) if _m else ''
            show_name = (getattr(item, 'show', '') or
                         getattr(item, 'contentSerieName', '') or
                         getattr(item, 'fulltitle', '') or '')
            slug = re.sub(r'[^a-z0-9]+', '-',
                          show_name.lower().strip()).strip('-') if show_name else ''
            if _sc_host and slug:
                show_url = '%s/it/titles/%s-%s' % (_sc_host, title_id, slug)
                logger.info('[UpNext] _rebuild_ctx: guessed show_url=%s' % show_url)
        if not show_url:
            return None

        # Fetch seasons list
        data    = _get_data(show_url)
        seasons = (data.get('props') or {}).get('title', {}).get('seasons', [])
        if not seasons:
            return None

        # Find current season index
        season_idx = 0
        for si, s in enumerate(seasons):
            if s.get('number') == cur_s:
                season_idx = si
                break

        # Fetch episode list for current season
        chosen   = seasons[season_idx]
        sdata    = _get_data(show_url + '/season-%d' % chosen['number'])
        episodes = (sdata.get('props') or {}).get('loadedSeason', {}).get('episodes', [])
        if not episodes:
            return None

        # Find current episode index
        ep_idx = 0
        for ei, ep in enumerate(episodes):
            if ep.get('number') == cur_e:
                ep_idx = ei
                break

        show_item = item.clone(action='episodios', contentType='tvshow', url=show_url)
        logger.info('[UpNext] rebuilt ctx from CW: S%02dE%02d, %d seasons, %d eps in S%d'
                    % (cur_s, cur_e, len(seasons), len(episodes), cur_s))
        return {
            'show_item':  show_item,
            'seasons':    seasons,
            'season_idx': season_idx,
            'episodes':   episodes,
            'ep_idx':     ep_idx,
            'title_id':   title_id,
        }
    except Exception as exc:
        logger.error('[UpNext] _rebuild_ctx_from_cw: %s' % str(exc))
        return None


def _apply_cw_to_item(it):
    """
    If 'it' matches a CW entry (by TMDB ID or normalised show name), copy the
    CW progress data onto it and make it act as a direct episode play — identical
    to clicking the same item in the CW row.
    Modifies 'it' in-place; no-op when there is no match.
    Returns True if a CW match was found and applied, False otherwise.
    """
    global _cw_lookup_by_tmdb, _cw_lookup_by_title
    tmdb = str(it.infoLabels.get('tmdb_id') or '').strip()
    cw_match = _cw_lookup_by_tmdb.get(tmdb) if tmdb else None
    if cw_match is None:
        show_name = (getattr(it, 'show', '') or
                     getattr(it, 'contentSerieName', '') or
                     getattr(it, 'fulltitle', '') or '')
        norm = _normalize_title(show_name)
        cw_match = _cw_lookup_by_title.get(norm) if norm else None
    if cw_match is None:
        return False
    # Save original state the first time we modify this item so it can be restored later
    if not hasattr(it, '_orig_cw_state'):
        it._orig_cw_state = {
            # Use __dict__.get (not getattr) — Item.__getattr__ returns '' for unknowns,
            # which would corrupt the saved state and cause '' > 0 TypeError later.
            'cw_time_watched':      float(it.__dict__.get('cw_time_watched', 0) or 0),
            'cw_total_time':        float(it.__dict__.get('cw_total_time', 0) or 0),
            'action':               getattr(it, 'action', ''),
            'url':                  getattr(it, 'url', ''),
            'contentType':          getattr(it, 'contentType', ''),
            'contentSeason':        getattr(it, 'contentSeason', 0),
            'contentEpisodeNumber': getattr(it, 'contentEpisodeNumber', 0),
            '_cw_show_url':         getattr(it, '_cw_show_url', ''),
        }
    # Apply progress bar data
    it.cw_time_watched = cw_match.cw_time_watched
    it.cw_total_time   = cw_match.cw_total_time
    # Make it play the same episode (direct video play, bypassing season picker)
    it.action               = cw_match.action
    it.url                  = cw_match.url
    it.contentType          = cw_match.contentType
    it.contentSeason        = getattr(cw_match, 'contentSeason', 0)
    it.contentEpisodeNumber = getattr(cw_match, 'contentEpisodeNumber', 0)
    it._cw_show_url         = getattr(cw_match, '_cw_show_url', '')
    return True


def _clear_cw_from_item(it):
    """
    Undo a previous _apply_cw_to_item call: restore the item to its original
    state (action, url, contentType, etc.) and zero progress bar fields.
    """
    orig = getattr(it, '_orig_cw_state', None)
    if orig:
        it.cw_time_watched      = orig['cw_time_watched']
        it.cw_total_time        = orig['cw_total_time']
        it.action               = orig['action']
        it.url                  = orig['url']
        it.contentType          = orig['contentType']
        it.contentSeason        = orig['contentSeason']
        it.contentEpisodeNumber = orig['contentEpisodeNumber']
        it._cw_show_url         = orig['_cw_show_url']
        del it._orig_cw_state
    else:
        it.cw_time_watched = 0
        it.cw_total_time   = 0


def _build_next_ep(ctx):
    """
    Given a next_ep_ctx dict describing the current episode, return
    (ep_item, new_ctx) for the immediately following episode, or (None, None)
    if no next episode exists or on network error.

    ctx keys:
      show_item  – original SC Item (action='seasons' or similar)
      seasons    – list of all season dicts from the SC API
      season_idx – int index of current season in `seasons`
      episodes   – list of episode dicts for the current season
      ep_idx     – int index of current episode in `episodes`
      title_id   – str, the SC series title id
    """
    try:
        show_item  = ctx['show_item']
        seasons    = ctx['seasons']
        si         = int(ctx['season_idx'])
        episodes   = ctx['episodes']
        ei         = int(ctx['ep_idx'])
        title_id   = ctx['title_id']

        import channels.streamingcommunity as _sc

        # ── next episode in the same season ──────────────────────────────────
        if ei + 1 < len(episodes):
            next_ei     = ei + 1
            next_ep     = episodes[next_ei]
            next_season = seasons[si]
            new_ctx     = dict(ctx, ep_idx=next_ei)

        # ── first episode of the next season ─────────────────────────────────
        elif si + 1 < len(seasons):
            next_si     = si + 1
            next_season = seasons[next_si]
            try:
                sdata = _get_data(show_item.url + '/season-%d' % next_season['number'])
            except Exception as exc:
                logger.error('[UpNext] fetch next season: %s' % str(exc))
                return None, None
            next_eps = (sdata.get('props') or {}).get('loadedSeason', {}).get('episodes', [])
            if not next_eps:
                return None, None
            next_ep = next_eps[0]
            new_ctx = dict(ctx, season_idx=next_si, episodes=next_eps, ep_idx=0)

        else:
            return None, None   # last episode of last season

        ep_item = show_item.clone(
            action='findvideos',
            contentType='episode',
            season=next_season['number'],
            episode=next_ep['number'],
            contentSeason=next_season['number'],
            contentEpisodeNumber=next_ep['number'],
            contentTitle='',
            url='%s/it/iframe/%s?episode_id=%s' % (_sc.host, title_id, next_ep['id'])
        )
        ep_item._upnext_season  = next_season['number']
        ep_item._upnext_episode = next_ep['number']
        ep_item._upnext_name    = (next_ep.get('name') or '').strip()
        return ep_item, new_ctx

    except Exception as exc:
        logger.error('[UpNext] _build_next_ep: %s' % str(exc))
        return None, None


# ── Module-level helpers ────────────────────────────────────────────────────────

def _apply_audio_sub_pref(player, item, av_started_event=None):
    """
    Apply the user's saved subtitle preference for this content after onAVStarted.
    Audio track selection is now handled by setting locale.audiolanguage BEFORE
    RunPlugin (see _launch), so Kodi picks the right track from frame 0 with no skip.
    This function only handles subtitles (on/off/language).
    """
    try:
        if item is None:
            return
        addon   = xbmcaddon.Addon()
        tmdb_id = str(item.infoLabels.get('tmdb_id') or '').strip()
        key     = tmdb_id or re.sub(r'[^a-z0-9]', '',
                                    (item.fulltitle or item.show or '').lower())
        if not key:
            return

        audio_pref = addon.getSetting('audiolang_%s' % key) or ''
        sub_pref   = addon.getSetting('sublang_%s'   % key) or ''
        if not sub_pref:
            return   # no subtitle preference → leave as-is

        # Wait for A/V pipeline ready before touching subtitle tracks
        if av_started_event is not None:
            av_started_event.wait(timeout=15)
        else:
            for _ in range(50):
                xbmc.sleep(100)
                if not player.isPlaying():
                    return
                if player.getAvailableAudioStreams():
                    break

        if not player.isPlaying():
            return

        # ── Subtitles ──
        if sub_pref == u'Nessun sottotitolo':
            player.showSubtitles(False)
        else:
            target_sub = None
            if 'Italiano' in sub_pref:
                target_sub = 'ital'
            elif 'Inglese' in sub_pref:
                target_sub = 'engl'
            elif 'Come audio' in sub_pref:
                if audio_pref and 'Italiano' in audio_pref:
                    target_sub = 'ital'
                elif audio_pref and 'Inglese' in audio_pref:
                    target_sub = 'engl'
            if target_sub:
                sub_streams = player.getAvailableSubtitleStreams()
                chosen = None
                for idx, s in enumerate(sub_streams):
                    sl = s.lower()
                    if target_sub in sl or \
                            (target_sub == 'ital' and sl in ('it', 'ita')) or \
                            (target_sub == 'engl' and sl in ('en', 'eng')):
                        chosen = idx
                        break
                if chosen is not None:
                    player.setSubtitleStream(chosen)
                    player.showSubtitles(True)
    except Exception as exc:
        logger.error('[CW] _apply_audio_sub_pref: %s' % str(exc))


def _clear_kodi_resume(ep_url):
    """Delete Kodi's internal resume/progress data for a StreamingCommunity episode.

    Kodi stores resume points in MyVideosXXX.db.  For SC/vixcloud content:
        path.strPath   = 'https://vixcloud.co/playlist/'
        files.strFilename = '<episode_id>'  (just the number)
    We extract episode_id from the iframe URL (?episode_id=NNN) and:
      1. Delete all bookmarks for that file  (removes the "Resume from" dialog)
      2. Delete the files row itself         (removes it from Kodi's own In-Progress list)
    """
    try:
        import glob as _glob
        import os   as _os
        import sqlite3 as _sqlite3

        logger.info('[CW] _clear_kodi_resume called with url: %s' % (ep_url or '(none)'))

        # played_url is the vixcloud URL: https://vixcloud.co/playlist/697221?token=...
        # Extract the numeric ID from the path segment (not ?episode_id= param).
        m = re.search(r'/playlist/(\d+)', ep_url or '')
        if not m:
            logger.info('[CW] _clear_kodi_resume: no playlist ID in url, skipping')
            return
        ep_id = m.group(1)
        logger.info('[CW] _clear_kodi_resume: vixcloud_id=%s' % ep_id)

        db_dir = xbmc.translatePath('special://database/')
        dbs = _glob.glob(_os.path.join(db_dir, 'MyVideos*.db'))
        if not dbs:
            logger.warning('[CW] _clear_kodi_resume: no MyVideos*.db found in %s' % db_dir)
            return
        db_path = max(dbs, key=_os.path.getmtime)  # highest version = active DB
        logger.info('[CW] _clear_kodi_resume: using db=%s' % db_path)

        conn = _sqlite3.connect(db_path, timeout=8)
        try:
            # Find idFile(s) matching this episode
            id_rows = conn.execute(
                "SELECT f.idFile FROM files f"
                " JOIN path p ON p.idPath=f.idPath"
                " WHERE p.strPath='https://vixcloud.co/playlist/'"
                "   AND f.strFilename=?",
                (ep_id,)
            ).fetchall()
            if not id_rows:
                logger.info('[CW] _clear_kodi_resume: ep_id=%s not found in files table' % ep_id)
                return
            id_list = [r[0] for r in id_rows]
            placeholders = ','.join('?' * len(id_list))
            # 1. Delete all bookmarks for this file
            c1 = conn.execute("DELETE FROM bookmark WHERE idFile IN (%s)" % placeholders, id_list)
            # 2. Delete the files entry itself (removes it from Kodi In-Progress)
            c2 = conn.execute("DELETE FROM files  WHERE idFile IN (%s)" % placeholders, id_list)
            conn.commit()
            logger.info('[CW] Kodi cleared ep_id=%s: bookmarks=%d files=%d'
                        % (ep_id, c1.rowcount, c2.rowcount))
        finally:
            conn.close()
    except Exception as exc:
        logger.error('[CW] _clear_kodi_resume: %s' % str(exc))


def _nuke_all_vixcloud_bookmarks():
    """Delete ALL Kodi resume bookmarks for vixcloud content.

    We manage our own resume system (CW DB). Kodi's built-in bookmarks only
    cause stale "Resume from" dialogs when replaying or navigating episodes.
    Called once at NetflixHome open time (fire-and-forget background thread)
    to clean up any bookmarks left over from prior sessions.
    """
    try:
        import glob as _glob
        import os   as _os
        import sqlite3 as _sqlite3

        db_dir = xbmc.translatePath('special://database/')
        dbs = _glob.glob(_os.path.join(db_dir, 'MyVideos*.db'))
        if not dbs:
            return
        db_path = max(dbs, key=_os.path.getmtime)

        conn = _sqlite3.connect(db_path, timeout=5)
        try:
            id_rows = conn.execute(
                "SELECT f.idFile FROM files f"
                " JOIN path p ON p.idPath=f.idPath"
                " WHERE p.strPath='https://vixcloud.co/playlist/'"
            ).fetchall()
            if not id_rows:
                logger.info('[CW] startup nuke: no vixcloud files found, skipping')
                return
            id_list = [r[0] for r in id_rows]
            placeholders = ','.join('?' * len(id_list))
            c1 = conn.execute("DELETE FROM bookmark WHERE idFile IN (%s)" % placeholders, id_list)
            c2 = conn.execute("DELETE FROM files   WHERE idFile IN (%s)" % placeholders, id_list)
            conn.commit()
            logger.info('[CW] startup nuke: cleared vixcloud bookmarks=%d files=%d'
                        % (c1.rowcount, c2.rowcount))
        finally:
            conn.close()
    except Exception as exc:
        logger.error('[CW] _nuke_all_vixcloud_bookmarks: %s' % str(exc))


def _cdnthumb(img_dict, host):
    url = (img_dict.get('original_url') or '').strip()
    if url:
        return url
    fname = (img_dict.get('filename') or '').strip()
    if fname:
        domain = host.split('://', 1)[-1]
        if domain.startswith('www.'):
            domain = domain[4:]
        return 'https://cdn.' + domain + '/images/' + fname
    return ''


def _build_item(raw, host):
    title = (raw.get('name') or '').strip()
    if not title:
        return None
    item_id   = raw.get('id', '')
    slug      = raw.get('slug') or str(item_id)
    item_type = (raw.get('type') or 'movie').replace('tv', 'tvshow')
    lang      = 'Sub-ITA' if raw.get('sub_ita', 0) == 1 else 'ITA'
    dstr      = raw.get('last_air_date') or raw.get('release_date') or ''
    year      = str(dstr).split('-')[0] if dstr else ''
    # Extract TMDB/IMDB IDs from SC raw data so TMDB can search by ID (faster + includes videos)
    tmdb_id   = str(raw.get('tmdb_id') or raw.get('tmdb') or '')
    imdb_id   = str(raw.get('imdb_id') or raw.get('imdb') or '')

    thumb = fanart = ''
    for img in (raw.get('images') or []):
        itype = (img.get('type') or '').lower()
        url   = _cdnthumb(img, host)
        if not url:
            continue
        if itype in ('poster', 'cover') and not thumb:
            thumb = url
        elif itype in ('backdrop', 'background', 'banner') and not fanart:
            fanart = url
        elif not thumb:
            thumb = url
    if not fanart:
        fanart = thumb

    plot = (raw.get('plot') or raw.get('description') or raw.get('overview') or '').strip()

    if item_type == 'movie':
        it = Item(
            channel='streamingcommunity',
            action='findvideos',
            contentType='movie',
            fulltitle=title, show=title, contentTitle=title,
            url=host + '/it/watch/%s' % item_id,
            thumbnail=thumb, fanart=fanart,
            year=year, language=lang,
        )
        it.infoLabels['title'] = title
        if year:
            it.infoLabels['year'] = year
        if plot:
            it.infoLabels['plot'] = plot
        if tmdb_id:
            it.infoLabels['tmdb_id'] = tmdb_id
        if imdb_id:
            it.infoLabels['imdb_id'] = imdb_id
    else:
        it = Item(
            channel='streamingcommunity',
            action='episodios',
            contentType='tvshow',
            fulltitle=title, show=title, contentSerieName=title,
            url=host + '/it/titles/%s-%s' % (item_id, slug),
            thumbnail=thumb, fanart=fanart,
            year=year, language=lang,
        )
        it.infoLabels['title'] = title
        it.infoLabels['tvshowtitle'] = title
        if year:
            it.infoLabels['year'] = year
        if plot:
            it.infoLabels['plot'] = plot
        if tmdb_id:
            it.infoLabels['tmdb_id'] = tmdb_id
        if imdb_id:
            it.infoLabels['imdb_id'] = imdb_id
    return it


def _item_to_li(item):
    title  = item.fulltitle or item.show or item.contentSerieName or ''
    thumb  = item.thumbnail or ''
    fanart = item.fanart or thumb
    plot   = (item.infoLabels.get('plot') or getattr(item, 'plot', '') or '').strip()
    li = xbmcgui.ListItem(title)
    li.setArt({'thumb': thumb, 'poster': thumb, 'fanart': fanart})
    li.setProperty('thumbnail',    thumb)
    li.setProperty('fanart_image', fanart)
    li.setProperty('title',        title)
    li.setProperty('year',         str(item.year or ''))
    li.setProperty('lang',         getattr(item, 'language', '') or '')
    li.setProperty('plot',         plot)
    li.setProperty('rating',       str(item.infoLabels.get('rating') or ''))
    li.setProperty('genre',        str(item.infoLabels.get('genre') or ''))
    # setInfo MUST run BEFORE setResumePoint: in Kodi 21 setInfo internally
    # re-initialises the VideoInfoTag, wiping any previously set resume point.
    info_type = 'movie' if getattr(item, 'contentType', '') == 'movie' else 'video'
    info_dict = {}
    for _k in ('title', 'year', 'plot', 'rating', 'votes', 'genre',
               'director', 'cast', 'runtime', 'season', 'episode', 'tvshowtitle'):
        _v = item.infoLabels.get(_k)
        if _v is not None:
            info_dict[_k] = _v
    if info_dict:
        li.setInfo(info_type, info_dict)
    # Continue Watching progress bar — AFTER setInfo so resume point is preserved.
    # Uses bar_step (1-9) for a 10-step image-based bar in the XML.
    cw_time  = float(getattr(item, 'cw_time_watched', 0) or 0)
    cw_total = float(getattr(item, 'cw_total_time', 0) or 0)
    if cw_time > 0 and cw_total > 0:
        pct  = max(0, min(96, int(cw_time / cw_total * 100)))
        step = pct // 10   # 0..9  (step 0 = <10%, no bar shown)
        if step >= 1:
            li.setProperty('has_progress', '1')
            li.setProperty('bar_step',     str(step))
        try:
            vt = li.getVideoInfoTag()
            vt.setResumePoint(cw_time, cw_total)
            vt.setPlaycount(0)
        except Exception:
            pass
    return li


def _extract_data_page(html):
    """
    Extract the data-page JSON object using brace-balanced scanning.
    Neither regex [^"]+ nor html.parser work because the raw HTML has literal "
    chars inside the data-page attribute value (SVG xmlns="..." etc.).
    Brace-counting ignores quotes entirely and finds the balanced {…} object.
    """
    marker = 'data-page="'
    idx = html.find(marker)
    if idx < 0:
        marker = "data-page='"
        idx = html.find(marker)
    if idx < 0:
        return ''
    start = html.find('{', idx + len(marker))
    if start < 0:
        return ''
    depth = 0
    for i in range(start, len(html)):
        c = html[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    return ''


def _strip_html_fields(s):
    """
    Remove "html":"..." JSON string values that contain SVG with unescaped ".
    The real JSON-closing " is identified by being followed by , } or ].
    SVG attribute " chars are followed by HTML chars (letters, /, >, backslash) not those.
    """
    result = []
    i = 0
    field = '"html":"'
    flen = len(field)
    while i < len(s):
        if s[i:i + flen] == field:
            result.append('"html":""')
            i += flen
            while i < len(s):
                c = s[i]
                if c == '\\' and i + 1 < len(s):
                    i += 2          # valid JSON escape, skip both chars
                elif c == '"':
                    j = i + 1
                    while j < len(s) and s[j] in ' \t\r\n':
                        j += 1
                    if j < len(s) and s[j] in ',}]':
                        i += 1      # real JSON-closing "
                        break
                    else:
                        i += 1      # bare " inside SVG, skip
                else:
                    i += 1
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


def _get_data(url):
    """
    Extract data-page JSON from SC HTML page.
    Pipeline:
      1. httptools.downloadpage (with CF bypass via Google Translate proxy)
      2. brace-counting to extract the full JSON object (immune to bare " in SVG)
      3. html.unescape to decode &quot; entities
      4. _strip_html_fields to remove SVG banner content (has thousands of bare ")
      5. json.loads
    """
    import json as _json
    import html as _html
    from core import httptools

    if _shutdown_event.is_set():
        return {}
    try:
        resp = httptools.downloadpage(url, ignore_response_code=True)
        raw_html = resp.data if resp else ''
        if not raw_html:
            logger.error('[NetflixHome] empty response for %s' % url)
            return {}

        json_str = _extract_data_page(raw_html)
        if not json_str:
            logger.error('[NetflixHome] no data-page in html (len=%d) for %s' % (len(raw_html), url))
            return {}

        logger.info('[NetflixHome] json_str len=%d for %s' % (len(json_str), url))
        decoded   = _html.unescape(json_str)
        cleaned   = _strip_html_fields(decoded)
        try:
            result = _json.loads(cleaned)
        except Exception as e:
            logger.error('[NetflixHome] json.loads failed for %s: %s' % (url, str(e)[:120]))
            return {}

        if isinstance(result, dict) and result:
            logger.info('[NetflixHome] OK for %s sliders=%d' % (
                url, len(result.get('props', {}).get('sliders', []))))
            return result
    except Exception as exc:
        logger.error('[NetflixHome] exception for %s: %s' % (url, str(exc)))
    return {}


def _normalize_title(title):
    """Normalize a title for deduplication: lowercase, ASCII-only, strip articles."""
    import unicodedata
    if not title:
        return ''
    s = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^a-z0-9\s]', '', s.lower())
    s = re.sub(r'^(il|la|lo|gli|le|i|un|una|uno|the|a|an)\s+', '', s.strip())
    return s.strip()


def _extract_item_title(it):
    """Get the display title from any Item, stripping Kodi markup tags."""
    title = (
        getattr(it, 'fulltitle', '') or
        getattr(it, 'show', '') or
        getattr(it, 'contentSerieName', '') or
        getattr(it, 'contentTitle', '') or
        getattr(it, 'title', '') or ''
    ).strip()
    return re.sub(r'\[/?[A-Za-z][^\]]*\]', '', title).strip()


def _tmdb_get_trailer(tmdb_id, ctype='movie'):
    """
    Fetch the official YouTube trailer ID from the TMDB /videos endpoint.
    TMDB-sourced IDs are official uploads — never age-restricted.
    Returns YouTube video_id string, or None.
    Prefers Italian; falls back to English.
    """
    if not tmdb_id or _shutdown_event.is_set():
        return None
    try:
        from core import httptools
        import json as _json

        _TMDB_HOST = 'https://api.themoviedb.org/3'
        _TMDB_API  = 'a1ab8b8669da03637a4b98fa39c39228'
        media_type = 'tv' if str(ctype) == 'tv' else 'movie'

        def _fetch(lang):
            if _shutdown_event.is_set():
                return []
            url = '{}/{}/{}/videos?api_key={}&language={}'.format(
                _TMDB_HOST, media_type, tmdb_id, _TMDB_API, lang)
            resp = httptools.downloadpage(url, timeout=3, ignore_response_code=True)
            if not resp.success:
                return []
            return _json.loads(resp.data or '{}').get('results', [])

        for lang in ('it', 'en'):
            videos = _fetch(lang)
            # Prefer Trailer type on YouTube
            for v in videos:
                if v.get('site') == 'YouTube' and v.get('type') == 'Trailer':
                    return v['key']
            # Accept any YouTube video from this language
            for v in videos:
                if v.get('site') == 'YouTube':
                    return v['key']

        return None
    except Exception as exc:
        logger.error('[TMDBTrailer] %s' % str(exc)[:100])
        return None


# Public Invidious instances used as YouTube search API (tried in order, first success wins)
def _youtube_search_trailer(title, year=''):
    """
    Search YouTube for an Italian trailer using the YouTube internal API (youtubei v1).
    No API key required. Returns the YouTube video_id string or None.
    """
    try:
        from core import httptools
        import json as _json
        try:
            from urllib import quote_plus          # Py2 (Kodi 18)
        except ImportError:
            from urllib.parse import quote_plus    # Py3 (Kodi 19+)

        def _yt_search(query):
            # Exit immediately if Kodi is shutting down — prevents blocking
            # the CPythonInvoker for the full socket-timeout duration.
            if _shutdown_event.is_set():
                return None
            body = _json.dumps({
                'query': query,
                'context': {
                    'client': {
                        'clientName': 'WEB',
                        'clientVersion': '2.20240101.00.00',
                        'hl': 'it',
                        'gl': 'IT',
                    }
                }
            })
            resp = httptools.downloadpage(
                'https://www.youtube.com/youtubei/v1/search',
                post=body,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                    'Accept-Language': 'it-IT,it;q=0.9',
                },
                ignore_response_code=True,
                timeout=3   # short timeout so threads exit within Kodi's 5-s kill window
            )
            if not resp.success:
                return None
            data = _json.loads(resp.data or '{}')
            videos = []
            for section in (data.get('contents', {})
                            .get('twoColumnSearchResultsRenderer', {})
                            .get('primaryContents', {})
                            .get('sectionListRenderer', {})
                            .get('contents', [])):
                for item in section.get('itemSectionRenderer', {}).get('contents', []):
                    vr = item.get('videoRenderer', {})
                    vid = vr.get('videoId')
                    if not vid:
                        continue
                    # Skip age-restricted / sign-in required videos.
                    # YouTube may signal this in two different places in the API response:
                    # 1) badges list (metadataBadgeRenderer label)
                    # 2) overlayTimeStatusRenderer style = "LIVE" or in
                    #    videoRenderer.videoRequiresLogin (older responses)
                    badges = vr.get('badges', [])
                    age_gated = any(
                        b.get('metadataBadgeRenderer', {}).get('label', '').lower()
                        in ('age-restricted', 'age restricted', '18+', 'solo per adulti', 'contenuto per adulti')
                        for b in badges
                    )
                    # Also check overlayBadges (second field YouTube sometimes uses)
                    if not age_gated:
                        for b in vr.get('ownerBadges', []):
                            lbl = b.get('metadataBadgeRenderer', {}).get('label', '').lower()
                            if 'age' in lbl or '18+' in lbl:
                                age_gated = True
                                break
                    if age_gated:
                        continue
                    # Parse duration string "M:SS" -> seconds
                    dur_str = vr.get('lengthText', {}).get('simpleText', '') or ''
                    secs = 0
                    if dur_str:
                        parts = dur_str.split(':')
                        try:
                            secs = int(parts[-2]) * 60 + int(parts[-1]) if len(parts) >= 2 else int(parts[0])
                        except Exception:
                            pass
                    videos.append((vid, secs))
            # Prefer 45s-7min (real trailers)
            for vid, secs in videos:
                if 45 <= secs <= 420:
                    return vid
            # Fallback: first result
            return videos[0][0] if videos else None

        # Query 1: title + year + "trailer ufficiale italiano"
        parts = [title]
        if year:
            parts.append(year)
        parts.append('trailer ufficiale italiano')
        vid = _yt_search(' '.join(parts))
        if vid:
            logger.info('[YTSearch] "%s" → query1 → %s' % (title, vid))
            return vid

        # Query 2: title + "trailer italiano" (drop year)
        vid = _yt_search('%s trailer italiano' % title)
        if vid:
            logger.info('[YTSearch] "%s" → query2 → %s' % (title, vid))
            return vid

        # Query 3: English fallback
        vid = _yt_search('%s%s trailer official' % (title, (' ' + year) if year else ''))
        if vid:
            logger.info('[YTSearch] "%s" → query3 → %s' % (title, vid))
        return vid

    except Exception as exc:
        logger.error('[YTSearch] %s' % str(exc)[:100])
        return None


def _fetch_trailers_small(rows_snapshot, per_row=10, max_total=20):
    """
    Fetch trailers via YouTube search (youtubei internal API).
    Results are cached in the module-level _trailer_cache dict so that
    repeated window opens never re-fetch the same id.
    per_row: max items to take from each row.
    max_total: hard cap on new searches per call.
    """
    global _trailer_cache

    # Pass 1: apply cached results immediately (no network)
    for _, items in rows_snapshot:
        for it in items:
            tid = str(it.infoLabels.get('tmdb_id') or it.fulltitle or it.show or '').strip()
            if not tid or it.infoLabels.get('trailer'):
                continue
            cached = _trailer_cache.get(tid)
            if cached:
                it.infoLabels['trailer'] = cached

    # Pass 2: collect items that still need fetching
    seen = {}   # key -> Item  (key = tmdb_id if available, else title)
    for _, items in rows_snapshot:
        row_count = 0
        for it in items:
            if row_count >= per_row:
                break
            tid = str(it.infoLabels.get('tmdb_id') or it.fulltitle or it.show or '').strip()
            if not tid:
                continue
            if tid in _trailer_cache:
                row_count += 1
                continue
            if not it.infoLabels.get('trailer') and tid not in seen:
                seen[tid] = it
            row_count += 1
            if len(seen) >= max_total:
                break
        if len(seen) >= max_total:
            break

    if not seen:
        return

    logger.info('[NetflixHome trailers] fetching %d new ids (daemon threads)' % len(seen))
    results = {}   # tmdb_id -> url str
    lock    = threading.Lock()

    def _one(tid):
        try:
            # Bail out immediately if Kodi is shutting down — no need to
            # fetch trailers when the window is being closed.
            if _shutdown_event.is_set():
                return
            it_obj  = seen[tid]
            title   = it_obj.fulltitle or it_obj.show or it_obj.contentSerieName or ''
            year    = str(it_obj.infoLabels.get('year') or '')
            item_tmdb_id = str(it_obj.infoLabels.get('tmdb_id') or '').strip()
            item_ctype   = 'tv' if getattr(it_obj, 'contentType', '') == 'tvshow' else 'movie'

            def _make_url(video_id):
                return ('plugin://plugin.video.youtube/play/?video_id=%s' % video_id)

            # YouTube search primary
            vid = _youtube_search_trailer(title, year)
            # TMDB fallback: if YouTube finds nothing (all restricted or no results)
            if not vid and item_tmdb_id:
                vid = _tmdb_get_trailer(item_tmdb_id, item_ctype)
            with lock:
                results[tid] = _make_url(vid) if vid else False
        except Exception as exc:
            logger.error('[NetflixHome trailers] %s: %s' % (tid, str(exc)[:60]))

    # Use daemon threads so they don't block addon shutdown (prevents the
    # "script didn't stop in 5 seconds" kill that was crashing Kodi).
    import time as _time
    threads = [threading.Thread(target=_one, args=(tid,), daemon=True)
               for tid in list(seen.keys())]
    # Throttle: start 2 at a time to avoid flooding YouTube
    _abort_monitor = xbmc.Monitor()
    active = []
    pending = list(threads)
    deadline = _time.time() + 30
    while (pending or active) and _time.time() < deadline:
        # Exit immediately if Kodi is shutting down — prevents this loop from
        # blocking the CPythonInvoker past Kodi's 5-second kill timeout.
        if _abort_monitor.abortRequested() or _shutdown_event.is_set():
            return
        # Refill active pool up to 2
        while pending and len(active) < 2:
            t = pending.pop(0)
            t.start()
            active.append(t)
        active = [t for t in active if t.is_alive()]
        if active:
            # Use Event.wait() instead of xbmc.sleep() so we wake IMMEDIATELY when
            # _shutdown_event.set() is called (e.g. from onAbortRequested), rather
            # than blocking the full 150 ms in a Kodi API call that may no longer be
            # safe after Kodi's C++ objects start tearing down.
            _shutdown_event.wait(timeout=0.15)
    # Wait briefly for any still-running threads (up to remaining deadline)
    remaining = max(0.1, deadline - _time.time())
    for t in threads:
        if t.is_alive():
            t.join(timeout=min(remaining, 1.0))

    # Store results in module cache and apply to items
    for tid, val in results.items():
        _trailer_cache[tid] = val

    found = sum(1 for v in results.values() if v)
    logger.info('[NetflixHome trailers] done: %d/%d got trailer (cache size: %d)'
                 % (found, len(seen), len(_trailer_cache)))

    for _, items in rows_snapshot:
        for it in items:
            tid = str(it.infoLabels.get('tmdb_id') or it.fulltitle or it.show or '').strip()
            if tid and not it.infoLabels.get('trailer'):
                val = _trailer_cache.get(tid)
                if val:
                    it.infoLabels['trailer'] = val


def _fetch_videos_for_rows(_ignored):
    """Deprecated stub — replaced by _fetch_trailers_small."""
    pass


def _row_content_type(label):
    """
    Determine the content type of a row from its label.
    Returns 'peliculas', 'series', or 'anime'.
    Returns None for ambiguous rows (e.g. 'In evidenza', 'Azione' without suffix).
    """
    l = label.lower()
    if 'anime' in l:
        return 'anime'
    if 'serie' in l or ' tv' in l or 'show' in l:
        return 'series'
    if 'film' in l or 'movie' in l or 'pellicol' in l:
        return 'peliculas'
    return None


def _fetch_enrich_items(ctype):
    """
    Fetch all items of the given content type from _ENRICH_SOURCE_MAP.
    Results are cached per-type for _CACHE_TTL seconds.
    Returns a raw list of Items; dedup is NOT done here — it is per-row in the caller.
    """
    from time import time
    global _enrich_cache

    now = time()
    cached = _enrich_cache.get(ctype)
    if cached and (now - cached['ts']) < _CACHE_TTL:
        return cached['items']

    sources = _ENRICH_SOURCE_MAP.get(ctype, [])
    if not sources:
        return []

    import importlib
    all_items = []
    lock = threading.Lock()

    def _fetch_one(channel_name, categoria):
        try:
            mod = importlib.import_module('channels.%s' % channel_name)
            if not hasattr(mod, 'newest'):
                return
            items = mod.newest(categoria) or []
            valid = []
            for it in items[:40]:
                act = getattr(it, 'action', '') or ''
                if act not in _VALID_ACTIONS:
                    continue
                if _extract_item_title(it):
                    valid.append(it)
            if valid:
                with lock:
                    all_items.extend(valid)
            logger.info('[NetflixHome enrich] %s/%s: %d items fetched'
                         % (channel_name, categoria, len(valid)))
        except Exception as exc:
            logger.error('[NetflixHome enrich] %s/%s failed: %s'
                         % (channel_name, categoria, str(exc)[:120]))

    threads = []
    for ch, cat in sources:
        t = threading.Thread(target=_fetch_one, args=(ch, cat))
        t.daemon = True
        threads.append(t)
        t.start()
    _mon_enr = xbmc.Monitor()
    for t in threads:
        if _mon_enr.abortRequested() or _shutdown_event.is_set():
            break
        t.join(timeout=_EXTRA_TIMEOUT)

    if all_items:
        try:
            from core import tmdb as _tmdb
            _tmdb.set_infoLabels_itemlist(all_items, seekTmdb=True, forced=True)
        except Exception as exc:
            logger.error('[NetflixHome enrich] tmdb: %s' % str(exc))
    _enrich_cache[ctype] = {'items': all_items, 'ts': now}
    logger.info('[NetflixHome enrich] %s pool ready: %d raw items' % (ctype, len(all_items)))
    return all_items


def _fetch_rows():
    from time import time
    global _cache
    if _cache['data'] is not None and (time() - _cache['ts']) < _CACHE_TTL:
        logger.info('[NetflixHome] cache hit, %d rows' % len(_cache['data']))
        return _cache['data']

    rows = []
    try:
        import channels.streamingcommunity as sc
        host = sc.host
        logger.info('[NetflixHome] host=%s' % host)

        # Fetch ALL sliders from main pages (different suffixes avoid dedup collision).
        pages = [
            (host + '/it',          ''),
            (host + '/it/movies',   ' \u2014 Film'),
            (host + '/it/tv-shows', ' \u2014 Serie TV'),
        ]
        seen_sliders = set()   # deduplicate by display_name (case-insensitive)
        homepage_data = None   # saved to extract genres list afterwards

        for page_url, page_suffix in pages:
            if len(rows) >= SC_MAX_ROWS:
                break
            try:
                data = _get_data(page_url)
                if not data or not isinstance(data, dict):
                    logger.error('[NetflixHome] _get_data empty for %s' % page_url)
                    continue
                if not homepage_data:
                    homepage_data = data
                props   = data.get('props', {})
                sliders = props.get('sliders', [])
                logger.error('[NetflixHome] %s => %d sliders' % (page_url, len(sliders)))

                for slider in sliders:
                    if len(rows) >= SC_MAX_ROWS:
                        break
                    slider_name = (
                        slider.get('name') or slider.get('label') or
                        slider.get('title') or 'Senza nome'
                    ).strip()

                    raw_titles = slider.get('titles', [])
                    if isinstance(raw_titles, dict):
                        raw_titles = raw_titles.get('data', [])
                    if not raw_titles:
                        continue

                    # Deduplicate by full display_name (includes page suffix)
                    display_name = slider_name + page_suffix
                    key = display_name.lower()
                    if key in seen_sliders:
                        continue
                    seen_sliders.add(key)

                    items = []
                    for raw in raw_titles[:20]:
                        try:
                            it = _build_item(raw, host)
                            if it:
                                items.append(it)
                        except Exception as exc:
                            logger.error('[NetflixHome] _build_item: %s' % str(exc))
                    if not items:
                        continue

                    try:
                        from core import tmdb as _tmdb
                        _tmdb.set_infoLabels_itemlist(items, seekTmdb=True, forced=True)
                    except Exception as exc:
                        logger.error('[NetflixHome] tmdb: %s' % str(exc))

                    rows.append((display_name, items))
                    logger.error('[NetflixHome] row "%s": %d items' % (display_name, len(items)))

            except Exception as exc:
                logger.error('[NetflixHome] page error %s: %s' % (page_url, str(exc)))

        # Fetch genre rows concurrently (each genre archive is a separate HTTP request)
        if homepage_data and len(rows) < SC_MAX_ROWS:
            try:
                import threading as _threading
                genres_list = (homepage_data.get('props') or {}).get('genres') or []

                def _fetch_genre_row(genre, result_list, lock):
                    gname = (genre.get('name') or '').strip()
                    gid   = genre.get('id')
                    if not gname or not gid:
                        return
                    try:
                        gurl  = host + '/it/archive?genre[]=' + str(gid)
                        gdata = _get_data(gurl)
                        titles = (gdata.get('props') or {}).get('titles') or {}
                        if isinstance(titles, dict):
                            raw_titles = titles.get('data', [])
                        elif isinstance(titles, list):
                            raw_titles = titles
                        else:
                            raw_titles = []
                        if not raw_titles:
                            return
                        items = []
                        for raw in raw_titles[:20]:
                            try:
                                it = _build_item(raw, host)
                                if it:
                                    items.append(it)
                            except Exception:
                                pass
                        if items:
                            try:
                                from core import tmdb as _tmdb
                                _tmdb.set_infoLabels_itemlist(items, seekTmdb=True, forced=True)
                            except Exception:
                                pass
                            with lock:
                                result_list.append((gname, items))
                                logger.error('[NetflixHome] genre row "%s": %d items' % (gname, len(items)))
                    except Exception as exc:
                        logger.error('[NetflixHome] genre "%s" error: %s' % (gname, str(exc)))

                remaining    = SC_MAX_ROWS - len(rows)
                genre_results = []
                glock = _threading.Lock()
                threads = []
                for g in genres_list[:remaining]:
                    t = _threading.Thread(target=_fetch_genre_row, args=(g, genre_results, glock))
                    t.daemon = True
                    threads.append(t)
                    t.start()
                _mon_gr = xbmc.Monitor()
                for t in threads:
                    if _mon_gr.abortRequested() or _shutdown_event.is_set():
                        break
                    t.join(timeout=12)
                rows.extend(genre_results[:remaining])
            except Exception as exc:
                logger.error('[NetflixHome] genres block: %s' % str(exc))

    except Exception as exc:
        logger.error('[NetflixHome] import/init: %s' % str(exc))

    logger.error('[NetflixHome] total rows: %d' % len(rows))
    if rows:
        _cache['data'] = rows
        _cache['ts'] = time()
    return rows



# ── Up Next Overlay Window ──────────────────────────────────────────────────────────

class UpNextOverlayWindow(xbmcgui.WindowXMLDialog):
    """
    Netflix-style overlay shown ON TOP of the fullscreen video player.
    Non-blocking (uses show() not doModal()). The calling thread polls
    is_done() and calls update() each second.
    """

    BTN_PLAY   = 9901
    BTN_CANCEL = 9902
    LBL_TITLE  = 9903
    LBL_TIMER  = 9904
    PROG_BAR   = 9905

    def __init__(self, *args, **kwargs):
        self._ep_label = kwargs.pop('ep_label', '')
        self._result   = 'cancel'
        self._done     = False

    def onInit(self):
        try:
            self.getControl(self.LBL_TITLE).setLabel(self._ep_label)
        except Exception:
            pass
        try:
            self.getControl(self.LBL_TIMER).setLabel('')
        except Exception:
            pass
        try:
            self.getControl(self.PROG_BAR).setPercent(0)
        except Exception:
            pass

    def update(self, secs_remaining, pct_elapsed):
        """Update countdown label and progress bar. Called every second from caller thread."""
        if self._done:
            return
        if secs_remaining > 0:
            mins = secs_remaining // 60
            secs = secs_remaining % 60
            timer_txt = (u'Parte in [B]%d:%02d[/B]'
                         u'  —  [COLOR FFE50914]▶ Guarda subito[/COLOR] per iniziare ora'
                         % (mins, secs))
        else:
            timer_txt = u'[B]In partenza...[/B]'
        try:
            self.getControl(self.LBL_TIMER).setLabel(timer_txt)
            self.getControl(self.PROG_BAR).setPercent(min(100, pct_elapsed))
        except Exception:
            pass

    def is_done(self):
        return self._done

    def onClick(self, ctrl_id):
        if ctrl_id == self.BTN_PLAY:
            self._result = 'play'
        else:
            self._result = 'cancel'
        self._done = True
        try:
            self.close()
        except Exception:
            pass

    def onAction(self, action):
        aid = action.getId()
        if aid in (92, 10, xbmcgui.ACTION_STOP,
                   xbmcgui.ACTION_BACKSPACE, xbmcgui.ACTION_PREVIOUS_MENU):
            self._result = 'cancel'
            self._done   = True
            try:
                self.close()
            except Exception:
                pass


# ── Detail Window ─────────────────────────────────────────────────────────────

class DetailWindow(xbmcgui.WindowXMLDialog):
    """
    Full-screen detail card for a single title.
    Shows fanart / trailer (via videowindow), scrollable plot, PLAY and MY LIST buttons.
    Opened via doModal() from NetflixHomeWindow._open_detail (main GUI thread).
    """

    ACTION_EXIT = 10
    ACTION_BACK = 92

    def __init__(self, *args, **kwargs):
        self._item            = kwargs.pop('item', None)
        self._result          = None   # 'play' | 'list' | None after close
        self._player          = xbmc.Player()
        self._close_requested = False  # Signal background threads to bail out
        self._selected_season  = None  # int: season selected in EpisodePicker
        self._selected_episode = None  # int: episode selected in EpisodePicker

    def onInit(self):
        item = self._item
        if not item:
            return

        # ── Collect metadata ──────────────────────────────────────────────
        title      = item.fulltitle or item.show or item.contentSerieName or ''
        year       = str(item.year or item.infoLabels.get('year') or '')
        lang       = getattr(item, 'language', '') or ''
        rating     = str(item.infoLabels.get('rating') or '')
        genre      = str(item.infoLabels.get('genre') or '')
        director   = str(item.infoLabels.get('director') or '')
        cast_raw   = item.infoLabels.get('cast') or []
        runtime    = str(item.infoLabels.get('runtime') or '')
        tagline    = str(item.infoLabels.get('tagline') or '')
        country    = str(item.infoLabels.get('country') or '')
        studio     = str(item.infoLabels.get('studio') or '')
        seasons    = str(item.infoLabels.get('season') or '')
        trailer    = str(item.infoLabels.get('trailer') or '')
        plot       = (item.infoLabels.get('plot') or '').strip()
        # Fanart: use item.fanart directly (set immediately), then upgrade to
        # TMDB /original/ backdrop in background for maximum resolution.
        fanart = item.fanart or item.thumbnail or ''

        ctype_lbl = ('Film' if getattr(item, 'contentType', '') == 'movie'
                     else 'Serie TV' if getattr(item, 'contentType', '') == 'tvshow'
                     else '')
        cast_str = (', '.join(str(c) for c in cast_raw[:7])
                    if isinstance(cast_raw, list) else str(cast_raw))
        rating_str = ''
        if rating:
            try:
                rating_str = '\u2605 %.1f' % float(rating)
            except Exception:
                pass

        # ── Set background fanart (instant, then upgraded to HD) ───────────
        try:
            self.getControl(DW_BG_FANART).setImage(fanart)
        except Exception:
            pass
        tmdb_id_hd = str(item.infoLabels.get('tmdb_id') or '').strip()
        if tmdb_id_hd:
            ctype_hd = 'tv' if getattr(item, 'contentType', '') == 'tvshow' else 'movie'
            t_hd = threading.Thread(target=self._load_hd_fanart, args=(tmdb_id_hd, ctype_hd))
            t_hd.daemon = True
            t_hd.start()

        # ── Title ─────────────────────────────────────────────────────────
        try:
            self.getControl(DW_TITLE).setLabel('[B]' + title + '[/B]')
        except Exception:
            pass

        # ── Meta 1: year · type · lang · ★ rating (green) ───────────────
        # Rating is highlighted in green (Apple TV+ style) via BBCode
        rating_display = ('[COLOR FF22C55E][B]' + rating_str + '[/B][/COLOR]'
                         ) if rating_str else ''
        meta1 = '  \u2022  '.join(
            p for p in [year, ctype_lbl, lang, rating_display] if p)
        try:
            self.getControl(DW_META1).setLabel(meta1)
        except Exception:
            pass

        # ── Meta 2: genre · runtime · country ────────────────────────────
        runtime_str = ('%s min' % runtime) if runtime else ''
        meta2 = '  \u2022  '.join(p for p in [genre, runtime_str, country] if p)
        try:
            self.getControl(DW_META2).setLabel(meta2)
        except Exception:
            pass

        # ── Meta 3: director · cast ───────────────────────────────────────
        meta3_parts = []
        if director:
            meta3_parts.append('Regia: ' + director)
        if cast_str:
            meta3_parts.append('Cast: ' + cast_str)
        if studio:
            meta3_parts.append('Studio: ' + studio)
        try:
            self.getControl(DW_META3).setLabel('  |  '.join(meta3_parts))
        except Exception:
            pass

        # ── Tagline ───────────────────────────────────────────────────────
        try:
            if tagline:
                self.getControl(DW_TAGLINE).setLabel('[I]' + tagline + '[/I]')
        except Exception:
            pass

        # ── Plot textbox (scrollable) ─────────────────────────────────────
        # Build a richer text combining all info with the full plot at the bottom
        plot_lines = []
        if seasons:
            plot_lines.append('Stagioni: ' + seasons)
        if plot_lines:
            plot_lines.append('')
        plot_lines.append(plot if plot else 'Nessuna trama disponibile.')
        full_plot = '\n'.join(plot_lines)
        try:
            self.getControl(DW_PLOT).setText(full_plot)
        except Exception:
            try:
                self.getControl(DW_PLOT).setLabel(full_plot)
            except Exception:
                pass

        # ── Default focus on PLAY ─────────────────────────────────────────
        try:
            self.setFocusId(DW_BTN_PLAY)
        except Exception:
            pass

        # ── Play button label: "Continua a guardare" if there's a saved position ──
        try:
            cw_entry = watch_history.get(_cw_key(item))
            if cw_entry:
                t_saved = float(cw_entry.get('time_watched', 0))
                t_total = float(cw_entry.get('total_time', 0) or 1)
                pct     = int(t_saved / t_total * 100)
                mins    = int(t_saved // 60)
                secs    = int(t_saved % 60)
                btn_label = u'\u25b6  Continua a guardare  \u2013  %d:%02d  (%d%%)' % (mins, secs, pct)
                self.getControl(DW_BTN_PLAY).setLabel(btn_label)
        except Exception:
            pass

        # ── TV show: show current episode info + STAGIONI & EPISODI button ──
        ct = getattr(item, 'contentType', '') or ''
        xbmc.log('[DetailWindow] onInit ct=%r action=%r tmdb=%r title=%r' % (
            ct, getattr(item, 'action', ''), item.infoLabels.get('tmdb_id'), item.fulltitle), xbmc.LOGINFO)
        if ct in ('tvshow', 'episode'):
            try:
                self.setProperty('is_tvshow', '1')
                _tmdb_str = str(item.infoLabels.get('tmdb_id') or '').strip()
                if _tmdb_str:
                    _ep_key = 'tv_%s' % _tmdb_str
                else:
                    # Fallback: same slug logic as _cw_key for episode items
                    _slug   = re.sub(r'[^a-z0-9]', '',
                                     (getattr(item, 'show', '') or
                                      getattr(item, 'contentSerieName', '') or
                                      getattr(item, 'fulltitle', '') or '').lower())
                    _ep_key = ('tv_%s' % _slug) if _slug else None
                _ep_info  = watch_history.get_episode_info(_ep_key) if _ep_key else None
                if _ep_info:
                    # Full episode tracking data available
                    _s   = _ep_info['season']
                    _e   = _ep_info['episode']
                    _et  = _ep_info.get('episode_title', '')
                    _tw  = float(_ep_info.get('time_watched', 0))
                    _tt  = float(_ep_info.get('total_time', 0) or 1)
                    _pct = int(_tw / _tt * 100) if _tw > 0 else 0
                    _ep_code = u'S%02dE%02d' % (_s, _e)
                    _ep_lbl  = u'\u25b6  Continua  %s' % _ep_code
                    if _et:
                        _ep_lbl += u'  \u2013  ' + _et
                    if _pct:
                        _ep_lbl += u'  (%d%%)' % _pct
                    if _tw > 10:
                        _mins = int(_tw // 60)
                        _secs = int(_tw % 60)
                        try:
                            self.getControl(DW_BTN_PLAY).setLabel(
                                u'\u25b6  Continua %s  \u2013  %d:%02d  (%d%%)' % (
                                    _ep_code, _mins, _secs, _pct))
                        except Exception:
                            pass
                else:
                    # No episode tracking — check if any CW entry exists for this series
                    _ep_entry = watch_history.get(_ep_key) if _ep_key else None
                    if _ep_entry:
                        # Old CW entry exists but without season/episode fields
                        _ep_lbl = u'\u25b6  Continua'
                        _tw2 = float(_ep_entry.get('time_watched', 0))
                        _tt2 = float(_ep_entry.get('total_time', 1) or 1)
                        if _tw2 > 10:
                            _pct2  = int(_tw2 / _tt2 * 100)
                            _mins2 = int(_tw2 // 60)
                            _secs2 = int(_tw2 % 60)
                            try:
                                self.getControl(DW_BTN_PLAY).setLabel(
                                    u'\u25b6  Continua a guardare  \u2013  %d:%02d  (%d%%)' % (
                                        _mins2, _secs2, _pct2))
                            except Exception:
                                pass
                    else:
                        # Truly new series — no watch history at all
                        _ep_lbl = u'Nuova serie  \u2013  S01E01'
                        try:
                            self.getControl(DW_BTN_PLAY).setLabel(u'\u25b6  GUARDA  S01E01')
                        except Exception:
                            pass
                self.getControl(DW_EP_INFO).setLabel(_ep_lbl)
                # Visibility is driven by Window.Property(is_tvshow) in the XML,
                # already set above via setProperty('is_tvshow', '1')
            except Exception as _exc:
                logger.error('[DetailWindow] ep info: %s' % str(_exc))

        # ── Background media: fanart slideshow for CW items, trailer otherwise ──
        tmdb_id_tr = str(item.infoLabels.get('tmdb_id') or '').strip()
        ctype_tr   = 'tv' if getattr(item, 'contentType', '') == 'tvshow' else 'movie'
        is_cw_item = bool(watch_history.get(_cw_key(item)))

        # Show/hide the "Remove from CW" button via window property
        try:
            self.setProperty('show_remove_cw', '1' if is_cw_item else '')
        except Exception:
            pass

        if is_cw_item:
            # CW item: rotate TMDB backdrops every 5 s, no trailer
            t2 = threading.Thread(
                target=self._start_fanart_slideshow,
                args=(tmdb_id_tr, ctype_tr, fanart),
            )
        else:
            # Normal item: play trailer
            t2 = threading.Thread(
                target=self._fetch_and_start_trailer,
                args=(title, year, tmdb_id_tr, ctype_tr, trailer),
            )
        t2.daemon = True
        t2.start()

    def _start_fanart_slideshow(self, tmdb_id, ctype, initial_fanart=''):
        """
        For CW items: rotate TMDB backdrop images on DW_BG_FANART every 5 seconds.
        Fetches up to 6 backdrops from TMDB /images endpoint (no_language filter
        gives the widest selection). Falls back to initial_fanart if TMDB fails.
        Runs in a background thread; respects _close_requested.
        """
        try:
            backdrops = []
            if tmdb_id:
                try:
                    from core.tmdb import Tmdb as _Tmdb, host as _tmdb_host, api as _tmdb_api
                    url   = '%s/%s/%s/images?api_key=%s&include_image_language=null' % (
                            _tmdb_host, ctype, tmdb_id, _tmdb_api)
                    data  = _Tmdb.get_json(url)
                    blist = (data or {}).get('backdrops', [])
                    for b in blist[:6]:
                        fp = b.get('file_path') or ''
                        if fp:
                            backdrops.append('https://image.tmdb.org/t/p/original' + fp)
                except Exception as exc:
                    logger.error('[DetailWindow] fanart slideshow fetch: %s' % str(exc)[:80])

            # If TMDB gave nothing, keep the initial fanart (already set in onInit)
            if not backdrops:
                if initial_fanart:
                    backdrops = [initial_fanart]
                else:
                    return   # nothing to show

            # Rotate: show each image for 5 seconds, loop indefinitely
            idx = 0
            while not self._close_requested:
                img = backdrops[idx % len(backdrops)]
                try:
                    self.getControl(DW_BG_FANART).setImage(img)
                except Exception:
                    break
                # Sleep in 200 ms chunks so we can react to close quickly
                for _ in range(25):   # 25 * 200 ms = 5 s
                    if self._close_requested:
                        return
                    xbmc.sleep(200)
                idx += 1
        except Exception as exc:
            logger.error('[DetailWindow] fanart slideshow: %s' % str(exc)[:80])

    def _fetch_and_start_trailer(self, title, year, tmdb_id, ctype, fallback_url=''):
        """Trailer search: YouTube first (age-restriction filtered), then TMDB, then
        the pre-existing URL from the channel as last resort. Runs in background thread."""
        if self._close_requested:
            return
        try:
            def _make_url(video_id):
                return ('plugin://plugin.video.youtube/play/?video_id=%s' % video_id)

            # 1) YouTube search (filters age-restricted results)
            vid = _youtube_search_trailer(title, year)
            trailer_url = _make_url(vid) if vid else None

            # 2) TMDB official videos if YouTube found nothing
            if not trailer_url and tmdb_id:
                vid = _tmdb_get_trailer(tmdb_id, ctype)
                trailer_url = _make_url(vid) if vid else None

            # 3) Pre-existing URL from channel as last resort
            if not trailer_url and fallback_url:
                trailer_url = fallback_url

            if trailer_url and not self._close_requested:
                self._start_trailer(trailer_url)
        except Exception as exc:
            logger.error('[DetailWindow] on-demand trailer: %s' % str(exc)[:100])

    def _load_hd_fanart(self, tmdb_id, ctype):
        """Upgrade background to TMDB /original/ backdrop for maximum resolution.
        Also updates DW_META1 with number of seasons for TV shows."""
        try:
            from core.tmdb import Tmdb as _Tmdb, host as _tmdb_host, api as _tmdb_api
            url  = '%s/%s/%s?api_key=%s&append_to_response=credits' % (
                    _tmdb_host, ctype, tmdb_id, _tmdb_api)
            data = _Tmdb.get_json(url)
            path = (data or {}).get('backdrop_path') or ''
            if path:
                hq_url = 'https://image.tmdb.org/t/p/original' + path
                self.getControl(DW_BG_FANART).setImage(hq_url)
            # For TV shows, prepend seasons count to META1
            if ctype == 'tv' and data:
                n_seasons = int((data or {}).get('number_of_seasons') or 0)
                if n_seasons > 0:
                    s_lbl = u'%d stagion%s' % (n_seasons, 'e' if n_seasons == 1 else 'i')
                    try:
                        current = self.getControl(DW_META1).getLabel()
                        new_meta1 = (s_lbl + u'  \u2022  ' + current) if current else s_lbl
                        self.getControl(DW_META1).setLabel(new_meta1)
                    except Exception:
                        pass
            # Populate cast panel from credits
            cast_list = (data or {}).get('credits', {}).get('cast', [])[:14]
            if cast_list:
                self._populate_cast_panel(cast_list)
        except Exception:
            pass

    def _populate_cast_panel(self, cast_list):
        """Populate the horizontal cast panel (id=220) with actor cards from TMDB credits."""
        try:
            list_items = []
            for actor in cast_list:
                name = actor.get('name', '')
                profile = actor.get('profile_path', '')
                thumb = ('https://image.tmdb.org/t/p/w185' + profile) if profile else ''
                li = xbmcgui.ListItem(label=name, offscreen=True)
                li.setProperty('actor_thumb', thumb)
                list_items.append(li)
            if list_items and not self._close_requested:
                self.getControl(DW_CAST_PANEL).addItems(list_items)
                self.getControl(DW_CAST_PANEL).setVisible(True)
                self.getControl(DW_CAST_HDR).setVisible(True)
        except Exception as exc:
            logger.error('[DetailWindow] cast panel: %s' % str(exc)[:80])

    def _start_trailer(self, trailer_url):
        """Delay slightly then fire PlayMedia so the window is fully rendered first."""
        # Check close flag before the initial delay: if user already pressed back, skip entirely
        if self._close_requested:
            return
        # Slice the 900 ms wait into 100 ms chunks so we can bail out early
        for _ in range(9):
            xbmc.sleep(100)
            if self._close_requested:
                return
        try:
            # Configure YouTube plugin subtitles / quality (persistent but harmless settings)
            try:
                yt = xbmcaddon.Addon('plugin.video.youtube')
                if yt.getSetting('kodion.subtitle.languages.num') != '2':
                    yt.setSetting('kodion.subtitle.languages.num', '2')
                if yt.getSetting('kodion.subtitle.download') != 'true':
                    yt.setSetting('kodion.subtitle.download', 'true')
                try:
                    if yt.getSetting('kodion.video.quality.isa') == 'true':
                        if int(yt.getSetting('kodion.mpd.quality.selection') or '0') < 4:
                            yt.setSetting('kodion.mpd.quality.selection', '4')
                    else:
                        if int(yt.getSetting('kodion.video.quality') or '0') < 4:
                            yt.setSetting('kodion.video.quality', '4')
                except Exception:
                    pass
            except Exception:
                pass

            # Final check before issuing PlayMedia — CRITICAL: prevents PlayMedia
            # from firing on a window that is already closing/closed (which would
            # cause OutputPicture timeouts as DXVA tries to write to a destroyed surface)
            if self._close_requested:
                return

            xbmc.executebuiltin('PlayMedia(%s)' % trailer_url)
            # Wait up to 8 s for the YouTube plugin to start playing
            for _ in range(80):
                if self._close_requested:
                    # PlayMedia was issued but window is closing: cancel it immediately
                    xbmc.executebuiltin('PlayerControl(Stop)')
                    return
                xbmc.sleep(100)
                if self._player.isPlaying():
                    break
            if self._player.isPlaying() and not self._close_requested:
                # Hide fanart so the videowindow (behind it) becomes visible
                try:
                    self.getControl(DW_BG_FANART).setVisible(False)
                except Exception:
                    pass
                # Cinema mode: fade out overlay after 3 s so trailer is (nearly) fullscreen
                threading.Thread(target=self._enter_cinema_mode, daemon=True).start()
                # Wait for YouTube plugin to register audio/subtitle tracks
                for _ in range(50):
                    if self._close_requested:
                        return
                    xbmc.sleep(100)
                if not self._close_requested:
                    self._maybe_set_subtitles()
        except Exception as exc:
            logger.error('[DetailWindow] trailer start: %s' % str(exc))

    def _maybe_set_subtitles(self):
        """Enable Italian subtitles only if the trailer audio is NOT already Italian."""
        try:
            # Check current audio language via Kodi info label
            audio_lang = xbmc.getInfoLabel('VideoPlayer.AudioLanguage').lower()
            # Common Italian identifiers: 'italian', 'italiano', 'ita', 'it'
            is_italian_audio = (
                'ital' in audio_lang
                or audio_lang in ('it', 'ita', 'ita_it')
                or audio_lang.startswith('it-')
            )
            if is_italian_audio:
                # Audio is already Italian — no subtitles needed
                self._player.showSubtitles(False)
                return
            # Audio is foreign — look for Italian subtitle track
            self._set_italian_subtitles()
        except Exception:
            pass

    def _set_italian_subtitles(self):
        """Enable Italian subtitle track; fall back to first available if Italian not found."""
        try:
            streams = self._player.getAvailableSubtitleStreams()
            if streams:
                it_index = None
                for i, s in enumerate(streams):
                    sl = s.lower()
                    if 'ital' in sl or sl in ('it', 'ita') or sl.startswith('it-') or sl.startswith('it_'):
                        it_index = i
                        break
                if it_index is not None:
                    self._player.setSubtitleStream(it_index)
                else:
                    # No Italian track → activate first available as fallback
                    self._player.setSubtitleStream(0)
                self._player.showSubtitles(True)
            else:
                # Plugin did not expose streams via API – force display anyway
                self._player.showSubtitles(True)
        except Exception:
            pass

    def _show_audio_sub_dialog(self):
        """
        Show a two-step dialog to let the user pick preferred audio language and
        subtitle language for this content.  The choices are stored in addon settings
        keyed by TMDB ID (or normalised title) so they persist across sessions.
        For TV series the same preference is applied to every episode automatically
        in _wait_and_restore() when the player announces a new audio stream.
        """
        item = self._item
        if not item:
            return
        try:
            addon = xbmcaddon.Addon()
            tmdb_id = str(item.infoLabels.get('tmdb_id') or '').strip()
            ct = getattr(item, 'contentType', '') or ''
            key = tmdb_id or re.sub(r'[^a-z0-9]', '',
                                    (item.fulltitle or item.show or '').lower())
            if not key:
                return

            pref_key_audio = 'audiolang_%s' % key
            pref_key_sub   = 'sublang_%s'   % key

            # ── Audio language ──
            audio_options = [
                u'Italiano',
                u'Inglese',
                u'Originale (non cambiare)',
            ]
            cur_audio = addon.getSetting(pref_key_audio) or ''
            cur_audio_idx = 0
            for _i, _o in enumerate(audio_options):
                if _o == cur_audio:
                    cur_audio_idx = _i
                    break
            audio_idx = xbmcgui.Dialog().select(
                u'Lingua audio preferita', audio_options,
                preselect=cur_audio_idx)
            if audio_idx < 0:
                return   # user cancelled
            addon.setSetting(pref_key_audio, audio_options[audio_idx])

            # ── Subtitle language ──
            sub_options = [
                u'Nessun sottotitolo',
                u'Italiano',
                u'Inglese',
                u'Come audio (stessa lingua)',
            ]
            cur_sub = addon.getSetting(pref_key_sub) or ''
            cur_sub_idx = 0
            for _i, _o in enumerate(sub_options):
                if _o == cur_sub:
                    cur_sub_idx = _i
                    break
            sub_idx = xbmcgui.Dialog().select(
                u'Sottotitoli preferiti', sub_options,
                preselect=cur_sub_idx)
            if sub_idx < 0:
                return   # user cancelled
            addon.setSetting(pref_key_sub, sub_options[sub_idx])

            xbmcgui.Dialog().notification(
                u'PrippiStream',
                u'Preferenze audio/sub salvate',
                xbmcgui.NOTIFICATION_INFO, 2500)
        except Exception as exc:
            logger.error('[DetailWindow] _show_audio_sub_dialog: %s' % str(exc))

    def _remove_from_cw(self):
        """Remove the current item from Continue Watching and close the detail card."""
        item = self._item
        if not item:
            return
        try:
            key = _cw_key(item)
            entry = watch_history.get(key)
            if entry:
                # Use the actual played URL (vixcloud CDN) saved during playback.
                # Falling back to item.url or item_url won't work because Kodi
                # stores the vixcloud ID, not the SC episode_id.
                played_url = entry.get('played_url', '')
                _clear_kodi_resume(played_url)
                watch_history.remove(key)
                xbmcgui.Dialog().notification(
                    u'PrippiStream',
                    u'Rimosso da "Continua a guardare"',
                    xbmcgui.NOTIFICATION_INFO, 2000)
            self._initiate_close(result='removed_cw')
        except Exception as exc:
            logger.error('[DetailWindow] _remove_from_cw: %s' % str(exc))

    def _open_episode_picker(self):
        """Open the EpisodePickerDialog (TMDB-based) and update labels on selection."""
        item = self._item
        if not item:
            return
        try:
            tmdb_id = str(item.infoLabels.get('tmdb_id') or '').strip()
            if not tmdb_id:
                xbmcgui.Dialog().notification(
                    u'PrippiStream',
                    u'Seleziona stagione/episodio con il tasto GUARDA',
                    xbmcgui.NOTIFICATION_INFO, 3000)
                return
            # Build show key — same logic as onInit
            show_key = 'tv_%s' % tmdb_id
            ep_info  = watch_history.get_episode_info(show_key) or {}
            # If no episode info, check if a plain CW entry exists for current ep
            if not ep_info:
                _cw_plain = watch_history.get(show_key) or {}
                cw_season = int(_cw_plain.get('season', 1) or 1)
                cw_ep     = int(_cw_plain.get('episode', 1) or 1)
            else:
                cw_season = int(ep_info.get('season', 1) or 1)
                cw_ep     = int(ep_info.get('episode', 1) or 1)
            picker = EpisodePickerDialog(
                'EpisodePicker.xml', config.get_runtime_path(),
                tmdb_id=tmdb_id,
                show_key=show_key,
                cw_season=cw_season,
                cw_ep=cw_ep,
            )
            picker.doModal()
            if picker._selected:
                sel_s, sel_e, sel_title = picker._selected
                self._selected_season  = sel_s
                self._selected_episode = sel_e
                # Update EP_INFO label
                _ep_code = u'S%02dE%02d' % (sel_s, sel_e)
                _ep_lbl  = u'\u25b6  %s' % _ep_code
                if sel_title:
                    _ep_lbl += u'  \u2013  ' + sel_title
                try:
                    self.getControl(DW_EP_INFO).setLabel(_ep_lbl)
                except Exception:
                    pass
                # Update GUARDA button to show the selected episode
                try:
                    self.getControl(DW_BTN_PLAY).setLabel(
                        u'\u25b6  GUARDA  %s' % _ep_code)
                except Exception:
                    pass
            del picker
        except Exception as exc:
            logger.error('[DetailWindow] _open_episode_picker: %s' % str(exc))

    def _initiate_close(self, result=None):
        """
        The ONLY way to close DetailWindow. Safe to call from any thread or GUI callback.

        Sets _close_requested immediately (so _start_trailer bails out), then spawns
        a single daemon thread that waits for the player to fully stop BEFORE calling
        self.close(). This prevents the OutputPicture-timeout crash that occurs when
        the window's videowindow D3D11 surface is destroyed while DXVA is still
        pushing frames into it.
        """
        if self._close_requested:
            return   # Already closing — ignore duplicate calls
        if result is not None:
            self._result = result
        self._close_requested = True
        threading.Thread(target=self._wait_stop_then_close, daemon=True).start()

    def _wait_stop_then_close(self):
        """
        Background daemon thread:
          1. Cancel any pending/active playback
          2. Poll until player is confirmed stopped (max 3 s)
          3. Wait for DXVA render buffers to flush (400 ms)
          4. Restore fanart overlay
          5. Close the window
        """
        try:
            # Step 1: cancel playback via both APIs to cover every state:
            # - PlayerControl(Stop) cancels a queued/starting PlayMedia
            # - player.stop() signals an already-playing stream to stop
            xbmc.executebuiltin('PlayerControl(Stop)')
            xbmc.sleep(150)   # brief yield so the stop message is processed
            if self._player.isPlaying():
                self._player.stop()

            # Step 2: wait until isPlaying() is False (max 3 s)
            for _ in range(30):
                xbmc.sleep(100)
                if not self._player.isPlaying():
                    break

            # Step 3: DXVA buffer flush.
            # isPlaying()==False means CVideoPlayer acknowledged the stop, but the
            # CVideoPlayerVideo decoder thread may still hold GPU buffer locks for
            # one more OutputPicture cycle. Without this wait the window teardown
            # races with the decoder → OutputPicture timeout → crash.
            xbmc.sleep(400)

            # Step 4: restore fanart overlay so there's no black flash
            try:
                self.getControl(DW_BG_FANART).setVisible(True)
            except Exception:
                pass
            # Restore cinema-mode group so window fade-out looks correct
            try:
                self.getControl(DW_OVERLAY_GROUP).setVisible(True)
            except Exception:
                pass

        except Exception:
            pass

        # Step 5: close the window (safe to call from any thread in Kodi)
        try:
            self.close()
        except Exception:
            pass

    def _enter_cinema_mode(self):
        """Sleep 3 s then fade out the overlay group so the trailer plays fullscreen.
        If the window is closing or trailer stopped, bail out."""
        for _ in range(30):  # 3 seconds in 100 ms chunks
            if self._close_requested:
                return
            xbmc.sleep(100)
        if self._close_requested or not self._player.isPlaying():
            return
        try:
            self.getControl(DW_OVERLAY_GROUP).setVisible(False)
        except Exception:
            pass

    def onAction(self, action):
        aid = action.getId()
        if aid in (self.ACTION_EXIT, self.ACTION_BACK):
            self._initiate_close()
        else:
            # Any other key restores the overlay (cinema mode → normal)
            try:
                self.getControl(DW_OVERLAY_GROUP).setVisible(True)
            except Exception:
                pass

    def onClick(self, control_id):
        # Restore overlay first (handles click after cinema mode hides it)
        try:
            self.getControl(DW_OVERLAY_GROUP).setVisible(True)
        except Exception:
            pass
        if control_id == DW_BTN_CLOSE:
            self._initiate_close()
        elif control_id == DW_BTN_PLAY:
            item = self._item
            ct      = getattr(item, 'contentType', '') or ''
            tmdb_id = str(item.infoLabels.get('tmdb_id') or '').strip() if item else ''
            # For tvshow with TMDB and no pre-selected episode: open picker first
            if ct == 'tvshow' and tmdb_id and self._selected_season is None:
                self._open_episode_picker()
                if self._selected_season is not None:
                    # Episode chosen — play it
                    self._initiate_close(result='play')
                # else: picker was cancelled, stay in DetailWindow
            else:
                self._initiate_close(result='play')
        elif control_id == DW_BTN_AUDIO_SUB:
            self._show_audio_sub_dialog()
        elif control_id == DW_BTN_REMOVE_CW:
            self._remove_from_cw()
        elif control_id == DW_BTN_EP_SEL:
            self._open_episode_picker()


# ─────────────────────────────────────────────────────────────────────────────
# EpisodePickerDialog — TMDB-based season/episode selector
# ─────────────────────────────────────────────────────────────────────────────

class EpisodePickerDialog(xbmcgui.WindowXMLDialog):
    """Full-screen episode picker with season tabs (id=310) and episode list (id=311).

    Opened via doModal() from DetailWindow._open_episode_picker.
    After doModal() returns, check _selected: None or (season, episode, title) tuple.
    """

    ACTION_EXIT = 10
    ACTION_BACK = 92

    def __init__(self, *args, **kwargs):
        self._tmdb_id   = kwargs.pop('tmdb_id', '')
        self._show_key  = kwargs.pop('show_key', '')
        self._cw_season = int(kwargs.pop('cw_season', 1) or 1)
        self._cw_ep     = int(kwargs.pop('cw_ep', 1) or 1)
        self._seasons   = []      # list of season dicts from TMDB
        self._cur_season_num = self._cw_season
        self._selected  = None    # (season, episode, title) on confirmation

    def onInit(self):
        t = threading.Thread(target=self._load_seasons)
        t.daemon = True
        t.start()

    def _load_seasons(self):
        try:
            from core.tmdb import Tmdb as _Tmdb, host as _tmdb_host, api as _tmdb_api
            url  = '%s/tv/%s?api_key=%s' % (_tmdb_host, self._tmdb_id, _tmdb_api)
            data = _Tmdb.get_json(url) or {}
            raw  = data.get('seasons', [])
            # Filter out specials (season_number == 0)
            self._seasons = [s for s in raw if s.get('season_number', 0) > 0]
            if not self._seasons:
                return
            # Build season tab list items
            items = []
            sel_idx = 0
            for i, s in enumerate(self._seasons):
                n    = s.get('season_number', i + 1)
                name = s.get('name') or (u'Stagione %d' % n)
                li   = xbmcgui.ListItem(label=name)
                li.setProperty('season_number', str(n))
                items.append(li)
                if n == self._cw_season:
                    sel_idx = i
            try:
                ctrl = self.getControl(EP_SEASON_LIST)
                ctrl.addItems(items)
                ctrl.selectItem(sel_idx)
            except Exception as exc:
                logger.error('[EpisodePicker] season tabs: %s' % str(exc))
            # Load episodes for the current season
            self._cur_season_num = self._seasons[sel_idx].get('season_number',
                                                               self._cw_season)
            self._load_episodes(self._cur_season_num)
        except Exception as exc:
            logger.error('[EpisodePicker] _load_seasons: %s' % str(exc))

    def _load_episodes(self, season_num):
        try:
            from core.tmdb import Tmdb as _Tmdb, host as _tmdb_host, api as _tmdb_api
            url  = '%s/tv/%s/season/%d?api_key=%s' % (
                    _tmdb_host, self._tmdb_id, season_num, _tmdb_api)
            data = _Tmdb.get_json(url) or {}
            episodes = data.get('episodes', [])
            watched  = set(
                tuple(w) for w in watch_history.get_watched_episodes(self._show_key)
                if len(w) == 2
            )
            items    = []
            sel_pos  = 0
            for ep in episodes:
                ep_num   = ep.get('episode_number', 0)
                ep_title = ep.get('name') or (u'Episodio %d' % ep_num)
                ep_thumb = ep.get('still_path', '')
                overview = (ep.get('overview') or '')[:200]
                runtime  = ep.get('runtime', 0)
                is_watched = (season_num, ep_num) in watched
                is_current = (season_num == self._cw_season and ep_num == self._cw_ep)
                ep_code    = u'S%02dE%02d' % (season_num, ep_num)
                if is_current:
                    label = u'[B]\u25b6  %s  \u2013  %s[/B]' % (ep_code, ep_title)
                    sel_pos = len(items)
                elif is_watched:
                    label = (u'[COLOR FF22C55E]\u2713[/COLOR] '
                             u'[COLOR FF888888]%s  \u2013  %s[/COLOR]' % (ep_code, ep_title))
                else:
                    label = u'%s  \u2013  %s' % (ep_code, ep_title)
                li = xbmcgui.ListItem(label=label, offscreen=True)
                if ep_thumb:
                    li.setArt({'thumb': 'https://image.tmdb.org/t/p/w300' + ep_thumb})
                li.setProperty('ep_num',      str(ep_num))
                li.setProperty('season_num',  str(season_num))
                li.setProperty('ep_title',    ep_title)
                li.setProperty('overview',    overview)
                li.setProperty('runtime',     ('%d min' % runtime) if runtime else '')
                items.append(li)
            try:
                ctrl = self.getControl(EP_EP_LIST)
                ctrl.reset()
                ctrl.addItems(items)
                if items:
                    ctrl.selectItem(sel_pos)
            except Exception as exc:
                logger.error('[EpisodePicker] ep list populate: %s' % str(exc))
        except Exception as exc:
            logger.error('[EpisodePicker] _load_episodes: %s' % str(exc))

    def onAction(self, action):
        if action.getId() in (self.ACTION_EXIT, self.ACTION_BACK):
            self.close()

    def onClick(self, control_id):
        if control_id == EP_SEASON_LIST:
            try:
                ctrl = self.getControl(EP_SEASON_LIST)
                pos  = int(ctrl.getSelectedPosition() or 0)
                if 0 <= pos < len(self._seasons):
                    new_season = self._seasons[pos].get('season_number', 1)
                    if new_season != self._cur_season_num:
                        self._cur_season_num = new_season
                        t = threading.Thread(target=self._load_episodes,
                                             args=(new_season,))
                        t.daemon = True
                        t.start()
            except Exception as exc:
                logger.error('[EpisodePicker] onClick season: %s' % str(exc))
        elif control_id == EP_EP_LIST:
            try:
                ctrl = self.getControl(EP_EP_LIST)
                pos  = int(ctrl.getSelectedPosition() or 0)
                li   = ctrl.getListItem(pos)
                if li:
                    s     = int(li.getProperty('season_num') or 0)
                    e     = int(li.getProperty('ep_num')     or 0)
                    title = li.getProperty('ep_title') or ''
                    if s and e:
                        self._selected = (s, e, title)
                        self.close()
            except Exception as exc:
                logger.error('[EpisodePicker] onClick episode: %s' % str(exc))
        elif control_id == EP_BTN_CANCEL:
            self.close()


# ─────────────────────────────────────────────────────────────────────────────
# NetflixSearchWindow — unified search overlay
# ─────────────────────────────────────────────────────────────────────────────

def _open_search(parent_window=None):
    """Ask for query text then open the search overlay modal."""
    # ── DIAGNOSTIC ──────────────────────────────────────────────────────────
    _ns_cls = globals().get('NetflixSearchWindow')
    xbmc.log('[NetflixSearch] DEBUG globals NetflixSearchWindow=%r' % _ns_cls, xbmc.LOGINFO)
    xbmc.log('[NetflixSearch] DEBUG module=%r' % globals().get('__name__'), xbmc.LOGINFO)
    # ────────────────────────────────────────────────────────────────────────
    xbmc.log('[NetflixSearch] _open_search: calling dialog_input', xbmc.LOGINFO)
    query = platformtools.dialog_input('', heading='Cerca su PrippiStream...')
    xbmc.log('[NetflixSearch] _open_search: dialog_input returned: %r' % query, xbmc.LOGINFO)
    if not query:
        return
    query = query.strip()
    if not query:
        return
    try:
        # Pause BG UI refreshes while search window is open (parent may be None)
        if parent_window is not None:
            parent_window._bg_ui_pause.clear()
        xbmc.log('[NetflixSearch] _open_search: creating NetflixSearchWindow', xbmc.LOGINFO)
        win = NetflixSearchWindow(
            'NetflixSearch.xml',
            config.get_runtime_path(),
            query=query,
            parent_window=parent_window,
        )
        xbmc.log('[NetflixSearch] _open_search: calling doModal', xbmc.LOGINFO)
        win.doModal()
        xbmc.log('[NetflixSearch] _open_search: doModal returned', xbmc.LOGINFO)
        del win
    except Exception as exc:
        xbmc.log('[NetflixSearch] _open_search ERROR: %s' % str(exc), xbmc.LOGERROR)
    finally:
        if parent_window is not None:
            parent_window._bg_ui_pause.set()


xbmc.log('[NetflixSearch] MODULE: about to define NetflixSearchWindow', xbmc.LOGINFO)


class NetflixSearchWindow(xbmcgui.WindowXML):
    """Netflix-style search results overlay.

    Three horizontal rows:
      ROW 0 (id=160) — StreamingCommunity (all types)
      ROW 1 (id=161) — Film from other global-search channels
      ROW 2 (id=162) — Serie TV from other global-search channels

    Focus on a card → hero panel updates (poster, title, meta, plot).
    Click a card → opens DetailWindow (same flow as home).
    """

    ACTION_EXIT = 10
    ACTION_BACK = 92

    def __init__(self, xmlFilename, scriptPath, query='', parent_window=None, **kwargs):
        super().__init__(xmlFilename, scriptPath, **kwargs)
        self._query          = query
        self._parent_window  = parent_window   # NetflixHomeWindow — for CW/launch delegation
        self._items     = []             # flat list of all results
        self._hero_item = None           # item currently shown in hero
        self._search_done = threading.Event()
        self._lock      = threading.Lock()
        self._cancelled    = threading.Event()   # UI-close signal (stops search thread)
        self._pf_cancelled = threading.Event()   # prefetch-stop signal (set only on back/close)
        # Pre-fetch: background link testing for non-SC results
        self._prefetch_results = {}  # id(item) → (server_item, [label, url]) or None
        self._prefetch_events  = {}  # id(item) → threading.Event (set when prefetch done)

    # ── Kodi WindowXML lifecycle ──────────────────────────────────────────

    def onInit(self):
        try:
            # Show query text in the query button
            self.getControl(SEARCH_QUERY_BTN).setLabel(
                '[COLOR FF888888]' + chr(0x1F50D) + '  [/COLOR]' + self._query
            )
            # Hide no-results label; show loading indicator
            self.getControl(SEARCH_NORESULTS).setVisible(False)
            self.getControl(SEARCH_LOADING).setVisible(True)
            # Start search in background thread
            t = threading.Thread(target=self._run_search_thread, name='NS-search')
            t.daemon = True
            t.start()
        except Exception as exc:
            logger.error('[NetflixSearch] onInit error: %s' % str(exc))

    def onAction(self, action):
        aid = action.getId()
        if aid in (self.ACTION_EXIT, self.ACTION_BACK):
            self._cancelled.set()
            self._pf_cancelled.set()  # cancel all prefetch workers on back/close
            self.close()
            return
        # Update hero when navigating within the grid (LEFT/RIGHT/UP/DOWN/scroll wheel)
        if aid in (ACTION_LEFT, ACTION_RIGHT, ACTION_UP, ACTION_DOWN,
                   ACTION_WHEEL_UP, ACTION_WHEEL_DOWN):
            if self.getFocusId() == SEARCH_WL_SC:
                threading.Thread(target=self._deferred_hero_update,
                                 daemon=True).start()
        # Note: UP from top row → search bar and DOWN from top bar → grid
        # are handled by <onup>/<ondown> in the XML — no override needed here.

    def onClick(self, control_id):
        if control_id in (SEARCH_BTN_BACK, SEARCH_CLOSE):
            self._cancelled.set()
            self._pf_cancelled.set()  # cancel prefetch on close
            self.close()
            return
        if control_id == SEARCH_QUERY_BTN:
            self._cancelled.set()
            self._pf_cancelled.set()  # cancel prefetch on close
            self.close()
            _open_search()
            return
        if control_id == SEARCH_PLAY:
            if self._hero_item:
                self._launch_item(self._hero_item)
            return
        if control_id == SEARCH_INFO:
            if self._hero_item:
                self._open_detail(self._hero_item)
            return
        if control_id == SEARCH_WL_SC:   # panel grid id=160
            try:
                pos = int(self.getControl(SEARCH_WL_SC).getSelectedPosition() or 0)
                if 0 <= pos < len(self._items):
                    self._open_detail(self._items[pos])
            except Exception as exc:
                logger.error('[NetflixSearch] onClick grid: %s' % str(exc))

    def onFocus(self, control_id):
        if control_id == SEARCH_WL_SC:   # panel grid id=160
            try:
                pos = int(self.getControl(SEARCH_WL_SC).getSelectedPosition() or 0)
                if 0 <= pos < len(self._items):
                    self._update_hero(self._items[pos])
            except Exception:
                pass

    def _deferred_hero_update(self):
        """Called from onAction on a background thread to update the hero panel
        after a navigation key. Waits briefly so the panel can process the key
        and update getSelectedPosition() before we read it."""
        xbmc.sleep(80)
        try:
            pos = int(self.getControl(SEARCH_WL_SC).getSelectedPosition() or 0)
            with self._lock:
                items = list(self._items)
            if 0 <= pos < len(items):
                self._update_hero(items[pos])
        except Exception:
            pass

    # ── Hero panel ────────────────────────────────────────────────────────

    def _update_hero(self, item):
        """Populate the hero panel with data from *item*."""
        if item is None:
            return
        try:
            self._hero_item = item
            # Poster
            thumb = item.thumbnail or ''
            self.getControl(131).setImage(thumb)
            # Fanart (background) — use fanart if available, else poster
            fanart = getattr(item, 'fanart', '') or thumb
            if fanart:
                self.getControl(130).setImage(fanart)
            # Title
            title = item.fulltitle or item.title or ''
            self.getControl(132).setLabel(title)
            # Meta
            info = item.infoLabels or {}
            year  = str(info.get('year', '')) if info.get('year') else ''
            rating = ('%.1f' % float(info.get('rating', 0))) if info.get('rating') else ''
            media  = info.get('mediatype', '')
            parts  = [p for p in [year, rating, media.upper()] if p]
            self.getControl(133).setLabel('  ·  '.join(parts))
            # Plot
            plot = str(info.get('plot', ''))[:200]
            self.getControl(134).setLabel(plot)
        except Exception as exc:
            logger.error('[NetflixSearch] _update_hero: %s' % str(exc))

    # ── Detail / play ──────────────────────────────────────────────────────

    def _open_detail(self, item):
        """Open DetailWindow modal (same flow as NetflixHomeWindow)."""
        try:
            dw = DetailWindow(
                'DetailWindow.xml',
                config.get_runtime_path(),
                item=item,
            )
            dw.doModal()
            result = getattr(dw, '_result', None)
            del dw
            if result == 'play':
                self._launch_item(item)
        except Exception as exc:
            logger.error('[NetflixSearch] _open_detail: %s' % str(exc))

    def _launch_item(self, item):
        """Play item. For non-SC items waits for pre-tested working URL and plays directly."""
        try:
            xbmc.log('[NetflixSearch] _launch_item action=%r ch=%s' % (
                item.action, getattr(item, '_search_channel', '?')), xbmc.LOGINFO)

            # ── Prefetch path: non-SC items ─────────────────────────────────────
            if getattr(item, '_search_channel', 'sc') != 'sc':
                _item_id  = id(item)
                _evt      = self._prefetch_events.get(_item_id)
                _pw       = self._parent_window
                _results  = self._prefetch_results

                # If no prefetch was pre-started for this item, start one now on-demand.
                # sources = [item] itself; _prefetch_links also searches extra channels.
                if _evt is None and getattr(item, '_search_channel', 'sc') != 'sc':
                    _evt = threading.Event()
                    self._prefetch_events[_item_id] = _evt
                    threading.Thread(
                        target=self._prefetch_links,
                        args=(_item_id, [item], _evt),
                        daemon=True
                    ).start()

                if _evt is not None:
                    def _async_play(evt=_evt, pw=_pw, item=item,
                                    item_id=_item_id, results=_results):
                        # Wait up to 20 s for prefetch to complete
                        evt.wait(timeout=20)
                        result = results.get(item_id)
                        if result:
                            _si, _vu = result           # (server_item, [label, url])
                            _stream_url = _vu[1]
                            xbmc.log('[NetflixSearch] direct play: %.80s' % _stream_url,
                                     xbmc.LOGINFO)
                            try:
                                # Append HTTP headers to URL (Kodi pipe format: url|Header=val&...).
                                # Referer comes from the server item URL (the embed page),
                                # User-Agent from httptools defaults.
                                try:
                                    import urllib.parse as _urlparse
                                except ImportError:
                                    import urllib as _urlparse
                                from core import httptools as _ht
                                _play_url = _stream_url
                                if '|' not in _play_url:
                                    _hdrs = {
                                        'User-Agent': _ht.default_headers.get('User-Agent', ''),
                                        'Referer': getattr(_si, 'url', '') or '',
                                    }
                                    _play_url = _play_url + '|' + _urlparse.urlencode(_hdrs)

                                # ListItem path = raw URL (no headers) — same as platformtools.py
                                li = xbmcgui.ListItem(
                                    item.fulltitle or item.title or '',
                                    path=_stream_url)
                                li.setArt({'thumb': item.thumbnail or ''})
                                try:
                                    _il = dict(item.infoLabels or {})
                                    if _il:
                                        li.setInfo('video', {
                                            k: v for k, v in _il.items()
                                            if v is not None and
                                            isinstance(v, (str, int, float))
                                        })
                                except Exception:
                                    pass
                                li.setProperty('IsPlayable', 'true')
                                _pre_play_set_lang(item)
                                # Same pattern as platformtools.py: add to playlist with
                                # piped-headers URL, then play the playlist
                                _pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                                _pl.clear()
                                _pl.add(_play_url, li)
                                xbmc.Player().play(_pl, li)
                                if pw:
                                    t2 = threading.Thread(
                                        target=pw._wait_and_restore, args=(item,))
                                    t2.daemon = True
                                    t2.start()
                            except Exception as _ex:
                                logger.error('[NS-prefetch] direct play error: %s' % str(_ex))
                                if pw:
                                    pw._launch(item)
                                else:
                                    xbmc.executebuiltin(
                                        'RunPlugin(plugin://plugin.video.prippistream/?%s)'
                                        % item.tourl())
                        else:
                            xbmc.log('[NetflixSearch] prefetch: no working URL, fallback to channel',
                                     xbmc.LOGINFO)
                            # Prefetch found no working direct URL — fall back to the full
                            # channel flow (opens server-selection dialog / findvideos).
                            if pw:
                                pw._launch(item)
                            else:
                                xbmcgui.Dialog().notification(
                                    'PrippiStream',
                                    'Nessun link funzionante trovato per questo film.',
                                    xbmcgui.NOTIFICATION_WARNING, 4000)

                    t = threading.Thread(target=_async_play, name='NS-launch', daemon=True)
                    t.start()
                    return

            # ── Normal path (SC item or no prefetch event) ──────────────────────
            if self._parent_window is not None:
                self._parent_window._launch(item)
            else:
                xbmc.executebuiltin(
                    'RunPlugin(plugin://plugin.video.prippistream/?%s)' % item.tourl()
                )
        except Exception as exc:
            logger.error('[NetflixSearch] _launch_item: %s' % str(exc))

    # ── Wraplist helpers ────────────────────────────────────────────────────

    def _populate_grid(self, items):
        """Populate the panel grid (id=160) with *items*."""
        if self._cancelled.is_set():
            return
        list_items = []
        for it in items:
            li = xbmcgui.ListItem(label=it.fulltitle or it.title or '', offscreen=True)
            li.setArt({'thumb': it.thumbnail or ''})
            li.setProperty('thumbnail', it.thumbnail or '')
            list_items.append(li)
        try:
            self.getControl(SEARCH_WL_SC).addItems(list_items)
        except Exception as exc:
            logger.error('[NetflixSearch] _populate_grid: %s' % str(exc))

    # ── Search engine ───────────────────────────────────────────────────────

    def _run_search_thread(self):
        """Background search: SC first (shown immediately), then ALL other active channels in parallel.

        Flow:
          1. Search StreamingCommunity → show results immediately (fast feedback).
          2. Search all other channels with include_in_global_search=True in parallel (6 workers).
          3. Merge SC + others, sort by title relevance (exact match first, SC preferred),
             dedup by tmdb_id (first/highest-priority occurrence wins), reset panel,
             re-populate with final sorted list.

        Fixed bugs vs previous version:
          - get_channels(Item(mode='all')) — was Item() whose mode="" matched no channel → returned [].
          - _do_channel receives a string (channel name), not a dict — was calling .get() on it.
        """
        import re as _re

        query = self._query
        # Strip Kodi colour/format tags for title comparison
        query_clean = _re.sub(r'\[/?[A-Za-z][^\]]*\]', '', query).strip().lower()
        sc_items    = []
        sc_tmdb_ids = set()

        # ── Step 1: StreamingCommunity (fastest, shown first) ──────────
        try:
            self._set_progress('[B][COLOR FFE50914]RICERCA IN CORSO[/COLOR][/B]  —  StreamingCommunity...')
            from channels import streamingcommunity as _sc
            from core.item import Item as _Item
            sc_seed = _Item(channel='streamingcommunity', extra='search', text_color='FFFFFFFF')
            sc_items = list(_sc.search(sc_seed, query) or [])
            # Filter out SC results without a valid thumbnail (blank cards)
            sc_items = [it for it in sc_items if (it.thumbnail or '').strip()
                        and (it.thumbnail or '').strip().lower() not in ('none', 'false', 'null', 'n/a')]
            for it in sc_items:
                it._search_channel = 'sc'
                tmdb = (it.infoLabels or {}).get('tmdb_id') or (it.infoLabels or {}).get('tmdb')
                if tmdb:
                    sc_tmdb_ids.add(str(tmdb))
            logger.info('[NetflixSearch] SC returned %d results' % len(sc_items))
        except Exception as exc:
            logger.error('[NetflixSearch] SC search error: %s' % str(exc))
        if self._cancelled.is_set():
            return

        # Show SC results immediately in the grid (user sees something right away)
        with self._lock:
            self._items = list(sc_items)
        self._populate_grid(sc_items)
        if sc_items:
            self._update_hero(sc_items[0])
            self._set_progress('[B][COLOR FFE50914]RICERCA IN CORSO[/COLOR][/B]  —  SC: %d risultati · cercando altri canali...' % len(sc_items))
        else:
            self._set_progress('[B][COLOR FFE50914]RICERCA IN CORSO[/COLOR][/B]  —  Nessun risultato SC · cercando altri canali...')

        # ── Step 2: Other channels (parallel) ──────────────────────────
        # Read channels directly from JSON flags — avoids the double check (JSON flag + Kodi
        # settings) that previously caused get_channels() to always return [].
        try:
            from core import channeltools
            import channelselector as _channelselector
            _all_chs = _channelselector.filterchannels('all')
            channels = []
            for _ch in _all_chs:
                if _ch.channel == 'streamingcommunity':
                    continue  # already searched above
                _cp = channeltools.get_channel_parameters(_ch.channel)
                if _cp.get('active', False) and _cp.get('include_in_global_search', False):
                    channels.append(_ch.channel)
        except Exception as exc:
            logger.error('[NetflixSearch] channels detection error: %s' % str(exc))
            channels = []

        logger.info('[NetflixSearch] global search: %d other channels' % len(channels))
        total_ch = len(channels)
        done_ch  = [0]
        all_others = []

        # Article-aware title match: used in both _do_channel and Step 4a.
        # Rule: if the query starts with a leading article ("i", "il", "la", "the"...),
        # also accept results that match after stripping the article from BOTH sides.
        # This lets "Pirati della Silicon Valley" match "I pirati della silicon valley".
        # If the query has NO leading article, be strict so "Un Amore per sempre"
        # is NOT accepted when searching "Amore per sempre" (different film).
        _ART_RE = _re.compile(
            r'^(il |la |lo |i |le |gli |l |un |una |uno |the |a |an )'
        )
        _q_norm_raw   = _re.sub(r'[^a-z0-9 ]', '', query_clean).strip()
        _q_has_art    = bool(_ART_RE.match(_q_norm_raw))
        _q_stripped   = _ART_RE.sub('', _q_norm_raw, count=1).strip()

        def _title_match_query(r_norm):
            """Return True if r_norm is a title-match for the current query."""
            # Direct match (exact, or result is query + quality/year suffix)
            if (r_norm == _q_norm_raw
                    or r_norm.startswith(_q_norm_raw + ' ')
                    or _q_norm_raw.startswith(r_norm + ' ')):
                return True
            # Article-aware match: only when query has a leading article
            if _q_has_art:
                r_stripped = _ART_RE.sub('', r_norm, count=1).strip()
                if (r_stripped == _q_stripped
                        or r_stripped.startswith(_q_stripped + ' ')
                        or _q_stripped.startswith(r_stripped + ' ')):
                    return True
            return False

        # FIX: get_channels returns a list of strings (channel names), not dicts.
        def _do_channel(ch_name):
            if self._cancelled.is_set():
                return []
            try:
                ch_module = __import__('channels.' + ch_name, fromlist=[ch_name])
                if not hasattr(ch_module, 'search'):
                    return []
                from core.item import Item as _Item
                results = ch_module.search(_Item(channel=ch_name), query) or []
                filtered = []
                for r in results:
                    tmdb = (r.infoLabels or {}).get('tmdb_id') or (r.infoLabels or {}).get('tmdb')
                    if tmdb and str(tmdb) in sc_tmdb_ids:
                        continue   # SC has this exact title — SC version wins
                    # Title relevance filter: reject results that don't closely match
                    # the query. "Un Amore per sempre" must not appear when searching
                    # "Amore per sempre" — it's a different film.
                    # Use the raw title (no article stripping) for accurate comparison.
                    _r_raw = _re.sub(r'\[/?[A-Za-z][^\]]*\]', '',
                                     (r.fulltitle or r.title or '')).strip().lower()
                    _r_norm = _re.sub(r'[^a-z0-9 ]', '', _r_raw)
                    _r_norm = _re.sub(r'\s+', ' ', _r_norm).strip()
                    if _q_norm_raw and not _title_match_query(_r_norm):
                        logger.debug('[NetflixSearch] %s: skip "%s" (no match for "%s")' % (
                            ch_name, _r_norm[:40], _q_norm_raw))
                        continue
                    r._search_channel = ch_name
                    filtered.append(r)
                logger.debug('[NetflixSearch] %s: %d results' % (ch_name, len(filtered)))
                return filtered
            except Exception as exc:
                logger.debug('[NetflixSearch] channel %s error: %s' % (ch_name, str(exc)))
                return []

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=6) as pool:
            future_map = {pool.submit(_do_channel, ch): ch for ch in channels}
            for fut in as_completed(future_map):
                if self._cancelled.is_set():
                    break
                batch = fut.result() or []
                all_others.extend(batch)
                done_ch[0] += 1
                if total_ch > 0:
                    self._set_progress('[B][COLOR FFE50914]RICERCA IN CORSO[/COLOR][/B]  —  %d / %d canali...' % (done_ch[0], total_ch))

        if self._cancelled.is_set():
            return

        # ── Step 3: Sort by relevance + dedup by tmdb_id OR normalized title ──
        combined = list(sc_items) + all_others

        def _relevance_key(it):
            raw   = (it.fulltitle or it.title or '').lower()
            clean = _re.sub(r'\[/?[A-Za-z][^\]]*\]', '', raw).strip()
            is_sc    = (getattr(it, '_search_channel', '') == 'sc')
            is_cb01  = (getattr(it, '_search_channel', '') == 'cineblog01')
            exact    = (clean == query_clean)
            starts   = clean.startswith(query_clean)
            contains = (query_clean in clean)
            # Tuple: (priority_bucket 0-10, title for stable secondary sort)
            # Order: SC > CB01 > everything else
            if exact    and is_sc:   return (0,  clean)
            if exact    and is_cb01: return (1,  clean)
            if exact:                return (2,  clean)
            if starts   and is_sc:   return (3,  clean)
            if starts   and is_cb01: return (4,  clean)
            if starts:               return (5,  clean)
            if contains and is_sc:   return (6,  clean)
            if contains and is_cb01: return (7,  clean)
            if contains:             return (8,  clean)
            if is_sc:                return (9,  clean)
            if is_cb01:              return (10, clean)
            return                          (11, clean)

        combined.sort(key=_relevance_key)

        def _norm_title(it):
            """Normalized title for dedup fallback when tmdb_id is absent."""
            raw = (it.fulltitle or it.title or '')
            t = _re.sub(r'\[/?[A-Za-z][^\]]*\]', '', raw).strip().lower()
            t = _re.sub(r'[^a-z0-9 ]', '', t)
            t = _re.sub(r'\s+', ' ', t).strip()
            # strip leading articles (IT + EN)
            t = _re.sub(r'^(il |la |lo |i |le |gli |un |una |uno |the |a |an )', '', t)
            return t

        def _valid_thumb(it):
            """Return True only if thumbnail is a usable URL or local path."""
            t = (it.thumbnail or '').strip()
            return bool(t) and t.lower() not in ('none', 'false', 'null', 'n/a')

        # Build sources map: norm_title → all non-SC items (may be from multiple channels)
        # Used by prefetch to test ALL channels for a title simultaneously.
        _all_sources_by_title = {}
        for _si in all_others:
            _nt2 = _norm_title(_si)
            if _nt2:
                _all_sources_by_title.setdefault(_nt2, []).append(_si)

        # Dedup: first occurrence (highest priority) wins per tmdb_id;
        # ALSO dedup by normalized title regardless of whether tmdb_id is present.
        seen_tmdb  = set()
        seen_title = set()
        deduped    = []
        for it in combined:
            # Skip items with no valid thumbnail — they render as blank cards
            if not _valid_thumb(it):
                continue
            nt   = _norm_title(it)
            tmdb = (it.infoLabels or {}).get('tmdb_id') or (it.infoLabels or {}).get('tmdb')
            if tmdb:
                key = str(tmdb)
                if key in seen_tmdb:
                    continue
                # Even if tmdb_id is unique, skip if another item with same title already shown
                if nt and nt in seen_title:
                    continue
                seen_tmdb.add(key)
            else:
                if not nt:
                    continue   # skip items with no usable title
                if nt in seen_title:
                    continue
            if nt:
                seen_title.add(nt)
            deduped.append(it)

        # ── Step 4a: Start background link pre-testing for non-SC items ────────
        # Only prefetch the TOP 3 non-SC results that closely match the query —
        # avoids saturating the network with threads for false-positive results.
        _pf_started = 0
        for _it in deduped:
            if getattr(_it, '_search_channel', 'sc') == 'sc':
                continue
            if _pf_started >= 3:
                break
            _nt = _norm_title(_it)
            # Use the same article-aware match as _do_channel.
            if _q_norm_raw and not _title_match_query(_nt):
                continue
            _sources = _all_sources_by_title.get(_nt, [_it])
            _evt = threading.Event()
            self._prefetch_events[id(_it)] = _evt
            _pf_t = threading.Thread(
                target=self._prefetch_links,
                args=(id(_it), list(_sources), _evt),
                name='NS-pf-%s' % (_nt[:20] if _nt else '?'),
                daemon=True
            )
            _pf_t.start()
            _pf_started += 1

        # ── Step 4b: Reset panel and re-populate with final sorted list ──
        with self._lock:
            self._items = deduped
        try:
            self.getControl(SEARCH_WL_SC).reset()
        except Exception:
            pass
        self._populate_grid(deduped)
        if deduped:
            self._update_hero(deduped[0])

        # ── Step 5: Finalize ───────────────────────────────────────────
        total = len(deduped)
        try:
            self.getControl(SEARCH_LOADING).setVisible(False)
            if total == 0:
                self.getControl(SEARCH_NORESULTS).setVisible(True)
                self._set_progress('Nessun risultato trovato per questa ricerca.')
            else:
                self._set_progress('[B]%d risultati[/B]  trovati tra tutti i canali' % total)
        except Exception:
            pass
        self._search_done.set()

    def _prefetch_links(self, item_id, sources, event):
        """Background: find first playable HD stream URL across ALL channel sources.

        Strategy:
          Phase 1 (parallel) — two task types submitted to the SAME thread pool:
            A) For each known source (channels that returned this film in search):
               call check()/findvideos() directly on the item URL.
            B) For each OTHER active+global_search channel NOT already in sources:
               search the channel for the film title, then call check()/findvideos()
               on matching results. This covers channels that missed the film during
               the global search (site slow, different indexing, etc.).
          Phase 2 (sequential) — sort all collected server items HD-first via
               sort_servers, resolve URLs one by one, stop at first working one.

        No server names are hardcoded — we test whatever findvideos returns from
        each channel (mixdrop, streamtape, voe, doodstream, … anything).
        """
        import re as _re

        try:
            _ART_RE = _re.compile(
                r'^(il |la |lo |i |le |gli |l |un |una |uno |the |a |an )'
            )
            from core import servertools, channeltools
            from core.servertools import sort_servers
            from core.item import Item as _PFItem
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import channelselector as _cs

            # ── helpers ────────────────────────────────────────────────────────
            def _norm(s):
                s = _re.sub(r'\[/?[A-Za-z][^\]]*\]', '', s or '').strip().lower()
                s = _re.sub(r'[^a-z0-9 ]', '', s)
                return _re.sub(r'\s+', ' ', s).strip()

            # Title: use original casing for search(), normalized for matching
            _ref  = sources[0] if sources else None
            _raw_title = (
                (getattr(_ref, 'fulltitle', '') or getattr(_ref, 'title', ''))
                if _ref else ''
            )
            # Strip Kodi colour tags from the raw title
            _raw_title = _re.sub(r'\[/?[A-Za-z][^\]]*\]', '', _raw_title).strip()
            _tq   = _norm(_raw_title)   # normalized version for title-match filtering
            _known_channels = {getattr(s, 'channel', '') for s in sources}

            def _fetch_servers(src):
                """Call check()/findvideos() on a known source Item → server items."""
                ch_name = getattr(src, 'channel', None)
                if not ch_name or self._pf_cancelled.is_set():
                    return []
                try:
                    ch  = __import__('channels.' + ch_name, fromlist=[ch_name])
                    act = getattr(src, 'action', 'findvideos')
                    if act == 'check' and hasattr(ch, 'check'):
                        sv = ch.check(src)
                    elif hasattr(ch, act):
                        sv = getattr(ch, act)(src)
                    elif hasattr(ch, 'findvideos'):
                        sv = ch.findvideos(src)
                    else:
                        return []
                    svlist = [i for i in (sv or []) if getattr(i, 'server', None)]
                    if svlist:
                        logger.debug('[NS-pf] fetch ch=%s → %d servers' % (ch_name, len(svlist)))
                    return svlist
                except Exception as _ex:
                    logger.debug('[NS-pf] fetch ch=%s: %s' % (ch_name, str(_ex)))
                    return []

            def _search_and_fetch(ch_name):
                """Search ch_name for the film title, call findvideos on matches → server items."""
                if self._pf_cancelled.is_set() or not _raw_title:
                    return []
                try:
                    ch = __import__('channels.' + ch_name, fromlist=[ch_name])
                    if not hasattr(ch, 'search'):
                        return []
                    # Pass original (un-normalised) title so case-sensitive searches work
                    results = ch.search(_PFItem(channel=ch_name), _raw_title) or []
                    # Keep only results whose title STARTS WITH the query (after normalisation).
                    # startswith rejects superset false-positives: "Un Amore per sempre"
                    # contains all query words but does NOT start with "amore per sempre",
                    # so it is correctly discarded. Quality/year suffixes are fine:
                    # "Amore per sempre HD" and "Amore per sempre 2021" both pass.
                    def _title_matches_ch(r):
                        if not _tq:
                            return False
                        n = _norm(getattr(r, 'title', '') or '')
                        # exact match OR result is query + suffix (quality/year)
                        if n == _tq or n.startswith(_tq + ' '):
                            return True
                        # article-aware: if _tq starts with leading article, also try stripped
                        _tq_stripped = _ART_RE.sub('', _tq, count=1).strip() if _ART_RE.match(_tq) else _tq
                        if _tq_stripped != _tq:
                            n_stripped = _ART_RE.sub('', n, count=1).strip()
                            return (n_stripped == _tq_stripped
                                    or n_stripped.startswith(_tq_stripped + ' ')
                                    or _tq_stripped.startswith(n_stripped + ' '))
                        return False

                    matched = [r for r in results if _title_matches_ch(r)]
                    if not matched:
                        return []
                    logger.debug('[NS-pf] search ch=%s → %d matches for "%s"' % (
                        ch_name, len(matched), _raw_title))
                    servers = []
                    for m in matched[:1]:   # max 1 item per channel to avoid noise
                        if self._pf_cancelled.is_set():
                            break
                        servers.extend(_fetch_servers(m))
                    return servers
                except Exception as _ex:
                    logger.debug('[NS-pf] search_fetch ch=%s: %s' % (ch_name, str(_ex)))
                    return []

            # ── discover extra channels ────────────────────────────────────────
            extra_channels = []
            try:
                for _ch in _cs.filterchannels('all'):
                    if _ch.channel == 'streamingcommunity':
                        continue
                    if _ch.channel in _known_channels:
                        continue
                    cp = channeltools.get_channel_parameters(_ch.channel)
                    if cp.get('active', False) and cp.get('include_in_global_search', False):
                        extra_channels.append(_ch.channel)
            except Exception as _ex:
                logger.debug('[NS-pf] extra channels detection: %s' % str(_ex))

            logger.info('[NS-pf] sources=%d known=%s · extra=%s · title="%s"' % (
                len(sources), sorted(_known_channels), sorted(extra_channels[:5]), _raw_title))

            # ── Phase 1: all tasks run in the SAME parallel pool ───────────────
            all_sv = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                futs = {}
                for src in sources:
                    futs[pool.submit(_fetch_servers, src)] = getattr(src, 'channel', '?')
                for ch in extra_channels:
                    futs[pool.submit(_search_and_fetch, ch)] = ch
                for fut in as_completed(futs):
                    if self._pf_cancelled.is_set():
                        break
                    all_sv.extend(fut.result() or [])

            if not all_sv or self._pf_cancelled.is_set():
                return

            logger.info('[NS-pf] Phase 1 total server items: %d' % len(all_sv))

            # ── Phase 2: sort HD-first, test sequentially, stop at first working ─
            for si in sort_servers(all_sv):
                if self._pf_cancelled.is_set():
                    break
                try:
                    video_urls, ok, _ = servertools.resolve_video_urls_for_playing(
                        si.server, si.url)
                    if ok and video_urls:
                        _stream_url = video_urls[0][1]
                        # Skip if the resolved URL is an image (e.g. mixdrop returning
                        # a CDN thumbnail instead of a real stream).
                        _IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
                        if any(_stream_url.lower().split('?')[0].endswith(ext)
                               for ext in _IMAGE_EXT):
                            logger.info('[NS-pf] SKIP image URL server=%s url=%.60s' % (
                                si.server, _stream_url))
                            continue
                        self._prefetch_results[item_id] = (si, video_urls[0])
                        logger.info('[NS-pf] FOUND server=%s qual=%s url=%.60s' % (
                            si.server, getattr(si, 'quality', '?'), video_urls[0][1]))
                        return  # stop immediately
                except Exception:
                    continue

        except Exception as ex:
            logger.error('[NS-pf] fatal: %s' % str(ex))
        finally:
            self._prefetch_results.setdefault(item_id, None)
            event.set()
            logger.info('[NS-pf] done item_id=%d found=%s' % (
                item_id, 'YES' if self._prefetch_results.get(item_id) else 'NO'))

    def _set_progress(self, text):
        try:
            self.getControl(SEARCH_PROGRESS).setLabel(text)
        except Exception:
            pass


xbmc.log('[NetflixSearch] MODULE: NetflixSearchWindow defined OK', xbmc.LOGINFO)


def open_netflix_home():
    """Public entry point — called from launcher.py."""
    _shutdown_event.clear()   # reset shutdown flag for this session
    win = NetflixHomeWindow('NetflixHome.xml', config.get_runtime_path())
    win.show()
    monitor = xbmc.Monitor()
    while not monitor.abortRequested() and win._alive:
        monitor.waitForAbort(0.5)
    # Signal all background threads to stop BEFORE destroying the window.
    # _shutdown_event tells every BG network thread not to issue new HTTP requests.
    # The currently-in-flight request will finish within its 3-second socket timeout,
    # then the thread checks the flag and returns — all within Kodi's 5-second window.
    win._alive = False
    _shutdown_event.set()     # unblocks all BG network threads immediately
    xbmc.sleep(300)   # brief pause so threads notice _alive=False / _shutdown_event
    del win
