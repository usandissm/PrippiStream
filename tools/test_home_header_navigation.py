"""Exercise the actual Home action handlers without Kodi or networking."""
import ast
from pathlib import Path
import types
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / 'platformcode/prippihome.py').read_text(encoding='utf-8-sig'))
namespace = {}
for statement in tree.body:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        try:
            namespace[statement.targets[0].id] = ast.literal_eval(statement.value)
        except (ValueError, TypeError):
            pass
namespace.update(_note_touch_action=lambda aid: None, _TOUCH_ACTION_IDS=set(),
                 _is_touch_mode=lambda: False,
                 logger=types.SimpleNamespace(debug=lambda *args: None))
home = next(cls for cls in tree.body if isinstance(cls, ast.ClassDef) and
            any(isinstance(fn, ast.FunctionDef) and fn.name == '_focus_first_content_row' for fn in cls.body))
for fn in home.body:
    if isinstance(fn, ast.FunctionDef) and fn.name in ('_focus_first_content_row', 'onAction'):
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<home-navigation>', 'exec'), namespace)


class Window:
    _focus_first_content_row = namespace['_focus_first_content_row']
    onAction = namespace['onAction']

    def __init__(self, fid, rows, missing=()):
        self.fid = fid
        self.rows_data = [('Row', items) for items in rows]
        self._num_rows = len(rows)
        self._probe = False
        self._last_focused_row = 0
        self.missing = set(missing)
        self.populated = []
        self.heroes = []

    def _mark_nav(self): pass
    def getFocusId(self): return self.fid
    def setFocusId(self, value): self.fid = value
    def getControl(self, value):
        if value in self.missing: raise RuntimeError('Missing XML slot')
        return object()
    def _populate_navigation_window(self, row): self.populated.append(row)
    def _schedule_hero(self, row): self.heroes.append(row)
    def _row_from_nav_fid(self, fid):
        return (fid - 2000) // 10 if 2000 <= fid < 2000 + self._num_rows * 10 else -1
    def down(self): self.onAction(types.SimpleNamespace(getId=lambda: namespace['ACTION_DOWN']))


class HeaderNavigationTests(unittest.TestCase):
    def test_all_header_controls_return_to_cw(self):
        for button in (109, 106, 107, 108):
            with self.subTest(button=button):
                window = Window(button, [[1], [2]])
                window.down()
                self.assertEqual(2000, window.fid)
                self.assertEqual([0], window.heroes)

    def test_empty_cw_and_other_empty_rows_are_skipped(self):
        for button in (109, 106, 107, 108):
            window = Window(button, [[], [], [1], [2]])
            window.down()
            self.assertEqual(2020, window.fid)
            self.assertEqual(2, window._last_focused_row)

    def test_empty_home_keeps_header_focus(self):
        window = Window(109, [[], []])
        window.down()
        self.assertEqual(109, window.fid)
        self.assertEqual([], window.heroes)

    def test_missing_xml_control_does_not_trap_header(self):
        window = Window(107, [[1], [2]], missing=[2000])
        window.down()
        self.assertEqual(2010, window.fid)

    def test_normal_down_between_rows_still_skips_empty_rows(self):
        window = Window(2000, [[1], [], [2]])
        window.down()
        self.assertEqual(2020, window.fid)

    def test_xml_does_not_jump_before_python_handles_down(self):
        xml = ET.parse(ROOT / 'resources/skins/Default/1080i/PrippiHome.xml')
        for button in (109, 106, 107, 108):
            control = xml.find('.//control[@id="%s"]' % button)
            self.assertEqual(str(button), control.findtext('ondown'))


if __name__ == '__main__': unittest.main()
