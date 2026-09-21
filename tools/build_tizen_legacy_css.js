'use strict';

var fs = require('fs');
var path = require('path');

var root = path.resolve(__dirname, '..');
var inputPath = path.join(root, 'tizen', 'PrippiStreamTV', 'css', 'style.css');
var outputPath = path.join(root, 'tizen', 'PrippiStreamTV', 'css', 'style-legacy.css');
var css = fs.readFileSync(inputPath, 'utf8');
var variables = {};
var rootBlock = css.match(/:root\s*\{([\s\S]*?)\}/);

if (!rootBlock) throw new Error('Blocco :root non trovato in style.css');

css.replace(/--([\w-]+)\s*:\s*([^;]+);/g, function (_, name, value) {
  if (!Object.prototype.hasOwnProperty.call(variables, name)) variables[name] = value.trim();
  return _;
});

css = css.replace(/var\(--([\w-]+)(?:\s*,\s*([^\)]+))?\)/g, function (_, name, fallback) {
  if (Object.prototype.hasOwnProperty.call(variables, name)) return variables[name];
  if (fallback) return fallback.trim();
  throw new Error('Variabile CSS senza valore legacy: --' + name);
});

css = '/* Generato da tools/build_tizen_legacy_css.js. Non modificare a mano. */\n' + css;
fs.writeFileSync(outputPath, css, 'utf8');
console.log('CSS legacy generato: ' + outputPath);
