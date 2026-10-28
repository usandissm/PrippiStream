"""Android bridge integration checks; no live services, player or real accounts."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
import bridge
DATA = tempfile.TemporaryDirectory()
bridge.init(runtime_dir=str(ROOT / 'app/src/main/assets/pydata'), data_dir=DATA.name)
from platformcode import (appevents as a, eventcalendar as c, eventpresentation as art,
                          eventtime, sportchannels as sport, mediahosting, iptv_pool)


class LiveEventsTest(unittest.TestCase):
    def fixture(self, **extra):
        value = dict(date=eventtime.now_rome().strftime('%d/%m/%Y'), time='23:55',
                     teams='Inter vs Bologna', league='Italia. Serie A',
                     calendar_url='https://example.invalid/fixture', sources=[])
        value.update(extra)
        return value

    def test_copied_modules_match_kodi(self):
        kodi = ROOT.parent / 'Kodi/platformcode'
        for name in ('eventcalendar', 'eventavailability', 'eventpresentation', 'eventartnet',
                     'eventresolver', 'eventquality', 'eventtime', 'tgevents', 'taskpool', 'mediahosting'):
            self.assertEqual((kodi / (name + '.py')).read_bytes(),
                             (ROOT / ('app/src/main/python/engine/platformcode/' + name + '.py')).read_bytes(), name)

    def test_no_iptv_pool_or_row(self):
        self.assertFalse(sport.IPTV_LIVE_ENABLED)
        self.assertFalse(iptv_pool.IPTV_POOL_ENABLED)
        with patch.object(sport, 'get_channels', return_value=[dict(kind='iptv', title='Old', par='x')]), \
                patch.object(sport, 'row_ready', return_value=True):
            self.assertEqual([], sport.build_items('sport'))
        with self.assertRaises(RuntimeError):
            bridge.resolve_live_attempt({'sport_kind': 'iptv'})

    def test_mh_first_and_original_priorities_untouched(self):
        rows = [dict(kind='sky', par='sport1', title='Sky Sport 1'),
                dict(kind='mediahosting', par='dazn_mh', title='DAZN [MH]', source_code='24')]
        with patch.object(sport, 'get_channels', return_value=rows), patch.object(sport, 'row_ready', return_value=True):
            items = sport.build_items('sport')
        self.assertEqual(['DAZN', 'Sky Sport 1'], [i.title for i in items])
        self.assertEqual('24', items[0].sport_source_code)

    def test_mh_requires_probe_success(self):
        channel = dict(kind='mediahosting', par='dazn_mh', source_code='24')
        with patch.object(mediahosting, 'online', return_value=False):
            self.assertFalse(sport._channel_token_valid(channel))
        with patch.object(mediahosting, 'online', return_value=True):
            self.assertTrue(sport._channel_token_valid(channel))
        self.assertEqual('mediahosting', channel['_validated_route'])

    def test_today_rows_and_file_badge_uris(self):
        with patch.object(c, 'cached', return_value=[self.fixture()]), patch.object(a, '_events', return_value=[]):
            items = a.build_items()
        self.assertEqual(1, len(items))
        payload = bridge._from_item(items[0])
        self.assertTrue(payload['_app_event'])
        self.assertTrue(payload['event_home_badge'].startswith('file:///'))
        self.assertTrue(payload['event_away_badge'].startswith('file:///'))
        self.assertEqual('event_play', payload['action'])
        self.assertTrue(payload['event_id'])

    def test_tomorrow_and_ace_only_not_in_row(self):
        from datetime import timedelta
        tomorrow = (eventtime.now_rome() + timedelta(days=1)).strftime('%d/%m/%Y')
        ace = self.fixture(calendar_url='', sources=[dict(url='acestream://abc', kind='ace')])
        with patch.object(c, 'cached', return_value=[self.fixture(date=tomorrow), ace]), patch.object(a, '_events', return_value=[]):
            self.assertEqual([], a.build_items())

    def test_refresh_cooldown_counts_failed_attempts(self):
        path = Path(DATA.name) / 'app_events_attempt.json'
        path.unlink(missing_ok=True)
        with patch.object(a.tgevents, 'cache_age', return_value=None), patch.object(a.tgevents, 'fetch_events', return_value=None) as fetch:
            a._refresh_sources_if_due()
            a._refresh_sources_if_due()
        self.assertEqual(1, fetch.call_count)

    def test_live_order_and_events_not_passed_to_epg(self):
        from core.item import Item
        event = Item(title='Game', action='event_play', infoLabels={'plot': 'status'})
        event._app_event = True
        with patch.object(sport, 'build_items', side_effect=lambda key: [Item(title=key)]), \
                patch.object(a, 'build_items', return_value=[event]), patch.object(a, 'start_refresh'), \
                patch('platformcode.skyepg.prefetch'), patch('platformcode.skyepg.now_on', return_value=None):
            bridge._LIVE_LOADING = True
            rows = bridge.live_rows()
        self.assertEqual(['live_sky', 'live_sport', 'live_events', 'live_tv'], [r['id'] for r in rows])
        self.assertEqual('EVENTI', rows[2]['title'])

    def test_offline_first_source_tries_next_with_headers(self):
        sources = [dict(url='https://example.invalid/off.m3u8', kind='hls'),
                   dict(url='https://example.invalid/on.m3u8', kind='hls', headers={'Referer': 'https://example.invalid/'})]
        item = dict(event_fixture=self.fixture(), event_calendar_url='https://example.invalid/fixture', _tg_event_sources=sources)
        original = a.eventquality.prepare
        def rank(values, resolve, **kwargs):
            return original(values, resolve, probe=lambda path: (1080, 5000), **kwargs)
        with patch.object(c, 'merge', return_value=[]), patch.object(c, 'sources', return_value=[]), \
                patch.object(a.eventquality, 'prepare', side_effect=rank), \
                patch.object(a.eventavailability, 'hls_reachable', side_effect=lambda v, **kw: '/on.' in v['url']):
            candidates = a.playback_candidates(item)
        self.assertEqual(1, len(candidates))
        self.assertIn('/on.', candidates[0]['url'])
        self.assertEqual(sources[1]['headers'], candidates[0]['headers'])

    def test_expired_card_not_played(self):
        self.assertEqual([], a.playback_candidates(dict(event_fixture=self.fixture(date='01/01/2000'))))


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        DATA.cleanup()
