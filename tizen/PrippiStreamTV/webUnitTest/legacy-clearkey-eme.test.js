'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var source = fs.readFileSync(path.resolve(__dirname, '..', 'legacy-clearkey-eme.js'), 'utf8');

function FakeMedia() {
  this._nativeListeners = {};
  this.generateCalls = [];
  this.addCalls = [];
}
FakeMedia.prototype.addEventListener = function (type, listener) {
  if (!this._nativeListeners[type]) this._nativeListeners[type] = [];
  this._nativeListeners[type].push(listener);
};
FakeMedia.prototype.fire = function (type, values) {
  var event = Object.assign({type: type, target: this}, values || {});
  (this._nativeListeners[type] || []).forEach(function (listener) { listener(event); });
};
FakeMedia.prototype.webkitGenerateKeyRequest = function (system, initData) {
  this.generateCalls.push({system: system, initData: initData});
};
FakeMedia.prototype.webkitAddKey = function (system, key, initData, sessionId) {
  this.addCalls.push({system: system, key: key, initData: initData, sessionId: sessionId});
};

var context = {
  window: null,
  navigator: {},
  HTMLMediaElement: FakeMedia,
  Uint8Array: Uint8Array,
  ArrayBuffer: ArrayBuffer,
  Promise: Promise,
  JSON: JSON,
  Object: Object,
  Error: Error,
  setTimeout: setTimeout,
  atob: function (value) { return Buffer.from(value, 'base64').toString('binary'); }
};
context.window = context;
vm.runInNewContext(source, context, {filename: 'legacy-clearkey-eme.js'});

assert.strictEqual(context.__PRIPPI_LEGACY_CLEARKEY_EME__, true, 'il ponte legacy deve installarsi');
assert.strictEqual(typeof context.navigator.requestMediaKeySystemAccess, 'function');
assert.strictEqual(typeof FakeMedia.prototype.setMediaKeys, 'function');

(async function () {
  var access = await context.navigator.requestMediaKeySystemAccess('org.w3.clearkey', [{}]);
  var keys = await access.createMediaKeys(), video = new FakeMedia();
  await video.setMediaKeys(keys);
  var session = keys.createSession('temporary');
  var kid = Buffer.from('00112233445566778899aabbccddeeff', 'hex');
  var request = Buffer.from(JSON.stringify({kids: [kid.toString('base64url')]}));
  var message = null;
  session.addEventListener('message', function (event) { message = event; });
  await session.generateRequest('keyids', request);
  assert.strictEqual(video.generateCalls[0].system, 'webkit-org.w3.clearkey');
  video.fire('webkitkeymessage', {sessionId: '7', message: request});
  assert.ok(message && message.messageType === 'license-request', 'la richiesta legacy deve diventare un evento EME');
  var key = Buffer.from('ffeeddccbbaa99887766554433221100', 'hex');
  var update = session.update(Buffer.from(JSON.stringify({keys: [{
    kty: 'oct', kid: kid.toString('base64url'), k: key.toString('base64url')
  }]})));
  video.fire('webkitkeyadded', {sessionId: '7'});
  await update;
  assert.strictEqual(video.addCalls[0].system, 'webkit-org.w3.clearkey');
  assert.strictEqual(video.addCalls[0].sessionId, '7');
  assert.strictEqual(session.keyStatuses._status, 'usable');
  console.log('Ponte ClearKey EME legacy: 9 verifiche superate');
}()).catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
