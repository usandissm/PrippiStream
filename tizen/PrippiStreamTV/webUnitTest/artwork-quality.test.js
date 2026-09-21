'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var root = path.resolve(__dirname, '..');
var main = fs.readFileSync(path.join(root, 'main.js'), 'utf8');
var standalone = fs.readFileSync(path.join(root, 'standalone.js'), 'utf8');

assert.ok(/TMDB[^\n]*\/t\/p\/w780/.test(standalone) || /\/t\/p\/w780/.test(standalone),
  'i poster TMDB devono essere richiesti almeno a 780px');
assert.ok(/ARTWORK_CACHE_MAX_AGE/.test(standalone), 'la grafica HD deve avere una cache persistente');
assert.ok(/route === '\/artwork'/.test(standalone), 'route artwork standalone mancante');
assert.ok(/queueArtworkUpgrade\(focused, element, true\)/.test(main), 'upgrade prioritario al focus mancante');
assert.ok(/queueArtworkUpgrade\(state\.items\[element\.getAttribute\('data-item'\)\], element, false\)/.test(main),
  'precaricamento HD automatico delle card mancante');
assert.ok(/artworkWorkerBusy/.test(main) && /scheduleArtworkWorker\(550\)/.test(main),
  'la coda HD deve restare seriale sui dispositivi lenti');
assert.ok(/detail-poster[\s\S]*image\(updated\)/.test(main), 'il dettaglio deve sostituire il poster SD con quello HD');

console.log('Qualita artwork Tizen: 7 verifiche superate');
