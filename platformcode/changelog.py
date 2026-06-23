# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# changelog — cumulative release notes for the update popup
#
# Notes live in changelog.txt at the addon root, newest version first, each as a
# "## <version>" section followed by its bullet lines. On update we show the
# notes for EVERY released version the user hasn't seen yet (not just the latest)
# so someone who skipped releases still learns what changed.
#
# An optional leading "## Prossima" (Unreleased) section holds notes not yet
# released; CI (tools/bump_version.py) renames it to the real version at release
# time. Such non-release sections are ignored at runtime.
#
# Kept Kodi-independent so it can be unit-tested standalone.
# ------------------------------------------------------------

from __future__ import unicode_literals

import re

_SECTION = re.compile(r'^##\s+(.+?)\s*$', re.MULTILINE)
_RELEASE = re.compile(r'^\d+\.\d+')


def _vkey(version):
    """Sort key from a version string: '2.0.0' -> (2, 0, 0). Missing parts are
    treated as 0 so '2.0' < '2.0.1'."""
    nums = re.findall(r'\d+', version or '')
    return tuple(int(n) for n in nums) if nums else (0,)


def parse(text):
    """Return [(version, notes_text), ...] in file order. Each entry's notes are
    the lines between its '## ' header and the next one (trailing/leading blank
    lines stripped)."""
    out = []
    if not text:
        return out
    heads = list(_SECTION.finditer(text))
    for i, h in enumerate(heads):
        version = h.group(1).strip()
        body_end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        notes = text[h.end():body_end].strip('\n').rstrip()
        out.append((version, notes))
    return out


def _is_release(version):
    return bool(_RELEASE.match(version or ''))


def _block(version, notes):
    return ('v%s\n%s' % (version, notes)) if notes else ('v%s' % version)


def pending_notes(last_seen, current, text):
    """Combined notes (newest first) for released versions newer than *last_seen*
    and not above *current*. Returns None when there is nothing to show.

    On a fresh install (no *last_seen*) returns only the latest released entry,
    so the user gets a welcome note instead of the whole history.
    """
    releases = [(v, n) for (v, n) in parse(text) if _is_release(v)]
    if not releases:
        return None
    releases.sort(key=lambda e: _vkey(e[0]), reverse=True)

    if not last_seen:
        v, n = releases[0]
        return _block(v, n)

    seen_k = _vkey(last_seen)
    cur_k = _vkey(current) if current else _vkey(releases[0][0])
    show = [(v, n) for (v, n) in releases if seen_k < _vkey(v) <= cur_k]
    if not show:
        return None
    return '\n\n'.join(_block(v, n) for (v, n) in show)
