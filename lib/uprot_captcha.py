# -*- coding: utf-8 -*-
"""
uprot.net "Captcha Verification" solver for the Maxstream resolver.

uprot.net/msf/<token> now gates the real maxstream.video/uprots/ links behind a
3-digit numeric image captcha (200x50 PNG, coloured digits over coloured noise,
answer validated server-side in the PHP session, regenerated on every failure).

This module reads those 3 digits with a tiny pure-stdlib OCR pipeline (no PIL /
numpy / tesseract — only zlib + struct, both present in Kodi's Python):

    PNG decode -> dark-pixel mask -> connected-component denoise ->
    column segmentation -> per-slot largest blob -> deslant -> grayscale
    template match (kNN over an embedded exemplar bank).

Per-attempt accuracy is ~80%; since a wrong POST simply returns a fresh captcha
in the same session, solve_uprot() retries a few times and reaches ~99%.

Embedded exemplar bank lives in uprot_captcha_data.py.
"""
import re
import struct
import zlib

from platformcode import logger

try:
    from lib.uprot_captcha_data import BANK, GW, GH, SCALE
except Exception:
    try:
        from uprot_captcha_data import BANK, GW, GH, SCALE
    except Exception:
        BANK, GW, GH, SCALE = {}, 14, 22, 8

DARK = 120          # max(R,G,B) below this == "ink" (digit) pixel
KNN = 3

