"""Conservative forced-subtitle selection, no player/network dependencies."""
import re


def is_forced(track):
    label = str(track.get('name') or track.get('label') or '')
    return bool(track.get('forced') or track.get('isforced') or re.search(r'\b(?:forced|forzat[ioae])\b', label, re.I))


def italian_forced(tracks):
    for index, track in enumerate(tracks):
        if isinstance(track, str):
            track = {'name': track}
        language = str(track.get('language') or '').lower().replace('_', '-').split('-')[0]
        label = str(track.get('name') or track.get('label') or '')
        if (language in ('it', 'ita', 'italian', 'italiano') or
                re.search(r'\b(?:italian[oa]?|ita|it)\b', label, re.I)) and is_forced(track):
            return int(track.get('index', index))
    return None


def apply_default(player):
    """Read real stream flags via JSON-RPC; never enable arbitrary full subtitles."""
    import json
    import xbmc
    for _ in range(10):
        if not player.isPlaying():
            return False
        try:
            result = json.loads(xbmc.executeJSONRPC(json.dumps(dict(jsonrpc='2.0', id=1,
                method='Player.GetProperties', params=dict(playerid=1, properties=['subtitles'])))))
            tracks = result.get('result', {}).get('subtitles') or player.getAvailableSubtitleStreams()
            selected = italian_forced(tracks)
            if selected is not None:
                player.setSubtitleStream(selected)
                player.showSubtitles(True)
                return True
            if tracks:
                return False
        except Exception:
            pass
        xbmc.sleep(300)
    return False
