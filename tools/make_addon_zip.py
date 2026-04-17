import zipfile
import os
import re

# Percorso root relativo a questo script (funziona su Linux/Windows/GitHub Actions)
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Leggi versione da addon.xml
with open(os.path.join(root_dir, 'addon.xml'), 'r', encoding='utf-8-sig') as _f:
    _xml = _f.read()
_m = re.search(r'<addon\b[^>]*\bversion="([0-9]+\.[0-9]+\.[0-9]+)"', _xml)
version = _m.group(1) if _m else '0.0.1'

addon_id = 'plugin.video.prippistream'
docs_dir = os.path.join(root_dir, 'docs', addon_id)
os.makedirs(docs_dir, exist_ok=True)

# Rimuovi vecchi ZIP prima di crearne uno nuovo
for _old in os.listdir(docs_dir):
    if _old.endswith('.zip'):
        os.remove(os.path.join(docs_dir, _old))

out = os.path.join(docs_dir, f'{addon_id}-{version}.zip')

exclude_names = {'.git', '.github', 'docs', 'tools', 'tests', '__pycache__', '.vscode',
                 'build', 'release.ps1',
                 '_test_images.py', '_test_sc.py', '_test_sc2.py',
                 '_write_xml.py', '_write_xml.py.bak', '_write_xml2.py', '_write_xml2_v6.py',
                 '_patch_xml_gen.py', '_fix_wraplist_bars.py', '_patch_upnext.py',
                 '_scale_1080i.py', 'NetflixHome_v7.xml', 'StreamingUnityHome_v7.py'}
exclude_ext = {'.pyc', '.pyo', '.zip'}

BOM = b'\xef\xbb\xbf'

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, files in os.walk(root_dir):
        # Rimuovi le cartelle escluse dalla ricerca
        dirnames[:] = [d for d in dirnames if d not in exclude_names]
        for file in files:
            if file in exclude_names:
                continue
            _, ext = os.path.splitext(file)
            if ext in exclude_ext:
                continue
            filepath = os.path.join(dirpath, file)
            relpath = os.path.relpath(filepath, root_dir).replace('\\', '/')
            arcname = addon_id + '/' + relpath
            # Rimuovi BOM dai file XML per compatibilita Kodi
            if ext == '.xml':
                with open(filepath, 'rb') as f:
                    data = f.read()
                if data.startswith(BOM):
                    data = data[3:]
                zf.writestr(arcname, data)
            else:
                zf.write(filepath, arcname)

print(f'ZIP addon creato: {out}')
