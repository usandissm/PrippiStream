"""Non-interactive zap notification, with proportional channel artwork."""
import os
import threading
import xml.etree.ElementTree as ET

import xbmc
import xbmcgui
import xbmcvfs

_lock = threading.RLock()
_shown = None


def _resolution():
    try:
        manifest = os.path.join(xbmcvfs.translatePath('special://skin/'), 'addon.xml')
        res = ET.parse(manifest).find('.//res')
        return int(res.attrib['width']), int(res.attrib['height'])
    except (OSError, ET.ParseError, AttributeError, ValueError, KeyError):
        return 1920, 1080


def clear(token=None):
    global _shown
    with _lock:
        if _shown is None or (token is not None and _shown[0] is not token):
            return
        _, window, controls = _shown
        _shown = None
        for control in reversed(controls):
            try:
                window.removeControl(control)
            except (RuntimeError, TypeError):
                pass


def show(title, message, logo, duration):
    global _shown
    with _lock:
        clear()
        if not xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):
            return  # No notification on Home while the next stream opens.
        controls = []
        token = object()
        try:
            window = xbmcgui.Window(12005)
            width, height = _resolution()
            sx, sy = lambda n: max(1, round(n * width / 1920)), lambda n: max(1, round(n * height / 1080))
            left, top = width - sx(630), sy(27)
            text = left + sx(169 if logo else 18)
            white = ('special://home/addons/plugin.video.prippistream/'
                     'resources/skins/Default/media/white.png')
            proposed = [xbmcgui.ControlImage(left, top, sx(608), sy(114), white,
                                             colorDiffuse='0xE0161616')]
            if logo:
                proposed.append(xbmcgui.ControlImage(left + sx(12), top + sy(10),
                                                     sx(144), sy(94), logo, aspectRatio=2))
            proposed.extend([
                xbmcgui.ControlLabel(text, top + sy(10), width - text - sx(36),
                                     sy(42), title, font='font13', textColor='0xFFFFFFFF'),
                xbmcgui.ControlLabel(text, top + sy(53), width - text - sx(36),
                                     sy(36), message, font='font12', textColor='0xFFE8E8E8'),
            ])
            _shown = (token, window, controls)
            for control in proposed:
                window.addControl(control)
                controls.append(control)
        except Exception:
            clear(token)
            xbmcgui.Dialog().notification(title, message, xbmcgui.NOTIFICATION_INFO, duration)
            return
        timer = threading.Timer(duration / 1000.0, clear, (token,))
        timer.daemon = True
        timer.start()
