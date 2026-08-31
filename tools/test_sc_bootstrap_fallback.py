# -*- coding: utf-8 -*-
"""Regression test del fallback SC verso il bootstrap WebView Android."""

import os
import sys
from types import SimpleNamespace


HERE = os.path.dirname(os.path.abspath(__file__))
PYROOT = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
sys.path.insert(0, PYROOT)

import bridge  # noqa: E402


def main():
    direct = 'https://vixcloud.co/embed/775471?token=test'
    worker = 'https://example.workers.dev/embed/775471?token=test'

    assert bridge._streamingcommunity_bootstrap_url(
        SimpleNamespace(bootstrap_url=direct),
        'https://streamingcommunity.example/title/1',
    ) == direct
    assert bridge._streamingcommunity_bootstrap_url(
        SimpleNamespace(bootstrap_url=''),
        worker,
    ) == worker
    assert bridge._streamingcommunity_bootstrap_url(
        SimpleNamespace(bootstrap_url=''),
        'https://streamingcommunity.example/title/1',
    ) == ''
    assert bridge._streamingcommunity_bootstrap_url(
        SimpleNamespace(bootstrap_url='javascript:alert(1)'),
        '',
    ) == ''

    # Verifica anche il ramo completo di bridge.resolve: un resolver Python
    # senza URL deve produrre una richiesta bootstrap, non abortire il play.
    bridge.init()
    from core import servertools
    from servers import streamingcommunityws

    original_resolver = servertools.resolve_video_urls_for_playing
    original_bootstrap = getattr(streamingcommunityws, 'bootstrap_url', '')
    try:
        servertools.resolve_video_urls_for_playing = lambda *args, **kwargs: ([], False, '')
        streamingcommunityws.bootstrap_url = direct
        playback = bridge.resolve({
            'server': 'streamingcommunityws',
            'url': 'https://streamingcommunity.example/iframe/1?episode_id=2',
            'title': 'Episodio test',
        })
        assert playback['url'] == direct
        assert playback['bootstrap_url'] == direct
        assert playback['manifest_type'] == 'bootstrap'
        assert playback['server'] == 'streamingcommunityws'
    finally:
        servertools.resolve_video_urls_for_playing = original_resolver
        streamingcommunityws.bootstrap_url = original_bootstrap

    print('OK: fallback SC accetta soltanto embed HTTP(S) VixCloud/worker')


if __name__ == '__main__':
    main()
