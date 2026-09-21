'use strict';

var assert = require('assert');
var flow = require('../cw-flow.js');

function episode(series, season, number, id) {
  return {
    contentType: 'episode',
    contentSerieName: series,
    season: season,
    episode: number,
    video_id: id || series + '-' + season + '-' + number,
    title: season + 'x' + number
  };
}

function parent(name) {
  return {contentType: 'tvshow', title: name, fulltitle: name};
}

(function deduplicatesLegacySeriesEntriesAndKeepsLatestProgress() {
  var show = parent('Serie Test');
  var oldEpisode = episode('Serie Test', 1, 2);
  var latestEpisode = episode('Serie Test', 1, 3);
  var migrated = flow.migrateEntries([
    {schema: 1, key: 'tv_111', item: oldEpisode, parent: show, queue: [oldEpisode], position: 900000, duration: 2400000, updatedAt: 100},
    {schema: 1, key: 'tv_serietest-duplicate', item: latestEpisode, parent: show, queue: [latestEpisode], position: 120000, duration: 2400000, updatedAt: 200}
  ], 30);

  assert.strictEqual(migrated.length, 1, 'una serie deve produrre una sola voce CW');
  assert.strictEqual(migrated[0].schema, 2, 'la voce deve essere migrata allo schema corrente');
  assert.strictEqual(migrated[0].key, 'tv_serietest');
  assert.strictEqual(migrated[0].item.episode, 3, 'deve vincere la riproduzione aggiornata piu recentemente');
  assert.strictEqual(migrated[0].position, 120000, 'il progresso non va scelto in base al valore massimo');
}());

(function breaksTimestampTiesUsingTheMostAdvancedProgress() {
  var movie = {contentType: 'movie', title: 'Film Test'};
  var migrated = flow.migrateEntries([
    {key: 'old-a', item: movie, position: 10000, duration: 100000, updatedAt: 50},
    {key: 'old-b', item: movie, position: 30000, duration: 100000, updatedAt: 50}
  ], 30);
  assert.strictEqual(migrated.length, 1);
  assert.strictEqual(migrated[0].position, 30000);
}());

(function neverMigratesLivePlaybackIntoContinueWatching() {
  var migrated = flow.migrateEntries([
    {key: 'live_rai1', item: {isLive: true, contentType: 'live', title: 'Rai 1'}, position: 20000, updatedAt: 10}
  ], 30);
  assert.deepStrictEqual(migrated, []);
}());

(function migratesLegacyEpisodesWithoutAStoredParent() {
  var migrated = flow.migrateEntries([
    {key: 'legacy-a', item: {contentType: 'episode', fulltitle: 'Legacy Show 1x02 - Due', season: 1, episode: 2}, updatedAt: 10},
    {key: 'legacy-b', item: {contentType: 'episode', fulltitle: 'Legacy Show 1x03 - Tre', season: 1, episode: 3}, updatedAt: 20}
  ], 30);
  assert.strictEqual(migrated.length, 1);
  assert.strictEqual(migrated[0].key, 'tv_legacyshow');
  assert.strictEqual(migrated[0].item.episode, 3);
}());

(function crossesFromLastEpisodeOfASeasonToTheNextSeason() {
  var s1e2 = episode('Serie Test', 1, 2);
  var s1e3 = episode('Serie Test', 1, 3);
  var s2e1 = episode('Serie Test', 2, 1);
  var s2e2 = episode('Serie Test', 2, 2);
  var normalized = flow.normalizeEpisodeQueue([s2e2, s1e3, s2e1, s1e2, s1e3], s1e3);

  assert.deepStrictEqual(normalized.items.map(function (item) { return item.season + 'x' + item.episode; }),
    ['1x2', '1x3', '2x1', '2x2']);
  assert.strictEqual(flow.nextEpisode(normalized.items, normalized.index, s1e3).video_id, s2e1.video_id,
    'dopo il finale di stagione deve partire il primo episodio della stagione seguente');
}());

(function showsTheOverlayOnlyDuringTheLastMinuteWhenANextEpisodeExists() {
  var duration = 30 * 60 * 1000;
  assert.strictEqual(flow.shouldShowUpNext(duration - 60001, duration, true, false, 60000), false);
  assert.strictEqual(flow.shouldShowUpNext(duration - 60000, duration, true, false, 60000), true);
  assert.strictEqual(flow.shouldShowUpNext(duration - 1000, duration, false, false, 60000), false);
  assert.strictEqual(flow.shouldShowUpNext(duration - 1000, duration, true, true, 60000), false);
}());

(function completionKeepsTheSeriesOnTheNextEpisodeAtKodiThreshold() {
  var fs = require('fs');
  var path = require('path');
  var main = fs.readFileSync(path.resolve(__dirname, '..', 'main.js'), 'utf8');
  assert.ok(/var CW_COMPLETE_PERCENT = 97;/.test(main),
    'Tizen deve usare la soglia CW del 97% come Kodi e Android');
  assert.ok(/position >= duration \* CW_COMPLETE_PERCENT \/ 100[\s\S]*nextEpisodeItem\(\)[\s\S]*saveContinueWatching\(completedNext, 0, 0, true\)/.test(main),
    'un episodio completato deve spostare il CW al successivo');
  assert.ok(/var completedNext = isEpisode\(state\.playerItem\)[\s\S]*saveContinueWatching\(completedNext, 0, 0, true\)/.test(main),
    'la fine naturale deve conservare il prossimo episodio anche con autoplay annullato');
}());

console.log('CW flow Tizen: 9 verifiche superate');
