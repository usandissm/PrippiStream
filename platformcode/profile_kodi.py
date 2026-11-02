"""Kodi adapter for name-only CW profiles. No networking in save callbacks."""
import json
import os
import re
import threading
import time

from core.item import Item
from platformcode import config, logger, profile_sync, watch_history

_SYNC = threading.Lock()


def active():
    # Kodi caches Addon instances across RunPlugin invocations. Read freshly so
    # Home and the settings action always write to the same selected profile.
    try:
        import xbmcaddon
        return xbmcaddon.Addon('plugin.video.prippistream').getSetting('cw_profile') or ''
    except ImportError:
        return str(config.get_setting('cw_profile', default='') or '')


def _path(profile, filename='continue_watching.json'):
    folder = profile_sync.directory(profile) if profile else config.get_data_path()
    return os.path.join(folder, filename)


def _read(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError('CW non leggibili: nessun dato sovrascritto')
    return result


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False)
    os.replace(path + '.tmp', path)


def _export(entry):
    if not entry.get('item_url'):
        return None  # watched-episode shells are not playable CW entries
    raw = json.loads(json.dumps(Item().fromurl(entry['item_url']).__dict__))
    if str(entry.get('key', '')).startswith('tv_'):
        info = raw.setdefault('infoLabels', {})
        info.update(mediatype='episode', tvshowtitle=info.get('tvshowtitle') or
                    raw.get('show') or raw.get('contentSerieName') or entry.get('title', ''))
        for field in ('season', 'episode'):
            if entry.get(field) is not None:
                info[field] = entry[field]
        raw['contentType'] = 'episode'
        if entry.get('show_url') and not raw.get('_app_series_parent'):
            raw['_app_series_parent'] = dict(channel=raw.get('channel'), action='episodios',
                title=info['tvshowtitle'], fulltitle=info['tvshowtitle'], url=entry['show_url'],
                contentType='tvshow', infoLabels=dict(tmdb_id=info.get('tmdb_id', ''),
                mediatype='tvshow', title=info['tvshowtitle']))
    return dict(item=raw, position_ms=round(float(entry.get('time_watched', 0)) * 1000),
                duration_ms=round(float(entry.get('total_time', 0)) * 1000),
                updated_at=round(float(entry.get('timestamp', 0)) * 1000))


def _snapshot(profile):
    entries = [row for row in (_export(e) for e in _read(_path(profile)).values()) if row]
    deletions = list(_read(_path(profile, 'profile_deletions.json')).values()) if profile else []
    return dict(entries=entries, deletions=deletions)


def record_removal(entry):
    """Called under watch_history._lock. Never sends network requests."""
    profile = active()
    if not profile:
        return
    row = _export(entry)
    if row:
        row.update(deleted=True, updated_at=round(time.time() * 1000))
        path = _path(profile, 'profile_deletions.json')
        deletions = _read(path)
        deletions[str(entry['key'])] = row
        _write(path, deletions)


def _import(response, previous):
    data = {}
    for row in response['entries']:
        raw = profile_sync.clean_item(row['item'])
        info = raw.setdefault('infoLabels', {})
        identity = profile_sync.identity(raw)
        series = identity.startswith('series:')
        parent = raw.get('_app_series_parent') or {}
        title = ((info.get('tvshowtitle') or raw.get('contentSerieName') or raw.get('show') or
                  parent.get('fulltitle') or parent.get('title')) if series else '') or raw.get('fulltitle') or raw.get('title') or info.get('title', '')
        tmdb = identity.split(':')[-1] if ':tmdb:' in identity else ''
        base = tmdb or re.sub(r'[^a-z0-9]', '', title.lower())
        key = ('tv_' if series else 'movie_') + base
        if not base:
            key += identity.split(':')[-1]
        if tmdb:
            info['tmdb_id'] = tmdb
        if series:
            raw.update(contentType='episode', show=title, contentSerieName=title)
            info.update(mediatype='episode', tvshowtitle=title)
        else:
            raw.setdefault('fulltitle', title)
        entry = dict(key=key, title=title, thumbnail=raw.get('thumbnail', ''), fanart=raw.get('fanart', ''),
                     time_watched=row['position_ms'] / 1000.0, total_time=row['duration_ms'] / 1000.0,
                     timestamp=row['updated_at'] / 1000.0, item_url=Item(**raw).tourl(),
                     show_url=parent.get('url') or raw.get('_cw_show_url', ''),
                     season=info.get('season', raw.get('contentSeason')),
                     episode=info.get('episode', raw.get('contentEpisodeNumber')),
                     episode_title=info.get('title', ''))
        if previous.get(key, {}).get('watched_episodes'):
            entry['watched_episodes'] = previous[key]['watched_episodes']
        data[key] = entry
    return data


