(function () {
  'use strict';

  var SHELL_VERSION = '0.3.0';
  var LOCAL_REVISION = 0;
  var MANIFEST_URL = localStorage.getItem('prippi.tizen.ota.manifest') ||
    'https://raw.githubusercontent.com/usandissm/PrippiStream/main/docs/tizen/app/manifest.json';
  var CACHE_KEY = 'prippi.tizen.ota.bundle.v1';
  var ACTIVE_KEY = 'prippi.tizen.ota.active';
  var CHECK_TIMEOUT = 8000;

  function setBootStatus(text) {
    var el = document.getElementById('connection');
    if (el) el.textContent = text;
  }

  function fetchText(url, timeout) {
    return new Promise(function (resolve, reject) {
      var finished = false;
      var timer = setTimeout(function () {
        if (!finished) reject(new Error('Timeout aggiornamento'));
      }, timeout || CHECK_TIMEOUT);
      fetch(url, {cache: 'no-store'}).then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.text();
      }).then(function (text) {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        resolve(text);
      }).catch(function (error) {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  /* SHA-256 sincrono ES5: evita dipendenze da SubtleCrypto sui vecchi TV. */
  function sha256Legacy(text) {
    var ascii = unescape(encodeURIComponent(text));
    var maxWord = Math.pow(2, 32), lengthProperty = 'length', i, j;
    var result = '', words = [], asciiBitLength = ascii[lengthProperty] * 8;
    var hash = sha256Legacy.h = sha256Legacy.h || [], k = sha256Legacy.k = sha256Legacy.k || [];
    var primeCounter = k[lengthProperty], isComposite = {};
    for (var candidate = 2; primeCounter < 64; candidate++) {
      if (!isComposite[candidate]) {
        for (i = 0; i < 313; i += candidate) isComposite[i] = candidate;
        hash[primeCounter] = (Math.pow(candidate, 0.5) * maxWord) | 0;
        k[primeCounter++] = (Math.pow(candidate, 1 / 3) * maxWord) | 0;
      }
    }
    ascii += '\x80';
    while (ascii[lengthProperty] % 64 - 56) ascii += '\x00';
    for (i = 0; i < ascii[lengthProperty]; i++) {
      j = ascii.charCodeAt(i);
      if (j >> 8) throw new Error('Carattere SHA-256 non valido');
      words[i >> 2] |= j << ((3 - i) % 4) * 8;
    }
    words[words[lengthProperty]] = (asciiBitLength / maxWord) | 0;
    words[words[lengthProperty]] = asciiBitLength;
    for (j = 0; j < words[lengthProperty];) {
      var w = words.slice(j, j += 16), oldHash = hash.slice(0), a = hash[0], e = hash[4];
      for (i = 0; i < 64; i++) {
        var w15 = w[i - 15], w2 = w[i - 2];
        var s0 = i < 16 ? w[i] :
          (w[i - 16] + ((w15 >>> 7 | w15 << 25) ^ (w15 >>> 18 | w15 << 14) ^ (w15 >>> 3)) +
          w[i - 7] + ((w2 >>> 17 | w2 << 15) ^ (w2 >>> 19 | w2 << 13) ^ (w2 >>> 10))) | 0;
        w[i] = s0;
        var t1 = (e + ((e >>> 6 | e << 26) ^ (e >>> 11 | e << 21) ^ (e >>> 25 | e << 7)) +
          ((e & hash[5]) ^ ((~e) & hash[6])) + k[i] + s0) | 0;
        var t2 = (((a >>> 2 | a << 30) ^ (a >>> 13 | a << 19) ^ (a >>> 22 | a << 10)) +
          ((a & hash[1]) ^ (a & hash[2]) ^ (hash[1] & hash[2]))) | 0;
        hash = [(t1 + t2) | 0].concat(hash);
        hash[4] = (hash[4] + t1) | 0;
        hash.pop();
        a = hash[0]; e = hash[4];
      }
      for (i = 0; i < 8; i++) hash[i] = (hash[i] + oldHash[i]) | 0;
    }
    for (i = 0; i < 8; i++) {
      for (j = 3; j + 1; j--) {
        var b = (hash[i] >> (j * 8)) & 255;
        result += (b < 16 ? '0' : '') + b.toString(16);
      }
    }
    return result;
  }

  function sha256(text) {
    if (window.crypto && window.crypto.subtle && window.TextEncoder) {
      return window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)).then(function (buffer) {
        return Array.prototype.map.call(new Uint8Array(buffer), function (value) {
          return (value < 16 ? '0' : '') + value.toString(16);
        }).join('');
      });
    }
    return Promise.resolve(sha256Legacy(text));
  }

  function assetUrl(path) {
    if (/^https?:\/\//i.test(path)) return path;
    return MANIFEST_URL.replace(/[^/?#]+(?:[?#].*)?$/, '') + path;
  }

  function validateManifest(manifest) {
    if (!manifest || manifest.schema !== 1 || !manifest.files ||
        !manifest.files.html || !manifest.files.css || !manifest.files.js) {
      throw new Error('Manifest OTA non valido');
    }
    return manifest;
  }

  function downloadBundle(manifest) {
    var names = ['html', 'css', 'js'];
    return Promise.all(names.map(function (name) {
      var file = manifest.files[name];
      return fetchText(assetUrl(file.url), CHECK_TIMEOUT).then(function (content) {
        return sha256(content).then(function (digest) {
          if (digest.toLowerCase() !== String(file.sha256).toLowerCase()) {
            throw new Error('Firma SHA-256 non valida: ' + name);
          }
          return content;
        });
      });
    })).then(function (contents) {
      return {manifest: manifest, html: contents[0], css: contents[1], js: contents[2]};
    });
  }

  function readCache() {
    try {
      var bundle = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
      return bundle && bundle.manifest && bundle.html && bundle.css && bundle.js ? bundle : null;
    } catch (error) { return null; }
  }

  function writeCache(bundle) {
    localStorage.setItem(CACHE_KEY, JSON.stringify(bundle));
  }

  function execute(code, source) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      var objectUrl = '';
      script.onload = function () { if (objectUrl) URL.revokeObjectURL(objectUrl); resolve(); };
      script.onerror = function () { if (objectUrl) URL.revokeObjectURL(objectUrl); reject(new Error('Avvio bundle fallito')); };
      try {
        objectUrl = URL.createObjectURL(new Blob([code + '\n//# sourceURL=' + source], {type: 'text/javascript'}));
        script.src = objectUrl;
      } catch (error) {
        script.text = code + '\n//# sourceURL=' + source;
      }
      document.head.appendChild(script);
      if (!script.src) resolve();
    });
  }

  function applyBundle(bundle) {
    window.__PRIPPI_APP_BOOTED__ = false;
    document.body.innerHTML = bundle.html;
    var old = document.getElementById('prippi-ota-style');
    if (old) old.parentNode.removeChild(old);
    var style = document.createElement('style');
    style.id = 'prippi-ota-style';
    style.textContent = bundle.css;
    document.head.appendChild(style);
    document.documentElement.setAttribute('data-prippi-version', bundle.manifest.version);
    localStorage.setItem(ACTIVE_KEY, JSON.stringify({
      version: bundle.manifest.version,
      revision: bundle.manifest.revision,
      shell: SHELL_VERSION,
      activated_at: new Date().toISOString()
    }));
    return execute(bundle.js, 'prippistream-ota-' + bundle.manifest.version + '.js');
  }

  function loadLocal() {
    document.documentElement.setAttribute('data-prippi-version', 'bundled-' + SHELL_VERSION);
    var script = document.createElement('script');
    script.src = 'main.js?v=' + encodeURIComponent(SHELL_VERSION);
    document.head.appendChild(script);
  }

  function fetchManifest() {
    var separator = MANIFEST_URL.indexOf('?') >= 0 ? '&' : '?';
    return fetchText(MANIFEST_URL + separator + '_=' + Date.now(), CHECK_TIMEOUT)
      .then(function (text) { return validateManifest(JSON.parse(text)); });
  }

  function backgroundCheck(activeRevision) {
    fetchManifest().then(function (manifest) {
      if ((manifest.revision || 0) <= activeRevision) return;
      return downloadBundle(manifest).then(function (bundle) {
        writeCache(bundle);
        var toast = document.getElementById('toast');
        if (toast) { toast.textContent = 'Aggiornamento ' + manifest.version + ' pronto: riavvio…'; toast.className = 'toast show'; }
        setTimeout(function () { location.reload(); }, 1200);
      });
    }).catch(function () {});
  }

  function start() {
    var cached = readCache();
    if (cached) {
      applyBundle(cached).then(function () {
        backgroundCheck(cached.manifest.revision || 0);
      }).catch(function () {
        localStorage.removeItem(CACHE_KEY);
        location.reload();
      });
      return;
    }
    setBootStatus('● Controllo aggiornamenti…');
    fetchManifest().then(downloadBundle).then(function (bundle) {
      writeCache(bundle);
      return applyBundle(bundle);
    }).catch(function () {
      loadLocal();
    });
  }

  window.PrippiOTA = {
    shellVersion: SHELL_VERSION,
    manifestUrl: MANIFEST_URL,
    active: function () { try { return JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null'); } catch (e) { return null; } },
    clearCache: function () { localStorage.removeItem(CACHE_KEY); localStorage.removeItem(ACTIVE_KEY); }
  };
  start();
}());
