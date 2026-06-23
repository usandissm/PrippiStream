# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# download_crypto — pluggable soft-DRM for offline downloads
#
# Two selectable cipher modes plus passthrough, all exposing the SAME
# offset-keyed symmetric primitive:
#
#     process(data, offset) -> bytes
#
# Because every cipher here is a stream cipher (keystream XOR), the operation
# is symmetric (encrypt == decrypt) and position-addressable: feeding chunks
# sequentially with an advancing offset encrypts a download in order, while the
# local playback server can decrypt an ARBITRARY byte range [start, start+len)
# simply by calling process(ciphertext, start) — enabling seek/scrub.
#
#   - 'aes'  : AES-128 in CTR mode (keystream = ECB(counter)). Strong.
#              Backend pycryptodome if present, else lib/pyaes (slower).
#   - 'xor'  : SHA-512 keystream (hash(key || block_index)). Light & fast.
#   - 'none' : passthrough (plaintext .ts, for compatibility/testing).
#
# The key is device-bound: derived from a stable hardware id so a file copied
# to another device will not decrypt. This is anti-copy obfuscation (soft-DRM),
# not hardware DRM — the key is computable from the (open-source) addon.
# ------------------------------------------------------------

from __future__ import division

import os
import hashlib
import struct
import threading

# AES backend preference: pycryptodome → native_aes (Kodi OpenSSL via ctypes,
# no dependency, releases the GIL) → pyaes (pure-python last resort).
_HAS_PYCRYPTO = False
try:
    from Crypto.Cipher import AES as _CAES
    _HAS_PYCRYPTO = True
except Exception:
    _CAES = None
try:
    from core import native_aes as _native_aes
except Exception:
    try:
        import native_aes as _native_aes
    except Exception:
        _native_aes = None
try:
    from lib import pyaes as _pyaes
except Exception:
    _pyaes = None

# Constant salt mixed into the device key derivation. Changing it invalidates
# every previously downloaded file, so keep it stable.
_SALT = b'PrippiStream-dl-v2-salto-7Qx'

_key_lock = threading.Lock()
_device_key_cache = None


# ── Device-bound key derivation ─────────────────────────────────────────────

def _hw_identifier():
    """Return a STABLE per-install identifier for the key derivation.

    Stability beats hardware-binding here. Our old primary was the network MAC
    (xbmc Network.MacAddress / uuid.getnode), but that is the wrong choice for an
    OFFLINE feature:
      * Toggling networking off — the exact moment offline downloads must still
        play — empties/changes Network.MacAddress, so the key no longer matches
        what encrypted the file.
      * On Android (the primary platform: TV boxes / Firestick / Google TV) apps
        cannot read the real WiFi MAC since Android 6; they get a constant fake
        (02:00:00:00:00:00) or nothing, so MAC is both non-unique AND volatile.

    A random id persisted in the addon data dir solves both: it survives reboots
    and network state, is unique per install, and is NOT carried by a copied .ts
    file on its own (soft-DRM anti-copy preserved). uuid.getnode() is kept only
    as a deterministic fallback when the data dir can't be written.
    """
    iid = _persisted_install_id()
    if iid:
        return 'inst:' + iid
    # Last resort (data dir unwritable): a real hardware MAC, never the random
    # multicast fallback (bit 40 set) which would change every run.
    try:
        import uuid
        node = uuid.getnode()
        if not (node >> 40) & 1:
            return 'node:%x' % node
    except Exception:
        pass
    return 'inst:none'


def _persisted_install_id():
    try:
        from platformcode import config
        path = os.path.join(config.get_data_path(), 'device.id')
    except Exception:
        path = os.path.join(os.path.expanduser('~'), '.prippistream_device.id')
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                v = f.read().strip()
                if v:
                    return v
    except Exception:
        pass
    v = hashlib.sha256(os.urandom(32)).hexdigest()
    # Only return the id if we could PERSIST it: an id that isn't saved would be
    # different on the next run, breaking decryption of files written now. If we
    # can't write, return '' so the caller uses its deterministic fallback.
    try:
        with open(path, 'w') as f:
            f.write(v)
        return v
    except Exception:
        return ''


def get_device_key():
    """Return the 16-byte device-bound key (cached for the process lifetime)."""
    global _device_key_cache
    with _key_lock:
        if _device_key_cache is None:
            import platform
            raw = b'|'.join([
                _SALT,
                _hw_identifier().encode('utf-8', 'ignore'),
                platform.machine().encode('utf-8', 'ignore'),
            ])
            _device_key_cache = hashlib.sha256(raw).digest()[:16]
        return _device_key_cache


