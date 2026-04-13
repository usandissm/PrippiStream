# -*- coding: utf-8 -*-
"""Writes the redesigned NetflixHome.xml"""
import os

XML_PATH = os.path.join(os.path.dirname(__file__),
    'resources', 'skins', 'Default', '720p', 'NetflixHome.xml')

# ------------------------------------------------------------------
# ITEM LAYOUT TEMPLATES (unfocused / focused)  –  portrait poster
# ------------------------------------------------------------------
ITEM_LAYOUT = '''
                <itemlayout height="202" width="142">
                    <control type="image">
                        <left>7</left><top>5</top>
                        <width>120</width><height>170</height>
                        <texture>$INFO[ListItem.Property(thumbnail)]</texture>
                        <aspectratio>scale</aspectratio>
                    </control>
                    <control type="label">
                        <left>7</left><top>178</top>
                        <width>120</width><height>20</height>
                        <font>font12</font>
                        <textcolor>FF777777</textcolor>
                        <label>$INFO[ListItem.Label]</label>
                        <align>center</align>
                        <truncated>true</truncated>
                    </control>
                </itemlayout>'''

FOCUSED_LAYOUT = '''
                <focusedlayout height="202" width="142">
                    <!-- Red border (3px around poster) -->
                    <control type="image">
                        <left>4</left><top>2</top>
                        <width>126</width><height>176</height>
                        <texture colordiffuse="FFE50914">white.png</texture>
                    </control>
                    <!-- Poster with subtle zoom on focus -->
                    <control type="image">
                        <left>7</left><top>5</top>
                        <width>120</width><height>170</height>
                        <texture>$INFO[ListItem.Property(thumbnail)]</texture>
                        <aspectratio>scale</aspectratio>
                        <animation effect="zoom" start="100" end="106" center="auto" time="200" tween="sine" easing="out">Focus</animation>
                        <animation effect="zoom" start="106" end="100" center="auto" time="150" tween="sine" easing="in">Unfocus</animation>
                    </control>
                    <!-- Title white when focused -->
                    <control type="label">
                        <left>7</left><top>178</top>
                        <width>120</width><height>20</height>
                        <font>font12</font>
                        <textcolor>FFFFFFFF</textcolor>
                        <label>$INFO[ListItem.Label]</label>
                        <align>center</align>
                        <truncated>true</truncated>
                    </control>
                </focusedlayout>'''


def row_block(idx, up_id, down_id):
    label_id = 2001 + idx * 10
    wl_id    = 2000 + idx * 10
    # First row has no top-gap; subsequent rows have 18px gap above label
    top_gap  = '0' if idx == 0 else '18'
    return f'''
            <!-- =============== ROW {idx} =============== -->
            <control type="label" id="{label_id}">
                <left>36</left><top>{top_gap}</top>
                <width>700</width><height>26</height>
                <font>font13</font>
                <textcolor>FFFFFFFF</textcolor>
                <shadowcolor>FF000000</shadowcolor>
                <label></label>
            </control>
            <control type="wraplist" id="{wl_id}">
                <left>0</left><top>6</top>
                <width>1280</width><height>202</height>
                <viewtype>wrap</viewtype>
                <orientation>horizontal</orientation>
                <scrolltime tween="cubic" easing="out">220</scrolltime>
                <onup>{up_id}</onup>
                <ondown>{down_id}</ondown>{ITEM_LAYOUT}{FOCUSED_LAYOUT}
            </control>'''


# Build all 6 row blocks (rows 0-5, IDs 2000-2050 step 10)
rows_xml = ''
for i in range(6):
    up   = max(2000, 2000 + (i - 1) * 10)
    down = min(2050, 2000 + (i + 1) * 10)
    rows_xml += row_block(i, up, down)

