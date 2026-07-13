# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# bridge.py — facade Python chiamata dalla UI nativa (Kotlin/Chaquopy).
# Espone il MOTORE (channels/servers/core) come API a dati (dict/JSON),
# senza alcuna UI Kodi. Tutto ciò che entra/esce è JSON-serializzabile.
# ------------------------------------------------------------
import os
import sys
import json

_INITED = False


def init(runtime_dir=None, data_dir=None, temp_dir=None):
    """Configura percorsi e sys.path. Idempotente. Da chiamare all'avvio dell'app
    (o dal test PC) PRIMA di ogni altra chiamata."""
    global _INITED
    if _INITED:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    shim_dir = os.path.join(here, 'xbmc_shim')
    engine_dir = os.path.join(here, 'engine')
    lib_dir = os.path.join(engine_dir, 'lib')   # come Kodi: la cartella lib è su sys.path
    # xbmc_shim per primo: 'import xbmc' deve trovare il nostro stub, non altro.
    for p in (shim_dir, engine_dir, lib_dir):
        if p not in sys.path:
            sys.path.insert(0, p)

    import prippi_env
    prippi_env.init(
        runtime_dir or engine_dir,
        data_dir or os.path.join(here, '.appdata'),
        temp_dir,
    )
    _INITED = True


# ── conversione Item ↔ dict ──────────────────────────────────────────────────

def _to_item(d):
    from core.item import Item
    return Item(**(d or {}))


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return str(v)


def _from_item(item):
    out = {}
    for k, v in item.__dict__.items():
        if k.startswith('__'):
            continue
        out[k] = _jsonable(v)
    return out


def _items_to_list(res):
    """Il motore ritorna una lista di Item (o un ItemList). Normalizza a list[dict]."""
    out = []
    try:
        for it in res:
            out.append(_from_item(it))
    except TypeError:
        pass
    return out


# ── API ──────────────────────────────────────────────────────────────────────

def channel_methods(channel_id):
    """Nomi dei metodi pubblici del canale (diagnostica)."""
    init()
    ch = __import__('channels.%s' % channel_id, fromlist=[channel_id])
    return [n for n in dir(ch) if not n.startswith('_') and callable(getattr(ch, n))]


def channel_call(channel_id, method, item_dict=None, text=None):
    """Invoca channel.<method>(item[, text]) e ritorna list[dict].
    method ∈ {mainlist, search, genres, newest, peliculas, browse, episodios, findvideos}."""
    init()
    ch = __import__('channels.%s' % channel_id, fromlist=[channel_id])
    fn = getattr(ch, method)
    item = _to_item(item_dict or {})
    # In Kodi il routing del launcher imposta item.channel dall'URL del plugin
    # (channel=...). Headless deve replicarlo, altrimenti findvideos/episodios che
    # leggono get_channel_parameters(item.channel) falliscono.
    item.channel = channel_id
    if method == 'search' and text is not None:
        res = fn(item, text)
    else:
        res = fn(item)
    return _items_to_list(res)


def resolve(item_dict):
    """Da un Item riproducibile → dati per il player nativo.
    Se l'item è già una sorgente diretta (url+manifest), la impacchetta;
    altrimenti passa per findvideos del canale.
    Ritorna {url, manifest_type, headers, drm_type, license_key, audio_language, subtitles}."""
    init()
    item = _to_item(item_dict or {})
    url = getattr(item, 'url', '') or ''
    manifest = (getattr(item, 'manifest', '') or '').lower()
    headers = getattr(item, 'headers', {}) or {}

    # Se l'item ha un SERVER (es. streamingcommunityws), esegui il resolver reale:
    # iframe/pagina → URL diretto riproducibile (es. playlist vixcloud).
    server = (getattr(item, 'server', '') or '').strip().lower()
    if server and server not in ('directo', 'local'):
        try:
            from core import servertools
            ret = servertools.resolve_video_urls_for_playing(server, url,
                                                             getattr(item, 'password', '') or '', False)
            video_urls = ret[0] if isinstance(ret, (list, tuple)) else ret
            if video_urls:
                best = video_urls[-1]          # [label, url, ...]
                label = str(best[0]) if len(best) > 0 else ''
                url = best[1] if len(best) > 1 else url
                if not manifest:
                    ll = label.lower()
                    manifest = 'mpd' if 'mpd' in ll or 'dash' in ll else 'hls'
        except Exception as exc:
            from platformcode import logger
            logger.error('[bridge] resolve server %s: %s' % (server, exc))

    if not manifest:
        low = url.split('|')[0].lower()
        manifest = 'hls' if ('.m3u8' in low or 'playlist' in low) else ('mpd' if '.mpd' in low else 'hls')
    return {
        'url': url.split('|')[0],
        'manifest_type': 'mpd' if 'mpd' in manifest else 'hls',
        'headers': _jsonable(headers),
        'drm_type': getattr(item, 'drm', '') or '',
        'license_key': getattr(item, 'license', '') or '',
        'audio_language': 'it',
        'subtitles': _jsonable(getattr(item, 'subtitle', '') or ''),
    }


# ── helper JSON per il ponte Kotlin (Chaquopy passa/riceve stringhe comodamente) ─

def call_json(channel_id, method, item_json='{}', text=None):
    return json.dumps(channel_call(channel_id, method,
                                   json.loads(item_json or '{}'), text), ensure_ascii=False)


def resolve_json(item_json='{}'):
    return json.dumps(resolve(json.loads(item_json or '{}')), ensure_ascii=False)
