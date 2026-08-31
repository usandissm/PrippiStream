# -*- coding: utf-8 -*-
"""Regressioni del percorso sottotitoli resolver -> player -> download.

Usa lo stesso bridge Python incluso nell'APK, senza rete: verifica sia il
quarto campo storico dei resolver Kodi sia l'unione delle tracce esterne nel
master HLS preparato dal player Android.
"""
from __future__ import print_function

import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
PYROOT = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
sys.path.insert(0, PYROOT)

import bridge  # noqa: E402


def main():
    bridge.init()

    from core import servertools
    from platformcode import download_manager

    original_resolve = servertools.resolve_video_urls_for_playing
    original_media = download_manager._resolve_media
    original_get = download_manager._http_get
    try:
        servertools.resolve_video_urls_for_playing = lambda *args, **kwargs: (
            [['720p', 'https://media.example/video.mp4', 0,
              'https://media.example/sub.it.vtt']], True, '')
        playback = bridge.resolve({
            'server': 'resolver_di_test',
            'url': 'https://page.example/watch/1',
            'title': 'Test sottotitoli',
        })
        assert playback['subtitles'] == 'https://media.example/sub.it.vtt', playback

        master = '''#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720
video.m3u8
'''.encode('utf-8')
        download_manager._resolve_media = lambda *args, **kwargs: (
            'https://media.example/master.m3u8', 'hls', {})
        download_manager._http_get = lambda *args, **kwargs: master

        from core.item import Item
        item = Item(url='https://page.example/watch/1', channel='test')
        item._app_subtitle_urls = ['https://media.example/sub.it.vtt']
        tracks = download_manager.probe_tracks(item.url, channel='test', item=item)
        assert len(tracks.get('subtitles') or []) == 1, tracks
        subtitle = tracks['subtitles'][0]
        assert subtitle['url'].endswith('sub.it.vtt'), subtitle
        assert subtitle['language'] == 'it', subtitle
        assert subtitle['label'] == 'Italiano', subtitle
    finally:
        servertools.resolve_video_urls_for_playing = original_resolve
        download_manager._resolve_media = original_media
        download_manager._http_get = original_get

    print('OK resolver -> player: sottotitolo esterno conservato')
    print('OK player -> download HLS: traccia italiana conservata')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
