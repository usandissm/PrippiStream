# -*- coding: utf-8 -*-
import ast
import datetime
import math
import os
import sys
import threading
import traceback
import xbmc

try:
    from urllib.parse import urlsplit
except ImportError:
    from urlparse import urlsplit
# on kodi 18 its xbmc.translatePath, on 19 xbmcvfs.translatePath
try:
    import xbmcvfs
    xbmc.translatePath = xbmcvfs.translatePath
except:
    pass
from platformcode import config
librerias = xbmc.translatePath(os.path.join(config.get_runtime_path(), 'lib'))
sys.path.insert(0, librerias)
os.environ['TMPDIR'] = config.get_temp_file('')

from core import filetools, channeltools, httptools, scrapertools, db
from lib import schedule
from platformcode import logger, platformtools, updater, xbmc_videolibrary
from servers import torrent

# if this service need to be reloaded because an update changed it
needsReload = False
# list of threads
threads = []


def updaterCheck():
    global needsReload
    # updater check
    updated, needsReload = updater.check(background=True)


def get_ua_list():
    # https://github.com/alfa-addon/addon/blob/master/plugin.video.alfa/platformcode/updater.py#L273
    logger.info()
    url = "https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform=Windows&num=6&offset=0"

    try:
        current_ver = config.get_setting("chrome_ua_version", default="").split(".")
        data = httptools.downloadpage(url, alfa_s=True, ignore_response_code=True).data

        data = ast.literal_eval(data)
        new_ua_ver = data[0].get('version', '') if data and isinstance(data, list) else ''
        if not new_ua_ver:
            return

        if not current_ver:
            config.set_setting("chrome_ua_version", new_ua_ver)
        else:
            for pos, val in enumerate(new_ua_ver.split('.')):
                if int(val) > int(current_ver[pos]):
                    config.set_setting("chrome_ua_version", new_ua_ver)
                    break
    except:
        logger.error(traceback.format_exc())


def run_threaded(job_func, args):
    job_thread = threading.Thread(target=job_func, args=args)
    job_thread.daemon = True   # daemon=True: Python interpreter can exit even if this
    job_thread.start()         # thread is still running (e.g. long library update scan)
    threads.append(job_thread)


def join_threads():
    logger.debug(threads)
    for th in threads:
        try:
            th.join(timeout=5)   # cap wait — network threads may block indefinitely
        except:
            logger.error(traceback.format_exc())


def _update_channels_json():
    """
    Downloads channels.json from the GitHub repo and updates the local copy if changed.
    Runs once at Kodi startup and then every 24h via schedule.
    When the file changes, invalidates the in-memory cache in config.py so that
    the next call to get_channel_url() uses the fresh domains.
    """
    REMOTE_URL = 'https://raw.githubusercontent.com/usandissm/PrippiStream/main/channels.json'
    local_path = os.path.join(config.get_runtime_path(), 'channels.json')
    try:
        try:
            import urllib.request as _urllib
        except ImportError:
            import urllib as _urllib
        remote_data = _urllib.urlopen(REMOTE_URL, timeout=10).read().decode('utf-8')
        try:
            with open(local_path, 'r', encoding='utf-8') as f:
                local_data = f.read()
        except Exception:
            local_data = ''
        if remote_data.strip() != local_data.strip():
            with open(local_path, 'w', encoding='utf-8') as f:
                f.write(remote_data)
            # Invalidate in-memory cache so next call re-reads the file
            config.channels_data = dict()
            logger.info('[channels_update] channels.json aggiornato dal repository')
        else:
            logger.debug('[channels_update] channels.json già aggiornato')
    except Exception as e:
        logger.error('[channels_update] errore aggiornamento channels.json: %s' % str(e))


