# -*- coding: utf-8 -*-
"""
Writes the redesigned NetflixHome.xml  v5
Layout: 1280x720
 - Hero:    y=0..200 (200px)  fanart + brand + categ + title + meta + plot
 - Divider: y=200..203        red bar
 - Rows:    y=203..710 (507px) grouplist
             Each row = wraplist (157px) + spacer (6px dark)  = 163px/row
             ~3 rows visible at once
 - Global arrows: id=5000 (left), id=5001 (right) â€” floating over rows area

Architecture notes:
 - wraplists are DIRECT children of grouplist (no <group> wrappers).
   Kodi lazy-renders off-screen groups; direct wraplists ARE accessible via
   getControl() even when scrolled off-screen.
 - id=100 image has an explicit transparent texture so Kodi registers it
   in the control tree (some versions skip image controls with no texture).
 - Row labels are NOT in the grouplist â€” they appear in the hero CATEG label
   (id=102) updated via Python onFocus. This avoids any label-in-grouplist
   focus-stealing issues.
 - Arrow buttons 5000/5001: keyboard nav returns to grouplist;
   onClick Python scrolls the currently-focused wraplist.

Portrait poster: 94x140, slot 110x157
Navigation:
  close btn 108 <-> row0(2000) <-> row1(2010) <-> ... <-> rowN (loops itself)
MAX_ROWS = 12  wraplist IDs 2000, 2010, ..., 2110
"""
import os

XML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
    'resources', 'skins', 'Default', '720p', 'NetflixHome.xml')

MAX_ROWS = 12
LAST_WL  = 2000 + (MAX_ROWS - 1) * 10   # = 2110

# â”€â”€ Item layouts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ITEM_LAYOUT = '''
                <itemlayout height="157" width="110">
                    <control type="image">
                        <left>8</left><top>4</top>
                        <width>94</width><height>140</height>
                        <texture>$INFO[ListItem.Property(thumbnail)]</texture>
                        <aspectratio>scale</aspectratio>
                    </control>
                    <control type="label">
                        <left>8</left><top>147</top>
                        <width>94</width><height>14</height>
                        <font>font10</font>
                        <textcolor>FF888888</textcolor>
                        <label>$INFO[ListItem.Label]</label>
                        <align>center</align>
                        <truncated>true</truncated>
                    </control>
                </itemlayout>'''

FOCUSED_LAYOUT = '''
                <focusedlayout height="157" width="110">
                    <control type="image">
                        <left>5</left><top>1</top>
                        <width>100</width><height>148</height>
                        <texture colordiffuse="FFE50914">white.png</texture>
                        <animation effect="fade" start="0" end="100" time="180" tween="sine">Focus</animation>
                        <animation effect="fade" start="100" end="0" time="120" tween="sine">Unfocus</animation>
                    </control>
                    <control type="image">
                        <left>8</left><top>4</top>
                        <width>94</width><height>140</height>
                        <texture>$INFO[ListItem.Property(thumbnail)]</texture>
                        <aspectratio>scale</aspectratio>
                        <animation effect="zoom" start="100" end="110" center="auto" time="200" tween="sine" easing="out">Focus</animation>
                        <animation effect="zoom" start="110" end="100" center="auto" time="140" tween="sine" easing="in">Unfocus</animation>
                    </control>
                    <control type="label">
                        <left>8</left><top>147</top>
                        <width>94</width><height>14</height>
                        <font>font10</font>
                        <textcolor>FFFFFFFF</textcolor>
                        <label>$INFO[ListItem.Label]</label>
                        <align>center</align>
                        <truncated>true</truncated>
                    </control>
                </focusedlayout>'''


def row_block(idx):
    wl_id = 2000 + idx * 10
    up_id = 108      if idx == 0          else (2000 + (idx - 1) * 10)
    dn_id = LAST_WL  if idx == MAX_ROWS-1 else (2000 + (idx + 1) * 10)
    return (
        '\n            <!-- â”€â”€ ROW %02d  id=%d â”€â”€ -->' % (idx, wl_id) +
        '\n            <control type="wraplist" id="%d">' % wl_id +
        '\n                <left>0</left><top>0</top>' +
        '\n                <width>1280</width><height>157</height>' +
        '\n                <viewtype>wrap</viewtype>' +
        '\n                <orientation>horizontal</orientation>' +
        '\n                <scrolltime tween="cubic" easing="out">220</scrolltime>' +
        '\n                <onup>%d</onup>' % up_id +
        '\n                <ondown>%d</ondown>' % dn_id +
        ITEM_LAYOUT + FOCUSED_LAYOUT +
        '\n            </control>' +
        # 6px dark spacer â€” colored so it blends with the dark background
        '\n            <control type="image">' +
        '\n                <left>0</left><top>0</top>' +
        '\n                <width>1280</width><height>6</height>' +
        '\n                <texture colordiffuse="FF0A0A0A">white.png</texture>' +
        '\n            </control>'
    )


rows_xml = ''.join(row_block(i) for i in range(MAX_ROWS))

XML = '''\
<?xml version="1.0" encoding="utf-8"?>
<!--
  Netflix-style home  StreamingCommunity  1280x720  v5
  Hero 200px | Red bar 3px | Rows 507px (grouplist, wraplist directly inside)
  Poster 94x140, slot 110x157, zoom+red border on focus
  Row labels: shown only in hero CATEG (id=102), NOT inside grouplist.
  MAX_ROWS=%(max_rows)d  wraplist IDs 2000..%(last_wl)d step 10
  Global arrows: 5000 (left), 5001 (right) â€” floating overlay
