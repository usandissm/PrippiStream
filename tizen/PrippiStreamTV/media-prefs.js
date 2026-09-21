(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.PrippiMediaPrefs = api;
}(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  var SCHEMA = 1;
  var STORAGE_KEY = 'prippi.tizen.media_prefs.v1';
  var SUBTITLES_OFF = '__off__';
  var LANGUAGE_ALIASES = {
    it: 'ita', ita: 'ita', italian: 'ita', italiano: 'ita',
    en: 'eng', eng: 'eng', english: 'eng', inglese: 'eng',
    es: 'spa', spa: 'spa', spanish: 'spa', spagnolo: 'spa',
    fr: 'fra', fre: 'fra', fra: 'fra', french: 'fra', francese: 'fra',
    de: 'deu', ger: 'deu', deu: 'deu', german: 'deu', tedesco: 'deu',
    pt: 'por', por: 'por', portuguese: 'por', portoghese: 'por',
    ja: 'jpn', jpn: 'jpn', japanese: 'jpn', giapponese: 'jpn'
  };

  function normalizedKey(value) {
    return String(value || '').toLowerCase().replace(/[^a-z0-9\u00c0-\u024f]+/g, '');
  }

  function mediaType(item) {
    var labels = item && item.infoLabels || {};
    var value = String(labels.mediatype || (item && item.contentType) || '').toLowerCase();
    if (item && (item.isLive || item._app_live) || value === 'live') return 'live';
    if (/episode/.test(value)) return 'episode';
    if (/tv|serie|season/.test(value)) return 'series';
    return 'movie';
  }

  function preferenceKey(item, parent, continueKey) {
    if (!item || mediaType(item) === 'live') return '';
    var resolver = continueKey || (typeof window !== 'undefined' && window.PrippiCwFlow && window.PrippiCwFlow.continueKey);
    if (typeof resolver === 'function') return String(resolver(item, parent) || '');
    var labels = item.infoLabels || {};
    var series = item.contentSerieName || item.show || item.tvshowtitle || labels.tvshowtitle ||
      (parent && (parent.contentSerieName || parent.show || parent.tvshowtitle || parent.fulltitle || parent.title));
    if (mediaType(item) === 'episode' || mediaType(item) === 'series') return 'tv_' + normalizedKey(series || item.title || item.fulltitle);
    return 'movie_' + String(labels.tmdb_id || item.tmdb_id || normalizedKey(item.fulltitle || item.title || item.url));
  }

  function normalizeLanguage(value) {
    var raw = String(value || '').trim().toLowerCase().replace(/_/g, '-');
    if (!raw) return '';
    var base = raw.split('-')[0];
    return LANGUAGE_ALIASES[raw] || LANGUAGE_ALIASES[base] || base;
  }

  function parsedExtra(track) {
    var value = track && track.extra_info;
    if (!value) return {};
    if (typeof value === 'object') return value;
    try { return JSON.parse(value); } catch (error) { return {}; }
  }

  function trackLanguage(track) {
    var extra = parsedExtra(track);
    return normalizeLanguage(track && (track.language || track.lang || track.track_lang) ||
      extra.track_lang || extra.language || extra.lang || '');
  }

  function trackLabel(track) {
    var extra = parsedExtra(track);
    return String(track && (track.label || track.name) || extra.track_name || extra.label ||
      extra.track_lang || extra.language || '').trim();
  }

  function trackPreference(track) {
    var language = trackLanguage(track);
    if (language) return language;
    var rawLabel = trackLabel(track), labelLanguage = LANGUAGE_ALIASES[String(rawLabel || '').trim().toLowerCase()];
    if (labelLanguage) return labelLanguage;
    var label = normalizedKey(rawLabel);
    return label ? 'label:' + label : '';
  }

  function findTrackIndex(tracks, preference) {
    preference = String(preference || '');
    if (!preference || preference === SUBTITLES_OFF) return -1;
    var wanted = preference.indexOf('label:') === 0 ? preference : normalizeLanguage(preference);
    for (var index = 0; index < (tracks || []).length; index += 1) {
      if (trackPreference(tracks[index]) === wanted) return index;
    }
    return -1;
  }

  function selectionPlan(audioTracks, textTracks, preferences) {
    preferences = normalizePrefs(preferences);
    var audioIndex = preferences.audio_lang ? findTrackIndex(audioTracks, preferences.audio_lang) : -1;
    var subtitleIndex = null;
    if (preferences.sub_lang === SUBTITLES_OFF) subtitleIndex = -1;
    else if (preferences.sub_lang) {
      var matchedSubtitle = findTrackIndex(textTracks, preferences.sub_lang);
      if (matchedSubtitle >= 0) subtitleIndex = matchedSubtitle;
    }
    return {
      audioIndex: audioIndex >= 0 ? audioIndex : null,
      subtitleIndex: subtitleIndex
    };
  }

  function emptyStore() { return {schema: SCHEMA, items: {}}; }

  function readStore(storage) {
    try {
      var parsed = JSON.parse(storage.getItem(STORAGE_KEY) || 'null');
      if (!parsed || typeof parsed !== 'object') return emptyStore();
      if (!parsed.items || typeof parsed.items !== 'object') {
        parsed = {schema: SCHEMA, items: parsed};
      }
      parsed.schema = SCHEMA;
      return parsed;
    } catch (error) { return emptyStore(); }
  }

  function normalizePrefs(prefs) {
    prefs = prefs || {};
    var audio = String(prefs.audio_lang || '');
    var subtitles = String(prefs.sub_lang || '');
    return {
      audio_lang: audio.indexOf('label:') === 0 ? audio : normalizeLanguage(audio),
      sub_lang: subtitles === SUBTITLES_OFF || subtitles.indexOf('label:') === 0 ? subtitles : normalizeLanguage(subtitles)
    };
  }

  function get(storage, item, parent, continueKey) {
    var key = preferenceKey(item, parent, continueKey);
    if (!key) return null;
    var prefs = readStore(storage).items[key];
    return prefs ? normalizePrefs(prefs) : null;
  }

  function set(storage, item, parent, patch, continueKey) {
    var key = preferenceKey(item, parent, continueKey);
    if (!key) return false;
    var store = readStore(storage), previous = normalizePrefs(store.items[key]);
    var next = normalizePrefs({
      audio_lang: Object.prototype.hasOwnProperty.call(patch || {}, 'audio_lang') ? patch.audio_lang : previous.audio_lang,
      sub_lang: Object.prototype.hasOwnProperty.call(patch || {}, 'sub_lang') ? patch.sub_lang : previous.sub_lang
    });
    store.items[key] = next;
    try { storage.setItem(STORAGE_KEY, JSON.stringify(store)); return true; } catch (error) { return false; }
  }

  return {
    SCHEMA: SCHEMA,
    STORAGE_KEY: STORAGE_KEY,
    SUBTITLES_OFF: SUBTITLES_OFF,
    preferenceKey: preferenceKey,
    normalizeLanguage: normalizeLanguage,
    trackLanguage: trackLanguage,
    trackPreference: trackPreference,
    findTrackIndex: findTrackIndex,
    selectionPlan: selectionPlan,
    get: get,
    set: set
  };
}));