class AddonMonitor(xbmc.Monitor):
    def __init__(self):
        self.settings_pre = config.get_all_settings_addon()

        self.updaterPeriod = None
        self.update_setting = None
        self.update_hour = None
        self.scheduleScreenOnJobs()
        self.scheduleUpdater()
        self.scheduleUA()
        super(AddonMonitor, self).__init__()

    def onSettingsChanged(self):
        logger.debug('settings changed')
        settings_post = config.get_all_settings_addon()
        # sometimes kodi randomly return default settings (rare but happens), this if try to workaround this
        if settings_post and settings_post.get('show_once', True):

            if self.settings_pre.get('addon_update_timer') != settings_post.get('addon_update_timer'):
                schedule.clear('updater')
                self.scheduleUpdater()

            if self.settings_pre.get('elementum_on_seed') != settings_post.get('elementum_on_seed') and settings_post.get('elementum_on_seed'):
                if not platformtools.dialog_yesno(config.get_localized_string(70805), config.get_localized_string(70806)):
                    config.set_setting('elementum_on_seed', False)
            if self.settings_pre.get("shortcut_key", '') != settings_post.get("shortcut_key", ''):
                xbmc.executebuiltin('Action(reloadkeymaps)')
            if self.settings_pre.get('downloadenabled') != settings_post.get('downloadenabled'):
                platformtools.itemlist_refresh()

            # backup settings
            filetools.copy(os.path.join(config.get_data_path(), "settings.xml"),
                           os.path.join(config.get_data_path(), "settings.bak"), True)
            logger.debug({k: self.settings_pre[k] for k in self.settings_pre
                          if k in settings_post and self.settings_pre[k] != settings_post[k]})

            self.settings_pre = config.get_all_settings_addon()

    def onNotification(self, sender, method, data):
        # logger.debug('METHOD', method, sender, data)
        if method == 'Playlist.OnAdd':
            from core import db
            db['OnPlay']['addon'] = True
            db.close()
        elif method == 'Player.OnStop':
            from core import db
            db['OnPlay']['addon'] = False
            db.close()
        elif method == 'VideoLibrary.OnUpdate':
            xbmc_videolibrary.set_watched_on_addon(data)
            logger.debug('AGGIORNO')

    def onScreensaverActivated(self):
        logger.debug('screensaver activated, un-scheduling screen-on jobs')
        schedule.clear('screenOn')

    def onScreensaverDeactivated(self):
        logger.debug('screensaver deactivated, re-scheduling screen-on jobs')
        self.scheduleScreenOnJobs()

    def scheduleUpdater(self):
        if not config.dev_mode():
            updaterCheck()
            self.updaterPeriod = config.get_setting('addon_update_timer')
            schedule.every(self.updaterPeriod).hours.do(updaterCheck).tag('updater')
            logger.debug('scheduled updater every ' + str(self.updaterPeriod) + ' hours')

    def scheduleUA(self):
        get_ua_list()
        schedule.every(1).day.do(get_ua_list)

    def scheduleScreenOnJobs(self):
        schedule.every().second.do(platformtools.viewmodeMonitor).tag('screenOn')
        schedule.every().second.do(torrent.elementum_monitor).tag('screenOn')

    def onDPMSActivated(self):
        logger.debug('DPMS activated, un-scheduling screen-on jobs')
        schedule.clear('screenOn')

    def onDPMSDeactivated(self):
        logger.debug('DPMS deactivated, re-scheduling screen-on jobs')
        self.scheduleScreenOnJobs()


