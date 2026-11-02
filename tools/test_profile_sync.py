"""Hermetic profile tests; --live additionally checks the deployed service with synthetic data only."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'lib')]
LIVE = '--live' in sys.argv
if LIVE:
    sys.argv.remove('--live')
settings = {}
data_path = ''
config = types.ModuleType('platformcode.config')
config.get_data_path = lambda: data_path
config.get_setting = lambda key, default=None, **kw: settings.get(key, default)
config.set_setting = lambda key, value: settings.__setitem__(key, value)
sys.modules['platformcode.config'] = config
logger = types.ModuleType('platformcode.logger')
for method in ('info', 'error', 'debug'):
    setattr(logger, method, lambda *args, **kwargs: None)
sys.modules['platformcode.logger'] = logger
# Skip only core/__init__'s GUI bootstrap; exercise the real Item codec.
core = types.ModuleType('core')
core.__path__ = [str(ROOT / 'core')]
sys.modules['core'] = core
from platformcode import profile_sync as sync, profile_kodi as kodi, watch_history
from core.item import Item


def entry(episode=1, stamp=None, position=20000):
    return dict(item=dict(channel='streamingcommunity', action='findvideos', title='Episode',
        url='https://example.com/titles/123/season/1/episode/' + str(episode),
        contentType='episode', contentSerieName='Synthetic Series',
        infoLabels=dict(tmdb_id='100', mediatype='episode', tvshowtitle='Synthetic Series',
                        season=1, episode=episode),
        _app_series_parent=dict(title='Synthetic Series', url='https://example.com/titles/123',
            infoLabels=dict(tmdb_id='100', mediatype='tvshow'))),
        position_ms=position, duration_ms=100000, updated_at=stamp or int(time.time()*1000)-1000)


class MemoryServer:
    def __init__(self):
        self.profiles = {}
        self.offline = False
    def __call__(self, profile, body=None):
        if self.offline:
            raise OSError('offline')
        records = self.profiles.get(profile, {})
        if body is not None:
            if body.get('require_new') and profile in self.profiles:
                raise ValueError('profile_exists')
            if profile not in self.profiles and not body.get('create'):
                raise ValueError('missing')
            self.profiles[profile] = records
            for op in body['operations']:
                previous = records.get(op['id'])
                order = lambda r: (r['modified_at'], r['deleted'], r['op_id'])
                if previous is None or order(op) > order(previous):
                    records[op['id']] = copy.deepcopy(op)
        return dict(schema=1, exists=profile in self.profiles, revision=len(records),
                    server_time=int(time.time()*1000), records=list(copy.deepcopy(records).values()))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        global data_path
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        data_path = self.temp.name
        settings.clear()
        self.server = MemoryServer()
        self.patcher = patch.object(sync, '_request', self.server)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
    def device(self, label):
        global data_path
        data_path = os.path.join(self.temp.name, label)
        os.makedirs(data_path, exist_ok=True)
    def test_join_existing_does_not_upload_another_history(self):
        sync.exchange('test', [], True, [entry()])
        self.device('second')
        unrelated = entry(); unrelated['item']['infoLabels']['tmdb_id']='200'
        unrelated['item']['_app_series_parent']['infoLabels']['tmdb_id']='200'
        result = sync.exchange('test', [], True, [unrelated])
        self.assertEqual(len(result['entries']), 1)
        self.assertEqual(result['entries'][0]['item']['_profile_id'], 'series:tmdb:100')
    def test_create_requires_a_unique_name_and_join_never_creates(self):
        with self.assertRaisesRegex(ValueError, 'Profilo non trovato'):
            sync.exchange('missing', [], True, mode='join')
        self.assertNotIn('missing', self.server.profiles)
        sync.exchange('unique', [], True, [entry()], mode='create')
        self.device('second')
        with self.assertRaisesRegex(ValueError, 'Nome già utilizzato'):
            sync.exchange('unique', [], True, [entry(2)], mode='create')
        result = sync.exchange('unique', [], True, mode='join')
        self.assertEqual(result['entries'][0]['item']['infoLabels']['episode'], 1)
    def test_linking_unions_titles_and_keeps_the_furthest_local_episode(self):
        now = int(time.time()*1000)
        sync.exchange('test', [], True, [entry(1, stamp=now-2000)], mode='create')
        self.device('new-device')
        # The more advanced episode wins at linking even if watched earlier.
        advanced = entry(4, stamp=now-50000)
        movie = dict(item=dict(channel='hd4me', action='findvideos', title='Synthetic Movie',
            contentType='movie', infoLabels=dict(tmdb_id='999', mediatype='movie')),
            position_ms=30000, duration_ms=90000, updated_at=now-5000)
        result = sync.exchange('test', [], True, [advanced, movie], mode='join')
        self.assertEqual(len(result['entries']), 2)
        series = next(e for e in result['entries'] if e['item']['_profile_id']=='series:tmdb:100')
        self.assertEqual(series['item']['infoLabels']['episode'], 4)
        self.device('third')
        result = sync.exchange('test', [], True, [entry(2)], mode='join')
        series = next(e for e in result['entries'] if e['item']['_profile_id']=='series:tmdb:100')
        self.assertEqual(series['item']['infoLabels']['episode'], 4)
    def test_linking_does_not_restore_an_old_removed_title(self):
        now = int(time.time()*1000)
        original = entry(stamp=now-5000)
        sync.exchange('test', [], True, [original], mode='create')
        sync.exchange('test', [dict(original, deleted=True, updated_at=now-2000)])
        self.device('second')
        self.assertEqual(sync.exchange('test', [], True, [original], mode='join')['entries'], [])
    def test_offline_outbox_is_durable_and_deletion_wins_over_stale_device(self):
        base = entry(stamp=int(time.time()*1000)-5000)
        first = sync.exchange('test', [], True, [base])['entries']
        self.device('second')
        sync.exchange('test', [], True)
        removed = dict(first[0], deleted=True, updated_at=base['updated_at']+3000)
        self.server.offline = True
        with self.assertRaises(OSError): sync.exchange('test', [removed])
        self.assertTrue(sync._load('test')['pending'])
        self.server.offline = False
        self.assertEqual(sync.exchange('test', [removed])['entries'], [])
        self.device('first-stale')
        sync.exchange('test', [], True)
        self.assertEqual(sync.exchange('test', [base])['entries'], [])
    def test_rewind_and_next_episode_use_event_time_not_max_progress(self):
        base = entry(stamp=int(time.time()*1000)-5000)
        sync.exchange('test', [], True, [base])
        rewind = entry(stamp=base['updated_at']+1000, position=10000)
        self.assertEqual(sync.exchange('test', [rewind])['entries'][0]['position_ms'], 10000)
        advanced = entry(2, stamp=base['updated_at']+2000, position=0)
        result = sync.exchange('test', [advanced])['entries']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['item']['infoLabels']['episode'], 2)
    def test_imported_snapshot_is_idempotent_and_profiles_are_isolated(self):
        result = sync.exchange('first', [], True, [entry()])
        before = copy.deepcopy(self.server.profiles)
        sync.exchange('first', result['entries'])
        self.assertEqual(before, self.server.profiles)
        self.assertEqual(sync.exchange('second', [], True)['entries'], [])
    def test_corrupt_outbox_is_never_replaced(self):
        path = Path(sync._path('test')); path.parent.mkdir(parents=True)
        path.write_text('{BROKEN', encoding='utf8')
        with self.assertRaises(ValueError): sync.exchange('test', [])
        self.assertEqual(path.read_text(), '{BROKEN')
    def test_private_fields_are_removed_and_admin_routes_rejected(self):
        raw = entry()['item']; raw.update(_app_media_url='file:///secret', headers={'Cookie':'secret'})
        raw['url'] = 'https://example.com/title?token=private&id=12|Cookie=secret'
        clean = sync.clean_item(raw)
        self.assertNotIn('headers', clean); self.assertNotIn('_app_media_url', clean)
        self.assertEqual(clean['url'], 'https://example.com/title?id=12')
        self.assertEqual(sync._url('http://192.168.1.1/file'), '')
        self.assertEqual(sync._url('https://example.com/movie.m3u8'), '')
        with self.assertRaises(ValueError): sync.clean_item(dict(raw, channel='setting'))
    def test_kodi_export_import_matches_android_identity_and_keeps_original_cw(self):
        android = entry(2)
        raw = android['item']; raw['_app_series_parent']['channel']='streamingcommunity'
        watch_history.save_progress('tv_100', 'Synthetic Series', '', '', 20, 100,
            Item(**raw).tourl(), show_url='https://example.com/titles/123', season=1, episode=2)
        original = Path(watch_history._get_path()).read_bytes()
        self.assertTrue(kodi.sync('test', connect=True, activate=True))
        rows = watch_history.get_all()
        self.assertEqual(len(rows), 1)
        restored = kodi._export(rows[0])
        self.assertEqual(sync.pack(restored)['id'], sync.pack(android)['id'])
        self.assertEqual(restored['item']['infoLabels']['episode'], 2)
        settings['cw_profile']=''
        self.assertEqual(Path(watch_history._get_path()).read_bytes(), original)
    def test_kodi_compare_apply_refuses_to_clobber_save_during_http(self):
        kodi.sync('test', connect=True, activate=True)
        def race(profile, body=None):
            response = self.server(profile, body)
            if body is None:
                raw = entry()['item']
                watch_history.save_progress('tv_100', 'Synthetic Series', '', '', 30, 100, Item(**raw).tourl())
            return response
        with patch.object(sync, '_request', race):
            self.assertFalse(kodi.sync())
        self.assertEqual(watch_history.get('tv_100')['time_watched'], 30)
    def test_kodi_removal_is_uploaded_and_not_resurrected(self):
        sync.exchange('test', [], True, [entry(stamp=int(time.time()*1000)-5000)])
        kodi.sync('test', connect=True, activate=True)
        watch_history.remove('tv_100')
        self.assertTrue(kodi._snapshot('test')['deletions'])
        kodi.sync()
        self.assertTrue(self.server.profiles['test']['series:tmdb:100']['deleted'])
        self.assertEqual(watch_history.get_all(), [])
    @unittest.skipUnless(LIVE, 'pass --live for a synthetic online integration check')
    def test_live_cross_device_roundtrip(self):
        self.patcher.stop()
        profile = 'qa-' + uuid.uuid4().hex[:20]
        row = entry(stamp=int(time.time()*1000)-2000)
        response = sync.exchange(profile, [], True, [row], mode='create')
        self.assertEqual(len(response['entries']), 1)
        self.device('live-second')
        with self.assertRaisesRegex(ValueError, 'Nome già utilizzato'):
            sync.exchange(profile, [], True, mode='create')
        response = sync.exchange(profile, [], True, mode='join')
        self.assertEqual(response['entries'][0]['item']['infoLabels']['episode'], 1)
        deleted = dict(response['entries'][0], deleted=True, updated_at=int(time.time()*1000))
        self.assertEqual(sync.exchange(profile, [deleted])['entries'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