def key_fingerprint():
    """Short non-secret fingerprint of the device key, for diagnostics. Lets us
    confirm in the log that encrypt (download) and decrypt (playback) sessions
    derived the SAME key without ever logging the key itself."""
    try:
        return hashlib.sha256(b'fp|' + get_device_key()).hexdigest()[:12]
    except Exception:
        return '?'


# ── Cipher implementations ──────────────────────────────────────────────────

def _xor_bytes(a, b):
    """XOR two equal-length byte strings efficiently."""
    n = len(a)
    return (int.from_bytes(a, 'big') ^ int.from_bytes(b, 'big')).to_bytes(n, 'big')


class NullCipher(object):
    name = 'none'

    def process(self, data, offset):
        return data


class XORCipher(object):
    """Position-keyed keystream from SHA-512(key || block_index). Fast, weak."""
    name = 'xor'
    _BLK = 64  # sha512 digest size

    def __init__(self, key):
        self._key = key

    def _keystream(self, offset, length):
        BLK = self._BLK
        start_blk = offset // BLK
        end_blk = (offset + length + BLK - 1) // BLK
        parts = []
        for b in range(start_blk, end_blk):
            parts.append(hashlib.sha512(self._key + struct.pack('>Q', b)).digest())
        ks = b''.join(parts)
        skip = offset - start_blk * BLK
        return ks[skip:skip + length]

    def process(self, data, offset):
        if not data:
            return data
        return _xor_bytes(data, self._keystream(offset, len(data)))


class AESCTRCipher(object):
    """AES-128-CTR. Keystream = AES-ECB of a 128-bit big-endian block counter
    (counter == file block index, so offset 0 starts at counter 0)."""
    name = 'aes'

    def __init__(self, key):
        self._key = key
        self._use_native = (not _HAS_PYCRYPTO and _native_aes is not None
                            and getattr(_native_aes, 'AVAILABLE', False))
        if not _HAS_PYCRYPTO and not self._use_native:
            if _pyaes is None:
                raise RuntimeError('AES mode requires pycryptodome, OpenSSL or pyaes')
            self._ecb = _pyaes.AESModeOfOperationECB(key)

    def process(self, data, offset):
        # Native OpenSSL CTR path: the entire keystream + XOR runs in C and
        # releases the GIL, so encrypting on the download writer thread doesn't
        # depend on getting Python GIL time (which a busy home GUI would starve).
        # Byte-identical to the ECB-of-counter + XOR fallback below.
        if data and self._use_native:
            block_start = offset // 16
            prefix = offset % 16
            ctr = (block_start).to_bytes(16, 'big')
            if prefix:
                return _native_aes.aes_ctr(self._key, ctr, (b'\x00' * prefix) + data)[prefix:]
            return _native_aes.aes_ctr(self._key, ctr, data)
        if not data:
            return data
        return _xor_bytes(data, self._keystream(offset, len(data)))

    def _ecb_blocks(self, first_block, n_blocks):
        buf = b''.join(((first_block + i).to_bytes(16, 'big')) for i in range(n_blocks))
        if _HAS_PYCRYPTO:
            return _CAES.new(self._key, _CAES.MODE_ECB).encrypt(buf)
        if self._use_native:
            return _native_aes.aes_ecb_encrypt(self._key, buf)
        # pyaes ECB encrypts one 16-byte block per call.
        out = bytearray()
        for i in range(n_blocks):
            out += self._ecb.encrypt(buf[i * 16:(i + 1) * 16])
        return bytes(out)

    def _keystream(self, offset, length):
        first_block = offset // 16
        prefix = offset % 16
        n_blocks = (prefix + length + 15) // 16
        ks = self._ecb_blocks(first_block, n_blocks)
        return ks[prefix:prefix + length]


def get_cipher(mode, key=None):
    """Factory. *mode* is 'aes' | 'xor' | 'none'. Key defaults to the device key."""
    mode = (mode or 'none').lower()
    if mode == 'none':
        return NullCipher()
    if key is None:
        key = get_device_key()
    if mode == 'xor':
        return XORCipher(key)
    if mode == 'aes':
        return AESCTRCipher(key)
    raise ValueError('unknown cipher mode: %r' % mode)


# Setting value (0/1/2) -> cipher mode name. Mirrors resources/settings.xml.
PROTECTION_MODES = {0: 'aes', 1: 'xor', 2: 'none'}


def mode_from_setting(value):
    try:
        return PROTECTION_MODES.get(int(value), 'aes')
    except Exception:
        return 'aes'
