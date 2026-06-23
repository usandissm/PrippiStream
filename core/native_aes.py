# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# native_aes — fast, GIL-releasing AES with NO Python-package dependency.
#
# The bundled pure-python pyaes is ~0.4 MB/s AND holds the GIL, which both
# cripples download speed and freezes the Kodi UI (segment decryption on 16
# worker threads serialises on the GIL). pycryptodome is NOT in the official
# Kodi repo, so it can't be a hard dependency. Instead we reach a native AES
# implementation that already lives in the process / OS:
#
#   Backend 1 — OpenSSL libcrypto via ctypes (EVP_* primitives).
#       Works on Linux/Android (system or Kodi-bundled libcrypto.so / BoringSSL)
#       and on Windows when a libcrypto DLL is on the search path. ~1 GB/s.
#
#   Backend 2 — Windows CNG / BCrypt (bcrypt.dll), a Windows fallback for the
#       common case where Kodi statically links OpenSSL into _ssl.pyd and there
#       is NO loadable libcrypto DLL anywhere. bcrypt.dll ships with every
#       Windows since Vista, so this needs no bundled file. Also releases the GIL.
#
# Both are byte-identical to pyaes (verified), so files already downloaded with
# any backend remain decryptable. All handles/keys are created per call (or the
# algorithm provider is read-only after setup), so the functions are safe to use
# from many worker threads concurrently.
#
# AVAILABLE is False only if neither native backend could be reached; callers
# then fall back to pyaes. BACKEND/LOADED_LIB/LOAD_ATTEMPTS are exported for the
# downloader to log, so kodi.log tells us exactly which path is active.
# ------------------------------------------------------------

import os
import sys
import ctypes
import ctypes.util
import threading

AVAILABLE = False
BACKEND = None          # 'openssl' | 'bcrypt' | None
LOADED_LIB = None       # name/path of the loaded lib (diagnostics)
LOAD_ATTEMPTS = []      # [(candidate, error), ...] for diagnostics

_lib = None             # OpenSSL libcrypto handle
_init_lock = threading.Lock()


# ── OpenSSL libcrypto backend ───────────────────────────────────────────────

# Candidate library names across platforms. The one Kodi uses for HTTPS is
# often already loaded, so loading it by name succeeds.
#
# NOTE: Kodi (Windows) statically links OpenSSL into _ssl.pyd/_hashlib.pyd, so
# there is NO versioned libcrypto-3.dll/libcrypto-1_1.dll to load by name. The
# plain 'libcrypto.dll' (shipped by many apps into System32, on the DLL search
# path) is what actually loads there — it MUST be in this list. When NOTHING
# loads here we fall through to the BCrypt backend (Windows) below.
_CANDIDATES = [
    'libcrypto-3.dll', 'libcrypto-1_1.dll', 'libcrypto.dll', 'libeay32.dll',  # Windows
    'libcrypto.so.3', 'libcrypto.so.1.1', 'libcrypto.so',           # Linux/Android
    'libcrypto.3.dylib', 'libcrypto.1.1.dylib', 'libcrypto.dylib',  # macOS
]


def _try_openssl():
    global _lib, AVAILABLE, BACKEND, LOADED_LIB
    names = list(_CANDIDATES)
    found = ctypes.util.find_library('crypto')
    if found:
        names.append(found)
    # Also try explicit full paths: alongside the _ssl module, in the Kodi app
    # dir, and in System32 — in case the bare name isn't on the search path.
    try:
        import ssl as _ssl_mod
        _dirs = []
        _sslfile = getattr(getattr(_ssl_mod, '_ssl', None), '__file__', '') or ''
        if _sslfile:
            _dirs.append(os.path.dirname(_sslfile))
        try:
            _dirs.append(os.path.dirname(sys.executable))   # kodi.exe dir
        except Exception:
            pass
        _sysroot = os.environ.get('SystemRoot') or r'C:\Windows'
        _dirs.append(os.path.join(_sysroot, 'System32'))
        for _d in _dirs:
            if not _d:
                continue
            for _n in ('libcrypto-3.dll', 'libcrypto-1_1.dll', 'libcrypto.dll',
                       'libcrypto.so.3', 'libcrypto.so.1.1', 'libcrypto.so'):
                names.append(os.path.join(_d, _n))
    except Exception:
        pass

    for name in names:
        try:
            lib = ctypes.CDLL(name)
            if not hasattr(lib, 'EVP_CIPHER_CTX_new'):
                LOAD_ATTEMPTS.append((name, 'no EVP_CIPHER_CTX_new'))
                continue
            _configure_openssl(lib)
            _lib = lib
            LOADED_LIB = name
            BACKEND = 'openssl'
            AVAILABLE = True
            return True
        except Exception as e:
            if len(LOAD_ATTEMPTS) < 40:
                LOAD_ATTEMPTS.append((name, str(e)))
            continue
    return False


