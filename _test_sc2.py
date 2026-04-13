"""
Direct SC page test using addon's httptools + html.parser approach.
"""
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('KODI_ADDON_DATA_PATH', os.path.join(os.environ['APPDATA'], 'Kodi', 'userdata', 'addon_data', 'plugin.video.prippistream'))

import warnings; warnings.filterwarnings('ignore')

# ---- Minimal Kodi mock BEFORE any addon import ----
import unittest.mock as mock
DATA_PATH = os.path.join(os.environ['APPDATA'], 'Kodi', 'userdata', 'addon_data', 'plugin.video.prippistream')
ADDON_PATH = os.path.abspath('.')

xbmc_mock = mock.MagicMock()
def _tp(p):
    if not isinstance(p, str): return DATA_PATH
    return (p.replace('special://home/', ADDON_PATH + os.sep)
              .replace('special://userdata/addon_data/plugin.video.prippistream/', DATA_PATH + os.sep)
              .replace('special://profile/', DATA_PATH + os.sep)
              .replace('special://masterprofile/', DATA_PATH + os.sep))
xbmc_mock.translatePath = _tp

xbmcaddon_mock = mock.MagicMock()
addon_inst = mock.MagicMock()
addon_inst.getAddonInfo.side_effect = lambda k: {
    'path': ADDON_PATH, 'Path': ADDON_PATH,
    'id': 'plugin.video.prippistream', 'Id': 'plugin.video.prippistream',
    'version': '1.0.0', 'Version': '1.0.0',
    'name': 'Stream4me', 'Name': 'Stream4me',
    'profile': DATA_PATH, 'Profile': DATA_PATH,
}.get(k, '')
addon_inst.getSetting.side_effect = lambda k: {
    'debug': 'false', 'httptools_timeout': '10',
    'chrome_ua_version': '122.0.0.0',
    'language': 'it',
}.get(k, '')
xbmcaddon_mock.Addon.return_value = addon_inst

xbmcvfs_mock = mock.MagicMock()
xbmcvfs_mock.translatePath = _tp

sys.modules['xbmc'] = xbmc_mock
sys.modules['xbmcgui'] = mock.MagicMock()
sys.modules['xbmcaddon'] = xbmcaddon_mock
sys.modules['xbmcvfs'] = xbmcvfs_mock
sys.modules['xbmcplugin'] = mock.MagicMock()

# ---- Now import addon modules ----
try:
    from platformcode import config, logger
    from core import httptools
    print("[OK] imports successful")
except Exception as e:
    print("[FAIL] import error:", e)
    import traceback; traceback.print_exc()
    sys.exit(1)

from html.parser import HTMLParser
import json, re

def extract_data_page(html):
    """
    Extract the data-page JSON using brace-balanced counting.
    Regex and html.parser both stop at the first bare " (e.g. xmlns="...")
    inside the SVG content embedded in the JSON strings.
    Brace counting ignores quotes entirely and finds the balanced JSON object.
    """
    marker = 'data-page="'
    idx = html.find(marker)
    if idx < 0:
        # try single-quoted
        marker = "data-page='"
        idx = html.find(marker)
    if idx < 0:
        return None
    start = html.find('{', idx + len(marker))
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(html)):
        c = html[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return html[start:i+1]
    return None

def strip_html_fields(s):
    """
    Remove all "html":"..." JSON string values that contain SVG/HTML with bare ".
    A bare " in SVG attributes is followed by HTML chars (letters, /, >, backslash),
    NOT by JSON structural chars (,  }  ]). We use this to find the REAL closing ".
    """
    result = []
    i = 0
    field = '"html":"'
    while i < len(s):
        if s[i:i+len(field)] == field:
            result.append('"html":""')
            i += len(field)
            # Skip the value, finding the real JSON-closing " 
            while i < len(s):
                c = s[i]
                if c == '\\' and i + 1 < len(s):
                    i += 2  # valid JSON escape sequence \X — skip both
                elif c == '"':
                    # Check if this " is the real JSON-closing one:
                    # the real closing " is followed by ,  }  ]  or whitespace+those
                    j = i + 1
                    while j < len(s) and s[j] in ' \t\r\n':
                        j += 1
                    if j < len(s) and s[j] in ',}]':
                        i += 1  # consume closing "
                        break
                    else:
                        i += 1  # bare " inside SVG content, skip
                else:
                    i += 1
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


def fix_json(s):
    """
    Fix unescaped " inside JSON string values.
    json.JSONDecodeError.pos points to the char AFTER the premature closing ".
    When that char is not " itself (e.g. it's \ or a letter), the actual
    problem is the " at pos-1 which we must escape instead.
    """
    for i in range(2000):
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            pos = getattr(e, 'pos', None)
            if pos is None or pos >= len(s):
                print("[fix_json] stuck after %d iters: %s" % (i, str(e)[:80]))
                break
            # If char at pos is not ", the premature-close " is at pos-1
            if s[pos] != '"' and pos > 0 and s[pos - 1] == '"':
                pos = pos - 1
            s = s[:pos] + '\\' + s[pos:]
    return None

def test_url(url):
    print("\n=== Testing:", url, "===")
    resp = httptools.downloadpage(url, ignore_response_code=True)
    html = resp.data or ''
    print("Status:", getattr(resp, 'code', '?'), "| HTML len:", len(html))

    if not html:
        print("EMPTY response!")
        return

    # Check if it's the CF challenge page
    if 'data-page' not in html:
        print("NO data-page in HTML!")
        print("First 500 chars:", repr(html[:500]))
        return

    json_str = extract_data_page(html)
    if not json_str:
        print("extract_data_page returned None!")
        idx = html.find('data-page')
        print("Raw snippet:", repr(html[idx:idx+200]))
        return

    print("extracted json len:", len(json_str))
    print("first 100:", repr(json_str[:100]))

    import html as _html
    decoded = _html.unescape(json_str)
    print("decoded len:", len(decoded))

    # Strip "html" fields (SVG banner content with thousands of unescaped ")
    # We need sliders data, not SVG imagery. Replace "html":"<svg ...>" with ""
    # Use char scanning since the value contains unescaped " (regex can't handle it)
    decoded_clean = strip_html_fields(decoded)
    print("decoded_clean len:", len(decoded_clean))
    data = fix_json(decoded_clean)
    if not data:
        print("FAILED to parse JSON")
        print("decoded around pos 460:", repr(decoded[455:485]))
        return

    props = data.get('props', {})
    print("props keys:", list(props.keys()))
    sliders = props.get('sliders', [])
    print("sliders count:", len(sliders))
    if sliders:
        for sl in sliders[:3]:
            titles = sl.get('titles', [])
            if isinstance(titles, dict):
                titles = titles.get('data', [])
            print("  slider:", sl.get('name','?'), "| titles:", len(titles))
            if titles:
                t = titles[0]
                print("    first:", t.get('name'), '-', t.get('type'), 'id:', t.get('id'))

for url in ['https://streamingcommunityz.pet/it/movies', 'https://streamingcommunityz.pet/it/tv-shows']:
    try:
        test_url(url)
    except Exception as e:
        print("ERROR:", e)
        import traceback; traceback.print_exc()
