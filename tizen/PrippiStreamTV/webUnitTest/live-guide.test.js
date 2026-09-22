'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');
var source = fs.readFileSync(path.join(__dirname, '..', 'standalone.js'), 'utf8');
var ui = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8');

function functionSource(name) {
  var start = source.indexOf('  function ' + name + '(');
  assert.ok(start >= 0, name + ' non trovata');
  var end = source.indexOf('\n  function ', start + 1);
  return source.slice(start, end < 0 ? source.length : end);
}

var context = {
  document: {
    createElement: function () {
      var element = {value: '', textContent: ''};
      Object.defineProperty(element, 'innerHTML', {set: function (value) {
        element.value = String(value).replace(/&#39;/g, "'").replace(/&amp;/g, '&').replace(/&Egrave;/g, 'È');
        element.textContent = element.value;
      }});
      return element;
    }
  }
};
require('vm').createContext(context);
['skyEpgNorm', 'decodeGuideText', 'parseSuperGuide', 'parseTvEpg', 'superGuideFor'].forEach(function (name) {
  require('vm').runInContext(functionSource(name), context);
});

var fixture = '<a href="/programmazione-canale/oggi/guida-programmi-tv-rai-1/217/">' +
  '<img alt="Rai 1"></a><div><p class="font-bold">11:55</p>' +
  '<p class="truncate text-lg">È sempre mezzogiorno!</p></div>' +
  '<div><p class="font-bold">13:30</p><p class="truncate text-base">Tg1</p></div>';
var guide = context.parseSuperGuide(fixture);
assert.strictEqual(guide.rai1.program, 'È sempre mezzogiorno!');
assert.strictEqual(guide.rai1.end, '13:30');
assert.strictEqual(guide.rai1.nextProgram, 'Tg1');
assert.strictEqual(context.superGuideFor({title: 'Rai 1'}, guide).program, 'È sempre mezzogiorno!');
assert.strictEqual(context.superGuideFor({title: 'Rai 2'}, guide), null, 'un canale numerato non deve ereditare la guida di un altro');
assert.strictEqual(context.superGuideFor({title: 'La7d'}, {la7cinema: {program: 'Film'}}).program, 'Film');
assert.strictEqual(context.superGuideFor({title: 'Motor Trend'}, {discoveryturbo: {program: 'Motori'}}).program, 'Motori');
assert.strictEqual(context.superGuideFor({title: 'Home and Garden TV'}, {hgtvhomegarden: {program: 'Casa'}}).program, 'Casa');

var euroFixture = '<h3>Eurosport 1</h3><table><tr><td class="col ellipsis">' +
  '<a title="16:00 Ciclismo"><span>16:00 Ciclismo</span></a><div class="progress-bar"></div></td></tr>' +
  '<tr><td><a title="17:45 Mountain Bike">17:45 Mountain Bike</a></td></tr></table>';
var euroGuide = context.parseTvEpg(euroFixture);
assert.strictEqual(euroGuide.eurosport1.program, 'Ciclismo');
assert.strictEqual(euroGuide.eurosport1.end, '17:45');
assert.strictEqual(euroGuide.eurosport1.nextProgram, 'Mountain Bike');

assert.ok(/liveItems = liveItems\.concat/.test(source), 'EPG deve includere tutte le righe Live');
assert.ok(/palinsesto\/onAir\.json/.test(source), 'manca la guida ufficiale RaiPlay');
assert.ok(/nownext\/nownext\.json/.test(source), 'manca la guida ufficiale Mediaset');
assert.ok(/broadcasterGuide/.test(source), 'la guida ufficiale dell’emittente deve avere priorità');
assert.ok(/offset = -60 \* 60 \* 1000/.test(source), 'manca la correzione oraria +1');
assert.ok(/Date\.parse\(event\.starttime\) >= currentEnd/.test(source), 'il successivo deve iniziare dopo la fine del corrente');
assert.ok(/currentIndex < 0 \|\| Date\.parse\(event\.starttime\) >/.test(source), 'gli eventi sovrapposti devono scegliere il più specifico');
assert.ok(/scheduleLiveEpgRefresh/.test(ui) && /4 \* 60 \* 1000/.test(ui), 'manca il refresh periodico della guida');
assert.ok(/live-expanded[\s\S]*return request\('\/live-epg'/.test(ui), 'EPG deve essere applicato dopo il catalogo Live completo');

console.log('Guida Live Tizen: parsing, matching, orari, sovrapposizioni e refresh verificati');
