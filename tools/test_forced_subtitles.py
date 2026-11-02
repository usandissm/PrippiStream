import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('subtitlepolicy', Path(__file__).resolve().parents[1] / 'platformcode/subtitlepolicy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class ForcedSubtitlesTest(unittest.TestCase):
    def test_prefers_real_italian_forced_flag(self):
        self.assertEqual(policy.italian_forced([
            dict(index=0, language='ita', name='Italian'),
            dict(index=1, language='eng', isforced=True),
            dict(index=2, language='ita', isforced=True)]), 2)
    def test_old_offline_labels(self):
        self.assertEqual(policy.italian_forced(['English (Forced)', 'Italian (Forced)']), 1)
        self.assertEqual(policy.italian_forced([dict(language='it', label='Italiano Forzati')]), 0)
    def test_no_arbitrary_full_subtitles(self):
        self.assertIsNone(policy.italian_forced(['Italian', 'English Forced']))


if __name__ == '__main__': unittest.main()
