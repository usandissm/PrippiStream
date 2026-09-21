'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var source = fs.readFileSync(path.resolve(__dirname, '..', 'fetch-polyfill.js'), 'utf8');
assert.ok(/global\.WeakSet/.test(source), 'polyfill WeakSet mancante per Hls.js sui Tizen 2.4');
var lastRequest = null;

function FakeXHR() {
  lastRequest = this;
  this.status = FakeXHR.nextStatus === undefined ? 200 : FakeXHR.nextStatus;
  this.statusText = 'OK';
  this.responseText = '{"ready":true}';
  this.responseURL = 'https://example.test/final';
  this.requestHeaders = {};
}
FakeXHR.prototype.open = function (method, url) { this.method = method; this.url = url; };
FakeXHR.prototype.setRequestHeader = function (name, value) { this.requestHeaders[name] = value; };
FakeXHR.prototype.getAllResponseHeaders = function () { return 'Content-Type: application/json\r\n'; };
FakeXHR.prototype.send = function (body) { this.body = body; this.onload(); };

var context = {
  Promise: Promise,
  XMLHttpRequest: FakeXHR,
  TypeError: TypeError,
  JSON: JSON,
  Object: Object,
  String: String
};
context.window = context;
vm.runInNewContext(source, context);

assert.strictEqual(typeof context.fetch, 'function');
context.fetch('https://example.test/start', {
  method: 'POST',
  credentials: 'include',
  headers: {'Content-Type': 'application/json'},
  body: '{"test":1}'
}).then(function (response) {
  assert.strictEqual(lastRequest.method, 'POST');
  assert.strictEqual(lastRequest.withCredentials, true);
  assert.strictEqual(lastRequest.body, '{"test":1}');
  assert.strictEqual(response.ok, true);
  assert.strictEqual(response.url, 'https://example.test/final');
  assert.strictEqual(response.headers.get('content-type'), 'application/json');
  return response.json();
}).then(function (body) {
  assert.strictEqual(body.ready, true);
  FakeXHR.nextStatus = 0;
  return context.fetch('data/live_channels.json');
}).then(function (localResponse) {
  assert.strictEqual(localResponse.status, 200);
  assert.strictEqual(localResponse.ok, true);
  console.log('Fetch legacy Tizen: 10 verifiche superate');
}).catch(function (error) {
  console.error(error && error.stack || error);
  process.exitCode = 1;
});