def _configure_openssl(lib):
    c_vp, c_cp, c_int = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    P_int = ctypes.POINTER(c_int)
    lib.EVP_CIPHER_CTX_new.restype = c_vp
    lib.EVP_CIPHER_CTX_free.argtypes = [c_vp]
    lib.EVP_CIPHER_CTX_set_padding.argtypes = [c_vp, c_int]
    lib.EVP_aes_128_cbc.restype = c_vp
    lib.EVP_aes_128_ecb.restype = c_vp
    lib.EVP_aes_128_ctr.restype = c_vp
    lib.EVP_DecryptInit_ex.argtypes = [c_vp, c_vp, c_vp, c_cp, c_cp]
    lib.EVP_DecryptUpdate.argtypes = [c_vp, c_vp, P_int, c_cp, c_int]
    lib.EVP_DecryptFinal_ex.argtypes = [c_vp, c_vp, P_int]
    lib.EVP_EncryptInit_ex.argtypes = [c_vp, c_vp, c_vp, c_cp, c_cp]
    lib.EVP_EncryptUpdate.argtypes = [c_vp, c_vp, P_int, c_cp, c_int]
    lib.EVP_EncryptFinal_ex.argtypes = [c_vp, c_vp, P_int]


def _ossl_cbc_decrypt(key, iv, data):
    ctx = _lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError('EVP_CIPHER_CTX_new failed')
    try:
        _lib.EVP_DecryptInit_ex(ctx, _lib.EVP_aes_128_cbc(), None, key, iv)
        _lib.EVP_CIPHER_CTX_set_padding(ctx, 0)
        out = ctypes.create_string_buffer(len(data) + 16)
        outl = ctypes.c_int(0)
        _lib.EVP_DecryptUpdate(ctx, out, ctypes.byref(outl), data, len(data))
        total = outl.value
        _lib.EVP_DecryptFinal_ex(ctx, ctypes.byref(out, total), ctypes.byref(outl))
        total += outl.value
        return out.raw[:total]
    finally:
        _lib.EVP_CIPHER_CTX_free(ctx)


def _ossl_ecb_encrypt(key, data):
    ctx = _lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError('EVP_CIPHER_CTX_new failed')
    try:
        _lib.EVP_EncryptInit_ex(ctx, _lib.EVP_aes_128_ecb(), None, key, None)
        _lib.EVP_CIPHER_CTX_set_padding(ctx, 0)
        out = ctypes.create_string_buffer(len(data) + 16)
        outl = ctypes.c_int(0)
        _lib.EVP_EncryptUpdate(ctx, out, ctypes.byref(outl), data, len(data))
        total = outl.value
        _lib.EVP_EncryptFinal_ex(ctx, ctypes.byref(out, total), ctypes.byref(outl))
        total += outl.value
        return out.raw[:total]
    finally:
        _lib.EVP_CIPHER_CTX_free(ctx)


def _ossl_ctr(key, counter16, data):
    ctx = _lib.EVP_CIPHER_CTX_new()
    if not ctx:
        raise RuntimeError('EVP_CIPHER_CTX_new failed')
    try:
        _lib.EVP_EncryptInit_ex(ctx, _lib.EVP_aes_128_ctr(), None, key, counter16)
        out = ctypes.create_string_buffer(len(data) + 16)
        outl = ctypes.c_int(0)
        _lib.EVP_EncryptUpdate(ctx, out, ctypes.byref(outl), data, len(data))
        total = outl.value
        _lib.EVP_EncryptFinal_ex(ctx, ctypes.byref(out, total), ctypes.byref(outl))
        total += outl.value
        return out.raw[:total]
    finally:
        _lib.EVP_CIPHER_CTX_free(ctx)


