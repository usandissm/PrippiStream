# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# bridge.py — facade Python chiamata dalla UI nativa (Kotlin/Chaquopy).
# Espone il MOTORE (channels/servers/core) come API a dati (dict/JSON),
# senza alcuna UI Kodi. Tutto ciò che entra/esce è JSON-serializzabile.
# ------------------------------------------------------------
import os
import sys
import json
import re
import glob
import time
import uuid
import threading
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote_plus

_INITED = False
_DOWNLOADS_RESUMED = False
_BROWSE_SESSIONS = {}
_BROWSE_SESSION_LIMIT = 8
_HOME_LOCK = threading.Lock()
_HOME_STATE = {
    'sc_rows': None,
    'anime_items': None,
    'loading': False,
    'complete': False,
}
_LIVE_LOCK = threading.Lock()
_LIVE_LOADING = False
_LIVE_REFRESHED_AT = 0
_FOURK_STARTED = False
_DOMAIN_SYNC_STARTED = False
_APP_LOW_POWER = False
_APP_TELEVISION = False
_DETAIL_CACHE = {}
_DETAIL_CACHE_LOCK = threading.Lock()
_DETAIL_CACHE_TTL = 6 * 60 * 60
_DETAIL_CACHE_LIMIT = 64


def _streamingcommunity_bootstrap_url(module, source_url=''):
    """Restituisce soltanto un embed VixCloud adatto al bootstrap nativo.

    ``streamingcommunityws.test_video_exists`` conserva l'iframe prima di
    tentare l'estrazione Python della playlist. Sulle box economiche il fetch
    diretto può fallire e il proxy esterno può restituire una pagina non valida:
    in quel caso l'embed resta comunque utilizzabile dal WebView Android.
    """
    candidates = (
        str(getattr(module, 'bootstrap_url', '') or '').strip(),
        str(source_url or '').strip(),
    )
    for candidate in candidates:
        low = candidate.lower()
        if (
            candidate.startswith(('https://', 'http://')) and
            '/embed/' in low and
            ('vixcloud.' in low or 'workers.dev' in low)
        ):
            return candidate
    return ''


def init(runtime_dir=None, data_dir=None, temp_dir=None):
    """Configura percorsi e sys.path. Idempotente. Da chiamare all'avvio dell'app
    (o dal test PC) PRIMA di ogni altra chiamata."""
    global _INITED, _DOMAIN_SYNC_STARTED
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

    # Lo snapshot motore validato dall'MVP usa già gli hook PERF in alcuni
    # moduli, ma non contiene ancora platformcode/perf.py. Il fallback vive
    # negli shim Android e sparisce automaticamente quando il motore
    # sincronizzato fornirà il modulo reale.
    try:
        from platformcode import perf as _perf  # noqa: F401
    except ImportError:
        import platformcode
        import prippi_perf
        sys.modules['platformcode.perf'] = prippi_perf
        platformcode.perf = prippi_perf

    import prippi_env
    prippi_env.init(
        runtime_dir or engine_dir,
        data_dir or os.path.join(here, '.appdata'),
        temp_dir,
    )
    _INITED = True
    # Android esegue il sync in modo sincrono dentro refresh_sc_domain_json,
    # prima di caricare Home. In passato il thread qui sotto poteva perdere la
    # gara contro la prima richiesta SC e lasciare in uso un URL già obsoleto.
    if runtime_dir and not _DOMAIN_SYNC_STARTED:
        _DOMAIN_SYNC_STARTED = True


def set_device_profile(low_power=False, television=False):
    """Riceve il profilo nativo prima di costruire Home e righe Live."""
    global _APP_LOW_POWER, _APP_TELEVISION
    _APP_LOW_POWER = bool(low_power)
    _APP_TELEVISION = bool(television)


def refresh_sc_domain_json():
    """Validate SC synchronously before Home/search imports stale content URLs."""
    init()
    try:
        import importlib
        from platformcode import config, prippihome
        # 1) Pull the central domain registry. Network failure is already handled
        # by _sync_channels_json and leaves the bundled last-known-good copy.
        registry = prippihome._sync_channels_json()
        # 2) Force config and the channel module to observe the just-written file.
        config.channels_data = dict()
        module_name = 'channels.streamingcommunity'
        if module_name in sys.modules:
            streamingcommunity = importlib.reload(sys.modules[module_name])
        else:
            streamingcommunity = importlib.import_module(module_name)
        # 3) Follow redirects, persist the final host and only then allow Home.
        value = streamingcommunity.refresh_host_on_startup()
        return json.dumps(
            {'ok': bool(value), 'host': value, 'registry': registry},
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False)


def detail_metadata_json(item_json='{}'):
    return json.dumps(
        _detail_metadata(json.loads(item_json or '{}')),
        ensure_ascii=False,
    )


def playback_policy_options_json():
    init()
    from platformcode import config
    return json.dumps({
        'allow_4k_metered': (
            config.get_setting('app_allow_4k_metered', default=False) is True
        ),
        'treat_wifi_metered': (
            config.get_setting('app_treat_wifi_metered', default=False) is True
        ),
    }, ensure_ascii=False)


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
    current_sc_cdn = ''
    if getattr(item, 'channel', '') == 'streamingcommunity':
        try:
            from platformcode import config
            from urllib.parse import urlsplit
            sc_host = urlsplit(config.get_channel_url(name='streamingcommunity')).netloc
            current_sc_cdn = 'cdn.' + sc_host.removeprefix('www.')
        except Exception:
            pass
    for k, v in item.__dict__.items():
        if k.startswith('__'):
            continue
        if k in ('thumbnail', 'fanart') and isinstance(v, str):
            prefix = 'special://home/addons/plugin.video.prippistream/'
            if v.startswith(prefix):
                import prippi_env
                v = 'file://' + os.path.join(
                    prippi_env.RUNTIME_DIR, v[len(prefix):].replace('/', os.sep))
            elif current_sc_cdn and v.startswith(('http://', 'https://')):
                try:
                    from urllib.parse import urlsplit, urlunsplit
                    parsed = urlsplit(v)
                    if parsed.netloc.startswith('cdn.streamingcommunity') and parsed.netloc != current_sc_cdn:
                        v = urlunsplit((parsed.scheme, current_sc_cdn, parsed.path,
                                        parsed.query, parsed.fragment))
                except Exception:
                    pass
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


