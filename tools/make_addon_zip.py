import zipfile
import os

root_dir = r'c:\Users\USand\Desktop\PROGETTI\PrippiStream'
out = os.path.join(root_dir, 'docs', 'plugin.video.prippistream', 'plugin.video.prippistream-1.0.0.zip')

exclude_names = {'.git', 'docs', 'tools', 'tests', '__pycache__', '.vscode',
                 'release.ps1', '_test_images.py', '_test_sc.py', '_test_sc2.py',
                 '_write_xml.py', '_write_xml.py.bak', '_write_xml2.py', '_write_xml2_v6.py',
                 '_patch_xml_gen.py'}
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
            arcname = 'plugin.video.prippistream/' + relpath
            # Rimuovi BOM dai file XML per compatibilita Kodi
            if ext == '.xml':
                with open(filepath, 'rb') as f:
                    data = f.read()
                if data.startswith(BOM):
                    data = data[3:]
                zf.writestr(arcname, data)
            else:
                zf.write(filepath, arcname)

print('ZIP addon creato:', out)
