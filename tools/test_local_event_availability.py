"""Deterministic network-contract checks: no real streams or players opened."""
import importlib.util
import os
import time
import unittest
from urllib.error import HTTPError

ROOT = os.path.join(os.environ['APPDATA'], 'Kodi', 'addons', 'plugin.video.prippistream')
spec = importlib.util.spec_from_file_location('availability', os.path.join(ROOT, 'platformcode', 'eventavailability.py'))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class Response:
    def __init__(self, url, body, content_type='application/octet-stream'):
        self.url, self.body = url, body
        self.headers = {'Content-Type': content_type}
        self.status = 200

    def geturl(self):
        return self.url

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class AvailabilityTest(unittest.TestCase):
    def source(self, **overrides):
        value = dict(url='https://example.invalid/live.m3u8', kind='hls',
                     headers={'Referer': 'https://example.invalid/player', 'Cookie': 'test=1'})
        value.update(overrides)
        return value

    def opener(self, pages, calls=None):
        def open_url(request, timeout):
            if calls is not None:
                calls.append((request.full_url, request.header_items()))
            value = pages[request.full_url]
            if isinstance(value, Exception):
                raise value
            return Response(request.full_url, value)
        return open_url

    def test_manifest_and_real_segment_required(self):
        calls = []
        pages = {'https://example.invalid/live.m3u8': b'#EXTM3U\n#EXTINF:6,\nseg.ts',
                 'https://example.invalid/seg.ts': b'G' + b'video' * 500}
        self.assertTrue(a.hls_reachable(self.source(), self.opener(pages, calls)))
        self.assertEqual(2, len(calls))
        headers = {key.lower(): value for key, value in calls[-1][1]}
        self.assertEqual('bytes=0-1023', headers['range'])
        self.assertEqual('test=1', headers['cookie'])
        self.assertEqual('https://example.invalid/player', headers['referer'])

    def test_http_403_manifest_is_unavailable(self):
        pages = {'https://example.invalid/live.m3u8': HTTPError('url', 403, 'Forbidden', {}, None)}
        self.assertFalse(a.hls_reachable(self.source(), self.opener(pages)))

    def test_200_playlist_but_403_segment_not_available(self):
        pages = {'https://example.invalid/live.m3u8': b'#EXTM3U\n#EXTINF:6,\nseg.ts',
                 'https://example.invalid/seg.ts': HTTPError('url', 403, 'Forbidden', {}, None)}
        self.assertFalse(a.hls_reachable(self.source(), self.opener(pages)))

    def test_html_player_not_a_working_hls_stream(self):
        pages = {'https://example.invalid/live.m3u8': b'<html>Access denied</html>'}
        self.assertFalse(a.hls_reachable(self.source(), self.opener(pages)))

    def test_html_segment_not_video(self):
        pages = {'https://example.invalid/live.m3u8': b'#EXTM3U\n#EXTINF:6,\nseg.ts',
                 'https://example.invalid/seg.ts': b'<!DOCTYPE html>denied'}
        self.assertFalse(a.hls_reachable(self.source(), self.opener(pages)))

    def test_master_with_a_working_alternative(self):
        pages = {'https://example.invalid/live.m3u8': b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2\nbad.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=1\ngood.m3u8',
                 'https://example.invalid/bad.m3u8': HTTPError('url', 404, 'missing', {}, None),
                 'https://example.invalid/good.m3u8': b'#EXTM3U\n#EXTINF:6,\nseg.ts',
                 'https://example.invalid/seg.ts': b'G' * 1024}
        self.assertTrue(a.hls_reachable(self.source(), self.opener(pages)))

    def test_expired_budget_not_marked_offline(self):
        self.assertIsNone(a.hls_reachable(self.source(), deadline=time.monotonic() - 1))

    def test_drm_requires_real_player_not_false_offline(self):
        pages = {'https://example.invalid/live.m3u8': b'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\n#EXTINF:6,\nseg.ts'}
        self.assertIsNone(a.hls_reachable(self.source(), self.opener(pages)))

    def test_broken_first_source_does_not_suppress_good_backup(self):
        sources = [self.source(url='https://example.invalid/bad'), self.source(url='https://example.invalid/good')]
        self.assertTrue(a.check(sources, resolve=lambda *args: [],
                                probe=lambda source, **kwargs: source['url'].endswith('good')))

    def test_published_wrapper_without_media_not_available(self):
        self.assertFalse(a.check([self.source(kind='web')], resolve=lambda *args: []))

    def test_focus_change_cancels_without_offline_claim(self):
        self.assertIsNone(a.check([self.source()], resolve=lambda *args: [], active=lambda: False))

    def test_inconclusive_probe_remains_unknown(self):
        self.assertIsNone(a.check([self.source()], resolve=lambda *args: [], probe=lambda *args, **kwargs: None))


if __name__ == '__main__':
    unittest.main()
