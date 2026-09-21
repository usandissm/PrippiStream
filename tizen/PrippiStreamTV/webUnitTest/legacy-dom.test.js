'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var source = fs.readFileSync(path.resolve(__dirname, '..', 'standalone.js'), 'utf8');
var helper = source.match(/function parseHtml\(html\)\s*\{([\s\S]*?)\n  \}/);

assert.ok(helper, 'fallback parser HTML mancante');
assert.ok(/parsed && parsed\.querySelector/.test(helper[1]));
assert.ok(/document\.createElement\('div'\)/.test(helper[1]));
assert.ok(/container\.innerHTML/.test(helper[1]));
assert.strictEqual((source.match(/new DOMParser\(\)\.parseFromString/g) || []).length, 1,
  'tutti i parser provider devono passare dal fallback Tizen 2.4');
assert.ok(/function parsePage\(html\)[\s\S]*?data-page=[\s\S]*?document\.createElement\('textarea'\)/.test(source),
  'data-page deve essere estratto senza costruire un DOM da 300 KB');
assert.ok(/var doc = parseHtml\(source\)/.test(source), 'il fallback DOM resta disponibile per pagine non-Inertia');

console.log('Parser HTML legacy Tizen: 7 verifiche superate');
