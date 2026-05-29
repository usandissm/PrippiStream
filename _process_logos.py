from PIL import Image
import numpy as np
from collections import deque

def remove_bg(path_in, path_out, resize=None, threshold=235):
    img = Image.open(path_in).convert('RGBA')
    data = np.array(img, dtype=np.uint8)
    h, w = data.shape[:2]
    visited = np.zeros((h, w), dtype=bool)
    q = deque()
    for (r, c) in [(0,0),(0,w-1),(h-1,0),(h-1,w-1)]:
        visited[r,c] = True
        q.append((r,c))
    removed = 0
    while q:
        r, c = q.popleft()
        px = data[r,c]
        if int(px[0]) >= threshold and int(px[1]) >= threshold and int(px[2]) >= threshold:
            data[r,c,3] = 0
            removed += 1
            for dr,dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                nr,nc = r+dr, c+dc
                if 0 <= nr < h and 0 <= nc < w and not visited[nr,nc]:
                    visited[nr,nc] = True
                    q.append((nr,nc))
    result = Image.fromarray(data, 'RGBA')
    if resize:
        result = result.resize(resize, Image.LANCZOS)
    result.save(path_out, 'PNG')
    total = h * w
    print(f"{path_out.split('/')[-1]}: removed={removed}/{total} ({100*removed/total:.1f}%), size={result.size}")

import shutil
dl = 'C:/Users/USand/Downloads'
base = 'C:/Users/USand/Desktop/PROGETTI/PrippiStream/resources/media'
# Square logo: process with threshold 238 (corners are 242-253)
remove_bg(dl+'/logo_loading_screen.png', base+'/logo_prippistream.png', resize=(512,512), threshold=238)
# Banner: already RGBA 71.4% transparent - just copy it
shutil.copy(dl+'/logo_home_ricerca (1).png', base+'/logo_banner.png')
print("Banner copied as-is (already transparent).")
print("Done.")