def _detail_metadata(item_dict):
    """Enrich one opened detail page, never the Home.

    This keeps cold paint cheap while giving every Android form factor the
    editorial fields already shown by Kodi's DetailWindow.
    """
    init()
    source = dict(item_dict or {})
    info = dict(source.get('infoLabels') or {})
    media_type = str(info.get('mediatype') or source.get('contentType') or '').lower()
    ctype = 'tv' if media_type in ('tvshow', 'serie', 'season', 'episode') else 'movie'
    tmdb_id = str(info.get('tmdb_id') or source.get('tmdb_id') or '').strip()
    if not tmdb_id:
        from urllib.parse import quote
        from core.tmdb import Tmdb, host as tmdb_host, api as tmdb_api
        title = str(
            source.get('contentSerieName')
            or source.get('show')
            or source.get('contentTitle')
            or source.get('fulltitle')
            or source.get('title')
            or ''
        ).strip()
        year = str(info.get('year') or source.get('year') or '')[:4]
        if not title:
            return source
        search_url = (
            '%s/search/%s?api_key=%s&language=it-IT&include_adult=false&query=%s'
            % (tmdb_host, ctype, tmdb_api, quote(title))
        )
        if year.isdigit():
            search_url += (
                '&first_air_date_year=%s' if ctype == 'tv'
                else '&primary_release_year=%s'
            ) % year
        results = (Tmdb.get_json(search_url) or {}).get('results') or []
        if not results and year:
            # Alcuni cataloghi riportano l'anno dell'ultima stagione: riprova
            # senza vincolo, ma richiedi comunque un titolo realmente uguale.
            search_url = (
                '%s/search/%s?api_key=%s&language=it-IT&include_adult=false&query=%s'
                % (tmdb_host, ctype, tmdb_api, quote(title))
            )
            results = (Tmdb.get_json(search_url) or {}).get('results') or []
        normalized_title = title.casefold()
        exact = next(
            (
                result for result in results
                if str(result.get('title') or result.get('name') or '').strip().casefold()
                == normalized_title
            ),
            None,
        )
        selected = exact or (results[0] if results else None)
        tmdb_id = str((selected or {}).get('id') or '').strip()
        if not tmdb_id:
            return source
        info['tmdb_id'] = tmdb_id
    cache_key = '%s:%s' % (ctype, tmdb_id)
    now = time.time()
    with _DETAIL_CACHE_LOCK:
        cached = _DETAIL_CACHE.get(cache_key)
        metadata = dict(cached['metadata']) if cached and now - cached['ts'] < _DETAIL_CACHE_TTL else None

    if metadata is None:
        from core.tmdb import Tmdb, host as tmdb_host, api as tmdb_api
        url = (
            '%s/%s/%s?api_key=%s&language=it-IT&'
            'append_to_response=credits,release_dates,content_ratings'
        ) % (tmdb_host, ctype, tmdb_id, tmdb_api)
        data = Tmdb.get_json(url) or {}
        if not data:
            return source

        credits = data.get('credits') or {}
        crew = credits.get('crew') or []
        directors = []
        for person in crew:
            if person.get('job') in ('Director', 'Series Director') and person.get('name'):
                if person['name'] not in directors:
                    directors.append(person['name'])
        if ctype == 'tv' and not directors:
            directors = [entry.get('name') for entry in (data.get('created_by') or [])
                         if entry.get('name')]
        cast = [entry.get('name') for entry in (credits.get('cast') or [])[:8]
                if entry.get('name')]

        certifications = []
        rating_group = data.get('content_ratings') if ctype == 'tv' else data.get('release_dates')
        for entry in (rating_group or {}).get('results', []):
            country = entry.get('iso_3166_1')
            if ctype == 'tv':
                value = entry.get('rating')
            else:
                releases = entry.get('release_dates') or []
                value = next((release.get('certification') for release in releases
                              if release.get('certification')), '')
            if value:
                certifications.append((country, value))
        certification = next((value for country, value in certifications if country == 'IT'), '')
        if not certification:
            certification = next((value for country, value in certifications if country == 'US'), '')
        if not certification and certifications:
            certification = certifications[0][1]

        runtime = data.get('runtime') or 0
        if ctype == 'tv' and not runtime:
            runtimes = data.get('episode_run_time') or []
            runtime = runtimes[0] if runtimes else 0
        if ctype == 'tv' and not runtime:
            runtime = (data.get('last_episode_to_air') or {}).get('runtime') or 0
        release_date = data.get('release_date') or data.get('first_air_date') or ''
        production_countries = [
            entry.get('name') or entry.get('iso_3166_1', '')
            for entry in data.get('production_countries', [])
            if entry.get('name') or entry.get('iso_3166_1')
        ]
        if not production_countries:
            production_countries = [
                str(country).strip()
                for country in data.get('origin_country', [])
                if str(country).strip()
            ]
        metadata = {
            'plot': data.get('overview') or '',
            'year': str(release_date)[:4] if release_date else '',
            'genre': ', '.join(entry.get('name', '') for entry in data.get('genres', [])
                               if entry.get('name')),
            'rating': data.get('vote_average') or 0,
            'runtime': runtime,
            'mpaa': certification,
            'premiered': release_date,
            'country': ', '.join(production_countries),
            'studio': ', '.join(
                entry.get('name', '') for entry in data.get('production_companies', [])[:3]
                if entry.get('name')
            ),
            'director': ', '.join(directors[:3]),
            'cast': cast,
            'thumbnail': (
                'https://image.tmdb.org/t/p/w500' + data.get('poster_path')
                if data.get('poster_path') else ''
            ),
            'fanart': (
                'https://image.tmdb.org/t/p/w1280' + data.get('backdrop_path')
                if data.get('backdrop_path') else ''
            ),
        }
        with _DETAIL_CACHE_LOCK:
            if len(_DETAIL_CACHE) >= _DETAIL_CACHE_LIMIT:
                oldest = min(_DETAIL_CACHE, key=lambda key: _DETAIL_CACHE[key]['ts'])
                _DETAIL_CACHE.pop(oldest, None)
            _DETAIL_CACHE[cache_key] = {'metadata': dict(metadata), 'ts': now}

    enriched_info = dict(info)
    for key in ('plot', 'year', 'genre', 'rating', 'runtime', 'mpaa', 'premiered',
                'country', 'studio', 'director', 'cast'):
        value = metadata.get(key)
        if value not in ('', None, [], {}):
            enriched_info[key] = value
    source['infoLabels'] = enriched_info
    for key in ('thumbnail', 'fanart'):
        if metadata.get(key):
            source[key] = metadata[key]
    return source


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
    items = _items_to_list(res)
    if method == 'live' or bool((item_dict or {}).get('_app_live')):
        for value in items:
            value['_app_live'] = True
    return items


def series_episodes(item_dict):
    """Flatten a provider's season/menu tree into native Android episodes."""
    init()
    from platformcode import prippihome
    parent = _to_item(item_dict or {})
    episodes = prippihome._get_channel_episodes(parent)
    series_title = (getattr(parent, 'fulltitle', '') or
                    getattr(parent, 'contentSerieName', '') or
                    getattr(parent, 'title', '') or '')
    parent_channel = (getattr(parent, 'channel', '') or
                      getattr(parent, '_search_channel', '') or '')
    for index, episode in enumerate(episodes, 1):
        episode.contentType = 'episode'
        episode.contentSerieName = (
            getattr(episode, 'contentSerieName', '') or series_title)
        if parent_channel == 'la7':
            # La7 paginates a programme through repeated menu nodes: those are
            # pages/categories, not real seasons. Present one ordered programme.
            display_season, display_episode = 1, index
        else:
            display_season = int(getattr(episode, '_disp_season', 0) or
                                 getattr(episode, 'contentSeason', 0) or 1)
            display_episode = int(getattr(episode, '_disp_ep', 0) or
                                  getattr(episode, 'contentEpisodeNumber', 0) or
                                  getattr(episode, 'episode', 0) or index)
        episode.contentSeason = display_season
        episode.contentEpisodeNumber = display_episode
        episode.season = display_season
        episode.episode = display_episode
    return _items_to_list(episodes)


def _playback_preferences():
    """Preferenze native condivise da VOD, Live, 4K e playback offline."""
    from platformcode import config
    quality = str(config.get_setting('app_video_quality', default='Auto') or 'Auto')
    audio = str(config.get_setting('app_audio_language', default='Italiano') or 'Italiano')
    subtitles = str(
        config.get_setting('app_subtitle_mode', default='Disattivati') or 'Disattivati'
    )
    height = {
        '4K': 2160,
        '2160p': 2160,
        '1080p': 1080,
        '720p': 720,
        '480p': 480,
    }.get(quality, 0)
    payload = {
        'audio_language': {'Inglese': 'en', 'Originale': ''}.get(audio, 'it'),
        'text_language': '' if subtitles == 'Automatici' else 'it',
        'subtitles_enabled': subtitles != 'Disattivati',
        'max_video_height': height,
        'autoplay_next': config.get_setting('app_autoplay_next', default=True) is not False,
        'fallback_enabled': config.get_setting('app_player_fallback', default=True) is not False,
    }
    return payload


