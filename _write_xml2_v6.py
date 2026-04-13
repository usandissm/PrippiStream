# -*- coding: utf-8 -*-
"""
Writes NetflixHome.xml  v6 — StreamingUnity look & feel
Layout 1280x720:
  Nav/hero  y=0..260    (260px)
  Divider   y=260..263  (3px:  1px neutral + 2px red)
  Rows      y=263..720  (457px, grouplist)
              Each row: 157px wraplist + 8px dark spacer = 165px
              ~2.8 rows visible at once (cinematic)

Design reference: streamingunity.biz
  - Near-black warm base:     #0D0D0D
  - Accent red:               #E50914
  - Availability green:       #22C55E
  - Description grey:         #B3B3B3
  - Hero left-to-right fade:  5 overlay bands (darkest left, fanart right)
  - Focus: white frame + red 3px top accent + poster zoom 100→107%
  - CTA visuals in hero: red "RIPRODUCI" + semi-transparent "INFO"
  - Nav bar overlay: 50px semi-transparent top strip
  - Loading screen: branded card with pulsing animation
"""
import os

XML_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'resources', 'skins', 'Default', '720p', 'NetflixHome.xml'
)

MAX_ROWS = 12
HERO_H   = 260
DIV_H    = 3
ROWS_Y   = HERO_H + DIV_H      # 263
ROWS_H   = 720 - ROWS_Y         # 457
LAST_WL  = 2000 + (MAX_ROWS - 1) * 10   # 2110

# ── Per-item layouts (unfocused + focused) ─────────────────────────────────────
# Slot: 110 × 157  |  Poster: 94 × 144 (unfocused), 102 × 147 (focused)
# Focus style: white outer frame + 3px red top accent + poster zoom
ITEM_LAYOUT = '''
                <itemlayout height="157" width="110">
                    <control type="image">
                        <left>8</left><top>3</top>
                        <width>94</width><height>144</height>
                        <texture>$INFO[ListItem.Property(thumbnail)]</texture>
                        <aspectratio>scale</aspectratio>
                    </control>
                    <control type="label">
                        <left>8</left><top>149</top>
                        <width>94</width><height>13</height>
                        <font>font10</font>
                        <textcolor>FFAAAAAA</textcolor>
                        <label>$INFO[ListItem.Label]</label>
                        <align>center</align>
                        <truncated>true</truncated>
                    </control>
                </itemlayout>'''

FOCUSED_LAYOUT = '''
                <focusedlayout height="157" width="110">
                    <control type="image">
                        <left>2</left><top>0</top>
                        <width>106</width><height>151</height>
                        <texture colordiffuse="EEFFFFFF">white.png</texture>
                        <animation effect="fade" start="0" end="100" time="180" tween="sine">Focus</animation>
                        <animation effect="fade" start="100" end="0" time="120" tween="sine">Unfocus</animation>
                    </control>
                    <control type="image">
                        <left>2</left><top>0</top>
                        <width>106</width><height>3</height>
                        <texture colordiffuse="FFE50914">white.png</texture>
                        <animation effect="fade" start="0" end="100" time="180" tween="sine">Focus</animation>
                        <animation effect="fade" start="100" end="0" time="120" tween="sine">Unfocus</animation>
                    </control>
                    <control type="image">
                        <left>4</left><top>2</top>
                        <width>102</width><height>147</height>
                        <texture>$INFO[ListItem.Property(thumbnail)]</texture>
                        <aspectratio>scale</aspectratio>
                        <animation effect="zoom" start="100" end="107" center="auto" time="200" tween="sine" easing="out">Focus</animation>
                        <animation effect="zoom" start="107" end="100" center="auto" time="140" tween="sine" easing="in">Unfocus</animation>
                    </control>
                    <control type="label">
                        <left>4</left><top>152</top>
                        <width>102</width><height>12</height>
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
        '\n            <!-- ROW %02d  id=%d -->' % (idx, wl_id) +
        '\n            <control type="wraplist" id="%d">' % wl_id +
        '\n                <left>0</left><top>0</top>' +
        '\n                <width>1280</width><height>157</height>' +
        '\n                <viewtype>wrap</viewtype>' +
        '\n                <orientation>horizontal</orientation>' +
        '\n                <scrolltime tween="cubic" easing="out">200</scrolltime>' +
        '\n                <onup>%d</onup>' % up_id +
        '\n                <ondown>%d</ondown>' % dn_id +
        ITEM_LAYOUT + FOCUSED_LAYOUT +
        '\n            </control>' +
        '\n            <control type="image">' +
        '\n                <left>0</left><top>0</top>' +
        '\n                <width>1280</width><height>8</height>' +
        '\n                <texture colordiffuse="FF0D0D0D">white.png</texture>' +
        '\n            </control>'
    )


rows_xml = ''.join(row_block(i) for i in range(MAX_ROWS))

XML = '''\
<?xml version="1.0" encoding="utf-8"?>
<!--
  StreamingUnity Home  1280x720  v6
  Hero 260px | Divider 3px | Rows 457px
  Design ref: streamingunity.biz
  Poster slot 110x157 | Focus: white frame + 3px red top + zoom 107%%
  MAX_ROWS=%(max_rows)d  wraplist IDs 2000..%(last_wl)d step 10
