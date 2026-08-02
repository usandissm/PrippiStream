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

  function resolve(item) {
    if (item.channel === 'streamingcommunity' || /streamingcommunity/i.test(item.url || '')) return resolveStreamingCommunity(item);
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
    if (route === '/live') return Promise.resolve({rows: []});
    if (route === '/browse-macros') return Promise.resolve({items: []});
    if (route === '/settings') return Promise.resolve({items: [
      {id: 'runtime', label: 'Motore', value: 'Standalone Tizen'},
      {id: 'ota', label: 'Aggiornamenti', value: document.documentElement.getAttribute('data-prippi-version') || 'attivi'}
    ]});
    return Promise.reject(new Error('Funzione standalone non disponibile: ' + route));
  }

  window.PrippiStandalone = {request: request, ensureHost: ensureHost, dataPage: dataPage};
}());

(function(){'use strict';
  var API=localStorage.getItem('prippi.tizen.api')||'';
  var DEMO='https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_ts/master.m3u8';
  var HOME_CACHE='prippi.tizen.home.v1',CACHE_MAX_AGE=30*60*1000;
  var state={page:'home',home:[],live:[],items:{},detail:null,playing:false,playerUiTimer:null,playerTick:null,playerEngine:'',htmlFallback:false};
  var avplay=window.webapis&&window.webapis.avplay;
  function esc(v){return String(v||'').replace(/[&<>"']/g,function(x){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[x];});}
  function title(x){return x.fulltitle||x.title||(x.infoLabels&&x.infoLabels.title)||'Senza titolo';}
  function image(x){return x.thumbnail||x.poster||x.fanart||'';}
  function note(x){var i=x.infoLabels||{};return [i.year||x.year,i.mediatype==='tvshow'?'Serie TV':i.mediatype==='movie'?'Film':''].filter(Boolean).join(' · ');}
  function save(x){var id='i'+Object.keys(state.items).length;state.items[id]=x;return id;}
  function toast(t){var e=document.getElementById('toast');e.textContent=t;e.className='toast show';setTimeout(function(){e.className='toast';},3000);}
  function status(ok,text){var e=document.getElementById('connection');e.textContent=(ok?'● ':'● ')+text;e.className=ok?'ok':'';}
  function request(path,body){if(window.PrippiStandalone)return window.PrippiStandalone.request(path,body);if(!API)return Promise.reject(Error('Motore standalone non disponibile'));var opts=body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{};return fetch(API+path,opts).then(function(r){return r.json();}).then(function(d){if(!d.ok)throw Error(d.error||'Risposta non valida');return d.data||d;});}
  function card(item,live){
    var id=save(item),img=image(item);
    var poster='<span class="poster" data-image="'+esc(img)+'"></span>';
    var description=live?'<small>'+esc(item.plot||'Live')+'</small>':'';
    return '<button class="card '+(live?'live':'')+'" data-item="'+id+'" data-focusable>'+poster+'<span class="card-copy">'+esc(title(item))+description+'</span></button>';
  }
  function rowMarkup(row,live){return '<section class="row"><h2>'+esc(row.title||'PrippiStream')+'</h2><div class="cards">'+(row.items||[]).slice(0,10).map(function(x){return card(x,live||x.isLive);}).join('')+'</div></section>';}
  function renderRows(rows,live){if(!rows.length)return '<div class="empty">Nessun contenuto disponibile.</div>';return rows.map(function(row){return rowMarkup(row,live);}).join('');}
  function hydratePosters(root){var queue=Array.prototype.slice.call((root||document).querySelectorAll('.poster[data-image]')).map(function(el){var url=el.getAttribute('data-image');el.removeAttribute('data-image');return {el:el,url:url};});function next(){var batch=queue.splice(0,6);batch.forEach(function(job){var el=job.el,url=job.url;if(!url){el.className+=' no-image';return;}var probe=new Image();probe.onload=function(){el.style.backgroundImage='url("'+url.replace(/["\\]/g,'\\$&')+'")';};probe.onerror=function(){el.className+=' no-image';};probe.src=url;});if(queue.length)setTimeout(next,160);}next();}
  function bindContent(root){root=root||document;Array.prototype.forEach.call(root.querySelectorAll('[data-item]'),function(e){e.onclick=function(){showDetail(state.items[e.dataset.item]);};e.onfocus=function(){if(state.page==='home')updateHero(state.items[e.dataset.item]);};});Array.prototype.forEach.call(document.querySelectorAll('[data-nav]'),function(e){e.onclick=function(){openPage(e.dataset.nav);};});hydrateHero(root);hydratePosters(root);}
  function renderHome(){var hero=state.home[0]&&state.home[0].items&&state.home[0].items[0],initial=state.home.slice(0,4);var h=hero?'<section class="hero"><div class="hero-art" data-hero-image="'+esc(hero.fanart||image(hero))+'"></div><div class="hero-copy"><small>IN EVIDENZA</small><h2>'+esc(title(hero))+'</h2><p>'+esc((hero.plot||'Scopri il catalogo PrippiStream.').slice(0,150))+'</p></div></section>':'';return h+renderRows(initial,false)+'<div id="home-tail"></div>';}
  function hydrateHero(root){Array.prototype.forEach.call((root||document).querySelectorAll('.hero-art[data-hero-image]'),function(el){var url=el.getAttribute('data-hero-image');el.removeAttribute('data-hero-image');if(!url)return;var probe=new Image();probe.onload=function(){el.style.backgroundImage='linear-gradient(90deg,#10284a 0%,rgba(12,30,56,.55) 48%,rgba(6,15,28,.15)),url("'+url.replace(/["\\]/g,'\\$&')+'")';};probe.src=url;});}
  function updateHero(item){var hero=document.querySelector('.hero'),art=document.querySelector('.hero-art'),copy=document.querySelector('.hero-copy');if(!hero||!art||!copy||!item)return;var url=item.fanart||image(item);art.style.backgroundImage='linear-gradient(90deg,#10284a 0%,rgba(12,30,56,.55) 48%,rgba(6,15,28,.15)),url("'+String(url||'').replace(/["\\]/g,'\\$&')+'")';var h=copy.querySelector('h2'),p=copy.querySelector('p');if(h)h.textContent=title(item);if(p)p.textContent=(item.plot||'Scopri il catalogo PrippiStream.').slice(0,170);}
  function appendHomeRows(){var tail=document.getElementById('home-tail'),at=4;if(!tail)return;function next(){if(state.page!=='home'||!tail.parentNode)return;var rows=state.home.slice(at,at+2);if(!rows.length)return;tail.insertAdjacentHTML('beforebegin',rows.map(function(row){return rowMarkup(row,false);}).join(''));bindContent(document.getElementById('content'));at+=rows.length;setTimeout(next,45);}setTimeout(next,0);}
  function renderSearch(){return '<div class="search-box"><input id="query" data-focusable autocomplete="off" placeholder="Cerca film, serie, anime…"><button id="search-go" class="action" data-focusable>Cerca</button></div><div id="search-results" class="catalog"></div>';}
  function renderBrowse(items){return '<div class="catalog">'+items.map(function(x){return card(x,false);}).join('')+'</div>';}
  function renderSettings(items){return '<div class="settings-list">'+items.map(function(x){return '<div class="setting"><div><b>'+esc(x.label||x.title||x.id)+'</b><small>'+esc(x.description||'Impostazione condivisa PrippiStream')+'</small></div><span>'+esc(String(x.value||''))+'</span></div>';}).join('')+'</div>';}
  function render(){var titleMap={home:'Home',search:'Cerca',browse:'Sfoglia',live:'Live TV',downloads:'Download',settings:'Impostazioni'};document.getElementById('page-title').textContent=titleMap[state.page];Array.prototype.forEach.call(document.querySelectorAll('[data-nav]'),function(x){x.className=x.dataset.nav===state.page?'active':'';});var c=document.getElementById('content');if(state.page==='home')c.innerHTML=state.home.length?renderHome():'<div class="loading">Caricamento Home…</div>';else if(state.page==='search')c.innerHTML=renderSearch();else if(state.page==='live')c.innerHTML=state.live.length?renderRows(state.live,true):'<div class="loading">Caricamento canali Live…</div>';else if(state.page==='downloads')c.innerHTML='<div class="download-note"><b>Download offline</b><p>La schermata e la cronologia saranno condivise con l’app Android. Il download fisico sulla TV richiede una gestione storage dedicata Tizen: lo abilitiamo dopo aver validato Home, ricerca, Live e player.</p></div>';else c.innerHTML='<div class="loading">Caricamento…</div>';bindContent(c);if(state.page==='home'&&state.home.length)appendHomeRows();var first=document.querySelector('.content [data-focusable]');if(first)first.focus();}
  function cachedHome(){try{var c=JSON.parse(localStorage.getItem(HOME_CACHE)||'null');return c&&Date.now()-c.time<CACHE_MAX_AGE?c.rows:null;}catch(e){return null;}}
  function saveHome(rows){try{var compact=rows.slice(0,8).map(function(row){var r={};Object.keys(row).forEach(function(k){r[k]=row[k];});r.items=(row.items||[]).slice(0,10);return r;});localStorage.setItem(HOME_CACHE,JSON.stringify({time:Date.now(),rows:compact}));}catch(e){}}
  function loadHome(){var cached=cachedHome();if(cached&&!state.home.length){state.home=cached;if(state.page==='home')render();}status(false,'Aggiornamento Home…');return request('/home').then(function(x){state.home=x.rows||[];saveHome(state.home);status(true,'Connesso al motore PrippiStream');if(state.page==='home')render();}).catch(function(e){status(cached,'Home dalla cache locale');if(!cached)document.getElementById('content').innerHTML='<div class="error">'+esc(e.message)+'</div>';});}
  function openPage(page){state.page=page;render();if(page==='home')loadHome();if(page==='live')request('/live').then(function(x){state.live=x.rows||[];render();}).catch(function(e){toast(e.message);});if(page==='browse')request('/browse-macros').then(function(x){document.getElementById('content').innerHTML=renderBrowse(x.items||[]);bindContent();}).catch(function(e){toast(e.message);});if(page==='settings')request('/settings').then(function(x){document.getElementById('content').innerHTML=renderSettings(x.items||[]);}).catch(function(e){toast(e.message);});if(page==='search')setTimeout(function(){var q=document.getElementById('query');q.focus();document.getElementById('search-go').onclick=runSearch;q.onkeydown=function(e){if(e.keyCode===13)runSearch();};},0);}
  function runSearch(){var q=document.getElementById('query').value.trim();if(!q)return;document.getElementById('search-results').innerHTML='<div class="loading">Ricerca in corso…</div>';request('/search?q='+encodeURIComponent(q)).then(function(x){document.getElementById('search-results').innerHTML=renderBrowse(x.items||[]);bindContent();}).catch(function(e){document.getElementById('search-results').innerHTML='<div class="error">'+esc(e.message)+'</div>';});}
  function isSeries(item){var info=item.infoLabels||{};return item.action==='episodios'||item.action==='episodes'||info.mediatype==='tvshow'||item.mediatype==='tvshow';}
  function showDetail(item){state.detail=item;var series=isSeries(item),el=document.getElementById('detail'),primary=series?'Episodi':'▶ Riproduci';el.className='overlay';el.innerHTML='<div class="detail-poster" style="background-image:url('+esc(image(item))+')"></div><div class="detail-body"><small>'+esc(note(item)||'PRIPPISTREAM')+'</small><h2>'+esc(title(item))+'</h2><p>'+esc(item.plot||'Caricamento informazioni…')+'</p><div class="actions"><button class="play" id="play" data-focusable>'+primary+'</button><button id="trailers" data-focusable>Trailer</button><button id="close-detail" data-focusable>Indietro</button></div></div>';document.getElementById('close-detail').onclick=closeDetail;document.getElementById('play').onclick=function(){series?showEpisodes(item):play(item);};document.getElementById('trailers').onclick=function(){toast('Trailer: integrazione WebView/YouTube nel prossimo passaggio');};document.getElementById('play').focus();request('/detail',{item:item}).then(function(x){state.detail=x;var p=el.querySelector('p');if(p)p.textContent=x.plot||item.plot||'Nessuna trama disponibile.';}).catch(function(){});}
  function showEpisodes(item){var el=document.getElementById('detail');el.innerHTML='<div class="detail-body" style="max-width:1300px"><small>SERIE TV</small><h2>'+esc(title(item))+'</h2><p>Caricamento episodi…</p></div>';request('/episodes',{item:item}).then(function(x){var episodes=x.items||x.episodes||[];if(!episodes.length)throw Error('Nessun episodio disponibile');el.innerHTML='<div class="detail-body" style="max-width:1300px"><small>SERIE TV</small><h2>'+esc(title(item))+'</h2><div class="catalog">'+episodes.map(function(ep){return card(ep,false);}).join('')+'</div><div class="actions"><button id="close-detail" data-focusable>Indietro</button></div></div>';document.getElementById('close-detail').onclick=closeDetail;bindContent();var first=el.querySelector('[data-focusable]');if(first)first.focus();}).catch(function(e){el.innerHTML='<div class="detail-body"><h2>Impossibile caricare gli episodi</h2><p>'+esc(e.message)+'</p><div class="actions"><button id="close-detail" data-focusable>Indietro</button></div></div>';document.getElementById('close-detail').onclick=closeDetail;document.getElementById('close-detail').focus();});}
  function closeDetail(){document.getElementById('detail').className='overlay hidden';state.detail=null;var f=document.querySelector('.content [data-focusable]');if(f)f.focus();}
  function findUrl(data){if(typeof data==='string'&&/^https?:/.test(data))return data;if(!data||typeof data!=='object')return '';var keys=['url','media_url','stream_url','manifest_url','playback_url'];for(var i=0;i<keys.length;i++)if(typeof data[keys[i]]==='string'&&/^https?:/.test(data[keys[i]]))return data[keys[i]];if(Array.isArray(data)){for(var j=0;j<data.length;j++){var u=findUrl(data[j]);if(u)return u;}}return '';}
  function isNativeMedia(url,manifest){return /^(hls|mpd|dash|progressive)$/i.test(manifest||'')||/\.(m3u8|mpd|mp4|m4s|ts)(\?|$)/i.test(url||'');}
  function play(item){toast('Risoluzione stream…');request('/resolve',{item:item}).then(function(x){var url=findUrl(x);if(!url)throw Error('Nessuno stream compatibile restituito');if(String(x.drm_type||'').toLowerCase()==='clearkey')throw Error('Questo canale usa ClearKey: il player Samsung non lo supporta ancora');if(isNativeMedia(url,x.manifest_type))openPlayer(url,title(item),'Riproduzione',x.headers||{},x.manifest_type||'');else openEmbed(url,title(item));}).catch(function(e){toast('Riproduzione non disponibile: '+e.message);});}
  function showPlayerUi(){var ui=document.getElementById('player-ui');ui.className='player-ui';clearTimeout(state.playerUiTimer);state.playerUiTimer=setTimeout(function(){ui.className='player-ui hidden';},5500);}
  function timeLabel(ms){var total=Math.max(0,Math.floor((ms||0)/1000)),m=Math.floor(total/60),s=total%60;return m+':'+(s<10?'0':'')+s;}
  function setPlayerText(name,sub){['player-title','player-title-new'].forEach(function(id){var el=document.getElementById(id);if(el)el.textContent=name||'';});['player-subtitle','player-subtitle-new'].forEach(function(id){var el=document.getElementById(id);if(el)el.textContent=sub||'';});}
  function updateTimeline(){try{var video=document.getElementById('html-player'),duration=state.playerEngine==='html'?(video.duration*1000):avplay.getDuration(),current=state.playerEngine==='html'?(video.currentTime*1000):avplay.getCurrentTime(),percent=(duration>0&&isFinite(duration))?Math.min(100,(current/duration)*100):0,label=percent?timeLabel(current)+' / '+timeLabel(duration):'LIVE';['player-progress','player-progress-new'].forEach(function(id){var el=document.getElementById(id);if(el)el.style.width=percent+'%';});['player-time','player-time-new'].forEach(function(id){var el=document.getElementById(id);if(el)el.textContent=label;});}catch(e){}}
  function startTimeline(){clearInterval(state.playerTick);updateTimeline();state.playerTick=setInterval(updateTimeline,500);}
  function openEmbed(url,name){closeDetail();var player=document.getElementById('player');player.className='player';player.style.cssText='position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:20;background:#000;display:block';document.getElementById('player-title').textContent=name;document.getElementById('player-subtitle').textContent='Avvio player del provider…';showPlayerUi();var old=document.getElementById('embed-player');if(old)old.parentNode.removeChild(old);var frame=document.createElement('iframe');frame.id='embed-player';frame.style.cssText='position:absolute;left:0;top:0;width:100vw;height:100vh;border:0;background:#000';frame.src=url;frame.setAttribute('allowfullscreen','');frame.onload=function(){state.playing=true;document.getElementById('player-subtitle').textContent='Player del provider';showPlayerUi();};player.insertBefore(frame,document.getElementById('avplay'));}
  function openPlayer(url,name,sub,headers,manifest){closeDetail();var player=document.getElementById('player'),video=document.getElementById('html-player'),surface=document.getElementById('avplay');player.className='player';player.style.cssText='position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:20;background:#000;display:block';setPlayerText(name,'Connessione…');showPlayerUi();state.htmlFallback=false;if(/^(hls|progressive)$/i.test(manifest||'')){state.playerEngine='html';surface.style.display='none';video.style.display='block';video.src=url;video.oncanplay=function(){video.play();state.playing=true;setPlayerText(name,sub);startTimeline();showPlayerUi();};video.onerror=function(){if(state.htmlFallback)return;state.htmlFallback=true;video.pause();video.removeAttribute('src');video.load();openAvPlayer(url,name,sub);};video.load();}else openAvPlayer(url,name,sub);}
  function openAvPlayer(url,name,sub){if(!avplay){toast('AVPlay disponibile soltanto sulla TV Samsung');return;}var video=document.getElementById('html-player'),surface=document.getElementById('avplay');state.playerEngine='avplay';video.style.display='none';surface.style.cssText='position:absolute;left:0;top:0;width:100vw;height:100vh;display:block;z-index:0';try{var vw=document.documentElement.clientWidth||window.innerWidth||1920,vh=document.documentElement.clientHeight||window.innerHeight||1080,scale=1920/vw;avplay.open(url||DEMO);avplay.setDisplayRect(0,0,Math.round(vw*scale),Math.round(vh*scale));avplay.setDisplayMethod('PLAYER_DISPLAY_MODE_AUTO_ASPECT_RATIO');avplay.prepareAsync(function(){avplay.play();state.playing=true;setPlayerText(name,sub);startTimeline();showPlayerUi();},function(e){setPlayerText(name,'Errore AVPlay: '+e);showPlayerUi();});}catch(e){setPlayerText(name,'Errore AVPlay: '+e.message);showPlayerUi();}}
  function closePlayer(){if(!state.playing&&document.getElementById('player').className.indexOf('hidden')>=0)return;var frame=document.getElementById('embed-player'),player=document.getElementById('player'),video=document.getElementById('html-player');if(frame)frame.parentNode.removeChild(frame);video.pause();video.removeAttribute('src');video.load();try{avplay.stop();avplay.close();}catch(e){}state.playing=false;state.playerEngine='';clearTimeout(state.playerUiTimer);clearInterval(state.playerTick);document.getElementById('player-ui').className='player-ui hidden';player.removeAttribute('style');document.getElementById('avplay').removeAttribute('style');player.className='player hidden';}
  function toggle(){try{var video=document.getElementById('html-player');if(state.playing){if(state.playerEngine==='html')video.pause();else avplay.pause();state.playing=false;toast('In pausa');}else{if(state.playerEngine==='html')video.play();else avplay.play();state.playing=true;toast('Riproduzione');}['player-toggle','player-toggle-new'].forEach(function(id){var el=document.getElementById(id);if(el)el.textContent=state.playing?'Ⅱ':'▶';});showPlayerUi();}catch(e){}}
  function seek(seconds){try{var video=document.getElementById('html-player');if(state.playerEngine==='html'&&isFinite(video.duration)){video.currentTime=Math.max(0,Math.min(video.duration,video.currentTime+seconds));}else if(state.playerEngine==='avplay'){if(seconds>0)avplay.jumpForward(seconds*1000,function(){},function(){});else avplay.jumpBackward(Math.abs(seconds)*1000,function(){},function(){});}updateTimeline();showPlayerUi();}catch(e){}}
  function move(key){var all=Array.prototype.slice.call(document.querySelectorAll('[data-focusable]')).filter(function(x){return x.offsetParent!==null;});var a=document.activeElement,ar=a.getBoundingClientRect(),best=null,score=Infinity;all.forEach(function(x){if(x===a)return;var r=x.getBoundingClientRect(),dx=(r.left+r.width/2)-(ar.left+ar.width/2),dy=(r.top+r.height/2)-(ar.top+ar.height/2),valid=(key===37&&dx<-4)||(key===39&&dx>4)||(key===38&&dy<-4)||(key===40&&dy>4);if(!valid)return;var s=(key===37||key===39)?Math.abs(dx)+Math.abs(dy)*2.6:Math.abs(dy)+Math.abs(dx)*2.6;if(s<score){score=s;best=x;}});if(best){best.focus();best.scrollIntoView({block:'nearest',inline:'nearest'});}}
  document.addEventListener('keydown',function(e){var k=e.keyCode;if(document.getElementById('player').className.indexOf('hidden')<0){showPlayerUi();if(k===10009||k===27||k===8||k===413){e.preventDefault();closePlayer();}else if(k===37||k===412){e.preventDefault();seek(-10);}else if(k===39||k===417){e.preventDefault();seek(10);}else if(k===13||k===415||k===10252){e.preventDefault();toggle();}return;}if(document.getElementById('detail').className.indexOf('hidden')<0&&[10009,27,8].indexOf(k)>=0){e.preventDefault();closeDetail();return;}if(k===13||k===415||k===10252){var active=document.activeElement;if(active&&active.hasAttribute('data-focusable')){e.preventDefault();active.click();}return;}if([37,38,39,40].indexOf(k)>=0){e.preventDefault();move(k);}else if(k===10009||k===27||k===8){e.preventDefault();try{tizen.application.getCurrentApplication().exit();}catch(x){}}});
  function keys(){if(!window.tizen||!tizen.tvinputdevice)return;['MediaPlayPause','MediaPlay','MediaPause','MediaStop','MediaFastForward','MediaRewind','ChannelUp','ChannelDown'].forEach(function(k){try{tizen.tvinputdevice.registerKey(k);}catch(e){}});}
  function boot(){if(window.__PRIPPI_APP_BOOTED__)return;window.__PRIPPI_APP_BOOTED__=true;keys();document.getElementById('player-toggle').onclick=toggle;document.getElementById('player-toggle-new').onclick=toggle;document.getElementById('player-rewind').onclick=function(){seek(-10);};document.getElementById('player-forward').onclick=function(){seek(10);};document.getElementById('player-exit').onclick=closePlayer;openPage('home');}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
}());