def resolve(item_dict):
    """Da un Item riproducibile → dati per il player nativo.
    Se l'item è già una sorgente diretta (url+manifest), la impacchetta;
    altrimenti passa per findvideos del canale.
    Ritorna {url, manifest_type, headers, drm_type, license_key, audio_language, subtitles}."""
    init()
    item = _to_item(item_dict or {})

    # Le dirette TV ufficiali passano dal findvideos del provider proprietario,
    # non dal resolver SKY/Sport.
    if bool((item_dict or {}).get('_app_live_provider')):
        channel = getattr(item, 'channel', '') or ''
        module = __import__('channels.%s' % channel, fromlist=[channel])
        sources = module.findvideos(item) or []
        if not sources:
            raise RuntimeError('Diretta TV non disponibile')
        source = _from_item(sources[0])
        source.pop('_app_live_provider', None)
        source.pop('_app_live', None)
        source['channel'] = channel
        return resolve(source)

    # Le card SKY/Sport/TV non passano da un channel.findvideos: il data-layer
    # dell'addon le risolve in un ListItem validato dal probe. Convertiamo quel
    # ListItem negli stessi dati neutrali consumati dal player Media3.
    if (getattr(item, 'action', '') == 'live_channel' or
            bool((item_dict or {}).get('_app_live'))):
        from platformcode import sportchannels
        li = sportchannels.resolve_validated_listitem(item)
        if li is None:
            li = sportchannels.resolve_listitem(item)
        if li is None:
            raise RuntimeError('Diretta non disponibile')
        live_url = li.getPath() or ''
        raw_headers = (li.getProperty('inputstream.adaptive.stream_headers') or
                       li.getProperty('inputstream.adaptive.manifest_headers') or '')
        headers = {}
        for part in raw_headers.split('&'):
            if '=' in part:
                key, value = part.split('=', 1)
                if key.lower() != 'verifypeer':
                    headers[unquote_plus(key)] = unquote_plus(value)
        if '|' in live_url:
            live_url, pipe_headers = live_url.split('|', 1)
            for part in pipe_headers.split('&'):
                if '=' in part:
                    key, value = part.split('=', 1)
                    headers[unquote_plus(key)] = unquote_plus(value)
        drm_legacy = li.getProperty('inputstream.adaptive.drm_legacy') or ''
        license_key = drm_legacy.split('|', 1)[1] if '|' in drm_legacy else ''
        payload = {
            'url': live_url,
            'bootstrap_url': '',
            'manifest_type': 'mpd' if '.mpd' in live_url.lower() else 'hls',
            'headers': _jsonable(headers),
            'drm_type': 'clearkey' if license_key else '',
            'license_key': license_key,
            'subtitles': [],
            'label': getattr(item, 'fulltitle', '') or getattr(item, 'title', '') or 'Diretta',
            'server': 'live',
        }
        payload.update(_playback_preferences())
        return payload
    url = getattr(item, 'url', '') or ''
    source_url = url
    manifest = (getattr(item, 'manifest', '') or '').lower()
    item_headers = getattr(item, 'headers', {}) or {}
    headers = dict(item_headers) if isinstance(item_headers, dict) else {}
    resolved_subtitles = getattr(item, 'subtitle', '') or ''

    # Le card SC ottenute dalla ricerca/Home sono pagine ``findvideos``. Kodi
    # esegue il passaggio al canale prima del resolver server; il bridge TV
    # deve fare lo stesso, altrimenti passa una pagina /watch/ al player.
    if (getattr(item, 'channel', '') == 'streamingcommunity' and
            getattr(item, 'action', '') == 'findvideos' and
            (getattr(item, 'server', '') or '').strip().lower() in ('', 'directo', 'local')):
        module = __import__('channels.streamingcommunity', fromlist=['streamingcommunity'])
        sources = module.findvideos(item) or []
        if not sources:
            raise RuntimeError('StreamingCommunity non ha restituito una sorgente riproducibile')
        return resolve(_from_item(sources[0]))

    # Se l'item ha un SERVER (es. streamingcommunityws), esegui il resolver reale:
    # iframe/pagina → URL diretto riproducibile (es. playlist vixcloud).
    server = (getattr(item, 'server', '') or '').strip().lower()
    # Alcune card Home SC arrivano già con action ``findvideos`` ma vengono
    # serializzate come ``directo``: la loro URL è ancora una pagina /watch/
    # oppure /iframe/. Senza questa normalizzazione Android/Tizen tentano di
    # riprodurre HTML come fosse un video e non invocano il resolver VixCloud.
    if (server in ('', 'directo', 'local') and
            getattr(item, 'channel', '') == 'streamingcommunity'):
        server = 'streamingcommunityws'
    if server and server not in ('directo', 'local'):
        try:
            from core import servertools
            ret = servertools.resolve_video_urls_for_playing(server, url,
                                                             getattr(item, 'password', '') or '', False)
            video_urls = ret[0] if isinstance(ret, (list, tuple)) else ret
            if not video_urls:
                raise RuntimeError('nessun URL riproducibile restituito dal resolver')
            best = video_urls[-1]          # [label, url, ...]
            label = str(best[0]) if len(best) > 0 else ''
            url = best[1] if len(best) > 1 else ''
            # Diversi resolver storici dell'addon (es. flashx/uptobox)
            # restituiscono [label, url, priority, subtitle]. Kodi lo applica
            # implicitamente; il player nativo deve riceverlo esplicitamente.
            if len(best) > 3 and best[3]:
                resolved_subtitles = best[3]
            if not url:
                raise RuntimeError('URL risolto vuoto')
            if server == 'streamingcommunityws':
                try:
                    module = __import__('servers.streamingcommunityws', fromlist=['streamingcommunityws'])
                    fresh_embed = str(getattr(module, 'bootstrap_url', '') or '')
                    if fresh_embed:
                        source_url = fresh_embed
                except Exception:
                    pass
            if not manifest:
                low_url = url.split('|')[0].lower()
                low_label = label.lower()
                if '.mpd' in low_url or 'dash' in low_label or 'mpd' in low_label:
                    manifest = 'mpd'
                elif ('.m3u8' in low_url or 'playlist' in low_url or
                      'hls' in low_label or server == 'streamingcommunityws'):
                    manifest = 'hls'
                else:
                    # MEGA e la maggior parte degli hoster restituiscono un
                    # file/proxy MP4, non un manifest HLS.
                    manifest = 'progressive'
        except Exception as exc:
            from platformcode import logger
            logger.error('[bridge] resolve server %s: %s' % (server, exc))
            # Alcuni hoster CB01 possono richiedere JavaScript browser. Il
            # captcha Maxstream viene sempre risolto qui in Python: al WebView
            # invisibile passiamo soltanto il gate successivo già sbloccato.
            if server == 'streamingcommunityws':
                module = __import__(
                    'servers.streamingcommunityws',
                    fromlist=['streamingcommunityws'],
                )
                bootstrap = _streamingcommunity_bootstrap_url(module, source_url)
                if not bootstrap:
                    raise RuntimeError(
                        'Resolver streamingcommunityws non disponibile: %s' % exc
                    )
                # Il player Android apre l'embed in un WebView invisibile e
                # intercetta la playlist richiesta dal browser. Questo evita di
                # dipendere dal worker proxy quando restituisce HTML non valido.
                url = bootstrap
                source_url = bootstrap
                manifest = 'bootstrap'
            elif server in ('mixdrop', 'maxstream'):
                bootstrap = source_url
                try:
                    module = __import__('servers.%s' % server, fromlist=[server])
                    if server == 'mixdrop':
                        page = str(getattr(module, 'data', '') or '')
                        if ('WE ARE SORRY' in page or 'ALMOST THERE' in page or
                                '<title>404 Not Found</title>' in page):
                            raise RuntimeError('file Mixdrop non disponibile')
                        unwrap = getattr(module, '_resolve_stayonline', None)
                        if callable(unwrap):
                            bootstrap = unwrap(source_url) or bootstrap
                    else:
                        unlocked = getattr(module, 'get_bootstrap_url', None)
                        bootstrap = unlocked() if callable(unlocked) else ''
                        if not bootstrap:
                            raise RuntimeError('file Maxstream non disponibile')
                except RuntimeError:
                    raise
                except Exception:
                    pass
                url = bootstrap
                source_url = bootstrap
                manifest = 'bootstrap'
            else:
                raise RuntimeError('Resolver %s non disponibile: %s' % (server, exc))

    if not manifest:
        low = url.split('|')[0].lower()
        manifest = ('hls' if ('.m3u8' in low or 'playlist' in low) else
                    ('mpd' if '.mpd' in low else 'progressive'))

    # Replica gli header che platformtools passa a inputstream.adaptive su Kodi.
    # Senza User-Agent + Referer il CDN vixcloud rifiuta il manifest con HTTP 403.
    try:
        from core import httptools
        playback_headers = dict(httptools.default_headers)
        playback_headers.update(headers)
        headers = playback_headers
    except Exception:
        pass
    # Alcuni resolver Kodi incorporano gli header nella URL dopo ``|``.
    # Media3 li vuole invece come request properties separate.
    if '|' in url:
        url, encoded_headers = url.split('|', 1)
        for part in encoded_headers.split('&'):
            if '=' in part:
                key, value = part.split('=', 1)
                headers[unquote_plus(key)] = unquote_plus(value)

    referer = getattr(item, 'referer', '') or source_url
    if referer:
        headers['Referer'] = referer
    # Media3 gestisce autonomamente la compressione; forzarla può far leggere il
    # manifest compresso come testo non valido, lo stesso problema già corretto
    # sul percorso Kodi/inputstream.adaptive.
    headers = {k: v for k, v in headers.items() if str(k).lower() != 'accept-encoding'}
    payload = {
        'url': url,
        # Pagina iframe usata dal percorso Android per ottenere il token nello
        # stesso contesto browser/rete che poi avvia Media3.
        'bootstrap_url': source_url,
        'manifest_type': ('bootstrap' if 'bootstrap' in manifest else
                          ('mpd' if 'mpd' in manifest else
                           ('progressive' if 'progressive' in manifest else 'hls'))),
        'headers': _jsonable(headers),
        'drm_type': getattr(item, 'drm', '') or '',
        'license_key': getattr(item, 'license', '') or '',
        'subtitles': _jsonable(resolved_subtitles),
        'label': getattr(item, 'title', '') or server or 'Sorgente',
        'server': server or 'directo',
    }
    payload.update(_playback_preferences())
    return payload


def _home_row_id(label, index):
    """ID stabile per Compose, derivato dal titolo ufficiale della riga addon."""
    import re
    slug = re.sub(r'[^a-z0-9]+', '_', str(label or '').lower()).strip('_')
    return 'addon_%02d_%s' % (index, slug or 'row')


