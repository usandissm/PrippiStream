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
  var HOME_KEY = 'prippi.tizen.standalone.home.v3';
  var SEARCH_CACHE_PREFIX = 'prippi.tizen.search.v3.';
  var MEDIASET_GRAPH_URL = 'https://mediasetplay.api-graph.mediaset.it';
  var MEDIASET_GRAPH_HASH = '0cbec614877306e7f2814d2c16163d510c8fc87f1677bc34f95f4f55dc027dce';
  var LIVE_BACKEND = 'https://test34344.herokuapp.com/filter.php';
  var LIVE_BACKEND_SKY_RESOLVE = 'A1A159';
  var LIVE_XOR_SECRET = 'my_secret_key';
  var NOWTV_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36';
  var NOWTV_ORIGIN = 'https://www.nowtv.it';
  var FREESHOT_ORIGIN = 'https://thisnot.business/';
  var hostPromise = null;
  var registryPromise = null;
  var expandedHomePromise = null;
  var expandedHomeRows = [];
  var expandedHomeDone = false;
  var expandedHomeGeneration = 0;
  var homeBootstrapPromise = null;
  var mediasetAuthPromise = null;
  var mediasetAuthAt = 0;
  var mediasetCatalogPromise = null;
  var discoverySessionPromise = null;
  var daddyDomainPromise = null;

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

  function deadline(promise, milliseconds, message) {
    return new Promise(function (resolve, reject) {
      var settled = false;
      var timer = setTimeout(function () {
        if (!settled) {
          settled = true;
          reject(new Error(message || 'Sorgente lenta'));
        }
      }, milliseconds);
      promise.then(function (value) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      }).catch(function (error) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  function cleanUrl(value) {
    var area = document.createElement('textarea');
    area.innerHTML = String(value || '').replace(/\\\//g, '/');
    return area.value.trim();
  }

  function absoluteUrl(value, base) {
    try { return new URL(value || '', base).href; } catch (error) { return value || ''; }
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
    return providerRegistry().then(function (data) { return data && data.direct && data.direct.streamingcommunity; })
      .catch(function () { return ''; });
  }

  function providerRegistry() {
    if (registryPromise) return registryPromise;
    registryPromise = json('https://raw.githubusercontent.com/usandissm/PrippiStream/main/channels.json?_=' + Date.now(), {cache: 'no-store'}, 6000)
      .catch(function () {
        return {direct: {
          streamingcommunity: SC_FALLBACKS[0], animeunity: 'https://www.animeunity.so',
          hd4me: 'https://hd4me.net', streamingita: 'https://streamingita.homes'
        }, findhost: {cineblog01: 'https://cb01official.uno'}};
      });
    return registryPromise;
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

  function mapLimit(values, limit, worker) {
    return new Promise(function (resolve) {
      var results = new Array(values.length), next = 0, active = 0, completed = 0;
      if (!values.length) { resolve(results); return; }
      function schedule() {
        while (active < limit && next < values.length) {
          (function (index) {
            active += 1;
            Promise.resolve().then(function () { return worker(values[index], index); })
              .catch(function () { return null; }).then(function (value) {
                results[index] = value;
                active -= 1;
                completed += 1;
                if (completed === values.length) resolve(results);
                else schedule();
              });
          }(next));
          next += 1;
        }
      }
      schedule();
    });
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

  function rowsFromPage(page, suffix) {
    var props = page.props || {}, host = props.app_url || localStorage.getItem(HOST_KEY) || SC_FALLBACKS[0];
    var cdn = props.cdn_url || ('https://cdn.' + new URL(host).host);
    return (props.sliders || []).map(function (slider, index) {
      var name = slider.name || slider.label || ('Riga ' + (index + 1));
      return {
        id: 'sc_' + String(name + suffix).toLowerCase().replace(/[^a-z0-9]+/g, '_'),
        title: name + (suffix || ''),
        items: flatten(slider.titles).slice(0, 30).map(function (raw) { return itemFromRaw(raw, host, cdn); })
      };
    }).filter(function (row) { return row.items.length; });
  }

  function uniqueRows(rows) {
    var seen = {}, output = [];
    (rows || []).forEach(function (row) {
      var key = String(row.title || row.id || '').toLowerCase();
      if (!key || seen[key] || !(row.items || []).length) return;
      seen[key] = true;
      output.push(row);
    });
    return output;
  }

  function archiveRows(host, homepage, existingCount, onProgress) {
    var curated = [
      ['I Pi\u00f9 Votati \u2014 Film', '/it/archive?sort=score&type=movie'],
      ['I Pi\u00f9 Votati \u2014 Serie TV', '/it/archive?sort=score&type=tv'],
      ['I Pi\u00f9 Visti \u2014 Film', '/it/archive?sort=views&type=movie'],
      ['I Pi\u00f9 Visti', '/it/archive?sort=views'],
      ['Serie TV \u2014 Aggiornate di Recente', '/it/archive?sort=last_air_date&type=tv'],
      ['Film \u2014 Aggiunti di Recente', '/it/archive?sort=created_at&type=movie']
    ];
    var genres = (((homepage || {}).props || {}).genres || []).filter(function (genre) {
      return genre && genre.id && genre.name;
    }).map(function (genre) {
      return [genre.name, '/it/archive?genre[]=' + encodeURIComponent(genre.id)];
    });
    var entries = curated.concat(genres), target = Math.max(0, 30 - existingCount);
    if (!target) return Promise.resolve([]);
    return new Promise(function (resolve) {
      var next = 0, active = 0, finished = false, collected = [], seen = {};
      function snapshot() {
        return collected.slice().sort(function (a, b) { return a.index - b.index; }).map(function (value) { return value.row; });
      }
      function completeIfReady() {
        if (finished) return true;
        if (collected.length >= target || (next >= entries.length && active === 0)) {
          finished = true;
          resolve(snapshot().slice(0, target));
          return true;
        }
        return false;
      }
      function pump() {
        if (completeIfReady()) return;
        while (!finished && active < 4 && next < entries.length && collected.length < target) {
          (function (entry, index) {
            active += 1;
            deadline(dataPage(host + entry[1]), 8500, 'Riga lenta').then(function (page) {
              var props = page.props || {}, titles = props.titles || [], cdn = props.cdn_url || ('https://cdn.' + new URL(host).host);
              if (!Array.isArray(titles)) titles = titles.data || [];
              var items = flatten(titles).slice(0, 20).map(function (raw) { return itemFromRaw(raw, host, cdn); });
              var key = String(entry[0] || '').toLowerCase();
              if (items.length && !seen[key] && collected.length < target) {
                seen[key] = true;
                collected.push({index: index, row: {id: 'sc_archive_' + index, title: entry[0], items: items}});
                if (onProgress) onProgress(snapshot());
              }
            }).catch(function () {}).then(function () {
              active -= 1;
              pump();
            });
          })(entries[next], next);
          next += 1;
        }
        completeIfReady();
      }
      pump();
    });
  }

  function tmdbItem(raw, forcedType) {
    var type = forcedType || raw.media_type || (raw.first_air_date ? 'tv' : 'movie');
    if (type !== 'movie' && type !== 'tv') return null;
    var name = raw.title || raw.name || 'Senza titolo';
    var year = String(raw.release_date || raw.first_air_date || '').slice(0, 4);
    return {
      channel: 'tmdb',
      tmdbOnly: true,
      action: type === 'tv' ? 'episodios' : 'findvideos',
      contentType: type === 'tv' ? 'tvshow' : 'movie',
      fulltitle: name,
      title: name,
      plot: raw.overview || '',
      thumbnail: raw.poster_path ? 'https://image.tmdb.org/t/p/w500' + raw.poster_path : '',
      fanart: raw.backdrop_path ? 'https://image.tmdb.org/t/p/w1280' + raw.backdrop_path : '',
      infoLabels: {
        mediatype: type === 'tv' ? 'tvshow' : 'movie',
        title: name,
        plot: raw.overview || '',
        year: year,
        rating: raw.vote_average || 0,
        tmdb_id: raw.id || ''
      }
    };
  }

  function tmdbList(path, type) {
    return json(TMDB + path + (path.indexOf('?') >= 0 ? '&' : '?') +
      'api_key=' + TMDB_KEY + '&language=it-IT&include_adult=false', {cache: 'no-store'}, 9000)
      .then(function (data) {
        return (data.results || []).map(function (raw) { return tmdbItem(raw, type); }).filter(Boolean).slice(0, 24);
      });
  }

  var SEARCH_STOPWORDS = {
    il: 1, lo: 1, la: 1, i: 1, gli: 1, le: 1, un: 1, uno: 1, una: 1,
    di: 1, del: 1, dello: 1, della: 1, dei: 1, degli: 1, delle: 1,
    a: 1, ad: 1, al: 1, alla: 1, da: 1, dal: 1, in: 1, nel: 1,
    con: 1, su: 1, per: 1, tra: 1, fra: 1, e: 1, ed: 1, o: 1,
    the: 1, an: 1, of: 1, and: 1, or: 1, to: 1, on: 1, at: 1
  };

  function cleanTitle(value) {
    return String(value || '').replace(/<[^>]+>/g, '').replace(/\[[^\]]+\]/g, '')
      .toLowerCase().replace(/[^a-z0-9\u00c0-\u024f ]/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function titleSignature(value) {
    return cleanTitle(value).split(' ').filter(function (word) { return word && !SEARCH_STOPWORDS[word]; }).join(' ');
  }

  function providerItem(source, values) {
    var type = values.type === 'tv' || values.type === 'anime' ? 'tv' : 'movie';
    var result = {
      channel: source,
      source: source,
      providerOnly: true,
      tmdbOnly: true,
      action: type === 'tv' ? 'episodios' : 'findvideos',
      contentType: type === 'tv' ? 'tvshow' : 'movie',
      searchType: values.type === 'anime' ? 'anime' : (type === 'tv' ? 'serie' : 'film'),
      fulltitle: values.title || 'Senza titolo',
      title: values.title || 'Senza titolo',
      plot: values.plot || '',
      thumbnail: values.thumbnail || '',
      fanart: values.fanart || values.thumbnail || '',
      providerUrl: values.url || '',
      language: values.language || '',
      infoLabels: {
        mediatype: type === 'tv' ? 'tvshow' : 'movie', title: values.title || '',
        plot: values.plot || '', year: values.year || '', rating: values.rating || 0,
        tmdb_id: values.tmdbId || ''
      }
    };
    return result;
  }

  function exactEnough(item, query, anime) {
    var q = cleanTitle(query), candidate = cleanTitle(item.fulltitle || item.title);
    if (!q || !candidate) return false;
    if (candidate === q || candidate.indexOf(q + ' ') === 0 || q.indexOf(candidate + ' ') === 0) return true;
    if (anime && (' ' + candidate + ' ').indexOf(' ' + q + ' ') >= 0) return true;
    var qs = titleSignature(q), cs = titleSignature(candidate);
    return qs.split(' ').length >= 2 && (cs === qs || cs.indexOf(qs + ' ') === 0 || qs.indexOf(cs + ' ') === 0);
  }

  function searchHd4me(query, registry) {
    var host = (registry.direct || {}).hd4me || 'https://hd4me.net';
    var url = host.replace(/\/$/, '') + '/wp-content/themes/mytheme/cache/posts_data.json';
    return json(url, {cache: 'force-cache'}, 8500).then(function (records) {
      var q = cleanTitle(query), qsig = titleSignature(query).split(' '), output = [];
      (records || []).some(function (record) {
        var italian = record.twy || '', original = record.to || '';
        var matches = cleanTitle(italian).indexOf(q) >= 0 || cleanTitle(original).indexOf(q) >= 0;
        if (!matches && qsig.length >= 2) {
          var sig = titleSignature(italian || original);
          matches = sig.indexOf(qsig.join(' ')) >= 0;
        }
        if (!matches || !record.pid) return false;
        var poster = record.pa ? 'https://image.tmdb.org/t/p/w500/' + String(record.pa).replace(/^\//, '').replace(/\.jpg$/i, '') + '.jpg' : '';
        output.push(providerItem('hd4me', {title: italian || original, type: 'movie', year: record.y || '',
          rating: record.rt || 0, thumbnail: poster, url: url.replace(/posts_data\.json$/, 'posts/' + record.pid + '.json')}));
        return output.length >= 40;
      });
      return output;
    });
  }

  function searchAnimeUnity(query, registry, homeMode) {
    var host = (registry.direct || {}).animeunity || 'https://www.animeunity.so';
    return text(host.replace(/\/$/, '') + '/archivio', {cache: 'no-store', credentials: 'include'}, 8500).then(function (response) {
      var doc = new DOMParser().parseFromString(response.body, 'text/html');
      var tokenNode = doc.querySelector('meta[name="csrf-token"]');
      var token = tokenNode && tokenNode.getAttribute('content');
      if (!token) throw new Error('AnimeUnity CSRF non disponibile');
      var payload = {offset: 0};
      if (query) payload.title = query;
      if (homeMode) payload.order = 'Popolarit\u00e0';
      return json(host.replace(/\/$/, '') + '/archivio/get-animes', {
        method: 'POST', credentials: 'include', cache: 'no-store',
        headers: {'Content-Type': 'application/json;charset=UTF-8', 'X-CSRF-TOKEN': token,
          'X-Requested-With': 'XMLHttpRequest', 'Referer': host + '/archivio'},
        body: JSON.stringify(payload)
      }, 9000);
    }).then(function (data) {
      return (data.records || []).map(function (record) {
        var name = record.title || record.title_eng || '';
        name = name.replace(/\s*\([^)]*ita[^)]*\)\s*/ig, ' ').trim();
        return providerItem('animeunity', {title: name, type: 'anime', year: record.date || '',
          rating: record.score || 0, thumbnail: record.imageurl || '', plot: record.plot || '',
          language: /\(ita\)/i.test(record.title || '') ? 'ITA' : 'Sub-ITA',
          url: host.replace(/\/$/, '') + '/anime/' + record.id + '-' + record.slug});
      }).filter(function (item) { return item.fulltitle && (!query || exactEnough(item, query, true)); }).slice(0, 30);
    });
  }

  function resolvedProviderHost(registry, name) {
    var direct = (registry.direct || {})[name];
    if (direct) return Promise.resolve(direct.replace(/\/$/, ''));
    var finder = (registry.findhost || {})[name];
    if (!finder) return Promise.reject(new Error('Host ' + name + ' non configurato'));
    return text(finder, {cache: 'no-store'}, 6500).then(function (response) {
      return new URL(response.url || finder).origin;
    });
  }

  function parseHtmlSearch(source, host, html, query) {
    var doc = new DOMParser().parseFromString(html, 'text/html'), output = [];
    if (source === 'streamingita') {
      Array.prototype.forEach.call(doc.querySelectorAll('.result-item'), function (node) {
        var link = node.querySelector('a[href]'), image = node.querySelector('img'), year = node.querySelector('.year');
        var titleNode = node.querySelector('.title a, .details .title, h3, h2');
        var href = link && absoluteUrl(link.getAttribute('href'), host);
        var item = providerItem(source, {title: titleNode && titleNode.textContent || link && link.textContent,
          type: /tv|serie/i.test(node.className + ' ' + (href || '')) ? 'tv' : 'movie',
          year: year && year.textContent.trim(), thumbnail: image && absoluteUrl(image.getAttribute('data-src') || image.getAttribute('src'), host),
          plot: (node.querySelector('.contenido p') || {}).textContent || '', url: href});
        if (exactEnough(item, query, false)) output.push(item);
      });
    } else {
      Array.prototype.forEach.call(doc.querySelectorAll('article.hentry, article.item, .post'), function (node) {
        var link = node.querySelector('h2 a[href], h3 a[href], .card-image + * a[href], a[href]');
        var image = node.querySelector('img'), href = link && absoluteUrl(link.getAttribute('href'), host) || '';
        var item = providerItem(source, {title: link && link.textContent.trim() || image && image.alt,
          type: /serietv|serie-tv|tvshow/i.test(href + ' ' + node.className) ? 'tv' : 'movie',
          thumbnail: image && absoluteUrl(image.getAttribute('data-src') || image.getAttribute('src'), host), url: href});
        if (exactEnough(item, query, false)) output.push(item);
      });
    }
    return output.slice(0, 40);
  }

  function searchHtmlProvider(name, query, registry) {
    return resolvedProviderHost(registry, name).then(function (host) {
      var url = name === 'cineblog01' ? host + '/search/' + encodeURIComponent(query).replace(/%20/g, '+') :
        host + '/?s=' + encodeURIComponent(query);
      return text(url, {cache: 'no-store', credentials: 'include'}, 8000).then(function (response) {
        return parseHtmlSearch(name, host, response.body, query);
      });
    });
  }

  function raiUrl(value) {
    if (!value) return '';
    if (/^https?:/i.test(value)) return value;
    if (value.indexOf('//') === 0) return 'https:' + value;
    return 'https://www.raiplay.it' + (value.charAt(0) === '/' ? value : '/' + value);
  }

  function raiItem(raw, forcedType) {
    var type = forcedType || (/programma|serie/i.test(raw.tipo || raw.type || '') ? 'tv' : 'movie');
    var images = raw.images || {}, title = raw.titolo || raw.name || raw.episode_title || 'RaiPlay';
    var poster = raiUrl(raw.immagine || images.portrait_logo || images.portrait43 || images.portrait || images.landscape);
    var fanart = raiUrl(images.landscape_logo || images.landscape || raw.immagine);
    var item = providerItem('raiplay', {title: title, type: type, thumbnail: poster, fanart: fanart,
      plot: raw.description || raw.vanity || '', url: raiUrl(raw.weblink || raw.url || raw.path_id)});
    item.providerOnly = false;
    item.tmdbOnly = false;
    item.video_url = raiUrl(raw.path_id || raw.video_url);
    item.info_url = raiUrl(raw.info_url);
    item.action = raw.episode || /video item/i.test(raw.type || '') ? 'findvideos' : 'episodios';
    if (raw.season) item.season = Number(raw.season) || 1;
    if (raw.episode) item.episode = Number(raw.episode) || 1;
    return item;
  }

  function raiSearch(query) {
    return json('https://www.raiplay.it/atomatic/raiplay-search-service/api/v1/msearch', {
      method: 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({templateIn: '6470a982e4e0301afe1f81f1', templateOut: '6516ac5d40da6c377b151642',
        params: {param: query, from: 0, sort: 'relevance', size: 40, additionalSize: 24,
          onlyVideoQuery: false, onlyProgramsQuery: false}})
    }, 9000).then(function (data) {
      var cards = (((data || {}).agg || {}).titoli || {}).cards || [];
      return cards.map(function (raw) { return raiItem(raw, /programma/i.test(raw.tipo || '') ? 'tv' : 'movie'); })
        .filter(function (item) { return exactEnough(item, query, true); });
    });
  }

  function raiHomeRows() {
    var pages = [
      ['RaiPlay Film', 'movie', 'https://www.raiplay.it/tipologia/film/index.json'],
      ['RaiPlay Serie', 'tv', 'https://www.raiplay.it/tipologia/serieitaliane/index.json'],
      ['RaiPlay Documentari', 'tv', 'https://www.raiplay.it/tipologia/documentari/index.json']
    ];
    return Promise.all(pages.map(function (entry) {
      return json(entry[2], {cache: 'no-store'}, 9000).then(function (data) {
        return (data.contents || []).filter(function (block) {
          return /Slider Block/.test(block.type || '') && !/Generi/.test(block.type || '') && (block.contents || []).length;
        }).slice(0, 3).map(function (block, index) {
          return {id: 'rai_' + entry[1] + '_' + index, title: entry[0] + ' - ' + (block.name || 'In evidenza'),
            items: (block.contents || []).slice(0, 20).map(function (raw) { return raiItem(raw, entry[1]); })};
        });
      }).catch(function () { return []; });
    })).then(flatten);
  }

  function mediasetThumb(raw, prefix) {
    var values = raw.thumbnails || {}, best = '';
    Object.keys(values).some(function (key) {
      if (key.indexOf(prefix) >= 0 && values[key] && values[key].url) { best = values[key].url.replace('.jpg', '@3.jpg'); return true; }
      return false;
    });
    return best;
  }

  function mediasetItem(raw, forcedType) {
    var series = !!(raw.seriesTitle || raw.seriesTvSeasons), type = forcedType || (series ? 'tv' : 'movie');
    var title = raw['mediasetprogram$brandTitle'] || raw.title || 'Mediaset Infinity';
    var item = providerItem('mediasetplay', {title: title, type: type,
      thumbnail: mediasetThumb(raw, 'image_vertical') || mediasetThumb(raw, 'image_keyframe'),
      fanart: mediasetThumb(raw, 'image_header_poster') || mediasetThumb(raw, 'image_keyframe'),
      plot: raw.longDescription || raw.description || raw['mediasettvseason$brandDescription'] || '',
      url: String(raw['mediasettvseason$pageUrl'] || raw['mediasetprogram$videoPageUrl'] || raw['mediasetprogram$pageUrl'] || '').replace(/^\/\//, 'https://')});
    item.providerOnly = false;
    item.tmdbOnly = false;
    item.video_id = series ? '' : raw.guid || '';
    item.seriesid = raw.seriesTvSeasons || raw.id || '';
    item.action = series ? 'episodios' : 'findvideos';
    item.msp_type = raw.programType || raw.programtype || raw.type || '';
    return item;
  }

  function mediasetFeed(args, forcedType) {
    return mediasetAuth(false).then(function (auth) {
      var values = Object.assign({}, args, {context: 'platform\u2248web', sid: auth.sid, sessionId: auth.sid,
        hitsPerPage: 30, property: args.query ? 'search' : 'play', tenant: 'play-prod-v2', page: 1,
        deviceId: '017ac511182d008322c989f3aac803083002507b00bd0'});
      var endpoint = 'https://api-ott-prod-fe.mediaset.net/PROD/play/reco/anonymous/v2.0?' + queryString(values);
      return json(endpoint, {cache: 'no-store', headers: {'Authorization': 'Bearer ' + auth.beToken}}, 10000);
    }).then(function (data) {
      var response = data.response || data, entries = response.entries || [];
      if (!entries.length) (response.blocks || []).forEach(function (block) { entries = entries.concat(block.items || []); });
      return entries.filter(function (raw) { return (raw['mediasetprogram$channelsRights'] || ['MediasetPlay_ANY']).indexOf('MediasetPlay_ANY') >= 0; })
        .map(function (raw) { return mediasetItem(raw, forcedType); });
    });
  }

  function mediasetGraphItems(data) {
    var output = [], seen = {};
    function walk(value) {
      if (!value) return;
      if (Array.isArray(value)) { value.forEach(walk); return; }
      if (typeof value !== 'object') return;
      if ((value.__typename === 'SeriesItem' || value.__typename === 'VideoItem') && value.guid && !seen[value.guid]) {
        seen[value.guid] = true;
        output.push(value);
      }
      Object.keys(value).forEach(function (key) { walk(value[key]); });
    }
    walk(data);
    return output;
  }

  function mediasetGraphImage(card, imageType, width, height) {
    var image = (card.cardImages || []).filter(function (value) {
      return value.type === imageType || value.sourceType === imageType;
    })[0];
    if (!image || !image.engine || !image.id) return '';
    var url = 'https://img-prod-api2.mediasetplay.mediaset.it/api/images/' + image.engine + '/v5/ita/' +
      image.id + '/' + (image.sourceType || imageType) + '/' + width + '/' + height;
    return image.r ? url + '?r=' + encodeURIComponent(image.r) : url;
  }

  function mediasetGraphItem(card) {
    var title = card.cardTitle || '', isSeries = card.__typename === 'SeriesItem';
    if (!title || (!isSeries && String(card.editorialType || '').toLowerCase() !== 'movie')) return null;
    var link = card.cardLink && card.cardLink.value || card.url || 'https://mediasetinfinity.mediaset.it/';
    var item = providerItem('mediasetplay', {title: title, type: isSeries ? 'tv' : 'movie',
      thumbnail: mediasetGraphImage(card, 'image_vertical', 400, 600),
      fanart: mediasetGraphImage(card, 'image_header_poster', 1200, 630),
      plot: card.cardText || card.description || '', url: link});
    item.providerOnly = false;
    item.tmdbOnly = false;
    item.video_id = isSeries ? '' : card.guid;
    item.seriesid = '';
    item.action = isSeries ? 'episodios' : 'findvideos';
    item.msp_type = isSeries ? 'series' : 'movie';
    if (isSeries) {
      item.seriesid = (card.seasons || []).slice().reverse().map(function (season, index) {
        var seasonLink = season.cardLink && season.cardLink.value || link;
        var match = String(seasonLink).match(/(?:stagione|season)[-_]?(\d+)/i);
        var number = match ? Number(match[1]) : index + 1;
        return {id: season.guid || '', title: season.seasonTitle || ('Stagione ' + number), url: seasonLink, number: number};
      }).filter(function (season) { return season.id; }).sort(function (a, b) { return a.number - b.number; });
    }
    return item;
  }

  function mediasetGraphSearch(query) {
    var variables = {after: null, first: 24, property: 'search', query: query, uxReference: 'main', variant: null};
    var extensions = {persistedQuery: {version: 1, sha256Hash: MEDIASET_GRAPH_HASH}};
    var endpoint = MEDIASET_GRAPH_URL + '?extensions=' + encodeURIComponent(JSON.stringify(extensions)) +
      '&variables=' + encodeURIComponent(JSON.stringify(variables));
    return json(endpoint, {cache: 'no-store', referrer: 'https://mediasetinfinity.mediaset.it/', headers: {
      'x-m-platform': 'WEB', 'x-m-property': 'MPLAY', 'x-m-app-version': '1.3.0-h1',
      'Accept': 'application/json'
    }}, 10000).then(function (data) {
      return mediasetGraphItems(data).map(mediasetGraphItem).filter(function (item) {
        return item && exactEnough(item, query, true);
      });
    });
  }

  function mediasetSearch(query) {
    return mediasetGraphSearch(query).then(function (items) {
      if (items.length) return items;
      return mediasetFeed({uxReference: 'main', params: 'channel\u2248', query: query}, '');
    })
      .then(function (items) {
        var matches = items.filter(function (item) {
        return item.msp_type !== 'episode' && item.msp_type !== 'extra' && exactEnough(item, query, true);
        });
        if (matches.length) return matches;
        return mediasetCatalog().then(function (catalog) {
          return catalog.filter(function (item) { return exactEnough(item, query, true); }).slice(0, 40);
        });
      }).catch(function () {
        return mediasetCatalog().then(function (items) {
          return items.filter(function (item) { return exactEnough(item, query, true); }).slice(0, 40);
        });
      });
  }

  function mediasetHtmlItem(link, forcedType) {
    var image = link.querySelector('img[alt], img[title]');
    if (!image) return null;
    var href = absoluteUrl(link.getAttribute('href'), 'https://mediasetinfinity.mediaset.it');
    var title = image.getAttribute('alt') || image.getAttribute('title') || '';
    var thumbnail = cleanUrl(image.getAttribute('src') || '');
    var idMatch = href.match(/_(SE\d+|Y\d+)(?:[?#]|$)/i) || thumbnail.match(/\/(SE\d+|Y\d+)\/image_/i);
    var contentId = idMatch && idMatch[1] || '';
    var type = forcedType || (/^SE/i.test(contentId) ? 'tv' : 'movie');
    if (!title || !href) return null;
    var description = '';
    Array.prototype.some.call(link.querySelectorAll('p'), function (node) {
      var value = String(node.textContent || '').trim();
      if (value && !/^(La tua lista|Aggiungi|Rimuovi)$/i.test(value)) { description = value; return true; }
      return false;
    });
    var item = providerItem('mediasetplay', {title: title, type: type, thumbnail: thumbnail,
      fanart: thumbnail, plot: description, url: href});
    item.providerOnly = false;
    item.tmdbOnly = false;
    item.video_id = type === 'movie' ? contentId : '';
    item.seriesid = type === 'tv' ? contentId : '';
    item.action = type === 'tv' ? 'episodios' : 'findvideos';
    item.msp_type = type === 'tv' ? 'series' : 'movie';
    return item;
  }

  function mediasetHtmlPage(url, type) {
    return text(url, {cache: 'no-store', headers: {'Accept': 'text/html'}}, 12000).then(function (response) {
      var doc = new DOMParser().parseFromString(response.body, 'text/html'), output = [], seen = {};
      Array.prototype.forEach.call(doc.querySelectorAll('a[data-testid="poster-card-link"][href]'), function (link) {
        var item = mediasetHtmlItem(link, type);
        var key = item && (item.seriesid || item.video_id || item.url);
        if (item && key && !seen[key]) { seen[key] = true; output.push(item); }
      });
      return output;
    });
  }

  function mediasetCatalog() {
    if (mediasetCatalogPromise) return mediasetCatalogPromise;
    var pages = [
      ['movie', 'https://mediasetinfinity.mediaset.it/browse/tutti-i-film_e60d9d8cfa6f5470017688117'],
      ['tv', 'https://mediasetinfinity.mediaset.it/browse/tutte-le-serie_e60dc958ba0e8450017067ac7'],
      ['tv', 'https://mediasetinfinity.mediaset.it/browse/tutti-i-programmi-tv_e61bcd4121de1c40016175e41']
    ];
    mediasetCatalogPromise = Promise.all(pages.map(function (page) {
      return mediasetHtmlPage(page[1], page[0]).catch(function () { return []; });
    })).then(function (groups) { return flatten(groups); }).catch(function (error) {
      mediasetCatalogPromise = null;
      throw error;
    });
    return mediasetCatalogPromise;
  }

  function mediasetHtmlRows() {
    return mediasetCatalog().then(function (items) {
      var films = items.filter(function (item) { return item.contentType === 'movie'; });
      var series = items.filter(function (item) { return item.contentType === 'tvshow' && /\/fiction|\/serie/i.test(item.url || ''); });
      var programs = items.filter(function (item) { return item.contentType === 'tvshow' && series.indexOf(item) < 0; });
      return [
        films.length ? {id: 'mediaset_html_film', title: 'Mediaset \u2014 Film', items: films.slice(0, 24)} : null,
        series.length ? {id: 'mediaset_html_serie', title: 'Mediaset \u2014 Serie TV', items: series.slice(0, 24)} : null,
        programs.length ? {id: 'mediaset_html_programmi', title: 'Mediaset \u2014 Programmi TV', items: programs.slice(0, 24)} : null
      ].filter(Boolean);
    });
  }

  function mediasetHomeRows() {
    var rows = [
      ['Mediaset \u2014 Film pi\u00f9 visti', 'movie', {uxReference: 'filmPiuVisti24H'}],
      ['Mediaset \u2014 Ultimi film', 'movie', {uxReference: 'filmUltimiArrivi'}],
      ['Mediaset \u2014 Serie del momento', 'tv', {uxReference: 'fictionSerieTvDelMomento'}],
      ['Mediaset \u2014 Serie pi\u00f9 viste', 'tv', {uxReference: 'serieTvPiuViste24H'}],
      ['Mediaset \u2014 Programmi TV', 'tv', {uxReference: 'stagioniPrimaSerata'}]
    ];
    return Promise.all(rows.map(function (row, index) {
      return mediasetFeed(row[2], row[1]).then(function (items) {
        return items.length ? {id: 'mediaset_' + index, title: row[0], items: items.slice(0, 20)} : null;
      }).catch(function () { return null; });
    })).then(function (values) {
      var available = values.filter(Boolean);
      return available.length ? available : mediasetHtmlRows();
    }).catch(function () { return mediasetHtmlRows(); });
  }

  function la7Search(query) {
    return text('https://www.la7.it/ricerca?query=' + encodeURIComponent(query) + '&page=0', {cache: 'no-store'}, 9000)
      .then(function (response) {
        var doc = new DOMParser().parseFromString(response.body, 'text/html'), output = [], seen = {}, grouped = {};
        Array.prototype.forEach.call(doc.querySelectorAll('.view-content a[href]'), function (link) {
          var holder = link.querySelector('.holder-bg'), titleNode = link.querySelector('.title');
          if (!holder || !titleNode) return;
          var href = absoluteUrl(link.getAttribute('href'), 'https://www.la7.it'), style = holder.getAttribute('data-background-image') || holder.style.backgroundImage || '';
          var thumb = style.replace(/^.*url\(['"]?/, '').replace(/['"]?\).*$/, '');
          var path = new URL(href).pathname.split('?')[0].replace(/^\/+|\/+$/g, '').split('/');
          var isProgramVideo = path.length >= 3 && ['video', 'rivedila7', 'articolo'].indexOf(path[1]) >= 0 &&
            ['la7-cinema-tutti-i-film', 'film'].indexOf(path[0]) < 0;
          var itemTitle = titleNode.textContent.trim(), type = 'movie';
          if (isProgramVideo) {
            if (grouped[path[0]]) return;
            grouped[path[0]] = true;
            href = 'https://www.la7.it/' + path[0];
            itemTitle = path[0].split('-').map(function (word) { return word.charAt(0).toUpperCase() + word.slice(1); }).join(' ');
            type = 'tv';
          }
          var item = providerItem('la7', {title: itemTitle, type: type, thumbnail: thumb, fanart: thumb, url: href});
          item.providerOnly = false; item.tmdbOnly = false;
          if (!seen[href] && exactEnough(item, query, true)) { seen[href] = true; output.push(item); }
        });
        return output.slice(0, 40);
      });
  }

  function la7SmartItem(raw) {
    var item = providerItem('la7', {title: raw.titolo || raw.title || raw.properti || 'La7', type: 'tv',
      thumbnail: raw.img_verticale || raw.smart_tv_locandina || raw.img || raw.immagine_vetrina || '',
      fanart: raw.img || raw.smart_tv_anteprima || raw.immagine_vetrina || raw.img_verticale || '',
      plot: raw.occhiello || raw.descrizione || raw.testo || ''});
    item.providerOnly = false;
    item.tmdbOnly = false;
    item.la7Lookup = true;
    return item;
  }

  function la7HomeRows() {
    return json('https://www.la7.it/sites/default/files/la7_app_home_smarttv.json', {cache: 'no-store'}, 9000)
      .then(function (data) {
        var definitions = [
          ['La7 - Da non perdere', data.da_non_perdere],
          ['La7 - I pi\u00f9 visti', data.topfive],
          ['La7 - Rivedi', data.rivedi]
        ];
        return definitions.map(function (entry, index) {
          var values = Array.isArray(entry[1]) ? flatten(entry[1]) : [];
          var items = values.filter(function (value) { return value && typeof value === 'object' && (value.titolo || value.title || value.properti); })
            .slice(0, 20).map(la7SmartItem);
          return items.length ? {id: 'la7_' + index, title: entry[0], items: items} : null;
        }).filter(Boolean);
      }).catch(function () { return []; });
  }

  function officialHomeRows() {
    return Promise.all([raiHomeRows(), mediasetHomeRows(), la7HomeRows()]).then(function (groups) { return flatten(groups); });
  }

  function sourcePriority(item) {
    var priorities = {streamingcommunity: 0, sc: 0, hd4me: 1, cineblog01: 2, streamingita: 3,
      animeunity: 4, tmdb: 9};
    var value = priorities[item.source || item.channel];
    return value === undefined ? 5 : value;
  }

  function dedupeSearch(items, query) {
    var slots = {}, output = [];
    (items || []).filter(function (item) { return item && item.thumbnail && exactEnough(item, query, item.searchType === 'anime'); })
      .sort(function (a, b) {
        var q = cleanTitle(query), at = cleanTitle(a.fulltitle), bt = cleanTitle(b.fulltitle);
        function score(value) { return value === q ? 0 : value.indexOf(q) === 0 ? 1 : value.indexOf(q) >= 0 ? 2 : 3; }
        return score(at) - score(bt) || sourcePriority(a) - sourcePriority(b) || at.localeCompare(bt);
      }).forEach(function (item) {
        var info = item.infoLabels || {}, normalized = titleSignature(item.fulltitle || item.title);
        var official = item.source === 'raiplay' || item.source === 'mediasetplay' || item.source === 'la7';
        if (official && (' ' + cleanTitle(item.fulltitle || item.title) + ' ').indexOf(' ' + cleanTitle(query) + ' ') >= 0) {
          normalized = titleSignature(query) || cleanTitle(query);
        }
        var key = info.tmdb_id ? 'tmdb:' + info.tmdb_id : 'title:' + normalized;
        if (!key || key === 'title:') return;
        if (slots[key] === undefined) { slots[key] = output.length; output.push(item); return; }
        var index = slots[key], previous = output[index];
        if (item.searchType === 'anime' && previous.searchType !== 'anime') output[index] = item;
        else if (sourcePriority(item) < sourcePriority(previous)) output[index] = item;
      });
    return output.slice(0, 100);
  }

  function tmdbHome() {
    return Promise.all([
      tmdbList('/trending/all/week?', ''),
      tmdbList('/movie/popular?', 'movie'),
      tmdbList('/tv/popular?', 'tv'),
      tmdbList('/movie/top_rated?', 'movie')
    ]).then(function (lists) {
      var names = ['In evidenza questa settimana', 'Film popolari', 'Serie TV popolari', 'Film più apprezzati'];
      var rows = lists.map(function (items, index) { return {id: 'tmdb_' + index, title: names[index], items: items}; })
        .filter(function (row) { return row.items.length; });
      if (!rows.length) throw new Error('Catalogo temporaneamente non disponibile');
      saveStandaloneHome(rows, true);
      return {rows: rows, fallback: true};
    });
  }

  function saveStandaloneHome(rows, fallback) {
    try {
      localStorage.setItem(HOME_KEY, JSON.stringify({rows: (rows || []).slice(0, 30), saved_at: Date.now(), fallback: !!fallback}));
    } catch (error) {}
  }

  function cachedHome() {
    try { return JSON.parse(localStorage.getItem(HOME_KEY) || 'null'); } catch (error) { return null; }
  }

  function cachedSearch(query) {
    try {
      var value = JSON.parse(localStorage.getItem(SEARCH_CACHE_PREFIX + encodeURIComponent(cleanTitle(query))) || 'null');
      return value && Date.now() - value.saved_at < 30 * 60 * 1000 && (value.items || []).length ? value.items : null;
    } catch (error) { return null; }
  }

  function saveSearch(query, items) {
    try {
      localStorage.setItem(SEARCH_CACHE_PREFIX + encodeURIComponent(cleanTitle(query)), JSON.stringify({saved_at: Date.now(), items: items.slice(0, 100)}));
    } catch (error) {}
  }

  function animeHomeRow() {
    return providerRegistry().then(function (registry) { return searchAnimeUnity('', registry, true); })
      .then(function (items) { return items.length ? {id: 'anime_popular', title: 'Anime', items: items} : null; })
      .catch(function () { return null; });
  }

  function expandHome(host, homepage, mainRows, generation) {
    var archive = [], anime = null, official = [];
    if (generation !== expandedHomeGeneration) return Promise.resolve({rows: expandedHomeRows, expanding: !expandedHomeDone});
    expandedHomeRows = mainRows.slice();
    expandedHomeDone = false;
    function publish() {
      if (generation !== expandedHomeGeneration) return;
      expandedHomeRows = uniqueRows(mainRows.concat(archive, anime ? [anime] : [], official));
      if (expandedHomeRows.length) saveStandaloneHome(expandedHomeRows, false);
    }
    var archiveTask = archiveRows(host, homepage, mainRows.length, function (partial) {
      archive = partial;
      publish();
    }).then(function (rows) { archive = rows || []; publish(); return rows; });
    var animeTask = animeHomeRow().then(function (row) { anime = row; publish(); return row; });
    var officialTask = officialHomeRows().then(function (rows) { official = rows || []; publish(); return rows; });
    return Promise.all([archiveTask, animeTask, officialTask]).then(function () {
      publish();
      if (generation === expandedHomeGeneration) expandedHomeDone = true;
      return {rows: expandedHomeRows, expanding: false};
    }).catch(function () {
      publish();
      if (generation === expandedHomeGeneration) expandedHomeDone = true;
      return {rows: expandedHomeRows, expanding: false};
    });
  }

  function home() {
    if (expandedHomePromise && !expandedHomeDone && expandedHomeRows.length) {
      return Promise.resolve({rows: expandedHomeRows, expanding: true});
    }
    if (homeBootstrapPromise) {
      return deadline(homeBootstrapPromise, 9000, 'Sorgente principale lenta').catch(function () {
        var cached = cachedHome();
        if (cached && cached.rows && cached.rows.length) return {rows: cached.rows, cached: true, expanding: true};
        return tmdbHome().then(function (response) { response.expanding = true; return response; });
      });
    }
    var generation = ++expandedHomeGeneration;
    var primary = ensureHost(false).then(function (host) {
      return Promise.all([dataPage(host + '/it'), dataPage(host + '/it/movies'), dataPage(host + '/it/tv-shows')])
        .then(function (pages) { return {host: host, pages: pages}; });
    }).then(function (bundle) {
      var rows = uniqueRows(rowsFromPage(bundle.pages[0], '').concat(
        rowsFromPage(bundle.pages[1], ' \u2014 Film'), rowsFromPage(bundle.pages[2], ' \u2014 Serie TV')));
      if (generation !== expandedHomeGeneration) return {rows: expandedHomeRows, expanding: !expandedHomeDone};
      expandedHomePromise = expandHome(bundle.host, bundle.pages[0], rows, generation);
      var initial = rows;
      expandedHomeRows = initial.slice();
      if (initial.length) saveStandaloneHome(initial, false);
      return {rows: initial, expanding: true};
    });
    homeBootstrapPromise = primary;
    primary.then(function () { if (homeBootstrapPromise === primary) homeBootstrapPromise = null; },
      function () { if (homeBootstrapPromise === primary) homeBootstrapPromise = null; });
    return deadline(primary, 9000, 'Sorgente principale lenta').catch(function (error) {
      var cached = cachedHome();
      if (cached && cached.rows && cached.rows.length) return {rows: cached.rows, cached: true, expanding: true};
      return tmdbHome().then(function (response) { response.expanding = true; return response; });
    });
  }

  function expandedHome() {
    if (expandedHomePromise) return Promise.resolve({rows: expandedHomeRows, expanding: !expandedHomeDone});
    var cached = cachedHome();
    if (homeBootstrapPromise) return Promise.resolve({rows: expandedHomeRows.length ? expandedHomeRows : (cached && cached.rows || []), expanding: true});
    return cached && cached.rows ? Promise.resolve({rows: cached.rows, cached: true}) : home();
  }

  function search(query) {
    var cached = cachedSearch(query);
    if (cached) return Promise.resolve({items: cached, aggregated: true, cached: true});
    var scSearch = ensureHost(false).then(function (host) {
      return dataPage(host + '/it/search?q=' + encodeURIComponent(query)).then(function (page) {
        var props = page.props || {}, resolvedHost = props.app_url || host, cdn = props.cdn_url || ('https://cdn.' + new URL(resolvedHost).host);
        return flatten(props.titles || []).slice(0, 100).map(function (raw) {
          var item = itemFromRaw(raw, resolvedHost, cdn);
          item.source = 'streamingcommunity';
          item.searchType = item.contentType === 'tvshow' ? 'serie' : 'film';
          return item;
        });
      });
    });
    return providerRegistry().then(function (registry) {
      var tasks = [
        scSearch,
        searchHd4me(query, registry),
        searchAnimeUnity(query, registry, false),
        searchHtmlProvider('cineblog01', query, registry),
        searchHtmlProvider('streamingita', query, registry),
        raiSearch(query),
        mediasetSearch(query),
        la7Search(query)
      ];
      return Promise.all(tasks.map(function (task) { return deadline(task, 9500, 'Provider lento').catch(function () { return []; }); }));
    }).then(function (groups) {
      var items = dedupeSearch(flatten(groups), query);
      if (items.length) {
        saveSearch(query, items);
        return {items: items, aggregated: true, sources: groups.map(function (group) { return group.length; })};
      }
      return tmdbList('/search/multi?query=' + encodeURIComponent(query), '').then(function (fallback) {
        saveSearch(query, fallback);
        return {items: fallback, aggregated: true, fallback: true, sources: groups.map(function (group) { return group.length; })};
      });
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
    if (item.channel === 'raiplay' || item.channel === 'mediasetplay' || item.channel === 'la7') return tmdbDetails(item);
    if (item.tmdbOnly) return tmdbDetails(item);
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

  function normalizeProviderEpisode(episode, parent, season, number, episodeTitle) {
    var name = String(episodeTitle || episode.episodeTitle || episode.title || episode.fulltitle || ('Episodio ' + number)).trim();
    episode.contentType = 'episode';
    episode.action = 'findvideos';
    episode.season = Number(season) || 1;
    episode.episode = Number(number) || 1;
    episode.contentSeason = episode.season;
    episode.contentEpisodeNumber = episode.episode;
    episode.contentSerieName = parent && (parent.fulltitle || parent.title) || episode.contentSerieName || '';
    episode.episodeTitle = name;
    episode.title = name;
    episode.fulltitle = name;
    episode.infoLabels = Object.assign({}, episode.infoLabels || {}, {
      mediatype: 'episode', title: name, episode_title: name,
      season: episode.season, episode: episode.episode,
      plot: episode.plot || (episode.infoLabels || {}).plot || ''
    });
    return episode;
  }

  function raiEpisodes(item) {
    var endpoint = item.video_url || item.providerUrl;
    if (!endpoint) return Promise.reject(new Error('Catalogo RaiPlay non disponibile'));
    return json(endpoint, {cache: 'no-store', credentials: 'include'}, 10000).then(function (program) {
      if (program.first_item_path && !(program.blocks || []).length) {
        return json(raiUrl(program.first_item_path), {cache: 'no-store'}, 10000).then(function (video) {
          var episode = raiItem(video, 'movie');
          return {items: [normalizeProviderEpisode(episode, item, Number(video.season) || 1,
            Number(video.episode) || 1, video.episode_title || video.titolo || video.name || episode.title)]};
        });
      }
      var sets = [], direct = [];
      (program.blocks || []).forEach(function (block) {
        sets = sets.concat(block.sets || []);
        direct = direct.concat(block.items || block.contents || []);
      });
      if (!sets.length && direct.length) {
        return {items: direct.map(function (raw, index) {
          var episode = raiItem(raw, 'tv'), number = Number(raw.episode) || index + 1;
          return normalizeProviderEpisode(episode, item, Number(raw.season) || 1, number,
            raw.episode_title || raw.titolo || raw.name || episode.title);
        })};
      }
      return Promise.all(sets.map(function (set, seasonIndex) {
        var match = String(set.name || '').match(/(\d+)/), season = match ? Number(match[1]) : seasonIndex + 1;
        return json(raiUrl(set.path_id), {cache: 'no-store'}, 10000).then(function (data) {
          return (data.items || data.contents || []).map(function (raw, episodeIndex) {
            var episode = raiItem(raw, 'tv');
            var number = Number(raw.episode) || episodeIndex + 1;
            return normalizeProviderEpisode(episode, item, Number(raw.season) || season, number,
              raw.episode_title || raw.titolo || raw.name || episode.title);
          });
        }).catch(function () { return []; });
      })).then(function (groups) { return {items: flatten(groups)}; });
    });
  }

  function mediasetEpisodes(item) {
    var rawSeasons = Array.isArray(item.seriesid) ? item.seriesid : [{id: item.seriesid, title: 'Stagione 1'}];
    return Promise.all(rawSeasons.map(function (seasonInfo, seasonIndex) {
      var seasonId = seasonInfo.id || seasonInfo, match = String(seasonInfo.title || '').match(/(\d+)(?!.*\d)/);
      var seasonNumber = Number(seasonInfo.number) || (match ? Number(match[1]) : seasonIndex + 1);
      var seasonUrl = seasonInfo.url || item.url || '';
      return mediasetSeasonPageEpisodes(seasonUrl, seasonNumber, item).then(function (pageItems) {
        if (pageItems.length) return pageItems;
        return mediasetLegacySeasonEpisodes(seasonId, seasonNumber, item);
      }).catch(function () { return mediasetLegacySeasonEpisodes(seasonId, seasonNumber, item); });
    })).then(function (groups) { return {items: flatten(groups)}; });
  }

  function mediasetSeasonPageEpisodes(seasonUrl, seasonNumber, parent) {
    if (!seasonUrl) return Promise.resolve([]);
    return text(seasonUrl, {cache: 'no-store', credentials: 'include'}, 12000).then(function (response) {
      var doc = new DOMParser().parseFromString(response.body, 'text/html'), fullIds = {}, fullOrder = [], output = [], seen = {};
      var patterns = [
        /editorialType\\?"\s*:\\?"Full Episode\\?"\s*,\\?"guid\\?"\s*:\\?"(F[A-Z0-9]+)/ig,
        /"editorialType"\s*:\s*"Full Episode"\s*,\s*"guid"\s*:\s*"(F[A-Z0-9]+)/ig
      ];
      patterns.forEach(function (pattern) {
        var match;
        while ((match = pattern.exec(response.body))) {
          if (!fullIds[match[1]]) fullOrder.push(match[1]);
          fullIds[match[1]] = true;
        }
      });
      Array.prototype.forEach.call(doc.querySelectorAll('a[href*="/video/"]'), function (link) {
        var href = absoluteUrl(link.getAttribute('href'), 'https://mediasetinfinity.mediaset.it');
        var idMatch = href.match(/_(F[A-Z0-9]{10,})(?:[?#]|$)/i), image = link.querySelector('img[alt], img[title]');
        if (!idMatch || !image) return;
        var videoId = idMatch[1];
        if (Object.keys(fullIds).length && !fullIds[videoId]) return;
        if (seen[videoId]) return;
        seen[videoId] = true;
        var episodeTitle = image.getAttribute('alt') || image.getAttribute('title') || 'Episodio';
        var numberMatch = episodeTitle.match(/(?:episodio|puntata)\s*(\d+)/i), number = numberMatch ? Number(numberMatch[1]) : output.length + 1;
        var episode = providerItem('mediasetplay', {title: episodeTitle, type: 'tv',
          thumbnail: cleanUrl(image.getAttribute('src') || parent.thumbnail || ''), fanart: parent.fanart || '',
          plot: '', url: href});
        episode.providerOnly = false;
        episode.tmdbOnly = false;
        episode.video_id = videoId;
        output.push(normalizeProviderEpisode(episode, parent, seasonNumber, number, episodeTitle));
      });
      fullOrder.forEach(function (videoId) {
        if (seen[videoId]) return;
        var guidMarker = '\\"guid\\":\\"' + videoId, guidIndex = response.body.indexOf(guidMarker);
        var titleMarker = '\\"cardTitle\\":\\"', titleStart = response.body.lastIndexOf(titleMarker, guidIndex);
        var episodeTitle = 'Episodio ' + (output.length + 1);
        if (titleStart >= 0 && guidIndex - titleStart < 10000) {
          titleStart += titleMarker.length;
          var titleEnd = response.body.indexOf('\\",\\"id\\"', titleStart);
          if (titleEnd > titleStart && titleEnd < guidIndex) {
            var encodedTitle = response.body.slice(titleStart, titleEnd);
            try { episodeTitle = JSON.parse('"' + encodedTitle + '"'); } catch (error) { episodeTitle = encodedTitle; }
          }
        }
        var numberMatch = episodeTitle.match(/(?:episodio|puntata)\s*(\d+)/i), number = numberMatch ? Number(numberMatch[1]) : output.length + 1;
        var thumbnail = 'https://img-prod-api2.mediasetplay.mediaset.it/api/images/mp/v5/ita/' +
          videoId + '/image_keyframe_poster/360/203';
        var episode = providerItem('mediasetplay', {title: episodeTitle, type: 'tv', thumbnail: thumbnail,
          fanart: parent.fanart || '', plot: '', url: seasonUrl});
        episode.providerOnly = false;
        episode.tmdbOnly = false;
        episode.video_id = videoId;
        seen[videoId] = true;
        output.push(normalizeProviderEpisode(episode, parent, seasonNumber, number, episodeTitle));
      });
      return output;
    });
  }

  function mediasetLegacySeasonEpisodes(seasonId, seasonNumber, parent) {
    if (!seasonId) return Promise.resolve([]);
      var subbrands = 'https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-subbrands-v2?byTvSeasonId=' +
        encodeURIComponent(seasonId) + '&sort=mediasetprogram$order';
    return json(subbrands, {cache: 'no-store'}, 10000).then(function (data) {
      return Promise.all((data.entries || []).map(function (entry) {
        var subbrand = entry['mediasetprogram$subBrandId'];
        if (!subbrand) return [];
        var endpoint = 'https://feed.entertainment.tv.theplatform.eu/f/PR1GhC/mediaset-prod-all-programs-v2?byCustomValue=subBrandId%7B' +
          encodeURIComponent(subbrand) + '%7D&range=0-10000&sort=:publishInfo_lastPublished,tvSeasonEpisodeNumber';
        return json(endpoint, {cache: 'no-store'}, 10000).then(function (episodes) {
          return (episodes.entries || []).map(function (raw, episodeIndex) {
            var episode = mediasetItem(raw, 'tv');
            episode.video_id = raw.guid || '';
            var season = Number(raw.tvSeasonNumber || raw['mediasetprogram$seasonNumber']) || seasonNumber;
            var number = Number(raw.tvSeasonEpisodeNumber || raw['mediasetprogram$episodeNumber']) || episodeIndex + 1;
            var episodeTitle = raw['mediasetprogram$episodeTitle'] || raw.title || raw.description || ('Episodio ' + number);
            return normalizeProviderEpisode(episode, parent, season, number, episodeTitle);
          });
        }).catch(function () { return []; });
      }));
    }).then(flatten).catch(function () { return []; });
  }

  function la7Episodes(item) {
    if (item.la7Lookup || !item.url) {
      return la7Search(item.fulltitle || item.title || '').then(function (matches) {
        if (!matches.length) throw new Error('Programma La7 non trovato');
        var series = matches.filter(function (candidate) { return candidate.contentType === 'tvshow'; })[0] || matches[0];
        if (series.contentType !== 'tvshow') {
          series.contentType = 'episode';
          series.action = 'findvideos';
          return {items: [series]};
        }
        return la7Episodes(series);
      });
    }
    return text(item.url, {cache: 'no-store', credentials: 'include'}, 11000).then(function (response) {
      var doc = new DOMParser().parseFromString(response.body, 'text/html'), output = [], seen = {};
      Array.prototype.forEach.call(doc.querySelectorAll('a[href]'), function (link) {
        var art = link.querySelector('[data-background-image]'), titleNode = link.querySelector('.title, .occhiello, h3, h4');
        if (!art || !titleNode) return;
        var href = absoluteUrl(link.getAttribute('href'), 'https://www.la7.it');
        if (!/la7\.it\/(?:[^/]+\/)?(?:video|rivedila7|articolo)\//i.test(href) || seen[href]) return;
        var style = art.getAttribute('data-background-image') || art.style.backgroundImage || '';
        var thumb = cleanUrl(style.replace(/^.*url\(['"]?/, '').replace(/['"]?\).*$/, ''));
        var episodeTitle = String(titleNode.textContent || '').replace(/\s+/g, ' ').trim();
        if (!episodeTitle) return;
        seen[href] = true;
        var episode = providerItem('la7', {title: episodeTitle, type: 'tv', thumbnail: thumb || item.thumbnail,
          fanart: item.fanart || thumb, plot: '', url: href});
        episode.providerOnly = false;
        episode.tmdbOnly = false;
        output.push(normalizeProviderEpisode(episode, item, 1, output.length + 1, episodeTitle));
      });
      if (!output.length) {
        var direct = normalizeProviderEpisode(Object.assign({}, item), item, 1, 1, item.episodeTitle || item.title || item.fulltitle);
        return {items: [direct]};
      }
      return {items: output};
    });
  }

  function episodes(item) {
    if (item.channel === 'raiplay') return raiEpisodes(item);
    if (item.channel === 'mediasetplay') return mediasetEpisodes(item);
    if (item.channel === 'la7') return la7Episodes(item);
    if (item.tmdbOnly) {
      return search(item.fulltitle || item.title || '').then(function (response) {
        var match = (response.items || []).filter(function (candidate) { return candidate.channel === 'streamingcommunity'; })[0];
        if (!match) throw new Error('Episodi non disponibili finché la sorgente principale è offline');
        return episodes(match);
      });
    }
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
                episodeTitle: name,
                plot: episode.plot || '', thumbnail: episodeImage(episode, item.thumbnail, cdn), fanart: item.fanart || '',
                season: season.number, episode: number, contentSeason: season.number, contentEpisodeNumber: number,
                contentSerieName: item.fulltitle || item.title,
                infoLabels: {mediatype: 'episode', title: name, episode_title: name,
                  season: season.number, episode: number, plot: episode.plot || ''},
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
    if (/^(?:https?:|data:)/i.test(item.logo)) return item.logo;
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
        item.isLive = true;
        return item;
      });
      var definitions = [
        {key: 'tv', id: 'live_tv', title: 'TV'},
        {key: 'sky', id: 'live_sky', title: 'SKY'},
        {key: 'sport', id: 'live_sport', title: 'Sport Live'}
      ];
      var rows = definitions.map(function (definition) {
        return {
          id: definition.id,
          title: definition.title,
          items: channels.filter(function (item) { return (item.live_row || 'tv') === definition.key; })
        };
      }).filter(function (row) { return row.items.length; });
      return {rows: rows};
    });
  }

  function skyEpgNorm(value) {
    return String(value || '').toLowerCase().replace(/\+/g, ' plus ').replace(/\bhd\b/g, '')
      .replace(/sky|channel/g, '').replace(/[^a-z0-9]+/g, '');
  }

  function skyEpgChannels() {
    var key = 'prippi.tizen.skyepg.channels.v1';
    try {
      var cached = JSON.parse(localStorage.getItem(key) || 'null');
      if (cached && Date.now() - cached.time < 24 * 60 * 60 * 1000 && cached.channels) return Promise.resolve(cached.channels);
    } catch (error) {}
    return json('https://apid.sky.it/gtv/v1/channels?env=DTH', {cache: 'no-store'}, 10000).then(function (payload) {
      var channels = payload.channels || [];
      try { localStorage.setItem(key, JSON.stringify({time: Date.now(), channels: channels})); } catch (error) {}
      return channels;
    });
  }

  function skyEpg(rows) {
    var premium = [];
    (rows || []).forEach(function (row) {
      if (row.id === 'live_sky' || row.id === 'live_sport') premium = premium.concat(row.items || []);
    });
    if (!premium.length) return Promise.resolve({rows: rows || []});
    return skyEpgChannels().then(function (channels) {
      var byName = {}, byNumber = {}, aliases = {mtv: 'mtvhd', zonadazn: 'dazn1'};
      channels.forEach(function (channel) {
        var norm = skyEpgNorm(channel.name);
        if (norm && byName[norm] == null) byName[norm] = channel.id;
        if (channel.number != null && byNumber[channel.number] == null) byNumber[channel.number] = channel.id;
      });
      var ids = [], idByItem = [];
      premium.forEach(function (item) {
        var norm = skyEpgNorm(item.sport_par || item.title), id = byName[norm];
        if (id == null && aliases[norm]) id = byName[aliases[norm]];
        if (id == null) {
          var number = String(item.sport_par || item.title || '').match(/(2\d\d)/);
          if (number) id = byNumber[Number(number[1])];
        }
        if (id != null) { idByItem.push({item: item, id: String(id)}); if (ids.indexOf(String(id)) < 0) ids.push(String(id)); }
      });
      var now = Date.now(), from = new Date(now - 3 * 60 * 60 * 1000).toISOString().slice(0, 19) + 'Z';
      var to = new Date(now + 5 * 60 * 60 * 1000).toISOString().slice(0, 19) + 'Z', batches = [];
      for (var at = 0; at < ids.length; at += 15) batches.push(ids.slice(at, at + 15));
      return Promise.all(batches.map(function (batch) {
        var endpoint = 'https://apid.sky.it/gtv/v1/events?' + queryString({
          from: from, to: to, pageSize: 400, pageNum: 0, env: 'DTH', channels: batch.join(',')
        });
        return json(endpoint, {cache: 'no-store'}, 10000).then(function (payload) { return payload.events || []; }).catch(function () { return []; });
      })).then(function (groups) {
        var eventsByChannel = {};
        [].concat.apply([], groups).forEach(function (event) {
          var id = String(event.channel && event.channel.id != null ? event.channel.id : event.channel || '');
          if (!eventsByChannel[id]) eventsByChannel[id] = [];
          eventsByChannel[id].push(event);
        });
        idByItem.forEach(function (mapping) {
          var events = (eventsByChannel[mapping.id] || []).sort(function (a, b) { return Date.parse(a.starttime) - Date.parse(b.starttime); });
          var currentIndex = -1;
          events.some(function (event, index) {
            if (Date.parse(event.starttime) <= now && Date.parse(event.endtime) > now) { currentIndex = index; return true; }
            return false;
          });
          if (currentIndex < 0) return;
          var current = events[currentIndex], next = events[currentIndex + 1], start = new Date(current.starttime), end = new Date(current.endtime);
          var hhmm = function (date) { return ('0' + date.getHours()).slice(-2) + ':' + ('0' + date.getMinutes()).slice(-2); };
          mapping.item.program = current.eventTitle || current.epgEventTitle || '';
          mapping.item.epg = hhmm(start) + '-' + hhmm(end) + '  ' + mapping.item.program;
          mapping.item.plot = [mapping.item.epg, current.eventSynopsis || '', next ? 'A seguire ' + hhmm(new Date(next.starttime)) + '  ' + (next.eventTitle || next.epgEventTitle || '') : ''].filter(Boolean).join('\n');
        });
        return {rows: rows || []};
      });
    }).catch(function () { return {rows: rows || []}; });
  }

  function xorDecodedJson(value) {
    var binary = atob(String(value || '').replace(/\s/g, ''));
    var output = '', index;
    for (index = 0; index < binary.length; index += 1) {
      output += String.fromCharCode(binary.charCodeAt(index) ^ LIVE_XOR_SECRET.charCodeAt(index % LIVE_XOR_SECRET.length));
    }
    try { return JSON.parse(decodeURIComponent(escape(output))); }
    catch (error) { return JSON.parse(output); }
  }

  function resolveSkyLive(item) {
    var par = item.sport_par || item.par;
    if (!par) return Promise.reject(new Error('Identificativo canale SKY assente'));
    var endpoint = LIVE_BACKEND + '?numTest=' + encodeURIComponent(LIVE_BACKEND_SKY_RESOLVE) + '&id=' + encodeURIComponent(par);
    return json(endpoint, {cache: 'no-store'}, 12000).then(function (payload) {
      var data = xorDecodedJson(payload && payload.data);
      var manifest = cleanUrl(data && data.manifest), kid = String(data && data.kid || '').replace(/[^0-9a-f]/ig, '').toLowerCase();
      var key = String(data && data.key || '').replace(/[^0-9a-f]/ig, '').toLowerCase();
      if (!manifest || kid.length !== 32 || key.length !== 32) throw new Error('Sessione ClearKey SKY non disponibile');
      var expiry = manifest.match(/_e~(\d+)/);
      if (expiry && Number(expiry[1]) <= Math.floor(Date.now() / 1000) + 30) throw new Error('Sessione SKY scaduta');
      return {
        url: manifest,
        manifest_type: 'mpd',
        drm_type: 'clearkey',
        license_key: kid + ':' + key,
        kid: kid,
        key: key,
        headers: {'User-Agent': NOWTV_UA, 'Referer': NOWTV_ORIGIN + '/', 'Origin': NOWTV_ORIGIN}
      };
    });
  }

  function daddyDomain() {
    if (daddyDomainPromise) return daddyDomainPromise;
    var cached = '';
    try { cached = localStorage.getItem('prippi.tizen.daddy.domain') || ''; } catch (error) {}
    var seeds = cached ? [cached, 'https://dlhd.st', 'https://dlhd.pk', 'https://daddylive.sx'] :
      ['https://dlhd.st', 'https://dlhd.pk', 'https://daddylive.sx'];
    var index = 0;
    function next() {
      if (index >= seeds.length) throw new Error('Dominio Daddy non raggiungibile');
      var seed = seeds[index++];
      return text(seed.replace(/\/$/, '') + '/', {cache: 'no-store'}, 8000).then(function (response) {
        var base = new URL(response.url || seed).origin;
        try { localStorage.setItem('prippi.tizen.daddy.domain', base); } catch (error) {}
        return base;
      }).catch(next);
    }
    daddyDomainPromise = next().catch(function (error) { daddyDomainPromise = null; throw error; });
    return daddyDomainPromise;
  }

  function resolveDaddyLive(item) {
    var code = String(item.daddy_code || (item.sport_kind === 'daddy' ? item.sport_par : '') || '');
    if (!code) return Promise.reject(new Error('Fallback Daddy non disponibile'));
    return daddyDomain().then(function (base) {
      return text(base + '/stream/stream-' + encodeURIComponent(code) + '.php', {
        cache: 'no-store', headers: {'Referer': base + '/'}
      }, 10000).then(function (response) { return {base: base, body: response.body}; });
    }).then(function (page) {
      var iframe = (page.body.match(/<iframe[^>]+src=["']([^"']+)/i) || [])[1];
      if (!iframe) throw new Error('Player Daddy non disponibile');
      iframe = absoluteUrl(iframe, page.base + '/');
      return text(iframe, {cache: 'no-store', headers: {'Referer': page.base + '/'}}, 10000)
        .then(function (response) { return {iframe: iframe, body: response.body}; });
    }).then(function (player) {
      var encoded = (player.body.match(/atob\(['"]([^'"]+)/i) || [])[1];
      var url = encoded ? cleanUrl(atob(encoded)) : '';
      if (!/^https?:/i.test(url)) throw new Error('Stream Daddy non disponibile');
      var origin = new URL(player.iframe).origin;
      return {
        url: url,
        manifest_type: 'hls',
        drm_type: '',
        headers: {'User-Agent': NOWTV_UA, 'Referer': origin + '/', 'Origin': origin},
        live_source: 'daddy'
      };
    });
  }

  function withDaddyFallback(primary, item) {
    return primary.catch(function (primaryError) {
      if (!item.daddy_code) throw primaryError;
      return resolveDaddyLive(item).catch(function (daddyError) {
        throw new Error((primaryError.message || 'Sorgente primaria non disponibile') + '; Daddy: ' + daddyError.message);
      });
    });
  }

  function resolveFreeshotLive(item) {
    var code = item.sport_fs || item.sport_par;
    if (!code) return Promise.reject(new Error('Fallback live non disponibile'));
    return text('https://popcdn.day/player/' + encodeURIComponent(code), {
      cache: 'no-store', headers: {'Referer': FREESHOT_ORIGIN}
    }, 10000).then(function (response) {
      var token = (response.body.match(/currentToken:\s*["'](.*?)["']/i) || [])[1];
      if (!token) throw new Error('Token live non disponibile');
      return {
        url: 'https://lovely.lovetier.bz/' + encodeURIComponent(code) + '/tracks-v1a1/mono.m3u8?token=' + encodeURIComponent(token),
        manifest_type: 'hls', drm_type: '', headers: {'Referer': FREESHOT_ORIGIN, 'Origin': FREESHOT_ORIGIN.replace(/\/$/, '')}
      };
    });
  }

  function resolveIptvOrgLive(item) {
    return text('https://iptv-org.github.io/iptv/countries/it.m3u', {cache: 'no-store'}, 10000).then(function (response) {
      var lines = response.body.split(/\r?\n/), wanted = String(item.sport_par || item.title || '').toLowerCase(), index;
      for (index = 0; index < lines.length - 1; index += 1) {
        if (lines[index].charAt(0) === '#' && lines[index].toLowerCase().indexOf(wanted) >= 0 && /^https?:/i.test(lines[index + 1])) {
          return {url: lines[index + 1].trim(), manifest_type: 'hls', drm_type: '', headers: {}};
        }
      }
      throw new Error('Diretta non disponibile nel catalogo IPTV');
    });
  }

  function resolveSportLive(item) {
    var kind = String(item.sport_kind || '').toLowerCase();
    if (kind === 'sky') {
      var primary = resolveSkyLive(item);
      if (item.sport_fs) primary = primary.catch(function () { return resolveFreeshotLive(item); });
      return withDaddyFallback(primary, item);
    }
    if (kind === 'freeshot') return withDaddyFallback(resolveFreeshotLive(item), item);
    if (kind === 'daddy') return resolveDaddyLive(item);
    if (kind === 'iptvorg') return resolveIptvOrgLive(item);
    return Promise.reject(new Error('Resolver live non supportato: ' + (kind || 'sconosciuto')));
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
        body: JSON.stringify(item.video_id ? {
          contentId: item.video_id, streamType: 'VOD', delivery: 'Streaming', createDevice: 'true',
          overrideAppName: 'web//mediasetplay-web/5.2.4-6ad16a4'
        } : {
          channelCode: item.callSign, streamType: 'LIVE', delivery: 'Streaming', createDevice: 'true',
          overrideAppName: 'web//mediasetplay-web/5.2.4-6ad16a4'
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
    if (item.la7Lookup || !item.url) {
      return la7Search(item.fulltitle || item.title || '').then(function (items) {
        if (!items.length) throw new Error('Contenuto La7 non trovato');
        return resolveLa7(items[0]);
      });
    }
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
    if (item.channel === 'sportchannels' || item.sport_kind) return resolveSportLive(item);
    if (item.channel === 'raiplay') return withDaddyFallback(resolveRai(item), item);
    if (item.channel === 'mediasetplay') return withDaddyFallback(resolveMediaset(item), item);
    if (item.channel === 'la7') return withDaddyFallback(resolveLa7(item), item);
    if (item.tmdbOnly) {
      return ensureHost(false).then(function () { return search(item.fulltitle || item.title || ''); }).then(function (response) {
        var match = (response.items || []).filter(function (candidate) { return candidate.channel === 'streamingcommunity'; })[0];
        if (!match) throw new Error('Sorgente non disponibile per questo titolo');
        return resolveStreamingCommunity(match);
      });
    }
    if (item.channel === 'streamingcommunity' || /streamingcommunity/i.test(item.url || '')) return resolveStreamingCommunity(item);
    if (item.channel === 'discoveryplus') return resolveDiscovery(item);
    if (/\.(m3u8|mpd|mp4)(\?|$)/i.test(item.url || '')) {
      return Promise.resolve({url: item.url, manifest_type: /\.mpd/i.test(item.url) ? 'mpd' : /\.m3u8/i.test(item.url) ? 'hls' : 'progressive', headers: item.headers || {}, drm_type: ''});
    }
    return Promise.reject(new Error('Sorgente non ancora portata in modalità standalone'));
  }

  function request(path, body) {
    var route = String(path || '').split('?')[0];
    if (route === '/home') return home();
    if (route === '/home-expanded') return expandedHome();
    if (route === '/search') return search(decodeURIComponent((String(path).split('q=')[1] || '').replace(/\+/g, ' ')));
    if (route === '/detail') return detail((body || {}).item || {});
    if (route === '/episodes') return episodes((body || {}).item || {});
    if (route === '/resolve') return resolve((body || {}).item || {});
    if (route === '/live') return live();
    if (route === '/live-epg') return skyEpg((body || {}).rows || []);
    if (route === '/browse-macros') return Promise.resolve({items: []});
    if (route === '/settings') return Promise.resolve({items: [
      {id: 'runtime', label: 'Motore', value: 'Standalone Tizen'},
      {id: 'ota', label: 'Aggiornamenti', value: document.documentElement.getAttribute('data-prippi-version') || 'attivi'}
    ]});
    return Promise.reject(new Error('Funzione standalone non disponibile: ' + route));
  }

  window.PrippiStandalone = {request: request, ensureHost: ensureHost, dataPage: dataPage};
}());
