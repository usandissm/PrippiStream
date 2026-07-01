# -*- coding: utf-8 -*-
"""Standalone validation for core/download_crypto + integration with the HLS
engine's encrypt hook (no Kodi, no network).

Run from repo root:  python tools/test_download_crypto.py
"""
import os
import sys
import json
import random
import tempfile
import importlib.util as _ilu

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _load(name, relpath):
    spec = _ilu.spec_from_file_location(name, os.path.join(_ROOT, relpath))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load('download_crypto', os.path.join('core', 'download_crypto.py'))
H = _load('hls_downloader', os.path.join('core', 'hls_downloader.py'))
from lib import pyaes


def _seq_encrypt(cipher, data, chunk):
    """Encrypt *data* feeding it sequentially in *chunk*-sized pieces, exactly
    like the downloader writes segments in order."""
    out = bytearray()
    off = 0
    for i in range(0, len(data), chunk):
        piece = data[i:i + chunk]
        out += cipher.process(piece, off)
        off += len(piece)
    return bytes(out)


def test_cipher_roundtrip_and_ranges():
    key = b'0123456789abcdef'
    plain = bytes(bytearray(random.randrange(256) for _ in range(100003)))  # non-block-aligned
    for mode in ('aes', 'xor', 'none'):
        cipher = C.get_cipher(mode, key)
        ct = _seq_encrypt(cipher, plain, chunk=4096)
        assert len(ct) == len(plain), "%s: length not preserved" % mode
        if mode != 'none':
            assert ct != plain, "%s: ciphertext == plaintext" % mode
        # Full decrypt.
        full = cipher.process(ct, 0)
        assert full == plain, "%s: full decrypt mismatch" % mode
        # Arbitrary ranges (simulate seek/scrub) — including non-aligned starts.
        for _ in range(40):
            start = random.randrange(0, len(plain))
            length = random.randrange(1, min(20000, len(plain) - start) + 1)
            dec = cipher.process(ct[start:start + length], start)
            assert dec == plain[start:start + length], \
                "%s: range [%d:%d] mismatch" % (mode, start, start + length)
        print("  %-4s round-trip + 40 random ranges OK" % mode)


def test_device_key_stable():
    k1 = C.get_device_key()
    k2 = C.get_device_key()
    assert k1 == k2 and len(k1) == 16
    print("  device key stable (%d bytes)" % len(k1))


def _build_fake_encrypted_stream(n, cdn_key, iv_hex):
    iv = bytes.fromhex(iv_hex)
    base = "https://cdn.example.com/v/"
    store = {"https://k/key.bin": cdn_key}
    expected = b''
    lines = ["#EXTM3U", "#EXT-X-MEDIA-SEQUENCE:0",
             "#EXT-X-KEY:METHOD=AES-128,URI=\"https://k/key.bin\",IV=0x%s" % iv_hex]
    for i in range(n):
        plain = ("SEG%03d-" % i).encode() + bytes(bytearray([i % 256])) * 1500
        expected += plain
        padlen = 16 - (len(plain) % 16)
        padded = plain + bytes(bytearray([padlen]) * padlen)
        enc = pyaes.Encrypter(pyaes.AESModeOfOperationCBC(cdn_key, iv), padding=pyaes.PADDING_NONE)
        store[base + "s%d.ts" % i] = enc.feed(padded) + enc.feed()
        lines += ["#EXTINF:6.0,", base + "s%d.ts" % i]
    lines.append("#EXT-X-ENDLIST")
    media_url = base + "index.m3u8"
    store[media_url] = "\n".join(lines).encode()
    return media_url, store, expected


def test_engine_encrypt_integration():
    """download_stream writes an ENCRYPTED file; decrypting it with the same
    cipher must reproduce the original (CDN-decrypted) plaintext."""
    cdn_key = b'aaaabbbbccccdddd'
    media_url, store, expected = _build_fake_encrypted_stream(
        10, cdn_key, "00000000000000000000000000000009")

    def http_get(url, headers=None, timeout=20):
        return store[url]

    key = b'ZZZZyyyyXXXXwww1'
    for mode in ('aes', 'xor', 'none'):
        cipher = C.get_cipher(mode, key)
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "enc.ts")
        H.download_stream(media_url, {}, out, http_get=http_get,
                          max_workers=3, encrypt=cipher.process)
        with open(out, 'rb') as f:
            on_disk = f.read()
        if mode != 'none':
            assert on_disk != expected, "%s: file on disk should be encrypted" % mode
        # Decrypt whole file.
        dec = C.get_cipher(mode, key).process(on_disk, 0)
        assert dec == expected, "%s: decrypted file mismatch" % mode
        # Decrypt a mid-stream range (seek).
        start, length = 5000, 4000
        rng = C.get_cipher(mode, key).process(on_disk[start:start + length], start)
        assert rng == expected[start:start + length], "%s: range decrypt mismatch" % mode
        print("  engine+%-4s encrypt/decrypt + seek OK (%d bytes)" % (mode, len(on_disk)))


if __name__ == '__main__':
    print("Testing core/download_crypto ...")
    test_cipher_roundtrip_and_ranges()
    test_device_key_stable()
    test_engine_encrypt_integration()
    print("ALL TESTS PASSED")
