import zipfile
import os

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(root_dir, 'docs', 'repository.prippistream')
out = os.path.join(root_dir, 'docs', 'repository.prippistream.zip')

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(src):
        for file in files:
            filepath = os.path.join(root, file)
            arcname = 'repository.prippistream/' + file
            zf.write(filepath, arcname)
            print('Added:', arcname)

print('ZIP creato:', out)
