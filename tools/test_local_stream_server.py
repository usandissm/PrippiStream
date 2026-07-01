# -*- coding: utf-8 -*-
"""Standalone validation for platformcode/local_stream_server: real loopback
HTTP requests with Range, verifying on-the-fly decryption (no Kodi).

Run from repo root:  python tools/test_local_stream_server.py
"""
import os
import sys
import types
import tempfile
import importlib.util as _ilu
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _load(name, relpath):
    spec = _ilu.spec_from_file_location(name, os.path.join(_ROOT, relpath))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load('download_crypto', os.path.join('core', 'download_crypto.py'))

# Shim the `core` and `platformcode` packages so local_stream_server imports
# resolve without dragging in Kodi-only deps.
core_pkg = types.ModuleType('core'); core_pkg.__path__ = []
core_pkg.download_crypto = C
sys.modules['core'] = core_pkg
sys.modules['core.download_crypto'] = C

pc_pkg = types.ModuleType('platformcode'); pc_pkg.__path__ = []
log_mod = types.ModuleType('platformcode.logger')
log_mod.error = lambda m: None
log_mod.info = lambda m: None
pc_pkg.logger = log_mod
sys.modules['platformcode'] = pc_pkg
sys.modules['platformcode.logger'] = log_mod

S = _load('local_stream_server', os.path.join('platformcode', 'local_stream_server.py'))


def _http_get(url, rng=None):
    req = urllib.request.Request(url)
    if rng:
        req.add_header('Range', 'bytes=%d-%d' % rng)
    resp = urllib.request.urlopen(req, timeout=10)
    return resp.status, resp.read(), resp.headers


def test_parse_range():
    assert S._parse_range('bytes=0-99', 1000) == (0, 99)
    assert S._parse_range('bytes=500-', 1000) == (500, 999)
    assert S._parse_range('bytes=-100', 1000) == (900, 999)
    assert S._parse_range(None, 1000) is None
    assert S._parse_range('bytes=2000-3000', 1000) is None
    print("  _parse_range OK")


def _make_encrypted_file(mode, plain):
    cipher = C.get_cipher(mode)   # device key
    enc = bytearray(); off = 0
    for i in range(0, len(plain), 7000):
        piece = plain[i:i + 7000]
        enc += cipher.process(piece, off); off += len(piece)
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, 'video.ts')
    with open(path, 'wb') as f:
        f.write(enc)
    return path


def test_server_decrypts_ranges():
    import random
    plain = bytes(bytearray(random.randrange(256) for _ in range(120007)))
    registry = {}

    def lookup(did):
        return registry.get(did)

    server = S.get_server(lookup=lookup)

    for mode in ('aes', 'xor', 'none'):
        path = _make_encrypted_file(mode, plain)
        did = 'dl_%s' % mode
        registry[did] = {'bundle': False, 'protection': mode,
                         'file_path': path, 'dir': ''}
        url = server.url_for(did)

        # Full GET (200) must reconstruct the plaintext.
        status, body, hdrs = _http_get(url)
        assert status == 200, "%s: expected 200, got %s" % (mode, status)
        assert body == plain, "%s: full body mismatch (%d vs %d)" % (mode, len(body), len(plain))
        assert hdrs.get('Accept-Ranges') == 'bytes'

        # Several Range requests (206) — simulate seeking.
        for _ in range(15):
            start = random.randrange(0, len(plain))
            end = min(len(plain) - 1, start + random.randrange(1, 30000))
            status, body, hdrs = _http_get(url, rng=(start, end))
            assert status == 206, "%s: expected 206, got %s" % (mode, status)
            assert body == plain[start:end + 1], "%s: range [%d-%d] mismatch" % (mode, start, end)
            assert hdrs.get('Content-Range') == 'bytes %d-%d/%d' % (start, end, len(plain))
        print("  server+%-4s full GET + 15 range seeks OK" % mode)

    # 404 for unknown id.
    try:
        _http_get(server.url_for('nope'))
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
    print("  404 for unknown id OK")
    server.stop()


def test_bundle():
    """A multi-track bundle: static playlists/subs served verbatim, encrypted
    track endpoints (v / a0) decrypted on the fly, url_for -> master.m3u8."""
    import random
    plain_v = bytes(bytearray(random.randrange(256) for _ in range(90001)))
    plain_a = bytes(bytearray(random.randrange(256) for _ in range(20003)))
    bdir = tempfile.mkdtemp()
    cv = C.get_cipher('aes')
    with open(os.path.join(bdir, 'video.ts'), 'wb') as f:
        f.write(cv.process(plain_v, 0))
    with open(os.path.join(bdir, 'audio.0.ts'), 'wb') as f:
        f.write(C.get_cipher('aes').process(plain_a, 0))
    open(os.path.join(bdir, 'sub.0.vtt'), 'w').write('WEBVTT\n\n00:00.0 --> 1.0\nx\n')
    open(os.path.join(bdir, 'master.m3u8'), 'w').write('#EXTM3U\nv.m3u8\n')
    open(os.path.join(bdir, 'v.m3u8'), 'w').write('#EXTM3U\n#EXTINF:5,\nv\n#EXT-X-ENDLIST\n')

    registry = {'b': {'bundle': True, 'protection': 'aes', 'dir': bdir, 'file_path': ''}}
    server = S.LocalStreamServer(lookup=registry.get)  # fresh (get_server is a singleton)
    server.start()
    base = server.url_for('b')
    assert base.endswith('/b/master.m3u8'), base
    root = base[:-len('/master.m3u8')]

    s, body, h = _http_get(root + '/master.m3u8')
    assert s == 200 and b'#EXTM3U' in body and 'mpegurl' in h.get('Content-Type', '')
    s, body, h = _http_get(root + '/sub.0.vtt')
    assert s == 200 and body.startswith(b'WEBVTT') and 'text/vtt' in h.get('Content-Type', '')
    s, body, h = _http_get(root + '/v')                  # full, decrypted
    assert s == 200 and body == plain_v, "video decrypt mismatch"
    s, body, h = _http_get(root + '/v', rng=(100, 5099))  # range, decrypted
    assert s == 206 and body == plain_v[100:5100], "video range mismatch"
    s, body, h = _http_get(root + '/a0')
    assert s == 200 and body == plain_a, "audio decrypt mismatch"
    print("  bundle: playlists + vtt + decrypted v/a0 (full+range) OK")
    server.stop()


if __name__ == '__main__':
    print("Testing platformcode/local_stream_server ...")
    test_parse_range()
    test_server_decrypts_ranges()
    test_bundle()
    print("ALL TESTS PASSED")
