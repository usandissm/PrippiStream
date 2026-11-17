"""Catalog access and offer filtering without reaching the live service."""
import io
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

setup = runpy.run_path(str(Path(__file__).with_name('test_live_events.py')), run_name='catalog_setup')
from platformcode import live_catalog as catalog, live_iptv_direct_local as slot


class LiveCatalogTest(unittest.TestCase):
    def setUp(self):
        self.data = Path(setup['DATA'].name)
        self.token = self.data / 'live-catalog.token'
        self.baseline = dict(catalog.STATE)
        self.addCleanup(catalog.STATE.update, self.baseline)
        self.addCleanup(self.token.unlink, missing_ok=True)

    def test_no_config_does_not_request_catalog(self):
        with patch.object(catalog, 'build_opener') as opener:
            catalog._refresh()
        opener.assert_not_called()
        self.assertEqual(('not_configured',), catalog.STATE['status'])

    def test_rejected_config_is_distinct_from_empty_catalog(self):
        self.token.write_text('A' * 43, encoding='ascii')
        unauthorized = HTTPError('', 401, '', {}, io.BytesIO(b''))
        with patch.object(catalog, 'build_opener') as opener:
            opener.return_value.open.side_effect = unauthorized
            catalog._refresh()
        self.assertEqual(('http', 401), catalog.STATE['status'])

    def test_dashboard_channel_available_with_play_access(self):
        self.token.write_text('A' * 43, encoding='ascii')
        channel = dict(group='sky', route='iptv', id='family_skycinemadue',
                       title='Sky Cinema Due', code='family_skycinemadue')
        payload = dict(version=1, channels=[channel], rules={})
        with patch.object(catalog, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(payload)
            catalog._refresh()
        self.assertEqual(('ok', 1), catalog.STATE['status'])
        with patch.object(slot, 'play_token', return_value='B' * 43), patch.object(slot, 'device_hidden', return_value=False):
            item, = catalog.online_rows('sky')
        self.assertEqual('iptv_vm', item['kind'])
        self.assertEqual(channel['id'], item['par'])

    def test_pending_device_keeps_existing_access_until_approval(self):
        pending = self.data / 'live-device.pending.token'
        active = self.data / 'live-device.token'
        pending.write_text('B' * 43, encoding='ascii')
        self.addCleanup(pending.unlink, missing_ok=True)
        self.addCleanup(active.unlink, missing_ok=True)
        self.token.write_text('A' * 43, encoding='ascii')
        with patch.object(catalog, 'build_opener') as opener:
            context = opener.return_value.open.return_value
            context.__enter__.return_value.read.return_value = '{"version":1,"rules":{},"channels":[]}'
            opener.return_value.open.side_effect = [HTTPError('', 401, '', {}, io.BytesIO()), context]
            catalog._refresh()
            self.assertTrue(pending.is_file())
            self.assertFalse(active.exists())
            opener.return_value.open.side_effect = None
            catalog._refresh()
        self.assertFalse(pending.exists())
        self.assertEqual('B' * 43, slot.play_token())


if __name__ == '__main__':
    unittest.main()
