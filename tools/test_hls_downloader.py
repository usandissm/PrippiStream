# -*- coding: utf-8 -*-
"""Standalone validation for core/hls_downloader (no Kodi, no network).

Run from repo root:  python tools/test_hls_downloader.py
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Load core/hls_downloader.py directly, bypassing core/__init__.py (which pulls
# in Kodi-only deps like `past`). The module is intentionally self-contained.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "hls_downloader", os.path.join(_ROOT, "core", "hls_downloader.py"))
H = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(H)

from lib import pyaes


def test_parse_master():
    txt = (
        "#EXTM3U\n"
        "#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID=\"subs\",NAME=\"Italian\",LANGUAGE=\"ita\",URI=\"subs/ita.m3u8\"\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=854x480\n"
        "v480/index.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080\n"
        "v1080/index.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=1280x720\n"
        "v720/index.m3u8\n"
    )
    m = H.parse_master(txt, "https://cdn.example.com/path/master.m3u8")
    assert m['is_master'] is True
    assert [v['height'] for v in m['variants']] == [1080, 720, 480], m['variants']
    assert m['variants'][0]['url'] == "https://cdn.example.com/path/v1080/index.m3u8"
    assert len(m['subtitles']) == 1 and m['subtitles'][0]['language'] == 'ita'
    assert m['subtitles'][0]['url'] == "https://cdn.example.com/path/subs/ita.m3u8"
    print("  parse_master OK")


def test_parse_media():
    txt = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXT-X-KEY:METHOD=AES-128,URI=\"https://k.example/key.bin\",IV=0x0123456789abcdef0123456789abcdef\n"
        "#EXTINF:6.0,\n"
        "seg0.ts\n"
        "#EXTINF:6.0,\n"
        "seg1.ts\n"
        "#EXT-X-ENDLIST\n"
    )
    med = H.parse_media(txt, "https://cdn.example.com/v1080/index.m3u8")
    assert len(med['segments']) == 2
    assert med['segments'][0]['url'] == "https://cdn.example.com/v1080/seg0.ts"
    assert med['segments'][0]['seq'] == 0 and med['segments'][1]['seq'] == 1
    assert med['segments'][0]['dur'] == 6.0 and med['segments'][1]['dur'] == 6.0
    assert med['key']['method'] == 'AES-128'
    assert med['map'] is None
    print("  parse_media OK")


def test_aes_roundtrip():
    key = b'0123456789abcdef'
    iv = b'abcdef9876543210'
    plain = b'The quick brown fox jumps over the lazy dog. ' * 10
    # PKCS7 pad
    padlen = 16 - (len(plain) % 16)
    padded = plain + bytes(bytearray([padlen]) * padlen)
    enc = pyaes.Encrypter(pyaes.AESModeOfOperationCBC(key, iv), padding=pyaes.PADDING_NONE)
    cipher = enc.feed(padded) + enc.feed()
    dec = H._aes_cbc_decrypt(cipher, key, iv)
    assert dec == plain, "AES round-trip mismatch"
    print("  aes_cbc_decrypt round-trip OK (backend=%s)" %
          ('pycryptodome' if H._HAS_PYCRYPTO else 'pyaes'))


def _build_fake_stream(n_segments, key, iv_hex):
    """Return (playlist_text, {url: bytes}, expected_plaintext)."""
    iv = bytes.fromhex(iv_hex)
    base = "https://cdn.example.com/v/"
    store = {}
    expected = b''
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-MEDIA-SEQUENCE:0",
             "#EXT-X-KEY:METHOD=AES-128,URI=\"https://k/key.bin\",IV=0x%s" % iv_hex]
    store["https://k/key.bin"] = key
    for i in range(n_segments):
        plain = ("SEGMENT-%03d-" % i).encode() + bytes(bytearray([i % 256])) * 2000
        expected += plain
        padlen = 16 - (len(plain) % 16)
        padded = plain + bytes(bytearray([padlen]) * padlen)
        enc = pyaes.Encrypter(pyaes.AESModeOfOperationCBC(key, iv), padding=pyaes.PADDING_NONE)
        store[base + "seg%d.ts" % i] = enc.feed(padded) + enc.feed()
        lines.append("#EXTINF:6.0,")
        lines.append(base + "seg%d.ts" % i)
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines), store, expected


def test_full_download_and_resume():
    key = b'aaaabbbbccccdddd'
    iv_hex = "00000000000000000000000000000001"
    n = 12
    playlist, store, expected = _build_fake_stream(n, key, iv_hex)
    media_url = "https://cdn.example.com/v/index.m3u8"
    store[media_url] = playlist.encode()

    def http_get(url, headers=None, timeout=20):
        if url not in store:
            raise RuntimeError("404 " + url)
        return store[url]

    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "out.ts")

    # Full download.
    written = H.download_stream(media_url, {}, out, http_get=http_get, max_workers=4)
    with open(out, 'rb') as f:
        got = f.read()
    assert got == expected, "full download mismatch (%d vs %d bytes)" % (len(got), len(expected))
    assert written == len(expected)
    assert not os.path.exists(out + '.dlmeta'), "sidecar should be cleared on success"
    print("  full download OK (%d bytes, %d segments)" % (written, n))

    # Resume: simulate a download that stopped after 5 segments.
    out2 = os.path.join(tmp, "out2.ts")
    seg_lens = []
    acc = b''
    # Recompute per-segment plaintext lengths to know byte boundary at seg 5.
    for i in range(n):
        plain = ("SEGMENT-%03d-" % i).encode() + bytes(bytearray([i % 256])) * 2000
        seg_lens.append(len(plain))
    cut = sum(seg_lens[:5])
    with open(out2, 'wb') as f:
        f.write(expected[:cut])
    import json
    with open(out2 + '.dlmeta', 'w') as f:
        json.dump({'total': n, 'done': 5, 'bytes': cut}, f)

    calls = {'count': 0}
    seg_urls = set("https://cdn.example.com/v/seg%d.ts" % i for i in range(n))

    def http_get_count(url, headers=None, timeout=20):
        if url in seg_urls:
            calls['count'] += 1
        return store[url]

    H.download_stream(media_url, {}, out2, http_get=http_get_count, max_workers=4)
    with open(out2, 'rb') as f:
        got2 = f.read()
    assert got2 == expected, "resumed download mismatch"
    assert calls['count'] == n - 5, "resume re-fetched too many segments: %d" % calls['count']
    print("  resume OK (re-fetched only %d of %d segments)" % (calls['count'], n))


def test_segment_metadata():
    """meta_out['segments'] records [dur, byte_len] per segment so a seekable
    byte-range playlist can be built; offsets reconstruct to the file size."""
    key = b'aaaabbbbccccdddd'
    iv_hex = "00000000000000000000000000000001"
    n = 7
    playlist, store, expected = _build_fake_stream(n, key, iv_hex)
    media_url = "https://cdn.example.com/v/index.m3u8"
    store[media_url] = playlist.encode()

    def http_get(url, headers=None, timeout=20):
        return store[url]

    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "out.ts")
    meta = {}
    H.download_stream(media_url, {}, out, http_get=http_get, max_workers=4,
                      meta_out=meta)
    segs = meta.get('segments')
    assert isinstance(segs, list) and len(segs) == n, segs
    assert all(s[0] == 6.0 for s in segs), "durations not attached"
    assert sum(s[1] for s in segs) == len(expected), "byte lengths don't sum to file"
    # Offsets are the running sum and must match each segment's real position.
    off = 0
    for i, (_, length) in enumerate(segs):
        plain = ("SEGMENT-%03d-" % i).encode() + bytes(bytearray([i % 256])) * 2000
        assert length == len(plain), "seg %d length mismatch" % i
        off += length
    assert off == len(expected)
    print("  segment metadata OK (%d segments, %d bytes)" % (n, off))

    # Resume from a pre-existing sidecar WITHOUT 'segs' → metadata unavailable,
    # reported as None so the caller falls back to a single-segment playlist.
    out2 = os.path.join(tmp, "out2.ts")
    cut = sum(len(("SEGMENT-%03d-" % i).encode() + bytes(bytearray([i % 256])) * 2000)
              for i in range(3))
    with open(out2, 'wb') as f:
        f.write(expected[:cut])
    import json
    with open(out2 + '.dlmeta', 'w') as f:
        json.dump({'total': n, 'done': 3, 'bytes': cut}, f)
    meta2 = {}
    H.download_stream(media_url, {}, out2, http_get=http_get, max_workers=4,
                      meta_out=meta2)
    assert meta2.get('segments') is None, "stale-sidecar resume must disable byte-range"
    print("  segment metadata resume-fallback OK")


if __name__ == '__main__':
    print("Testing core/hls_downloader ...")
    test_parse_master()
    test_parse_media()
    test_aes_roundtrip()
    test_full_download_and_resume()
    test_segment_metadata()
    print("ALL TESTS PASSED")