# ----------------------------------------------------------------- PNG decode
def decode_png_rgb(data):
    """Decode a non-interlaced, 8-bit truecolour (colour type 2) PNG.
    Returns (w, h, rgb_bytes). uprot captchas are always this format."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a png')
    off = 8
    w = h = 0
    bd = ct = None
    idat = bytearray()
    while off < len(data):
        ln = struct.unpack('>I', data[off:off + 4])[0]
        typ = data[off + 4:off + 8]
        body = data[off + 8:off + 8 + ln]
        if typ == b'IHDR':
            w, h, bd, ct = struct.unpack('>IIBB', body[:10])
        elif typ == b'IDAT':
            idat += body
        elif typ == b'IEND':
            break
        off += 12 + ln
    if ct != 2 or bd != 8:
        raise ValueError('unsupported png ct=%s bd=%s' % (ct, bd))
    raw = zlib.decompress(bytes(idat))
    stride = w * 3
    out = bytearray(stride * h)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ft = raw[pos]; pos += 1
        line = bytearray(raw[pos:pos + stride]); pos += stride
        if ft == 1:
            for i in range(3, stride):
                line[i] = (line[i] + line[i - 3]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                a = line[i - 3] if i >= 3 else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - 3] if i >= 3 else 0
                b = prev[i]
                c = prev[i - 3] if i >= 3 else 0
                p = a + b - c
                pa = abs(p - a); pb = abs(p - b); pc = abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, bytes(out)

# ---------------------------------------------------------------- mask / blobs
def build_mask(w, h, rgb, dark=DARK):
    m = bytearray(w * h)
    for y in range(h):
        base = y * w * 3
        row = y * w
        for x in range(w):
            i = base + x * 3
            mx = rgb[i]
            if rgb[i + 1] > mx:
                mx = rgb[i + 1]
            if rgb[i + 2] > mx:
                mx = rgb[i + 2]
            if mx < dark:
                m[row + x] = 1
    return m

def connected_components(w, h, m):
    seen = bytearray(w * h)
    comps = []
    for sy in range(h):
        for sx in range(w):
            i0 = sy * w + sx
            if not m[i0] or seen[i0]:
                continue
            stack = [i0]; seen[i0] = 1; pts = []
            x0 = x1 = sx; y0 = y1 = sy
            while stack:
                i = stack.pop(); pts.append(i)
                cy, cx = divmod(i, w)
                if cx < x0: x0 = cx
                if cx > x1: x1 = cx
                if cy < y0: y0 = cy
                if cy > y1: y1 = cy
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx = cx + dx; ny = cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if m[j] and not seen[j]:
                                seen[j] = 1; stack.append(j)
            comps.append({'pts': pts, 'bbox': (x0, y0, x1 + 1, y1 + 1),
                          'area': len(pts)})
    return comps

def denoise(w, h, m):
    """Drop speck and line-like (swoosh / band) components; keep digit blobs."""
    out = bytearray(w * h)
    for c in connected_components(w, h, m):
        x0, y0, x1, y1 = c['bbox']
        bw = x1 - x0; bh = y1 - y0; area = c['area']
        fill = area / float(bw * bh)
        if area < 14:
            continue
        if bw > 40 or bh > 44:
            continue
        if fill < 0.16 and area < 90:
            continue
        for i in c['pts']:
            out[i] = 1
    return out

def column_groups(w, h, m, gap=3, min_mass=20, min_width=4):
    col = [0] * w
    for x in range(w):
        c = 0
        for y in range(h):
            c += m[y * w + x]
        col[x] = c
    groups = []
    x = 0
    while x < w:
        if col[x] > 0:
            x0 = x; mass = 0; g = 0
            while x < w:
                if col[x] > 0:
                    mass += col[x]; x += 1; g = 0
                else:
                    g += 1
                    if g > gap:
                        break
                    x += 1
            x1 = x - g
            if mass >= min_mass and (x1 - x0) >= min_width:
                groups.append((x0, x1, mass))
        else:
            x += 1
    return groups

def largest_blob_in_slot(w, h, m, x0, x1, pad=2):
    a = max(0, x0 - pad); b = min(w, x1 + pad)
    sub = bytearray(w * h)
    for y in range(h):
        base = y * w
        for x in range(a, b):
            sub[base + x] = m[base + x]
    comps = connected_components(w, h, sub)
    if not comps:
        return sub

    def score(c):
        _, by0, _, by1 = c['bbox']
        bh = by1 - by0
        return c['area'] + 3 * bh - 1.5 * abs((by0 + by1) / 2.0 - h / 2.0)

    best = max(comps, key=score)
    out = bytearray(w * h)
    for i in best['pts']:
        out[i] = 1
    return out

# --------------------------------------------------------------- normalisation
def _crop_rows(w, h, m, x0, x1):
    ys = [y for y in range(h) for x in range(x0, x1) if m[y * w + x]]
    if not ys:
        return None
    return min(ys), max(ys) + 1

def _best_shear(pts, bh):
    if not pts:
        return 0.0
    cy = bh / 2.0
    best = 0.0; bestscore = -1
    s = -0.6
    while s <= 0.6001:
        cols = {}
        for (x, y) in pts:
            nx = int(round(x + s * (y - cy)))
            cols[nx] = cols.get(nx, 0) + 1
        score = sum(v * v for v in cols.values())
        if score > bestscore:
            bestscore = score; best = s
        s += 0.1
    return best

def normalize_gray(w, h, m, x0, x1, gw=GW, gh=GH, scale=SCALE):
    yr = _crop_rows(w, h, m, x0, x1)
    if not yr:
        return None
    y0, y1 = yr
    bw = x1 - x0; bh = y1 - y0
    if bw < 2 or bh < 4:
        return None
    pts = []
    for yy in range(y0, y1):
        base = yy * w
        for xx in range(x0, x1):
            if m[base + xx]:
                pts.append((xx - x0, yy - y0))
    if not pts:
        return None
    shear = _best_shear(pts, bh)
    cy = bh / 2.0
    grid = bytearray(bw * bh)
    for (x, y) in pts:
        nx = int(round(x - shear * (y - cy)))
        if 0 <= nx < bw:
            grid[y * bw + nx] = 1
    xs = [i % bw for i in range(bw * bh) if grid[i]]
    minx = min(xs); maxx = max(xs)
    ew = maxx - minx + 1
    if ew < 1:
        ew = bw
    feat = []
    for gy in range(gh):
        ra = gy * bh // gh; rb = (gy + 1) * bh // gh
        if rb <= ra:
            rb = ra + 1
        for gx in range(gw):
            ca = minx + gx * ew // gw; cb = minx + (gx + 1) * ew // gw
            if cb <= ca:
                cb = ca + 1
            s = 0; n = 0
            for yy in range(ra, rb):
                rbase = yy * bw
                for xx in range(ca, cb):
                    if 0 <= xx < bw:
                        s += grid[rbase + xx]
                    n += 1
            feat.append(int(round(scale * s / float(n))) if n else 0)
    return tuple(feat)

# ----------------------------------------------------------------- recognition
def featurize(png_bytes, n=4):
    """Return up to *n* grayscale feature vectors (left-to-right) for a captcha.
    uprot has used both 3- and 4-digit codes; *n* is read from the page's
    pattern="[0-9]{n}" by solve_uprot so we segment into the right count."""
    w, h, rgb = decode_png_rgb(png_bytes)
    m = build_mask(w, h, rgb)
    cm = denoise(w, h, m)
    groups = column_groups(w, h, cm)
    groups = sorted(groups, key=lambda g: -g[2])[:n]
    groups = sorted(groups, key=lambda g: g[0])
    if len(groups) != n and groups:
        x0 = min(g[0] for g in groups); x1 = max(g[1] for g in groups)
        step = (x1 - x0) / float(n)
        groups = [(int(x0 + k * step), int(x0 + (k + 1) * step), 0) for k in range(n)]
    feats = []
    for x0, x1, _ in groups:
        gm = largest_blob_in_slot(w, h, cm, x0, x1)
        nb = normalize_gray(w, h, gm, 0, w)
        if nb:
            feats.append(nb)
    return feats

def _classify(feat):
    dists = []
    for ch, exs in BANK.items():
        for ex in exs:
            d = 0
            for i in range(len(feat)):
                d += abs(feat[i] - ex[i])
            dists.append((d, ch))
    if not dists:
        return None
    dists.sort()
    votes = {}
    for d, ch in dists[:KNN]:
        votes[ch] = votes.get(ch, 0) + 1
    return max(votes.items(), key=lambda kv: kv[1])[0]

def _auto_digit_count(png_bytes, default=4):
    """Best-effort digit count from the IMAGE itself — fallback used when the
    page's pattern="[0-9]{n}" is unavailable. Counts the well-separated dark
    blobs (digit columns) so the solver adapts even if uprot changes the digit
    count (3↔4↔5) AND the surrounding HTML."""
    try:
        w, h, rgb = decode_png_rgb(png_bytes)
        cm = denoise(w, h, build_mask(w, h, rgb))
        groups = column_groups(w, h, cm)
        if not groups:
            return default
        mx = max(g[2] for g in groups)
        n = sum(1 for g in groups if g[2] >= max(35, 0.12 * mx))
        return n if 2 <= n <= 6 else default
    except Exception:
        return default


def solve_image(png_bytes, n=None):
    """Return the n-digit code string, or None. When *n* is None the digit count
    is auto-detected from the image (so the OCR self-adapts to 3/4/5 digits)."""
    try:
        if not n:
            n = _auto_digit_count(png_bytes)
        feats = featurize(png_bytes, n)
    except Exception as e:
        logger.error('uprot_captcha.solve_image decode error: %s' % e)
        return None
    if len(feats) != n:
        return None
    code = ''.join(_classify(f) or '' for f in feats)
    return code if len(code) == n else None

# ----------------------------------------------------------------- HTTP flow
import base64 as _b64

_IMG_RE = re.compile(r'data:image/png;base64,([A-Za-z0-9+/=]+)')
_TOKEN_RE = re.compile(r'maxstream\.video/uprots/')
# How many digits the captcha expects, e.g. pattern="[0-9]{4}". uprot has used
# both 3 and 4; read it so the OCR segments into the right number of glyphs.
_NDIGITS_RE = re.compile(r"""pattern=["']\[0-9\]\{(\d+)\}""")


