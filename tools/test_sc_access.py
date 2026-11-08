"""Offline integration gates for optional authorized SC and transparent free fallback."""
import io
import json
import sys
import time
import unittest
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
import sc_access

ENDPOINT = 'https://prippistream-sc-access.prippistream-profiles.workers.dev/v1/playback'
ITEM = {'channel': 'streamingcommunity', 'url': 'https://catalog.example/it/iframe/12?episode_id=34'}


class AccessTests(unittest.TestCase):
    def test_identifiers(self):
        self.assertEqual(sc_access.content_ids(ITEM), {'title_id': '12', 'episode_id': '34'})
        self.assertEqual(sc_access.content_ids(dict(ITEM, url='https://catalog.example/it/titles/12-title')), {'title_id': '12'})
        self.assertIsNone(sc_access.content_ids(dict(ITEM, channel='raiplay')))
        self.assertIsNone(sc_access.content_ids(dict(ITEM, _app_live=True)))
        self.assertIsNone(sc_access.content_ids(dict(ITEM, _app_event=True)))
        self.assertIsNone(sc_access.content_ids(dict(ITEM, url='https://catalog.example/it/iframe/12?episode_id=../2')))

    def test_fresh_authorized_source_no_account_to_client(self):
        embed = 'https://vixcloud.cc/embed/56?canPlayFHD=1&token=authorized&expires=' + str(int(time.time()+600))
        def opener(request, timeout):
            self.assertEqual(json.loads(request.data), {'title_id': '12', 'episode_id': '34'})
            self.assertEqual(timeout, 15)
            self.assertNotIn('Cookie', request.headers)
            return io.BytesIO(json.dumps({'available': True, 'embed_url': embed}).encode())
        result = sc_access.playback(ITEM, ENDPOINT, 'client-key', {'max_video_height': 720}, opener)
        self.assertEqual(result['bootstrap_url'], embed)
        self.assertEqual(result['max_video_height'], 720)
        self.assertTrue(result['fallback_enabled'])
        self.assertNotIn('client-key', json.dumps(result))

    def test_no_subscription_invalid_grant_and_network_error_all_fall_back(self):
        invalid = ['https://evil.org/embed/1?canPlayFHD=1',
                   'https://vixcloud.cc/embed/1?canPlayFHD=1&token=t&expires=1',
                   'https://vixcloud.cc/embed/1?canPlayFHD=0&token=t&expires=' + str(int(time.time()+600))]
        for embed in invalid:
            result = sc_access.playback(ITEM, ENDPOINT, 'key', {}, lambda *a, **k: io.BytesIO(json.dumps({'available': True, 'embed_url': embed}).encode()))
            self.assertEqual(result, {})
        self.assertEqual(sc_access.playback(ITEM, ENDPOINT, 'key', {}, lambda *a, **k: io.BytesIO(b'{"available":false}')), {})
        def failed(*args, **kwargs):
            raise TimeoutError('must not reach UI/logs')
        self.assertEqual(sc_access.playback(ITEM, ENDPOINT, 'key', {}, failed), {})

    def test_disabled_config_does_not_contact_service(self):
        def forbidden(*args, **kwargs):
            self.fail('unexpected request')
        self.assertEqual(sc_access.playback(ITEM, '', '', {}, forbidden), {})
        self.assertEqual(sc_access.playback(ITEM, 'https://evil.org/v1/playback', 'k', {}, forbidden), {})

    def test_lazy_free_candidate_and_existing_download_flow(self):
        player = (ROOT / 'app/src/main/java/com/prippi/stream/PlayerActivity.kt').read_text(encoding='utf-8')
        repository = (ROOT / 'app/src/main/java/com/prippi/stream/ContentRepository.kt').read_text(encoding='utf-8')
        self.assertIn('it.manifest == "sc_free_fallback" && it.scFreeFallbackJson.isNotBlank()', player)
        self.assertIn('PythonBridge.authorizedScPlayback(raw)', player)
        self.assertIn('else PythonBridge.resolve(raw)', player)
        self.assertIn('if (!isPlaybackGenerationActive(generation)) return@runOnUiThread', player)
        self.assertIn('PythonBridge.authorizedScCandidate(raw)', repository)
        self.assertNotIn('PythonBridge.authorizedScPlayback(raw)', repository)

    def test_authorization_is_lazy_and_has_no_account_data(self):
        sc_access.configure('', '')
        self.assertEqual(sc_access.candidate(ITEM, {}), {})
        sc_access.configure(ENDPOINT, 'client-key')
        result = sc_access.candidate(ITEM, {'max_video_height': 720})
        self.assertEqual(result['manifest_type'], 'sc_authorized')
        self.assertEqual(result['max_video_height'], 720)
        self.assertNotIn('client-key', json.dumps(result))

    def test_download_manifest_uses_only_actual_grant(self):
        html = "window.masterPlaylist = { params: {'token':'fresh','expires':'9999999999'}, url: 'https://vixcloud.cc/playlist/56' }; window.canPlayFHD = true; window.streams = [{\"active\":true,\"url\":\"https://vixcloud.cc/playlist/56?ub=1&h=0\"}];"
        url = sc_access.playlist_from_embed('https://vixcloud.cc/embed/56', html)
        self.assertIn('h=1', url)
        self.assertIn('ub=1', url)
        self.assertEqual(sc_access.playlist_from_embed('https://vixcloud.cc/embed/56', html.replace('= true', '= false')), '')

    def test_partial_download_never_changes_rendition(self):
        existing = SimpleNamespace(_app_sc_download_height=1080)
        sc_access.validate_download_variant(existing, {'height':1080})
        with self.assertRaisesRegex(RuntimeError, 'parziale è conservato'):
            sc_access.validate_download_variant(existing, {'height':720})
        self.assertEqual(sc_access.locked_download_height(SimpleNamespace()), 0)


if __name__ == '__main__':
    unittest.main()