def sync(profile=None, connect=False, activate=False, mode='auto'):
    """Compare-and-apply prevents late HTTP replies overwriting fresh playback."""
    if not _SYNC.acquire(False):
        return False
    try:
        selected = active()
        profile = profile_sync.name(profile or selected)
        with watch_history._lock:
            before = _snapshot(profile)
            seed = _snapshot(selected)['entries'] if connect else None
            if connect and mode == 'join' and selected and selected != profile:
                seed = before['entries']  # never mix two different named profiles
        response = profile_sync.exchange(profile, before['entries'] + before['deletions'], connect, seed, mode)
        if not response.get('complete'):
            return False
        with watch_history._lock:
            if active() != selected or before != _snapshot(profile):
                return False
            previous = _read(_path(profile))
            imported = _import(response, previous)
            _write(_path(profile), imported)
            # Clear only after the durable shared outbox has been acknowledged.
            _write(_path(profile, 'profile_deletions.json'), {})
            if activate:
                config.set_setting('cw_profile', profile)
                if active() != profile:
                    raise OSError('Selezione profilo non salvata')
        return previous != imported or activate
    finally:
        _SYNC.release()


def setup(onboarding=False):
    import xbmc
    import xbmcgui
    dialog = xbmcgui.Dialog()
    if xbmc.Player().isPlayingVideo():
        dialog.ok('Profilo CW', 'Interrompi la riproduzione prima di cambiare profilo.')
        return
    choice = dialog.select('Profilo PrippiStream · stessi CW su APK e Kodi',
                           ['Ho già un profilo', 'Crea un profilo', 'Solo su questo dispositivo'])
    if choice < 0:
        return
    if choice == 2:
        config.set_setting('cw_profile', '')
        config.set_setting('cw_profile_onboarding_done', True)
        return
    mode = 'join' if choice == 0 else 'create'
    dialog.ok('Il tuo profilo', ('Inserisci il nome del profilo già creato.' if mode == 'join' else
              'Scegli un nome univoco, non già utilizzato. I CW attuali verranno copiati nel nuovo profilo.') +
              ' Usa lo stesso nome sugli altri dispositivi. Senza password: chi conosce il nome accede ai CW.')
    value = dialog.input('Nome profilo univoco' if mode == 'create' else 'Nome profilo esistente', defaultt=active() if mode == 'join' else '')
    if not value.strip():
        return
    busy = xbmcgui.DialogProgress()
    busy.create('Profilo CW', 'Collegamento e sincronizzazione…')
    try:
        if not sync(value, connect=True, activate=True, mode=mode):
            raise ValueError('Progressi cambiati durante il collegamento: riprova')
        config.set_setting('cw_profile_onboarding_done', True)
        dialog.ok('Profilo CW', 'Profilo collegato: ' + active())
    except ValueError as exc:
        dialog.ok('Profilo CW', str(exc))
    except Exception as exc:
        logger.error('[Profile] connect failed: %s' % type(exc).__name__)
        dialog.ok('Profilo CW', 'Collegamento non riuscito. I CW precedenti sono conservati. Riprova con una connessione disponibile.')
    finally:
        busy.close()


def offer_onboarding():
    try:
        import xbmcaddon
        done = xbmcaddon.Addon('plugin.video.prippistream').getSetting('cw_profile_onboarding_done') == 'true'
    except ImportError:
        done = config.get_setting('cw_profile_onboarding_done', default=False)
    if not done:
        setup(onboarding=True)
