"""
bump_version.py — Versione di addon.xml + "timbro" del changelog per la release.

Uso:
    python tools/bump_version.py            -> calcola la versione di release,
                                               timbra il changelog, sincronizza <news>,
                                               stampa la versione
    python tools/bump_version.py --read     -> stampa la versione corrente SENZA modificare

Versione: di norma incrementa la patch (X.Y.Z -> X.Y.Z+1). MA se la versione in
addon.xml e' gia' PIU' AVANTI di quella pubblicata (docs/addons.xml) — cioe' il
maintainer ha "pinnato" a mano una nuova minor/major come 1.1.0 — la mantiene
com'e' (cosi' si possono pubblicare versioni .0). I rilasci di routine
(addon.xml == pubblicata) ottengono il solito patch+1.

Changelog: se changelog.txt inizia con una sezione "## Prossima" (o "## Unreleased"),
la rinomina con la versione di release e copia le sue note dentro <news> di addon.xml.
Senza sezione "Prossima", changelog e <news> non vengono toccati.
"""
import re
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
addon_xml_path = os.path.join(root, 'addon.xml')
changelog_path = os.path.join(root, 'changelog.txt')

with open(addon_xml_path, 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Trova l'attributo version nel tag <addon ...>
m = re.search(r'(<addon\b[^>]*\bversion=")([0-9]+)\.([0-9]+)\.([0-9]+)(")', content)
if not m:
    print('ERROR: version not found in addon.xml', file=sys.stderr)
    sys.exit(1)

major, minor, patch = int(m.group(2)), int(m.group(3)), int(m.group(4))
current = f'{major}.{minor}.{patch}'

if '--read' in sys.argv:
    print(current)
    sys.exit(0)


def _vtuple(s):
    mm = re.search(r'(\d+)\.(\d+)\.(\d+)', s or '')
    return tuple(int(x) for x in mm.groups()) if mm else (0, 0, 0)


# Versione gia' pubblicata (da docs/addons.xml). Se addon.xml e' gia' avanti
# (release .0 pinnata a mano), NON bumpare; altrimenti patch+1. Fallback sicuro
# al patch+1 se non si riesce a leggere la versione pubblicata.
published = None
try:
    with open(os.path.join(root, 'docs', 'addons.xml'), 'r', encoding='utf-8') as f:
        dx = f.read()
    pm = re.search(r'id="plugin\.video\.prippistream"[^>]*version="([0-9]+\.[0-9]+\.[0-9]+)"', dx)
    if pm:
        published = pm.group(1)
except Exception:
    published = None

if published and _vtuple(current) > _vtuple(published):
    new_version = current        # versione pinnata avanti rispetto alla pubblicata: tienila
else:
    new_version = f'{major}.{minor}.{patch + 1}'

content = content[:m.start(2)] + new_version + content[m.end(4):]


def _xml_escape(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ── Timbra il changelog e sincronizza <news> ────────────────────────────────
try:
    with open(changelog_path, 'r', encoding='utf-8') as f:
        cl = f.read()
except FileNotFoundError:
    cl = None

if cl is not None:
    secs = list(re.finditer(r'^##\s+(.+?)\s*$', cl, re.MULTILINE))
    if secs and secs[0].group(1).strip().lower() in ('prossima', 'unreleased', '[prossima]'):
        head = secs[0]
        body_end = secs[1].start() if len(secs) > 1 else len(cl)
        body = cl[head.end():body_end].strip('\n').rstrip()
        cl = cl[:head.start(1)] + new_version + cl[head.end(1):]
        with open(changelog_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(cl)
        if body:
            news = '<news>%s\n</news>' % _xml_escape(body)
            content = re.sub(r'<news>.*?</news>', lambda _m: news, content,
                             count=1, flags=re.DOTALL)

with open(addon_xml_path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)

print(new_version)
