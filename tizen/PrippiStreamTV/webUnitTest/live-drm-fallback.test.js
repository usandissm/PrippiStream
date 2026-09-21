'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var main = fs.readFileSync(path.resolve(__dirname, '..', 'main.js'), 'utf8');
var standalone = fs.readFileSync(path.resolve(__dirname, '..', 'standalone.js'), 'utf8');

assert.ok(/openClearKeyPlayer\(url, target, response\)\.catch\(function \(drmError\)/.test(main),
  'un errore ClearKey deve attivare il fallback a tempo di riproduzione');
assert.ok(/request\('\/resolve-live-fallback', \{item: target\}\)/.test(main),
  'il player deve chiedere una sorgente live alternativa');
assert.ok(/fallback\.embed_url && !isNativeMedia\(fallbackUrl, fallback\.manifest_type\)[\s\S]*openEmbed\(fallback\.embed_url, target\)/.test(main),
  'soltanto un fallback non nativo deve aprire la pagina provider');
assert.ok(/function resolveLiveFallback\(item\)/.test(standalone),
  'il runtime standalone deve esporre il resolver alternativo');
assert.ok(/item\.sport_fs \? resolveFreeshotLive\(item\)/.test(standalone),
  'Freeshot deve precedere Daddy quando disponibile');
assert.ok(/fallback = fallback\.catch\(function \(\) \{ return resolveDaddyLive\(item\); \}\)/.test(standalone),
  'Daddy deve restare il fallback finale');
assert.ok(/route === '\/resolve-live-fallback'/.test(standalone),
  'la route fallback deve essere registrata');
assert.ok(/new Promise\(function \(resolve, reject\)[\s\S]*Timeout avvio DASH\/DRM/.test(main),
  'ClearKey deve fallire esplicitamente se il video non parte');
assert.ok(/modernEme[\s\S]*ClearKey EME moderno non disponibile su Tizen 2\.4/.test(main),
  'Tizen 2.4 senza EME moderno deve passare subito alla sorgente alternativa');
assert.ok(/pageUrl:[\s\S]*embed_url:\s*player\.pageUrl/.test(standalone),
  'Daddy deve aprire la pagina esterna per mantenere il referrer richiesto');

console.log('Fallback DRM live Tizen: 10 verifiche superate');
