'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var source = fs.readFileSync(path.resolve(__dirname, '..', 'standalone.js'), 'utf8');
var helpers = source.match(/function absoluteUrl[\s\S]*?(?=\n  function queryString)/);
var rewrite = source.match(/function rewriteHost[\s\S]*?(?=\n  function dataPage)/);
assert.ok(helpers && rewrite, 'helper URL legacy mancanti');

var context = {decodeURIComponent: decodeURIComponent, encodeURIComponent: encodeURIComponent, String: String, RegExp: RegExp};
vm.runInNewContext(helpers[0] + '\n' + rewrite[0], context);

assert.strictEqual(context.originOf('https://streamingcommunityz.tools/it/movies'), 'https://streamingcommunityz.tools');
assert.strictEqual(context.hostOf('https://streamingcommunityz.tools/it'), 'streamingcommunityz.tools');
assert.strictEqual(context.absoluteUrl('/it/tv-shows', 'https://streamingcommunityz.tools/it/movies'), 'https://streamingcommunityz.tools/it/tv-shows');
assert.strictEqual(context.rewriteHost('https://streamingcommunityz.pizza/it/watch/12?x=1', 'https://streamingcommunityz.tools'), 'https://streamingcommunityz.tools/it/watch/12?x=1');
assert.strictEqual(context.queryValue(context.setQueryValue('https://video.test/master.m3u8?a=1', 'token', 'x y'), 'token'), 'x y');
assert.strictEqual((source.match(/new URL\s*\(/g) || []).length, 0, 'standalone non deve usare URL parzialmente implementato su Tizen 2.4');

console.log('URL legacy Tizen: 6 verifiche superate');
