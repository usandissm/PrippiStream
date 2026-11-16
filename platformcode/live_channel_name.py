"""Display names used in the desktop Live rows and IPTV fallback."""
import re

SUFFIX = re.compile(
    r'\s*(?:\[\s*(?:FHD|FLH|HD|SD|UHD|4K|BACKUP|FS|MH)\s*\]'
    r'|\(\s*(?:backup|buffering|principale|fibra(?: top)?|serie [ab])\s*\)'
    r'|\s+(?:full\s*hd|fhd|flh|hd|sd|uhd|4k|hevc|hdr|backup|buffering|italy|italia))\s*$',
    re.I,
)


def channel_name(value):
    name = ' '.join(str(value or '').split())
    while True:
        shorter = SUFFIX.sub('', name).strip()
        if shorter == name:
            break
        name = shorter
    name = re.sub(r'\s*\+\s*(1|24)$', r' +\1', name)
    name = re.sub(r'^Sky (?:Sport|Calcio) (?:\d+\s*\()?((?:25[1-9]))\)?$',
                  r'Sky Sport \1', name, flags=re.I)
    return name


def channel_key(value):
    return re.sub(r'[^a-z0-9]', '', channel_name(value).casefold().replace('+', 'plus'))