# ── Windows CNG / BCrypt backend ────────────────────────────────────────────
# Used when no OpenSSL libcrypto can be loaded (typical on classic Kodi for
# Windows, which statically links OpenSSL). bcrypt.dll is part of Windows.

_bcrypt = None
_h_alg_cbc = None       # AES algorithm provider, ChainingModeCBC
_h_alg_ecb = None       # AES algorithm provider, ChainingModeECB
_bc_keyobj_len = 0      # required key-object buffer size

_NT_SUCCESS = 0


def _w(s):
    """UTF-16LE NUL-terminated wide string for BCrypt property/algo names."""
    return ctypes.create_unicode_buffer(s)


def _try_bcrypt():
    global _bcrypt, _h_alg_cbc, _h_alg_ecb, _bc_keyobj_len
    global AVAILABLE, BACKEND, LOADED_LIB
    if not sys.platform.startswith('win'):
        return False
    try:
        bc = ctypes.WinDLL('bcrypt')
    except Exception as e:
        LOAD_ATTEMPTS.append(('bcrypt.dll', str(e)))
        return False
    try:
        hAlg = ctypes.c_void_p()
        st = bc.BCryptOpenAlgorithmProvider(ctypes.byref(hAlg), _w('AES'), None, 0)
        if st != _NT_SUCCESS:
            LOAD_ATTEMPTS.append(('bcrypt:OpenAlg', 'NTSTATUS 0x%08x' % (st & 0xffffffff)))
            return False
        # Query key-object length.
        objlen = ctypes.c_ulong(0)
        got = ctypes.c_ulong(0)
        bc.BCryptGetProperty(hAlg, _w('ObjectLength'),
                             ctypes.byref(objlen), ctypes.sizeof(objlen),
                             ctypes.byref(got), 0)
        keyobj_len = objlen.value or 0

        # Two providers: one fixed to CBC, one to ECB chaining.
        def _mk(mode_value):
            h = ctypes.c_void_p()
            s = bc.BCryptOpenAlgorithmProvider(ctypes.byref(h), _w('AES'), None, 0)
            if s != _NT_SUCCESS:
                raise RuntimeError('OpenAlg %s: 0x%08x' % (mode_value, s & 0xffffffff))
            mode = _w(mode_value)
            s = bc.BCryptSetProperty(h, _w('ChainingMode'),
                                     ctypes.cast(mode, ctypes.c_char_p),
                                     (len(mode_value) + 1) * 2, 0)
            if s != _NT_SUCCESS:
                raise RuntimeError('SetChain %s: 0x%08x' % (mode_value, s & 0xffffffff))
            return h

        h_cbc = _mk('ChainingModeCBC')
        h_ecb = _mk('ChainingModeECB')
        bc.BCryptCloseAlgorithmProvider(hAlg, 0)

        # Smoke test: a known AES-128-ECB vector (FIPS-197) to be sure the
        # backend actually works before we advertise AVAILABLE.
        _bcrypt = bc
        _h_alg_cbc = h_cbc
        _h_alg_ecb = h_ecb
        _bc_keyobj_len = keyobj_len
        key = bytes.fromhex('000102030405060708090a0b0c0d0e0f')
        pt = bytes.fromhex('00112233445566778899aabbccddeeff')
        ct = _bc_ecb_encrypt(key, pt)
        if ct != bytes.fromhex('69c4e0d86a7b0430d8cdb78070b4c55a'):
            LOAD_ATTEMPTS.append(('bcrypt:selftest', 'vector mismatch %s' % ct.hex()))
            _bcrypt = None
            return False

        BACKEND = 'bcrypt'
        LOADED_LIB = 'bcrypt.dll (Windows CNG)'
        AVAILABLE = True
        return True
    except Exception as e:
        LOAD_ATTEMPTS.append(('bcrypt:init', str(e)))
        _bcrypt = None
        return False


