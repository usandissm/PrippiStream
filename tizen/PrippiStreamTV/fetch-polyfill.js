(function (global) {
  'use strict';

  if (typeof global.WeakSet !== 'function') {
    global.WeakSet = function LegacyWeakSet(iterable) {
      this._items = [];
      if (iterable && typeof iterable.forEach === 'function') {
        var self = this;
        iterable.forEach(function (value) { self.add(value); });
      }
    };
    global.WeakSet.prototype.add = function (value) {
      if ((typeof value !== 'object' && typeof value !== 'function') || value === null) throw new TypeError('Invalid value used in weak set');
      if (!this.has(value)) this._items.push(value);
      return this;
    };
    global.WeakSet.prototype.has = function (value) { return this._items.indexOf(value) >= 0; };
    global.WeakSet.prototype.delete = function (value) {
      var index = this._items.indexOf(value);
      if (index < 0) return false;
      this._items.splice(index, 1);
      return true;
    };
  }

  if (global.fetch) return;

  function Headers(raw) {
    this.map = {};
    var lines = String(raw || '').replace(/\r/g, '').split('\n');
    for (var i = 0; i < lines.length; i++) {
      var separator = lines[i].indexOf(':');
      if (separator <= 0) continue;
      var name = lines[i].slice(0, separator).trim().toLowerCase();
      var value = lines[i].slice(separator + 1).trim();
      this.map[name] = this.map[name] ? this.map[name] + ', ' + value : value;
    }
  }

  Headers.prototype.get = function (name) {
    name = String(name || '').toLowerCase();
    return Object.prototype.hasOwnProperty.call(this.map, name) ? this.map[name] : null;
  };

  Headers.prototype.forEach = function (callback, context) {
    for (var name in this.map) {
      if (Object.prototype.hasOwnProperty.call(this.map, name)) {
        callback.call(context, this.map[name], name, this);
      }
    }
  };

  function Response(xhr, requestUrl) {
    var status = xhr.status === 1223 ? 204 : xhr.status;
    if (status === 0 && xhr.responseText) status = 200;
    this.status = status;
    this.statusText = xhr.statusText || '';
    this.ok = this.status >= 200 && this.status < 300;
    this.url = xhr.responseURL || requestUrl;
    this.headers = new Headers(xhr.getAllResponseHeaders ? xhr.getAllResponseHeaders() : '');
    this._text = xhr.responseText === undefined ? '' : xhr.responseText;
  }

  Response.prototype.text = function () {
    return Promise.resolve(this._text);
  };

  Response.prototype.json = function () {
    var text = this._text;
    return new Promise(function (resolve, reject) {
      try { resolve(JSON.parse(text)); } catch (error) { reject(error); }
    });
  };

  global.fetch = function (input, options) {
    options = options || {};
    var url = typeof input === 'string' ? input : input.url;
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open(options.method || 'GET', url, true);
      if (options.credentials === 'include') xhr.withCredentials = true;
      var headers = options.headers || {};
      for (var name in headers) {
        if (!Object.prototype.hasOwnProperty.call(headers, name)) continue;
        try { xhr.setRequestHeader(name, headers[name]); } catch (error) {}
      }
      xhr.onload = function () { resolve(new Response(xhr, url)); };
      xhr.onerror = function () { reject(new TypeError('Richiesta di rete fallita')); };
      xhr.ontimeout = function () { reject(new TypeError('Timeout di rete')); };
      xhr.onabort = function () { reject(new TypeError('Richiesta annullata')); };
      try { xhr.send(options.body === undefined ? null : options.body); }
      catch (error) { reject(error); }
    });
  };
}(window));
