(function () {
  'use strict';

  var TMDB_KEY = 'a1ab8b8669da03637a4b98fa39c39228';
  var TMDB = 'https://api.themoviedb.org/3';
  var SC_FALLBACKS = [
    'https://streamingcommunityz.support',
    'https://streamingcommunityz.pizza',
    'https://streamingcommunityz.run'
  ];
  var HOST_KEY = 'prippi.tizen.sc.host';
  var HOME_KEY = 'prippi.tizen.standalone.home.v1';
  var hostPromise = null;
  var mediasetAuthPromise = null;
  var mediasetAuthAt = 0;
  var discoverySessionPromise = null;

  function timeoutFetch(url, options, timeout) {
    return new Promise(function (resolve, reject) {
      var done = false;
      var timer = setTimeout(function () {
        if (!done) reject(new Error('Timeout rete'));
      }, timeout || 10000);
      fetch(url, options || {}).then(function (response) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        if (!response.ok) throw new Error('HTTP ' + response.status);
        resolve(response);
      }).catch(function (error) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  function text(url, options, timeout) {
    return timeoutFetch(url, options, timeout).then(function (response) {
      return response.text().then(function (body) {
        return {body: body, url: response.url || url};
      });
    });
  }

  function json(url, options, timeout) {
    return timeoutFetch(url, options, timeout).then(function (response) { return response.json(); });
  }

  function cleanUrl(value) {
    var area = document.createElement('textarea');
    area.innerHTML = String(value || '').replace(/\\\//g, '/');
    return area.value.trim();
  }

  function queryString(values) {
    var parts = [];
    Object.keys(values || {}).forEach(function (key) {
      var value = values[key];
      if (value === undefined || value === null) return;
      if (typeof value === 'object') value = JSON.stringify(value);
      parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(value)));
    });
    return parts.join('&');
  }

  function parsePage(html) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var node = doc.querySelector('[data-page]');
    if (!node) throw new Error('Pagina provider non riconosciuta');
    return JSON.parse(node.getAttribute('data-page') || '{}');
  }

  function unique(values) {
    var seen = {}, out = [];
    values.forEach(function (value) {
      value = String(value || '').replace(/\/$/, '');
      if (value && !seen[value]) { seen[value] = true; out.push(value); }
    });
    return out;
  }

  function registryHost() {
    return json('https://raw.githubusercontent.com/usandissm/PrippiStream/main/channels.json?_=' + Date.now(), {cache: 'no-store'}, 6000)
      .then(function (data) { return data && data.direct && data.direct.streamingcommunity; })
      .catch(function () { return ''; });
  }

  function probe(candidates, index) {
    if (index >= candidates.length) throw new Error('StreamingCommunity non raggiungibile');
    var candidate = candidates[index];
    return text(candidate + '/it/movies', {cache: 'no-store', credentials: 'include'}, 7000)
      .then(function (response) {
        parsePage(response.body);
        var parsed = new URL(response.url);
        var resolved = parsed.protocol + '//' + parsed.host;
        localStorage.setItem(HOST_KEY, resolved);
        return resolved;
      }).catch(function () { return probe(candidates, index + 1); });
  }

  function ensureHost(force) {
    if (force) hostPromise = null;
    if (hostPromise) return hostPromise;
    hostPromise = registryHost().then(function (remote) {
      return probe(unique([localStorage.getItem(HOST_KEY), remote].concat(SC_FALLBACKS)), 0);
    }).catch(function (error) { hostPromise = null; throw error; });
    return hostPromise;
  }

  function rewriteHost(url, host) {
    try {
      var parsed = new URL(url, host);
      if (/streamingcommunity/i.test(parsed.host)) return host + parsed.pathname + parsed.search;
      return parsed.href;
    } catch (error) { return url; }
  }

  function dataPage(url, retry) {
    return ensureHost(false).then(function (host) {
      var current = rewriteHost(url, host);
      return text(current, {cache: 'no-store', credentials: 'include'}, 10000).then(function (response) {
        return parsePage(response.body);
      });
    }).catch(function (error) {
      if (retry === false) throw error;
      return ensureHost(true).then(function () { return dataPage(url, false); });
    });
  }

  function flatten(values) {
    var out = [];
    (values || []).forEach(function (value) {
      if (Array.isArray(value)) value.forEach(function (nested) { out.push(nested); });
      else out.push(value);
    });
    return out;
  }

  function translation(raw, key) {
    var found = (raw.translations || []).filter(function (entry) {
      return entry.locale === 'it' && entry.key === key;
    })[0];
    return found && found.value || '';
  }

  function imageOf(raw, type, cdn) {
    var images = raw.images || [];
    var selected = images.filter(function (image) { return image.type === type && image.lang === 'it'; })[0] ||
      images.filter(function (image) { return image.type === type; })[0];
    if (!selected) return '';
    return selected.original_url || selected.original_url_field || (cdn + '/images/' + selected.filename);
  }

  function itemFromRaw(raw, host, cdn) {
    var isTv = raw.type === 'tv' || raw.type === 'tvshow';
    var title = translation(raw, 'name') || raw.name || 'Senza titolo';
    var plot = translation(raw, 'plot') || raw.plot || '';
    var poster = imageOf(raw, 'poster', cdn);
    var fanart = imageOf(raw, 'background', cdn) || imageOf(raw, 'cover', cdn);
    var info = {
      mediatype: isTv ? 'tvshow' : 'movie',
      title: title,
      plot: plot,
      year: String(raw.last_air_date || raw.release_date || '').slice(0, 4),
      rating: raw.score || raw.vote_average || 0,
      tmdb_id: raw.tmdb_id || raw.tmdb || '',
      genre: (raw.genres || []).map(function (genre) { return genre.name || genre; }).join(', '),
      thumbnail: poster,
      fanart: fanart
    };
    return {
      channel: 'streamingcommunity',
      action: isTv ? 'episodios' : 'findvideos',
      contentType: isTv ? 'tvshow' : 'movie',
      fulltitle: title,
      title: title,
      plot: plot,
      language: raw.sub_ita ? 'Sub-ITA' : 'ITA',
      thumbnail: poster,
      fanart: fanart,
      infoLabels: info,
      sc_id: raw.id,
      sc_slug: raw.slug || '',
      url: isTv ? host + '/it/titles/' + raw.id + '-' + raw.slug : host + '/it/watch/' + raw.id
    };
  }

  function rowsFromPage(page, prefix) {
    var props = page.props || {}, host = props.app_url || localStorage.getItem(HOST_KEY) || SC_FALLBACKS[0];
    var cdn = props.cdn_url || ('https://cdn.' + new URL(host).host);
    var labels = {trending: 'del momento', latest: 'aggiunti di recente', top10: 'Top 10'};
    return (props.sliders || []).map(function (slider, index) {
      var name = slider.name || slider.label || ('Riga ' + (index + 1));
      return {
        id: 'standalone_' + prefix.toLowerCase() + '_' + name,
        title: prefix + ' ' + (labels[name] || slider.label || name),
        items: flatten(slider.titles).slice(0, 30).map(function (raw) { return itemFromRaw(raw, host, cdn); })
      };
    }).filter(function (row) { return row.items.length; });
  }

  function cachedHome() {
    try { return JSON.parse(localStorage.getItem(HOME_KEY) || 'null'); } catch (error) { return null; }
  }

  function home() {
    return ensureHost(false).then(function (host) {
      return Promise.all([dataPage(host + '/it/movies'), dataPage(host + '/it/tv-shows')]);
    }).then(function (pages) {
      var rows = rowsFromPage(pages[0], 'Film').concat(rowsFromPage(pages[1], 'Serie TV'));
      if (rows.length) localStorage.setItem(HOME_KEY, JSON.stringify({rows: rows, saved_at: Date.now()}));
      return {rows: rows};
    }).catch(function (error) {
      var cached = cachedHome();
      if (cached && cached.rows && cached.rows.length) return {rows: cached.rows, cached: true};
      throw error;
    });
  }

  function search(query) {
    return ensureHost(false).then(function (host) {
      return dataPage(host + '/it/search?q=' + encodeURIComponent(query));
    }).then(function (page) {
      var props = page.props || {}, host = props.app_url || localStorage.getItem(HOST_KEY), cdn = props.cdn_url || ('https://cdn.' + new URL(host).host);
      return {items: flatten(props.titles || []).slice(0, 100).map(function (raw) { return itemFromRaw(raw, host, cdn); })};
    });
  }

  function tmdbType(item) {
    var info = item.infoLabels || {};
    return /tv|serie|episode|season/.test(String(info.mediatype || item.contentType || '').toLowerCase()) ? 'tv' : 'movie';
  }

  function tmdbDetails(item) {
    var info = item.infoLabels || {}, type = tmdbType(item), id = info.tmdb_id || item.tmdb_id;
    var locate = id ? Promise.resolve(id) : json(TMDB + '/search/' + type + '?api_key=' + TMDB_KEY + '&language=it-IT&include_adult=false&query=' + encodeURIComponent(item.fulltitle || item.title || ''))
      .then(function (data) { return data.results && data.results[0] && data.results[0].id; });
    return locate.then(function (tmdbId) {
      if (!tmdbId) return item;
      return json(TMDB + '/' + type + '/' + tmdbId + '?api_key=' + TMDB_KEY + '&language=it-IT&append_to_response=credits').then(function (data) {
        var result = Object.assign({}, item), labels = Object.assign({}, info);
        labels.tmdb_id = tmdbId;
        labels.plot = data.overview || labels.plot || item.plot || '';
        labels.year = String(data.release_date || data.first_air_date || labels.year || '').slice(0, 4);
        labels.rating = data.vote_average || labels.rating || 0;
        labels.runtime = data.runtime || (data.episode_run_time || [])[0] || 0;
        labels.genre = (data.genres || []).map(function (genre) { return genre.name; }).join(', ');
        result.infoLabels = labels;
        result.plot = labels.plot;
        if (data.poster_path) result.thumbnail = 'https://image.tmdb.org/t/p/w500' + data.poster_path;
        if (data.backdrop_path) result.fanart = 'https://image.tmdb.org/t/p/w1280' + data.backdrop_path;
        return result;
      }).catch(function () { return item; });
    });
  }

  function detail(item) {
    return dataPage(item.url).then(function (page) {
      var props = page.props || {}, raw = props.title || {}, host = props.app_url || localStorage.getItem(HOST_KEY), cdn = props.cdn_url || ('https://cdn.' + new URL(host).host);
      var merged = Object.assign({}, item, itemFromRaw(raw, host, cdn));
      if (item.url) merged.url = rewriteHost(item.url, host);
      return tmdbDetails(merged);
    }).catch(function () { return tmdbDetails(item); });
  }

  function episodeImage(episode, fallback, cdn) {
    var image = (episode.images || [])[0];
    if (!image) return fallback || '';
    return image.original_url || image.original_url_field || (cdn + '/images/' + image.filename);
  }

  function episodes(item) {
    return dataPage(item.url).then(function (page) {
      var props = page.props || {}, titleData = props.title || {}, seasons = titleData.seasons || [];
      var host = props.app_url || localStorage.getItem(HOST_KEY), cdn = props.cdn_url || ('https://cdn.' + new URL(host).host), output = [];
      var chain = Promise.resolve();
      seasons.forEach(function (season) {
        chain = chain.then(function () {
          return dataPage(rewriteHost(item.url, host) + '/season-' + season.number).then(function (seasonPage) {
            var list = (((seasonPage.props || {}).loadedSeason || {}).episodes || []);
            list.forEach(function (episode, index) {
              var number = episode.number || index + 1, name = episode.name || ('Episodio ' + number);
              output.push({
                channel: 'streamingcommunity', action: 'findvideos', contentType: 'episode',
                fulltitle: (item.fulltitle || item.title) + ' ' + season.number + 'x' + number,
                title: season.number + 'x' + (number < 10 ? '0' : '') + number + ' - ' + name,
                plot: episode.plot || '', thumbnail: episodeImage(episode, item.thumbnail, cdn), fanart: item.fanart || '',
                season: season.number, episode: number, contentSeason: season.number, contentEpisodeNumber: number,
                contentSerieName: item.fulltitle || item.title,
                infoLabels: {mediatype: 'episode', season: season.number, episode: number, plot: episode.plot || ''},
                url: host + '/it/iframe/' + season.title_id + '?episode_id=' + episode.id
              });
            });
          });
        });
      });
      return chain.then(function () { return {items: output}; });
    });
  }

  function resolveStreamingCommunity(item) {
    var source = item.url || '';
    var iframePromise = /\/it\/iframe\//.test(source) ? ensureHost(false).then(function (host) { return rewriteHost(source, host); }) :
      dataPage(source).then(function (page) {
        var embed = (page.props || {}).embedUrl;
        if (!embed) throw new Error('Iframe non disponibile');
        return rewriteHost(embed, (page.props || {}).app_url || localStorage.getItem(HOST_KEY));
      });
    return iframePromise.then(function (iframeUrl) {
      return text(iframeUrl, {cache: 'no-store', credentials: 'include'}, 10000).then(function (response) {
        var doc = new DOMParser().parseFromString(response.body, 'text/html'), frame = doc.querySelector('iframe');
        var embedUrl = frame && frame.getAttribute('src');
        if (!embedUrl) throw new Error('Player VixCloud non disponibile');
        return text(embedUrl, {cache: 'no-store', credentials: 'include', referrer: iframeUrl, referrerPolicy: 'unsafe-url'}, 10000)
          .then(function (embedResponse) { return {iframeUrl: iframeUrl, embedUrl: embedUrl, body: embedResponse.body}; });
      });
    }).then(function (data) {
      var streamsMatch = data.body.match(/window\.streams\s*=\s*(\[[^;]+\])/i);
      var streams = streamsMatch ? JSON.parse(streamsMatch[1]) : [];
      var active = streams.filter(function (stream) { return stream.active && stream.url; })[0] || streams[0];
      var baseMatch = data.body.match(/window\.masterPlaylist[\s\S]*?url:\s*['"]([^'"]+)/i);
      var base = active && active.url || baseMatch && baseMatch[1];
      var token = (data.body.match(/['"]token['"]\s*:\s*['"]([^'"]+)/i) || [])[1];
      var expires = (data.body.match(/['"]expires['"]\s*:\s*['"]([^'"]+)/i) || [])[1];
      if (!base || !token || !expires) throw new Error('Token VixCloud non disponibile');
      var playlist = new URL(base), embed = new URL(data.embedUrl);
      playlist.searchParams.set('token', token);
      playlist.searchParams.set('expires', expires);
      if (/canPlayFHD\s*=\s*true/i.test(data.body)) playlist.searchParams.set('h', '1');
      ['b', 'scz'].forEach(function (key) { if (embed.searchParams.get(key)) playlist.searchParams.set(key, embed.searchParams.get(key)); });
      return text(playlist.href, {cache: 'no-store', credentials: 'include', referrer: data.embedUrl, referrerPolicy: 'unsafe-url'}, 10000)
        .then(function (response) {
          if (response.body.indexOf('#EXTM3U') !== 0) throw new Error('Playlist HLS non valida');
          return {url: playlist.href, manifest_type: 'hls', headers: {}, drm_type: '', subtitles: [], server: 'streamingcommunityws'};
        });
    });
  }

  function liveLogo(item) {
    if (!item.logo) return item.thumbnail || '';
    return (window.__PRIPPI_LIVE_LOGO_BASE__ || 'assets/tv_logos/') + item.logo;
  }

  function live() {
    var source = window.__PRIPPI_LIVE_CHANNELS__;
    var catalog = source && source.length ? Promise.resolve(source) :
      json('data/live_channels.json', {cache: 'no-store'}, 5000).catch(function () { return []; });
    return catalog.then(function (values) {
      var channels = values.map(function (entry) {
        var item = Object.assign({}, entry);
        item.thumbnail = liveLogo(item);
        item.fanart = item.thumbnail;
        return item;
      });
      return {rows: channels.length ? [{id: 'official_tv', title: 'TV', items: channels}] : []};
    });
  }

  function resolveRai(item) {
    if (!item.video_url) return Promise.reject(new Error('Endpoint Rai non disponibile'));
    return json(item.video_url, {cache: 'no-store', credentials: 'include'}, 10000).then(function (data) {
      if (data.first_item_path) {
        var nested = new URL(data.first_item_path, 'https://www.raiplay.it').href.replace(/\.html\?json/i, '.json');
        return json(nested, {cache: 'no-store', credentials: 'include'}, 10000);
      }
      return data;
    }).then(function (data) {
      var content = data && data.video && data.video.content_url;
      if (!content) throw new Error('Stream Rai non disponibile');
      var separator = content.indexOf('?') >= 0 ? '&' : '?';
      return text(cleanUrl(content) + separator + 'output=56', {cache: 'no-store'}, 10000);
    }).then(function (response) {
      var match = response.body.match(/<url[^>]*type=["']content["'][^>]*>\s*<!\[CDATA\[([^\]]+)/i) ||
        response.body.match(/<url[^>]*type=["']content["'][^>]*>([^<]+)/i);
      var url = cleanUrl(match && match[1]);
      if (!url) throw new Error('Playlist Rai non trovata');
      return {url: url, manifest_type: /\.mpd(\?|$)/i.test(url) ? 'mpd' : 'hls', headers: {}, drm_type: ''};
    });
  }

  function mediasetAuth(force) {
    if (force) mediasetAuthPromise = null;
    if (mediasetAuthPromise && Date.now() - mediasetAuthAt < 30 * 60 * 1000) return mediasetAuthPromise;
    mediasetAuthPromise = json('https://api-ott-prod-fe.mediaset.net/PROD/play/idm/anonymous/login/v2.0', {
      method: 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        client_id: 'f66e2a01-c619-4e53-8e7c-4761449dd8ee',
        platform: 'pc', appName: 'web//mediasetplay-web/1.3.0-h1-8d023f0'
      })
    }, 10000).then(function (data) {
      var auth = data && data.response;
      if (!auth || !auth.beToken || !auth.sid) throw new Error('Sessione Mediaset non disponibile');
      mediasetAuthAt = Date.now();
      return auth;
    }).catch(function (error) { mediasetAuthPromise = null; throw error; });
    return mediasetAuthPromise;
  }

  function resolveMediaset(item, retry) {
    return mediasetAuth(false).then(function (auth) {
      var endpoint = 'https://api-ott-prod-fe.mediaset.net/PROD/play/playback/check/v2.0?sid=' + encodeURIComponent(auth.sid);
      return json(endpoint, {
        method: 'POST', cache: 'no-store', headers: {
          'Content-Type': 'application/json', 'Authorization': 'Bearer ' + auth.beToken
        },
        body: JSON.stringify({
          channelCode: item.callSign, streamType: 'LIVE', delivery: 'Streaming',
          createDevice: 'true', overrideAppName: 'web//mediasetplay-web/1.3.0-h1-8d023f0'
        })
      }, 10000);
    }).then(function (data) {
      var selector = data && data.response && data.response.mediaSelector;
      if (!selector || !selector.url) throw new Error('Canale Mediaset non disponibile');
      return text(selector.url + (selector.url.indexOf('?') >= 0 ? '&' : '?') + queryString(selector), {
        cache: 'no-store'
      }, 10000).then(function (response) { return {selector: selector, body: response.body}; });
    }).then(function (data) {
      var match = data.body.match(/<video[^>]+src=["']([^"']+)/i);
      var url = cleanUrl(match && match[1]);
      if (!url) throw new Error('Playlist Mediaset non trovata');
      var isDash = /dash/i.test(data.selector.formats || '') && /\.mpd(\?|$)/i.test(url);
      return {url: url, manifest_type: isDash ? 'mpd' : 'hls', headers: {}, drm_type: ''};
    }).catch(function (error) {
      if (retry === false) throw error;
      return mediasetAuth(true).then(function () { return resolveMediaset(item, false); });
    });
  }

  function resolveLa7(item) {
    return text(item.url, {cache: 'no-store', credentials: 'include'}, 10000).then(function (response) {
      var hls = response.body.match(/["']?m3u8["']?\s*:\s*["']([^"']+)/i);
      var mp4 = response.body.match(/["']?mp4["']?\s*:\s*["']([^"']+)/i);
      var url = cleanUrl(hls && hls[1] || mp4 && mp4[1]);
      if (!url) throw new Error('La7 offre al dispositivo soltanto una sorgente DRM non ancora compatibile');
      url = url.replace('http://la7-vh.akamaihd.net/i/', 'https://awsvodpkg.iltrovatore.it/local/hls/')
        .replace('csmil/master.m3u8', 'urlset/master.m3u8');
      return {url: url, manifest_type: hls ? 'hls' : 'progressive', headers: {}, drm_type: ''};
    });
  }

  function discoverySession() {
    if (discoverySessionPromise) return discoverySessionPromise;
    var deviceId = 'tizen-' + Date.now().toString(16) + Math.random().toString(16).slice(2);
    discoverySessionPromise = json('https://prod-realmservice.mercury.dnitv.com/realm-config/www.discoveryplus.com%2Fit%2Fepg', {cache: 'no-store'}, 10000)
      .then(function (realm) {
        var domain = 'https://' + realm.domain;
        return json(domain + '/token?deviceId=' + encodeURIComponent(deviceId) + '&realm=dplay&shortlived=true', {cache: 'no-store'}, 10000)
          .then(function (tokenData) {
            var token = tokenData && tokenData.data && tokenData.data.attributes && tokenData.data.attributes.token;
            if (!token) throw new Error('Token Discovery non disponibile');
            return {domain: domain, token: token, deviceId: deviceId};
          });
      }).catch(function (error) { discoverySessionPromise = null; throw error; });
    return discoverySessionPromise;
  }

  function resolveDiscovery(item) {
    return discoverySession().then(function (session) {
      var headers = {
        'Content-Type': 'application/json',
        'x-disco-client': 'WEB:UNKNOWN:dplus_us:2.46.0',
        'x-disco-params': 'realm=dplay,siteLookupKey=dplus_it',
        'Authorization': 'Bearer ' + session.token
      };
      var body = {
        channelId: item.id,
        deviceInfo: {adBlocker: 'true', drmSupported: 'true', hwDecodingCapabilities: [], screen: {width: 1920, height: 1080}, player: {width: 1920, height: 1080}},
        wisteriaProperties: {
          advertiser: {firstPlay: 0, fwIsLat: 0},
          device: {browser: {name: 'chrome', version: '76'}, type: 'desktop'},
          platform: 'desktop', product: 'dplus_emea', sessionId: session.deviceId,
          streamProvider: {suspendBeaconing: 0, hlsVersion: 6, pingConfig: 1}
        }
      };
      return json(session.domain + '/playback/v3/channelPlaybackInfo', {
        method: 'POST', cache: 'no-store', headers: headers, credentials: 'include', body: JSON.stringify(body)
      }, 12000);
    }).then(function (data) {
      var streaming = data && data.data && data.data.attributes && data.data.attributes.streaming || [];
      var source = streaming.filter(function (entry) { return !(entry.protection && entry.protection.drmEnabled); })[0] || streaming[0];
      if (!source || !source.url) throw new Error('Stream Discovery non disponibile');
      if (source.protection && source.protection.drmEnabled) {
        throw new Error('Il canale Discovery richiede Widevine; supporto TV in preparazione');
      }
      return {url: source.url, manifest_type: /\.mpd(\?|$)/i.test(source.url) ? 'mpd' : 'hls', headers: {}, drm_type: ''};
    });
  }

  function resolve(item) {
    if (item.channel === 'streamingcommunity' || /streamingcommunity/i.test(item.url || '')) return resolveStreamingCommunity(item);
    if (item.channel === 'raiplay') return resolveRai(item);
    if (item.channel === 'mediasetplay') return resolveMediaset(item);
    if (item.channel === 'la7') return resolveLa7(item);
    if (item.channel === 'discoveryplus') return resolveDiscovery(item);
    if (/\.(m3u8|mpd|mp4)(\?|$)/i.test(item.url || '')) {
      return Promise.resolve({url: item.url, manifest_type: /\.mpd/i.test(item.url) ? 'mpd' : /\.m3u8/i.test(item.url) ? 'hls' : 'progressive', headers: item.headers || {}, drm_type: ''});
    }
    return Promise.reject(new Error('Sorgente non ancora portata in modalità standalone'));
  }

  function request(path, body) {
    var route = String(path || '').split('?')[0];
    if (route === '/home') return home();
    if (route === '/search') return search(decodeURIComponent((String(path).split('q=')[1] || '').replace(/\+/g, ' ')));
    if (route === '/detail') return detail((body || {}).item || {});
    if (route === '/episodes') return episodes((body || {}).item || {});
    if (route === '/resolve') return resolve((body || {}).item || {});
    if (route === '/live') return live();
    if (route === '/browse-macros') return Promise.resolve({items: []});
    if (route === '/settings') return Promise.resolve({items: [
      {id: 'runtime', label: 'Motore', value: 'Standalone Tizen'},
      {id: 'ota', label: 'Aggiornamenti', value: document.documentElement.getAttribute('data-prippi-version') || 'attivi'}
    ]});
    return Promise.reject(new Error('Funzione standalone non disponibile: ' + route));
  }

  window.PrippiStandalone = {request: request, ensureHost: ensureHost, dataPage: dataPage};
}());
