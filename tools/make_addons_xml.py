import hashlib
import re
import os

BOM = b'\xef\xbb\xbf'

# Vai nella cartella root del progetto (uno sopra tools/)
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root)

with open('addon.xml', 'rb') as f:
    addon_data = f.read()
if addon_data.startswith(BOM):
    addon_data = addon_data[3:]

with open('docs/repository.prippistream/addon.xml', 'rb') as f:
    repo_data = f.read()
if repo_data.startswith(BOM):
    repo_data = repo_data[3:]

# Normalizza line endings a LF
addon_data = addon_data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
repo_data  = repo_data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')

addon_content = re.sub(rb'<\?xml[^?]*\?>\s*', b'', addon_data).strip()
repo_content  = re.sub(rb'<\?xml[^?]*\?>\s*', b'', repo_data).strip()

header = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
addons_xml = header + b'<addons>\n' + addon_content + b'\n' + repo_content + b'\n</addons>\n'

with open('docs/addons.xml', 'wb') as f:
    f.write(addons_xml)

md5 = hashlib.md5(addons_xml).hexdigest()
with open('docs/addons.xml.md5', 'w', newline='') as f:
    f.write(md5)

print('addons.xml rigenerato, md5:', md5)
