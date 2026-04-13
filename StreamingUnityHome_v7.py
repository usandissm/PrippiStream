# -*- coding: utf-8 -*-
"""
Writes NetflixHome.xml  v8 -- StreamingUnity look & feel tuned for Kodi TV remote

Layout (1080i / 1920x1080):
  Hero area   : 0 .. 418 px  (418px tall, left-side gradient, brand, title, CTA)
  Divider     : 418 .. 423 px  (5px red)
  Rows area   : 423 .. 1080 px  (657px, grouplist vertical)

Each row slot: 450px tall (poster 330px + 120px title+gap)
"""
from __future__ import annotations
from pathlib import Path

MAX_ROWS  = 50          # number of wraplist slots in the XML

# ---- Layout dimensions (1920x1080) -------------------------------------------
SKIN_W    = 1920
SKIN_H    = 1080
HERO_H    = 418
DIV_H     = 5
ROWS_Y    = HERO_H + DIV_H          # 423
ROWS_H    = SKIN_H - ROWS_Y         # 657

CARD_W    = 278   # card slot width  (185 * 1.5)
CARD_H    = 450   # card slot height (300 * 1.5)
LABEL_H   = 42    # category label height above wraplist (28 * 1.5)
GAP_H     = 30    # breathing room below row (20 * 1.5)
ARROW_W   = 48    # left/right arrow button width (32 * 1.5)

POSTER_W  = 263   # poster image width  (175 * 1.5)
POSTER_H  = 330   # poster image height (220 * 1.5)
LBL_H     = 105   # card title label height (70 * 1.5)

HERO_FADE_H = 72  # bottom fade strip height (48 * 1.5)

# Button IDs in hero
BTN_PLAY  = 110   # PLAY button
BTN_INFO  = 111   # MORE INFO button
BTN_LIST  = 112   # MY LIST button

SCRIPT_DIR     = Path(__file__).resolve().parent
LOCAL_XML_PATH = SCRIPT_DIR / 'NetflixHome_v7.xml'
ADDON_XML_PATH = SCRIPT_DIR / 'resources' / 'skins' / 'Default' / '1080i' / 'NetflixHome.xml'


def write_outputs(xml):
    written = []
    LOCAL_XML_PATH.write_text(xml, encoding='utf-8')
    written.append(str(LOCAL_XML_PATH))
    if ADDON_XML_PATH.parent.exists():
        ADDON_XML_PATH.write_text(xml, encoding='utf-8')
        written.append(str(ADDON_XML_PATH))
    return written


# ---- Card layouts ------------------------------------------------------------
# Slot: 278 wide x 450 tall  => ~6-7 visible per row on 1920px
# Poster: 263 x 330  (8px h-padding, 5px top)
# Title label: top=342, height=105

ITEM_LAYOUT = '''
                <itemlayout height="450" width="278">
                    <control type="image">
                        <left>6</left><top>3</top>
                        <width>266</width><height>333</height>
                        <texture colordiffuse="18000000">white.png</texture>
                    </control>
                    <control type="image">
                        <left>8</left><top>5</top>
                        <width>263</width><height>330</height>
                        <texture>$INFO[ListItem.Property(thumbnail)]</texture>
                        <aspectratio>stretch</aspectratio>
                    </control>
                    <control type="label">
                        <left>6</left><top>342</top>
                        <width>266</width><height>105</height>
                        <font>font13</font>
                        <textcolor>FFAAAAAA</textcolor>
                        <label>$INFO[ListItem.Label]</label>
                        <align>center</align>
                        <aligny>top</aligny>
                    </control>
                </itemlayout>'''

