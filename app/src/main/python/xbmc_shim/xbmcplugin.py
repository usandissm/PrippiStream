# -*- coding: utf-8 -*-
# Shim di `xbmcplugin` — stub no-op. Il routing/listing lo fa la UI nativa via
# il bridge; qui basta non far fallire gli import.

SORT_METHOD_NONE = 0
SORT_METHOD_LABEL = 1
SORT_METHOD_VIDEO_YEAR = 2
CONTENT_TYPE = 0


def addDirectoryItem(handle, url, listitem, isFolder=False, totalItems=0):
    return True


def addDirectoryItems(handle, items, totalItems=0):
    return True


def endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=True):
    pass


def setContent(handle, content):
    pass


def setPluginCategory(handle, category):
    pass


def addSortMethod(handle, sortMethod, label2Mask=''):
    pass


def setResolvedUrl(handle, succeeded, listitem):
    pass
