"""Offline startup/whole-calendar regression tests against workspace source."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('platformcode')
pkg.__path__ = [str(ROOT / 'platformcode')]
pkg.config = types.SimpleNamespace(get_data_path=lambda: tempfile.gettempdir(),
                                   get_runtime_path=lambda: str(ROOT))
sys.modules['platformcode'] = pkg
def load(name):
    spec = importlib.util.spec_from_file_location('platformcode.' + name, ROOT / ('platformcode/' + name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    setattr(pkg, name, module)
    spec.loader.exec_module(module)
    return module
time = load('eventtime')
art = load('eventpresentation')
pool = load('taskpool')
cal = load('eventcalendar')
availability = load('eventavailability')
pkg.eventresolver = types.SimpleNamespace(resolve=lambda *args, **kwargs: [])


class StartupTest(unittest.TestCase):
    def setUp(self):
        cal._SOURCE_RESULTS.clear()

    def test_only_italian_serie_a(self):
        events = [dict(league=league, calendar_url='https://example.invalid/' + str(i))
                  for i, league in enumerate(('Italia. Serie A', 'Serie A', 'Brasile. Serie A', 'Italia. Serie B'))]
        with patch.object(cal, 'merge', return_value=events), patch.object(cal, 'verify_event', return_value='available') as verify:
            cal.precheck_serie_a([])
        self.assertEqual(2, verify.call_count)

    def test_uses_today_filtered_merge(self):
        with patch.object(cal, 'merge', return_value=[]) as merge:
            cal.precheck_serie_a([{'date': 'tomorrow'}])
        merge.assert_called_once_with([{'date': 'tomorrow'}])

    def test_cancelled_no_probe(self):
        with patch.object(cal, 'merge', return_value=[dict(league='Serie A')]), patch.object(cal, 'verify_event') as verify:
            cal.precheck_serie_a([], active=lambda: False)
        verify.assert_not_called()

    def test_verified_result_not_probed_twice(self):
        event = dict(calendar_url='https://example.invalid/a', sources=[])
        with patch.object(cal, 'sources', return_value=[]), patch.object(availability, 'check', return_value=True) as check:
            self.assertEqual('available', cal.verify_event(event))
            self.assertEqual('available', cal.verify_event(event))
        self.assertEqual(1, check.call_count)

    def test_primary_survives_calendar_failure(self):
        event = dict(calendar_url='https://example.invalid/a', sources=[dict(kind='hls', url='https://example.invalid/media')])
        with patch.object(cal, 'sources', side_effect=OSError), patch.object(availability, 'check', return_value=True) as check:
            self.assertEqual('available', cal.verify_event(event))
        self.assertEqual(event['sources'], check.call_args.args[0])

    def test_cancelled_removes_pending(self):
        event = dict(calendar_url='https://example.invalid/a', sources=[])
        alive = [True]
        def check(*args, **kwargs):
            alive[0] = False
            return None
        with patch.object(cal, 'sources', return_value=[]), patch.object(availability, 'check', side_effect=check):
            cal.verify_event(event, active=lambda: alive[0])
        self.assertIsNone(cal.verified_state(event['calendar_url']))

    def test_all_calendar_days_artwork(self):
        events = [dict(teams='Past vs Other', date='01/01/2020'),
                  dict(teams='Future vs Club', date='01/01/2030'), dict(teams='Multigol')]
        with patch.object(pool, 'map_background') as work:
            art.warm_badges(events)
        self.assertEqual(['Club', 'Future', 'Other', 'Past'], work.call_args.args[1])
        self.assertEqual(3, work.call_args.kwargs['workers'])

    def test_parent_and_localized_alias(self):
        with patch.object(art, '_cached_badge', side_effect=lambda key: '/badge.png' if key == __import__('hashlib').sha256(b'bayernmunich').hexdigest()[:24] else ''):
            self.assertEqual('/badge.png', art.badge('Bayern Monaco (D)'))


if __name__ == '__main__':
    unittest.main()
