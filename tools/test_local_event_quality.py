"""Offline tests of the installed Kodi quality policy (no media requests)."""
import importlib.util
import os
import time
import unittest

path = os.path.join(os.environ['APPDATA'], 'Kodi', 'addons', 'plugin.video.prippistream',
                    'platformcode', 'eventquality.py')
spec = importlib.util.spec_from_file_location('quality', path)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


class ListItem:
    def __init__(self, value):
        self.value = value

    def getPath(self):
        return self.value

    def getProperty(self, key):
        return ''


class QualityTest(unittest.TestCase):
    def test_master(self):
        self.assertEqual((1080, 6000000), q.parse_hls(
            '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\na.m3u8\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,AUDIO="it"\nb.m3u8'))

    def test_html_not_video(self):
        self.assertEqual((0, 0), q.parse_hls('<html>RESOLUTION=1920x1080</html>'))

    def test_media_playlist_unknown(self):
        self.assertEqual((0, 0), q.parse_hls('#EXTM3U\n#EXTINF:5\nvideo.ts'))

    def test_order_and_fallback(self):
        sources = [dict(url='720'), dict(url='unknown'), dict(url='1080')]
        ranks = {'720': (720, 2000000), '1080': (1080, 5000000), 'unknown': (0, 0)}
        result = q.prepare(sources, lambda source: ListItem(source['url']), probe=lambda url: ranks[url])
        self.assertEqual(['1080', '720', 'unknown'], [source['url'] for source, _, _ in result])

    def test_failed_resolver_does_not_abort_other_links(self):
        def resolve(source):
            if source['url'] == 'bad':
                raise ValueError('resolver unavailable')
            return ListItem(source['url'])
        result = q.prepare([dict(url='bad'), dict(url='ok')], resolve, probe=lambda url: (0, 0))
        self.assertEqual(['ok'], [source['url'] for source, _, _ in result])

    def test_equal_quality_prefers_primary_provider(self):
        sources = [dict(url='calendar', _origin='calendar'), dict(url='primary', _origin='primary')]
        result = q.prepare(sources, lambda source: ListItem(source['url']), probe=lambda url: (1080, 5000000))
        self.assertEqual('primary', result[0][0]['url'])

    def test_deadline_preserves_pending_fallback(self):
        def resolve(source):
            time.sleep(0.4)
            return ListItem(source['url'])
        start = time.monotonic()
        result = q.prepare([dict(url='slow')], resolve, budget=0.05, probe=lambda url: (0, 0))
        self.assertLess(time.monotonic() - start, 0.3)
        self.assertEqual('slow', result[0][0]['url'])


if __name__ == '__main__':
    unittest.main()
