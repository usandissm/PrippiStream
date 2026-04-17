"""
bump_version.py — Incrementa automaticamente la versione patch in addon.xml.

Uso:
    python tools/bump_version.py            → incrementa patch, stampa la nuova versione
    python tools/bump_version.py --read     → stampa la versione corrente SENZA modificare
"""
import re
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
addon_xml_path = os.path.join(root, 'addon.xml')

with open(addon_xml_path, 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Trova l'attributo version nel tag <addon ...>
m = re.search(r'(<addon\b[^>]*\bversion=")([0-9]+)\.([0-9]+)\.([0-9]+)(")', content)
if not m:
    print('ERROR: version not found in addon.xml', file=sys.stderr)
    sys.exit(1)

major, minor, patch = int(m.group(2)), int(m.group(3)), int(m.group(4))

if '--read' in sys.argv:
    print(f'{major}.{minor}.{patch}')
    sys.exit(0)

new_version = f'{major}.{minor}.{patch + 1}'
new_content = content[:m.start(2)] + new_version + content[m.end(4):]

with open(addon_xml_path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(new_content)

print(new_version)
