"""Focused SC resolver regressions; --live also probes one current episode.
No Kodi state, cookies, DNS settings, or real playback progress is modified.
"""
import html
import importlib.util
from pathlib import Path
import re
import ssl
import sys
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36'
core = types.ModuleType('core')
core.httptools = types.SimpleNamespace(default_headers={'User-Agent': UA, 'Accept-Encoding': 'gzip'})
core.filetools = types.SimpleNamespace()
core.support = types.SimpleNamespace(scrapertools=types.SimpleNamespace(decodeHtmlentities=html.unescape))
platformcode = types.ModuleType('platformcode')
platformcode.logger = types.SimpleNamespace(info=lambda *a: None, error=lambda *a: None, debug=lambda *a: None)
platformcode.config = types.SimpleNamespace()
xbmc = types.SimpleNamespace(getInfoLabel=lambda value: '21.3')
spec = importlib.util.spec_from_file_location('sc_test_connector', ROOT / 'servers/streamingcommunityws.py')
sc = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'core': core, 'platformcode': platformcode, 'xbmc': xbmc}):
    spec.loader.exec_module(sc)

EMBED = 'https://vixcloud.example/embed/2?scz=1&b=2'
HTML = """window.masterPlaylist = { params: {'token': 'fresh', 'expires': '123'},
url: 'https://video.example/playlist/2', }; window.canPlayFHD = true;
window.streams = [{"active":true,"url":"https://video.example/playlist/active?quality=high"}];"""


class ResolverTests(unittest.TestCase):
    def setUp(self):
        core.support.match = lambda *a, **kw: types.SimpleNamespace(match=EMBED)

    def test_resolution_preserves_active_stream_and_signed_parameters(self):
        with patch.object(sc, '_player_page', return_value=HTML) as fetch:
            self.assertEqual((True, ''), sc.test_video_exists('https://catalog.example/iframe/1'))
        fetch.assert_called_once_with(EMBED, 'https://catalog.example/iframe/1')
        url = sc.get_video_url('unused')[0][1]
        self.assertEqual('/playlist/active', urllib.parse.urlsplit(url).path)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(['fresh'], query['token'])
        self.assertEqual(['1'], query['scz'])
        self.assertEqual(['2'], query['b'])
        self.assertEqual(['1'], query['h'])

    def test_403_is_not_future_content_and_clears_previous_episode(self):
        with patch.object(sc, '_player_page', return_value=HTML):
            sc.test_video_exists('https://catalog.example/iframe/1')
        failure = urllib.error.HTTPError(EMBED, 403, 'Forbidden', {}, None)
        with patch.object(sc, '_player_page', side_effect=failure):
            ok, message = sc.test_video_exists('https://catalog.example/iframe/2')
        self.assertIs(ok, False)
        self.assertIn('403', message)
        self.assertNotIn('Prossimamente', message)
        self.assertEqual([], sc.get_video_url('unused'))
        self.assertEqual('', sc.activeStreamUrl)

    def test_unrecognized_html_is_not_future_content(self):
        with patch.object(sc, '_player_page', return_value='<html>Player cambiato</html>'):
            ok, message = sc.test_video_exists('https://catalog.example/iframe/1')
        self.assertIs(ok, False)
        self.assertIn('non riconosciuta', message)

    def test_transport_keeps_tls_verification_and_episode_referrer(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = HTML.encode()
        response.headers = {}
        response.getcode.return_value = 200
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(sc.urllib.request, 'build_opener', return_value=opener) as factory:
            self.assertEqual(HTML, sc._player_page(EMBED, 'https://catalog.example/episode'))
        self.assertEqual(ssl.CERT_REQUIRED, factory.call_args.args[0]._context.verify_mode)
        request = opener.open.call_args.args[0]
        self.assertEqual('https://catalog.example/episode', request.get_header('Referer'))
        self.assertEqual('identity', request.get_header('Accept-encoding'))


def live_probe():
    page = 'https://streamingcommunityz.boo/it/iframe/66295?episode_id=371886'
    headers = {'User-Agent': UA, 'Referer': 'https://streamingcommunityz.boo/'}
    with urllib.request.urlopen(urllib.request.Request(page, headers=headers), timeout=15) as response:
        body = response.read(1024 * 1024).decode('utf-8')
    embed = html.unescape(re.search(r'<iframe[^>]+src=["\x27]([^"\x27]+)', body).group(1))
    core.support.match = lambda *a, **kw: types.SimpleNamespace(match=embed)
    ok, message = sc.test_video_exists(page)
    print('LIVE resolver:', ok, message)
    if not ok:
        raise SystemExit(1)
    playlist = sc.get_video_url(page)[0][1]
    print('LIVE playlist host:', urllib.parse.urlsplit(playlist).hostname)
    request = urllib.request.Request(playlist, headers={'User-Agent': UA, 'Referer': embed})
    with urllib.request.urlopen(request, timeout=15) as response:
        manifest = response.read(2 * 1024 * 1024).decode('utf-8')
        print('LIVE manifest: HTTP', response.status, 'HLS=', manifest.startswith('#EXTM3U'))
    if not manifest.startswith('#EXTM3U'):
        raise SystemExit(1)


if __name__ == '__main__':
    live = '--live' in sys.argv
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if live:
        live_probe()
