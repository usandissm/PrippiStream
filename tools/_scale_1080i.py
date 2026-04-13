# -*- coding: utf-8 -*-
"""Scale 720p skin XMLs to 1080i (1920x1080) for Kodi.
Scales both child-tag dimensions (<width>X</width>) and
itemlayout/focusedlayout attribute dimensions (width="X").
"""
import re
import sys

FACTOR = 1.5


def scale_xml(src, dst, factor=FACTOR):
    with open(src, encoding='utf-8') as f:
        content = f.read()

    # 1) Scale child tags: <left>, <top>, <width>, <height>, <wrapwidth>
    def scale_tag(m):
        tag = m.group(1)
        val = int(m.group(2))
        new_val = int(round(val * factor))
        return '<%s>%d</%s>' % (tag, new_val, tag)

    content = re.sub(r'<(left|top|width|height|wrapwidth)>(\d+)</', scale_tag, content)

    # 2) Scale itemlayout / focusedlayout ATTRIBUTES: height="X"  width="X"
    #    These define wraplist slot sizes — omitting them causes item overlap in 1080i.
    def scale_layout_attrs(m):
        tag   = m.group(1)
        attrs = m.group(2)

        def scale_attr(am):
            attr = am.group(1)
            val  = int(am.group(2))
            return '%s="%d"' % (attr, int(round(val * factor)))

        new_attrs = re.sub(r'(height|width)="(\d+)"', scale_attr, attrs)
        return '<%s %s>' % (tag, new_attrs)

    content = re.sub(r'<(itemlayout|focusedlayout)([^>]+)>', scale_layout_attrs, content)

    # 3) Update resolution comment
    content = content.replace('1280x720', '1920x1080')

    with open(dst, 'w', encoding='utf-8') as f:
        f.write(content)

    print('scaled %s -> %s' % (src, dst))


if __name__ == '__main__':
    scale_xml(
        'resources/skins/Default/720p/NetflixHome.xml',
        'resources/skins/Default/1080i/NetflixHome.xml',
    )
    scale_xml(
        'resources/skins/Default/720p/DetailWindow.xml',
        'resources/skins/Default/1080i/DetailWindow.xml',
    )
    print('done')