-->
<window>
    <defaultcontrol>2000</defaultcontrol>

    <animation type="WindowOpen" reversible="false">
        <effect type="fade" start="0" end="100" time="280" tween="sine"/>
    </animation>
    <animation type="WindowClose" reversible="false">
        <effect type="fade" start="100" end="0" time="180" tween="sine"/>
    </animation>

    <controls>

        <!-- ══════════════════════════════════════════════
             BASE: near-black warm background
        ══════════════════════════════════════════════ -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1280</width><height>720</height>
            <texture colordiffuse="FF0D0D0D">white.png</texture>
        </control>

        <!-- ══════════════════════════════════════════════
             HERO FANART  id=100
             Explicit transparent texture so Kodi registers
             this control in the tree before Python sets the image.
        ══════════════════════════════════════════════ -->
        <control type="image" id="100">
            <left>0</left><top>0</top>
            <width>1280</width><height>%(hero_h)d</height>
            <texture colordiffuse="00FFFFFF">white.png</texture>
            <aspectratio>scale</aspectratio>
        </control>

        <!-- ══════════════════════════════════════════════
             HERO GRADIENT OVERLAYS
             Simulate StreamingUnity left-to-right scrim:
               - Band 1 (full):     light global dimmer
               - Band 2 (0-560):    solid dark for text area
               - Band 3 (560-680):  strong fade
               - Band 4 (680-820):  medium fade
               - Band 5 (820-960):  light fade
               - Band 6 (bottom):   solid merge into rows
        ══════════════════════════════════════════════ -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1280</width><height>%(hero_h)d</height>
            <texture colordiffuse="77000000">white.png</texture>
        </control>
        <control type="image">
            <left>0</left><top>0</top>
            <width>560</width><height>%(hero_h)d</height>
            <texture colordiffuse="EE0D0D0D">white.png</texture>
        </control>
        <control type="image">
            <left>560</left><top>0</top>
            <width>120</width><height>%(hero_h)d</height>
            <texture colordiffuse="AA0D0D0D">white.png</texture>
        </control>
        <control type="image">
            <left>680</left><top>0</top>
            <width>140</width><height>%(hero_h)d</height>
            <texture colordiffuse="660D0D0D">white.png</texture>
        </control>
        <control type="image">
            <left>820</left><top>0</top>
            <width>140</width><height>%(hero_h)d</height>
            <texture colordiffuse="330D0D0D">white.png</texture>
        </control>
        <!-- Bottom merge strip (hard dark transition into rows) -->
        <control type="image">
            <left>0</left><top>%(hero_fade_y)d</top>
            <width>1280</width><height>40</height>
            <texture colordiffuse="FF0D0D0D">white.png</texture>
        </control>

        <!-- ══════════════════════════════════════════════
             NAV BAR OVERLAY  y=0..50
             Semi-transparent dark strip, layered above fanart.
        ══════════════════════════════════════════════ -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1280</width><height>50</height>
            <texture colordiffuse="CC000000">white.png</texture>
        </control>

        <!-- Brand logo: "STREAMING[red]UNITY[/red]" -->
        <control type="label">
            <left>32</left><top>14</top>
            <width>440</width><height>26</height>
            <font>font14</font>
            <textcolor>FFFFFFFF</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label>[B]STREAMING[COLOR FFE50914]UNITY[/COLOR][/B]</label>
        </control>

        <!-- ══════════════════════════════════════════════
             CLOSE BUTTON  id=108
        ══════════════════════════════════════════════ -->
        <control type="button" id="108">
            <left>1196</left><top>12</top>
            <width>56</width><height>28</height>
            <texturefocus colordiffuse="CCE50914">white.png</texturefocus>
            <texturenofocus colordiffuse="2EFFFFFF">white.png</texturenofocus>
            <label>[B]✕  Esci[/B]</label>
            <font>font12</font>
            <textcolor>FFFFFFFF</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <ondown>2000</ondown>
        </control>

        <!-- ══════════════════════════════════════════════
             HERO CONTENT AREA (y=58..255)
             Layout from top:
               62  Row category / name       id=102
               84  Title (large, bold)        id=103
              130  Meta: year, lang, quality  id=104  (green)
              152  Plot description           id=105  (grey)
              213  CTA: PLAY + INFO visuals
        ══════════════════════════════════════════════ -->

        <!-- Row category name  id=102 -->
        <control type="label" id="102">
            <left>32</left><top>62</top>
            <width>620</width><height>18</height>
            <font>font12</font>
            <textcolor>FFAAAAAA</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
        </control>

        <!-- Title  id=103 -->
        <control type="label" id="103">
            <left>32</left><top>84</top>
            <width>720</width><height>42</height>
            <font>font16</font>
            <textcolor>FFFFFFFF</textcolor>
            <shadowcolor>BB000000</shadowcolor>
            <label></label>
        </control>

        <!-- Meta (year · lang · quality)  id=104 -->
        <control type="label" id="104">
            <left>32</left><top>130</top>
            <width>680</width><height>18</height>
            <font>font12</font>
            <textcolor>FF22C55E</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
        </control>

        <!-- Plot description  id=105 -->
        <control type="label" id="105">
            <left>32</left><top>152</top>
            <width>740</width><height>56</height>
            <font>font12</font>
            <textcolor>FFB3B3B3</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
            <wrapwidth>740</wrapwidth>
        </control>

        <!-- CTA: PLAY button (visual only, not interactive) -->
        <control type="image">
            <left>32</left><top>213</top>
            <width>172</width><height>32</height>
            <texture colordiffuse="FFE50914">white.png</texture>
        </control>
        <control type="label">
            <left>32</left><top>215</top>
            <width>172</width><height>28</height>
            <font>font12</font>
            <textcolor>FFFFFFFF</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label>[B]&#9654;  RIPRODUCI[/B]</label>
            <align>center</align>
        </control>

        <!-- CTA: INFO button (visual only, not interactive) -->
        <control type="image">
            <left>216</left><top>213</top>
            <width>128</width><height>32</height>
            <texture colordiffuse="40FFFFFF">white.png</texture>
        </control>
        <control type="label">
            <left>216</left><top>215</top>
            <width>128</width><height>28</height>
            <font>font12</font>
            <textcolor>FFDEDEDE</textcolor>
            <label>[B]INFO[/B]</label>
            <align>center</align>
        </control>

        <!-- ══════════════════════════════════════════════
             DIVIDER  y=%(div_y)d
             1px neutral dark + 2px brand red
        ══════════════════════════════════════════════ -->
        <control type="image">
            <left>0</left><top>%(div_y)d</top>
            <width>1280</width><height>1</height>
            <texture colordiffuse="FF1E1E1E">white.png</texture>
        </control>
        <control type="image">
            <left>0</left><top>%(div_y1)d</top>
            <width>1280</width><height>2</height>
            <texture colordiffuse="FFE50914">white.png</texture>
        </control>

        <!-- ══════════════════════════════════════════════
             LOADING OVERLAY  id=200
             Shown at open, Python hides it after data loads.
             Card: dark bg + red top bar + brand text + pulse.
        ══════════════════════════════════════════════ -->
        <control type="group" id="200">
            <!-- Full-screen dimmer -->
            <control type="image">
                <left>0</left><top>0</top>
                <width>1280</width><height>720</height>
                <texture colordiffuse="EE0D0D0D">white.png</texture>
            </control>
            <!-- Card background -->
            <control type="image">
                <left>432</left><top>288</top>
                <width>416</width><height>118</height>
                <texture colordiffuse="FF191919">white.png</texture>
            </control>
            <!-- Card red top bar -->
            <control type="image">
                <left>432</left><top>288</top>
                <width>416</width><height>4</height>
                <texture colordiffuse="FFE50914">white.png</texture>
            </control>
            <!-- Brand in loading -->
            <control type="label">
                <left>432</left><top>304</top>
                <width>416</width><height>26</height>
                <font>font13</font>
                <textcolor>FFFFFFFF</textcolor>
                <align>center</align>
                <label>[B]STREAMING[COLOR FFE50914]UNITY[/COLOR][/B]</label>
            </control>
            <!-- Loading text (fade pulse) -->
            <control type="label">
                <left>432</left><top>336</top>
                <width>416</width><height>20</height>
                <font>font12</font>
                <textcolor>FF888888</textcolor>
                <align>center</align>
                <label>Caricamento in corso...</label>
                <animation effect="fade" start="20" end="100" time="850" tween="sine" loop="true" reversible="true">Visible</animation>
            </control>
            <!-- Progress bar (static track) -->
            <control type="image">
                <left>432</left><top>376</top>
                <width>416</width><height>2</height>
                <texture colordiffuse="FF2A2A2A">white.png</texture>
            </control>
            <!-- Progress bar fill (pulse fade) -->
            <control type="image">
                <left>432</left><top>376</top>
                <width>190</width><height>2</height>
                <texture colordiffuse="FFE50914">white.png</texture>
                <animation effect="fade" start="15" end="85" time="600" tween="cubic" loop="true" reversible="true">Visible</animation>
            </control>
        </control>

        <!-- ══════════════════════════════════════════════
             ROWS GROUPLIST  y=%(rows_y)d  h=%(rows_h)d
             Direct wraplist children (no group wrappers).
             Per-row labels: shown only in hero id=102.
             8px dark spacers between rows.
        ══════════════════════════════════════════════ -->
        <control type="grouplist" id="9000">
            <left>0</left><top>%(rows_y)d</top>
            <width>1280</width><height>%(rows_h)d</height>
            <orientation>vertical</orientation>
            <defaultcontrol alwaysfocus="true">2000</defaultcontrol>
            <scrolltime tween="cubic" easing="out">240</scrolltime>
