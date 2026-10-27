"""Regression tests of installed fixes; no remote services, UI or actual logs sent."""
import ast
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

ROOT = os.path.join(os.environ['APPDATA'], 'Kodi', 'addons', 'plugin.video.prippistream')
DATA = tempfile.TemporaryDirectory()
logger = types.SimpleNamespace(info=lambda *args: None, debug=lambda *args: None, error=lambda *args: None)
pkg = types.ModuleType('platformcode')
pkg.config = types.SimpleNamespace(get_data_path=lambda: DATA.name, get_runtime_path=lambda: ROOT)
pkg.logger = logger
pkg.deviceprofile = types.SimpleNamespace(is_low_power=lambda: False, worker_count=lambda *args: 2)
sys.modules['platformcode'] = pkg


def load(name):
    spec = importlib.util.spec_from_file_location('platformcode.' + name, os.path.join(ROOT, 'platformcode', name + '.py'))
    module = importlib.util.module_from_spec(spec)
    setattr(pkg, name, module)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pool = load('taskpool')
fourk = load('_fourk')


def tree(path):
    with open(os.path.join(ROOT, path), encoding='utf-8-sig') as stream:
        return ast.parse(stream.read())


home_tree = tree('platformcode/prippihome.py')


def function(source, name, namespace):
    node = next(n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<installed regression>', 'exec'), namespace)
    return namespace[name]


class Item:
    def __init__(self, **values):
        self.__dict__.update(dict(title='', fulltitle='', thumbnail='', fanart='', infoLabels={}, args={}), **values)

    def __getattr__(self, name):
        return ''

    def clone(self, **values):
        return Item(**dict(self.__dict__, **values))


core = types.ModuleType('core')
core.item = types.ModuleType('core.item')
core.item.Item = Item
sys.modules['core'] = core
sys.modules['core.item'] = core.item


class FixTests(unittest.TestCase):
    def setUp(self):
        fourk._last_attempt = 0
        fourk._ready = False
        fourk._index_by_tmdb = {}
        fourk._building = False
        path = os.path.join(DATA.name, 'fourk_cache.json')
        if os.path.exists(path):
            os.unlink(path)  # test-owned temporary fixture only

    def test_bad_api_payload_uses_expired_cache_without_overwriting(self):
        path = os.path.join(DATA.name, 'fourk_cache.json')
        cache = dict(ts=0, ver=fourk._CACHE_VERSION, movies={'10': dict(stream_url='https://example.invalid/old', name='Old')})
        with open(path, 'w', encoding='utf-8') as stream:
            json.dump(cache, stream)
        with patch.object(fourk, '_api', return_value={'error': 'not a stream list'}):
            fourk.build_4k_index()
        self.assertTrue(fourk._ready)
        self.assertIn(10, fourk._index_by_tmdb)
        self.assertFalse(fourk._building)
        with open(path, encoding='utf-8') as stream:
            self.assertEqual(cache, json.load(stream))

    def test_mixed_stream_payload_and_invalid_rating_do_not_crash(self):
        payload = ['bad', None, {'name': 'Missing id'},
                   {'stream_id': '2', 'name': 'Film 4K (2020)', 'rating': 'not-a-number', 'container_extension': '../bad'}]
        def api(action, params=''):
            return payload if action == 'get_vod_streams' else {'info': {'tmdb_id': '21'}}
        with patch.object(fourk, '_api', side_effect=api):
            fourk.build_4k_index()
        self.assertEqual(0.0, fourk._index_by_tmdb[21]['rating'])
        self.assertEqual('mkv', fourk._index_by_tmdb[21]['ext'])

    def test_cancelled_fourk_does_not_fetch_or_replace_index(self):
        fourk._index_by_tmdb = {5: {'name': 'Existing'}}
        with patch.object(fourk, '_api') as api:
            fourk.build_4k_index(cancel=lambda: True)
        api.assert_not_called()
        self.assertEqual({5: {'name': 'Existing'}}, fourk._index_by_tmdb)

    def test_empty_rebuild_does_not_destroy_last_good_catalogue(self):
        path = os.path.join(DATA.name, 'fourk_cache.json')
        old = dict(ts=0, ver=fourk._CACHE_VERSION, movies={'10': dict(stream_url='https://example.invalid/old')})
        with open(path, 'w', encoding='utf-8') as stream:
            json.dump(old, stream)
        with patch.object(fourk, '_api', return_value=[dict(stream_id=1, name='New 4K')]), \
                patch.object(fourk, '_fetch_vod_info', return_value=(1, None)):
            fourk.build_4k_index()
        self.assertIn(10, fourk._index_by_tmdb)
        with open(path, encoding='utf-8') as stream:
            self.assertEqual(old, json.load(stream))

    def test_fourk_errors_do_not_log_account_or_url_tokens(self):
        messages = []
        log = types.SimpleNamespace(error=messages.append)
        url = 'https://example.invalid/api?username=private&password=secret'
        with patch.object(fourk, 'logger', log), patch.object(fourk, 'urlopen', side_effect=RuntimeError(url)):
            self.assertEqual((None, None), fourk._http_get(url))
        self.assertNotIn('secret', str(messages))
        self.assertNotIn('private', str(messages))

    def test_tmdb_cancellable_path_returns_without_executor(self):
        source = tree('core/tmdb.py')
        g = dict(def_lang='it', config=types.SimpleNamespace(get_setting=lambda *args: True),
                 os=os, logger=logger, deviceprofile=pkg.deviceprofile,
                 set_infoLabels_item=lambda *args: self.fail('cancelled job must not execute'))
        fetch = function(source, 'set_infoLabels_itemlist', g)
        self.assertEqual([], fetch([Item()], forced=True, cancel=lambda: True))

    def test_cache_normalization_drops_bad_ids_and_values(self):
        self.assertEqual({1: {'stream_url': 'https://example.invalid/video'}},
                         fourk._validated_movies({'1': {'stream_url': 'https://example.invalid/video'},
                                                  'oops': {}, '3': 'bad', '4': None}))

    def test_pool_order_and_prompt_cancellation_of_pending_work(self):
        result, complete = pool.map_background(lambda value: value * 2, [3, 1, 2], workers=2)
        self.assertTrue(complete)
        self.assertEqual([6, 2, 4], result)
        cancel, entered, release = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def work(value):
            calls.append(value)
            entered.set()
            release.wait(2)
            return value
        timer = threading.Thread(target=lambda: (entered.wait(1), cancel.set()), daemon=True)
        timer.start()
        started = time.monotonic()
        try:
            result, complete = pool.map_background(work, range(100), workers=1, cancelled=cancel.is_set)
            self.assertFalse(complete)
            self.assertLess(time.monotonic() - started, 0.7)
            self.assertLessEqual(len(calls), 1)
        finally:
            release.set()

    def test_enrichment_snapshot_survives_external_append(self):
        original = [Item(infoLabels={'year': '2020', 'tmdb_id': '1'})]
        def enrich(values, **kwargs):
            original.append(Item(infoLabels={'tmdb_id': '2'}))
        core.tmdb = types.SimpleNamespace(set_infoLabels_itemlist=enrich)
        g = dict(_dl_active=lambda: False, _shutdown_event=threading.Event(),
                 _SC_BAD_TMDB_IDS=set(), logger=logger)
        self.assertTrue(function(home_tree, '_tmdb_enrich_validated', g)(original))
        self.assertEqual(2, len(original))

    def test_replaced_home_row_not_rerendered_after_enrichment(self):
        row = [Item(infoLabels={})]
        owner = types.SimpleNamespace(rows_data=[('Old', row)], _rows_lock=threading.RLock(),
                                      _alive=True, _bg_ui_pause=threading.Event(), _nav_idle=threading.Event(),
                                      _populated={0}, _last_focused_row=0, _write_home_snapshot=lambda: None)
        owner._bg_ui_pause.set(); owner._nav_idle.set()
        rendered = []
        owner._refresh_row_cards = lambda index: rendered.append(index)
        owner._update_hero = lambda index: rendered.append(index)
        def enrich(values):
            owner.rows_data = [('New', [Item()])]
            return True
        g = dict(xbmc=types.SimpleNamespace(Monitor=lambda: types.SimpleNamespace(abortRequested=lambda: False), sleep=lambda _: None),
                 _dl_active=lambda: False, _CW_ROW_LABEL='CW', _shutdown_event=threading.Event(),
                 _tmdb_enrich_validated=enrich, logger=logger)
        function(home_tree, '_bg_enrich_inplace', g)(owner)
        self.assertEqual([], rendered)

    def test_anime_genres_and_years_with_missing_page_are_safe(self):
        source = tree('channels/animeunity.py')
        support = types.SimpleNamespace(info=lambda: None, match=lambda *a, **kw: self.fail('None must not reach parser'))
        for name in ('genres', 'years'):
            g = dict(_ensure_init=lambda: None, _archivio_data=None, support=support)
            self.assertEqual([], function(source, name, g)(Item()))

    def test_anime_genres_args_not_shared_and_malformed_rows_skipped(self):
        source = tree('channels/animeunity.py')
        support = types.SimpleNamespace(info=lambda: None, typo=lambda text, *args: text, thumb=lambda values: values,
            match=lambda *a, **kw: types.SimpleNamespace(match='[{"name":"A"},null,{"name":"B"}]'))
        g = dict(_ensure_init=lambda: None, _archivio_data='page', support=support, json=json)
        values = function(source, 'genres', g)(Item(args={}))
        self.assertEqual('A', values[0].args['genres'][0]['name'])
        self.assertEqual('B', values[1].args['genres'][0]['name'])

    def test_diagnostics_back_and_decline_never_send(self):
        source = tree('specials/setting.py')
        for note, confirmed, expected in ((None, True, None), ('', False, None), ('', True, ''), ('Test', True, 'Test')):
            calls = []
            tools = types.SimpleNamespace(dialog_input=lambda **kw: note,
                                          dialog_yesno=lambda *a, **kw: (calls.append('confirm') or confirmed))
            self.assertEqual(expected, function(source, '_confirm_diagnostic_send', {'platformtools': tools})())
            if note is None:
                self.assertEqual([], calls)

    def test_live_order_events_after_sport_tv_last(self):
        method = next(n for n in ast.walk(home_tree) if isinstance(n, ast.FunctionDef) and n.name == '_assemble_initial')
        start = next(i for i, n in enumerate(method.body) if isinstance(n, ast.Assign) and
                     any(isinstance(t, ast.Name) and t.id == '_row_toggle' for t in n.targets))
        end = next(i for i, n in enumerate(method.body) if isinstance(n, ast.Assign) and
                   any(isinstance(t, ast.Name) and t.id == '_live_block_end' for t in n.targets))
        part = ast.FunctionDef(name='assemble', args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='self')],
            kwonlyargs=[], kw_defaults=[], defaults=[]), body=[ast.Assign(targets=[ast.Name(id='_perf_t', ctx=ast.Store())],
                value=ast.Constant(value=0))] + method.body[start:end + 1], decorator_list=[])
        pkg.tgevents = types.SimpleNamespace(load_cached=lambda: [], build_row_items=lambda _: [])
        g = dict(_row_hidden=lambda _: False, _perf_t=0, perf=types.SimpleNamespace(mark=lambda *a: 0),
                 logger=logger, sportchannels=types.SimpleNamespace(build_items=lambda key: [],
                     row_label=lambda key: {'sky':'SKY', 'sport':'SPORT LIVE', 'tv':'TV'}[key]))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[part], type_ignores=[])), '<live block>', 'exec'), g)
        owner = types.SimpleNamespace(rows_data=[('CW', []), ('Download', [])])
        g['assemble'](owner)
        self.assertEqual(['CW', 'Download', 'SKY', 'SPORT LIVE', 'Eventi Calcio', 'TV'], [r[0] for r in owner.rows_data])

    def test_tv_transient_error_keeps_recent_metadata(self):
        tv = load('tvchannels')
        tv.PROVIDERS = ('discoveryplus',)
        module = types.SimpleNamespace(mainlist=lambda _: [], live=lambda _: [Item(title='Channel', fulltitle='Channel')])
        with patch.object(tv.importlib, 'import_module', return_value=module):
            first = tv.load()
            module.live = lambda _: (_ for _ in ()).throw(ValueError('502'))
            second = tv.load()
        self.assertEqual(['Channel'], [value.title for value in second])
        self.assertIsNot(first[0], second[0])

    def test_home_close_signals_all_workers_before_native_close(self):
        stop, called = threading.Event(), []
        class Base:
            def close(self):
                self.native_closed_after_stop = stop.is_set()
        method = next(n for n in ast.walk(home_tree) if isinstance(n, ast.FunctionDef) and n.name == 'close')
        cls = ast.ClassDef(name='PrippiHomeWindow', bases=[ast.Name(id='Base', ctx=ast.Load())],
                           keywords=[], body=[method], decorator_list=[])
        g = dict(Base=Base, _shutdown_event=stop, logger=logger,
                 sportchannels=types.SimpleNamespace(abort_probes=lambda: called.append('sport')),
                 skyepg=types.SimpleNamespace(abort_prefetch=lambda: called.append('epg')),
                 _fourk_if_loaded=lambda: types.SimpleNamespace(abort_build=lambda: called.append('fourk')))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<installed close>', 'exec'), g)
        owner = g['PrippiHomeWindow']()
        owner._alive, owner._hero_nav_token = True, 0
        owner._nav_idle = threading.Event()
        owner.close()
        self.assertFalse(owner._alive)
        self.assertTrue(owner.native_closed_after_stop)
        self.assertTrue(owner._nav_idle.is_set())
        self.assertEqual(['sport', 'epg', 'fourk'], called)

    def test_empty_genre_cache_retries_after_cooldown(self):
        now = [1000]
        calls = []
        response = [dict(props=dict(genres=[]))]
        channel = types.ModuleType('channels.streamingcommunity')
        channel.host = 'https://example.invalid'
        channel.get_data = lambda url: (calls.append(url) or response[0])
        channels = types.ModuleType('channels')
        channels.streamingcommunity = channel
        g = dict(_br_genre_cache={}, _br_genre_cache_expiry={}, logger=logger,
                 time=types.SimpleNamespace(time=lambda: now[0]), _is_kdrama_genre=lambda *args: False)
        with patch.dict(sys.modules, {'channels': channels, 'channels.streamingcommunity': channel}):
            fetch = function(home_tree, '_br_fetch_genres', g)
            self.assertEqual(1, len(fetch('film')))
            self.assertEqual(1, len(fetch('film')))
            self.assertEqual(1, len(calls))
            response[0] = dict(props=dict(genres=['bad', dict(type='movie', id=1, name='Action')]))
            now[0] += 46
            self.assertEqual(2, len(fetch('film')))

    def test_youtube_failure_does_not_launch_repeatedly(self):
        launches, notifications = [], []
        class Addon:
            def getSetting(self, key): return ''
            def setSetting(self, key, value): pass
        xbmc = types.SimpleNamespace(sleep=lambda _: None, executebuiltin=launches.append)
        gui = types.SimpleNamespace(NOTIFICATION_INFO='info', Dialog=lambda: types.SimpleNamespace(
            notification=lambda *args: notifications.append(args)))
        g = dict(_yt_trailer_retry_after=0, time=types.SimpleNamespace(time=lambda: 1000), logger=logger,
                 xbmc=xbmc, xbmcaddon=types.SimpleNamespace(Addon=lambda *args: Addon()), xbmcgui=gui)
        start = function(home_tree, '_start_trailer', g)
        owner = types.SimpleNamespace(_close_requested=False, _player=types.SimpleNamespace(isPlaying=lambda: False))
        start(owner, 'plugin://plugin.video.youtube/play/?video_id=test')
        start(owner, 'plugin://plugin.video.youtube/play/?video_id=test2')
        self.assertEqual(1, len(launches))
        self.assertEqual(1, len(notifications))
        self.assertEqual(1120, g['_yt_trailer_retry_after'])

    def test_new_home_does_not_clear_old_worker_stop_event(self):
        method = next(n for n in home_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'open_prippi_home')
        assign = next(n for n in method.body if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == '_shutdown_event' for t in n.targets))
        old = threading.Event()
        old.set()
        g = dict(threading=threading, _shutdown_event=old)
        exec(compile(ast.Module(body=[assign], type_ignores=[]), '<home generation>', 'exec'), g)
        self.assertTrue(old.is_set())
        self.assertIsNot(old, g['_shutdown_event'])
        self.assertFalse(g['_shutdown_event'].is_set())

    def test_live_probe_cancellation_survives_reopen(self):
        source = tree('platformcode/sportchannels.py')
        stop, entered, release = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def verify(channel):
            calls.append(channel['par'])
            entered.set()
            release.wait(2)
            return True
        g = dict(_abort_event=stop, threading=threading, time=time, logger=logger,
                 deviceprofile=pkg.deviceprofile, _channel_token_valid=verify)
        probe = function(source, '_probe_parallel', g)
        results = []
        runner = threading.Thread(target=lambda: results.append(probe([{'par': str(i)} for i in range(100)])), daemon=True)
        runner.start()
        try:
            self.assertTrue(entered.wait(1))
            stop.set()
            g['_abort_event'] = threading.Event()  # new Home session
            runner.join(0.7)
            self.assertFalse(runner.is_alive())
            self.assertLessEqual(len(calls), 2)
        finally:
            release.set()


if __name__ == '__main__':
    unittest.main()