XML = f'''<?xml version="1.0" encoding="utf-8"?>
<!--
    Netflix-style home per StreamingCommunity  -  1280x720
    Hero: y=0..215  |  Rows: y=218.. (grouplist, scroll verticale auto)
    Poster portrait 120x170, slot 134x202, rosso E50914, zoom on focus
    Righe: 6 (3 Film + 3 Serie TV)
-->
<window>
    <defaultcontrol>2000</defaultcontrol>

    <animation type="WindowOpen" reversible="false">
        <effect type="fade" start="0" end="100" time="320"/>
    </animation>
    <animation type="WindowClose" reversible="false">
        <effect type="fade" start="100" end="0" time="200"/>
    </animation>

    <controls>

        <!-- ============================================================ -->
        <!-- BASE DARK BACKGROUND                                          -->
        <!-- ============================================================ -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1280</width><height>720</height>
            <texture colordiffuse="FF0A0A0A">white.png</texture>
        </control>

        <!-- ============================================================ -->
        <!-- HERO FANART  (id 100)                                         -->
        <!-- ============================================================ -->
        <control type="image" id="100">
            <left>0</left><top>0</top>
            <width>1280</width><height>215</height>
            <aspectratio>scale</aspectratio>
        </control>

        <!-- Fanart dimmer -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1280</width><height>215</height>
            <texture colordiffuse="99000000">white.png</texture>
        </control>

        <!-- Top-bar gradient (readability) -->
        <control type="image">
            <left>0</left><top>0</top>
            <width>1280</width><height>62</height>
            <texture colordiffuse="EE000000">white.png</texture>
        </control>

        <!-- Bottom gradient (smooth fade to rows) -->
        <control type="image">
            <left>0</left><top>148</top>
            <width>1280</width><height>70</height>
            <texture colordiffuse="FF0A0A0A">white.png</texture>
        </control>

        <!-- ============================================================ -->
        <!-- TOP BAR                                                        -->
        <!-- ============================================================ -->

        <!-- SC brand (red accent) -->
        <control type="label">
            <left>32</left><top>14</top>
            <width>550</width><height>30</height>
            <font>font14</font>
            <textcolor>FFE50914</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label>[B]StreamingCommunity[/B]</label>
        </control>

        <!-- Current row/category indicator  (id 102 = HERO_CATEG) -->
        <control type="label" id="102">
            <left>32</left><top>46</top>
            <width>900</width><height>22</height>
            <font>font12</font>
            <textcolor>FF888888</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
        </control>

        <!-- Close button  (id 108) -->
        <control type="button" id="108">
            <left>1186</left><top>9</top>
            <width>78</width><height>32</height>
            <texturefocus colordiffuse="CCE50914">white.png</texturefocus>
            <texturenofocus colordiffuse="40FFFFFF">white.png</texturenofocus>
            <label>[B]x Esci[/B]</label>
            <font>font12</font>
            <textcolor>FFFFFFFF</textcolor>
            <focusedcolor>FFFFFFFF</focusedcolor>
            <align>center</align>
            <ondown>2000</ondown>
        </control>

        <!-- ============================================================ -->
        <!-- HERO TEXT  (bottom of hero stripe)                            -->
        <!-- ============================================================ -->

        <!-- Title of focused item  (id 103 = HERO_TITLE) -->
        <control type="label" id="103">
            <left>32</left><top>148</top>
            <width>860</width><height>40</height>
            <font>font14</font>
            <textcolor>FFFFFFFF</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
        </control>

        <!-- Meta: year | language  (id 104 = HERO_META) -->
        <control type="label" id="104">
            <left>32</left><top>191</top>
            <width>700</width><height>22</height>
            <font>font12</font>
            <textcolor>FF00CC66</textcolor>
            <shadowcolor>FF000000</shadowcolor>
            <label></label>
        </control>

        <!-- ============================================================ -->
        <!-- LOADING OVERLAY  (id 200, group, shown/hidden by Python)       -->
        <!-- ============================================================ -->
        <control type="group" id="200">
            <!-- Full-screen dim -->
            <control type="image">
                <left>0</left><top>0</top>
                <width>1280</width><height>720</height>
                <texture colordiffuse="CC000000">white.png</texture>
            </control>
            <!-- Panel box -->
            <control type="image">
                <left>390</left><top>298</top>
                <width>500</width><height>120</height>
                <texture colordiffuse="FF1A1A1A">white.png</texture>
            </control>
            <!-- Red accent bar on top of panel -->
            <control type="image">
                <left>390</left><top>298</top>
                <width>500</width><height>4</height>
                <texture colordiffuse="FFE50914">white.png</texture>
            </control>
            <!-- Pulsing loading text -->
            <control type="label">
                <left>390</left><top>326</top>
                <width>500</width><height>46</height>
                <font>font14</font>
                <textcolor>FFFFFFFF</textcolor>
                <shadowcolor>FF000000</shadowcolor>
                <align>center</align>
                <label>[B]Caricamento in corso...[/B]</label>
                <animation effect="fade" start="30" end="100" time="800" tween="sine" loop="true" reversible="true">Visible</animation>
            </control>
            <!-- Subtitle -->
            <control type="label">
                <left>390</left><top>378</top>
                <width>500</width><height>22</height>
                <font>font12</font>
                <textcolor>FF666666</textcolor>
                <align>center</align>
                <label>StreamingCommunity...</label>
            </control>
        </control>

        <!-- ============================================================ -->
        <!-- ROWS - grouplist verticale, scorre automaticamente             -->
        <!--   row 0..5  ID wraplist: 2000,2010..2050  label: 2001..2051   -->
        <!--   ogni riga: label 26px + gap 6px + wraplist 202px = 234px     -->
        <!--   tra righe: 18px gap sopra ogni label (fuorche' la 0)         -->
        <!--   stima visibili: ~2 righe complete + inizio 3a               -->
        <!-- ============================================================ -->
        <control type="grouplist" id="9000">
            <left>0</left><top>218</top>
            <width>1280</width><height>502</height>
            <orientation>vertical</orientation>
            <defaultcontrol alwaysfocus="true">2000</defaultcontrol>
            <scrolltime tween="cubic" easing="out">280</scrolltime>
{rows_xml}
        </control><!-- end grouplist 9000 -->

    </controls>
</window>
'''

with open(XML_PATH, 'w', encoding='utf-8') as f:
    f.write(XML)

print(f'Written {len(XML):,} bytes to {XML_PATH}')