def _home_payload(sc_rows, anime_items=None):
    rows = list(sc_rows or [])
    try:
        from platformcode import config, prippihome
        if (config.get_setting('show_4k_row') is True and
                prippihome._fourk._ready):
            fourk_items = prippihome._build_4k_row() or []
            if fourk_items:
                rows.insert(0, (u'Film in 4K', fourk_items))
    except Exception:
        pass
    if anime_items:
        from platformcode import prippihome
        rows.append((prippihome._ANIME_ROW_LABEL, anime_items))
    return [
        {'id': _home_row_id(label, index), 'title': label,
         'items': _items_to_list(items)}
        for index, (label, items) in enumerate(rows) if items
    ]


def _fill_home_background(host, homepage_data, main_rows, need_archive):
    """Seconda fase Home 2.0: archivio SC e AnimeUnity, senza bloccare la UI."""
    from platformcode import logger, prippihome
    sc_rows = list(main_rows or [])
    completed = False
    try:
        if need_archive and host:
            if _APP_LOW_POWER:
                # Leave the first rows completely uncontended while Compose
                # establishes focus and decodes the first visible textures.
                time.sleep(3.0)

            # Gli snapshot vecchi/low-power potevano contenere solo il primo
            # lotto. Recupera i metadata correnti (inclusi i generi) e fonde
            # eventuali slider nuovi prima di completare l'archivio.
            if not homepage_data:
                try:
                    fresh_rows, fresh_host, homepage_data = prippihome._fetch_main_rows()
                    if fresh_host:
                        host = fresh_host
                    known = {
                        str(label or '').strip().lower()
                        for label, _items in sc_rows
                    }
                    for label, items in fresh_rows or []:
                        key = str(label or '').strip().lower()
                        if key and key not in known:
                            sc_rows.append((label, items))
                            known.add(key)
                except Exception as exc:
                    logger.error('[bridge] home refresh main rows: %s' % exc)

            archive_rows = prippihome._fetch_archive_rows(
                host,
                homepage_data,
                len(sc_rows),
                max_workers=2 if _APP_LOW_POWER else None,
                max_new_rows=None,
                existing_labels=[label for label, _items in sc_rows],
            ) or []
            known = {
                str(label or '').strip().lower()
                for label, _items in sc_rows
            }
            for label, items in archive_rows:
                key = str(label or '').strip().lower()
                if key and key not in known:
                    sc_rows.append((label, items))
                    known.add(key)
        anime_items = prippihome._fetch_anime_row() or []
        with _HOME_LOCK:
            _HOME_STATE['sc_rows'] = sc_rows
            _HOME_STATE['anime_items'] = anime_items
        # Come nella Home Kodi, completa in background i metadati TMDB delle
        # righe gia' visibili. Le chiamate progressive di home() serializzano
        # gli stessi Item aggiornati, quindi anno/voto/poster compaiono senza
        # rallentare il primo frame dell'app.
        if not _APP_LOW_POWER:
            for _label, items in sc_rows:
                if not items or (items[0].infoLabels or {}).get('_enr'):
                    continue
                try:
                    prippihome._tmdb_enrich_validated(items)
                    for it in items:
                        it.infoLabels['_enr'] = 1
                except Exception as exc:
                    logger.error('[bridge] home enrich %s: %s' % (_label, exc))
        if sc_rows:
            prippihome._snapshot_write(sc_rows, host)
        if sc_rows:
            prippihome._cache['data'] = sc_rows
            prippihome._cache['ts'] = time.time()
            prippihome._snapshot_write(sc_rows, host)
        completed = True
        logger.info('[bridge] home complete: %d rows' % len(sc_rows))
    except Exception as exc:
        logger.error('[bridge] home background: %s' % exc)
    finally:
        with _HOME_LOCK:
            _HOME_STATE['loading'] = False
            _HOME_STATE['complete'] = completed


def home():
    """Home Android dal data-layer ufficiale di ``PrippiHomeWindow``.

    Restituisce subito snapshot/slider principali e completa archivio + Anime
    in background. Le chiamate successive raccolgono le righe gia' pronte.
    """
    global _FOURK_STARTED
    init()
    from platformcode import config, logger, prippihome

    if (not _APP_LOW_POWER and config.get_setting('show_4k_row') is True and
            not _FOURK_STARTED):
        _FOURK_STARTED = True
        threading.Thread(target=prippihome._fourk.build_4k_index, daemon=True).start()

    with _HOME_LOCK:
        cached_rows = _HOME_STATE['sc_rows']
        cached_anime = _HOME_STATE['anime_items']
        loading = _HOME_STATE['loading']
        complete = _HOME_STATE['complete']
    if cached_rows is not None:
        if not loading and not complete:
            _unused_rows, _unused_ts, retry_host = prippihome._snapshot_read()
            if retry_host:
                with _HOME_LOCK:
                    if not _HOME_STATE['loading'] and not _HOME_STATE['complete']:
                        _HOME_STATE['loading'] = True
                        threading.Thread(
                            target=_fill_home_background,
                            args=(retry_host, None, list(cached_rows), True),
                            daemon=True,
                        ).start()
        return _home_payload(cached_rows, cached_anime)

    snapshot_rows, _snapshot_ts, snapshot_host = prippihome._snapshot_read()
    host = snapshot_host
    homepage_data = None
    # Uno snapshot presente non è necessariamente completo: le vecchie build
    # low-power salvavano solo tre righe aggiuntive e poi non le completavano.
    need_archive = len(snapshot_rows or []) < prippihome.SC_MAX_ROWS
    if snapshot_rows:
        main_rows = snapshot_rows
    else:
        try:
            main_rows, host, homepage_data = prippihome._fetch_main_rows()
        except Exception as exc:
            logger.error('[bridge] home main: %s' % exc)
            main_rows = []

        # Rete di sicurezza se la struttura delle pagine slider cambia.
        if not main_rows:
            ch = __import__('channels.streamingcommunity', fromlist=['streamingcommunity'])
            main_rows = []
            for title, category in (
                ('Film aggiunti di recente', 'peliculas'),
                ('Serie TV aggiunte di recente', 'series'),
            ):
                try:
                    items = ch.newest(category) or []
                    if items:
                        main_rows.append((title, items))
                except Exception as exc:
                    logger.error('[bridge] home fallback %s: %s' % (category, exc))

    with _HOME_LOCK:
        _HOME_STATE['sc_rows'] = list(main_rows or [])
        if not loading:
            _HOME_STATE['loading'] = True
            threading.Thread(
                target=_fill_home_background,
                args=(host, homepage_data, list(main_rows or []), need_archive),
                daemon=True,
            ).start()
    return _home_payload(main_rows)


