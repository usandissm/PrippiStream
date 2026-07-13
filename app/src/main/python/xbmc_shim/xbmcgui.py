# -*- coding: utf-8 -*-
# Shim di `xbmcgui` — stub inerti. La UI è nativa (Compose), quindi qui niente
# finestre/dialoghi reali: servono solo a far importare i moduli senza errori.

# Costanti di azione più comuni (referenziate da alcuni moduli motore)
ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
INPUT_ALPHANUM = 0


class ListItem(object):
    def __init__(self, label='', label2='', path='', offscreen=False):
        self.label = label
        self.label2 = label2
        self._path = path
        self._props = {}
        self._info = {}
        self._art = {}

    def setLabel(self, v): self.label = v
    def setLabel2(self, v): self.label2 = v
    def setPath(self, v): self._path = v
    def getPath(self): return self._path
    def setProperty(self, k, v): self._props[k] = v
    def getProperty(self, k): return self._props.get(k, '')
    def setArt(self, d): self._art.update(d or {})
    def setInfo(self, type, infoLabels): self._info.update(infoLabels or {})
    def setContentLookup(self, v): pass
    def setMimeType(self, v): pass
    def addStreamInfo(self, *a, **k): pass
    def setSubtitles(self, *a, **k): pass


class Dialog(object):
    def ok(self, *a, **k): return True
    def yesno(self, *a, **k): return False
    def notification(self, *a, **k): pass
    def select(self, *a, **k): return -1
    def multiselect(self, *a, **k): return None
    def input(self, *a, **k): return ''
    def browse(self, *a, **k): return ''


class DialogProgress(object):
    def create(self, *a, **k): pass
    def update(self, *a, **k): pass
    def iscanceled(self): return False
    def close(self): pass


class DialogProgressBG(object):
    def create(self, *a, **k): pass
    def update(self, *a, **k): pass
    def isFinished(self): return True
    def close(self): pass


class Window(object):
    def __init__(self, *a, **k): pass
    def getProperty(self, k): return ''
    def setProperty(self, k, v): pass
    def clearProperty(self, k): pass


class WindowXML(object):
    def __init__(self, *a, **k): pass


class WindowXMLDialog(object):
    def __init__(self, *a, **k): pass