FOCUSED_LAYOUT = '''
                <focusedlayout height="450" width="278">
                    <control type="image">
                        <left>0</left><top>0</top>
                        <width>278</width><height>450</height>
                        <texture colordiffuse="66000000">white.png</texture>
                        <animation effect="fade" start="0" end="100" time="120" tween="sine">Focus</animation>
                        <animation effect="fade" start="100" end="0" time="90" tween="sine">Unfocus</animation>
                    </control>
                    <control type="image">
                        <left>1</left><top>0</top>
                        <width>276</width><height>339</height>
                        <texture colordiffuse="F0FFFFFF">white.png</texture>
                        <animation effect="fade" start="0" end="100" time="140" tween="sine">Focus</animation>
                        <animation effect="fade" start="100" end="0" time="100" tween="sine">Unfocus</animation>
                    </control>
                    <!-- dark bg behind label so text is always readable -->
                    <control type="image">
                        <left>1</left><top>339</top>
                        <width>276</width><height>111</height>
                        <texture colordiffuse="D8101010">white.png</texture>
                        <animation effect="fade" start="0" end="100" time="140" tween="sine">Focus</animation>
                        <animation effect="fade" start="100" end="0" time="90" tween="sine">Unfocus</animation>
                    </control>
                    <control type="image">
                        <left>1</left><top>0</top>
                        <width>276</width><height>5</height>
                        <texture colordiffuse="FFE50914">white.png</texture>
                        <animation effect="fade" start="0" end="100" time="140" tween="sine">Focus</animation>
                        <animation effect="fade" start="100" end="0" time="100" tween="sine">Unfocus</animation>
                    </control>
                    <control type="image">
                        <left>4</left><top>3</top>
                        <width>269</width><height>330</height>
                        <texture>$INFO[ListItem.Property(thumbnail)]</texture>
                        <aspectratio>stretch</aspectratio>
                        <animation effect="zoom" start="100" end="105" center="auto" time="150" tween="sine" easing="out">Focus</animation>
                        <animation effect="zoom" start="105" end="100" center="auto" time="110" tween="sine" easing="in">Unfocus</animation>
                    </control>
                    <control type="label">
                        <left>4</left><top>344</top>
                        <width>269</width><height>105</height>
                        <font>font13</font>
                        <textcolor>FFFFFFFF</textcolor>
                        <shadowcolor>FF000000</shadowcolor>
                        <label>$INFO[ListItem.Label]</label>
                        <align>center</align>
                        <aligny>top</aligny>
                    </control>
                </focusedlayout>'''


