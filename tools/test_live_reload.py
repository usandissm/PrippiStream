"""Manual Live refresh is single-flight and leaves downloaded files untouched."""
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

s = runpy.run_path(str(Path(__file__).with_name('test_live_events.py')), run_name='reload_setup')
b, a = s['bridge'], s['a']
from platformcode import skyepg, liveepg

class ReloadTest(unittest.TestCase):
    def tearDown(self):
        b._LIVE_LOADING = False

    def test_repeated_click_joins_existing_worker(self):
        b._LIVE_LOADING = False
        with patch.object(skyepg, 'invalidate_requests') as invalidate, patch.object(liveepg, 'reset'), \
                patch.object(a, 'start_refresh') as events, patch.object(b.threading, 'Thread') as thread:
            self.assertTrue(json.loads(b.reload_live_json())['started'])
            self.assertFalse(json.loads(b.reload_live_json())['started'])
            thread.return_value.start.assert_called_once()
            invalidate.assert_called_once()
            events.assert_called_once_with(force=True)

    def test_failed_start_does_not_leave_live_permanently_loading(self):
        b._LIVE_LOADING = False
        with patch.object(skyepg, 'invalidate_requests', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):
                b.reload_live_json()
        self.assertFalse(b._LIVE_LOADING)

    def test_status_waits_for_channels_and_event_metadata(self):
        for channels, events in ((False,False), (True,False), (False,True)):
            b._LIVE_LOADING = channels
            with patch.object(a, 'refreshing', return_value=events):
                self.assertEqual(channels or events, json.loads(b.live_refresh_status_json())['refreshing'])

    def test_guide_invalidation_keeps_valid_programme_fallback(self):
        old = dict(skyepg._epg_cache)
        skyepg._epg_cache['test'] = {'prog': 'Current'}
        skyepg._key_attempts['test'] = 123
        try:
            skyepg.invalidate_requests()
            self.assertFalse(skyepg._key_attempts)
            self.assertEqual('Current', skyepg._epg_cache['test']['prog'])
        finally:
            skyepg._epg_cache.clear()
            skyepg._epg_cache.update(old)

if __name__ == '__main__':
    unittest.main()