def _bc_run(h_alg, key, data, iv, decrypt):
    """Run BCryptEncrypt/Decrypt with NO padding. Returns the output bytes.
    A fresh key handle is generated per call → thread-safe."""
    bc = _bcrypt
    hKey = ctypes.c_void_p()
    keyobj = ctypes.create_string_buffer(_bc_keyobj_len) if _bc_keyobj_len else None
    st = bc.BCryptGenerateSymmetricKey(
        h_alg, ctypes.byref(hKey),
        keyobj, _bc_keyobj_len,
        ctypes.c_char_p(key), len(key), 0)
    if st != _NT_SUCCESS:
        raise RuntimeError('GenKey 0x%08x' % (st & 0xffffffff))
    try:
        ivbuf = None
        ivlen = 0
        if iv is not None:
            ivbuf = ctypes.create_string_buffer(iv, len(iv))  # mutable copy
            ivlen = len(iv)
        out = ctypes.create_string_buffer(len(data) + 16)
        res = ctypes.c_ulong(0)
        fn = bc.BCryptDecrypt if decrypt else bc.BCryptEncrypt
        st = fn(hKey,
                ctypes.c_char_p(data), len(data),
                None,
                ivbuf, ivlen,
                out, len(data),
                ctypes.byref(res), 0)
        if st != _NT_SUCCESS:
            raise RuntimeError('%s 0x%08x' % ('Decrypt' if decrypt else 'Encrypt',
                                              st & 0xffffffff))
        return out.raw[:res.value]
    finally:
        bc.BCryptDestroyKey(hKey)


def _bc_cbc_decrypt(key, iv, data):
    return _bc_run(_h_alg_cbc, key, data, iv, decrypt=True)


def _bc_ecb_encrypt(key, data):
    return _bc_run(_h_alg_ecb, key, data, None, decrypt=False)


def _bc_ctr(key, counter16, data):
    """AES-CTR via ECB-of-counter XOR data (CNG has no native CTR). The AES
    (ECB of the counter buffer) runs in C and releases the GIL; only the counter
    construction + XOR are Python — same as the existing pyaes-CTR fallback."""
    n = len(data)
    if n == 0:
        return data
    nblocks = (n + 15) // 16
    start = int.from_bytes(counter16, 'big')
    mask = (1 << 128) - 1
    ctrbuf = bytearray(nblocks * 16)
    for i in range(nblocks):
        ctrbuf[i * 16:(i + 1) * 16] = ((start + i) & mask).to_bytes(16, 'big')
    ks = _bc_ecb_encrypt(key, bytes(ctrbuf))[:n]
    return (int.from_bytes(data, 'big') ^ int.from_bytes(ks, 'big')).to_bytes(n, 'big')


# ── Public API (dispatches to whichever backend loaded) ─────────────────────

def _ensure():
    global AVAILABLE
    if AVAILABLE or BACKEND is not None:
        return
    with _init_lock:
        if AVAILABLE or BACKEND is not None:
            return
        if _try_openssl():
            return
        _try_bcrypt()


def aes_cbc_decrypt(key, iv, data):
    """AES-128-CBC decrypt with padding disabled (caller strips PKCS7).
    data length must be a multiple of 16. Returns the decrypted bytes."""
    _ensure()
    if not AVAILABLE:
        raise RuntimeError('native_aes unavailable')
    if BACKEND == 'openssl':
        return _ossl_cbc_decrypt(key, iv, data)
    return _bc_cbc_decrypt(key, iv, data)


def aes_ecb_encrypt(key, data):
    """AES-128-ECB encrypt with padding disabled (used to build a CTR keystream:
    ECB of consecutive counter blocks). data length must be a multiple of 16."""
    _ensure()
    if not AVAILABLE:
        raise RuntimeError('native_aes unavailable')
    if BACKEND == 'openssl':
        return _ossl_ecb_encrypt(key, data)
    return _bc_ecb_encrypt(key, data)


def aes_ctr(key, counter16, data):
    """AES-128-CTR (encrypt == decrypt). counter16 is the initial 128-bit
    counter as big-endian bytes (== block index for offset 0)."""
    _ensure()
    if not AVAILABLE:
        raise RuntimeError('native_aes unavailable')
    if BACKEND == 'openssl':
        return _ossl_ctr(key, counter16, data)
    return _bc_ctr(key, counter16, data)


# Probe at import so AVAILABLE/BACKEND reflect reality for callers that check.
_ensure()
