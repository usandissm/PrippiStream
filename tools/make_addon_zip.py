import zipfile
import os
import re
import shutil
import hashlib
import json

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

out = os.path.join(docs_dir, f'{addon_id}-{version}.zip')

exclude_names = {'.git', '.github', 'docs', 'tools', 'tests', '__pycache__', '.vscode',
                 '.codex-log-analysis', '.pytest_cache', 'reports',
                 'build', 'release.ps1',
                 '.gitignore', '.gitattributes', '.gitmodules',
                 'PROJECT_STATUS.md', 'ROADMAP_V2.md',
                 '_test_images.py', '_test_sc.py', '_test_sc2.py',
                 '_write_xml.py', '_write_xml.py.bak', '_write_xml2.py', '_write_xml2_v6.py',
                 '_patch_xml_gen.py', '_fix_wraplist_bars.py', '_patch_upnext.py',
                 '_scale_1080i.py', 'PrippiHome_v7.xml', 'StreamingUnityHome_v7.py',
                 # screenshot dello store: il repo GitHub li legge dal git, non
                 # servono nello zip installato (~1,5MB risparmiati)
                 'screenshot-1.png', 'screenshot-2.png', 'screenshot-3.png'}
exclude_ext = {'.pyc', '.pyo', '.zip', '.apk'}
# Development-only content shipped inside vendored libraries. Match complete
# relative path prefixes: generic directory names such as "test" may be used by
# runtime providers elsewhere and must not be excluded globally.
exclude_path_prefixes = (
    'lib/future/backports/test/',
    'lib/chardet/cli/',
    'lib/torrentool/repo/',
)
exclude_paths = {
    'lib/future/README.rst',
    'lib/future/CONTRIBUTING.rst',
}

BOM = b'\xef\xbb\xbf'
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

tmp_out = out + '.tmp'
if os.path.exists(tmp_out):
    os.remove(tmp_out)

with zipfile.ZipFile(tmp_out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for dirpath, dirnames, files in os.walk(root_dir):
        # Rimuovi le cartelle escluse dalla ricerca
        dirnames[:] = sorted(d for d in dirnames if d not in exclude_names)
        for file in sorted(files):
            if file in exclude_names:
                continue
            _, ext = os.path.splitext(file)
            if ext in exclude_ext:
                continue
            filepath = os.path.join(dirpath, file)
            relpath = os.path.relpath(filepath, root_dir).replace('\\', '/')
            if relpath in exclude_paths or relpath.startswith(exclude_path_prefixes):
                continue
            arcname = addon_id + '/' + relpath
            with open(filepath, 'rb') as f:
                data = f.read()
            # Rimuovi BOM dai file XML per compatibilita Kodi
            if ext == '.xml' and data.startswith(BOM):
                data = data[3:]
            info = zipfile.ZipInfo(arcname, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED,
                        compresslevel=9)

    # I dati IPTV restano fuori da Git, ma vanno inseriti entrambi nella
    # release locale: senza catalogo una nuova installazione mostrerebbe solo
    # ClearKey pur avendo il pool account. I client restano indipendenti: ogni
    # play verifica live active_cons/max_connections sul provider.
    kodi_data = os.path.join(os.environ.get('APPDATA', ''), 'Kodi', 'userdata',
                             'addon_data', addon_id)
    seed_specs = (
        ('iptv_accounts.json', 'accounts'),
        ('iptv_catalog.json', 'items'),
    )
    for seed_name, collection_key in seed_specs:
        source = os.path.join(kodi_data, seed_name)
        if not os.path.isfile(source):
            raise RuntimeError('Seed IPTV richiesto ma assente: %s' % source)
        with open(source, 'rb') as seed_file:
            seed_data = seed_file.read()
        try:
            seed_json = json.loads(seed_data.decode('utf-8-sig'))
            seed_count = len(seed_json.get(collection_key, []))
        except Exception as exc:
            raise RuntimeError('Seed IPTV non valido (%s): %s' % (seed_name, exc))
        if not seed_count:
            raise RuntimeError('Seed IPTV vuoto: %s' % seed_name)
        seed_info = zipfile.ZipInfo(
            addon_id + '/resources/data/' + seed_name, ZIP_TIMESTAMP)
        seed_info.compress_type = zipfile.ZIP_DEFLATED
        seed_info.external_attr = 0o600 << 16
        seed_info.create_system = 3
        zf.writestr(seed_info, seed_data, compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9)
        print('Seed IPTV incluso: %s (%d voci)' % (seed_name, seed_count))

os.replace(tmp_out, out)

# Mantieni nella cartella docs solo l'artefatto appena completato. La pulizia
# avviene dopo la sostituzione atomica, quindi una build fallita non cancella
# l'ultima candidate valida.
for _old in os.listdir(docs_dir):
    _old_path = os.path.join(docs_dir, _old)
    if _old.endswith('.zip') and os.path.abspath(_old_path) != os.path.abspath(out):
        os.remove(_old_path)

print(f'ZIP addon creato: {out}')

# Copia di comodita' nella root del progetto: e' il percorso stabile da usare
# per l'installazione manuale su PC e box. Il file .zip e' gia' escluso dal
# contenuto del pacchetto, quindi non puo' finire ricorsivamente nella build.
install_copy = os.path.join(root_dir, os.path.basename(out))
shutil.copy2(out, install_copy)
print(f'ZIP pronto per installazione: {install_copy}')
with open(out, 'rb') as _f:
    digest = hashlib.sha256(_f.read()).hexdigest().upper()
with zipfile.ZipFile(out, 'r') as _zf:
    entries = len(_zf.infolist())
print(f'SHA-256: {digest}')
print(f'Entry: {entries}')

# Rigenera index.html nella cartella docs/plugin.video.prippistream
index_sub = f'''<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html>
 <head>
  <title>Index of /plugin.video.prippistream</title>
 </head>
 <body>
<h1>Index of /plugin.video.prippistream</h1>
<pre>      <a href="?C=N;O=D">Name</a>                                        <a href="?C=M;O=A">Last modified</a>      <a href="?C=S;O=A">Size</a>  <a href="?C=D;O=A">Description</a><hr>      <a href="../">Parent Directory</a>
      <a href="{addon_id}-{version}.zip">{addon_id}-{version}.zip</a>
      <a href="icon.png">icon.png</a>
      <a href="fanart.jpg">fanart.jpg</a>
<hr></pre>
</body></html>'''
with open(os.path.join(docs_dir, 'index.html'), 'w', encoding='utf-8') as f:
    f.write(index_sub)
print('index.html aggiornato in docs/plugin.video.prippistream/')
