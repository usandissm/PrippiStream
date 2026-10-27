"""Offline release gate, usable locally and on GitHub Actions without Kodi."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def same_text(left, right):
    # Git normalizes checkout line endings; the ZIP was built on Windows.
    return left.replace(b'\r\n', b'\n') == right.replace(b'\r\n', b'\n')


def normal_notes(text):
    return '\n'.join(line.strip().lstrip('-• ').strip() for line in text.splitlines() if line.strip())


def main():
    addon = ET.parse(ROOT / 'addon.xml').getroot()
    version = addon.attrib['version']
    feed_bytes = (ROOT / 'docs/addons.xml').read_bytes()
    assert hashlib.md5(feed_bytes).hexdigest() == (ROOT / 'docs/addons.xml.md5').read_text().strip().lower(), 'Feed MD5 mismatch'
    feed = ET.fromstring(feed_bytes)
    entry = next(value for value in feed if value.attrib.get('id') == addon.attrib['id'])
    assert entry.attrib['version'] == version, 'Feed version mismatch'
    spec = importlib.util.spec_from_file_location('release_changelog', ROOT / 'platformcode/changelog.py')
    notes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notes)
    text = (ROOT / 'changelog.txt').read_text(encoding='utf-8-sig')
    approved = next(body for ver, body in notes.parse(text) if ver == version)
    for previous in ('', '1.5.7', '2.0.1', '2.0.2', '2.0.3'):
        assert notes.pending_notes(previous, version, text) == approved, 'Popup includes old/unapproved history'
    news = addon.find('.//news').text or ''
    assert normal_notes(news) == normal_notes(approved), 'Metadata notes differ from popup'
    runtime = ['channels/animeunity.py', 'core/tmdb.py', 'specials/setting.py'] + [
        'platformcode/' + name + '.py' for name in (
            '_fourk', 'prippihome', 'skyepg', 'sportchannels', 'tvchannels', 'changelog',
            'taskpool', 'mediahosting', 'tgevents', 'eventavailability', 'eventcalendar',
            'eventpresentation', 'eventquality', 'eventresolver', 'eventtime')]
    for name in runtime:
        ast.parse((ROOT / name).read_text(encoding='utf-8-sig'), feature_version=(3, 8))
    archive = ROOT / 'docs/plugin.video.prippistream' / ('plugin.video.prippistream-' + version + '.zip')
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None, 'ZIP CRC error'
        names = package.namelist()
        prefix = 'plugin.video.prippistream/'
        for name in names:
            parts = Path(name).parts
            assert name.startswith(prefix) and '..' not in parts, 'Unexpected archive path'
            assert not set(parts).intersection({'private_iptv', 'userdata', '.git', '.codex-artifacts', 'tools', 'tizen'}), 'Private/development payload'
            assert not name.lower().endswith(('.log', '.dmp', '.apk', '.pyc')), 'Diagnostic/build payload: ' + name
            assert Path(name).name not in {'iptv_accounts.json', 'iptv_catalog.json'}, 'Private IPTV catalogue'
        assert any('/event_team_badges/' in name for name in names), 'Portable event badges missing'
        assert ET.fromstring(package.read(prefix + 'addon.xml')).attrib['version'] == version
        for name in runtime:
            assert same_text(package.read(prefix + name), (ROOT / name).read_bytes()), 'Stale packaged runtime: ' + name
        assert same_text(package.read(prefix + 'changelog.txt'), (ROOT / 'changelog.txt').read_bytes())
        assert b'IPTV_LIVE_ENABLED = False' in package.read(prefix + 'platformcode/sportchannels.py'), 'IPTV unexpectedly enabled'
    stable = ROOT / 'docs/plugin.video.prippistream.zip'
    assert hashlib.sha256(stable.read_bytes()).digest() == hashlib.sha256(archive.read_bytes()).digest(), 'Stable direct ZIP is stale'
    print('Kodi ' + version + ': feed, checksum, artwork, runtime, Python 3.8 syntax and latest-only popup verified.')


if __name__ == '__main__':
    main()