-->
<window>
    <defaultcontrol>2000</defaultcontrol>

    <animation type="WindowOpen" reversible="false">
        <effect type="fade" start="0" end="100" time="300"/>
    </animation>
    <animation type="WindowClose" reversible="false">
        <effect type="fade" start="100" end="0" time="200"/>
    </animation>

    <controls>

        <!-- â”€â”€ DARK BASE â”€â”€ -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1280</width><height>720</height>
            <texture colordiffuse="FF0A0A0A">white.png</texture>
        </control>

        <!-- â”€â”€ HERO FANART  id=100 â”€â”€
             Explicit transparent texture so Kodi registers this control
             in the window's control tree (some builds skip id-less images).
        -->
        <control type="image" id="100">
            <left>0</left><top>0</top>
            <width>1280</width><height>200</height>
            <texture colordiffuse="00FFFFFF">white.png</texture>
            <aspectratio>scale</aspectratio>
        </control>
        <!-- Gradient overlays for readability -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1280</width><height>200</height>
            <texture colordiffuse="88000000">white.png</texture>
        </control>
        <control type="image">
            <left>0</left><top>0</top>
            <width>600</width><height>200</height>
            <texture colordiffuse="BB000000">white.png</texture>
        </control>
        <control type="image">
            <left>0</left><top>160</top>
            <width>1280</width><height>40</height>
            <texture colordiffuse="FF0A0A0A">white.png</texture>
        </control>

        <!-- â”€â”€ BRAND  (SC red) â”€â”€ -->
        <control type="label">
            <left>32</left><top>10</top>
            <width>600</width><height>26</height>
            <font>font14</font>
            <textcolor>FFE50914</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label>[B]StreamingCommunity[/B]</label>
        </control>

        <!-- â”€â”€ HERO ROW NAME  id=102 â”€â”€ -->
        <control type="label" id="102">
            <left>32</left><top>38</top>
            <width>900</width><height>18</height>
            <font>font12</font>
            <textcolor>FFAAAAAA</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
        </control>

        <!-- â”€â”€ HERO TITLE  id=103 â”€â”€ -->
        <control type="label" id="103">
            <left>32</left><top>58</top>
            <width>860</width><height>36</height>
            <font>font16</font>
            <textcolor>FFFFFFFF</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
        </control>

        <!-- â”€â”€ HERO META (year / lang)  id=104 â”€â”€ -->
        <control type="label" id="104">
            <left>32</left><top>98</top>
            <width>700</width><height>18</height>
            <font>font12</font>
            <textcolor>FF00CC66</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
        </control>

        <!-- â”€â”€ HERO PLOT  id=105 â”€â”€ -->
        <control type="label" id="105">
            <left>32</left><top>118</top>
            <width>760</width><height>44</height>
            <font>font12</font>
            <textcolor>FFCCCCCC</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
            <wrapwidth>760</wrapwidth>
        </control>

        <!-- â”€â”€ CLOSE BUTTON  id=108 â”€â”€ -->
        <control type="button" id="108">
            <left>1186</left><top>8</top>
            <width>78</width><height>30</height>
            <texturefocus colordiffuse="CCE50914">white.png</texturefocus>
            <texturenofocus colordiffuse="40FFFFFF">white.png</texturenofocus>
            <label>[B]x Esci[/B]</label>
            <font>font12</font>
            <textcolor>FFFFFFFF</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <ondown>2000</ondown>
        </control>

        <!-- â”€â”€ RED DIVIDER y=200 â”€â”€ -->
        <control type="image">
            <left>0</left><top>200</top>
            <width>1280</width><height>3</height>
            <texture colordiffuse="FFE50914">white.png</texture>
        </control>

        <!-- â”€â”€ LOADING OVERLAY  id=200 â”€â”€ -->
        <control type="group" id="200">
            <control type="image">
                <left>0</left><top>0</top>
                <width>1280</width><height>720</height>
                <texture colordiffuse="CC000000">white.png</texture>
            </control>
            <control type="image">
                <left>390</left><top>295</top>
                <width>500</width><height>110</height>
                <texture colordiffuse="FF1A1A1A">white.png</texture>
            </control>
            <control type="image">
                <left>390</left><top>295</top>
                <width>500</width><height>4</height>
                <texture colordiffuse="FFE50914">white.png</texture>
            </control>
            <control type="label">
                <left>390</left><top>320</top>
                <width>500</width><height>44</height>
                <font>font14</font>
                <textcolor>FFFFFFFF</textcolor>
                <shadowcolor>FF000000</shadowcolor>
                <align>center</align>
                <label>[B]Caricamento in corso...[/B]</label>
                <animation effect="fade" start="25" end="100" time="750" tween="sine" loop="true" reversible="true">Visible</animation>
            </control>
            <control type="label">
                <left>390</left><top>372</top>
                <width>500</width><height>20</height>
                <font>font12</font>
                <textcolor>FF555555</textcolor>
                <align>center</align>
                <label>StreamingCommunity...</label>
            </control>
        </control>

        <!-- â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
             ROWS GROUPLIST  y=203  h=507
             DIRECT wraplist children (no <group> wrappers).
             Direct children of grouplist are ALWAYS registered in Kodi's
             control tree, even when scrolled off-screen.
             Per-row labels shown in hero (id=102) via onFocus.
             Dark 6px spacers between rows blend with dark bg.
        â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• -->
        <control type="grouplist" id="9000">
            <left>0</left><top>203</top>
            <width>1280</width><height>507</height>
            <orientation>vertical</orientation>
            <defaultcontrol alwaysfocus="true">2000</defaultcontrol>
            <scrolltime tween="cubic" easing="out">260</scrolltime>
