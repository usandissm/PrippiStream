'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var main = fs.readFileSync(path.resolve(__dirname, '..', 'main.js'), 'utf8');
var standalone = fs.readFileSync(path.resolve(__dirname, '..', 'standalone.js'), 'utf8');
var openPlayer = main.match(/function openPlayer\(url, item, headers, manifest\)\s*\{([\s\S]*?)\n  \}/);

assert.ok(openPlayer, 'selezione player mancante');
var body = openPlayer[1];
assert.ok(/if \(directHlsAvplay\)[\s\S]*openAvPlayer\(url, item, headers \|\| \{\}\)/.test(body),
  'tutti gli HLS diretti sui TV Samsung devono usare AVPlay');
assert.ok(/video\.onerror[\s\S]*openAvPlayer\(url, item, headers \|\| \{\}\)/.test(body),
  'AVPlay deve restare disponibile come fallback del video HTML');
assert.ok(/if \(hls && !nativeHlsWithoutAvplay && window\.Hls && Hls\.isSupported\(\)\)/.test(body),
  'Hls.js deve restare disponibile quando AVPlay non è utilizzabile');
assert.ok(/nativeHlsWithoutAvplay/.test(body) && /directHlsAvplay/.test(body),
  'il video HTML deve restare il fallback quando AVPlay non esiste');
assert.ok(/function setAvplayFullscreen\(\)[\s\S]*PLAYER_DISPLAY_MODE_LETTER_BOX/.test(main),
  'AVPlay deve usare la superficie fisica del TV senza deformare il video');
assert.ok(/player\.className = state\.playerLive \? 'player live' : 'player ondemand'/.test(main));
assert.ok(/function isLiveMedia[\s\S]*String\(explicit\)\.toLowerCase\(\) === 'true'/.test(main));
assert.ok(/\.player\.live \.timeline-wrap\s*\{\s*display:\s*none/.test(
  fs.readFileSync(path.resolve(__dirname, '..', 'css', 'style.css'), 'utf8')));
assert.ok(/response\.embed_url && !isNativeMedia\(url, response\.manifest_type\)[\s\S]*openEmbed\(response\.embed_url, target\)/.test(main),
  'solo i fallback non nativi devono usare il player incorporato su Tizen legacy');
assert.ok(/xhrSetup:[\s\S]*xhr\.setRequestHeader\(name, headers\[name\]\)/.test(main),
  'gli HLS protetti devono inoltrare gli header del provider');
assert.ok(/live_source:\s*'daddy',[\s\S]*embed_url:\s*player\.pageUrl/.test(standalone),
  'il resolver Daddy deve conservare la pagina stream esterna compatibile');
assert.ok(/live_source:\s*'freeshot',[\s\S]*embed_url:\s*'https:\/\/popcdn\.day\/player\/'/.test(standalone),
  'il resolver Freeshot deve conservare la pagina player compatibile');

console.log('Selezione player Tizen: 11 verifiche superate');