def _digit_count(html, default=4):
    m = _NDIGITS_RE.search(html or '')
    if m:
        try:
            n = int(m.group(1))
            if 2 <= n <= 8:
                return n
        except Exception:
            pass
    return default


def _has_links(html):
    return bool(html) and bool(_TOKEN_RE.search(html)) \
        and 'Captcha Verification' not in html


def _rate_limited(html):
    return bool(html) and 'Request limit exceeded' in html


def _img_bytes(html):
    m = _IMG_RE.search(html or '')
    if not m:
        return None
    try:
        return _b64.b64decode(m.group(1))
    except Exception:
        return None


def solve_uprot(msf_url, downloadpage, max_attempts=6):
    """Drive the uprot.net captcha and return the HTML that contains the real
    maxstream.video/uprots/ links, or None.

    `downloadpage` is core.httptools.downloadpage (shares a global cookie jar,
    so the PHPSESSID set by the first GET is reused by the POSTs)."""
    hdr = {'Referer': 'https://uprot.net/'}
    post_hdr = {'Referer': msf_url, 'Origin': 'https://uprot.net',
                'X-Requested-With': 'XMLHttpRequest'}
    try:
        html = downloadpage(msf_url, headers=hdr).data or ''
    except Exception as e:
        logger.error('uprot_captcha.solve_uprot GET error: %s' % e)
        return None

    if _has_links(html):
        return html
    if _rate_limited(html):
        logger.info('uprot_captcha: rate-limited (503) -> fall back')
        return None

    for attempt in range(max_attempts):
        if _rate_limited(html):
            logger.info('uprot_captcha: rate-limited mid-flow -> fall back')
            return None
        img = _img_bytes(html)
        if not img:
            # not a captcha page and no links -> give up (or refresh once)
            if attempt == 0:
                html = downloadpage(msf_url, headers=hdr).data or ''
                continue
            return None
        # Digit count from the page pattern (reliable); None -> auto-detect from
        # the image. Either way the solver self-adapts if uprot changes 3↔4↔5.
        code = solve_image(img, _digit_count(html, default=None))
        logger.info('uprot_captcha attempt %d -> code=%s' % (attempt + 1, code))
        if not code:
            # unreadable image -> fetch a fresh one
            html = downloadpage(msf_url, headers=hdr).data or ''
            continue
        try:
            html = downloadpage(msf_url, post={'captcha': code},
                                headers=post_hdr).data or ''
        except Exception as e:
            logger.error('uprot_captcha.solve_uprot POST error: %s' % e)
            return None
        if _has_links(html):
            logger.info('uprot_captcha solved in %d attempt(s)' % (attempt + 1))
            return html
        # wrong code: response carries a fresh captcha image -> loop
    logger.info('uprot_captcha: giving up after %d attempts' % max_attempts)
    return None
