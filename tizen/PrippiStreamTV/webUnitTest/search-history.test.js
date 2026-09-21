'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var main = fs.readFileSync(path.resolve(__dirname, '..', 'main.js'), 'utf8');

assert.ok(/SEARCH_HISTORY_KEY = 'prippi\.tizen\.search_history\.v1'/.test(main),
  'la cronologia deve avere uno storage locale versionato');
assert.ok(/function saveSearchHistory\(query\)[\s\S]*entries\.unshift\(clean\)[\s\S]*SEARCH_HISTORY_MAX_ITEMS/.test(main),
  'la ricerca più recente deve essere salvata per prima e limitata');
assert.ok(/data-zone="search-history"/.test(main),
  'le ricerche recenti devono essere raggiungibili col telecomando');
assert.ok(/data-search-history[\s\S]*runSearch\(\)/.test(main),
  'selezionare una ricerca recente deve rilanciarla');
assert.ok(/search-history-clear[\s\S]*clearSearchHistory/.test(main),
  'la cronologia deve poter essere cancellata');

console.log('Cronologia ricerche Tizen: 5 verifiche superate');
