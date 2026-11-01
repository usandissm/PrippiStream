"""Legacy downloads preserve online identities without exposing media credentials."""
from pathlib import Path
import runpy
import unittest

setup = runpy.run_path(str(Path(__file__).with_name('test_live_events.py')), run_name='download_setup')
bridge = setup['bridge']
from core.item import Item

class MetadataTest(unittest.TestCase):
    def test_old_item_url_recovers_episode_and_provider_parent(self):
        item = Item(title='Episodio 2', channel='streamingcommunity', contentType='episode',
                    contentSeason=1, contentEpisodeNumber=2, contentSerieName='Serie',
                    infoLabels={'mediatype': 'episode', 'tvshowtitle': 'Serie'})
        item._app_series_parent = {'title': 'Serie', 'id': '42', 'contentType': 'tvshow'}
        item._app_media_url = 'https://example.invalid/signed'
        item._app_media_headers = {'Cookie': 'secret'}
        result = bridge._download_content({'item_url': item.tourl()})
        self.assertEqual('streamingcommunity', result['channel'])
        self.assertEqual(2, result['infoLabels']['episode'])
        self.assertEqual('42', result['_app_series_parent']['id'])
        self.assertNotIn('_app_media_url', result)
        self.assertNotIn('_app_media_headers', result)

    def test_new_download_retains_full_queue_metadata(self):
        item = Item(title='One', contentType='episode')
        item._app_episode_queue = [{'title': 'One'}, {'title': 'Two'}]
        self.assertEqual(2, len(bridge._download_content({'item_url': item.tourl()})['_app_episode_queue']))

    def test_damaged_legacy_metadata_has_safe_fallback(self):
        result = bridge._download_content({'key':'old', 'title':'Film', 'type':'movie'})
        self.assertEqual('Film', result['title'])
        self.assertEqual('old', result['id'])

if __name__ == '__main__':
    unittest.main()
