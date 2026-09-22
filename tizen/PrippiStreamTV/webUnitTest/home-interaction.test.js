'use strict';
var assert = require('assert');
var fs = require('fs');
var vm = require('vm');
var source = fs.readFileSync(require('path').join(__dirname, '..', 'main.js'), 'utf8');
function extract(name) {
  var start = source.indexOf('  function ' + name + '(');
  var end = source.indexOf('\n  function ', start + 1);
  return source.slice(start, end);
}
var moves = [];
var active = {getAttribute: function (key) {
  return {'data-zone': 'row', 'data-row': '2', 'data-col': '6'}[key];
}};
var context = {
  document: {activeElement: active},
  focusRow: function (row, column) { moves.push([row, column]); return true; }
};
vm.createContext(context);
vm.runInContext(extract('moveFocus'), context);
context.moveFocus(40);
context.moveFocus(38);
context.moveFocus(39);
assert.deepStrictEqual(moves, [[3, 0], [1, 0], [2, 7]]);

var events = [], input = {value: 'Matrix', blur: function () { events.push('blur'); }};
context.document.getElementById = function (id) { return id === 'query' ? input : {}; };
context.focusElement = function () { events.push('focus'); };
context.request = function () { events.push('request'); return new Promise(function () {}); };
vm.runInContext(extract('runSearch'), context);
context.runSearch();
assert.deepStrictEqual(events, ['blur', 'focus', 'request']);

context.state = {page: 'home'};
context.document.querySelector = function (selector) { return selector; };
vm.runInContext(extract('firstContentFocus'), context);
assert.ok(context.firstContentFocus().indexOf('[data-col="0"]') >= 0);
console.log('Interazioni Home Tizen: navigazione verticale, focus iniziale e chiusura tastiera verificati');
