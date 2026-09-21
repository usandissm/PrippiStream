'use strict';

var assert = require('assert');
var prefs = require('../media-prefs.js');
var cw = require('../cw-flow.js');

function memoryStorage() {
  var values = {};
  return {
    getItem: function (key) { return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : null; },
    setItem: function (key, value) { values[key] = String(value); }
  };
}

function episode(series, season, number) {
  return {contentType: 'episode', contentSerieName: series, season: season, episode: number, title: season + 'x' + number};
}

(function sharesPreferencesAcrossEveryEpisodeAndSeason() {
  var storage = memoryStorage(), parent = {contentType: 'tvshow', title: 'Serie Test'};
  var first = episode('Serie Test', 1, 1), later = episode('Serie Test', 4, 8);
  assert.strictEqual(prefs.set(storage, first, parent, {audio_lang: 'it', sub_lang: 'eng'}, cw.continueKey), true);
  assert.deepStrictEqual(prefs.get(storage, later, parent, cw.continueKey), {audio_lang: 'ita', sub_lang: 'eng'});
}());

(function keepsMoviesIndependent() {
  var storage = memoryStorage(), first = {contentType: 'movie', title: 'Film Uno'}, second = {contentType: 'movie', title: 'Film Due'};
  prefs.set(storage, first, null, {audio_lang: 'Italian'}, cw.continueKey);
  assert.strictEqual(prefs.get(storage, second, null, cw.continueKey), null);
  assert.strictEqual(prefs.get(storage, first, null, cw.continueKey).audio_lang, 'ita');
}());

(function neverPersistsLivePreferences() {
  var storage = memoryStorage(), live = {isLive: true, contentType: 'live', title: 'Rai 1'};
  assert.strictEqual(prefs.set(storage, live, null, {audio_lang: 'ita'}, cw.continueKey), false);
  assert.strictEqual(prefs.get(storage, live, null, cw.continueKey), null);
  assert.strictEqual(storage.getItem(prefs.STORAGE_KEY), null);
  assert.strictEqual(prefs.set(storage, {_app_live: true, title: 'Sky Uno'}, null, {sub_lang: 'ita'}, cw.continueKey), false);
}());

(function persistsExplicitSubtitleOff() {
  var storage = memoryStorage(), item = {contentType: 'movie', title: 'Film'};
  prefs.set(storage, item, null, {sub_lang: prefs.SUBTITLES_OFF}, cw.continueKey);
  assert.strictEqual(prefs.get(storage, item, null, cw.continueKey).sub_lang, '__off__');
}());

(function preservesTheOtherChoiceOnPartialUpdates() {
  var storage = memoryStorage(), item = {contentType: 'movie', title: 'Film'};
  prefs.set(storage, item, null, {audio_lang: 'eng', sub_lang: 'ita'}, cw.continueKey);
  prefs.set(storage, item, null, {sub_lang: '__off__'}, cw.continueKey);
  assert.deepStrictEqual(prefs.get(storage, item, null, cw.continueKey), {audio_lang: 'eng', sub_lang: '__off__'});
}());

(function matchesIsoAliasesAndAvPlayMetadata() {
  var tracks = [
    {language: 'en-US', label: 'English'},
    {extra_info: JSON.stringify({track_lang: 'it-IT', track_name: 'Italiano'})}
  ];
  assert.strictEqual(prefs.findTrackIndex(tracks, 'ita'), 1);
  assert.strictEqual(prefs.findTrackIndex(tracks, 'English'), 0);
}());

(function usesStableLabelsWhenLanguageIsMissing() {
  var track = {label: 'Commento regista'};
  assert.strictEqual(prefs.trackPreference(track), 'label:commentoregista');
  assert.strictEqual(prefs.findTrackIndex([track], 'label:commentoregista'), 0);
}());

(function safelyFallsBackWhenTheTrackIsUnavailable() {
  assert.strictEqual(prefs.findTrackIndex([{language: 'eng'}], 'ita'), -1);
  assert.strictEqual(prefs.findTrackIndex([], 'ita'), -1);
}());

(function buildsASafeSelectionPlanForEachNewEpisode() {
  assert.deepStrictEqual(prefs.selectionPlan(
    [{language: 'eng'}, {language: 'ita'}],
    [{language: 'eng'}],
    {audio_lang: 'ita', sub_lang: 'ita'}
  ), {audioIndex: 1, subtitleIndex: null}, 'una traccia sottotitoli assente non deve essere forzata');
  assert.deepStrictEqual(prefs.selectionPlan(
    [{language: 'eng'}],
    [{language: 'ita'}],
    {audio_lang: 'ita', sub_lang: '__off__'}
  ), {audioIndex: null, subtitleIndex: -1}, 'OFF deve essere riapplicato anche se cambia il catalogo tracce');
}());

console.log('Preferenze media Tizen: 9 verifiche superate');
