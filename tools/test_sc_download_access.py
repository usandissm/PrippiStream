"""Exercise the actual download adapters with isolated DB/network substitutes."""
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))
import sc_access
import bridge
import test_download_state as fixtures

manager_module = fixtures.manager_module
fixtures.platformcode.download_manager = manager_module
fixtures.core.servertools = types.ModuleType('core.servertools')


class DownloadAccessTests(unittest.TestCase):
    def test_legacy_prepared_download_never_contacts_new_service(self):
        item = fixtures.FakeItem(90)
        item._app_media_url = 'https://existing.example/master.m3u8'
        item._app_media_headers = {'Referer': 'existing'}
        with patch.object(sc_access, 'download_media', side_effect=AssertionError('legacy modified')):
            self.assertEqual(manager_module._resolve_media(item.url, item.channel, item),
                             (item._app_media_url, 'hls', item._app_media_headers))

    def test_only_delayed_or_expired_new_download_gets_fresh_authorization(self):
        item = fixtures.FakeItem(91)
        item._app_sc_access_download = True
        item._app_media_url = 'https://prepared.example/master.m3u8'
        item._app_media_prepared_at = time.time()
        with patch.object(sc_access, 'download_media', return_value=('https://fresh.example/master.m3u8', {})) as renew:
            self.assertEqual(manager_module._resolve_media(item.url, item.channel, item)[0], item._app_media_url)
            renew.assert_not_called()
            item._app_media_prepared_at = 0
            self.assertEqual(manager_module._resolve_media(item.url, item.channel, item)[0], 'https://fresh.example/master.m3u8')
            renew.assert_called_once()

    def test_refresh_preserves_download_height_not_current_best(self):
        item = fixtures.FakeItem(92)
        item._app_sc_access_download = True
        item._app_sc_download_height = 720
        manager = manager_module.DownloadManager()
        job = {'item': item, 'target_height': 0}
        info = {'variants':[{'height':1080,'url':'new1080'}, {'height':720,'url':'same720'}], 'headers':{'Referer':'fresh'}}
        with patch.object(manager_module, 'probe_tracks', return_value=info):
            self.assertEqual(manager._fresh_url(job, 'video', 0)[0], 'same720')
        item._app_sc_download_height = 1080
        with patch.object(manager_module, 'probe_tracks', return_value=dict(info, variants=[{'height':720,'url':'lower'}])):
            with self.assertRaisesRegex(RuntimeError, 'parziale è conservato'):
                manager._fresh_url(job, 'video', 0)

    def test_completed_and_old_partial_are_not_replaced_by_new_source(self):
        old = {'key':'existing','status':'done','item_url':'original-source'}
        with patch.object(bridge, 'init'), patch.object(bridge, '_to_item', return_value=object()), \
             patch.object(manager_module, '_entry_from_item', return_value={'key':'existing'}), \
             patch.object(fixtures.downloads_db, 'get', return_value=old), \
             patch.object(bridge, 'download_enqueue') as enqueue, patch.object(bridge, 'download_resume', return_value=old) as resume:
            self.assertEqual(bridge.download_enqueue_resolved({}, 'new-source'), old)
            enqueue.assert_not_called()
            resume.assert_not_called()
            old['status'] = 'paused'
            bridge.download_enqueue_resolved({}, 'new-source')
            resume.assert_called_once_with('existing')
            self.assertEqual(old['item_url'], 'original-source')

    def test_new_entry_opt_in_keeps_account_credentials_out(self):
        sc_access.configure('https://prippistream-sc-access.prippistream-profiles.workers.dev/v1/playback','client-key')
        item = {'channel':'streamingcommunity', 'url':'https://catalog.example/it/iframe/12'}
        with patch.object(bridge, 'init'), patch.object(bridge, '_to_item', return_value=object()), \
             patch.object(manager_module, '_entry_from_item', return_value={'key':'new'}), \
             patch.object(fixtures.downloads_db, 'get', return_value=None), \
             patch.object(bridge, 'download_enqueue', side_effect=lambda data, height: data):
            prepared = bridge.download_enqueue_resolved(item, 'https://video.example/master.m3u8')
            self.assertTrue(prepared['_app_sc_access_download'])
            self.assertGreater(prepared['_app_media_prepared_at'], 0)
            self.assertNotIn('client-key', str(prepared))


if __name__ == '__main__':
    unittest.main()