def row_block(idx):
    """Each group row: category label + wraplist + left/right arrow buttons + gap."""
    wl_id    = 2000 + idx * 10
    label_id = 3000 + idx * 10
    la_id    = 4000 + idx * 10   # left arrow
    ra_id    = 4001 + idx * 10   # right arrow
    ov_id    = 5000 + idx * 10   # mouse-blocker overlay button
    hb_id    = 6000 + idx * 10   # hover-frame group
    row_h    = CARD_H             # 450
    label_h  = LABEL_H            # 42
    gap_h    = GAP_H              # 30
    ov_left  = ARROW_W            # 48
    ov_w     = SKIN_W - 2 * ARROW_W  # 1824
    ra_left  = SKIN_W - ARROW_W   # 1872
    arrow_bg_always  = '70000000'
    arrow_bg_focused = 'C0000000'
    return (
        '\n            <!-- ------------------- ROW %02d ------------------- -->' % idx
        + '\n            <control type="group">'

        # Category label
        + '\n                <left>0</left><top>0</top>'
        + '\n                <width>%d</width><height>%d</height>' % (SKIN_W, label_h + row_h + gap_h)
        + '\n                <control type="label" id="%d">' % label_id
        + '\n                    <left>60</left><top>3</top>'
        + '\n                    <width>1350</width><height>%d</height>' % label_h
        + '\n                    <font>font13</font>'
        + '\n                    <textcolor>FFFFFFFF</textcolor>'
        + '\n                    <shadowcolor>FF000000</shadowcolor>'
        + '\n                    <label></label>'
        + '\n                    <align>left</align>'
        + '\n                </control>'

        # Wraplist
        + '\n                <control type="wraplist" id="%d">' % wl_id
        + '\n                    <left>0</left><top>%d</top>' % label_h
        + '\n                    <width>%d</width><height>%d</height>' % (SKIN_W, row_h)
        + '\n                    <viewtype>wrap</viewtype>'
        + '\n                    <orientation>horizontal</orientation>'
        + '\n                    <scrolltime tween="cubic" easing="out">200</scrolltime>'
        + ITEM_LAYOUT
        + FOCUSED_LAYOUT
        + '\n                </control>'

        # Left arrow
        + '\n                <control type="button" id="%d">' % la_id
        + '\n                    <left>0</left><top>%d</top>' % label_h
        + '\n                    <width>%d</width><height>%d</height>' % (ARROW_W, row_h)
        + '\n                    <texturefocus colordiffuse="%s">white.png</texturefocus>' % arrow_bg_focused
        + '\n                    <texturenofocus colordiffuse="%s">white.png</texturenofocus>' % arrow_bg_always
        + '\n                    <label>[B]&#x2039;[/B]</label>'
        + '\n                    <font>font14</font>'
        + '\n                    <textcolor>CCFFFFFF</textcolor>'
        + '\n                    <focusedcolor>FFFFFFFF</focusedcolor>'
        + '\n                    <align>center</align>'
        + '\n                    <onleft>%d</onleft>' % wl_id
        + '\n                    <onright>%d</onright>' % wl_id
        + '\n                </control>'

        # Right arrow
        + '\n                <control type="button" id="%d">' % ra_id
        + '\n                    <left>%d</left><top>%d</top>' % (ra_left, label_h)
        + '\n                    <width>%d</width><height>%d</height>' % (ARROW_W, row_h)
        + '\n                    <texturefocus colordiffuse="%s">white.png</texturefocus>' % arrow_bg_focused
        + '\n                    <texturenofocus colordiffuse="%s">white.png</texturenofocus>' % arrow_bg_always
        + '\n                    <label>[B]&#x203A;[/B]</label>'
        + '\n                    <font>font14</font>'
        + '\n                    <textcolor>CCFFFFFF</textcolor>'
        + '\n                    <focusedcolor>FFFFFFFF</focusedcolor>'
        + '\n                    <align>center</align>'
        + '\n                    <onleft>%d</onleft>' % wl_id
        + '\n                    <onright>%d</onright>' % wl_id
        + '\n                </control>'

        # Hover-frame: border-only group, initially off-screen, moved by Python setPosition.
        + '\n                <control type="group" id="%d">' % hb_id
        + '\n                    <left>%d</left><top>%d</top>' % (-CARD_W, label_h)
        + '\n                    <width>%d</width><height>%d</height>' % (CARD_W, row_h)
        # Red top strip
        + '\n                    <control type="image">'
        + '\n                        <left>1</left><top>0</top>'
        + '\n                        <width>%d</width><height>5</height>' % (CARD_W - 2)
        + '\n                        <texture colordiffuse="FFE50914">white.png</texture>'
        + '\n                    </control>'
        # White left border
        + '\n                    <control type="image">'
        + '\n                        <left>0</left><top>0</top>'
        + '\n                        <width>4</width><height>%d</height>' % POSTER_H
        + '\n                        <texture colordiffuse="F0FFFFFF">white.png</texture>'
        + '\n                    </control>'
        # White right border
        + '\n                    <control type="image">'
        + '\n                        <left>%d</left><top>0</top>' % (CARD_W - 4)
        + '\n                        <width>4</width><height>%d</height>' % POSTER_H
        + '\n                        <texture colordiffuse="F0FFFFFF">white.png</texture>'
        + '\n                    </control>'
        # White bottom border at base of poster
        + '\n                    <control type="image">'
        + '\n                        <left>0</left><top>%d</top>' % (POSTER_H - 4)
        + '\n                        <width>%d</width><height>4</height>' % CARD_W
        + '\n                        <texture colordiffuse="F0FFFFFF">white.png</texture>'
        + '\n                    </control>'
        # Dark background behind label
        + '\n                    <control type="image">'
        + '\n                        <left>1</left><top>%d</top>' % POSTER_H
        + '\n                        <width>%d</width><height>%d</height>' % (CARD_W - 2, row_h - POSTER_H)
        + '\n                        <texture colordiffuse="D8101010">white.png</texture>'
        + '\n                    </control>'
        + '\n                </control>'

        # Overlay button: transparent, covers wraplist cards (leaves arrows exposed).
        + '\n                <control type="button" id="%d">' % ov_id
        + '\n                    <left>%d</left><top>%d</top>' % (ov_left, label_h)
        + '\n                    <width>%d</width><height>%d</height>' % (ov_w, row_h)
        + '\n                    <texturefocus colordiffuse="00000000">-</texturefocus>'
        + '\n                    <texturenofocus colordiffuse="00000000">-</texturenofocus>'
        + '\n                    <label></label>'
        + '\n                </control>'

        + '\n            </control>'  # close group
    )


