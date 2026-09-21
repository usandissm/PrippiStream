(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.PrippiCwFlow = api;
}(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  var SCHEMA = 2;
  var MAX_QUEUE_ITEMS = 200;

  function normalizedKey(value) {
    return String(value || '').toLowerCase().replace(/[^a-z0-9\u00c0-\u024f]+/g, '');
  }

  function labels(item) {
    return item && item.infoLabels || {};
  }

  function title(item) {
    var itemLabels = labels(item);
    return item && (item.fulltitle || item.title || itemLabels.title) || '';
  }

  function mediaType(item) {
    var value = String(labels(item).mediatype || (item && item.contentType) || '').toLowerCase();
    if (item && item.isLive) return 'live';
    if (/episode/.test(value)) return 'episode';
    if (/tv|serie|season/.test(value)) return 'series';
    return 'movie';
  }

  function isEpisode(item) {
    return mediaType(item) === 'episode';
  }

  function inferredSeriesTitle(item) {
    if (!isEpisode(item)) return '';
    return String(title(item)).replace(/\s+(?:s?\d+\s*[xe]\s*\d+|\d+x\d+)(?:\s*[-.:\u2014].*)?$/i, '').trim();
  }

  function seriesName(item, parent) {
    var itemLabels = labels(item), parentLabels = labels(parent);
    return String(item && (item.contentSerieName || item.show || item.tvshowtitle) ||
      itemLabels.tvshowtitle || itemLabels.showtitle ||
      (parent && (parent.contentSerieName || parent.show || parent.tvshowtitle)) ||
      parentLabels.tvshowtitle || parentLabels.showtitle || title(parent) ||
      inferredSeriesTitle(item) ||
      (mediaType(item) === 'series' ? title(item) : '') || '').trim();
  }

  function seriesIdentifier(item, parent) {
    var itemLabels = labels(item), parentLabels = labels(parent);
    return parentLabels.tmdb_id || (parent && (parent.tmdb_id || parent.series_id || parent.id)) ||
      itemLabels.tvshowid || itemLabels.series_tmdb_id ||
      (item && (item.series_tmdb_id || item.series_id)) || '';
  }

  function continueKey(item, parent) {
    var type = mediaType(item), series = type === 'episode' || type === 'series';
    if (series) {
      var name = normalizedKey(seriesName(item, parent));
      return 'tv_' + (name || normalizedKey(seriesIdentifier(item, parent)) ||
        normalizedKey(item && (item.url || item.video_id)) || 'unknown');
    }
    var itemLabels = labels(item);
    return 'movie_' + (itemLabels.tmdb_id || (item && item.tmdb_id) || normalizedKey(title(item)) ||
      normalizedKey(item && (item.url || item.video_id)) || 'unknown');
  }

  function episodeNumber(item, key) {
    var itemLabels = labels(item);
    return Number(item && (item[key] || item[key === 'season' ? 'contentSeason' : 'contentEpisodeNumber']) ||
      itemLabels[key] || 0) || 0;
  }

  function sameMedia(left, right) {
    if (!left || !right) return false;
    if (isEpisode(left) || isEpisode(right)) {
      if (left.video_id && right.video_id && String(left.video_id) === String(right.video_id)) return true;
      var leftSeason = episodeNumber(left, 'season'), rightSeason = episodeNumber(right, 'season');
      var leftEpisode = episodeNumber(left, 'episode'), rightEpisode = episodeNumber(right, 'episode');
      var leftSeries = normalizedKey(seriesName(left)), rightSeries = normalizedKey(seriesName(right));
      if (leftSeason && leftEpisode && leftSeason === rightSeason && leftEpisode === rightEpisode &&
          (!leftSeries || !rightSeries || leftSeries === rightSeries)) return true;
    }
    if (left.video_id && right.video_id) return String(left.video_id) === String(right.video_id);
    if (left.url && right.url) return String(left.url) === String(right.url);
    return normalizedKey(title(left)) === normalizedKey(title(right));
  }

  function compareEpisodes(left, right) {
    var seasonDifference = episodeNumber(left, 'season') - episodeNumber(right, 'season');
    if (seasonDifference) return seasonDifference;
    return episodeNumber(left, 'episode') - episodeNumber(right, 'episode');
  }

  function normalizeEpisodeQueue(queue, current) {
    var output = [];
    (queue || []).concat(current ? [current] : []).forEach(function (item) {
      if (!item || !isEpisode(item) || output.some(function (saved) { return sameMedia(saved, item); })) return;
      output.push(item);
    });
    output.sort(compareEpisodes);
    var index = current ? output.findIndex(function (item) { return sameMedia(item, current); }) : -1;
    if (index < 0 && current) {
      output.push(current);
      output.sort(compareEpisodes);
      index = output.findIndex(function (item) { return sameMedia(item, current); });
    }
    if (output.length > MAX_QUEUE_ITEMS) {
      var start = Math.max(0, Math.min(index, output.length - MAX_QUEUE_ITEMS));
      output = output.slice(start, start + MAX_QUEUE_ITEMS);
      index = current ? output.findIndex(function (item) { return sameMedia(item, current); }) : -1;
    }
    return {items: output, index: index};
  }

  function newerEntry(left, right) {
    var time = Number(right.updatedAt || 0) - Number(left.updatedAt || 0);
    if (time) return time;
    return Number(right.position || 0) - Number(left.position || 0);
  }

  function migrateEntries(entries, maxItems) {
    var groups = {}, output = [];
    (Array.isArray(entries) ? entries : []).filter(function (entry) {
      return entry && entry.item && !entry.item.isLive && mediaType(entry.item) !== 'live';
    }).forEach(function (entry) {
      var key = continueKey(entry.item, entry.parent), group = groups[key];
      if (!group) group = groups[key] = [];
      group.push(entry);
    });
    Object.keys(groups).forEach(function (key) {
      var group = groups[key].sort(newerEntry), newest = group[0];
      var parent = newest.parent || group.map(function (entry) { return entry.parent; }).filter(Boolean)[0] || null;
      var combinedQueue = [];
      group.forEach(function (entry) { combinedQueue = combinedQueue.concat(entry.queue || []); });
      var queue = isEpisode(newest.item) ? normalizeEpisodeQueue(combinedQueue, newest.item) : {items: [], index: -1};
      output.push({
        schema: SCHEMA,
        key: key,
        item: newest.item,
        parent: parent,
        queue: queue.items,
        index: queue.index,
        queueComplete: group.some(function (entry) { return entry.queueComplete === true; }),
        position: Math.max(0, Number(newest.position || 0)),
        duration: Math.max(0, Number(newest.duration || 0)),
        updatedAt: Math.max(0, Number(newest.updatedAt || 0))
      });
    });
    return output.sort(newerEntry).slice(0, Number(maxItems || 30));
  }

  function nextEpisode(queue, currentIndex, current) {
    var normalized = normalizeEpisodeQueue(queue, current);
    var index = current ? normalized.index : Number(currentIndex);
    if (!current && index < 0) index = Number(currentIndex);
    return index >= 0 && index + 1 < normalized.items.length ? normalized.items[index + 1] : null;
  }

  function shouldShowUpNext(current, duration, hasNext, cancelled, promptMs) {
    current = Number(current || 0);
    duration = Number(duration || 0);
    var remaining = duration - current;
    return !!hasNext && !cancelled && duration > 0 && remaining > 0 &&
      remaining <= Number(promptMs || 60000);
  }

  return {
    SCHEMA: SCHEMA,
    MAX_QUEUE_ITEMS: MAX_QUEUE_ITEMS,
    normalizedKey: normalizedKey,
    continueKey: continueKey,
    sameMedia: sameMedia,
    normalizeEpisodeQueue: normalizeEpisodeQueue,
    migrateEntries: migrateEntries,
    nextEpisode: nextEpisode,
    shouldShowUpNext: shouldShowUpNext
  };
}));
