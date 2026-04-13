# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Netflix-style Home Window for StreamingCommunity + multi-source
# v4 — lazy-load extra rows from other VOD channels.
# ------------------------------------------------------------

import re
import sys
import threading
import xbmc
import xbmcaddon
import xbmcgui

from core.item import Item
from platformcode import config, logger

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

BG_FANART          = 100
HERO_CATEG         = 102
HERO_TITLE         = 103
HERO_META          = 104
HERO_PLOT          = 105
CLOSE_BTN          = 108
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

# ── Detail window control IDs ──────────────────────────────────
DW_BG_FANART   = 201
DW_VIDEO       = 202
DW_TITLE       = 204
DW_META1       = 205
DW_META2       = 206
DW_META3       = 207
DW_TAGLINE     = 208
DW_PLOT        = 209
DW_BTN_PLAY    = 210
DW_BTN_LIST    = 211
DW_BTN_CLOSE   = 212

ACTION_EXIT         = 10
ACTION_BACK         = 92
ACTION_LEFT         = 1
ACTION_RIGHT        = 2
ACTION_UP           = 3
ACTION_DOWN         = 4
ACTION_WHEEL_UP     = 104
ACTION_WHEEL_DOWN   = 105
ACTION_MOUSE_MOVE   = 107


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
        """Run in background thread: fetch SC rows, then update UI."""
        try:
            self.rows_data = _fetch_rows()
        except Exception as exc:
            logger.error('[NetflixHome] fetch error: %s' % str(exc))
            self.rows_data = []

        if not self._alive:
            return

        try:
            self.getControl(LOADING_LBL).setVisible(False)
        except Exception:
            pass

        self._num_rows = min(len(self.rows_data), MAX_ROWS)
        logger.debug('[NetflixHome] rows loaded: %d' % self._num_rows)

        if self._num_rows > 0 and self._alive:
            xbmc.sleep(80)
            for i in range(min(4, self._num_rows)):
                self._populate_single_row(i)
            self._update_hero(0)
            self.setFocusId(ROW_WRAPLIST_BASE)

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
            # Step 1: collect which content types are needed across all SC rows
            needed_types = set()
            for label, _ in list(self.rows_data):
                ct = _row_content_type(label)
                if ct:
                    needed_types.add(ct)
            if not needed_types or not self._alive:
                return

            # Step 2: pre-fetch all needed types concurrently
            fetch_threads = []
            for ct in needed_types:
                t = threading.Thread(target=_fetch_enrich_items, args=(ct,))
                t.daemon = True
                fetch_threads.append(t)
                t.start()
            for t in fetch_threads:
                t.join(timeout=_EXTRA_TIMEOUT + 5)

            if not self._alive:
                return

            # Step 3: enrich each SC row using the now-cached pools
            for i in range(len(self.rows_data)):
                if not self._alive:
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
            # Uses 3 workers max and a lightweight /videos endpoint — safe for Kodi.
            if self._alive:
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
        try:
            wl = self.getControl(wl_id)
            wl.reset()
            wl.addItems([_item_to_li(it) for it in items])
            self._populated.add(i)
        except Exception as exc:
            logger.error('[NetflixHome] populate row %d wraplist: %s' % (i, str(exc)))
        try:
            self.getControl(lbl_id).setLabel('[B]%s[/B]' % cat_name.upper())
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
                pos = self.getControl(ROW_WRAPLIST_BASE + row_idx * ROW_STEP).getSelectedPosition()
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
        # Truncate plot to ~220 chars (56px label height in v6 hero = ~4 lines)
        if len(plot) > 220:
            plot = plot[:217] + '...'
        try:
            img = fanart or thumb
            if img:
                self.getControl(BG_FANART).setImage(img)
            self.getControl(HERO_TITLE).setLabel('[B]' + title + '[/B]')
            meta = '  •  '.join(p for p in [year, ctype_lbl, lang, rating_str, genre_str] if p)
            self.getControl(HERO_META).setLabel(meta)
            self.getControl(HERO_CATEG).setLabel(self.rows_data[row_idx][0])
            try:
                self.getControl(HERO_PLOT).setLabel(plot)
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
            self.getControl(HOVER_BOX_BASE + row_idx * ROW_STEP).setPosition(-278, 42)
        except Exception:
            pass

    def onFocus(self, control_id):
        """Fires when a control gains focus."""
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
                    sel = self.getControl(ROW_WRAPLIST_BASE + i * ROW_STEP).getSelectedPosition()
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
                                new_idx = (base + slot) % n_items
                                cur_sel = self.getControl(ROW_WRAPLIST_BASE + i * ROW_STEP).getSelectedPosition()
                                self._hover_item[i] = new_idx
                                # Move hover-frame to the correct card slot (y=42 = label_h)
                                if self._hover_box_row >= 0 and self._hover_box_row != i:
                                    self._hide_hover_box(self._hover_box_row)
                                try:
                                    self.getControl(HOVER_BOX_BASE + i * ROW_STEP).setPosition(slot * 278, 42)
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
                pos = self.getControl(ROW_WRAPLIST_BASE + i * ROW_STEP).getSelectedPosition()
                if pos < 0 or pos >= len(items):
                    pos = 0
            except Exception:
                pos = 0
        elif pos >= len(items):
            pos = 0
        return items[pos]

    def onClick(self, control_id):
        if control_id == CLOSE_BTN:
            self._alive = False
            self.close()
            return

        # ── Overlay button click (mouse click on card) → open detail window ──
        for i in range(self._num_rows):
            if control_id == ROW_OVERLAY_BASE + i * ROW_STEP:
                try:
                    item_idx = self._hover_item.get(i)
                    if item_idx is None:
                        item_idx = self.getControl(ROW_WRAPLIST_BASE + i * ROW_STEP).getSelectedPosition()
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
                    pos     = wl.getSelectedPosition()
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
                    pos = self.getControl(wl_id).getSelectedPosition()
                    if 0 <= pos < len(self.rows_data[i][1]):
                        self._open_detail(self.rows_data[i][1][pos])
                except Exception as exc:
                    logger.error('[NetflixHome] onClick row %d: %s' % (i, str(exc)))
                break

    def _launch(self, item):
        if item.action == 'findvideos':
            xbmc.executebuiltin('RunPlugin(plugin://plugin.video.prippistream/?%s)' % item.tourl())
            # After RunPlugin the video player may hide this dialog.
            # A background thread waits for playback to end then restores it.
            t = threading.Thread(target=self._wait_and_restore)
            t.daemon = True
            t.start()
        else:
            # TV show: show inline season/episode selector without leaving
            # the Netflix home (avoids all container/window navigation issues).
            t = threading.Thread(target=self._select_episode, args=(item,))
            t.daemon = True
            t.start()

    def _open_detail(self, item):
        """Open the detail window for item (called on the main Kodi GUI thread)."""
        # Save exact focus position before entering modal dialog
        saved_row = self._last_focused_row
        saved_pos = 0
        try:
            wl = self.getControl(ROW_WRAPLIST_BASE + saved_row * ROW_STEP)
            saved_pos = wl.getSelectedPosition()
        except Exception:
            pass

        self._bg_ui_pause.clear()
        try:
            win = DetailWindow('DetailWindow.xml', config.get_runtime_path(), item=item)
            win.doModal()
            result = win._result
            del win
        finally:
            self._bg_ui_pause.set()

        # Restore focus to the exact row + item position.
        # selectItem BEFORE setFocusId: setFocusId can snap the wraplist back to 0
        # if called first; selectItem must already be set when focus lands there.
        try:
            wl_id = ROW_WRAPLIST_BASE + saved_row * ROW_STEP
            self._last_focused_row = saved_row
            self._last_focused_pos = saved_pos
            self.getControl(wl_id).selectItem(saved_pos)
            xbmc.sleep(50)
            self.setFocusId(wl_id)
        except Exception:
            pass
        if result == 'play':
            self._launch(item)
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

    def _restore_home(self):
        """Bring this dialog back to front and restore keyboard focus to the last row+position."""
        try:
            self.show()
            xbmc.sleep(300)
            row   = self._last_focused_row
            wl_id = ROW_WRAPLIST_BASE + row * ROW_STEP
            try:
                self.getControl(wl_id).selectItem(self._last_focused_pos)
                xbmc.sleep(50)
                self.setFocusId(wl_id)
            except Exception:
                try:
                    self.setFocusId(CLOSE_BTN)
                except Exception:
                    pass
        except Exception as exc:
            logger.error('[NetflixHome] _restore_home: %s' % str(exc))

    def _wait_and_restore(self):
        """Wait for playback to start then finish, then bring the dialog back."""
        player  = xbmc.Player()
        monitor = xbmc.Monitor()
        # Wait up to 20 s for playback to actually start
        for _ in range(40):
            if not self._alive or monitor.abortRequested():
                return
            if player.isPlaying():
                break
            xbmc.sleep(500)
        else:
            return  # playback never started
        # Wait for playback to end
        while player.isPlaying() and self._alive and not monitor.abortRequested():
            xbmc.sleep(1000)
        if not self._alive or monitor.abortRequested():
            return
        xbmc.sleep(800)  # let Kodi settle after player closes
        self._restore_home()

    def _select_episode(self, item):
        """Inline season/episode picker for TV shows (runs in a background thread)."""
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
                chosen = seasons[0]
            else:
                sl = ['Stagione %d  (%s ep.)' % (
                    s['number'], s.get('episodes_count', '?')) for s in seasons]
                idx = xbmcgui.Dialog().select('[B]%s[/B]' % item.fulltitle, sl)
                if idx < 0:
                    return
                chosen = seasons[idx]

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
            xbmc.executebuiltin('RunPlugin(plugin://plugin.video.prippistream/?%s)' % ep_item.tourl())
            t2 = threading.Thread(target=self._wait_and_restore)
            t2.daemon = True
            t2.start()

        except Exception as exc:
            logger.error('[NetflixHome] _select_episode: %s' % str(exc))


