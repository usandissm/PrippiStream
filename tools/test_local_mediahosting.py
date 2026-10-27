"""Installed MH resolver and SPORT LIVE integration, offline Kodi doubles."""
import ast
import json
import os
import re
import runpy
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

s = runpy.run_path('tools/test_local_event_calendar.py')
s['load']('eventavailability')
mh = s['load']('mediahosting')


class Item:
    def __init__(self, **values):
        self.__dict__.update(values)

    def __getattr__(self, key):
        return ''


class ListItem:
    def __init__(self, path='', **kwargs):
        self.path, self.properties = path, {}

    def setLabel(self, value): self.label = value
    def setContentLookup(self, value): pass
    def setMimeType(self, value): self.mime = value
    def setProperty(self, key, value): self.properties[key] = value
    def setArt(self, value): self.art = value


sys.modules['xbmcgui'] = types.SimpleNamespace(ListItem=ListItem)
with open(os.path.join(s['ROOT'], 'platformcode', 'sportchannels.py'), encoding='utf-8-sig') as stream:
    tree = ast.parse(stream.read())
functions = {'_parse_sport_backend', '_channel_token_valid', 'build_items',
             'resolve_listitem', 'resolve_validated_listitem', '_sport_canonical_title'}
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in functions]
g = dict(re=re, json=json, Item=Item, IPTV_LIVE_ENABLED=False,
         _CODE_SPORT_SKY='sky', _CODE_SPORT_SKY2='sky2', _DADDY_FALLBACK={},
         _is_dead=lambda par: False, _sky_channel_valid=lambda par: True,
         _freeshot_ok=lambda par: False, _daddy_ok=lambda par: False,
         _daddy_channels=lambda row: [], _strip_color=lambda text: re.sub(r'\[/?COLOR[^\]]*\]', '', text).strip(),
         _logo_for=lambda par, remote='': 'poster/' + par,
         logger=types.SimpleNamespace(debug=lambda *args: None, info=lambda *args: None, error=lambda *args: None))
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<installed sport integration>', 'exec'), g)


class MediaHostingTest(unittest.TestCase):
    def setUp(self):
        self.docs = {'sky': {'items': [{'title': 'SPORT UNO', 'myresolve': 'sky@@skysportuno'}]},
                     'sky2': {'items': [{'title': '[COLOR lime]DAZN [MH][/COLOR]', 'myresolve': 'mediahosting@@24'}]}}
        g['_backend_get'] = lambda code: json.dumps(self.docs[code])
        g['_probe_parallel'] = lambda values: [v for v in values if g['_channel_token_valid'](v)]
        g['row_ready'] = lambda row: True

    def test_verified_mh_first_and_exact_provider_id(self):
        with patch.object(mh, 'online', return_value=True) as probe:
            values = g['_parse_sport_backend']()
        self.assertEqual(['dazn_mh', 'skysportuno'], [v['par'] for v in values])
        self.assertEqual('24', values[0]['_validated_code'])
        probe.assert_called_once_with('24')

    def test_offline_mh_absent_other_channels_preserved(self):
        with patch.object(mh, 'online', return_value=False):
            values = g['_parse_sport_backend']()
        self.assertEqual(['skysportuno'], [v['par'] for v in values])

    def test_unrelated_mediahosting_channel_not_imported(self):
        self.docs['sky2']['items'][0]['title'] = 'Another Channel [MH]'
        with patch.object(mh, 'online', return_value=True) as probe:
            values = g['_parse_sport_backend']()
        probe.assert_not_called()
        self.assertEqual(['skysportuno'], [v['par'] for v in values])

    def test_build_items_stable_order_distinct_zona_dazn(self):
        sky = dict(title='Sky Sport Uno', par='skysportuno', kind='sky')
        channel = dict(title='DAZN [MH]', par='dazn_mh', kind='mediahosting', source_code='24',
                       _validated_route='mediahosting', _validated_code='24')
        zona = dict(title='Zona DAZN', par='ZonaDAZN', kind='freeshot')
        g['get_channels'] = lambda row: [sky, channel, dict(channel), zona]
        values = g['build_items']('sport')
        self.assertEqual(['DAZN', 'Sky Sport Uno', 'Zona DAZN'], [v.title for v in values])
        self.assertEqual('24', values[0].sport_source_code)

    def test_validated_and_regular_playback_share_headers(self):
        item = Item(title='DAZN', fulltitle='DAZN', sport_kind='mediahosting', sport_par='dazn_mh',
                    sport_source_code='24', sport_validated_route='mediahosting', sport_validated_code='24')
        for function in ('resolve_listitem', 'resolve_validated_listitem'):
            li = g[function](item)
            self.assertIn('/stream/24/index.m3u8', li.path)
            self.assertEqual('inputstream.adaptive', li.properties['inputstream'])
            headers = parse_qs(li.properties['inputstream.adaptive.manifest_headers'])
            self.assertEqual([mh.REFERER], headers['Referer'])
            self.assertEqual([mh.REFERER.rstrip('/')], headers['Origin'])

    def test_unknown_network_check_is_not_published_as_online(self):
        self.assertFalse(mh.online('24', probe=lambda source: None))
        self.assertTrue(mh.online('24', probe=lambda source: True))

    def test_invalid_stream_id_rejected(self):
        self.assertIsNone(mh.source('../other'))
        self.assertIsNone(mh.source('24?token=other'))
        self.assertIsNone(mh.listitem('', 'DAZN'))


if __name__ == '__main__':
    unittest.main()
