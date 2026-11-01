"""Offline artwork provider contracts, ambiguity guards and temporary failures."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

s = runpy.run_path(str(Path(__file__).with_name('test_event_startup.py')))
a = s['art']
net = s['load']('eventartnet')


class ArtworkTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.mockpath = patch.object(net, '_path', return_value=str(self.path / 'backoff.json'))
        self.mockpath.start()
        self.addCleanup(self.mockpath.stop)
        net._BACKOFF, net._NEXT = {}, {}

    def test_429_is_persisted_and_next_request_not_sent(self):
        error = HTTPError('https://example.invalid', 429, 'limit', {'Retry-After': '1000'}, None)
        with patch.object(net, 'urlopen', side_effect=error) as open_url:
            for _ in range(2):
                with self.assertRaises(net.TemporaryError):
                    net.read(Request('https://example.invalid/logo'), 100)
        self.assertEqual(1, open_url.call_count)
        self.assertIn('example.invalid', json.loads((self.path / 'backoff.json').read_text()))

    def test_404_remains_permanent(self):
        with patch.object(net, 'urlopen', side_effect=HTTPError('url', 404, 'gone', {}, None)):
            with self.assertRaises(HTTPError):
                net.read('https://example.invalid/logo', 100)
        self.assertFalse((self.path / 'backoff.json').exists())

    def test_cooldown_survives_module_restart(self):
        net._pause('example.invalid', 900)
        net._BACKOFF = None
        with patch.object(net, 'urlopen') as request:
            with self.assertRaises(net.TemporaryError):
                net.read('https://example.invalid/logo', 100)
        request.assert_not_called()

    def test_malformed_json_not_cached_as_absent_team(self):
        with patch.object(a, '_directory', return_value=str(self.path)), \
                patch.object(a, '_cached_badge', return_value=''), \
                patch.object(a, '_wiki_badge', return_value=''), \
                patch.object(a, '_art_read', return_value=b'<html>temporary upstream error</html>'):
            self.assertEqual('', a.badge('Example Missing Club', fetch=True))
        self.assertEqual([], list(self.path.glob('*.miss-*')))

    def test_wikipedia_languages_share_limit(self):
        net._pause('wikipedia.org', 900)
        with patch.object(net, 'urlopen') as request:
            with self.assertRaises(net.TemporaryError):
                net.read('https://it.wikipedia.org/page', 100)
        request.assert_not_called()

    def test_search_without_logos_uses_verified_team_details(self):
        doc = dict(team=dict(id='6972', logos=[dict(href='https://example.invalid/logo.png')]))
        with patch.object(a, '_art_read', return_value=json.dumps(doc).encode()) as read:
            logos = a._espn_logos(dict(id='6972', league='afc.cup'))
        self.assertEqual('https://example.invalid/logo.png', logos[0]['href'])
        self.assertTrue(read.call_args.args[0].full_url.endswith('/afc.cup/teams/6972'))

    def test_wrong_team_id_does_not_supply_logo(self):
        with patch.object(a, '_art_read', return_value=b'{"team":{"id":"2","logos":[{"href":"https://example.invalid/wrong"}]}}'):
            self.assertEqual([], a._espn_logos(dict(id='1', league='ita.1')))

    def test_institutional_prefix_but_not_ambiguous_clubs(self):
        team = dict(id='1', name='SC Amiens', sport='soccer')
        self.assertEqual([team], a._matching_espn_teams('Amiens', [team]))
        other = dict(id='2', name='Amiens FC', sport='soccer')
        self.assertEqual([], a._matching_espn_teams('Amiens', [team, other]))

    def test_rate_limit_does_not_poison_missing_cache(self):
        with patch.object(a, '_directory', return_value=str(self.path)), \
                patch.object(a, '_cached_badge', return_value=''), \
                patch.object(a, '_wiki_badge', side_effect=net.TemporaryError), \
                patch.object(a, '_art_read', return_value=b'{}'):
            self.assertEqual('', a.badge('Example Missing Club', fetch=True))
        self.assertEqual([], list(self.path.glob('*.miss-*')))

    def test_real_missing_match_is_cached(self):
        with patch.object(a, '_directory', return_value=str(self.path)), \
                patch.object(a, '_cached_badge', return_value=''), \
                patch.object(a, '_wiki_badge', return_value=''), \
                patch.object(a, '_art_read', return_value=b'{}'):
            self.assertEqual('', a.badge('Example Missing Club', fetch=True))
        self.assertEqual(1, len(list(self.path.glob('*.miss-*'))))


if __name__ == '__main__':
    unittest.main()