def _refresh_live_background():
    """Aggiorna i parser live senza saturare i dispositivi low-power."""
    global _LIVE_LOADING, _LIVE_REFRESHED_AT
    from platformcode import logger, sportchannels

    def refresh_one(row_key):
        try:
            fresh = sportchannels._PARSERS[row_key]()
            if fresh is not None:
                sportchannels._mem_cache[row_key]['data'] = fresh
                sportchannels._mem_cache[row_key]['ts'] = time.time()
                sportchannels._save_disk_cache(row_key, fresh)
                logger.info('[bridge] live %s pronta: %d canali' % (row_key, len(fresh)))
        except Exception as exc:
            logger.error('[bridge] live refresh %s: %s' % (row_key, exc))

    try:
        sportchannels.reset_state()
        row_keys = ('tv', 'sky', 'sport')
        if _APP_LOW_POWER:
            # Sulle box economiche tre parser/probe contemporanei contendono
            # CPU, rete e memoria proprio mentre la Home deve restare fluida.
            for key in row_keys:
                refresh_one(key)
        else:
            workers = [
                threading.Thread(target=refresh_one, args=(key,), daemon=True)
                for key in row_keys
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        try:
            from platformcode import skyepg
            live_items = []
            for key in row_keys:
                live_items += sportchannels.build_items(key) or []
            epg_keys = [getattr(item, 'sport_par', '') or getattr(item, 'fulltitle', '')
                        for item in live_items]
            skyepg.prefetch([key for key in epg_keys if key])
        except Exception as exc:
            logger.error('[bridge] live EPG: %s' % exc)
    finally:
        with _LIVE_LOCK:
            _LIVE_LOADING = False
            _LIVE_REFRESHED_AT = time.time()


def live_rows():
    """Righe TV, SKY e Sport online, con priorità ai device low-power."""
    global _LIVE_LOADING
    init()
    from platformcode import sportchannels
    from platformcode import skyepg
    rows = []
    for index, key in enumerate(('tv', 'sky', 'sport')):
        items = sportchannels.build_items(key) or []
        for item in items:
            item._app_live = True
            epg = skyepg.now_on(getattr(item, 'sport_par', '') or
                                getattr(item, 'fulltitle', ''))
            if epg:
                when = ('%s–%s' % (epg.get('start', ''), epg.get('end', ''))).strip('–')
                lines = [u'IN ONDA%s' % (u' · ' + when if when else ''), epg.get('prog', '')]
                if epg.get('ep_info') or epg.get('ep_title'):
                    lines.append(' · '.join(x for x in
                        (epg.get('ep_info', ''), epg.get('ep_title', '')) if x))
                if epg.get('next_prog'):
                    lines.append(u'A seguire %s · %s' %
                                 (epg.get('next_start', ''), epg['next_prog']))
                item.infoLabels['plot'] = '\n'.join(line for line in lines if line)
        if items:
            rows.append({
                'id': 'live_' + key,
                'title': sportchannels.row_label(key),
                'items': _items_to_list(items),
            })
    with _LIVE_LOCK:
        if not _LIVE_LOADING and (time.time() - _LIVE_REFRESHED_AT) >= sportchannels._CACHE_TTL:
            _LIVE_LOADING = True
            threading.Thread(target=_refresh_live_background, daemon=True).start()
    return rows


def resolve_4k(item_dict):
    """Candidato 4K dell'indice addon per un film TMDB, oppure dict vuoto."""
    init()
    from platformcode import _fourk, config
    info = (item_dict or {}).get('infoLabels') or {}
    tmdb_id = info.get('tmdb_id') or (item_dict or {}).get('tmdb_id')
    f4k = _fourk.lookup_4k(tmdb_id)
    if not f4k:
        return {}
    url = _fourk.get_resolved_url(f4k) or ''
    if not url:
        return {}
    headers = {}
    if '|' in url:
        url, encoded_headers = url.split('|', 1)
        for part in encoded_headers.split('&'):
            if '=' in part:
                key, value = part.split('=', 1)
                headers[unquote_plus(key)] = unquote_plus(value)
    payload = {
        'url': url,
        'bootstrap_url': '',
        'manifest_type': ('hls' if '.m3u8' in url.lower() else
                          'mpd' if '.mpd' in url.lower() else 'progressive'),
        'headers': headers,
        'drm_type': '',
        'license_key': '',
        'subtitles': [],
        'label': '4K Ultra HD',
        'server': 'fourk',
        'ask_quality': config.get_setting('fourk_ask_quality') is True,
    }
    payload.update(_playback_preferences())
    return payload


def fhd_for_4k(item_dict):
    """Controparte StreamingCommunity usata dall'addon come fallback FHD."""
    init()
    from platformcode import prippihome
    item = _to_item(item_dict or {})
    found = prippihome._resolve_sc_movie(item)
    return _from_item(found) if found is not None else {}


def global_search(text, timeout=18):
    """Ricerca globale headless con le stesse regole di PrippiSearchWindow.

    StreamingCommunity viene risolto per primo; i provider successivi non sono
    hard-coded, ma arrivano dagli stessi flag ``include_in_global_search`` usati
    dall'addon. Filtri, cache, classificazione e priorita' di deduplica chiamano
    direttamente gli helper del data-layer di ``platformcode.prippihome``.
    """
    init()
    import re
    import time
    from concurrent.futures import ThreadPoolExecutor, wait
    from core.item import Item
    from platformcode import logger, prippihome, deviceprofile
    import channelselector

    query = str(text or '').strip()
    if not query:
        return []
    deadline = time.monotonic() + max(3, int(timeout))
    query_clean = re.sub(r'\[/?[A-Za-z][^\]]*\]', '', query).strip().lower()

    # Condivide anche la cache finale dell'addon: stessi payload e stessa TTL.
    cache_hit, cached = prippihome._search_final_cache_get(query)
    if cache_hit and cached and all(
            getattr(item, '_app_search_bridge_version', 0) == 2 for item in cached):
        return _items_to_list(cached)[:120]

    def valid_thumb(item):
        value = (getattr(item, 'thumbnail', '') or '').strip()
        return bool(value) and value.lower() not in ('none', 'false', 'null', 'n/a')

    def mark(item, source):
        item._search_channel = 'sc' if source == 'streamingcommunity' else source
        item._search_type = prippihome._classify_search_item(item)
        item._app_search_source = source
        if not getattr(item, 'channel', ''):
            item.channel = source
        return item

    # 1) StreamingCommunity, come nell'addon, prima degli altri provider.
    sc_items = []
    sc_tmdb_ids = set()
    try:
        hit, raw = prippihome._search_provider_cache_get('streamingcommunity', query)
        if not hit:
            from channels import streamingcommunity as sc
            raw = list(sc.search(Item(channel='streamingcommunity', extra='search',
                                      text_color='FFFFFFFF'), query) or [])
            prippihome._search_provider_cache_put('streamingcommunity', query, raw)
        sc_items = [mark(item, 'streamingcommunity') for item in raw
                    if valid_thumb(item) and not prippihome._is_pagination_item(item)]
        for item in sc_items:
            info = getattr(item, 'infoLabels', None) or {}
            tmdb = info.get('tmdb_id') or info.get('tmdb')
            if tmdb:
                sc_tmdb_ids.add(str(tmdb))
    except Exception as exc:
        logger.error('[bridge] global search streamingcommunity: %s' % str(exc)[:160])

    # Stessa scoperta dinamica dell'addon (attivo, abilitato, lingua e flag JSON).
    channels = []
    try:
        from core import channeltools
        for channel_item in channelselector.filterchannels('all'):
            channel_id = channel_item.channel
            if channel_id == 'streamingcommunity':
                continue
            params = channeltools.get_channel_parameters(channel_id)
            if params.get('active', False) and params.get('include_in_global_search', False):
                channels.append(channel_id)
    except Exception as exc:
        logger.error('[bridge] global search channel discovery: %s' % str(exc)[:160])

    article_re = re.compile(r'^(il |la |lo |i |le |gli |l |un |una |uno |the |a |an )')
    q_norm = re.sub(r'[^a-z0-9 ]', '', query_clean).strip()
    q_has_article = bool(article_re.match(q_norm))
    q_stripped = article_re.sub('', q_norm, count=1).strip()
    stopwords = {
        'il', 'lo', 'la', 'i', 'gli', 'le', 'l', 'un', 'uno', 'una',
        'di', 'del', 'dello', 'della', 'dei', 'degli', 'delle',
        'a', 'ad', 'al', 'allo', 'alla', 'ai', 'agli', 'alle',
        'da', 'dal', 'dallo', 'dalla', 'dai', 'dagli', 'dalle',
        'in', 'nel', 'nello', 'nella', 'nei', 'negli', 'nelle',
        'con', 'col', 'coi', 'su', 'sul', 'sullo', 'sulla', 'sui', 'sugli', 'sulle',
        'per', 'tra', 'fra', 'e', 'ed', 'o', 'od',
        'the', 'an', 'of', 'and', 'or', 'to', 'on', 'at',
    }

    def significant_words(value):
        return [word for word in value.split() if word not in stopwords]

    q_sig = significant_words(q_norm)

    official_channels = {'raiplay', 'mediasetplay', 'la7'}

    def title_matches(value, anime=False, official=False):
        if (value == q_norm or value.startswith(q_norm + ' ')
                or q_norm.startswith(value + ' ')):
            return True
        if q_has_article:
            stripped = article_re.sub('', value, count=1).strip()
            if (stripped == q_stripped or stripped.startswith(q_stripped + ' ')
                    or q_stripped.startswith(stripped + ' ')):
                return True
            words = significant_words(value)
            size = min(len(q_sig), len(words))
            if size >= 2 and q_sig[:size] == words[:size]:
                return True
        return bool((anime or official) and q_norm and re.search(
            r'(?:^|\s)' + re.escape(q_norm) + r'(?:\s|$)', value))

    def run(channel_id):
        try:
            module = __import__('channels.%s' % channel_id, fromlist=[channel_id])
            fn = getattr(module, 'search', None)
            if not callable(fn):
                return []
            hit, raw = prippihome._search_provider_cache_get(channel_id, query)
            if not hit:
                raw = list(fn(Item(channel=channel_id), query) or [])
                prippihome._search_provider_cache_put(channel_id, query, raw)
            anime_channel = prippihome._channel_is_anime(channel_id)
            result = []
            for item in raw:
                if prippihome._is_pagination_item(item):
                    continue
                info = getattr(item, 'infoLabels', None) or {}
                tmdb = info.get('tmdb_id') or info.get('tmdb')
                if tmdb and str(tmdb) in sc_tmdb_ids:
                    continue
                raw_title = re.sub(r'\[/?[A-Za-z][^\]]*\]', '',
                                   (item.fulltitle or item.title or '')).strip().lower()
                normalized = re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', '', raw_title)).strip()
                if q_norm and not title_matches(
                        normalized, anime_channel, channel_id in official_channels):
                    continue
                result.append(mark(item, channel_id))
            return result
        except Exception as exc:
            logger.error('[bridge] global search %s: %s' % (channel_id, str(exc)[:160]))
            return []

    others = []
    remaining = max(0.1, deadline - time.monotonic())
    if channels and remaining > 0:
        pool = ThreadPoolExecutor(max_workers=min(
            len(channels), deviceprofile.worker_count('search', 6)))
        futures = {pool.submit(run, channel): channel for channel in channels}
        done, pending = wait(list(futures), timeout=remaining)
        # Ordine deterministico uguale alla lista provider, non al tempo di risposta.
        for channel in channels:
            future = next((f for f, c in futures.items() if c == channel), None)
            if future in done:
                try:
                    others.extend(future.result() or [])
                except Exception:
                    pass
        for future in pending:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)

    combined = list(sc_items) + others

    def item_tmdb(item):
        info = getattr(item, 'infoLabels', None) or {}
        return str(info.get('tmdb_id') or info.get('tmdb')
                   or getattr(item, '_pref_tmdb', '') or '')

    # Anche l'arricchimento anime e la preferenza AnimeUnity sono quelli addon.
    anime_no_tmdb = [item for item in combined
                     if getattr(item, '_search_type', '') == 'anime' and not item_tmdb(item)]
    if anime_no_tmdb and time.monotonic() < deadline:
        native = [(item, item.thumbnail, item.fanart,
                   (item.infoLabels or {}).get('plot', ''),
                   (item.infoLabels or {}).get('title', '')) for item in anime_no_tmdb]
        try:
            prippihome._tmdb_enrich_validated(anime_no_tmdb)
        except Exception as exc:
            logger.error('[bridge] global search anime enrich: %s' % str(exc)[:160])
        for item, thumb, fanart, plot, title in native:
            matched = item_tmdb(item)
            if matched:
                item._pref_tmdb = matched
                item.infoLabels.pop('tmdb_id', None)
                item.infoLabels.pop('tmdb', None)
                item.infoLabels.pop('imdb_id', None)
            if thumb:
                item.thumbnail = thumb
            if fanart:
                item.fanart = fanart
            if plot:
                item.infoLabels['plot'] = plot
            if title:
                item.infoLabels['title'] = title

    animeunity_tmdb = {item_tmdb(item) for item in combined
                       if getattr(item, '_search_channel', '') == 'animeunity' and item_tmdb(item)}
    if animeunity_tmdb:
        combined = [item for item in combined
                    if getattr(item, '_search_channel', '') == 'animeunity'
                    or getattr(item, '_search_type', '') != 'anime'
                    or item_tmdb(item) not in animeunity_tmdb]

    def clean_title(item):
        value = re.sub(r'\[/?[A-Za-z][^\]]*\]', '',
                       (item.fulltitle or item.title or '').lower()).strip()
        return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', '', value)).strip()

    def relevance(item):
        value = clean_title(item)
        source = getattr(item, '_search_channel', '')
        exact = value == q_norm or (len(q_sig) >= 2 and significant_words(value) == q_sig)
        starts, contains = value.startswith(q_norm), q_norm in value
        base = 0 if source == 'sc' else (1 if source == 'cineblog01' else 2)
        bucket = 0 if exact else (3 if starts else (6 if contains else 9))
        return bucket + base, value

    combined.sort(key=relevance)

    def normalized_title(item):
        value = clean_title(item)
        source = getattr(item, '_search_channel', '') or getattr(item, 'channel', '')
        if (source in official_channels and q_norm
                and re.search(r'(?:^|\s)' + re.escape(q_norm) + r'(?:\s|$)', value)):
            query_significant = ' '.join(q_sig)
            return query_significant or q_norm
        significant = ' '.join(significant_words(value))
        return significant or article_re.sub('', value, count=1)

    source_priority = {'sc': 0, 'streamingcommunity': 0, 'hd4me': 1, 'cineblog01': 2}

    def attach_fallback(primary, alternate):
        """Conserva le edizioni scartate dalla deduplica per il player Android.

        L'addon mantiene l'intera lista server nel DB del player; l'app deve fare
        altrettanto anche quando due provider rappresentano lo stesso titolo.
        """
        values = list(getattr(primary, '_app_fallback_items', []) or [])
        raw = _from_item(alternate)
        inherited = list(raw.pop('_app_fallback_items', []) or [])
        values.append(raw)
        values.extend(inherited)
        unique, seen = [], set()
        for value in values:
            if not isinstance(value, dict):
                continue
            key = (value.get('channel', ''), value.get('action', ''),
                   value.get('url', ''), value.get('fulltitle') or value.get('title', ''))
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
        primary._app_fallback_items = unique[:8]

    deduped, seen_tmdb, seen_title = [], {}, {}
    for item in combined:
        if not valid_thumb(item):
            continue
        title_key = normalized_title(item)
        tmdb = item_tmdb(item)
        duplicate_index = None
        matched_by_tmdb = False
        if tmdb and tmdb in seen_tmdb:
            previous = deduped[seen_tmdb[tmdb]]
            if not (title_key and getattr(item, '_search_channel', '') ==
                    getattr(previous, '_search_channel', '') and
                    title_key != normalized_title(previous)):
                duplicate_index = seen_tmdb[tmdb]
                matched_by_tmdb = True
        elif title_key and title_key in seen_title:
            candidate = seen_title[title_key]
            candidate_tmdb = item_tmdb(deduped[candidate])
            if not (tmdb and candidate_tmdb and candidate_tmdb != tmdb):
                duplicate_index = candidate
        if duplicate_index is not None:
            previous = deduped[duplicate_index]
            previous_tmdb = item_tmdb(previous)
            replacement = False
            if (getattr(item, '_search_type', '') == 'anime'
                    and getattr(previous, '_search_type', '') != 'anime'
                    and (matched_by_tmdb or not previous_tmdb)):
                replacement = True
            elif getattr(previous, '_search_type', '') != 'anime':
                current_source = getattr(item, '_search_channel', '') or item.channel
                previous_source = getattr(previous, '_search_channel', '') or previous.channel
                if source_priority.get(current_source, 5) < source_priority.get(previous_source, 5):
                    replacement = True
            if replacement:
                attach_fallback(item, previous)
                deduped[duplicate_index] = item
            else:
                attach_fallback(previous, item)
            continue
        if not tmdb and not title_key:
            continue
        index = len(deduped)
        if tmdb:
            seen_tmdb[tmdb] = index
        if title_key:
            seen_title[title_key] = index
        deduped.append(item)

    if 'one piece' in re.sub(r'[^a-z0-9 ]', '', query_clean):
        deduped = prippihome._onepiece_curate(deduped, want_extras=True,
                                              at_front=True, force=True)
    for item in deduped:
        item._app_search_bridge_version = 2
    prippihome._search_final_cache_put(query, deduped)
    return _items_to_list(deduped)[:120]


