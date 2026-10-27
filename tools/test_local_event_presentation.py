"""Offline tests: no catalogue or playback URL is requested."""
import importlib.util
import os
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime

ROOT = os.path.join(os.environ['APPDATA'], 'Kodi', 'addons', 'plugin.video.prippistream')
spec = importlib.util.spec_from_file_location('presentation', os.path.join(ROOT, 'platformcode', 'eventpresentation.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PresentationTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 27, 18, 0)

    def event(self, **kw):
        event = dict(teams='Juventus vs Fiorentina', date='', time='20:45',
                     sources=[dict(kind='web', url='https://example.invalid/page')])
        event.update(kw)
        return event

    def test_unsupported_hidden(self):
        self.assertEqual([], p.prepare([self.event(sources=[dict(kind='ace', url='acestream://hash')])], self.now))

    def test_unknown_date_never_today(self):
        text, start, rank = p.calendar(self.event(), self.now)
        self.assertIsNone(start)
        self.assertNotIn('Oggi', text)
        self.assertIn('non confermata', text)

    def test_expired_date_not_next_year(self):
        self.assertEqual([], p.prepare([self.event(date='26/10')], self.now))

    def test_tomorrow(self):
        status = p.calendar(self.event(date='28/10'), self.now)[0]
        self.assertIn('Domani', status)
        self.assertIn('PROSSIMAMENTE', status)

    def test_italian_competitions_always_first(self):
        values = p.prepare([self.event(teams='A vs B', league='Premier League', date='27/10', time='19:00'),
                            self.event(league='Serie A', date='28/10')], self.now)
        self.assertEqual('Serie A', values[0]['league'])

    def test_country_groups_then_time_not_league(self):
        events = [self.event(teams='E vs F', league='Germania. Bundesliga', date='27/10', time='20:00'),
                  self.event(teams='A vs B', league='Italia. Serie A', date='27/10', time='22:00'),
                  self.event(teams='C vs D', league='Italia. Serie B', date='27/10', time='19:00'),
                  self.event(teams='G vs H', league='Germania. 2 Bundesliga', date='27/10', time='18:30')]
        values = p.prepare(events, self.now)
        self.assertEqual(['Italia', 'Italia', 'Germania', 'Germania'], [e['_country'] for e in values])
        self.assertEqual(['19:00', '22:00', '18:30', '20:00'], [e['time'] for e in values])

    def test_brazil_serie_a_not_italian(self):
        self.assertEqual('Brasile', p.country_for('Brasile. Serie A'))

    def test_duplicates_merge_sources(self):
        values = p.prepare([self.event(), self.event(sources=[dict(kind='hls', url='https://example.invalid/live.m3u8')])], self.now)
        self.assertEqual(1, len(values))
        self.assertEqual(2, len(values[0]['sources']))

    def test_ambiguous_teams_not_guessed(self):
        self.assertEqual('', p.teams('A vs B vs C')[1])

    def test_skin_valid(self):
        ET.parse(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'PrippiHome.xml'))


if __name__ == '__main__':
    unittest.main()