if __name__ == "__main__":
    logger.info('Starting PrippiStream service')

    # Test if all the required directories are created
    config.verify_directories_created()

    # Install keymap: copy back_stops_video.xml to userdata/keymaps/ so that
    # pressing Back in fullscreen video stops playback on every device.
    try:
        _keymap_src = filetools.join(config.get_runtime_path(), 'resources', 'keymaps', 'back_stops_video.xml')
        _keymap_dst_dir = xbmc.translatePath('special://userdata/keymaps/')
        _keymap_dst = filetools.join(_keymap_dst_dir, 'back_stops_video.xml')
        if not filetools.isdir(_keymap_dst_dir):
            filetools.mkdir(_keymap_dst_dir)
        # Only write if missing or content differs (idempotent)
        _src_data = filetools.read(_keymap_src)
        if not filetools.isfile(_keymap_dst) or filetools.read(_keymap_dst) != _src_data:
            filetools.write(_keymap_dst, _src_data)
            xbmc.executebuiltin('Action(reloadkeymaps)')
            logger.info('Keymap back_stops_video installed/updated')
    except:
        logger.error('Could not install keymap: ' + traceback.format_exc())

    # Force mandatory settings on every startup (new install, update, or existing).
    # These are always overwritten so the user never has to set them manually.
    config.set_setting('autostart', True)       # launch at Kodi start
    config.set_setting('default_action', 2)     # video quality = High (0=Ask, 1=Low, 2=High)

    # Suppress the YouTube addon setup wizard so it never appears to the user.
    # The wizard key is 'kodion.setup_wizard'; setting it to 'false' prevents it
    # from showing both on first install and after YouTube updates.
    try:
        import xbmcaddon as _xbmcaddon
        _yt_addon = _xbmcaddon.Addon('plugin.video.youtube')
        if _yt_addon.getSetting('kodion.setup_wizard') != 'false':
            _yt_addon.setSetting('kodion.setup_wizard', 'false')
            logger.info('[Setup] YouTube setup wizard suppressed')
    except Exception:
        pass  # YouTube not installed yet — will be suppressed on next service start

    if config.get_setting('autostart'):
        xbmc.executebuiltin('RunAddon(plugin.video.' + config.PLUGIN_NAME + ')')

    # port old db to new
    old_db_name = filetools.join(config.get_data_path(), "prippistream_db.sqlite")
    if filetools.isfile(old_db_name):
        try:
            import sqlite3

            old_db_conn = sqlite3.connect(old_db_name, timeout=15)
            old_db = old_db_conn.cursor()
            old_db.execute('select * from viewed')

            for ris in old_db.fetchall():
                if ris[1]:  # tvshow
                    show = db['viewed'].get(ris[0], {})
                    show[str(ris[1]) + 'x' + str(ris[2])] = ris[3]
                    db['viewed'][ris[0]] = show
                else:  # film
                    db['viewed'][ris[0]] = ris[3]
        except:
            pass
        finally:
            filetools.remove(old_db_name, True, False)

    # replace tvdb to tmdb for series
    if config.get_setting('videolibrary_kodi') and config.get_setting('show_once'):
        nun_records, records = xbmc_videolibrary.execute_sql_kodi('select * from path where strPath like "' +
                                           filetools.join(config.get_setting('videolibrarypath'), config.get_setting('folder_tvshows')) +
                                           '%" and strScraper="metadata.tvdb.com"')
        if nun_records:
            import xbmcaddon
            # change language
            tvdbLang = xbmcaddon.Addon(id="metadata.tvdb.com").getSetting('language')
            newLang = tvdbLang + '-' + tvdbLang.upper()
            xbmcaddon.Addon(id="metadata.tvshows.themoviedb.org").setSetting('language', newLang)
            updater.refreshLang()

            # prepare to replace strSettings
            path_settings = xbmc.translatePath("special://profile/addon_data/metadata.tvshows.themoviedb.org/settings.xml")
            settings_data = filetools.read(path_settings)
            strSettings = ' '.join(settings_data.split()).replace("> <", "><")
            strSettings = strSettings.replace("\"", "\'")

            # update db
            nun_records, records = xbmc_videolibrary.execute_sql_kodi(
                'update path set strScraper="metadata.tvshows.themoviedb.org", strSettings="' + strSettings + '" where strPath like "' +
                filetools.join(config.get_setting('videolibrarypath'), config.get_setting('folder_tvshows')) +
                '%" and strScraper="metadata.tvdb.com"')

            # scan new info
            xbmc.executebuiltin('UpdateLibrary(video)')
            xbmc.executebuiltin('CleanLibrary(video)')
            # while xbmc.getCondVisibility('Library.IsScanningVideo()'):
            #     xbmc.sleep(1000)

    # check if the user has any connection problems
    from platformcode.checkhost import test_conn
    run_threaded(test_conn, (True, not config.get_setting('resolver_dns'), True, [], [], True))

    # Schedule daily channels.json update from GitHub (domain list refresh)
    schedule.every().day.do(run_threaded, _update_channels_json, ()).tag('channels_update')
    # Also run once at startup (in background, non-blocking)
    run_threaded(_update_channels_json, ())

    # ── Addon update notification (works on every platform including Android TV) ──
    # Kodi's own update toast is sometimes suppressed by skins/settings on TV.
    # We detect the version change ourselves and show a reliable notification.
    try:
        current_ver = config.get_addon_version(with_fix=False)
        last_ver    = config.get_setting('last_notified_version', default='')
        if current_ver != last_ver:
            import xbmcgui
            xbmcgui.Dialog().notification(
                config.get_localized_string(20000),                     # "PrippiStream"
                u'Aggiornato alla versione %s' % current_ver,
                xbmcgui.NOTIFICATION_INFO,
                5000,   # 5 s
                True    # sound=True
            )
            config.set_setting('last_notified_version', current_ver)
    except Exception:
        logger.error(traceback.format_exc())

    monitor = AddonMonitor()

    while True:
        try:
            schedule.run_pending()
        except:
            logger.error(traceback.format_exc())

        if needsReload:
            join_threads()
            db.close()
            logger.info('Relaunching service.py')
            xbmc.executeJSONRPC(
                '{"jsonrpc": "2.0", "id":1, "method": "Addons.SetAddonEnabled", "params": { "addonid": "plugin.video.prippistream", "enabled": false }}')
            xbmc.executeJSONRPC(
                '{"jsonrpc": "2.0", "id":1, "method": "Addons.SetAddonEnabled", "params": { "addonid": "plugin.video.prippistream", "enabled": true }}')
            logger.debug(threading.enumerate())
            break

        if monitor.waitForAbort(1): # every second
            logger.debug('PrippiStream service EXIT')
            # db need to be closed when not used, it will cause freezes
            join_threads()
            logger.debug('Close Threads')
            db.close()
            logger.debug('Close DB')
            break
    logger.debug('PrippiStream service STOPPED')