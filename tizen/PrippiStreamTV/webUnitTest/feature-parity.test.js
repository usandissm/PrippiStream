'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var root = path.resolve(__dirname, '..');
var main = fs.readFileSync(path.join(root, 'main.js'), 'utf8');
var flow = fs.readFileSync(path.join(root, 'cw-flow.js'), 'utf8');
var prefs = fs.readFileSync(path.join(root, 'media-prefs.js'), 'utf8');
var standalone = fs.readFileSync(path.join(root, 'standalone.js'), 'utf8');

assert.ok(/var CW_COMPLETE_PERCENT = 97;/.test(main),
  'CW Tizen deve usare la stessa soglia di completamento di Android e Kodi');
assert.ok(/position >= duration \* CW_COMPLETE_PERCENT \/ 100[\s\S]*saveContinueWatching\(completedNext, 0, 0, true\)/.test(main),
  'al 97% il CW di una serie deve avanzare al prossimo episodio');
assert.ok(/document\.addEventListener\('visibilitychange'[\s\S]*suspendPlaybackForVisibility/.test(main) &&
  /window\.addEventListener\('pagehide'[\s\S]*persistActivePlayback/.test(main) &&
  /window\.addEventListener\('beforeunload'[\s\S]*persistActivePlayback/.test(main),
  'il progresso deve essere salvato anche quando Tizen sospende o chiude la pagina');
assert.ok(/setScreenSaver\(screenState/.test(main) && /SCREEN_SAVER_OFF/.test(main) && /SCREEN_SAVER_ON/.test(main),
  'lo screensaver Samsung deve essere disattivato solo durante la riproduzione');
assert.ok(/hasContinue[\s\S]*Continua [\s\S]*episodeCode/.test(main) &&
  /hasContinue\) document\.getElementById\('detail-resume'\)/.test(main),
  'un episodio avanzato a posizione zero deve restare riproducibile dal pulsante Continua');
assert.ok(/savedSeason[\s\S]*seasons\.indexOf\(savedSeason\)/.test(main),
  'il selettore episodi deve aprire la stagione salvata nel CW');
assert.ok(/detail-remove-cw/.test(main) && /removeContinueWatching/.test(main),
  'la rimozione manuale dal CW deve essere disponibile');
assert.ok(/SEARCH_HISTORY_KEY/.test(main) && /saveSearchHistory/.test(main) && /clearSearchHistory/.test(main),
  'la cronologia ricerche deve essere persistente e cancellabile');
assert.ok(/persistTrackPreference/.test(main) && /applyStoredTrackPreferences/.test(main) && /STORAGE_KEY/.test(prefs),
  'audio e sottotitoli devono conservare le preferenze come su Android');
assert.ok(/normalizeEpisodeQueue/.test(flow) && /compareEpisodes/.test(flow),
  'la coda episodi deve essere ordinata tra stagioni');
assert.ok(/request\('\/trailer'/.test(main) && /function tmdbTrailer/.test(standalone) && /_app_trailer/.test(main),
  'il trailer deve essere disponibile senza contaminare il Continua a guardare');

console.log('Parità funzioni Android/Tizen: 11 verifiche superate');
