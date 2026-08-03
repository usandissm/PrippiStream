(function () {
  'use strict';

  localStorage.removeItem('prippi.tizen.api');

  var HOME_CACHE = 'prippi.tizen.home.v3';
  var CW_KEY = 'prippi.tizen.continue_watching.v1';
  var CACHE_MAX_AGE = 30 * 60 * 1000;
  var PLAYER_HIDE_MS = 6500;
  var CW_MIN_PROGRESS_MS = 10000;
  var CW_COMPLETE_PERCENT = 92;
  var CW_MAX_ITEMS = 30;
  var UP_NEXT_PROMPT_MS = 60000;
  var UP_NEXT_MIN_WATCHED_MS = 60000;
  var avplay = window.webapis && window.webapis.avplay;
  var state = {
    page: 'home',
    home: [],
    homeLoading: false,
    homeError: '',
    live: [],
    liveLoading: false,
    liveError: '',
    searchItems: [],
    searchQuery: '',
    searchFilter: 'all',
    items: {},
    itemSeq: 0,
    renderGeneration: 0,
    renderedRows: 0,
    detail: null,
    detailParent: null,
    detailOrigin: '',
    focusMemory: {},
    playerOpen: false,
    playing: false,
    playerLive: false,
    playerEngine: '',
    playerUiTimer: null,
    playerTick: null,
    toastTimer: null,
    htmlFallback: false,
    hlsInstance: null,
    shakaInstance: null,
    hlsFatalRetries: 0,
    playerItem: null,
    pendingResumeMs: 0,
    lastProgressSave: 0,
    episodeQueue: [],
    episodeIndex: -1,
    episodeParent: null,
    upNextVisible: false,
    upNextCancelled: false,
    switchingEpisode: false,
    episodeTransitionScheduled: false,
    episodeTransitionTimer: null,
    liveQueue: [],
    liveIndex: -1,
    liveRowTitle: '',
    liveSwitchBusy: false,
    liveSwitchAt: 0,
    playRequestId: 0
  };

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (character) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character];
    });
  }

  function title(item) {
    var labels = item && item.infoLabels || {};
    return item && (item.fulltitle || item.title || labels.title) || 'Senza titolo';
  }

  function image(item) {
    return item && (item.thumbnail || item.poster || item.fanart) || '';
  }

  function info(item) {
    return item && item.infoLabels || {};
  }

  function summary(value, limit) {
    var text = String(value || '').replace(/\s+/g, ' ').replace(/^\s+|\s+$/g, '');
    if (text.length <= limit) return text;
    return text.slice(0, Math.max(0, limit - 1)).replace(/\s+\S*$/, '') + '…';
  }

  function mediaType(item) {
    var value = String(info(item).mediatype || item.contentType || '').toLowerCase();
    if (item && String(item.contentType || '').toLowerCase() === 'episode') return 'episode';
    if (/episode/.test(value)) return 'episode';
    if (/tv|serie|season/.test(value)) return 'series';
    if (item && item.isLive) return 'live';
    return 'movie';
  }

  function isSeries(item) { return mediaType(item) === 'series'; }
  function isEpisode(item) { return mediaType(item) === 'episode'; }

  function itemNote(item) {
    var labels = info(item), parts = [];
    if (labels.year || item.year) parts.push(labels.year || item.year);
    if (labels.rating) parts.push('Valutazione ' + Number(labels.rating).toFixed(1));
    if (!parts.length) {
      if (isSeries(item)) parts.push('Serie TV');
      else if (isEpisode(item)) parts.push('Episodio');
      else if (item.isLive) parts.push('In diretta');
      else parts.push('Film');
    }
    return parts.join('  -  ');
  }

  function normalizedKey(value) {
    return String(value || '').toLowerCase().replace(/[^a-z0-9\u00c0-\u024f]+/g, '');
  }

  function continueKey(item, parent) {
    var labels = info(item), parentLabels = info(parent || {}), episode = isEpisode(item), series = episode || isSeries(item);
    var tmdb = series ? (parentLabels.tmdb_id || labels.tmdb_id) : labels.tmdb_id;
    var name = episode ? ((parent && title(parent)) || item.contentSerieName || item.show || title(item)) : title(item);
    var fallback = normalizedKey(name) || normalizedKey(item.url) || normalizedKey(item.video_id);
    return (series ? 'tv_' : 'movie_') + (tmdb || fallback);
  }

  function sameMedia(left, right) {
    if (!left || !right) return false;
    if (isEpisode(left) || isEpisode(right)) {
      if (left.video_id && right.video_id) return String(left.video_id) === String(right.video_id);
      var leftSeason = Number(left.season || left.contentSeason || 0), rightSeason = Number(right.season || right.contentSeason || 0);
      var leftEpisode = Number(left.episode || left.contentEpisodeNumber || 0), rightEpisode = Number(right.episode || right.contentEpisodeNumber || 0);
      var leftSeries = normalizedKey(left.contentSerieName || left.show || ''), rightSeries = normalizedKey(right.contentSerieName || right.show || '');
      if (leftSeason && leftEpisode && leftSeason === rightSeason && leftEpisode === rightEpisode &&
          (!leftSeries || !rightSeries || leftSeries === rightSeries)) return true;
    }
    if (left.video_id && right.video_id) return String(left.video_id) === String(right.video_id);
    if (left.url && right.url) return String(left.url) === String(right.url);
    return Number(left.season || left.contentSeason || 0) === Number(right.season || right.contentSeason || 0) &&
      Number(left.episode || left.contentEpisodeNumber || 0) === Number(right.episode || right.contentEpisodeNumber || 0) &&
      normalizedKey(left.contentSerieName || left.show || left.fulltitle) === normalizedKey(right.contentSerieName || right.show || right.fulltitle);
  }

  function cleanStoredItem(item) {
    try {
      return JSON.parse(JSON.stringify(item || {}, function (key, value) {
        if (/^_cw/.test(key) || key === '_displaySeason') return undefined;
        return value;
      }));
    } catch (error) { return {}; }
  }

  function readContinueWatching() {
    try {
      var entries = JSON.parse(localStorage.getItem(CW_KEY) || '[]');
      if (!Array.isArray(entries)) return [];
      return entries.filter(function (entry) {
        return entry && entry.key && entry.item && !entry.item.isLive;
      }).sort(function (a, b) { return Number(b.updatedAt || 0) - Number(a.updatedAt || 0); }).slice(0, CW_MAX_ITEMS);
    } catch (error) { return []; }
  }

  function writeContinueWatching(entries) {
    var values = (entries || []).slice(0, CW_MAX_ITEMS);
    while (values.length) {
      try { localStorage.setItem(CW_KEY, JSON.stringify(values)); return true; } catch (error) { values.pop(); }
    }
    try { localStorage.removeItem(CW_KEY); } catch (error) {}
    return false;
  }

  function compactQueueItem(item) {
    var stored = cleanStoredItem(item), labels = Object.assign({}, stored.infoLabels || {});
    delete stored.plot;
    delete labels.plot;
    stored.infoLabels = labels;
    return stored;
  }

  function findContinueWatching(item, parent) {
    var key = continueKey(item, parent);
    return readContinueWatching().filter(function (entry) { return entry.key === key; })[0] || null;
  }

  function removeContinueWatching(item, parent) {
    var key = continueKey(item, parent);
    writeContinueWatching(readContinueWatching().filter(function (entry) { return entry.key !== key; }));
    refreshContinueWatchingRow();
  }

  function saveContinueWatching(item, position, duration, force) {
    if (!item || item.isLive || state.playerLive) return;
    position = Math.max(0, Number(position || 0));
    duration = Math.max(0, Number(duration || 0));
    var parent = state.episodeParent, key = continueKey(item, parent), entries = readContinueWatching();
    if (!force && position < CW_MIN_PROGRESS_MS) return;
    if (!force && duration > 0 && position >= duration * CW_COMPLETE_PERCENT / 100) {
      writeContinueWatching(entries.filter(function (entry) { return entry.key !== key; }));
      refreshContinueWatchingRow();
      return;
    }
    var queue = [], queueIndex = -1;
    if (isEpisode(item)) {
      var sourceQueue = state.episodeQueue.length ? state.episodeQueue : [item];
      var sourceIndex = state.episodeIndex >= 0 ? state.episodeIndex : sourceQueue.findIndex(function (value) { return sameMedia(value, item); });
      sourceIndex = Math.max(0, sourceIndex);
      queue = sourceQueue.slice(sourceIndex, sourceIndex + 24).map(compactQueueItem);
      if (!queue.length || !sameMedia(queue[0], item)) queue.unshift(compactQueueItem(item));
      queueIndex = 0;
    }
    var entry = {
      schema: 1,
      key: key,
      item: cleanStoredItem(item),
      parent: parent ? cleanStoredItem(parent) : null,
      queue: queue,
      index: queueIndex,
      position: position,
      duration: duration,
      updatedAt: Date.now()
    };
    entries = entries.filter(function (value) { return value.key !== key; });
    entries.unshift(entry);
    writeContinueWatching(entries);
    refreshContinueWatchingRow();
  }

  function continueWatchingItems() {
    return readContinueWatching().map(function (entry) {
      var item;
      if (isEpisode(entry.item)) {
        item = Object.assign({}, entry.parent || entry.item, {contentType: 'tvshow'});
        item._cwResumeItem = entry.item;
      } else item = Object.assign({}, entry.item);
      item._cwEntry = entry;
      item._cwProgress = entry.duration > 0 ? Math.min(100, entry.position / entry.duration * 100) : 0;
      return item;
    });
  }

  function withContinueWatching(rows) {
    var base = (rows || []).filter(function (row) { return row.id !== 'continue_watching'; });
    var items = continueWatchingItems();
    return items.length ? [{id: 'continue_watching', title: 'Continua a guardare', items: items}].concat(base) : base;
  }

  function refreshContinueWatchingRow() {
    state.home = withContinueWatching(state.home);
    if (state.page === 'home' && !state.playerOpen) renderPage(true);
  }

  function saveItem(item) {
    var id = 'item-' + (++state.itemSeq);
    state.items[id] = item;
    return id;
  }

  function resetItems() {
    state.items = {};
    state.itemSeq = 0;
  }

  function request(path, body) {
    if (window.PrippiStandalone) return window.PrippiStandalone.request(path, body);
    return Promise.reject(new Error('Motore standalone non disponibile'));
  }

  function closest(element, selector) {
    while (element && element.nodeType === 1) {
      var matcher = element.matches || element.msMatchesSelector || element.webkitMatchesSelector;
      if (matcher && matcher.call(element, selector)) return element;
      element = element.parentElement;
    }
    return null;
  }

  function toast(message, error) {
    var element = document.getElementById('toast');
    clearTimeout(state.toastTimer);
    element.textContent = message;
    element.className = error ? 'toast show error' : 'toast show';
    state.toastTimer = setTimeout(function () { element.className = 'toast'; }, error ? 5200 : 3200);
  }

  function status(ok, text) {
    var element = document.getElementById('connection');
    element.innerHTML = '<span></span>' + esc(text);
    element.className = ok ? 'connection ok' : 'connection';
  }

  function loadingMarkup(titleText, bodyText) {
    return '<div class="loading-state"><div class="state-panel"><div class="spinner"></div><h2>' +
      esc(titleText) + '</h2><p>' + esc(bodyText || 'Ancora un momento...') + '</p></div></div>';
  }

  function emptyMarkup(titleText, bodyText, icon) {
    return '<div class="empty-state"><div class="state-panel"><div class="state-icon">' +
      esc(icon || '!') + '</div><h2>' + esc(titleText) + '</h2><p>' + esc(bodyText) + '</p></div></div>';
  }

  function errorMarkup(message, retry) {
    return '<div class="error-state"><div class="state-panel"><div class="state-icon">!</div>' +
      '<h2>Qualcosa non ha funzionato</h2><p>' + esc(message || 'Riprova tra poco.') + '</p>' +
      (retry ? '<button class="state-action" data-retry="' + esc(retry) + '" data-focusable data-zone="state" data-focus-key="retry:' + esc(retry) + '">Riprova</button>' : '') +
      '</div></div>';
  }

  function cardMarkup(item, options) {
    options = options || {};
    var id = saveItem(item), live = !!options.live, episode = isEpisode(item), classes = 'card';
    if (live) classes += ' live';
    if (episode) classes += ' episode';
    var meta = live ? (item.epg || item.program || 'In diretta') : itemNote(item);
    var badge = options.badge ? '<span class="card-badge">' + esc(options.badge) + '</span>' : '';
    var progress = Number(item._cwProgress || 0);
    var progressMarkup = progress > 0 ? '<span class="card-progress"><i style="width:' + Math.min(100, progress) + '%"></i></span>' : '';
    return '<button class="' + classes + '" data-item="' + id + '" data-focusable data-zone="' +
      esc(options.zone || 'row') + '" data-row="' + Number(options.row || 0) + '" data-col="' +
      Number(options.col || 0) + '" data-grid-index="' + Number(options.gridIndex == null ? -1 : options.gridIndex) +
      '" data-action="' + esc(options.action || 'detail') + '" data-focus-key="' + esc(options.focusKey || id) + '">' +
      badge + '<span class="poster" data-image="' + esc(image(item)) + '"></span>' + progressMarkup +
      '<span class="card-copy"><span class="card-title">' + esc(title(item)) + '</span>' +
      '<span class="card-meta">' + esc(meta) + '</span></span></button>';
  }

  function rowMarkup(row, rowIndex, live) {
    var items = row.items || [];
    return '<section class="row" data-row-section="' + rowIndex + '"><div class="row-header"><h2>' +
      esc(row.title || 'PrippiStream') + '</h2><span class="row-count">' + items.length + '</span></div>' +
      '<div class="cards">' + items.map(function (item, column) {
        return cardMarkup(item, {
          live: live || item.isLive,
          zone: 'row',
          row: rowIndex,
          col: column,
          focusKey: state.page + ':' + (row.id || row.title || rowIndex) + ':' + column
        });
      }).join('') + '</div></section>';
  }

  function rowsMarkup(rows, live, startIndex) {
    return (rows || []).map(function (row, index) { return rowMarkup(row, (startIndex || 0) + index, live); }).join('');
  }

  function hydratePosters(root) {
    var queue = Array.prototype.slice.call((root || document).querySelectorAll('.poster[data-image]')).map(function (element) {
      var url = element.getAttribute('data-image');
      element.removeAttribute('data-image');
      return {element: element, url: url};
    });
    function next() {
      queue.splice(0, 8).forEach(function (job) {
        if (!job.url) { job.element.className += ' no-image'; return; }
        var probe = new Image();
        probe.onload = function () {
          job.element.style.backgroundImage = 'url("' + job.url.replace(/["\\]/g, '\\$&') + '")';
        };
        probe.onerror = function () { job.element.className += ' no-image'; };
        probe.src = job.url;
      });
      if (queue.length) setTimeout(next, 90);
    }
    next();
  }

  function setHeroImage(element, url) {
    if (!element || !url) return;
    var probe = new Image();
    probe.onload = function () { element.style.backgroundImage = 'url("' + url.replace(/["\\]/g, '\\$&') + '")'; };
    probe.src = url;
  }

  function heroMarkup(item) {
    var id = saveItem(item);
    return '<section class="hero"><div class="hero-art" data-hero-image="' + esc(item.fanart || image(item)) + '"></div>' +
      '<div class="hero-copy"><span class="eyebrow">In evidenza</span><h2>' + esc(title(item)) + '</h2>' +
      '<p>' + esc(summary(item.plot || 'Scopri il catalogo PrippiStream.', 210)) + '</p>' +
      '<button class="hero-action" data-item="' + id + '" data-action="detail" data-focusable data-zone="hero" ' +
      'data-focus-key="home:hero">Scopri</button></div></section>';
  }

  function renderHomeMarkup() {
    var hero = state.home[0] && state.home[0].items && state.home[0].items[0];
    if (!hero) return emptyMarkup('Catalogo non disponibile', 'Controlla la connessione e riapri la Home.', 'H');
    state.renderedRows = Math.min(3, state.home.length);
    return '<div class="home-layout">' + heroMarkup(hero) + '<div id="home-scroll" class="home-scroll">' +
      rowsMarkup(state.home.slice(0, state.renderedRows), false, 0) + '<div id="home-tail"></div></div></div>';
  }

  function appendHomeRows(generation) {
    if (generation !== state.renderGeneration || state.page !== 'home') return;
    if (state.renderedRows >= state.home.length) return;
    var start = state.renderedRows, nextRows = state.home.slice(start, start + 2), tail = document.getElementById('home-tail');
    if (!tail) return;
    var holder = document.createElement('div');
    holder.innerHTML = rowsMarkup(nextRows, false, start);
    while (holder.firstChild) tail.parentNode.insertBefore(holder.firstChild, tail);
    state.renderedRows += nextRows.length;
    bindContent(tail.parentNode);
    hydratePosters(tail.parentNode);
    if (state.renderedRows < state.home.length) setTimeout(function () { appendHomeRows(generation); }, 260);
  }

  function renderSearchMarkup() {
    return '<div class="page-scroll"><div class="section-intro"><div><h2>Trova qualcosa da guardare</h2>' +
      '<p>Cerca film, serie TV e anime con il telecomando.</p></div></div>' +
      '<div class="search-box"><input id="query" data-focusable data-zone="form" data-form-index="0" ' +
      'data-focus-key="search:query" autocomplete="off" placeholder="Titolo di un film o di una serie">' +
      '<button id="search-go" class="action" data-focusable data-zone="form" data-form-index="1" ' +
      'data-focus-key="search:go">Cerca</button></div><div id="search-status" class="search-status">Scrivi almeno due caratteri.</div>' +
      '<div id="search-filters" class="browse-filters search-filters hidden"><button class="filter-chip selected" data-search-filter="all" data-focusable data-zone="filters" data-filter-index="0">Tutto</button>' +
      '<button class="filter-chip" data-search-filter="film" data-focusable data-zone="filters" data-filter-index="1">Film</button>' +
      '<button class="filter-chip" data-search-filter="serie" data-focusable data-zone="filters" data-filter-index="2">Serie TV</button>' +
      '<button class="filter-chip" data-search-filter="anime" data-focusable data-zone="filters" data-filter-index="3">Anime</button></div>' +
      '<div id="search-results" class="catalog"></div></div>';
  }

  function uniqueHomeItems() {
    var output = [], seen = {};
    state.home.forEach(function (row) {
      (row.items || []).forEach(function (item) {
        var key = item.url || title(item);
        if (!seen[key]) { seen[key] = true; output.push(item); }
      });
    });
    return output;
  }

  function browseItems(filter) {
    var items = uniqueHomeItems();
    if (filter === 'movies') items = items.filter(function (item) { return !isSeries(item); });
    if (filter === 'series') items = items.filter(isSeries);
    if (filter === 'anime') items = items.filter(function (item) { return item.searchType === 'anime' || item.source === 'animeunity'; });
    if (filter === 'raiplay' || filter === 'mediasetplay' || filter === 'la7') {
      items = items.filter(function (item) { return (item.source || item.channel) === filter; });
    }
    return items.slice(0, 180);
  }

  function renderBrowseMarkup(filter) {
    filter = filter || 'all';
    var items = browseItems(filter);
    var fallback = state.homeError ? errorMarkup(state.homeError, 'home') :
      loadingMarkup('Catalogo in caricamento', 'La sezione apparirà appena la Home sarà disponibile.');
    return '<div class="page-scroll"><div class="section-intro"><div><h2>Esplora il catalogo</h2>' +
      '<p>Una raccolta unica, organizzata per il grande schermo.</p></div></div>' +
      '<div class="browse-filters"><button class="filter-chip ' + (filter === 'all' ? 'selected' : '') + '" data-filter="all" data-focusable data-zone="filters" data-filter-index="0">Tutto</button>' +
      '<button class="filter-chip ' + (filter === 'movies' ? 'selected' : '') + '" data-filter="movies" data-focusable data-zone="filters" data-filter-index="1">Film</button>' +
      '<button class="filter-chip ' + (filter === 'series' ? 'selected' : '') + '" data-filter="series" data-focusable data-zone="filters" data-filter-index="2">Serie TV</button>' +
      '<button class="filter-chip ' + (filter === 'anime' ? 'selected' : '') + '" data-filter="anime" data-focusable data-zone="filters" data-filter-index="3">Anime</button>' +
      '<button class="filter-chip ' + (filter === 'raiplay' ? 'selected' : '') + '" data-filter="raiplay" data-focusable data-zone="filters" data-filter-index="4">RaiPlay</button>' +
      '<button class="filter-chip ' + (filter === 'mediasetplay' ? 'selected' : '') + '" data-filter="mediasetplay" data-focusable data-zone="filters" data-filter-index="5">Mediaset</button>' +
      '<button class="filter-chip ' + (filter === 'la7' ? 'selected' : '') + '" data-filter="la7" data-focusable data-zone="filters" data-filter-index="6">La7</button></div>' +
      (items.length ? '<div id="browse-grid" class="catalog">' + items.map(function (item, index) {
        return cardMarkup(item, {zone: 'grid', gridIndex: index, row: Math.floor(index / 5), col: index % 5, focusKey: 'browse:' + filter + ':' + index});
      }).join('') + '</div>' : fallback) + '</div>';
  }

  function renderLiveMarkup() {
    if (!state.live.length) return state.liveError ? errorMarkup(state.liveError, 'live') :
      loadingMarkup('Preparazione dei canali', 'La navigazione resta disponibile durante il caricamento.');
    return '<div class="page-scroll"><div class="section-intro"><div><h2>Dirette</h2><p>Canali organizzati in righe, con logo in proporzione.</p></div></div>' +
      rowsMarkup(state.live, true, 0) + '</div>';
  }

  function renderDownloadsMarkup() {
    return '<div class="page-scroll"><div class="section-intro"><div><h2>I tuoi download</h2>' +
      '<p>Contenuti disponibili senza connessione.</p></div></div>' +
      emptyMarkup('Nessun download sulla TV', 'I download effettuati sul telefono restano nell\'app Android. Il salvataggio locale sulla TV verrà mostrato qui quando lo storage Tizen sarà validato.', 'D') + '</div>';
  }

  function settingCard(id, label, description, value, toggle) {
    return '<div class="setting" ' + (toggle ? 'tabindex="-1" data-setting="' + esc(id) + '" data-focusable data-zone="settings" data-setting-index="' + toggle.index + '"' : '') + '>' +
      '<div><b>' + esc(label) + '</b><small>' + esc(description) + '</small></div>' +
      (toggle ? '<button class="setting-toggle" tabindex="-1">' + esc(value) + '</button>' : '<span class="setting-value">' + esc(value) + '</span>') + '</div>';
  }

  function renderSettingsMarkup() {
    var subtitles = localStorage.getItem('prippi.tizen.subtitles') === 'on';
    var reduced = localStorage.getItem('prippi.tizen.reduced-motion') === 'on';
    var version = document.documentElement.getAttribute('data-prippi-version') || 'bundle locale';
    return '<div class="page-scroll"><div class="section-intro"><div><h2>Preferenze TV</h2>' +
      '<p>Impostazioni semplici, pensate per telecomando e schermi condivisi.</p></div></div><div class="settings-grid">' +
      settingCard('runtime', 'Motore', 'L\'app funziona direttamente sulla TV, senza PC.', 'Standalone', null) +
      settingCard('version', 'Aggiornamenti', 'Bundle verificato tramite SHA-256.', version, null) +
      settingCard('subtitles', 'Sottotitoli automatici', 'Restano disattivati finché non li selezioni nel player.', subtitles ? 'ON' : 'OFF', {index: 0}) +
      settingCard('reduced-motion', 'Animazioni ridotte', 'Riduce transizioni e lavoro grafico sui dispositivi lenti.', reduced ? 'ON' : 'OFF', {index: 1}) +
      '</div></div>';
  }

  function renderPage(preserveFocus) {
    state.renderGeneration += 1;
    var generation = state.renderGeneration;
    resetItems();
    var titles = {home: 'Home', search: 'Cerca', browse: 'Sfoglia', live: 'Live TV', downloads: 'Download', settings: 'Impostazioni'};
    document.getElementById('page-title').textContent = titles[state.page] || 'PrippiStream';
    Array.prototype.forEach.call(document.querySelectorAll('[data-nav]'), function (element) {
      var settings = element.getAttribute('data-nav') === 'settings';
      var active = element.getAttribute('data-nav') === state.page;
      element.className = (settings ? 'rail-settings' : '') + (active ? (settings ? ' active' : 'active') : '');
    });
    var content = document.getElementById('content');
    if (state.page === 'home') content.innerHTML = state.home.length ? renderHomeMarkup() :
      (state.homeError ? errorMarkup(state.homeError, 'home') : loadingMarkup('Caricamento Home', 'Le prime righe saranno disponibili appena pronte.'));
    if (state.page === 'search') content.innerHTML = renderSearchMarkup();
    if (state.page === 'browse') content.innerHTML = renderBrowseMarkup('all');
    if (state.page === 'live') content.innerHTML = renderLiveMarkup();
    if (state.page === 'downloads') content.innerHTML = renderDownloadsMarkup();
    if (state.page === 'settings') content.innerHTML = renderSettingsMarkup();
    bindContent(content);
    hydratePosters(content);
    Array.prototype.forEach.call(content.querySelectorAll('[data-hero-image]'), function (element) {
      setHeroImage(element, element.getAttribute('data-hero-image'));
      element.removeAttribute('data-hero-image');
    });
    if (state.page === 'home' && state.home.length) setTimeout(function () { appendHomeRows(generation); }, 220);
    if (state.page === 'search') bindSearch();
    if (state.page === 'browse') bindBrowseFilters();
    if (state.page === 'settings') bindSettings();
    setTimeout(function () { restoreFocus(preserveFocus); }, 0);
  }

  function cachedHome() {
    try {
      var data = JSON.parse(localStorage.getItem(HOME_CACHE) || 'null');
      return data && data.rows && data.rows.length ? data : null;
    } catch (error) { return null; }
  }

  function saveHome(rows) {
    var catalog = (rows || []).filter(function (row) { return row.id !== 'continue_watching'; });
    try { localStorage.setItem(HOME_CACHE, JSON.stringify({time: Date.now(), rows: catalog.slice(0, 30)})); } catch (error) {}
  }

  function acceptHome(rows, message) {
    if (!rows || !rows.length) return;
    state.homeLoading = false;
    state.homeError = '';
    state.home = withContinueWatching(rows);
    saveHome(rows);
    if (state.page === 'home' || state.page === 'browse') renderPage(true);
    status(true, message || 'Home pronta');
  }

  function loadHome() {
    var cache = cachedHome();
    state.homeLoading = true;
    state.homeError = '';
    if (!state.home.length && cache) {
      state.home = withContinueWatching(cache.rows);
      renderPage(true);
      status(true, 'Home pronta');
    }
    request('/home').then(function (response) {
      var rows = response.rows || [];
      if (!rows.length) throw new Error('Il catalogo non contiene righe');
      acceptHome(rows, response.cached ? 'Home dalla cache' : response.fallback ? 'Catalogo disponibile' : 'Connesso');
      pollExpandedHome(0);
    }).catch(function (error) {
      state.homeLoading = false;
      state.homeError = error.message || 'Catalogo non disponibile';
      status(false, 'Connessione da verificare');
      if (!state.home.length && (state.page === 'home' || state.page === 'browse')) renderPage(true);
    });
  }

  function pollExpandedHome(attempt) {
    request('/home-expanded').then(function (expanded) {
      var rows = expanded.rows || [];
      if (rows.length && rows.length !== catalogHomeCount()) {
        acceptHome(rows, expanded.expanding ? 'Nuove righe disponibili' : 'Catalogo completo');
      }
      if (expanded.expanding && attempt < 80) {
        setTimeout(function () { pollExpandedHome(attempt + 1); }, 900);
      }
    }).catch(function () {});
  }

  function catalogHomeCount() {
    return state.home.filter(function (row) { return row.id !== 'continue_watching'; }).length;
  }

  function loadLive() {
    state.liveLoading = true;
    state.liveError = '';
    request('/live').then(function (response) {
      state.liveLoading = false;
      state.live = (response.rows || []).map(function (row) {
        var normalized = Object.assign({}, row);
        normalized.items = (row.items || []).map(function (item) { return Object.assign({}, item, {isLive: true}); });
        return normalized;
      });
      state.liveError = '';
      renderPage(true);
      status(true, 'Canali aggiornati');
      request('/live-epg', {rows: state.live}).then(function (epgResponse) {
        if (!epgResponse || !epgResponse.rows) return;
        state.live = epgResponse.rows;
        if (state.page === 'live') renderPage(true);
      }).catch(function () {});
    }).catch(function (error) {
      state.liveLoading = false;
      state.liveError = error.message || 'Canali non disponibili';
      if (state.page === 'live') renderPage(true);
      toast('Live non disponibile: ' + error.message, true);
    });
  }

  function openPage(page) {
    if (!page) return;
    state.focusMemory[state.page] = currentFocusKey();
    state.page = page;
    renderPage(false);
    if (page === 'home') loadHome();
    if (page === 'live') loadLive();
    if (page === 'browse' && !state.home.length) loadHome();
  }

  function bindSearch() {
    var input = document.getElementById('query'), button = document.getElementById('search-go');
    if (!input || !button) return;
    button.onclick = runSearch;
    input.onkeydown = function (event) { if (event.keyCode === 13) runSearch(); };
  }

  function runSearch() {
    var input = document.getElementById('query'), query = input ? input.value.replace(/^\s+|\s+$/g, '') : '';
    var statusElement = document.getElementById('search-status'), results = document.getElementById('search-results');
    if (query.length < 2) { toast('Inserisci almeno due caratteri'); if (input) input.focus(); return; }
    statusElement.textContent = 'Ricerca in corso...';
    results.innerHTML = '';
    request('/search?q=' + encodeURIComponent(query)).then(function (response) {
      var items = response.items || [];
      if (!items.length) {
        statusElement.textContent = 'Nessun risultato per "' + query + '".';
        results.innerHTML = emptyMarkup('Nessun risultato', 'Prova un titolo diverso.', '?');
        return;
      }
      state.searchItems = items;
      state.searchQuery = query;
      state.searchFilter = 'all';
      updateSearchResults('all');
      var first = results.querySelector('[data-focusable]');
      if (first) focusElement(first);
    }).catch(function (error) {
      statusElement.textContent = 'Ricerca non riuscita.';
      results.innerHTML = errorMarkup(error.message);
      toast('Ricerca non disponibile: ' + error.message, true);
    });
  }

  function searchKind(item) {
    if (item.searchType) return item.searchType;
    return isSeries(item) ? 'serie' : 'film';
  }

  function updateSearchResults(filter) {
    var results = document.getElementById('search-results'), filters = document.getElementById('search-filters');
    var statusElement = document.getElementById('search-status');
    if (!results || !filters) return;
    state.searchFilter = filter || 'all';
    filters.className = 'browse-filters search-filters';
    Array.prototype.forEach.call(filters.querySelectorAll('[data-search-filter]'), function (button) {
      button.className = 'filter-chip' + (button.getAttribute('data-search-filter') === state.searchFilter ? ' selected' : '');
    });
    var items = state.searchFilter === 'all' ? state.searchItems : state.searchItems.filter(function (item) {
      return searchKind(item) === state.searchFilter;
    });
    statusElement.textContent = items.length + ' risultati per "' + state.searchQuery + '"';
    results.innerHTML = items.map(function (item, index) {
      return cardMarkup(item, {zone: 'grid', gridIndex: index, row: Math.floor(index / 5), col: index % 5,
        focusKey: 'search:' + state.searchQuery + ':' + state.searchFilter + ':' + index});
    }).join('') || emptyMarkup('Nessun risultato', 'Nessun contenuto in questa categoria.', '?');
    bindContent(results);
    hydratePosters(results);
    bindSearchFilters();
  }

  function bindSearchFilters() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-search-filter]'), function (button) {
      button.onclick = function () {
        var filter = button.getAttribute('data-search-filter');
        updateSearchResults(filter);
        var selected = document.querySelector('[data-search-filter="' + filter + '"]');
        if (selected) focusElement(selected);
      };
    });
  }

  function bindBrowseFilters() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-filter]'), function (button) {
      button.onclick = function () {
        var filter = button.getAttribute('data-filter');
        document.getElementById('content').innerHTML = renderBrowseMarkup(filter);
        bindContent(document.getElementById('content'));
        bindBrowseFilters();
        hydratePosters(document.getElementById('content'));
        var selected = document.querySelector('[data-filter="' + filter + '"]');
        if (selected) focusElement(selected);
      };
    });
  }

  function bindSettings() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-setting]'), function (element) {
      element.onclick = function () {
        var key = element.getAttribute('data-setting'), storageKey = 'prippi.tizen.' + key;
        localStorage.setItem(storageKey, localStorage.getItem(storageKey) === 'on' ? 'off' : 'on');
        state.focusMemory.settings = 'setting:' + key;
        renderPage(true);
        toast('Preferenza aggiornata');
      };
      element.setAttribute('data-focus-key', 'setting:' + element.getAttribute('data-setting'));
    });
  }

  function bindContent(root) {
    root = root || document;
    Array.prototype.forEach.call(root.querySelectorAll('[data-retry]'), function (element) {
      if (element.getAttribute('data-bound') === '1') return;
      element.setAttribute('data-bound', '1');
      element.onclick = function () {
        var retry = element.getAttribute('data-retry');
        if (retry === 'home') loadHome();
        if (retry === 'live') loadLive();
      };
    });
    Array.prototype.forEach.call(root.querySelectorAll('[data-item]'), function (element) {
      if (element.getAttribute('data-bound') === '1') return;
      element.setAttribute('data-bound', '1');
      element.onclick = function () {
        var item = state.items[element.getAttribute('data-item')];
        if (!item) return;
        if (element.getAttribute('data-action') === 'play') play(item);
        else showDetail(item);
      };
      element.onfocus = function () {
        rememberFocus(element);
        if (state.page === 'home') updateHero(state.items[element.getAttribute('data-item')]);
      };
    });
  }

  function updateHero(item) {
    if (!item) return;
    var hero = document.querySelector('.hero'), art = document.querySelector('.hero-art');
    if (!hero || !art) return;
    var heading = hero.querySelector('h2'), paragraph = hero.querySelector('p'), action = hero.querySelector('.hero-action');
    if (heading) heading.textContent = title(item);
    if (paragraph) paragraph.textContent = summary(item.plot || 'Scopri il catalogo PrippiStream.', 210);
    setHeroImage(art, item.fanart || image(item));
    if (action) {
      var id = saveItem(item);
      action.setAttribute('data-item', id);
      action.onclick = function () { showDetail(item); };
    }
  }

  function detailMeta(item) {
    var labels = info(item), values = [];
    if (labels.year || item.year) values.push(labels.year || item.year);
    if (labels.rating) values.push('Valutazione ' + Number(labels.rating).toFixed(1));
    if (labels.runtime) values.push(labels.runtime + ' min');
    if (labels.genre) values.push(labels.genre);
    if (!values.length) values.push(isSeries(item) ? 'Serie TV' : isEpisode(item) ? 'Episodio' : item.isLive ? 'Live' : 'Film');
    return values.map(function (value) { return '<span class="detail-chip">' + esc(value) + '</span>'; }).join('');
  }

  function showDetail(item) {
    state.detailOrigin = currentFocusKey();
    state.detail = item;
    state.detailParent = null;
    renderDetail(item);
    request('/detail', {item: item}).then(function (updated) {
      state.detail = updated;
      var paragraph = document.querySelector('#detail .detail-body p');
      if (paragraph) paragraph.textContent = updated.plot || item.plot || 'Nessuna trama disponibile.';
      var art = document.getElementById('detail');
      if (updated.fanart) art.style.backgroundImage = 'url("' + updated.fanart.replace(/["\\]/g, '\\$&') + '")';
    }).catch(function () {});
  }

  function renderDetail(item) {
    var series = isSeries(item), live = !!item.isLive, cw = item._cwEntry || (!live && findContinueWatching(item, series ? item : null));
    var hasResume = !!(cw && cw.position >= CW_MIN_PROGRESS_MS);
    var resumeItem = series && cw ? Object.assign({}, item, {_cwEntry: cw, _cwResumeItem: cw.item}) :
      cw ? Object.assign({}, item, {_cwEntry: cw}) : item;
    var actions = [], actionIndex = 0, overlay = document.getElementById('detail');
    if (hasResume) actions.push('<button id="detail-resume" class="play" data-focusable data-zone="detail" data-detail-index="' + (actionIndex++) + '">Riprendi</button>');
    if (series) actions.push('<button id="detail-episodes"' + (!hasResume ? ' class="play"' : '') + ' data-focusable data-zone="detail" data-detail-index="' + (actionIndex++) + '">Episodi</button>');
    else actions.push('<button id="detail-primary"' + (!hasResume ? ' class="play"' : '') + ' data-focusable data-zone="detail" data-detail-index="' + (actionIndex++) + '">' + (hasResume ? 'Dall\'inizio' : 'Riproduci') + '</button>');
    if (!live) actions.push('<button id="detail-trailer" data-focusable data-zone="detail" data-detail-index="' + (actionIndex++) + '">Trailer</button>');
    if (cw) actions.push('<button id="detail-remove-cw" data-focusable data-zone="detail" data-detail-index="' + (actionIndex++) + '">Rimuovi da Continua a guardare</button>');
    actions.push('<button id="detail-close" data-focusable data-zone="detail" data-detail-index="' + actionIndex + '">Indietro</button>');
    state.detailParent = null;
    overlay.className = 'overlay';
    overlay.style.backgroundImage = item.fanart ? 'url("' + item.fanart.replace(/["\\]/g, '\\$&') + '")' : '';
    overlay.innerHTML = '<div class="detail-layout"><div class="detail-poster" style="background-image:url(\'' + esc(image(item)) + '\')"></div>' +
      '<div class="detail-body"><span class="eyebrow">' + esc(series ? 'Serie TV' : item.isLive ? 'Canale Live' : 'PrippiStream') + '</span>' +
      '<h2>' + esc(title(item)) + '</h2><div class="detail-meta">' + detailMeta(item) + '</div>' +
      '<p>' + esc(item.plot || 'Caricamento informazioni...') + '</p><div class="actions">' +
      actions.join('') + '</div></div></div>';
    if (hasResume) document.getElementById('detail-resume').onclick = function () { play(resumeItem, {resume: true}); };
    if (series) document.getElementById('detail-episodes').onclick = function () { showEpisodes(item); };
    else document.getElementById('detail-primary').onclick = function () { play(item, {fromStart: hasResume}); };
    if (!live) document.getElementById('detail-trailer').onclick = function () { toast('Trailer non ancora disponibile per questo contenuto.'); };
    if (cw) document.getElementById('detail-remove-cw').onclick = function () {
      removeContinueWatching(cw.item || item._cwResumeItem || item, cw.parent || (series ? item : null));
      closeDetail();
      toast('Rimosso da Continua a guardare');
    };
    document.getElementById('detail-close').onclick = closeDetail;
    focusElement(document.getElementById(hasResume ? 'detail-resume' : series ? 'detail-episodes' : 'detail-primary'));
  }

  function showEpisodes(item) {
    var overlay = document.getElementById('detail');
    state.detailParent = item;
    overlay.style.backgroundImage = '';
    overlay.innerHTML = '<div class="episodes-layout"><div class="episodes-header"><div class="episodes-titlebar">' +
      '<button id="episodes-back" class="episodes-back" data-focusable data-zone="episodes-header" data-focus-key="episodes:back">&#8592;</button>' +
      '<div><span class="eyebrow">Serie TV</span><h2>' + esc(title(item)) + '</h2></div></div>' +
      '<div id="season-picker" class="season-picker"></div></div><div id="episode-content">' +
      loadingMarkup('Caricamento episodi', 'Le stagioni saranno disponibili appena pronte.') + '</div></div>';
    document.getElementById('episodes-back').onclick = function () { renderDetail(item); };
    focusElement(document.getElementById('episodes-back'));
    request('/episodes', {item: item}).then(function (response) {
      var episodes = response.items || response.episodes || [];
      if (!episodes.length) throw new Error('Nessun episodio disponibile');
      var seasons = [], seen = {};
      episodes.forEach(function (episode) {
        var season = Number(episode.season || episode.contentSeason || (episode.infoLabels || {}).season || 1) || 1;
        episode._displaySeason = season;
        if (!seen[season]) { seen[season] = true; seasons.push(season); }
      });
      episodes.sort(function (a, b) {
        return a._displaySeason - b._displaySeason || Number(a.episode || a.contentEpisodeNumber || 0) - Number(b.episode || b.contentEpisodeNumber || 0);
      });
      state.episodeParent = item;
      state.episodeQueue = episodes.slice();
      state.episodeIndex = -1;
      seasons.sort(function (a, b) { return a - b; });
      renderEpisodeSeason(item, episodes, seasons, seasons[0]);
    }).catch(function (error) {
      var content = document.getElementById('episode-content');
      if (content) content.innerHTML = errorMarkup(error.message);
    });
  }

  function episodeTitleText(episode) {
    var labels = info(episode), number = Number(episode.episode || episode.contentEpisodeNumber || labels.episode || 0);
    var raw = String(episode.episodeTitle || episode.name || labels.episode_title || labels.title || episode.title || '').trim();
    var seriesName = String(episode.contentSerieName || episode.show || '').trim();
    if (seriesName && raw.toLowerCase().indexOf(seriesName.toLowerCase()) === 0) raw = raw.slice(seriesName.length).trim();
    raw = raw.replace(/^\s*(?:s?\d+\s*[xe]\s*\d+|\d+x\d+)\s*[-.:\u2014]?\s*/i, '').trim();
    return (number ? number + '. ' : '') + (raw || ('Episodio ' + number));
  }

  function episodeRowMarkup(episode, index) {
    var id = saveItem(episode), labels = info(episode);
    var number = Number(episode.episode || episode.contentEpisodeNumber || labels.episode || index + 1);
    var plot = episode.plot || labels.plot || 'Nessuna trama disponibile.';
    var cw = findContinueWatching(episode, state.episodeParent), progress = cw && sameMedia(cw.item, episode) && cw.duration > 0 ? Math.min(100, cw.position / cw.duration * 100) : 0;
    return '<button class="episode-row" data-item="' + id + '" data-action="play" data-focusable data-zone="episodes" ' +
      'data-grid-index="' + index + '" data-focus-key="episode:' + episode._displaySeason + ':' + number + '">' +
      '<span class="episode-number">' + number + '</span><span class="episode-thumb poster" data-image="' + esc(image(episode)) + '"></span>' +
      '<span class="episode-copy"><b>' + esc(episodeTitleText(episode)) + '</b><small>' + esc(summary(plot, 190)) + '</small></span>' +
      '<span class="episode-play">&#9654;</span>' + (progress ? '<span class="episode-progress"><i style="width:' + progress + '%"></i></span>' : '') + '</button>';
  }

  function renderEpisodeSeason(parent, episodes, seasons, selectedSeason) {
    var picker = document.getElementById('season-picker'), content = document.getElementById('episode-content');
    if (!picker || !content) return;
    picker.innerHTML = seasons.map(function (season, index) {
      return '<button class="filter-chip' + (season === selectedSeason ? ' selected' : '') + '" data-season="' + season +
        '" data-focusable data-zone="episode-seasons" data-filter-index="' + index + '" data-focus-key="season:' + season + '">Stagione ' + season + '</button>';
    }).join('');
    var visible = episodes.filter(function (episode) { return episode._displaySeason === selectedSeason; });
    content.innerHTML = '<div class="episode-list">' + visible.map(episodeRowMarkup).join('') + '</div>';
    Array.prototype.forEach.call(picker.querySelectorAll('[data-season]'), function (button) {
      button.onclick = function () {
        var season = Number(button.getAttribute('data-season'));
        renderEpisodeSeason(parent, episodes, seasons, season);
        var selected = document.querySelector('[data-season="' + season + '"]');
        if (selected) focusElement(selected);
      };
    });
    bindContent(content);
    hydratePosters(content);
  }

  function closeDetail() {
    var overlay = document.getElementById('detail');
    overlay.className = 'overlay hidden';
    overlay.removeAttribute('style');
    overlay.innerHTML = '';
    state.detail = null;
    state.detailParent = null;
    setTimeout(function () { restoreFocusByKey(state.detailOrigin); }, 0);
  }

  function findUrl(data) {
    if (typeof data === 'string' && /^https?:/.test(data)) return data;
    if (!data || typeof data !== 'object') return '';
    var keys = ['url', 'media_url', 'stream_url', 'manifest_url', 'playback_url'], index;
    for (index = 0; index < keys.length; index += 1) if (typeof data[keys[index]] === 'string' && /^https?:/.test(data[keys[index]])) return data[keys[index]];
    if (Array.isArray(data)) for (index = 0; index < data.length; index += 1) { var nested = findUrl(data[index]); if (nested) return nested; }
    return '';
  }

  function isNativeMedia(url, manifest) {
    return /^(hls|mpd|dash|progressive)$/i.test(manifest || '') || /\.(m3u8|mpd|mp4|m4s|ts)(\?|$)/i.test(url || '');
  }

  function isEmulatorRuntime() {
    var nav = window.navigator || {};
    var signature = String(nav.userAgent || '') + ' ' + String(nav.platform || '');
    if (/emulator|x86_64|\bx86\b/i.test(signature)) return true;
    try {
      var arch = window.tizen && tizen.systeminfo && tizen.systeminfo.getCapability(
        'http://tizen.org/feature/platform.core.cpu.arch'
      );
      return /x86/i.test(String(arch || ''));
    } catch (error) { return false; }
  }

  function isHtmlPlayerEngine() {
    return state.playerEngine === 'html' || state.playerEngine === 'hlsjs' || state.playerEngine === 'shaka';
  }

  function liveIdentity(item) {
    return String(item && (item.sport_par || item.callSign || item.video_url || item.url || title(item)) || '').toLowerCase();
  }

  function prepareLiveSession(item) {
    var identity = liveIdentity(item), found = null;
    state.live.some(function (row) {
      var index = (row.items || []).findIndex(function (candidate) { return liveIdentity(candidate) === identity; });
      if (index < 0) return false;
      found = {row: row, index: index};
      return true;
    });
    state.liveQueue = found ? found.row.items.slice() : [item];
    state.liveIndex = found ? found.index : 0;
    state.liveRowTitle = found ? found.row.title : 'Live TV';
  }

  function play(item, options) {
    options = options || {};
    var entry = item._cwEntry || null, target = item._cwResumeItem || item, requestId = ++state.playRequestId;
    if (target.isLive && !options.switchingLive) prepareLiveSession(target);
    if (entry && item._cwResumeItem) {
      state.episodeParent = entry.parent || item;
      state.episodeQueue = entry.queue || [];
      state.episodeIndex = Number(entry.index == null ? -1 : entry.index);
    } else if (isEpisode(target)) {
      state.episodeIndex = state.episodeQueue.findIndex(function (candidate) { return sameMedia(candidate, target); });
    } else {
      state.episodeQueue = [];
      state.episodeIndex = -1;
      state.episodeParent = null;
    }
    var saved = entry || findContinueWatching(target, state.episodeParent);
    state.pendingResumeMs = !options.fromStart && saved && sameMedia(saved.item, target) ? Number(saved.position || 0) : 0;
    state.playerItem = target;
    state.switchingEpisode = !!options.switching;
    if (!options.switching && !options.switchingLive) toast('Ricerca della sorgente migliore...');
    else setPlayerText(playbackTitle(target), 'Preparazione episodio successivo...');
    if (options.switchingLive) setPlayerText(playbackTitle(target), 'Cambio canale...');
    return request('/resolve', {item: target}).then(function (response) {
      if (requestId !== state.playRequestId) throw {stale: true};
      var url = findUrl(response);
      if (!url) throw new Error('Nessuno stream compatibile restituito');
      if (String(response.drm_type || '').toLowerCase() === 'clearkey') return openClearKeyPlayer(url, target, response);
      if (isNativeMedia(url, response.manifest_type)) openPlayer(url, target, response.headers || {}, response.manifest_type || '');
      else openEmbed(url, target);
      return null;
    }).then(function () {
      if (requestId === state.playRequestId) state.liveSwitchBusy = false;
    }).catch(function (error) {
      if (requestId !== state.playRequestId || (error && error.stale)) return;
      state.switchingEpisode = false;
      state.liveSwitchBusy = false;
      if (options.switchingLive && state.liveQueue.length > 1 && Number(options.liveAttempts || 0) < state.liveQueue.length - 1) {
        switchLive(Number(options.liveDirection || 1), Number(options.liveAttempts || 0) + 1, true);
        return;
      }
      toast('Riproduzione non disponibile: ' + error.message, true);
      if (state.playerOpen) { setPlayerText(playbackTitle(target), target.isLive ? 'Canale non disponibile' : 'Episodio non disponibile'); showPlayerUi(true); }
    });
  }

  function playbackTitle(item) {
    if (!isEpisode(item)) return title(item);
    var parent = item.contentSerieName || item.show || (state.episodeParent && title(state.episodeParent)) || '';
    return (parent ? parent + '  -  ' : '') + episodeTitleText(item);
  }

  function openPlayerShell(item) {
    clearTimeout(state.episodeTransitionTimer);
    state.episodeTransitionTimer = null;
    stopPlayerMedia();
    var detail = document.getElementById('detail');
    if (detail && detail.className.indexOf('hidden') < 0) closeDetail();
    state.playerOpen = true;
    state.playerLive = !!item.isLive;
    state.playing = false;
    var player = document.getElementById('player');
    player.className = state.playerLive ? 'player live' : 'player';
    document.getElementById('player-kind').textContent = state.playerLive ? 'IN DIRETTA' : 'PRIPPISTREAM';
    document.getElementById('player-rewind').disabled = state.playerLive;
    document.getElementById('player-forward').disabled = state.playerLive;
    state.playerItem = item;
    state.lastProgressSave = 0;
    state.upNextVisible = false;
    state.upNextCancelled = false;
    state.episodeTransitionScheduled = false;
    hideUpNext(false);
    setPlayerText(playbackTitle(item), 'Connessione...');
    setPlayerProgress(0, 0, 0);
    showPlayerUi(true);
  }

  function openEmbed(url, item) {
    openPlayerShell(item);
    state.playerEngine = 'embed';
    var player = document.getElementById('player'), old = document.getElementById('embed-player');
    if (old) old.parentNode.removeChild(old);
    var frame = document.createElement('iframe');
    frame.id = 'embed-player';
    frame.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;border:0;background:#000;z-index:1';
    frame.src = url;
    frame.setAttribute('allowfullscreen', '');
    frame.onload = function () { state.playing = true; setPlayerText(playbackTitle(item), 'Player del provider'); showPlayerUi(true); };
    player.insertBefore(frame, document.getElementById('avplay'));
  }

  function openPlayer(url, item, headers, manifest) {
    openPlayerShell(item);
    var video = document.getElementById('html-player'), surface = document.getElementById('avplay');
    var htmlPreferred = /^(hls|progressive)$/i.test(manifest || '') || /\.m3u8(\?|$)/i.test(url || '');
    var hls = /^hls$/i.test(manifest || '') || /\.m3u8(\?|$)/i.test(url || '');
    var hasHeaders = headers && Object.keys(headers).length > 0;
    state.htmlFallback = false;
    if (hls && (isEmulatorRuntime() || hasHeaders) && window.Hls && Hls.isSupported()) {
      openHlsJs(url, item, headers || {});
      return;
    }
    if (htmlPreferred) {
      state.playerEngine = 'html';
      surface.style.display = 'none';
      video.style.display = 'block';
      video.src = url;
      video.onwaiting = function () { setPlayerText(playbackTitle(item), 'Buffering...'); showPlayerUi(false); };
      video.onplaying = function () { state.playing = true; state.switchingEpisode = false; setPlayerText(playbackTitle(item), state.playerLive ? 'In diretta' : 'Riproduzione'); startTimeline(); showPlayerUi(false); };
      video.oncanplay = function () { applyHtmlResume(video); video.play(); };
      video.onended = handlePlaybackCompleted;
      video.onerror = function () {
        if (state.htmlFallback) return;
        state.htmlFallback = true;
        video.pause(); video.removeAttribute('src'); video.load();
        if (hls && isEmulatorRuntime()) {
          setPlayerText(playbackTitle(item), 'HLS non supportato dal player HTML dell\'emulatore');
          showPlayerUi(true);
          return;
        }
        openAvPlayer(url, item, headers || {});
      };
      video.load();
    } else openAvPlayer(url, item, headers || {});
  }

  function clearKeyPair(response) {
    var pair = String(response.license_key || '').split(':');
    var kid = String(response.kid || pair[0] || '').replace(/[^0-9a-f]/ig, '').toLowerCase();
    var key = String(response.key || pair[1] || '').replace(/[^0-9a-f]/ig, '').toLowerCase();
    return kid.length === 32 && key.length === 32 ? {kid: kid, key: key} : null;
  }

  function openClearKeyPlayer(url, item, response) {
    if (isEmulatorRuntime()) {
      return Promise.reject(new Error('ClearKey va verificato sulla TV Samsung reale; la sessione DRM chiude l\'emulatore'));
    }
    if (!window.shaka || !window.shaka.Player) return Promise.reject(new Error('Runtime DASH/ClearKey non disponibile'));
    var pair = clearKeyPair(response);
    if (!pair) return Promise.reject(new Error('Chiave ClearKey non valida'));
    try { window.shaka.polyfill.installAll(); } catch (error) {}
    if (!window.shaka.Player.isBrowserSupported()) return Promise.reject(new Error('DASH/MSE non supportato dal televisore'));
    openPlayerShell(item);
    var video = document.getElementById('html-player'), surface = document.getElementById('avplay');
    state.playerEngine = 'shaka';
    surface.style.display = 'none';
    video.style.display = 'block';
    video.onwaiting = function () { setPlayerText(playbackTitle(item), 'Buffering...'); showPlayerUi(false); };
    video.onplaying = function () {
      state.playing = true;
      setPlayerText(playbackTitle(item), 'In diretta');
      startTimeline();
      showPlayerUi(false);
    };
    video.onerror = function () { setPlayerText(playbackTitle(item), 'Errore decoder ClearKey'); showPlayerUi(true); };
    var player = new window.shaka.Player(video), clearKeys = {};
    clearKeys[pair.kid] = pair.key;
    state.shakaInstance = player;
    player.configure({
      drm: {clearKeys: clearKeys},
      preferredAudioLanguage: 'it',
      streaming: {bufferingGoal: 18, rebufferingGoal: 3, bufferBehind: 12}
    });
    var networking = player.getNetworkingEngine && player.getNetworkingEngine();
    if (networking && response.headers) {
      networking.registerRequestFilter(function (type, request) {
        Object.keys(response.headers).forEach(function (name) {
          if (!/^(?:user-agent|referer|origin)$/i.test(name)) request.headers[name] = response.headers[name];
        });
      });
    }
    player.addEventListener('error', function (event) {
      var detail = event && event.detail;
      setPlayerText(playbackTitle(item), 'Errore DASH/DRM' + (detail && detail.code ? ' (' + detail.code + ')' : ''));
      showPlayerUi(true);
    });
    setPlayerText(playbackTitle(item), 'Preparazione DASH/ClearKey...');
    return player.load(url).then(function () {
      var started = video.play();
      return started && started.then ? started : Promise.resolve();
    }).catch(function (error) {
      var detail = error && error.detail;
      throw new Error(detail && detail.code ? 'DASH/DRM ' + detail.code : error.message || 'DASH/DRM non riproducibile');
    });
  }

  function openHlsJs(url, item, headers) {
    var video = document.getElementById('html-player'), surface = document.getElementById('avplay');
    state.playerEngine = 'hlsjs';
    state.hlsFatalRetries = 0;
    surface.style.display = 'none';
    video.style.display = 'block';
    video.onwaiting = function () { setPlayerText(playbackTitle(item), 'Buffering...'); showPlayerUi(false); };
    video.onplaying = function () {
      state.playing = true;
      state.switchingEpisode = false;
      setPlayerText(playbackTitle(item), 'Riproduzione');
      startTimeline();
      showPlayerUi(false);
    };
    video.onended = handlePlaybackCompleted;
    video.onerror = function () { failHlsJs(item, 'Errore del decoder video dell\'emulatore'); };
    var hls = new Hls({
      enableWorker: false,
      enableWebVTT: false,
      enableCEA708Captions: false,
      lowLatencyMode: false,
      capLevelToPlayerSize: true,
      maxBufferLength: 30,
      backBufferLength: 30,
      xhrSetup: function (xhr) {
        Object.keys(headers || {}).forEach(function (name) {
          try { xhr.setRequestHeader(name, headers[name]); } catch (error) {}
        });
      }
    });
    state.hlsInstance = hls;
    hls.on(Hls.Events.MANIFEST_PARSED, function () {
      applyHtmlResume(video);
      var started;
      try { started = video.play(); } catch (error) { failHlsJs(item, error.message); return; }
      if (started && started.catch) started.catch(function (error) { failHlsJs(item, error.message); });
    });
    hls.on(Hls.Events.ERROR, function (event, data) {
      if (!data || !data.fatal) return;
      state.hlsFatalRetries += 1;
      if (state.hlsFatalRetries <= 2 && data.type === Hls.ErrorTypes.NETWORK_ERROR) {
        hls.startLoad();
        return;
      }
      if (state.hlsFatalRetries <= 2 && data.type === Hls.ErrorTypes.MEDIA_ERROR) {
        hls.recoverMediaError();
        return;
      }
      failHlsJs(item, data.details || data.type || 'HLS non riproducibile');
    });
    hls.attachMedia(video);
    hls.loadSource(url);
    setPlayerText(playbackTitle(item), 'Preparazione HLS compatibile...');
  }

  function failHlsJs(item, reason) {
    state.playing = false;
    clearInterval(state.playerTick);
    setPlayerText(playbackTitle(item), 'Riproduzione non disponibile: ' + reason);
    showPlayerUi(true);
  }

  function fallbackToHtml(url, item) {
    if (state.htmlFallback) return false;
    state.htmlFallback = true;
    try { avplay.stop(); avplay.close(); } catch (error) {}
    var video = document.getElementById('html-player'), surface = document.getElementById('avplay');
    state.playerEngine = 'html';
    surface.style.display = 'none';
    video.style.display = 'block';
    video.src = url;
    video.onwaiting = function () { setPlayerText(playbackTitle(item), 'Buffering...'); showPlayerUi(false); };
    video.onplaying = function () { state.playing = true; state.switchingEpisode = false; setPlayerText(playbackTitle(item), state.playerLive ? 'In diretta' : 'Riproduzione'); startTimeline(); showPlayerUi(false); };
    video.oncanplay = function () { applyHtmlResume(video); video.play(); };
    video.onended = handlePlaybackCompleted;
    video.onerror = function () { setPlayerText(playbackTitle(item), 'Formato video non supportato dal dispositivo'); showPlayerUi(true); };
    video.load();
    setPlayerText(playbackTitle(item), 'Provo il player compatibile...');
    return true;
  }

  function openAvPlayer(url, item, headers) {
    if (!avplay) { setPlayerText(playbackTitle(item), 'AVPlay non disponibile in questo ambiente'); showPlayerUi(true); return; }
    var video = document.getElementById('html-player'), surface = document.getElementById('avplay');
    state.playerEngine = 'avplay';
    video.style.display = 'none';
    surface.style.display = 'block';
    try {
      avplay.setListener({
        onbufferingstart: function () { setPlayerText(playbackTitle(item), 'Buffering...'); showPlayerUi(false); },
        onbufferingcomplete: function () { setPlayerText(playbackTitle(item), state.playerLive ? 'In diretta' : 'Riproduzione'); },
        onstreamcompleted: handlePlaybackCompleted,
        onerror: function (error) {
          state.playing = false;
          if (fallbackToHtml(url, item)) return;
          setPlayerText(playbackTitle(item), 'Errore player: ' + error);
          showPlayerUi(true);
        }
      });
      avplay.open(url);
      if (headers && headers['User-Agent']) {
        try { avplay.setStreamingProperty('USER_AGENT', headers['User-Agent']); } catch (error) {}
      }
      if (headers && headers.Cookie) {
        try { avplay.setStreamingProperty('COOKIE', headers.Cookie); } catch (error) {}
      }
      avplay.setDisplayRect(0, 0, 1920, 1080);
      avplay.setDisplayMethod('PLAYER_DISPLAY_MODE_AUTO_ASPECT_RATIO');
      avplay.prepareAsync(function () {
        startAvPlayback(item);
      }, function (error) {
        if (fallbackToHtml(url, item)) return;
        setPlayerText(playbackTitle(item), 'Errore AVPlay: ' + error);
        showPlayerUi(true);
      });
    } catch (error) {
      setPlayerText(playbackTitle(item), 'Errore AVPlay: ' + error.message);
      showPlayerUi(true);
    }
  }

  function applyHtmlResume(video) {
    var resume = Number(state.pendingResumeMs || 0);
    state.pendingResumeMs = 0;
    if (resume >= CW_MIN_PROGRESS_MS && isFinite(video.duration)) {
      try { video.currentTime = Math.min(video.duration - 1, resume / 1000); } catch (error) {}
    }
  }

  function startAvPlayback(item) {
    var resume = Number(state.pendingResumeMs || 0);
    state.pendingResumeMs = 0;
    function started() {
      try { avplay.play(); } catch (error) {}
      state.playing = true;
      state.switchingEpisode = false;
      setPlayerText(playbackTitle(item), state.playerLive ? 'In diretta' : 'Riproduzione');
      startTimeline();
      showPlayerUi(false);
    }
    if (resume >= CW_MIN_PROGRESS_MS) {
      try { avplay.seekTo(resume, started, started); } catch (error) { started(); }
    } else started();
  }

  function setPlayerText(name, subtitle) {
    document.getElementById('player-title').textContent = name || '';
    document.getElementById('player-subtitle').textContent = subtitle || '';
  }

  function timeLabel(milliseconds) {
    var seconds = Math.max(0, Math.floor((milliseconds || 0) / 1000)), hours = Math.floor(seconds / 3600);
    seconds -= hours * 3600;
    var minutes = Math.floor(seconds / 60), rest = seconds % 60;
    return (hours ? hours + ':' + (minutes < 10 ? '0' : '') : '') + minutes + ':' + (rest < 10 ? '0' : '') + rest;
  }

  function setPlayerProgress(current, duration, percent) {
    document.getElementById('player-progress').style.width = (percent || 0) + '%';
    document.getElementById('player-current').textContent = state.playerLive ? '' : timeLabel(current);
    document.getElementById('player-duration').textContent = state.playerLive ? 'LIVE' : timeLabel(duration);
  }

  function updateTimeline() {
    if (!state.playerOpen) return;
    try {
      var video = document.getElementById('html-player');
      var duration = isHtmlPlayerEngine() ? video.duration * 1000 : avplay.getDuration();
      var current = isHtmlPlayerEngine() ? video.currentTime * 1000 : avplay.getCurrentTime();
      var percent = duration > 0 && isFinite(duration) ? Math.min(100, current / duration * 100) : 0;
      setPlayerProgress(current, duration, percent);
      if (!state.playerLive && state.playerItem && Date.now() - state.lastProgressSave >= 5000) {
        state.lastProgressSave = Date.now();
        saveContinueWatching(state.playerItem, current, duration, false);
      }
      updateUpNext(current, duration);
    } catch (error) { setPlayerProgress(0, 0, 0); }
  }

  function startTimeline() {
    clearInterval(state.playerTick);
    updateTimeline();
    state.playerTick = setInterval(updateTimeline, 700);
  }

  function nextEpisodeItem() {
    var index = state.episodeIndex + 1;
    return index >= 0 && index < state.episodeQueue.length ? state.episodeQueue[index] : null;
  }

  function updateUpNext(current, duration) {
    if (!isEpisode(state.playerItem) || state.upNextCancelled || !nextEpisodeItem() || !duration) return;
    var remaining = Math.max(0, duration - current);
    if (!state.upNextVisible && current >= UP_NEXT_MIN_WATCHED_MS && remaining > 0 && remaining <= UP_NEXT_PROMPT_MS) showUpNext();
    if (!state.upNextVisible) return;
    var seconds = Math.max(0, Math.ceil(remaining / 1000));
    var timer = document.getElementById('up-next-timer'), progress = document.getElementById('up-next-progress');
    if (timer) timer.textContent = seconds ? 'Parte automaticamente tra ' + Math.floor(seconds / 60) + ':' + (seconds % 60 < 10 ? '0' : '') + (seconds % 60) : 'Avvio episodio successivo...';
    if (progress) progress.style.width = Math.min(100, Math.max(0, (UP_NEXT_PROMPT_MS - remaining) / UP_NEXT_PROMPT_MS * 100)) + '%';
  }

  function showUpNext() {
    var next = nextEpisodeItem(), overlay = document.getElementById('up-next');
    if (!next || !overlay || state.upNextVisible) return;
    state.upNextVisible = true;
    document.getElementById('up-next-title').textContent = episodeTitleText(next);
    overlay.className = 'up-next';
    showPlayerUi(false);
    focusElement(document.getElementById('up-next-play'));
  }

  function hideUpNext(cancelAutoplay) {
    var overlay = document.getElementById('up-next');
    if (cancelAutoplay) state.upNextCancelled = true;
    state.upNextVisible = false;
    if (overlay) overlay.className = 'up-next hidden';
  }

  function switchToNextEpisode() {
    var next = nextEpisodeItem();
    if (!state.playerOpen || !next || state.switchingEpisode) return;
    clearTimeout(state.episodeTransitionTimer);
    state.episodeTransitionTimer = null;
    state.episodeTransitionScheduled = false;
    state.switchingEpisode = true;
    hideUpNext(false);
    state.episodeIndex += 1;
    saveContinueWatching(next, 0, 0, true);
    stopPlayerMedia();
    play(next, {switching: true});
  }

  function handlePlaybackCompleted() {
    if (!state.playerOpen || state.switchingEpisode || state.episodeTransitionScheduled) return;
    state.playing = false;
    clearInterval(state.playerTick);
    if (isEpisode(state.playerItem) && nextEpisodeItem() && !state.upNextCancelled) {
      state.episodeTransitionScheduled = true;
      setPlayerText(playbackTitle(state.playerItem), 'Avvio episodio successivo...');
      clearTimeout(state.episodeTransitionTimer);
      state.episodeTransitionTimer = setTimeout(switchToNextEpisode, 800);
      return;
    }
    if (state.playerItem) removeContinueWatching(state.playerItem, state.episodeParent);
    hideUpNext(false);
    setPlayerText(playbackTitle(state.playerItem || {}), 'Riproduzione completata');
    showPlayerUi(true);
  }

  function showPlayerUi(focusControls) {
    var ui = document.getElementById('player-ui');
    ui.className = 'player-ui';
    clearTimeout(state.playerUiTimer);
    if (focusControls) {
      var active = document.activeElement;
      if (!active || active.getAttribute('data-zone') !== 'player') focusElement(document.getElementById('player-toggle'));
    }
    if (state.playing) state.playerUiTimer = setTimeout(function () {
      if (document.activeElement && document.activeElement.getAttribute('data-zone') === 'player') return;
      ui.className = 'player-ui hidden';
    }, PLAYER_HIDE_MS);
  }

  function currentPlayerTimes() {
    try {
      var video = document.getElementById('html-player');
      return isHtmlPlayerEngine() ? {current: video.currentTime * 1000, duration: video.duration * 1000} :
        state.playerEngine === 'avplay' ? {current: avplay.getCurrentTime(), duration: avplay.getDuration()} : {current: 0, duration: 0};
    } catch (error) { return {current: 0, duration: 0}; }
  }

  function stopPlayerMedia() {
    var frame = document.getElementById('embed-player'), video = document.getElementById('html-player');
    if (frame) frame.parentNode.removeChild(frame);
    if (state.hlsInstance) {
      try { state.hlsInstance.destroy(); } catch (error) {}
      state.hlsInstance = null;
    }
    if (state.shakaInstance) {
      try { state.shakaInstance.destroy(); } catch (error) {}
      state.shakaInstance = null;
    }
    try { video.pause(); video.removeAttribute('src'); video.load(); } catch (error) {}
    video.onwaiting = video.onplaying = video.oncanplay = video.onended = video.onerror = null;
    video.style.display = 'none';
    try { avplay.stop(); avplay.close(); } catch (error) {}
    clearInterval(state.playerTick);
    document.getElementById('avplay').style.display = 'none';
  }

  function closePlayer() {
    if (!state.playerOpen && document.getElementById('player').className.indexOf('hidden') >= 0) return;
    var times = currentPlayerTimes();
    if (state.playerItem && !state.playerLive) saveContinueWatching(state.playerItem, times.current, times.duration, false);
    stopPlayerMedia();
    state.playerOpen = false;
    state.playing = false;
    state.playerLive = false;
    state.playerEngine = '';
    state.playerItem = null;
    state.pendingResumeMs = 0;
    state.switchingEpisode = false;
    state.episodeTransitionScheduled = false;
    clearTimeout(state.episodeTransitionTimer);
    state.episodeTransitionTimer = null;
    state.liveQueue = [];
    state.liveIndex = -1;
    state.liveRowTitle = '';
    state.liveSwitchBusy = false;
    state.playRequestId += 1;
    hideUpNext(false);
    clearTimeout(state.playerUiTimer);
    document.getElementById('player').className = 'player hidden';
    document.getElementById('player-ui').className = 'player-ui';
    setTimeout(function () { restoreFocusByKey(state.detailOrigin); }, 0);
  }

  function togglePlayback() {
    try {
      var video = document.getElementById('html-player');
      if (state.playing) {
        if (isHtmlPlayerEngine()) video.pause(); else if (state.playerEngine === 'avplay') avplay.pause();
        state.playing = false;
        document.getElementById('player-toggle').textContent = 'Riprendi';
        setPlayerText(document.getElementById('player-title').textContent, 'In pausa');
      } else {
        if (isHtmlPlayerEngine()) video.play(); else if (state.playerEngine === 'avplay') avplay.play();
        state.playing = true;
        document.getElementById('player-toggle').textContent = 'Pausa';
      }
      showPlayerUi(true);
    } catch (error) { toast('Comando player non disponibile', true); }
  }

  function seek(seconds) {
    if (state.playerLive) { toast('La diretta non dispone di una timeline'); showPlayerUi(true); return; }
    try {
      var video = document.getElementById('html-player');
      if (isHtmlPlayerEngine() && isFinite(video.duration)) video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + seconds));
      else if (state.playerEngine === 'avplay') {
        if (seconds > 0) avplay.jumpForward(seconds * 1000, function () {}, function () {});
        else avplay.jumpBackward(Math.abs(seconds) * 1000, function () {}, function () {});
      }
      updateTimeline();
      showPlayerUi(true);
    } catch (error) { toast('Seek non disponibile', true); }
  }

  function switchLive(direction, attempts, bypassDebounce) {
    attempts = Number(attempts || 0);
    if (!state.playerOpen || !state.playerLive || state.liveQueue.length < 2 || state.liveSwitchBusy) return;
    var now = Date.now();
    if (!bypassDebounce && now - state.liveSwitchAt < 650) return;
    state.liveSwitchAt = now;
    state.liveSwitchBusy = true;
    state.liveIndex = (state.liveIndex + direction + state.liveQueue.length) % state.liveQueue.length;
    var next = state.liveQueue[state.liveIndex];
    stopPlayerMedia();
    state.playerOpen = true;
    state.playerLive = true;
    state.playerItem = next;
    setPlayerText(title(next), 'Cambio canale...');
    toast(title(next) + '  -  ' + (state.liveIndex + 1) + '/' + state.liveQueue.length);
    play(next, {switchingLive: true, liveDirection: direction, liveAttempts: attempts});
  }

  function isVisible(element) { return !!(element && element.offsetParent !== null); }

  function focusElement(element) {
    if (!isVisible(element)) return false;
    element.focus();
    rememberFocus(element);
    ensureVisible(element);
    return true;
  }

  function ensureVisible(element) {
    var cards = closest(element, '.cards');
    if (cards) {
      var left = element.offsetLeft, right = left + element.offsetWidth;
      if (left < cards.scrollLeft + 10) cards.scrollLeft = Math.max(0, left - 12);
      if (right > cards.scrollLeft + cards.clientWidth - 10) cards.scrollLeft = right - cards.clientWidth + 12;
    }
    var scroller = closest(element, '.home-scroll') || closest(element, '.page-scroll') || closest(element, '.episodes-layout');
    if (scroller) {
      var rect = element.getBoundingClientRect(), scrollRect = scroller.getBoundingClientRect();
      if (rect.top < scrollRect.top + 10) scroller.scrollTop -= scrollRect.top + 10 - rect.top;
      if (rect.bottom > scrollRect.bottom - 20) scroller.scrollTop += rect.bottom - scrollRect.bottom + 20;
    }
  }

  function currentFocusKey() {
    var active = document.activeElement;
    return active && active.getAttribute && active.getAttribute('data-focus-key') || '';
  }

  function rememberFocus(element) {
    var key = element && element.getAttribute && element.getAttribute('data-focus-key');
    if (key && state.page) state.focusMemory[state.page] = key;
  }

  function restoreFocusByKey(key) {
    if (key) {
      var element = document.querySelector('[data-focus-key="' + key.replace(/"/g, '\\"') + '"]');
      if (focusElement(element)) return true;
    }
    return false;
  }

  function focusActiveNav() {
    return focusElement(document.querySelector('[data-nav="' + state.page + '"]'));
  }

  function firstContentFocus() {
    return document.querySelector('#content [data-focusable]');
  }

  function restoreFocus(preserve) {
    if (preserve && restoreFocusByKey(state.focusMemory[state.page])) return;
    var first = firstContentFocus();
    if (!focusElement(first)) focusActiveNav();
  }

  function elementsInZone(zone, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll('[data-zone="' + zone + '"][data-focusable]')).filter(isVisible);
  }

  function moveNav(key) {
    var buttons = elementsInZone('nav'), active = document.activeElement, index = buttons.indexOf(active);
    if (key === 38 && index > 0) return focusElement(buttons[index - 1]);
    if (key === 40 && index >= 0 && index < buttons.length - 1) return focusElement(buttons[index + 1]);
    if (key === 39) return focusElement(firstContentFocus());
    return false;
  }

  function focusRow(row, column) {
    var selector = '[data-zone="row"][data-row="' + row + '"]', candidates = Array.prototype.slice.call(document.querySelectorAll(selector)).filter(isVisible);
    if (!candidates.length) return false;
    return focusElement(candidates[Math.min(column, candidates.length - 1)]);
  }

  function moveGrid(active, key) {
    var grid = closest(active, '.catalog');
    if (!grid) return false;
    var elements = Array.prototype.slice.call(grid.querySelectorAll('[data-zone="grid"]')).filter(isVisible);
    var index = elements.indexOf(active), columns = 5, next = index;
    if (key === 37) { if (index % columns === 0) return focusActiveNav(); next = index - 1; }
    if (key === 39) next = index + 1;
    if (key === 38) next = index - columns;
    if (key === 40) next = index + columns;
    return next >= 0 && next < elements.length ? focusElement(elements[next]) : false;
  }

  function moveByGeometry(active, key, root) {
    var elements = Array.prototype.slice.call((root || document).querySelectorAll('[data-focusable]')).filter(isVisible);
    var source = active.getBoundingClientRect(), best = null, score = Infinity;
    elements.forEach(function (element) {
      if (element === active) return;
      var rect = element.getBoundingClientRect();
      var dx = rect.left + rect.width / 2 - (source.left + source.width / 2);
      var dy = rect.top + rect.height / 2 - (source.top + source.height / 2);
      var valid = (key === 37 && dx < -6) || (key === 39 && dx > 6) || (key === 38 && dy < -6) || (key === 40 && dy > 6);
      if (!valid) return;
      var candidate = (key === 37 || key === 39) ? Math.abs(dx) + Math.abs(dy) * 4 : Math.abs(dy) + Math.abs(dx) * 4;
      if (candidate < score) { score = candidate; best = element; }
    });
    return focusElement(best);
  }

  function moveFocus(key) {
    var active = document.activeElement;
    if (!active || !active.getAttribute) return focusElement(firstContentFocus()) || focusActiveNav();
    var zone = active.getAttribute('data-zone');
    if (zone === 'nav') return moveNav(key);
    if (zone === 'hero') {
      if (key === 37) return focusActiveNav();
      if (key === 40) return focusRow(0, 0);
      return false;
    }
    if (zone === 'row') {
      var row = Number(active.getAttribute('data-row')), column = Number(active.getAttribute('data-col'));
      if (key === 37) return column > 0 ? focusRow(row, column - 1) : focusActiveNav();
      if (key === 39) return focusRow(row, column + 1);
      if (key === 38) return row > 0 ? focusRow(row - 1, column) : focusElement(document.querySelector('.hero-action'));
      if (key === 40) return focusRow(row + 1, column);
    }
    if (zone === 'grid') return moveGrid(active, key);
    if (zone === 'form') {
      var formIndex = Number(active.getAttribute('data-form-index'));
      if (key === 37) return formIndex > 0 ? focusElement(document.querySelector('[data-form-index="' + (formIndex - 1) + '"]')) : focusActiveNav();
      if (key === 39) return focusElement(document.querySelector('[data-form-index="' + (formIndex + 1) + '"]'));
      if (key === 40) return focusElement(document.querySelector('#search-results [data-focusable]'));
    }
    if (zone === 'filters') {
      var filterIndex = Number(active.getAttribute('data-filter-index'));
      if (key === 37) return filterIndex > 0 ? focusElement(document.querySelector('[data-filter-index="' + (filterIndex - 1) + '"]')) : focusActiveNav();
      if (key === 39) return focusElement(document.querySelector('[data-filter-index="' + (filterIndex + 1) + '"]'));
      if (key === 40) return focusElement(document.querySelector('#browse-grid [data-focusable], #search-results [data-focusable]'));
    }
    if (zone === 'settings') return moveByGeometry(active, key, document.querySelector('.settings-grid')) || (key === 37 ? focusActiveNav() : false);
    if (zone === 'state') return key === 37 ? focusActiveNav() : false;
    if (zone === 'detail' || zone === 'episodes-header' || zone === 'episode-seasons' || zone === 'episodes') {
      return moveByGeometry(active, key, document.getElementById('detail'));
    }
    return moveByGeometry(active, key, document.getElementById('content'));
  }

  function playerButtons() {
    return ['player-rewind', 'player-toggle', 'player-forward'].map(function (id) { return document.getElementById(id); }).filter(function (button) {
      return isVisible(button) && !button.disabled;
    });
  }

  function movePlayerFocus(key) {
    var buttons = playerButtons(), active = document.activeElement, index = buttons.indexOf(active);
    if (key === 37 && index > 0) return focusElement(buttons[index - 1]);
    if (key === 39 && index >= 0 && index < buttons.length - 1) return focusElement(buttons[index + 1]);
    if (key === 38) return focusElement(document.getElementById('player-exit'));
    if (key === 40 && active === document.getElementById('player-exit')) return focusElement(document.getElementById('player-toggle'));
    return false;
  }

  function registerKeys() {
    try {
      ['MediaPlayPause', 'MediaPlay', 'MediaPause', 'MediaRewind', 'MediaFastForward', 'MediaStop', 'ChannelUp', 'ChannelDown'].forEach(function (key) {
        try { tizen.tvinputdevice.registerKey(key); } catch (error) {}
      });
    } catch (error) {}
  }

  document.addEventListener('focusin', function (event) { rememberFocus(event.target); });

  document.addEventListener('keydown', function (event) {
    var key = event.keyCode, active;
    if (state.playerOpen) {
      if (state.upNextVisible) {
        active = document.activeElement;
        if (key === 10009 || key === 27 || key === 8) { event.preventDefault(); hideUpNext(true); showPlayerUi(true); return; }
        if (key === 37 || key === 39) {
          event.preventDefault();
          focusElement(document.getElementById(active === document.getElementById('up-next-play') ? 'up-next-cancel' : 'up-next-play'));
          return;
        }
        if (key === 13 && active && active.getAttribute('data-zone') === 'upnext') { event.preventDefault(); active.click(); return; }
      }
      showPlayerUi(false);
      if (state.playerLive && (key === 427 || key === 428)) {
        event.preventDefault();
        switchLive(key === 427 ? 1 : -1, 0, false);
        return;
      }
      if (key === 10009 || key === 27 || key === 8 || key === 413) { event.preventDefault(); closePlayer(); return; }
      if (key === 412) { event.preventDefault(); seek(-10); return; }
      if (key === 417) { event.preventDefault(); seek(10); return; }
      if (key === 415 || key === 19 || key === 10252) { event.preventDefault(); togglePlayback(); return; }
      if (key === 37 || key === 38 || key === 39 || key === 40) {
        event.preventDefault();
        if (document.getElementById('player-ui').className.indexOf('hidden') >= 0) showPlayerUi(true);
        else movePlayerFocus(key);
        return;
      }
      if (key === 13) {
        event.preventDefault();
        active = document.activeElement;
        if (active && active.getAttribute('data-zone') === 'player') active.click(); else togglePlayback();
      }
      return;
    }
    if (document.getElementById('detail').className.indexOf('hidden') < 0 && (key === 10009 || key === 27 || key === 8)) {
      event.preventDefault();
      if (state.detailParent) renderDetail(state.detailParent); else closeDetail();
      return;
    }
    if (key === 13 || key === 415 || key === 10252) {
      active = document.activeElement;
      if (active && active.hasAttribute('data-focusable')) { event.preventDefault(); active.click(); }
      return;
    }
    if (key === 37 || key === 38 || key === 39 || key === 40) { event.preventDefault(); moveFocus(key); return; }
    if (key === 10009 || key === 27 || key === 8) {
      event.preventDefault();
      if (state.page !== 'home') openPage('home');
      else { try { tizen.application.getCurrentApplication().exit(); } catch (error) {} }
    }
  });

  function boot() {
    if (window.__PRIPPI_APP_BOOTED__) return;
    window.__PRIPPI_APP_BOOTED__ = true;
    registerKeys();
    Array.prototype.forEach.call(document.querySelectorAll('[data-nav]'), function (element) {
      element.onclick = function () { openPage(element.getAttribute('data-nav')); };
      element.setAttribute('data-focus-key', 'nav:' + element.getAttribute('data-nav'));
    });
    document.getElementById('player-rewind').onclick = function () { seek(-10); };
    document.getElementById('player-toggle').onclick = togglePlayback;
    document.getElementById('player-forward').onclick = function () { seek(10); };
    document.getElementById('player-exit').onclick = closePlayer;
    document.getElementById('up-next-play').onclick = switchToNextEpisode;
    document.getElementById('up-next-cancel').onclick = function () { hideUpNext(true); showPlayerUi(true); };
    openPage('home');
  }

  boot();
}());
