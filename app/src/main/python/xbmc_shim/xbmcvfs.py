# -*- coding: utf-8 -*-
# Shim di `xbmcvfs` — I/O file mappato su filesystem reale. API usata dal motore:
# File, Stat, copy, delete, exists, listdir, mkdirs, rename, rmdir.
import os
import shutil

from xbmc import translatePath


def exists(path):
    return os.path.exists(translatePath(path))


def mkdir(path):
    try:
        os.mkdir(translatePath(path)); return True
    except Exception:
        return False


def mkdirs(path):
    try:
        os.makedirs(translatePath(path), exist_ok=True); return True
    except Exception:
        return False


def delete(path):
    try:
        os.remove(translatePath(path)); return True
    except Exception:
        return False


def rmdir(path, force=False):
    try:
        rp = translatePath(path)
        shutil.rmtree(rp) if force else os.rmdir(rp)
        return True
    except Exception:
        return False


def rename(path, newpath):
    try:
        os.replace(translatePath(path), translatePath(newpath)); return True
    except Exception:
        return False


def copy(src, dst):
    try:
        shutil.copyfile(translatePath(src), translatePath(dst)); return True
    except Exception:
        return False


def listdir(path):
    """Ritorna (dirs, files) come Kodi."""
    rp = translatePath(path)
    dirs, files = [], []
    try:
        for name in os.listdir(rp):
            (dirs if os.path.isdir(os.path.join(rp, name)) else files).append(name)
    except Exception:
        pass
    return dirs, files


class Stat(object):
    def __init__(self, path):
        try:
            self._st = os.stat(translatePath(path))
        except Exception:
            self._st = None

    def st_size(self):
        return self._st.st_size if self._st else 0

    def st_mtime(self):
        return self._st.st_mtime if self._st else 0


class File(object):
    def __init__(self, path, mode='r'):
        rp = translatePath(path)
        # Kodi: 'w' scrive, altrimenti legge; sempre in binario per compatibilità.
        binary = 'b'
        if 'w' in mode:
            os.makedirs(os.path.dirname(rp) or '.', exist_ok=True)
            self._f = open(rp, 'w' + binary)
        else:
            self._f = open(rp, 'r' + binary)

    def read(self, num=None):
        data = self._f.read() if num is None else self._f.read(num)
        try:
            return data.decode('utf-8', 'ignore')
        except Exception:
            return data

    def readBytes(self, num=None):
        return self._f.read() if num is None else self._f.read(num)

    def write(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self._f.write(data)
        return True

    def size(self):
        try:
            cur = self._f.tell(); self._f.seek(0, 2); n = self._f.tell(); self._f.seek(cur); return n
        except Exception:
            return 0

    def seek(self, offset, whence=0):
        return self._f.seek(offset, whence)

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