%(rows)s
        </control>

        <!-- â”€â”€ GLOBAL LEFT ARROW  id=5000 (floating overlay, mouse-only) â”€â”€ -->
        <control type="button" id="5000">
            <left>0</left><top>203</top>
            <width>32</width><height>507</height>
            <texturefocus colordiffuse="80000000">white.png</texturefocus>
            <texturenofocus colordiffuse="00000000">white.png</texturenofocus>
            <label>[B]â€¹[/B]</label>
            <font>font14</font>
            <textcolor>CCFFFFFF</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <onup>108</onup>
            <ondown>9000</ondown>
            <onleft>9000</onleft>
            <onright>9000</onright>
        </control>

        <!-- â”€â”€ GLOBAL RIGHT ARROW  id=5001 (floating overlay, mouse-only) â”€â”€ -->
        <control type="button" id="5001">
            <left>1248</left><top>203</top>
            <width>32</width><height>507</height>
            <texturefocus colordiffuse="80000000">white.png</texturefocus>
            <texturenofocus colordiffuse="00000000">white.png</texturenofocus>
            <label>[B]â€º[/B]</label>
            <font>font14</font>
            <textcolor>CCFFFFFF</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <onup>108</onup>
            <ondown>9000</ondown>
            <onleft>9000</onleft>
            <onright>9000</onright>
        </control>

    </controls>
</window>
''' % {'max_rows': MAX_ROWS, 'last_wl': LAST_WL, 'rows': rows_xml}

with open(XML_PATH, 'w', encoding='utf-8') as fh:
    fh.write(XML)
print('Written %d bytes  ->  %s' % (len(XML), XML_PATH))