def channel_catalog(category=None):
    """Catalogo canali attivi dell'addon, senza dipendenze dalla UI Kodi."""
    init()
    from core import channeltools
    from platformcode import config
    root = config.get_runtime_path()
    out = []
    for path in sorted(glob.glob(os.path.join(root, 'channels', '*.json'))):
        channel_id = os.path.splitext(os.path.basename(path))[0]
        try:
            params = channeltools.get_channel_parameters(channel_id)
            categories = list(params.get('categories') or [])
            if not params.get('channel') or not params.get('active'):
                continue
            enabled = config.get_setting('enabled', channel_id, default=True)
            if enabled is False:
                continue
            if category and category not in categories:
                continue
            out.append({
                'id': channel_id,
                'title': params.get('title') or channel_id,
                'thumbnail': params.get('thumbnail') or '',
                'fanart': params.get('fanart') or '',
                'categories': categories,
                'language': list(params.get('language') or []),
                'has_settings': bool(params.get('has_settings')),
            })
        except Exception as exc:
            from platformcode import logger
            logger.error('[bridge] catalog channel %s: %s' % (channel_id, exc))
    out.sort(key=lambda value: str(value.get('title', '')).lower())
    return out


def browse_macros():
    """Macro ufficiali della schermata Sfoglia dell'addon 2.0."""
    init()
    from platformcode import config
    values = [
        ('film', 'Film'),
        ('serie', 'Serie TV'),
        ('kdrama', 'K-Drama'),
        ('anime', 'Anime'),
    ]
    if bool(config.get_setting('show_adult_anime')):
        values.append(('hentai', 'Hentai'))
    return [{
        'title': title,
        'fulltitle': title,
        'channel': '_app_macro',
        'action': '_app_macro_genres',
        '_app_macro': macro,
        'thumbnail': '',
    } for macro, title in values]


