'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');

var root = path.resolve(__dirname, '..');
var html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
var css = fs.readFileSync(path.join(root, 'css', 'style.css'), 'utf8');
var main = fs.readFileSync(path.join(root, 'main.js'), 'utf8');

(function viewportKeepsAFluidHeight() {
  var viewport = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/i);
  assert.ok(viewport, 'meta viewport mancante');
  assert.ok(/width=1920/.test(viewport[1]), 'il canvas TV deve conservare la larghezza di progetto');
  assert.ok(!/height\s*=/.test(viewport[1]), 'un altezza viewport fissa provoca il crop sulle finestre ultrawide');
}());

(function heroUsesOneResponsiveHeightSource() {
  assert.ok(/--hero-height:\s*350px/.test(css));
  assert.ok(/grid-template-rows:\s*var\(--hero-height\)/.test(css));
  assert.ok(/height:\s*var\(--hero-height\)/.test(css));
  assert.ok(/@media\s*\(max-height:\s*860px\)/.test(css));
  assert.ok(/@media\s*\(max-height:\s*700px\)/.test(css));
  assert.ok(/@media\s*\(max-width:\s*1100px\)\s*and\s*\(max-height:\s*700px\)/.test(css));
}());

(function copyCannotEscapeTheHero() {
  assert.ok(/\.hero-copy\s*\{[^}]*top:\s*var\(--hero-copy-y\)[^}]*bottom:\s*var\(--hero-copy-y\)[^}]*overflow:\s*hidden/s.test(css));
  assert.ok(/\.hero h2\s*\{[^}]*-webkit-line-clamp:\s*2/s.test(css));
  assert.ok(/\.hero p\s*\{[^}]*flex:\s*none[^}]*-webkit-line-clamp:\s*2/s.test(css));
}());

(function fanartIsCroppedWithoutDistortion() {
  var art = css.match(/\.hero-art\s*\{([^}]+)\}/);
  assert.ok(art, 'stile fanart Hero mancante');
  assert.ok(/background-size:\s*cover/.test(art[1]));
  assert.ok(/background-repeat:\s*no-repeat/.test(art[1]));
}());

(function focusCannotScrollTheApplicationRoots() {
  assert.ok(/function\s+focusWithoutRootScroll\s*\([^)]*\)/.test(main));
  assert.ok(/\.focus\(\{preventScroll:\s*true\}\)/.test(main), 'focus deve richiedere preventScroll');
  assert.ok(/function\s+resetNonScrollableRoots[\s\S]*document\.documentElement[\s\S]*document\.body[\s\S]*querySelector\('\.main'\)[\s\S]*getElementById\('content'\)/.test(main));
  assert.ok(/setTimeout\(resetNonScrollableRoots,\s*0\)/.test(main), 'serve il reset differito per WebKit Tizen');
  assert.strictEqual((main.match(/\.focus\(/g) || []).length, 2,
    'focus nativi aggiuntivi devono passare da focusWithoutRootScroll');
}());

console.log('Hero responsive Tizen: 5 verifiche superate');
