import re, os

for res in ['1080i', '720p']:
    path = os.path.join(
        r'C:\Users\USand\Desktop\PROGETTI\PrippiStream',
        'resources', 'skins', 'Default', res, 'NetflixSearch.xml'
    )
    content = open(path, encoding='utf-8').read()
    # Remove old row content that was left after the new panel was inserted
    marker_start = '<!-- \u2500\u2500 Row 0: StreamingCommunity \u2500\u2500 -->'
    marker_end   = '</control> <!-- end grouplist 9010 -->'
    if marker_start in content and marker_end in content:
        idx_s = content.index(marker_start)
        idx_e = content.index(marker_end) + len(marker_end)
        # Also strip the leading whitespace/newline before marker_start
        while idx_s > 0 and content[idx_s - 1] in (' ', '\t'):
            idx_s -= 1
        new_content = content[:idx_s] + content[idx_e:]
        open(path, 'w', encoding='utf-8').write(new_content)
        print(res, 'OK - removed', idx_e - idx_s, 'chars')
    else:
        print(res, 'marker_start found:', marker_start in content)
        print(res, 'marker_end found:', marker_end in content)
