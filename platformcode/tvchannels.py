# -*- coding: utf-8 -*-
"""Riga TV ufficiale condivisa da Kodi e app Android.

Usa le API live dei quattro moduli GPL di Stream4Me conservati internamente;
non espone alcuna navigazione manuale dei provider.
"""
from __future__ import unicode_literals

import importlib
import os
import re

from core.item import Item
from platformcode import logger


PROVIDERS = ('raiplay', 'mediasetplay', 'la7', 'discoveryplus')


def _logo(title, current=''):
    slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
    path = os.path.join('resources', 'media', 'tv_logos', slug + '.png')
    from platformcode import config
    if os.path.isfile(os.path.join(config.get_runtime_path(), path)):
        return 'special://home/addons/plugin.video.prippistream/' + path.replace(os.sep, '/')
    return current


def _live_entry(module, seed):
    for entry in module.mainlist(seed) or []:
        if getattr(entry, 'action', '') == 'live':
            return entry
    return seed.clone(action='live')


def load():
    items, seen = [], set()
    for provider in PROVIDERS:
        try:
            module = importlib.import_module('channels.%s' % provider)
            seed = Item(channel=provider, contentType='video')
            before = len(items)
            for item in module.live(_live_entry(module, seed)) or []:
                title = (getattr(item, 'fulltitle', '') or
                         getattr(item, 'title', '') or '').strip()
                key = (provider, title.casefold())
                if not title or key in seen:
                    continue
                seen.add(key)
                item.channel = provider
                item.action = 'findvideos'
                item.contentType = 'video'
                item.thumbnail = _logo(title, getattr(item, 'thumbnail', '') or '')
                item.fanart = item.thumbnail
                item.is_live_channel = True
                item._app_live_provider = True
                items.append(item)
            logger.info('[TV] %s: %d dirette' % (provider, len(items) - before))
        except Exception as exc:
            logger.error('[TV] %s: %s' % (provider, str(exc)))
    return items


def resolve_listitem(item):
    """Resolve a TV provider in-process and return a playable Kodi ListItem.

    Keeping resolution in the Home interpreter lets ``Player.play`` replace the
    current live stream directly.  A fresh RunPlugin invocation would close the
    old player first, expose the Home, and only then open the next channel.
    """
    try:
        import xbmcgui
        module = importlib.import_module('channels.%s' % item.channel)
        candidates = module.findvideos(item.clone()) or []
        resolved = next((it for it in candidates if getattr(it, 'url', '')), None)
        if not resolved:
            return None

        raw_url = resolved.url or ''
        url, sep, encoded_headers = raw_url.partition('|')
        manifest = (getattr(resolved, 'manifest', '') or '').lower()
        drm = getattr(resolved, 'drm', '') or ''
        license_key = getattr(resolved, 'license', '') or ''
        li = xbmcgui.ListItem(path=url, offscreen=True)
        li.setLabel(item.fulltitle or item.title or '')
        li.setContentLookup(False)
        li.setArt({'thumb': item.thumbnail or '', 'icon': item.thumbnail or '',
                   'poster': item.thumbnail or '', 'fanart': item.fanart or ''})

        if manifest in ('mpd', 'hls') or drm:
            li.setProperty('inputstream', 'inputstream.adaptive')
        if manifest == 'mpd' or drm:
            li.setProperty('inputstream.adaptive.manifest_type', 'mpd')
            li.setMimeType('application/dash+xml')
            if drm and license_key:
                li.setProperty('inputstream.adaptive.license_type', drm)
                li.setProperty('inputstream.adaptive.license_key', license_key)
        elif manifest == 'hls' or '.m3u8' in url.lower():
            li.setProperty('inputstream.adaptive.manifest_type', 'hls')
            li.setMimeType('application/x-mpegURL')

        if sep and encoded_headers:
            li.setProperty('inputstream.adaptive.stream_headers', encoded_headers)
            li.setProperty('inputstream.adaptive.manifest_headers', encoded_headers)
        return li
    except Exception as exc:
        logger.error('[TV] resolve %s: %s' %
                     (getattr(item, 'fulltitle', '') or item.title, str(exc)))
        return None
