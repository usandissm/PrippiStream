# -*- coding: utf-8 -*-
"""Small, read-only network/device summary shown from addon settings."""
import platform
import socket
import sys

import xbmc

from platformcode import platformtools


def _label(*names):
    # Android/low-power devices can expose the temporary literal "Busy" while
    # Kodi refreshes network properties. Never present it as the actual value.
    for attempt in range(8):
        for name in names:
            try:
                value = (xbmc.getInfoLabel(name) or '').strip()
                if value and value.lower() not in ('busy', 'occupato'):
                    return value
            except Exception:
                pass
        if attempt < 7:
            xbmc.sleep(125)
    return 'Non disponibile'


def _local_ip():
    value = _label('Network.IPAddress', 'System.IPAddress')
    if value != 'Non disponibile':
        return value
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))
        return sock.getsockname()[0]
    except Exception:
        return 'Non disponibile'
    finally:
        if sock:
            sock.close()


def show():
    try:
        host = socket.gethostname() or 'Non disponibile'
    except Exception:
        host = 'Non disponibile'
    rows = [
        ('Indirizzo IP', _local_ip()),
        ('Hostname', host),
        ('Stato rete', _label('Network.LinkState')),
        ('Indirizzo MAC', _label('Network.MacAddress')),
        ('Subnet mask', _label('Network.SubnetMask')),
        ('Gateway', _label('Network.GatewayAddress')),
        ('DNS primario', _label('Network.DNS1Address')),
        ('DNS secondario', _label('Network.DNS2Address')),
        ('Sistema', platform.system() + ' ' + platform.machine()),
        ('Kodi', _label('System.BuildVersion')),
        ('Python', sys.version.split()[0]),
    ]
    text = '\n'.join('[B]%s:[/B] %s' % pair for pair in rows)
    platformtools.dialog_textviewer('PrippiStream - Informazioni di rete', text)
