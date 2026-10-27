"""Exercise actual installed navigation methods without requiring a Kodi GUI."""
import ast
import os
import types
import unittest

ROOT = os.path.join(os.environ['APPDATA'], 'Kodi', 'addons', 'plugin.video.prippistream')
with open(os.path.join(ROOT, 'platformcode', 'prippihome.py'), encoding='utf-8-sig') as stream:
    tree = ast.parse(stream.read())
method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
              and node.name == '_select_row_card')
namespace = dict(ROW_WRAPLIST_BASE=2000, ROW_STEP=10)
exec(compile(ast.Module(body=[method], type_ignores=[]), '<installed navigation>', 'exec'), namespace)


class NavigationTest(unittest.TestCase):
    def test_wrap_first_last_and_last_first_focus_reset(self):
        for target in (118, 0):
            selection = types.SimpleNamespace(pos=0)
            log = []
            def focus(control):
                # Reproduce Kodi's list-focus reset: selecting BEFORE focus lost it.
                selection.pos = 0
                log.append(('focus', control))
            def select(pos):
                selection.pos = pos
                log.append(('select', pos))
            window = types.SimpleNamespace(
                _populate_single_row=lambda row: None,
                getControl=lambda control: types.SimpleNamespace(selectItem=select),
                setFocusId=focus,
                _schedule_hero=lambda row: log.append(('hero', selection.pos)))
            namespace['_select_row_card'](window, 5, target)
            self.assertEqual(target, selection.pos)
            self.assertEqual(('hero', target), log[-1])
            self.assertEqual(5, window._last_focused_row)

    def test_arrow_click_uses_same_selection_and_hero_path(self):
        click = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                     and node.name == 'onClick' and any(isinstance(n, ast.Name) and n.id == 'ARROW_PAGE_SIZE'
                                                       for n in ast.walk(node)))
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == '_select_row_card' for node in ast.walk(click)))


if __name__ == '__main__':
    unittest.main()
