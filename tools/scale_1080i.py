import os, re

SCALE = 1.5
SRC = r'C:\Users\USand\Desktop\PROGETTI\PrippiStream\resources\skins\Default\720p'
DST = r'C:\Users\USand\Desktop\PROGETTI\PrippiStream\resources\skins\Default\1080i'

SCALE_TAGS = {'left','top','right','bottom','width','height','posx','posy',
              'textoffsetx','textoffsety','itemgap','scrollheight','spinwidth','spinheight'}

SCALE_ATTRS = {'height', 'width', 'left', 'top', 'right', 'bottom'}

def scale_int(val):
    v = val.strip()
    if '%' in v or not re.match(r'^-?[0-9]+$', v):
        return v
    return str(int(round(int(v) * SCALE)))

def scale_content(content):
    lines = content.split('\n')
    result = []
    in_animation = 0
    for line in lines:
        in_animation += len(re.findall(r'<animation', line))
        if in_animation > 0:
            result.append(line)
            in_animation -= len(re.findall(r'</animation>', line))
            continue

        # Scale child tag values: <width>180</width>
        def tag_replacer(m):
            tag = m.group(1).lower()
            val = m.group(2)
            if tag in SCALE_TAGS:
                return '<{0}>{1}</{0}>'.format(m.group(1), scale_int(val))
            return m.group(0)
        line = re.sub(r'<([A-Za-z]+)>(-?[0-9]+(?:%)?)<\/[A-Za-z]+>', tag_replacer, line)

        # Scale inline attributes: height="570" or width='180'
        def attr_replacer(m):
            attr = m.group(1).lower()
            val = m.group(2)
            suffix = m.group(3)
            if attr in SCALE_ATTRS:
                return '{0}="{1}"{2}'.format(m.group(1), scale_int(val), suffix)
            return m.group(0)
        # Matches: attrname="123" or attrname='123' followed by space, >, or /
        line = re.sub(r'([A-Za-z]+)=["\'](-?[0-9]+)["\']([  \t>/])', attr_replacer, line)

        result.append(line)
    return '\n'.join(result)

os.makedirs(DST, exist_ok=True)
files = [f for f in os.listdir(SRC) if f.endswith('.xml')]
count = 0
for fname in files:
    with open(os.path.join(SRC, fname), 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    scaled = scale_content(content)
    with open(os.path.join(DST, fname), 'w', encoding='utf-8') as f:
        f.write(scaled)
    count += 1
    print('Scalato:', fname)

print('Totale: {} file XML scalati (tag + attributi inline) da 720p a 1080i (x1.5)'.format(count))
