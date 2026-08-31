# -*- coding: utf-8 -*-
"""Smoke test della superficie completa dei canali inclusi nell'APK.

Importa lo stesso bridge usato da Chaquopy e verifica che ogni canale attivo sia
importabile, esponga ``mainlist`` e produca almeno una voce navigabile. Non avvia
stream e non sostituisce i test reali dei provider, ma intercetta regressioni di
sync, dipendenze Kodi mancanti e menu non raggiungibili dalla UI Android.
"""
from __future__ import print_function

import os
import sys
import traceback


HERE = os.path.dirname(os.path.abspath(__file__))
PYROOT = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
sys.path.insert(0, PYROOT)

import bridge  # noqa: E402


def main():
    bridge.init()
    catalog = bridge.channel_catalog()
    failures = []
    print('Canali attivi:', len(catalog))
    for channel in catalog:
        channel_id = channel['id']
        try:
            methods = bridge.channel_methods(channel_id)
            if 'mainlist' not in methods:
                raise RuntimeError('mainlist non esposto')
            items = bridge.channel_call(channel_id, 'mainlist', {})
            if not items:
                raise RuntimeError('menu principale vuoto')
            navigable = [item for item in items if item.get('action')]
            if not navigable:
                raise RuntimeError('nessuna voce navigabile')
            # Search e configurazione sono intercettate nativamente; tutte le
            # altre azioni che la UI può mostrare devono esistere nel modulo.
            missing = sorted({
                item.get('action') for item in navigable
                if item.get('action') not in methods
                and item.get('action') not in ('search', 'channel_config')
            })
            if missing:
                raise RuntimeError('azioni menu non esposte: ' + ', '.join(missing))
            print('OK %-22s menu=%-3d azioni=%-3d' % (
                channel_id, len(items), len(navigable),
            ))
        except Exception as exc:
            failures.append((channel_id, str(exc)))
            print('KO %-22s %s' % (channel_id, exc))
            traceback.print_exc()

    provider_settings = [
        setting
        for category in bridge.settings_schema()
        for setting in category.get('settings', [])
        if setting.get('channel')
    ]
    if provider_settings:
        failures.append(('settings', 'impostazioni provider esposte nella UI Android'))

    # La UI touch non deve riproporre controlli che hanno senso soltanto in
    # Kodi/Android TV. Il motore continua a conservarli con i relativi default.
    app_setting_ids = {
        setting.get('id')
        for category in bridge.settings_schema()
        for setting in category.get('settings', [])
    }
    kodi_only = {
        'addon_version_display', 'autostart', 'live_remote_enabled',
        'live_remote_overlay', 'live_remote_learn',
    }
    leaked = sorted(kodi_only & app_setting_ids)
    if leaked:
        failures.append(('settings', 'opzioni solo Kodi esposte: ' + ', '.join(leaked)))

    print('\nESITO: %d/%d canali raggiungibili' % (
        len(catalog) - len([f for f in failures if f[0] != 'settings']), len(catalog),
    ))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
