# -*- coding: utf-8 -*-
"""File-backed bridge between fullscreen keymaps and the active live Home session."""
import json
import glob
import os
import time

import xbmc

from platformcode import config, logger


def _path(name):
    return os.path.join(config.get_data_path(), name)


MAPPING_PATH = lambda: _path('live_remote_mapping.json')
SESSION_PATH = lambda: _path('live_remote_session.json')
COMMAND_PATH = lambda: _path('live_remote_command.json')
COMMAND_GLOB = lambda: _path('live_remote_command.*.json')


def _write_json(path, payload):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return None


def save_mapping(next_event, previous_event):
    payload = {
        'version': 1,
        'next': {'action': int(next_event[0]), 'button': int(next_event[1])},
        'previous': {'action': int(previous_event[0]), 'button': int(previous_event[1])},
        'saved_at': time.time(),
    }
    _write_json(MAPPING_PATH(), payload)


def deactivate_keymap():
    """Remove only PrippiStream's temporary fullscreen keymap."""
    key_dir = xbmc.translatePath('special://userdata/keymaps/')
    dst = os.path.join(key_dir, 'prippistream_live_remote.xml')
    try:
        os.remove(dst)
    except OSError:
        return False
    xbmc.executebuiltin('Action(reloadkeymaps)')
    logger.info('[LiveRemote] keymap temporaneo rimosso')
    return True


def activate_keymap(mapping=None):
    mapping = mapping or _read_json(MAPPING_PATH())
    if not mapping:
        return False
    next_button = int(mapping.get('next', {}).get('button') or 0)
    prev_button = int(mapping.get('previous', {}).get('button') or 0)
    if not next_button or not prev_button:
        logger.info('[LiveRemote] keymap non installato: button code non disponibili')
        return False
    if next_button == prev_button:
        logger.info('[LiveRemote] keymap non installato: button code duplicati')
        return False
    import base64
    next_q = base64.b64encode(b'{"action":"live_zap","direction":"next"}').decode('ascii')
    prev_q = base64.b64encode(b'{"action":"live_zap","direction":"previous"}').decode('ascii')
    action_names = {1: 'left', 2: 'right', 3: 'up', 4: 'down',
                    5: 'pageup', 6: 'pagedown'}
    next_action = int(mapping.get('next', {}).get('action') or 0)
    prev_action = int(mapping.get('previous', {}).get('action') or 0)

    def _binding(button, action, query):
        command = 'RunPlugin(plugin://plugin.video.prippistream/?%s)' % query
        named = action_names.get(action)
        # Android TV often reports PageUp/PageDown button codes that Kodi's
        # named key parser handles correctly while <key id=...> is ignored.
        # Keep the numeric binding too for PC/remotes that need the raw code.
        extra = '<%s>%s</%s>' % (named, command, named) if named else ''
        return '<key id="%d">%s</key>%s' % (button, command, extra)

    xml = ('<keymap><FullscreenVideo><keyboard>%s%s'
           '</keyboard></FullscreenVideo></keymap>'
           % (_binding(next_button, next_action, next_q),
              _binding(prev_button, prev_action, prev_q)))
    key_dir = xbmc.translatePath('special://userdata/keymaps/')
    os.makedirs(key_dir, exist_ok=True)
    dst = os.path.join(key_dir, 'prippistream_live_remote.xml')
    old = ''
    try:
        with open(dst, 'r', encoding='utf-8') as handle:
            old = handle.read()
    except Exception:
        pass
    if old != xml:
        with open(dst, 'w', encoding='utf-8') as handle:
            handle.write(xml)
        xbmc.executebuiltin('Action(reloadkeymaps)')
    logger.info('[LiveRemote] keymap installato next=%d previous=%d' %
                (next_button, prev_button))
    return True


# Compatibility for callers/builds that still use the old name.
install_keymap = activate_keymap


def start_session(row, items, index):
    channels = [{'title': it.fulltitle or it.title or '',
                 'par': str(getattr(it, 'sport_par', '') or '')}
                for it in items]
    _write_json(SESSION_PATH(), {'version': 1, 'row': row, 'index': int(index),
                                 'channels': channels, 'started_at': time.time()})
    clear_command()


def update_session_index(index):
    payload = _read_json(SESSION_PATH())
    if payload:
        payload['index'] = int(index)
        payload['updated_at'] = time.time()
        _write_json(SESSION_PATH(), payload)


def clear_session(deactivate=True):
    for path in [SESSION_PATH(), COMMAND_PATH()] + glob.glob(COMMAND_GLOB()):
        try:
            os.remove(path)
        except OSError:
            pass
    if deactivate:
        deactivate_keymap()


def clear_command():
    for path in [COMMAND_PATH()] + glob.glob(COMMAND_GLOB()):
        try:
            os.remove(path)
        except OSError:
            pass


def request(direction):
    if direction not in ('next', 'previous'):
        return False
    if (not config.get_setting('live_remote_enabled', default=True)
            or not os.path.exists(SESSION_PATH())):
        # The learned keys keep their normal fullscreen-video behavior for films,
        # episodes and trailers. Dispatch the semantic action, not the physical
        # key, so it cannot recurse through our generated keymap.
        xbmc.executebuiltin('Action(%s)' %
                            ('StepForward' if direction == 'next' else 'StepBack'))
        logger.info('[LiveRemote] nessuna sessione live: fallback %s' % direction)
        return False
    # Each RunPlugin invocation is a separate Python process. A shared .tmp name
    # races under held/repeated keys on Windows; unique final command files are
    # lock-free and the Home watcher coalesces them.
    stamp = '%020d.%d' % (int(time.time() * 1000000), os.getpid())
    path = _path('live_remote_command.%s.json' % stamp)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({'direction': direction, 'ts': time.time()}, handle,
                  ensure_ascii=False, separators=(',', ':'))
    logger.info('[LiveRemote] richiesta %s' % direction)
    return True


def consume_command():
    paths = sorted(glob.glob(COMMAND_GLOB()))
    if not paths:
        return None
    # Keep the newest direction and discard the burst: this is both debounce and
    # coalescing, without spawning one playback for every auto-repeat event.
    payload = _read_json(paths[-1])
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass
    return payload
