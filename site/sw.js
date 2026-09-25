/* Offline support: app shell is cached on install; book files are served from the
 * per-book cache that the "Download" button fills (see downloadBook in app.js). */
var SHELL = 'shell-v8';
var FILES = ['./', 'index.html', 'app.js', 'style.css', 'manifest.webmanifest', 'icons/icon.svg'];
self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(SHELL).then(function (c) { return c.addAll(FILES); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('shell-') === 0 && k !== SHELL; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  var url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  // index.json: network first so new books show up; everything else: cache first
  if (/books\/index\.json$/.test(url.pathname)) {
    e.respondWith(fetch(e.request).then(function (r) {
      var copy = r.clone(); caches.open(SHELL).then(function (c) { c.put(e.request, copy); }); return r;
    }).catch(function () { return caches.match(e.request); }));
    return;
  }
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(function (hit) {
    return hit || fetch(e.request);
  }));
});
