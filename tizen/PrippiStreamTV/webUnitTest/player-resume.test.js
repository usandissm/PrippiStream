'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var main = fs.readFileSync(path.resolve(__dirname, '..', 'main.js'), 'utf8');
var match = main.match(/function applyHtmlResume\(video\)\s*\{([\s\S]*?)\n  \}/);
assert.ok(match, 'funzione di ripresa HTML/HLS mancante');

var applyResume = new Function('state', 'CW_MIN_PROGRESS_MS', 'video', match[1]);
var state = {pendingResumeMs: 120000};
var video = {duration: NaN, currentTime: 0};

assert.strictEqual(applyResume(state, 10000, video), false, 'senza metadata il seek deve essere rimandato');
assert.strictEqual(state.pendingResumeMs, 120000, 'la posizione CW non va consumata prima dei metadata');
assert.strictEqual(video.currentTime, 0);

video.duration = 3600;
assert.strictEqual(applyResume(state, 10000, video), true, 'con durata valida il seek deve riuscire');
assert.strictEqual(video.currentTime, 120, 'i millisecondi CW devono diventare secondi video');
assert.strictEqual(state.pendingResumeMs, 0, 'la posizione va consumata soltanto dopo il seek');

video.currentTime = 125;
assert.strictEqual(applyResume(state, 10000, video), false, 'un seek gia applicato non va ripetuto');
assert.strictEqual(video.currentTime, 125);

var hlsBody = main.match(/function openHlsJs\(url, item, headers\)\s*\{([\s\S]*?)\n  \}/);
assert.ok(hlsBody && /video\.onloadedmetadata\s*=\s*function\s*\(\)\s*\{\s*applyHtmlResume\(video\)/.test(hlsBody[1]),
  'Hls.js deve riprovare la posizione CW quando arrivano i metadata');

var avMatch = main.match(/function applyAvResume\(\)\s*\{([\s\S]*?)\n  \}/);
assert.ok(avMatch, 'funzione di ripresa AVPlay mancante');
var current = 0, timelineUpdates = 0;
var avState = {pendingResumeMs: 120000, playerEngine: 'avplay', avResumeInFlight: false, avResumeAttempts: 0};
var avplay = {
  getDuration: function () { return 3600000; },
  getCurrentTime: function () { return current; },
  seekTo: function (target, success) { current = target; success(); }
};
var applyAv = new Function('state', 'CW_MIN_PROGRESS_MS', 'avplay', 'setTimeout', 'updateTimeline', avMatch[1]);
assert.strictEqual(applyAv(avState, 10000, avplay, function (callback) { callback(); }, function () { timelineUpdates += 1; }), true,
  'AVPlay deve tentare il seek dopo l\'avvio');
assert.strictEqual(current, 120000, 'AVPlay deve ricevere la posizione CW in millisecondi');
assert.strictEqual(avState.pendingResumeMs, 0, 'la posizione AVPlay va consumata solo dopo la verifica del seek');
assert.strictEqual(timelineUpdates, 1, 'la timeline deve aggiornarsi dopo la ripresa');
assert.ok(/oncurrentplaytime:[\s\S]*applyAvResume\(\)/.test(main),
  'AVPlay deve ritentare la ripresa al primo avanzamento reale');
assert.ok(/state\.pendingResumeMs < CW_MIN_PROGRESS_MS[\s\S]*saveContinueWatching/.test(main),
  'un avvio a zero non deve sovrascrivere la posizione CW prima del seek');

console.log('Ripresa CW Tizen: 14 verifiche superate');