def browse_macro_call(item_dict):
    """Espone il data-layer di PrippiBrowseWindow senza la UI Kodi."""
    init()
    from platformcode import prippihome
    action = (item_dict or {}).get('action') or ''
    macro = (item_dict or {}).get('_app_macro') or 'film'
    genres = prippihome._br_fetch_genres(macro)
    if action == '_app_macro_genres':
        return [{
            'title': g.get('name') or 'Tutti',
            'fulltitle': g.get('name') or 'Tutti',
            'channel': '_app_macro',
            'action': '_app_macro_titles',
            '_app_macro': macro,
            '_app_genre_index': index,
        } for index, g in enumerate(genres)]
    if action != '_app_macro_titles':
        if action not in ('_app_macro_more', '_app_macro_sort'):
            return []

    def controls(session_id, browser, items):
        sort = browser._sort
        result = [{
            'title': 'Ordina: ' + ('Più recenti' if sort == 'recent' else 'Meno recenti'),
            'fulltitle': 'Ordina: ' + ('Più recenti' if sort == 'recent' else 'Meno recenti'),
            'channel': '_app_macro',
            'action': '_app_macro_sort',
            '_app_browse_session': session_id,
            '_app_macro': browser._macro,
            '_app_sort': sort,
        }]
        result.extend(_items_to_list(items))
        if browser._has_more:
            result.append({
                'title': 'Carica altri titoli',
                'fulltitle': 'Carica altri titoli',
                'channel': '_app_macro',
                'action': '_app_macro_more',
                '_app_browse_session': session_id,
                '_app_macro': browser._macro,
                '_app_sort': sort,
            })
        return result

    session_id = str((item_dict or {}).get('_app_browse_session') or '')
    session = _BROWSE_SESSIONS.get(session_id)
    if action in ('_app_macro_more', '_app_macro_sort') and session:
        browser = session['browser']
        session['touched'] = time.time()
        if action == '_app_macro_more':
            genre = browser._genres[browser._genre_idx]
            sc_items, other_items = browser._fetch_batch(browser._macro, genre, append=True)
            new_items = browser._dedup_new(browser._items, sc_items, other_items)
            browser._items = list(browser._items) + new_items
            return controls(session_id, browser, browser._items)
        # Il pulsante sort dell'addon alterna recent/old e riparte dalla prima pagina.
        item_dict = dict(item_dict or {})
        item_dict['_app_macro'] = browser._macro
        item_dict['_app_genre_index'] = browser._genre_idx
        item_dict['_app_sort'] = 'old' if browser._sort == 'recent' else 'recent'
        macro = browser._macro
        genres = browser._genres

    index = int((item_dict or {}).get('_app_genre_index') or 0)
    genre = genres[index] if 0 <= index < len(genres) else genres[0]
    browser = prippihome.PrippiBrowseWindow('', '')
    browser._macro = macro
    browser._sort = (item_dict or {}).get('_app_sort') or 'recent'
    browser._genres = genres
    browser._genre_idx = index
    sc_items, other_items = browser._fetch_batch(macro, genre, append=False)
    browser._items = browser._dedup_new([], sc_items, other_items)
    if macro in ('anime', 'serie'):
        browser._items = prippihome._onepiece_curate(browser._items, want_extras=False)

    session_id = uuid.uuid4().hex
    _BROWSE_SESSIONS[session_id] = {'browser': browser, 'touched': time.time()}
    if len(_BROWSE_SESSIONS) > _BROWSE_SESSION_LIMIT:
        oldest = min(_BROWSE_SESSIONS, key=lambda key: _BROWSE_SESSIONS[key]['touched'])
        if oldest != session_id:
            _BROWSE_SESSIONS.pop(oldest, None)
    return controls(session_id, browser, browser._items)


def settings_schema():
    """Impostazioni visibili dell'addon con valore corrente.

    La UI Android usa questo schema come sorgente unica: quando settings.xml
    cambia nella v2, la schermata nativa riceve automaticamente le nuove voci.
    """
    init()
    from platformcode import config
    path = os.path.join(config.get_runtime_path(), 'resources', 'settings.xml')
    root = ET.parse(path).getroot()
    playback_settings = [
        ('app_video_quality', 'Qualità video massima', 'select', 'Auto',
         ['Auto', '2160p', '1080p', '720p', '480p']),
        ('app_audio_language', 'Lingua audio preferita', 'select', 'Italiano',
         ['Italiano', 'Originale', 'Inglese']),
        ('app_subtitle_mode', 'Sottotitoli', 'select', 'Disattivati',
         ['Italiani', 'Automatici', 'Disattivati']),
        ('app_autoplay_next', 'Avvia automaticamente il prossimo episodio', 'bool', True, []),
        ('app_player_fallback', 'Prova automaticamente la sorgente successiva', 'bool', True, []),
        ('app_allow_4k_metered', 'Consenti 4K su reti a consumo', 'bool', False, []),
        ('app_treat_wifi_metered', 'Tratta il Wi-Fi come hotspot/rete a consumo', 'bool', False, []),
    ]
    categories = [{
        'label': 'Riproduzione',
        'settings': [{
            'id': setting_id,
            'label': label,
            'type': setting_type,
            'default': default,
            'value': _jsonable(config.get_setting(setting_id, default=default)),
            'values': values,
            'range': [],
            'enabled': True,
        } for setting_id, label, setting_type, default, values in playback_settings],
    }]
    # Impostazioni legate esclusivamente all'ambiente Kodi/telecomando TV.
    # Restano nel motore sincronizzato (e quindi nell'addon), ma non devono
    # comparire nell'app Android touch: la versione è già mostrata nell'header
    # e l'app viene avviata dal launcher Android.
    app_ignored_settings = {
        'addon_version_display',
        'autostart',
        'resolver_dns_provider',
        'live_remote_enabled',
        'live_remote_overlay',
        'live_remote_learn',
    }
    for category in root.findall('category'):
        settings = []
        for node in category.findall('setting'):
            setting_id = node.get('id') or ''
            if (not setting_id or setting_id in app_ignored_settings or
                    node.get('visible', '').lower() == 'false'):
                continue
            setting_type = node.get('type') or 'text'
            values = (node.get('values') or '').split('|') if node.get('values') else []
            range_values = (node.get('range') or '').split(',') if node.get('range') else []
            settings.append({
                'id': setting_id,
                'label': node.get('label') or setting_id,
                'type': setting_type,
                'default': node.get('default') or '',
                'value': _jsonable(config.get_setting(setting_id, default=node.get('default') or '')),
                'values': values,
                'range': range_values,
                'enabled': (node.get('enable') or '').lower() != 'false',
            })
        if settings:
            categories.append({'label': category.get('label') or '', 'settings': settings})

    # Le configurazioni provider restano nei channels/*.json e continuano a
    # essere lette internamente dal motore. Non fanno parte del contratto UI
    # Android, che espone soltanto impostazioni proprie e di riproduzione.
    return categories


def set_setting(setting_id, value, channel_id=''):
    init()
    from platformcode import config
    if channel_id:
        try:
            path = os.path.join(config.get_runtime_path(), 'channels', channel_id + '.json')
            with open(path, 'r', encoding='utf-8') as handle:
                raw_settings = json.load(handle).get('settings') or []
            raw = next((item for item in raw_settings if item.get('id') == setting_id), None)
            values = list((raw or {}).get('lvalues') or (raw or {}).get('values') or [])
            if (raw or {}).get('type') in ('list', 'select') and value in values:
                value = values.index(value)
        except Exception:
            pass
    return _jsonable(config.set_setting(setting_id, value, channel=channel_id or ''))


# ── download offline ────────────────────────────────────────────────────────

def downloads_list():
    """Stato persistente della stessa coda download usata dall'addon 2.0."""
    init()
    from platformcode import downloads_db
    downloads_db.repair_completed()
    return [_jsonable(entry) for entry in downloads_db.get_all()]


def downloads_resume_once():
    """Riprende una sola volta per processo solo i job interrotti.

    Viene chiamata dal servizio Android al vero avvio del processo, mai dalla
    semplice apertura della schermata Download.
    """
    global _DOWNLOADS_RESUMED
    init()
    if not _DOWNLOADS_RESUMED:
        from platformcode import download_manager, downloads_db
        _DOWNLOADS_RESUMED = True
        downloads_db.repair_completed()
        downloads_db.migrate_legacy_network_errors()
        download_manager.get_manager().resume_pending()
    return downloads_list()


