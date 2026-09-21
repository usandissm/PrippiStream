(function (global) {
  'use strict';

  var mediaPrototype = global.HTMLMediaElement && global.HTMLMediaElement.prototype;
  var hasModernEme = global.navigator &&
    typeof global.navigator.requestMediaKeySystemAccess === 'function' &&
    mediaPrototype && typeof mediaPrototype.setMediaKeys === 'function';
  if (hasModernEme || !mediaPrototype ||
      typeof mediaPrototype.webkitGenerateKeyRequest !== 'function' ||
      typeof mediaPrototype.webkitAddKey !== 'function') return;

  var MODERN_KEY_SYSTEM = 'org.w3.clearkey';
  var LEGACY_KEY_SYSTEM = 'webkit-org.w3.clearkey';

  function bytes(value) {
    if (value instanceof Uint8Array) return new Uint8Array(value);
    if (value && value.buffer) return new Uint8Array(value.buffer, value.byteOffset || 0, value.byteLength);
    return new Uint8Array(value || 0);
  }

  function copyBuffer(value) {
    var source = bytes(value), copy = new Uint8Array(source.length), index;
    for (index = 0; index < source.length; index += 1) copy[index] = source[index];
    return copy.buffer;
  }

  function ascii(value) {
    var source = bytes(value), output = '', index;
    for (index = 0; index < source.length; index += 1) output += String.fromCharCode(source[index]);
    return output;
  }

  function base64Url(value) {
    value = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
    while (value.length % 4) value += '=';
    var binary = atob(value), output = new Uint8Array(binary.length), index;
    for (index = 0; index < binary.length; index += 1) output[index] = binary.charCodeAt(index);
    return output;
  }

  function eventTarget(target) {
    target._listeners = {};
    target.addEventListener = function (type, listener) {
      if (!this._listeners[type]) this._listeners[type] = [];
      if (this._listeners[type].indexOf(listener) < 0) this._listeners[type].push(listener);
    };
    target.removeEventListener = function (type, listener) {
      var values = this._listeners[type] || [], index = values.indexOf(listener);
      if (index >= 0) values.splice(index, 1);
    };
    target.dispatchEvent = function (event) {
      event.target = event.target || this;
      (this._listeners[event.type] || []).slice().forEach(function (listener) {
        if (typeof listener === 'function') listener.call(target, event);
        else if (listener && listener.handleEvent) listener.handleEvent(event);
      });
      return true;
    };
  }

  function LegacyKeyStatuses() {
    this._kid = null;
    this._status = 'status-pending';
  }
  Object.defineProperty(LegacyKeyStatuses.prototype, 'size', {
    get: function () { return this._kid ? 1 : 0; }
  });
  LegacyKeyStatuses.prototype.forEach = function (callback, context) {
    if (this._kid) callback.call(context, this._status, copyBuffer(this._kid), this);
  };
  LegacyKeyStatuses.prototype.get = function () { return this._kid ? this._status : undefined; };
  LegacyKeyStatuses.prototype.has = function () { return !!this._kid; };

  function LegacyMediaKeySession(mediaKeys) {
    eventTarget(this);
    this._mediaKeys = mediaKeys;
    this._initData = null;
    this._kid = null;
    this._updateResolve = null;
    this._updateReject = null;
    this.sessionId = '';
    this.expiration = NaN;
    this.keyStatuses = new LegacyKeyStatuses();
    var closeResolve;
    this.closed = new Promise(function (resolve) { closeResolve = resolve; });
    this._closeResolve = closeResolve;
  }

  LegacyMediaKeySession.prototype.generateRequest = function (initDataType, initData) {
    var session = this;
    this._initData = bytes(initData);
    if (initDataType === 'keyids') {
      try {
        var request = JSON.parse(ascii(this._initData));
        if (request.kids && request.kids[0]) this._kid = base64Url(request.kids[0]);
      } catch (error) {}
    }
    if (this._kid) this.keyStatuses._kid = this._kid;
    return this._mediaKeys._generate(session);
  };

  LegacyMediaKeySession.prototype.update = function (response) {
    var session = this, payload, entry;
    try {
      payload = JSON.parse(ascii(response));
      entry = payload && payload.keys && payload.keys[0];
      if (!entry || !entry.k) throw new Error('Risposta ClearKey priva di chiave');
      var key = base64Url(entry.k), kid = entry.kid ? base64Url(entry.kid) : session._kid;
      if (kid) { session._kid = kid; session.keyStatuses._kid = kid; }
      return new Promise(function (resolve, reject) {
        session._updateResolve = resolve;
        session._updateReject = reject;
        try {
          session._mediaKeys._video.webkitAddKey(
            LEGACY_KEY_SYSTEM, key, null, session.sessionId || ''
          );
          setTimeout(function () {
            if (session._updateResolve) session._keyAdded();
          }, 1500);
        } catch (error) {
          session._updateResolve = null;
          session._updateReject = null;
          reject(error);
        }
      });
    } catch (error) { return Promise.reject(error); }
  };

  LegacyMediaKeySession.prototype._keyAdded = function () {
    this.keyStatuses._status = 'usable';
    this.dispatchEvent({type: 'keystatuseschange'});
    if (this._updateResolve) this._updateResolve();
    this._updateResolve = null;
    this._updateReject = null;
  };
  LegacyMediaKeySession.prototype.load = function () { return Promise.resolve(false); };
  LegacyMediaKeySession.prototype.remove = function () { return this.close(); };
  LegacyMediaKeySession.prototype.close = function () {
    try {
      if (this._mediaKeys._video.webkitCancelKeyRequest && this.sessionId) {
        this._mediaKeys._video.webkitCancelKeyRequest(LEGACY_KEY_SYSTEM, this.sessionId);
      }
    } catch (error) {}
    this._closeResolve();
    return Promise.resolve();
  };

  function LegacyMediaKeys() {
    this._video = null;
    this._sessions = [];
    this._pending = [];
  }
  LegacyMediaKeys.prototype.createSession = function () {
    var session = new LegacyMediaKeySession(this);
    this._sessions.push(session);
    return session;
  };
  LegacyMediaKeys.prototype.setServerCertificate = function () { return Promise.resolve(false); };
  LegacyMediaKeys.prototype._find = function (sessionId) {
    var index;
    for (index = 0; index < this._sessions.length; index += 1) {
      if (String(this._sessions[index].sessionId) === String(sessionId)) return this._sessions[index];
    }
    return this._pending[0] || this._sessions[0] || null;
  };
  LegacyMediaKeys.prototype._attach = function (video) {
    var keys = this;
    this._video = video;
    video.addEventListener('webkitkeymessage', function (event) {
      var session = keys._find(event.sessionId);
      if (!session) return;
      session.sessionId = String(event.sessionId || session.sessionId || '');
      var index = keys._pending.indexOf(session);
      if (index >= 0) keys._pending.splice(index, 1);
      session.dispatchEvent({
        type: 'message', messageType: 'license-request', message: copyBuffer(event.message || session._initData)
      });
    });
    video.addEventListener('webkitkeyadded', function (event) {
      var session = keys._find(event.sessionId);
      if (session) session._keyAdded();
    });
    video.addEventListener('webkitkeyerror', function (event) {
      var session = keys._find(event.sessionId), error = new Error('Errore EME legacy ClearKey');
      if (session && session._updateReject) session._updateReject(error);
      if (session) session.dispatchEvent({type: 'error', error: error});
    });
  };
  LegacyMediaKeys.prototype._generate = function (session) {
    var keys = this;
    if (this._pending.indexOf(session) < 0) this._pending.push(session);
    return new Promise(function (resolve, reject) {
      var attempts = 0;
      function generate() {
        attempts += 1;
        if (!keys._video) {
          if (attempts < 80) { setTimeout(generate, 50); return; }
          reject(new Error('Elemento video ClearKey non collegato'));
          return;
        }
        try {
          keys._video.webkitGenerateKeyRequest(LEGACY_KEY_SYSTEM, session._initData);
          resolve();
        } catch (error) {
          if (attempts < 80) { setTimeout(generate, 50); return; }
          reject(error);
        }
      }
      generate();
    });
  };

  function LegacyMediaKeySystemAccess(configuration) {
    this.keySystem = MODERN_KEY_SYSTEM;
    this._configuration = configuration || {};
  }
  LegacyMediaKeySystemAccess.prototype.getConfiguration = function () {
    var source = this._configuration;
    return {
      initDataTypes: source.initDataTypes || ['cenc', 'keyids'],
      audioCapabilities: source.audioCapabilities || [],
      videoCapabilities: source.videoCapabilities || [],
      distinctiveIdentifier: 'optional', persistentState: 'optional',
      sessionTypes: ['temporary'], label: source.label || ''
    };
  };
  LegacyMediaKeySystemAccess.prototype.createMediaKeys = function () {
    return Promise.resolve(new LegacyMediaKeys());
  };

  global.navigator.requestMediaKeySystemAccess = function (keySystem, configurations) {
    if (keySystem !== MODERN_KEY_SYSTEM) return Promise.reject(new Error('Key system non supportato'));
    return Promise.resolve(new LegacyMediaKeySystemAccess(configurations && configurations[0]));
  };
  mediaPrototype.setMediaKeys = function (mediaKeys) {
    this._prippiMediaKeys = mediaKeys || null;
    if (mediaKeys) mediaKeys._attach(this);
    return Promise.resolve();
  };
  try {
    Object.defineProperty(mediaPrototype, 'mediaKeys', {
      configurable: true, get: function () { return this._prippiMediaKeys || null; }
    });
  } catch (error) {}

  global.MediaKeys = LegacyMediaKeys;
  global.MediaKeySystemAccess = LegacyMediaKeySystemAccess;
  global.MediaKeySession = LegacyMediaKeySession;
  global.__PRIPPI_LEGACY_CLEARKEY_EME__ = true;
}(window));
