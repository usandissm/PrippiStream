# -*- coding: utf-8 -*-
"""Standalone validation for the pure helpers in download_manager (no Kodi).

Run from repo root:  python tools/test_download_manager.py
"""
import os
import sys
import types
import importlib.util as _ilu

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _load(name, relpath):
    spec = _ilu.spec_from_file_location(name, os.path.join(_ROOT, relpath))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_C = _load('download_crypto', os.path.join('core', 'download_crypto.py'))
_H = _load('hls_downloader', os.path.join('core', 'hls_downloader.py'))

# Shim packages so download_manager's top-level imports resolve.
core_pkg = types.ModuleType('core'); core_pkg.__path__ = []
core_pkg.hls_downloader = _H
core_pkg.download_crypto = _C
sys.modules['core'] = core_pkg
sys.modules['core.hls_downloader'] = _H
sys.modules['core.download_crypto'] = _C

pc_pkg = types.ModuleType('platformcode'); pc_pkg.__path__ = []
log_mod = types.ModuleType('platformcode.logger')
log_mod.error = lambda m: None
log_mod.info = lambda m: None
cfg_mod = types.ModuleType('platformcode.config')
cfg_mod.get_setting = lambda *a, **k: ''
cfg_mod.get_data_path = lambda: os.path.join(_ROOT, '_tmp_data')
db_mod = types.ModuleType('platformcode.downloads_db')
sys.modules['platformcode'] = pc_pkg
sys.modules['platformcode.logger'] = log_mod
sys.modules['platformcode.config'] = cfg_mod
sys.modules['platformcode.downloads_db'] = db_mod
pc_pkg.logger = log_mod; pc_pkg.config = cfg_mod; pc_pkg.downloads_db = db_mod

M = _load('download_manager', os.path.join('platformcode', 'download_manager.py'))


class FakeItem(object):
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_pick_variant():
    V = [{'height': 1080, 'url': 'a'}, {'height': 720, 'url': 'b'}, {'height': 480, 'url': 'c'}]
    assert M._pick_variant(V, 0)['height'] == 1080      # best
    assert M._pick_variant(V, 720)['height'] == 720     # exact
    assert M._pick_variant(V, 1000)['height'] == 720    # highest <= target
    assert M._pick_variant(V, 200)['height'] == 480     # below all -> lowest
    assert M._pick_variant([], 720) is None
    print("  _pick_variant OK")


def test_sanitize():
    assert M._sanitize('One Piece: Strong World?/x') == 'One Piece_ Strong World__x'
    assert M._sanitize('') == 'download'
    assert len(M._sanitize('x' * 500)) <= 120
    print("  _sanitize OK")


def test_entry_from_item():
    movie = FakeItem(contentType='movie', fulltitle='Inception', thumbnail='t.jpg')
    e = M._entry_from_item(movie)
    assert e['type'] == 'movie' and e['key'].startswith('dlmovie_')
    assert e['title'] == 'Inception'
    assert M._output_basename(e) == 'Inception'

    ep = FakeItem(contentType='episode', contentSerieName='One Piece',
                  contentSeason=1, contentEpisodeNumber=5, contentTitle='Romance Dawn',
                  thumbnail='t.jpg')
    e2 = M._entry_from_item(ep)
    assert e2['type'] == 'episode'
    assert e2['season'] == 1 and e2['episode'] == 5
    assert e2['show_key'] == 'dlshow_one_piece'
    assert e2['key'] == 'dlshow_one_piece_s1e5'
    assert e2['title'] == 'Romance Dawn'
    assert M._output_basename(e2) == 'One Piece S01E05'

    # Two episodes of the same show share show_key (grouping).
    ep2 = FakeItem(contentType='episode', contentSerieName='One Piece',
                   contentSeason=1, contentEpisodeNumber=6)
    assert M._entry_from_item(ep2)['show_key'] == e2['show_key']
    print("  _entry_from_item / _output_basename OK")


def test_markup_stripped_in_title():
    it = FakeItem(contentType='movie', fulltitle='[B]Matrix[/B] [COLOR red]x[/COLOR]')
    e = M._entry_from_item(it)
    assert e['title'] == 'Matrix x', e['title']
    print("  markup stripping OK")


def test_byterange_playlist():
    segs = [[6.0, 1000], [6.0, 1000], [3.0, 500]]
    pl = M._media_playlist('v', segs, 15.0)
    assert '#EXT-X-VERSION:4' in pl
    assert '#EXT-X-TARGETDURATION:6' in pl                # ceil(max dur)
    # Contiguous byte ranges, one per segment, all pointing at the same resource.
    assert '#EXT-X-BYTERANGE:1000@0' in pl
    assert '#EXT-X-BYTERANGE:1000@1000' in pl
    assert '#EXT-X-BYTERANGE:500@2000' in pl
    assert pl.splitlines().count('v') == 3
    assert pl.rstrip().endswith('#EXT-X-ENDLIST')
    # No segment info → single-segment fallback (old behaviour, not seekable).
    pl2 = M._media_playlist('a0', None, 12.0)
    assert '#EXT-X-BYTERANGE' not in pl2
    assert '#EXTINF:12.000,' in pl2 and pl2.splitlines().count('a0') == 1
    print("  byte-range playlist OK")


if __name__ == '__main__':
    print("Testing platformcode/download_manager (pure helpers) ...")
    test_pick_variant()
    test_sanitize()
    test_entry_from_item()
    test_markup_stripped_in_title()
    test_byterange_playlist()
    print("ALL TESTS PASSED")