def download_network_state(available):
    """Aggiorna il gate della coda dalla rete *validata* osservata da Android."""
    init()
    from platformcode import download_manager
    download_manager.get_manager().set_network_available(bool(available))
    return True


def download_enqueue(item_dict, target_height=0):
    """Accoda un film/episodio lasciando al motore la risoluzione del server."""
    init()
    from platformcode import download_manager, downloads_db
    item = _to_item(item_dict or {})
    manager = download_manager.get_manager()
    manager.enqueue(item, int(target_height or 0))
    key = download_manager._entry_from_item(item).get('key')
    return _jsonable(downloads_db.get(key) or {'key': key, 'status': 'queued'})


def download_enqueue_resolved(item_dict, media_url, headers=None, target_height=0,
                              subtitle_urls=None):
    """Accoda usando la playlist già autorizzata dal WebView Android."""
    prepared = dict(item_dict or {})
    prepared['_app_media_url'] = media_url
    prepared['_app_media_headers'] = dict(headers or {})
    prepared['_app_subtitle_urls'] = list(subtitle_urls or [])
    return download_enqueue(prepared, target_height)


def download_pause(key):
    init()
    from platformcode import download_manager, downloads_db
    download_manager.get_manager().cancel(key)
    return _jsonable(downloads_db.get(key) or {})


def download_resume(key):
    init()
    from core.item import Item
    from platformcode import download_manager, downloads_db
    entry = downloads_db.get(key) or {}
    item_url = entry.get('item_url') or ''
    if not item_url:
        raise RuntimeError('Download non ripristinabile: sorgente mancante')
    item = Item().fromurl(item_url)
    download_manager.get_manager().enqueue(
        item,
        entry.get('target_height', 0),
        protection=entry.get('protection'),
        db_entry=entry,
        audio_langs=entry.get('audio_langs'),
        sub_langs=entry.get('sub_langs'),
    )
    return _jsonable(downloads_db.get(key) or {})


def download_remove(key):
    init()
    from platformcode import downloads_db
    entry = downloads_db.get(key) or {}
    if entry.get('status') in ('queued', 'downloading'):
        raise RuntimeError('Metti prima in pausa il download')
    downloads_db.remove(key, delete_files=True)
    return True


def download_playback(key):
    """URL loopback che decritta al volo il file/bundle, compatibile Media3."""
    init()
    from platformcode import downloads_db, local_stream_server
    downloads_db.repair_completed()
    entry = downloads_db.get(key) or {}
    if entry.get('status') != 'done':
        raise RuntimeError('Il download non è ancora completo')
    is_bundle = bool(entry.get('bundle'))
    payload = {
        'url': local_stream_server.url_for(key),
        'bootstrap_url': '',
        'manifest_type': 'hls' if is_bundle else 'progressive',
        'headers': {},
        'subtitles': ([u'file://' + quote(entry.get('sub_path'), safe='/')]
                      if entry.get('sub_path') else []),
    }
    payload.update(_playback_preferences())
    return payload


def trailer_urls(item_dict):
    """Return ordered YouTube trailer candidates for the embedded Android player.

    Some uploads reject iframe playback. Supplying the YouTube-search result
    plus all suitable TMDB videos lets the app transparently try the next one,
    without opening the YouTube website or another app.
    """
    init()
    from platformcode import prippihome
    item = _to_item(item_dict or {})
    info = getattr(item, 'infoLabels', None) or {}
    title = (getattr(item, 'fulltitle', '') or getattr(item, 'title', '') or
             info.get('title') or '').strip()
    year = str(info.get('year') or getattr(item, 'year', '') or '')[:4]
    tmdb_id = str(info.get('tmdb_id') or getattr(item, 'tmdb_id', '') or '')
    media = str(info.get('mediatype') or getattr(item, 'contentType', '') or '').lower()
    ctype = 'tv' if media in ('tv', 'tvshow', 'serie', 'season', 'episode') else 'movie'
    cache_key = tmdb_id or (u'%s:%s' % (title.lower(), year))
    cached = prippihome._trailer_cache.get(cache_key)
    if cached is False:
        return []
    video_ids = []

    def _add(value):
        if not value:
            return
        match = re.search(r'(?:youtu\.be/|[?&]v=|/embed/)([A-Za-z0-9_-]{6,})', str(value))
        video_id = match.group(1) if match else str(value)
        if re.match(r'^[A-Za-z0-9_-]{6,}$', video_id) and video_id not in video_ids:
            video_ids.append(video_id)

    if cached:
        _add(cached)
    if not video_ids:
        _add(prippihome._youtube_search_trailer(
            title, year, prippihome._trailer_kind(item)) or '')
    if tmdb_id:
        for candidate in prippihome._tmdb_get_trailer_candidates(tmdb_id, ctype):
            _add(candidate)
    prippihome._trailer_cache[cache_key] = video_ids[0] if video_ids else False
    return ['https://www.youtube.com/watch?v=' + video_id for video_id in video_ids]


def trailer_url(item_dict):
    """Compatibility wrapper for older Android/Kodi bridge callers."""
    urls = trailer_urls(item_dict)
    return urls[0] if urls else ''


# ── helper JSON per il ponte Kotlin (Chaquopy passa/riceve stringhe comodamente) ─

def call_json(channel_id, method, item_json='{}', text=None):
    return json.dumps(channel_call(channel_id, method,
                                   json.loads(item_json or '{}'), text), ensure_ascii=False)


def series_episodes_json(item_json='{}'):
    return json.dumps(series_episodes(json.loads(item_json or '{}')), ensure_ascii=False)


def channel_methods_json(channel_id):
    return json.dumps(channel_methods(channel_id), ensure_ascii=False)


def resolve_json(item_json='{}'):
    return json.dumps(resolve(json.loads(item_json or '{}')), ensure_ascii=False)


def resolve_4k_json(item_json='{}'):
    return json.dumps(resolve_4k(json.loads(item_json or '{}')), ensure_ascii=False)


def fhd_for_4k_json(item_json='{}'):
    return json.dumps(fhd_for_4k(json.loads(item_json or '{}')), ensure_ascii=False)


def home_json():
    return json.dumps(home(), ensure_ascii=False)


def live_rows_json():
    return json.dumps(live_rows(), ensure_ascii=False)


def global_search_json(text, timeout=18):
    return json.dumps(global_search(text, timeout), ensure_ascii=False)


def search_history_json(action='load', query=''):
    """Cronologia ufficiale dell'addon (stesso file atomico e stesso limite)."""
    init()
    from platformcode import search_history, prippihome
    limit = prippihome._search_history_limit()
    if action == 'save':
        values = search_history.save(query, limit)
    elif action == 'clear':
        search_history.clear()
        values = []
    else:
        values = search_history.load(limit)
    return json.dumps(values, ensure_ascii=False)


def channel_catalog_json(category=None):
    return json.dumps(channel_catalog(category), ensure_ascii=False)


def browse_macros_json():
    return json.dumps(browse_macros(), ensure_ascii=False)


def browse_macro_call_json(item_json='{}'):
    return json.dumps(browse_macro_call(json.loads(item_json or '{}')), ensure_ascii=False)


def settings_schema_json():
    return json.dumps(settings_schema(), ensure_ascii=False)


def set_setting_json(setting_id, value, channel_id=''):
    return json.dumps(set_setting(setting_id, value, channel_id), ensure_ascii=False)


def downloads_list_json(resume=False):
    values = downloads_resume_once() if resume else downloads_list()
    return json.dumps(values, ensure_ascii=False)


def download_network_state_json(available):
    return json.dumps(download_network_state(available), ensure_ascii=False)


def download_enqueue_json(item_json='{}', target_height=0):
    return json.dumps(download_enqueue(json.loads(item_json or '{}'), target_height), ensure_ascii=False)


def download_enqueue_resolved_json(item_json='{}', media_url='', headers_json='{}',
                                   target_height=0, subtitles_json='[]'):
    return json.dumps(download_enqueue_resolved(
        json.loads(item_json or '{}'), media_url,
        json.loads(headers_json or '{}'), target_height,
        json.loads(subtitles_json or '[]'),
    ), ensure_ascii=False)


def download_pause_json(key):
    return json.dumps(download_pause(key), ensure_ascii=False)


def download_resume_json(key):
    return json.dumps(download_resume(key), ensure_ascii=False)


def download_remove_json(key):
    return json.dumps(download_remove(key), ensure_ascii=False)


def download_playback_json(key):
    return json.dumps(download_playback(key), ensure_ascii=False)


def trailer_url_json(item_json='{}'):
    return json.dumps(trailer_url(json.loads(item_json or '{}')), ensure_ascii=False)


def trailer_urls_json(item_json='{}'):
    return json.dumps(trailer_urls(json.loads(item_json or '{}')), ensure_ascii=False)
