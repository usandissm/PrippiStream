# -*- coding: utf-8 -*-
"""Patch _write_xml.py to remove visible=false from rows"""
import re

f = open('_write_xml.py', encoding='utf-8')
content = f.read()
f.close()

# 1. Remove visible=false from the label control inside row_block
content = content.replace(
    "                <visible>false</visible>\n            </control>\n            <control type=\"wraplist\" id=\"{wl_id}\">",
    "            </control>\n            <control type=\"wraplist\" id=\"{wl_id}\">",
)

# 2. Remove visible=false from the wraplist control
content = content.replace(
    "                <ondown>{down_id}</ondown>\n                <visible>false</visible>{ITEM_LAYOUT}{FOCUSED_LAYOUT}",
    "                <ondown>{down_id}</ondown>{ITEM_LAYOUT}{FOCUSED_LAYOUT}",
)

# 3. Fix focusedlayout width to match itemlayout (142)
content = content.replace(
    '<focusedlayout height="202" width="134">',
    '<focusedlayout height="202" width="142">',
)

open('_write_xml.py', 'w', encoding='utf-8').write(content)
print('Patched _write_xml.py')
