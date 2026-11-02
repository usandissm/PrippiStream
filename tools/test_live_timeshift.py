"""Exercise the real bridge preference function without starting the engine."""
import ast
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app/src/main/python/bridge.py').read_text(encoding='utf-8')
FN = next(node for node in ast.parse(SOURCE).body
          if isinstance(node, ast.FunctionDef) and node.name == '_playback_preferences')


class PreferencesTest(unittest.TestCase):
    def evaluate(self, enabled=None):
        config = types.ModuleType('platformcode.config')
        config.get_setting = lambda key, default=None: (
            enabled if key == 'app_live_timeshift' and enabled is not None else default)
        package = types.ModuleType('platformcode')
        package.config = config
        namespace = {}
        with patch.dict(sys.modules, {'platformcode': package, 'platformcode.config': config}):
            exec(compile(ast.Module(body=[FN], type_ignores=[]), '<bridge>', 'exec'), namespace)
            return namespace['_playback_preferences']()

    def test_default_disabled(self):
        self.assertIs(self.evaluate()['live_timeshift_enabled'], False)

    def test_enabled_propagates_to_playback(self):
        self.assertIs(self.evaluate(True)['live_timeshift_enabled'], True)
        self.assertIs(self.evaluate(False)['live_timeshift_enabled'], False)

    def test_other_preferences_preserved(self):
        for value in (True, False):
            prefs = self.evaluate(value)
            self.assertIs(prefs['autoplay_next'], True)
            self.assertIs(prefs['fallback_enabled'], True)
            self.assertEqual(prefs['audio_language'], 'it')


if __name__ == '__main__':
    unittest.main()