# ── Module-level helpers ──────────────────────────────────────

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
    # Populate Kodi's native info dict so internal dialogs show full metadata
    info_type = 'movie' if getattr(item, 'contentType', '') == 'movie' else 'video'
    info_dict = {}
    for _k in ('title', 'year', 'plot', 'rating', 'votes', 'genre',
               'director', 'cast', 'runtime', 'season', 'episode', 'tvshowtitle'):
        _v = item.infoLabels.get(_k)
        if _v is not None:
            info_dict[_k] = _v
    if info_dict:
        li.setInfo(info_type, info_dict)
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

        logger.error('[NetflixHome] json_str len=%d for %s' % (len(json_str), url))
        decoded   = _html.unescape(json_str)
        cleaned   = _strip_html_fields(decoded)
        try:
            result = _json.loads(cleaned)
        except Exception as e:
            logger.error('[NetflixHome] json.loads failed for %s: %s' % (url, str(e)[:120]))
            return {}

        if isinstance(result, dict) and result:
            logger.error('[NetflixHome] OK for %s sliders=%d' % (
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
                timeout=10
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
            return vid

        # Query 2: title + "trailer italiano" (drop year)
        vid = _yt_search('%s trailer italiano' % title)
        if vid:
            return vid

        # Query 3: English fallback
        vid = _yt_search('%s%s trailer official' % (title, (' ' + year) if year else ''))
        return vid

    except Exception as exc:
        logger.error('[YTSearch] %s' % str(exc)[:100])
        return None


def _fetch_trailers_small(rows_snapshot, per_row=15, max_total=60):
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

    logger.error('[NetflixHome trailers] fetching %d new ids (3 workers)' % len(seen))
    results = {}   # tmdb_id -> url str
    lock    = threading.Lock()

    def _one(tid):
        try:
            it_obj = seen[tid]
            title  = it_obj.fulltitle or it_obj.show or it_obj.contentSerieName or ''
            year   = str(it_obj.infoLabels.get('year') or '')

            def _make_url(video_id):
                return ('plugin://plugin.video.youtube/play/?video_id=%s'
                        '&subtitle=it&language=it,en' % video_id)

            vid = _youtube_search_trailer(title, year)
            with lock:
                results[tid] = _make_url(vid) if vid else False
        except Exception as exc:
            logger.error('[NetflixHome trailers] %s: %s' % (tid, str(exc)[:60]))

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pool.map(_one, list(seen.keys()), timeout=30)

    # Store results in module cache and apply to items
    for tid, val in results.items():
        _trailer_cache[tid] = val

    found = sum(1 for v in results.values() if v)
    logger.error('[NetflixHome trailers] done: %d/%d got trailer (cache size: %d)'
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
            logger.error('[NetflixHome enrich] %s/%s: %d items fetched'
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
    for t in threads:
        t.join(timeout=_EXTRA_TIMEOUT)

    if all_items:
        try:
            from core import tmdb as _tmdb
            _tmdb.set_infoLabels_itemlist(all_items, seekTmdb=True, forced=True)
        except Exception as exc:
            logger.error('[NetflixHome enrich] tmdb: %s' % str(exc))
    _enrich_cache[ctype] = {'items': all_items, 'ts': now}
    logger.error('[NetflixHome enrich] %s pool ready: %d raw items' % (ctype, len(all_items)))
    return all_items


def _fetch_rows():
    from time import time
    global _cache
    if _cache['data'] is not None and (time() - _cache['ts']) < _CACHE_TTL:
        logger.error('[NetflixHome] cache hit, %d rows' % len(_cache['data']))
        return _cache['data']

    rows = []
    try:
        import channels.streamingcommunity as sc
        host = sc.host
        logger.error('[NetflixHome] host=%s' % host)

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
                for t in threads:
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
        self._item   = kwargs.pop('item', None)
        self._result = None   # 'play' | 'list' | None after close
        self._player = xbmc.Player()

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

        # ── Meta 1: year · type · lang · rating ───────────────────────────
        meta1 = '  \u2022  '.join(p for p in [year, ctype_lbl, lang, rating_str] if p)
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

        # ── Videowindow starts behind fanart; fanart is hidden by _start_trailer ──
        # (no need to touch videowindow visibility — fanart covers it until trailer plays)

        # ── Start trailer in background after short delay ─────────────────
        if trailer:
            t = threading.Thread(target=self._start_trailer, args=(trailer,))
            t.daemon = True
            t.start()
        else:
            # Item was not pre-fetched (e.g. beyond per_row limit) → search on-demand
            tmdb_id_tr = str(item.infoLabels.get('tmdb_id') or '').strip()
            ctype_tr   = 'tv' if getattr(item, 'contentType', '') == 'tvshow' else 'movie'
            t2 = threading.Thread(
                target=self._fetch_and_start_trailer,
                args=(title, year, tmdb_id_tr, ctype_tr),
            )
            t2.daemon = True
            t2.start()

    def _fetch_and_start_trailer(self, title, year, tmdb_id, ctype):
        """On-demand trailer search for items not pre-fetched. Runs in background thread."""
        try:
            def _make_url(video_id):
                return ('plugin://plugin.video.youtube/play/?video_id=%s'
                        '&subtitle=it&language=it,en' % video_id)

            vid = _youtube_search_trailer(title, year)
            if vid:
                self._start_trailer(_make_url(vid))
        except Exception as exc:
            logger.error('[DetailWindow] on-demand trailer: %s' % str(exc)[:100])

    def _load_hd_fanart(self, tmdb_id, ctype):
        """Upgrade background to TMDB /original/ backdrop for maximum resolution."""
        try:
            from core.tmdb import Tmdb as _Tmdb, host as _tmdb_host, api as _tmdb_api
            url  = '%s/%s/%s?api_key=%s' % (_tmdb_host, ctype, tmdb_id, _tmdb_api)
            data = _Tmdb.get_json(url)
            path = (data or {}).get('backdrop_path') or ''
            if path:
                hq_url = 'https://image.tmdb.org/t/p/original' + path
                self.getControl(DW_BG_FANART).setImage(hq_url)
        except Exception:
            pass

    def _start_trailer(self, trailer_url):
        """Delay slightly then fire PlayMedia so the window is fully rendered first."""
        xbmc.sleep(900)
        try:
            # Configure YouTube plugin to auto-select and download Italian subtitles.
            # kodion.subtitle.languages.num=2 → "preferred language with fallback"
            # (preferred = youtube.language which is already 'it').
            # kodion.subtitle.download=true → plugin writes the sub track so Kodi picks it up.
            # These settings are persistent but harmless — they just set Italian subs globally.
            try:
                yt = xbmcaddon.Addon('plugin.video.youtube')
                if yt.getSetting('kodion.subtitle.languages.num') != '2':
                    yt.setSetting('kodion.subtitle.languages.num', '2')
                if yt.getSetting('kodion.subtitle.download') != 'true':
                    yt.setSetting('kodion.subtitle.download', 'true')
                # Enforce at least 1080p (FHD):
                # When ISA is active: kodion.mpd.quality.selection 4=1080p, default is already 4
                # When ISA is off:    kodion.video.quality          4=max (1080p Live/720p cap)
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
            xbmc.executebuiltin('PlayMedia(%s)' % trailer_url)
            # Wait up to 8 s for the YouTube plugin to start playing
            for _ in range(80):
                xbmc.sleep(100)
                if self._player.isPlaying():
                    break
            if self._player.isPlaying():
                # Hide fanart so the videowindow (behind it) becomes visible
                try:
                    self.getControl(DW_BG_FANART).setVisible(False)
                except Exception:
                    pass
                # Wait longer for YouTube plugin to register audio/subtitle tracks
                xbmc.sleep(5000)
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

    def _stop_player(self):
        """Stop any active playback (trailer) and wait until fully stopped."""
        try:
            if self._player.isPlaying():
                self._player.stop()
                # Poll until isPlaying() returns False (up to 2s)
                for _ in range(20):
                    xbmc.sleep(100)
                    if not self._player.isPlaying():
                        break
                # Restore fanart overlay (covers videowindow black rectangle when idle)
                try:
                    self.getControl(DW_BG_FANART).setVisible(True)
                except Exception:
                    pass
                # IMPORTANT: isPlaying()==False does NOT mean DXVA GPU buffers are
                # released — that happens asynchronously in the video decoder thread.
                # Without this extra wait, closing the window immediately after triggers
                # a D3D11 race condition between window repaint and DXVA buffer release.
                xbmc.sleep(600)
        except Exception:
            pass

    def onAction(self, action):
        aid = action.getId()
        if aid in (self.ACTION_EXIT, self.ACTION_BACK):
            self._stop_player()
            self.close()

    def onClick(self, control_id):
        if control_id == DW_BTN_CLOSE:
            self._stop_player()
            self.close()

        elif control_id == DW_BTN_PLAY:
            self._result = 'play'
            self._stop_player()
            self.close()

        elif control_id == DW_BTN_LIST:
            self._result = 'list'
            self._stop_player()
            self.close()


def open_netflix_home():
    """Public entry point — called from launcher.py."""
    win = NetflixHomeWindow('NetflixHome.xml', config.get_runtime_path())
    win.show()
    monitor = xbmc.Monitor()
    while not monitor.abortRequested() and win._alive:
        monitor.waitForAbort(0.5)
    del win
