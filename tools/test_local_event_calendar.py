"""Offline calendar tests; optional --refresh downloads calendar metadata only."""
import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime

ROOT = os.path.join(os.environ['APPDATA'], 'Kodi', 'addons', 'plugin.video.prippistream')
DATA = os.path.join(os.environ['APPDATA'], 'Kodi', 'userdata', 'addon_data', 'plugin.video.prippistream')
package = types.ModuleType('platformcode')
package.config = types.SimpleNamespace(get_data_path=lambda: DATA)
sys.modules['platformcode'] = package


def load(name):
    spec = importlib.util.spec_from_file_location('platformcode.' + name, os.path.join(ROOT, 'platformcode', name + '.py'))
    module = importlib.util.module_from_spec(spec)
    setattr(package, name, module)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


eventtime = load('eventtime')
art = load('eventpresentation')
calendar = load('eventcalendar')


class CalendarTest(unittest.TestCase):
    def test_winter_source_clock_is_converted_to_italy(self):
        event = eventtime.normalize_calendar(self.fixture(time='15:30'))
        self.assertEqual('14:30', event['time'])
        self.assertEqual('2026-10-27T13:30:00Z', event['start_utc'])
        self.assertEqual('Europe/Rome', event['timezone'])

    def test_summer_and_day_rollover(self):
        self.assertEqual('15:30', eventtime.normalize_calendar(self.fixture(date='27/07/2026', time='15:30'))['time'])
        event = eventtime.normalize_calendar(self.fixture(time='00:30'))
        self.assertEqual(('26/10/2026', '23:30'), (event['date'], event['time']))

    def test_conversion_idempotent_including_cache(self):
        event = eventtime.normalize_calendar(self.fixture(time='15:30'))
        self.assertEqual(event, eventtime.normalize_calendar(event))

    def test_dst_transition_is_based_on_the_event_instant(self):
        from datetime import timedelta
        self.assertEqual(datetime(2026, 10, 25, 2, 59), eventtime.rome_from_utc(datetime(2026, 10, 25, 0, 59)))
        self.assertEqual(datetime(2026, 10, 25, 2), eventtime.rome_from_utc(datetime(2026, 10, 25, 1)))
        self.assertEqual(datetime(2026, 3, 29, 1, 59), eventtime.rome_from_utc(datetime(2026, 3, 29, 0, 59)))
        self.assertEqual(datetime(2026, 3, 29, 3), eventtime.rome_from_utc(datetime(2026, 3, 29, 1)))

    def test_country_never_changes_source_timezone(self):
        for league in ('Italia. Serie A', 'Inghilterra. Coppa di Lega', 'Indonesia. Liga 1'):
            self.assertEqual('21:00', eventtime.normalize_calendar(self.fixture(time='22:00', league=league))['time'])

    def test_calibration_fixtures_italy_england_portugal(self):
        for source, expected in [('15:30', '14:30'), ('19:30', '18:30'),
                                 ('22:00', '21:00'), ('22:15', '21:15')]:
            self.assertEqual(expected, eventtime.normalize_calendar(self.fixture(time=source))['time'])

    def test_old_and_normalized_clocks_can_merge_sources_without_duplicate(self):
        original = self.fixture(time='15:30')
        normalized = eventtime.normalize_calendar(original)
        source = self.fixture(time='15:30', date='', calendar_url='',
                              sources=[dict(kind='web', url='https://example.invalid/play')])
        events = calendar.merge([source], [normalized], now=datetime(2026, 10, 27, 12))
        self.assertEqual(1, len(events))
        self.assertEqual('14:30', events[0]['time'])
        self.assertEqual(1, len(events[0]['sources']))

    def test_country_prefix_does_not_hide_available_primary_sources(self):
        source = self.fixture(league='Serie A', date='', time='18:30',
                              sources=[dict(kind='web', url='https://example.invalid/play')])
        fixture = self.fixture(league='Italia. Serie A', time='18:30')
        result = calendar.merge([source], [fixture], now=datetime(2026, 10, 27, 12))
        self.assertEqual(1, len(result))
        self.assertEqual(1, len(result[0]['sources']))
        self.assertNotEqual(art.competition_key('Brasile. Serie A'), art.competition_key('Serie A'))

    def test_dynamic_event_status(self):
        fixture = self.fixture(time='14:30')
        self.assertIn('PROSSIMAMENTE', art.event_status(fixture, datetime(2026, 10, 27, 12), available=False))
        self.assertIn('Sorgente non disponibile', art.event_status(fixture, datetime(2026, 10, 27, 12), available=False))
        ready = art.event_status(fixture, datetime(2026, 10, 27, 12), available=True)
        self.assertNotIn('PROSSIMAMENTE', ready)
        self.assertIn('Sorgente Disponibile', ready)
        self.assertIn('TRA POCO', art.event_status(fixture, datetime(2026, 10, 27, 14, 15), available=False))
        self.assertIn('ORA IN PROGRAMMA', art.event_status(fixture, datetime(2026, 10, 27, 14, 30), available=False))
        self.assertNotIn('IN ONDA', art.event_status(fixture, datetime(2026, 10, 27, 14, 30), available=False))
        self.assertIn('IN ONDA', art.event_status(fixture, datetime(2026, 10, 27, 14, 30), playing=True))

    def test_metadata_availability_cache(self):
        from unittest.mock import patch
        route = 'https://example.invalid/test-source-state'
        doc = {'items': [{'link': 'https://example.invalid/channel.m3u8'}]}
        with patch.object(calendar, '_get', return_value=doc) as request:
            self.assertIsNone(calendar.source_state(route))
            calendar.sources(route)
            self.assertTrue(calendar.source_state(route))
            calendar.sources(route)
            self.assertEqual(1, request.call_count)
            calendar.sources(route, force=True)
            self.assertEqual(2, request.call_count)

    def test_hostless_iframe_player_uses_published_cdn_origin(self):
        from unittest.mock import patch
        route = 'https://example.invalid/hostless-player'
        doc = {'items': [{'myresolve': 'lvtv@@https://webplayer.php?t=ifr&c=3093088',
                          'thumbnail': 'https://cdn.livetv907.me/img/linkflag/12.png'}]}
        with patch.object(calendar, '_get', return_value=doc):
            values = calendar.sources(route, force=True)
        self.assertEqual('https://cdn.livetv907.me/webplayer.php?t=ifr&c=3093088', values[0]['url'])
        self.assertFalse(values[0]['calendar_embed'])

    def test_hostless_player_without_a_trusted_origin_not_available(self):
        from unittest.mock import patch
        doc = {'items': [{'myresolve': 'lvtv@@https://webplayer.php?t=ifr&c=1',
                          'thumbnail': 'https://example.invalid/flag.png'}]}
        with patch.object(calendar, '_get', return_value=doc):
            self.assertEqual([], calendar.sources('https://example.invalid/no-origin', force=True))

    def test_alieztv_still_uses_dedicated_embed_resolver(self):
        from unittest.mock import patch
        doc = {'items': [{'myresolve': 'lvtv@@https://webplayer2.php?t=alieztv&c=12345'}]}
        with patch.object(calendar, '_get', return_value=doc):
            values = calendar.sources('https://example.invalid/alieztv', force=True)
        self.assertTrue(values[0]['calendar_embed'])
        self.assertIn('id=12345', values[0]['url'])

    def test_failed_resolution_overrides_published_link_status(self):
        from unittest.mock import patch
        route = 'https://example.invalid/failed-event'
        event = self.fixture(calendar_url=route, sources=[dict(kind='web', url='https://example.invalid/play')])
        calendar.report_source_result(route, False)
        self.assertTrue(calendar.source_failed(route))
        self.assertIn('Sorgente non disponibile', art.event_status(event, datetime(2026, 10, 27, 18)))
        calendar.report_source_result(route, True)
        self.assertFalse(calendar.source_failed(route))
        self.assertIn('Sorgente Disponibile', art.event_status(event, datetime(2026, 10, 27, 18)))
        calendar.report_source_result(route, False)
        with patch.object(calendar.time, 'time', return_value=calendar._SOURCE_RESULTS[route]['ts'] + 121):
            self.assertFalse(calendar.source_failed(route))

    def test_published_candidate_never_implies_verified_availability(self):
        from unittest.mock import patch
        route = 'https://example.invalid/unverified-status'
        event = self.fixture(calendar_url=route, sources=[dict(kind='hls', url='https://example.invalid/live.m3u8')])
        with patch.object(calendar, '_get', return_value={'items': [{'link': event['sources'][0]['url']}]}):
            calendar.sources(route)
        text = art.event_status(event, datetime(2026, 10, 27, 18))
        self.assertIn('Sorgente da verificare', text)
        self.assertNotIn('Sorgente Disponibile', text)

    def test_check_state_singleflight_and_playback_wins_race(self):
        route = 'https://example.invalid/singleflight'
        token = calendar.begin_source_check(route)
        self.assertIsNotNone(token)
        self.assertEqual('checking', calendar.verified_state(route))
        self.assertIsNone(calendar.begin_source_check(route))
        calendar.report_source_result(route, True)
        calendar.finish_source_check(route, token, False)
        self.assertEqual('available', calendar.verified_state(route))

    def test_cancelled_probe_can_be_retried_and_unknown_is_not_positive(self):
        route = 'https://example.invalid/cancelled-probe'
        token = calendar.begin_source_check(route)
        calendar.finish_source_check(route, token, None, cancelled=True)
        self.assertIsNone(calendar.verified_state(route))
        token = calendar.begin_source_check(route)
        calendar.finish_source_check(route, token, None)
        self.assertEqual('unknown', calendar.verified_state(route))

    def fixture(self, **overrides):
        value = dict(teams='A vs B', league='Cup', time='20:45', date='27/10/2026',
                     calendar_url='https://example.invalid/event', sources=[])
        value.update(overrides)
        return value

    def test_calendar_keeps_unpublished_event(self):
        self.assertEqual(1, len(art.prepare([self.fixture()], datetime(2026, 10, 27, 18))))

    def test_no_wrong_competition_match(self):
        a = self.fixture(date='', calendar_url='', league='Other Cup', sources=[dict(kind='web', url='https://example.invalid/play')])
        result = calendar.merge([a], [self.fixture()], home=False)
        self.assertFalse(any(e.get('calendar_url') and e.get('sources') for e in result))

    def test_duplicate_days(self):
        item = dict(title='[COLOR gold]20:45 A vs B[/COLOR] [COLOR aqua][Cup][/COLOR]',
                    externallink='https://example.invalid/event')
        group = dict(name='27 ottobre', items=[item])
        result = calendar.parse(dict(channels=[group, group]), datetime(2026, 10, 27))
        self.assertEqual(1, len(result))
        self.assertEqual('27/10/2026', result[0]['date'])
        self.assertEqual('Cup', result[0]['league'])

    def test_home_excludes_tomorrow_and_later(self):
        fixtures = [self.fixture(), self.fixture(teams='C vs D', date='28/10/2026'),
                    self.fixture(teams='E vs F', date='29/10/2026')]
        result = calendar.merge([], fixtures, now=datetime(2026, 10, 27, 18))
        self.assertEqual(['27/10/2026'], [event['date'] for event in result])

    def test_home_italian_first(self):
        fixtures = [self.fixture(league='Premier League', time='19:00'),
                    self.fixture(teams='C vs D', league='Serie A')]
        result = calendar.merge([], fixtures, now=datetime(2026, 10, 27, 18))
        self.assertEqual('Serie A', result[0]['league'])

    def test_home_hides_unknown_date(self):
        event = self.fixture(date='', calendar_url='', sources=[dict(kind='web', url='https://example.invalid/play')])
        result = calendar.merge([event], [], now=datetime(2026, 10, 27, 18))
        self.assertEqual([], result)

    def test_undated_source_contributes_to_matching_calendar_fixture(self):
        event = self.fixture(date='', calendar_url='', sources=[dict(kind='web', url='https://example.invalid/play')])
        result = calendar.merge([event], [self.fixture()], now=datetime(2026, 10, 27, 18))
        self.assertEqual(1, len(result))
        self.assertEqual('27/10/2026', result[0]['date'])
        self.assertEqual(1, len(result[0]['sources']))


if __name__ == '__main__':
    if '--refresh' in sys.argv:
        events = calendar.refresh()
        print('Eventi calendario:', len(events))
        print('Giorni unici:', len({e['date'] for e in events}))
        print('Card Home:', len(calendar.merge([], events)))
    else:
        unittest.main()
