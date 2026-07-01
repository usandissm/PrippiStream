# -*- coding: utf-8 -*-
"""Standalone validation for platformcode/changelog (no Kodi).

Run from repo root:  python tools/test_changelog.py
"""
import os
import sys
import importlib.util as _ilu

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = _ilu.spec_from_file_location(
    "changelog", os.path.join(_ROOT, "platformcode", "changelog.py"))
C = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(C)

SAMPLE = u"""## Prossima
- nuova roba non ancora rilasciata

## 2.0.1
- fix B

## 2.0.0
- fix A
- altra cosa

## 1.0.80
- anime
"""


def test_parse():
    secs = C.parse(SAMPLE)
    assert [v for v, _ in secs] == ['Prossima', '2.0.1', '2.0.0', '1.0.80']
    assert dict(secs)['2.0.0'] == u'- fix A\n- altra cosa'
    print("  parse OK")


def test_full_history_includes_old_versions():
    # Updating to 2.0.1 -> shows the FULL history (2.0.1, 2.0.0, 1.0.80),
    # newest first, NOT just the latest, and excludes the unreleased Prossima.
    out = C.pending_notes('1.0.80', '2.0.1', SAMPLE)
    assert out.startswith('v2.0.1'), out
    assert 'v2.0.0' in out and 'v1.0.80' in out      # old versions included
    assert 'nuova roba' not in out                    # Prossima (unreleased) excluded
    assert out.index('v2.0.1') < out.index('v2.0.0') < out.index('v1.0.80')
    print("  full history incl old versions OK")


def test_fresh_install_full_history():
    out = C.pending_notes('', '2.0.1', SAMPLE)
    assert 'v2.0.1' in out and 'v2.0.0' in out and 'v1.0.80' in out
    print("  fresh install full history OK")


def test_capped_at_current():
    out = C.pending_notes('', '2.0.0', SAMPLE)
    assert 'v2.0.0' in out and 'v1.0.80' in out and 'v2.0.1' not in out
    print("  history capped at current OK")


def test_no_entry_for_current_returns_none():
    # A routine patch with no changelog entry of its own -> no popup.
    assert C.pending_notes('1.0.80', '9.9.9', SAMPLE) is None
    print("  no-entry current -> None OK")


def test_semver_order():
    assert C._vkey('2.0.10') > C._vkey('2.0.9')
    assert C._vkey('2.0') < C._vkey('2.0.1')
    print("  semver ordering OK")


if __name__ == '__main__':
    print("Testing platformcode/changelog ...")
    test_parse()
    test_full_history_includes_old_versions()
    test_fresh_install_full_history()
    test_capped_at_current()
    test_no_entry_for_current_returns_none()
    test_semver_order()
    print("ALL TESTS PASSED")
