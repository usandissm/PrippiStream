"""Inspect image structure from SC API"""
import sys, os, unittest.mock as mock, warnings, json, html as _html
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')
DATA_PATH = os.path.join(os.environ['APPDATA'], 'Kodi', 'userdata', 'addon_data', 'plugin.video.prippistream')
ADDON_PATH = os.path.abspath('.')
def _tp(p):
    if not isinstance(p, str): return DATA_PATH
    return p.replace('special://home/', ADDON_PATH+os.sep).replace('special://userdata/addon_data/plugin.video.prippistream/', DATA_PATH+os.sep).replace('special://profile/', DATA_PATH+os.sep).replace('special://masterprofile/', DATA_PATH+os.sep)
xbmc_mock = mock.MagicMock(); xbmc_mock.translatePath = _tp
addon_inst = mock.MagicMock()
addon_inst.getAddonInfo.side_effect = lambda k: {'path':ADDON_PATH,'Path':ADDON_PATH,'id':'plugin.video.prippistream','version':'1.0','name':'s4me','profile':DATA_PATH,'Profile':DATA_PATH}.get(k,'')
addon_inst.getSetting.side_effect = lambda k: {'debug':'false','httptools_timeout':'10','chrome_ua_version':'122.0.0.0','language':'it'}.get(k,'')
xba = mock.MagicMock(); xba.Addon.return_value = addon_inst
xbv = mock.MagicMock(); xbv.translatePath = _tp
sys.modules['xbmc']=xbmc_mock; sys.modules['xbmcgui']=mock.MagicMock(); sys.modules['xbmcaddon']=xba; sys.modules['xbmcvfs']=xbv; sys.modules['xbmcplugin']=mock.MagicMock()

from core import httptools

def brace_extract(h):
    m = 'data-page="'; idx = h.find(m)
    if idx < 0: m = "data-page='"; idx = h.find(m)
    if idx < 0: return ''
    s = h.find('{', idx+len(m)); depth = 0
    for i in range(s, len(h)):
        if h[i] == '{': depth += 1
        elif h[i] == '}':
            depth -= 1
            if depth == 0: return h[s:i+1]
    return ''

def strip_html_fields(s):
    result = []; i = 0; field = '"html":"'; flen = len(field)
    while i < len(s):
        if s[i:i+flen] == field:
            result.append('"html":""'); i += flen
            while i < len(s):
                c = s[i]
                if c == '\\' and i+1 < len(s): i += 2
                elif c == '"':
                    j = i+1
                    while j < len(s) and s[j] in ' \t\r\n': j += 1
                    if j < len(s) and s[j] in ',}]': i += 1; break
                    else: i += 1
                else: i += 1
        else: result.append(s[i]); i += 1
    return ''.join(result)

resp = httptools.downloadpage('https://streamingcommunityz.pet/it/movies', ignore_response_code=True)
j = brace_extract(resp.data)
d = _html.unescape(j)
cleaned = strip_html_fields(d)
data = json.loads(cleaned)

cdn_url = data['props'].get('cdn_url', '')
scws_url = data['props'].get('scws_url', '')
print('cdn_url:', cdn_url)
print('scws_url:', scws_url)

# Print image structure for first 3 titles in first slider
for sl in data['props']['sliders'][:1]:
    print('\nSlider:', sl.get('name'))
    for t in sl['titles'][:3]:
        print('  title:', t.get('name'), 'type:', t.get('type'), 'id:', t.get('id'))
        imgs = t.get('images', [])
        print('  images count:', len(imgs))
        for img in imgs[:4]:
            print('    img:', json.dumps(img))
