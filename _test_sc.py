"""
Standalone test for SC data-page extraction.
Run: python _test_sc.py
"""
import sys, re, json, random, os
sys.path.insert(0, '.')

import warnings
warnings.filterwarnings('ignore')

from lib import requests
import urllib.parse as urlparse
import http.cookiejar as cookielib

SC_URL = 'https://streamingcommunityz.pet/it/archive?type=movie&sort=last_air_date'
WORKERS = [
    {'url': 'quiet-base-584a.ifewfijdqwji.workers.dev', 'token': 'c48912u84u0238u82'},
    {'url': 'jfhofuhueshfuh.fmegvvon.workers.dev',       'token': 'h8fes78f4378hj9ufj'},
    {'url': 'u88929j98eijdjskfkls.lcbtcnob.workers.dev', 'token': 'nfdvsjnsd73ns82'},
]

# Load Kodi cookies (CF clearance)
COOKIES_FILE = os.path.join(os.environ.get('APPDATA',''), 'Kodi', 'userdata', 'addon_data', 'plugin.video.prippistream', 'cookies.dat')

def make_session():
    s = requests.Session()
    if os.path.isfile(COOKIES_FILE):
        cj = cookielib.MozillaCookieJar()
        try:
            cj.load(COOKIES_FILE, ignore_discard=True, ignore_expires=True)
            s.cookies = requests.cookies.RequestsCookieJar()
            for c in cj:
                s.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
            print('[session] loaded %d cookies from %s' % (len(cj._cookies), COOKIES_FILE))
        except Exception as e:
            print('[session] cookie load error:', e)
    else:
        print('[session] no cookies file found at', COOKIES_FILE)
    return s


def fetch_html(url):
    """Try direct (with cookies), then via CF proxy workers."""
    parse = urlparse.urlparse(url)
    domain = parse.netloc
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36'
    session = make_session()

    # direct attempt with CF cookies
    try:
        r = session.get(url, headers={'User-Agent': ua, 'Accept-Language': 'it-IT,it;q=0.9'}, timeout=10, verify=False)
        if r.status_code == 200:
            print('[fetch] direct OK, len=%d' % len(r.text))
            return r.text
        print('[fetch] direct status=%d server=%s' % (r.status_code, r.headers.get('Server','?')))
        print('[fetch] response snippet:', repr(r.text[:300]))
    except Exception as e:
        print('[fetch] direct error:', str(e)[:80])

    # CF worker proxies
    workers = WORKERS[:]
    random.shuffle(workers)
    for w in workers:
        proxy_url = urlparse.urlunparse((parse.scheme, w['url'], parse.path, parse.params, parse.query, ''))
        try:
            r = session.get(proxy_url, headers={
                'User-Agent': ua,
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'it-IT,it;q=0.9',
                'Px-Host': domain,
                'Px-Token': w['token'],
            }, timeout=15, verify=False)
            if r.status_code == 200:
                print('[fetch] worker %s OK, len=%d' % (w['url'][:30], len(r.text)))
                return r.text
            print('[fetch] worker %s status=%d' % (w['url'][:30], r.status_code))
        except Exception as e:
            print('[fetch] worker %s error: %s' % (w['url'][:30], str(e)[:80]))

    return ''


def extract_data_page(html):
    """Replicate _get_data logic from netflixhome.py"""
    PLACEHOLDER = '\x02'
    protected = html.replace('&quot;', PLACEHOLDER)
    m = re.search(r'data-page="([^"]+)"', protected, re.DOTALL)
    if not m:
        print('[extract] no data-page tag found!')
        idx = html.find('data-page')
        if idx >= 0:
            print('[extract] data-page raw:', repr(html[idx:idx+150]))
        return None
    matched = m.group(1).replace(PLACEHOLDER, '&quot;')
    print('[extract] matched len=%d' % len(matched))
    print('[extract] first 100:', repr(matched[:100]))

    # decodeHtmlentities (simplified: just unescape html entities)
    import html as _html
    decoded = _html.unescape(matched)
    print('[extract] decoded len=%d' % len(decoded))

    # _fix_json
    s = decoded
    for i in range(500):
        try:
            data = json.loads(s)
            print('[fix_json] parsed after %d fixes, keys=%s' % (i, list(data.keys())[:5]))
            return data
        except json.JSONDecodeError as e:
            if e.pos is None or e.pos >= len(s):
                print('[fix_json] stuck at iter %d: %s' % (i, str(e)[:80]))
                break
            s = s[:e.pos] + '\\' + s[e.pos:]
    return None


html = fetch_html(SC_URL)
if not html:
    print('FAILED: could not fetch HTML')
    sys.exit(1)

data = extract_data_page(html)
if not data:
    print('FAILED: could not extract data-page JSON')
    sys.exit(1)

props = data.get('props', {})
print('props keys:', list(props.keys())[:10])
titles_raw = props.get('titles', [])
if isinstance(titles_raw, dict):
    titles_raw = titles_raw.get('data', [])
print('titles count:', len(titles_raw))
if titles_raw:
    t = titles_raw[0]
    print('first title:', t.get('name'), '|', t.get('type'), '| id:', t.get('id'))
