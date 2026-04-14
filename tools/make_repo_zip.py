import zipfile
import os

src = r'c:\Users\USand\Desktop\PROGETTI\PrippiStream\docs\repository.prippistream'
out = r'c:\Users\USand\Desktop\PROGETTI\PrippiStream\docs\repository.prippistream.zip'

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(src):
        for file in files:
            filepath = os.path.join(root, file)
            arcname = 'repository.prippistream/' + file
            zf.write(filepath, arcname)
            print('Added:', arcname)

print('ZIP creato:', out)