%(rows)s
        </control>

        <!-- ══ GLOBAL LEFT ARROW  id=5000 ══ -->
        <control type="button" id="5000">
            <left>0</left><top>%(rows_y)d</top>
            <width>34</width><height>%(rows_h)d</height>
            <texturefocus colordiffuse="88000000">white.png</texturefocus>
            <texturenofocus colordiffuse="00000000">white.png</texturenofocus>
            <label>[B]‹[/B]</label>
            <font>font14</font>
            <textcolor>BBFFFFFF</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <onup>108</onup>
            <ondown>9000</ondown>
            <onleft>9000</onleft>
            <onright>9000</onright>
        </control>

        <!-- ══ GLOBAL RIGHT ARROW  id=5001 ══ -->
        <control type="button" id="5001">
            <left>1246</left><top>%(rows_y)d</top>
            <width>34</width><height>%(rows_h)d</height>
            <texturefocus colordiffuse="88000000">white.png</texturefocus>
            <texturenofocus colordiffuse="00000000">white.png</texturenofocus>
            <label>[B]›[/B]</label>
            <font>font14</font>
            <textcolor>BBFFFFFF</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <onup>108</onup>
            <ondown>9000</ondown>
            <onleft>9000</onleft>
            <onright>9000</onright>
        </control>

    </controls>
</window>
''' % {
    'max_rows':      MAX_ROWS,
    'last_wl':       LAST_WL,
    'hero_h':        HERO_H,
    'hero_fade_y':   HERO_H - 40,      # 220
    'div_y':         HERO_H,           # 260
    'div_y1':        HERO_H + 1,       # 261
    'rows_y':        ROWS_Y,           # 263
    'rows_h':        ROWS_H,           # 457
    'rows':          rows_xml,
}

with open(XML_PATH, 'w', encoding='utf-8') as fh:
    fh.write(XML)
print('Written %d bytes  ->  %s' % (len(XML), XML_PATH))
