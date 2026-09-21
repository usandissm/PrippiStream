'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var root = path.resolve(__dirname, '..');
var index = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
var modern = fs.readFileSync(path.join(root, 'css', 'style.css'), 'utf8');
var legacy = fs.readFileSync(path.join(root, 'css', 'style-legacy.css'), 'utf8');
var layout = fs.readFileSync(path.join(root, 'css', 'legacy-layout.css'), 'utf8');
var main = fs.readFileSync(path.join(root, 'main.js'), 'utf8');
var fetchPolyfill = fs.readFileSync(path.join(root, 'fetch-polyfill.js'), 'utf8');

(function selectsTheRightEngineWithoutChangingTheMarkup() {
  assert.ok(/CSS\.supports\('--prippi-ui-test',\s*'0'\)/.test(index));
  assert.ok(/supportsModernCss\s*\?\s*'style\.css'\s*:\s*'style-legacy\.css'/.test(index));
  assert.ok(/legacy-layout\.css/.test(index));
}());

(function legacyPaletteAndMetricsAreGeneratedFromTheCanonicalUi() {
  assert.strictEqual(/var\(--/.test(legacy), false, 'Tizen 2.4 non interpreta le custom properties');
  ['#07101d', '#45dfbf', '350px', '236px'].forEach(function (token) {
    assert.ok(legacy.indexOf(token) >= 0, 'token grafico canonico mancante: ' + token);
  });
  assert.ok(/--hero-height:\s*350px/.test(modern), 'la sorgente moderna deve restare canonica');
}());

(function legacyLayoutReplacesUnsupportedGeometry() {
  assert.ok(/\.main\s*\{[^}]*left:\s*236px/s.test(layout));
  assert.ok(/\.content\s*\{[^}]*height:\s*944px/s.test(layout));
  assert.ok(/\.home-scroll\s*\{[^}]*top:\s*375px/s.test(layout));
  assert.ok(/\.catalog\s*\{[^}]*display:\s*-webkit-flex/s.test(layout));
  assert.ok(/\.catalog \.card\s*\{[^}]*width:\s*calc\(20% - 20px\)/s.test(layout));
  assert.ok(/\.episode-row[^}]*display:\s*-webkit-flex/s.test(layout));
  assert.ok(/\.player-top[^}]*display:\s*-webkit-flex/s.test(layout));
}());

(function everyUnsupportedModernRuleHasAnExplicitFallback() {
  var required = [
    '.app-shell', '.rail', '.rail-nav', '.main', '.home-layout', '.hero-art',
    '.cards', '.card.live', '.catalog', '.search-box', '.empty-state',
    '.settings-grid', '.setting', '.overlay', '.detail-layout', '.detail-meta',
    '.actions', '.episodes-header', '.season-picker', '.episode-list',
    '.episode-row', '.episode-copy', '.episode-play', '.player', '#html-player',
    '#avplay', '#embed-player', '.player-ui', '.player-shade', '.player-top',
    '.player-icon-button', '.player-status', '.player-center', '.timeline-wrap',
    '.player-live-info', '.player-actions', '.up-next-actions'
  ];
  required.forEach(function (selector) {
    assert.ok(layout.indexOf(selector) >= 0, 'fallback legacy mancante per ' + selector);
  });
}());

(function embeddedVideoUsesOldWebkitSafeEdges() {
  assert.strictEqual(/cssText\s*=\s*[^;]*inset:/.test(main), false);
  assert.ok(/position:absolute;top:0;right:0;bottom:0;left:0/.test(main));
}());

(function networkingIsAvailableBeforeStandaloneBoots() {
  var polyfillPosition = index.indexOf('fetch-polyfill.js');
  assert.ok(polyfillPosition >= 0, 'polyfill fetch mancante');
  assert.ok(polyfillPosition < index.indexOf('standalone.js'), 'fetch deve esistere prima del provider standalone');
  assert.ok(/XMLHttpRequest/.test(fetchPolyfill));
  assert.ok(/hls\.legacy\.min\.js/.test(index), 'runtime HLS legacy mancante');
  assert.ok(polyfillPosition < index.indexOf('hls.legacy.min.js'), 'i polyfill devono precedere Hls.js legacy');
}());

console.log('Compatibilita UI Tizen 2.4: 6 gruppi di verifiche superati');
