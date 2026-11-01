"""Deterministic EPG publication checks for both engines. No network."""
import importlib.util
import json
from pathlib import Path
import runpy
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / 'tools/test_live_events.py'), run_name='epg_setup')
from core.item import Item

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

class GateTest(unittest.TestCase):
    def engines(self):
        for directory in (ROOT / 'app/src/main/python/engine/platformcode', ROOT.parent / 'Kodi/platformcode'):
            epg = module('tested_epg', directory / 'skyepg.py')
            gate = module('tested_gate', directory / 'liveepg.py')
            gate.skyepg = epg
            yield epg, gate

    def test_no_guide_releases_after_bounded_wait(self):
        for epg, gate in self.engines():
            items = [Item(title='Channel', sport_par='channel')]
            with patch.object(epg, 'prefetch'), patch.object(epg, 'now_on', return_value=None), patch.object(gate, 'WAIT_SECONDS', 0.03):
                start = time.monotonic()
                self.assertTrue(gate.wait(items))
                self.assertLess(time.monotonic() - start, 0.3)
                self.assertGreaterEqual(time.monotonic() - start, 0.03)

    def test_fresh_cache_releases_immediately(self):
        for epg, gate in self.engines():
            with patch.object(epg, 'prefetch'), patch.object(epg, 'now_on', return_value={'prog': 'Now'}):
                self.assertTrue(gate.ready([Item(title='Channel')]))

    def test_cancel_does_not_block_or_publish(self):
        for epg, gate in self.engines():
            with patch.object(epg, 'prefetch'):
                self.assertFalse(gate.wait([Item(title='Channel')], active=lambda: False))

    def test_late_rows_are_not_lost_to_global_cooldown(self):
        for epg, gate in self.engines():
            batches = []
            def fetch(keys):
                batches.append(set(keys))
                if keys == ['sky']:
                    epg.prefetch(['sport'])
                return 0
            with patch.object(epg, '_prefetch', side_effect=fetch), patch.object(epg, '_save_epg_disk'):
                epg.prefetch(['sky'])
                epg.prefetch(['sky'])
                epg.prefetch(['tv'])
            self.assertEqual([{'sky'}, {'sport'}, {'tv'}], batches)
            self.assertTrue(epg.attempted(['sky', 'sport', 'tv']))

    def test_failure_counts_as_attempt_and_does_not_hide_row(self):
        for epg, gate in self.engines():
            with patch.object(epg, '_prefetch', side_effect=OSError('offline')), patch.object(epg, '_save_epg_disk'):
                epg.prefetch(['channel'])
            with patch.object(epg, 'prefetch'), patch.object(epg, 'now_on', return_value=None):
                self.assertTrue(gate.ready([Item(title='channel')]))

    def test_persistent_cache_discards_expired_programmes(self):
        for epg, gate in self.engines():
            with tempfile.TemporaryDirectory() as directory, patch.object(epg.config, 'get_data_path', return_value=directory):
                path = Path(directory) / 'live_epg_programmes.json'
                path.write_text(json.dumps({epg._norm('old'): {'prog': 'Old', 'until': 1},
                    epg._norm('new'): {'prog': 'New', 'until': time.time()+60, 'start':'12:00', 'end':'14:00', 'synopsis':''}}))
                self.assertIsNone(epg.now_on('old'))
                self.assertEqual('New', epg.now_on('new')['prog'])

if __name__ == '__main__':
    unittest.main()
