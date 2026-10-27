"""Standalone tests: no Kodi imports, no other add-ons, no network."""
import importlib.util
import os
import unittest
from unittest.mock import patch

ROOT = os.path.join(os.environ['APPDATA'], 'Kodi', 'addons', 'plugin.video.prippistream')


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, 'platformcode', name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolver = load('eventresolver')


class ResolverTest(unittest.TestCase):
    def test_direct(self):
        values = resolver.resolve('https://example.invalid/stream.m3u8', {'Referer': 'https://example.invalid/page'})
        self.assertEqual('hls', values[0]['kind'])

    def test_iframe_chain_and_headers(self):
        pages = {
            'https://example.invalid/channel': '<iframe src="/embed"></iframe>',
            'https://example.invalid/embed': 'source: "https://media.example.invalid/live.m3u8"',
        }
        calls = []
        def fetch(url, headers):
            calls.append((url, headers))
            return url, pages[url]
        result = resolver.resolve('https://example.invalid/channel', fetch=fetch)
        self.assertEqual('https://example.invalid/channel', calls[1][1]['Referer'])
        self.assertEqual('https://example.invalid/embed', result[0]['headers']['Referer'])
        self.assertEqual('https://example.invalid', result[0]['headers']['Origin'])

    def test_bad_embed_tries_alternative(self):
        def fetch(url, headers):
            if url.endswith('/start'):
                return url, '<iframe src="/good"></iframe><iframe src="/bad"></iframe>'
            if url.endswith('/bad'):
                raise ValueError('HTTP 403')
            return url, 'file: "https://example.invalid/live.m3u8"'
        self.assertTrue(resolver.resolve('https://example.invalid/start', fetch=fetch))

    def test_loop_bounded(self):
        self.assertEqual([], resolver.resolve('https://example.invalid/a',
                         fetch=lambda url, hdr: (url, '<iframe src="/a"></iframe>')))

    def test_catalogue_uses_no_installed_addon_files(self):
        module = load('tgevents')
        with patch('builtins.open', side_effect=AssertionError('unexpected file read')):
            self.assertIsNone(module._addon_path())
            self.assertGreater(len(module._key_lines()), 10)
            self.assertTrue(module._user_agents())


if __name__ == '__main__':
    unittest.main()
