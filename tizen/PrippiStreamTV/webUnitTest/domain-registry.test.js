'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var appRoot = path.resolve(__dirname, '..');
var repoRoot = path.resolve(appRoot, '..', '..');
var standalone = fs.readFileSync(path.join(appRoot, 'standalone.js'), 'utf8');
var registry = JSON.parse(fs.readFileSync(path.join(repoRoot, 'channels.json'), 'utf8'));
var match = standalone.match(/var SC_FALLBACKS = \[\s*'([^']+)'/);

assert.ok(match, 'lista fallback SC mancante');
assert.strictEqual(match[1], 'https://streamingcommunityz.tools');
assert.strictEqual(registry.direct.streamingcommunity, match[1]);
assert.strictEqual(registry.findhost.streamingcommunity, match[1]);
assert.ok(/\[SC_FALLBACKS\[0\],\s*localStorage\.getItem\(HOST_KEY\),\s*remote\]/.test(standalone),
  'il dominio diretto deve essere provato prima di cache e redirect remoti');

console.log('Registro domini SC Tizen: 5 verifiche superate');