rows_xml = ''.join(row_block(i) for i in range(MAX_ROWS))

# ---- Full XML template -------------------------------------------------------
XML = '''<?xml version="1.0" encoding="utf-8"?>
<!--
  StreamingUnity Home 1920x1080 v8
  Hero %(HERO_H)dpx | Rows area %(ROWS_H)dpx | Card %(CARD_W)dx%(CARD_H)d
  Buttons: PLAY id=%(BTN_PLAY)d  MORE INFO id=%(BTN_INFO)d  MY LIST id=%(BTN_LIST)d
-->
<window type="dialog">
    <allowmouse>false</allowmouse>
    <animation type="WindowOpen" reversible="false">
        <effect type="fade" start="0" end="100" time="240" tween="sine"/>
    </animation>
    <animation type="WindowClose" reversible="false">
        <effect type="fade" start="100" end="0" time="160" tween="sine"/>
    </animation>

    <controls>

        <!-- Base background -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1920</width><height>1080</height>
            <texture colordiffuse="FF0D0D0D">white.png</texture>
        </control>

        <!-- Hero fanart -->
        <control type="image" id="100">
            <left>0</left><top>0</top>
            <width>1920</width><height>%(HERO_H)d</height>
            <texture colordiffuse="00FFFFFF">white.png</texture>
            <aspectratio>scale</aspectratio>
        </control>

        <!-- Hero gradients -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1920</width><height>%(HERO_H)d</height>
            <texture colordiffuse="60000000">white.png</texture>
        </control>
        <control type="image">
            <left>0</left><top>0</top>
            <width>960</width><height>%(HERO_H)d</height>
            <texture colordiffuse="F00D0D0D">white.png</texture>
        </control>
        <control type="image">
            <left>960</left><top>0</top>
            <width>210</width><height>%(HERO_H)d</height>
            <texture colordiffuse="880D0D0D">white.png</texture>
        </control>
        <!-- Bottom fade into rows -->
        <control type="image">
            <left>0</left><top>%(HERO_FADE_TOP)d</top>
            <width>1920</width><height>%(HERO_FADE_H)d</height>
            <texture colordiffuse="FF0D0D0D">white.png</texture>
        </control>

        <!-- Top bar -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1920</width><height>75</height>
            <texture colordiffuse="C0000000">white.png</texture>
        </control>

        <!-- Brand -->
        <control type="label">
            <left>42</left><top>20</top>
            <width>300</width><height>36</height>
            <font>font14</font>
            <textcolor>FFFFFFFF</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label>[B]STREAMING[COLOR FFE50914]UNITY[/COLOR][/B]</label>
        </control>

        <!-- EXIT button -->
        <control type="button" id="108">
            <left>1788</left><top>17</top>
            <width>120</width><height>42</height>
            <texturefocus colordiffuse="FFE50914">white.png</texturefocus>
            <texturenofocus colordiffuse="30FFFFFF">white.png</texturenofocus>
            <label>[B]EXIT[/B]</label>
            <font>font12</font>
            <textcolor>FFAAAAAA</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <animation effect="zoom" start="100" end="110" center="auto" time="120" tween="sine" easing="out">Focus</animation>
            <animation effect="zoom" start="110" end="100" center="auto" time="90" tween="sine" easing="in">Unfocus</animation>
        </control>

        <!-- Row category label -->
        <control type="label" id="102">
            <left>48</left><top>84</top>
            <width>960</width><height>27</height>
            <font>font10</font>
            <textcolor>FFE50914</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
            <align>left</align>
        </control>

        <!-- Title -->
        <control type="label" id="103">
            <left>48</left><top>114</top>
            <width>1080</width><height>72</height>
            <font>font14</font>
            <textcolor>FFFFFFFF</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
            <align>left</align>
        </control>

        <!-- Meta (year / lang) -->
        <control type="label" id="104">
            <left>48</left><top>192</top>
            <width>1020</width><height>27</height>
            <font>font12</font>
            <textcolor>FF22C55E</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
            <align>left</align>
        </control>

        <!-- Plot summary -->
        <control type="label" id="105">
            <left>48</left><top>225</top>
            <width>1080</width><height>90</height>
            <font>font12</font>
            <textcolor>FFB3B3B3</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
            <wrapwidth>1080</wrapwidth>
            <align>left</align>
        </control>

        <!-- PLAY: dark outline unfocused -> solid red focused -->
        <control type="button" id="%(BTN_PLAY)d">
            <left>48</left><top>327</top>
            <width>222</width><height>60</height>
            <texturefocus colordiffuse="FFE50914">white.png</texturefocus>
            <texturenofocus colordiffuse="50E50914">white.png</texturenofocus>
            <label>[B]PLAY[/B]</label>
            <font>font12</font>
            <textcolor>FFDDDDDD</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <onup>108</onup>
            <ondown>2000</ondown>
            <onleft>%(BTN_LIST)d</onleft>
            <onright>%(BTN_INFO)d</onright>
            <animation effect="zoom" start="100" end="108" center="auto" time="130" tween="sine" easing="out">Focus</animation>
            <animation effect="zoom" start="108" end="100" center="auto" time="100" tween="sine" easing="in">Unfocus</animation>
        </control>

        <!-- MORE INFO -->
        <control type="button" id="%(BTN_INFO)d">
            <left>288</left><top>327</top>
            <width>222</width><height>60</height>
            <texturefocus colordiffuse="C0FFFFFF">white.png</texturefocus>
            <texturenofocus colordiffuse="30FFFFFF">white.png</texturenofocus>
            <label>[B]INFO[/B]</label>
            <font>font12</font>
            <textcolor>FFAAAAAA</textcolor>
            <focusedcolor>FF0D0D0D</focusedcolor>
            <align>center</align>
            <onup>108</onup>
            <ondown>2000</ondown>
            <onleft>%(BTN_PLAY)d</onleft>
            <onright>%(BTN_LIST)d</onright>
            <animation effect="zoom" start="100" end="108" center="auto" time="130" tween="sine" easing="out">Focus</animation>
            <animation effect="zoom" start="108" end="100" center="auto" time="100" tween="sine" easing="in">Unfocus</animation>
        </control>

        <!-- MY LIST -->
        <control type="button" id="%(BTN_LIST)d">
            <left>528</left><top>327</top>
            <width>222</width><height>60</height>
            <texturefocus colordiffuse="C0FFFFFF">white.png</texturefocus>
            <texturenofocus colordiffuse="30FFFFFF">white.png</texturenofocus>
            <label>[B]+ LIST[/B]</label>
            <font>font12</font>
            <textcolor>FFAAAAAA</textcolor>
            <focusedcolor>FF0D0D0D</focusedcolor>
            <align>center</align>
            <onup>108</onup>
            <ondown>2000</ondown>
            <onleft>%(BTN_INFO)d</onleft>
            <onright>%(BTN_PLAY)d</onright>
            <animation effect="zoom" start="100" end="108" center="auto" time="130" tween="sine" easing="out">Focus</animation>
            <animation effect="zoom" start="108" end="100" center="auto" time="100" tween="sine" easing="in">Unfocus</animation>
        </control>

        <!-- Hero/rows divider -->
        <control type="image">
            <left>0</left><top>%(HERO_H)d</top>
            <width>1920</width><height>%(DIV_H)d</height>
            <texture colordiffuse="FFE50914">white.png</texture>
        </control>

        <!-- Loading overlay (id=200, hidden after load) -->
        <control type="group" id="200">
            <left>0</left><top>0</top>
            <width>1920</width><height>1080</height>
            <control type="image">
                <left>0</left><top>0</top>
                <width>1920</width><height>1080</height>
                <texture colordiffuse="E8000000">white.png</texture>
            </control>
            <control type="image">
                <left>660</left><top>420</top>
                <width>600</width><height>120</height>
                <texture colordiffuse="FF151515">white.png</texture>
            </control>
            <control type="image">
                <left>660</left><top>420</top>
                <width>600</width><height>3</height>
                <texture colordiffuse="FFE50914">white.png</texture>
            </control>
            <control type="label">
                <left>660</left><top>444</top>
                <width>600</width><height>36</height>
                <font>font14</font>
                <textcolor>FFFFFFFF</textcolor>
                <align>center</align>
                <label>[B]STREAMING[COLOR FFE50914]UNITY[/COLOR][/B]</label>
            </control>
            <control type="label">
                <left>660</left><top>492</top>
                <width>600</width><height>30</height>
                <font>font12</font>
                <textcolor>FF7E7E7E</textcolor>
                <align>center</align>
                <label>Caricamento...</label>
                <animation effect="fade" start="20" end="100" time="800" tween="sine" loop="true" reversible="true">Visible</animation>
            </control>
            <control type="image">
                <left>720</left><top>522</top>
                <width>480</width><height>3</height>
                <texture colordiffuse="FF252525">white.png</texture>
            </control>
            <control type="image">
                <left>720</left><top>522</top>
                <width>180</width><height>3</height>
                <texture colordiffuse="FFE50914">white.png</texture>
                <animation effect="fade" start="20" end="80" time="500" tween="cubic" loop="true" reversible="true">Visible</animation>
            </control>
        </control>

        <!-- Rows grouplist (vertical scroll) -->
        <control type="grouplist" id="9000">
            <left>0</left><top>%(ROWS_Y)d</top>
            <width>1920</width><height>%(ROWS_H)d</height>
            <orientation>vertical</orientation>
            <defaultcontrol>2000</defaultcontrol>
            <scrolltime tween="cubic" easing="out">220</scrolltime>
%(rows_xml)s
        </control>

    </controls>
</window>
''' % {
    'HERO_H':        HERO_H,
    'HERO_FADE_TOP': HERO_H - HERO_FADE_H,
    'HERO_FADE_H':   HERO_FADE_H,
    'DIV_H':         DIV_H,
    'ROWS_Y':        ROWS_Y,
    'ROWS_H':        ROWS_H,
    'CARD_W':        CARD_W,
    'CARD_H':        CARD_H,
    'BTN_PLAY':      BTN_PLAY,
    'BTN_INFO':      BTN_INFO,
    'BTN_LIST':      BTN_LIST,
    'rows_xml':      rows_xml,
}


if __name__ == '__main__':
    out_paths = write_outputs(XML)
    print('Written %d bytes' % len(XML.encode('utf-8')))
    for p in out_paths:
        print(' ->', p)
