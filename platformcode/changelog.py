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
    """FULL release-notes history (newest first) up to *current*, so the update
    popup always shows the older versions too — not just the latest — letting a
    user who skipped releases see everything that was added.

    Returns None when *current* has no changelog entry of its own (e.g. a routine
    patch that shipped no notes) so those releases don't pop up. *last_seen* is
    accepted for API compatibility; the caller (service.py) gates on the version
    actually changing before calling this.
    """
    releases = [(v, n) for (v, n) in parse(text) if _is_release(v)]
    if not releases:
        return None
    cur_k = _vkey(current) if current else None
    # Only notify when THIS version added notes; skip no-note patch releases.
    if cur_k is not None and not any(_vkey(v) == cur_k for (v, _) in releases):
        return None
    releases.sort(key=lambda e: _vkey(e[0]), reverse=True)
    shown = [(v, n) for (v, n) in releases if cur_k is None or _vkey(v) <= cur_k]
    if not shown:
        return None
    return '\n\n'.join(_block(v, n) for (v, n) in shown)
