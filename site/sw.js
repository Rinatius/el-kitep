/* Offline support.
 * App files, the lists the app loads (books, changelog, missing books) and each book's text (book.json)
 * are fetched from the network first and revalidated with the server, so a normal reload shows the newest
 * version. The saved copy is used when the phone is offline or the network is too slow. Pictures of a
 * downloaded book come from that book's cache (filled by the "Download" button, see downloadBook in app.js). */
var APP = 'app';
var SHELL = ['./', 'index.html', 'app.js', 'style.css', 'manifest.webmanifest', 'icons/icon.svg'];
var DATA = ['books/index.json', 'changelog.json', 'missing.json', 'ministry.json']; // lists the app loads: fetched like app files
var SLOW_MS = 4000; // after this, answer from the saved copy and let the network update it in the background

function abs(u) { return new URL(u, self.registration.scope).href; }

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(APP).then(function (c) {
    return c.addAll(SHELL.map(function (u) { return new Request(u, { cache: 'reload' }); }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  var shell = SHELL.concat(DATA).map(abs);
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.map(function (k) {
      // old versioned app caches
      if (k.indexOf('shell-') === 0) return caches.delete(k);
      // older app versions also saved app files inside each downloaded book; those copies went stale
      // (and older app versions left an empty cache for every book shown in the library)
      if (k.indexOf('book-') === 0) {
        return caches.open(k).then(function (c) {
          return Promise.all(shell.map(function (u) { return c.delete(u, { ignoreSearch: true }); }))
            .then(function () { return c.keys(); })
            .then(function (left) { if (!left.length) return caches.delete(k); });
        });
      }
    }));
  }).then(function () { return self.clients.claim(); }));
});

// Network first, revalidating with the server; the saved copy when offline or slow.
function networkFirst(key, save) {
  var saved = save ? caches.open(APP).then(function (c) { return c.match(key); }) : caches.match(key, { ignoreSearch: true });
  var net = fetch(key, { cache: 'no-cache' }).then(function (r) {
    if (r.ok && save) { var copy = r.clone(); caches.open(APP).then(function (c) { return c.put(key, copy); }); }
    return r;
  });
  return new Promise(function (resolve) {
    var done = false;
    function answer(r) { if (!done && r) { done = true; resolve(r); } }
    var timer = setTimeout(function () { saved.then(answer); }, SLOW_MS);
    net.then(function (r) { clearTimeout(timer); answer(r); }, function () {
      clearTimeout(timer);
      saved.then(function (hit) { answer(hit || Response.error()); });
    });
  });
}

self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  var url = new URL(e.request.url);
  if (url.origin === 'https://img.elkitep.com') { // book pictures on elkitep.com: the downloaded copy if there is one
    // (ignoreVary: the bucket answers with "Vary: Origin" and the saved copy was stored without one)
    e.respondWith(caches.match(e.request, { ignoreSearch: true, ignoreVary: true }).then(function (hit) { return hit || fetch(e.request); }));
    return;
  }
  if (url.origin !== location.origin) return;
  var path = url.origin + url.pathname, scope = abs('./');
  if (e.request.mode === 'navigate' && (path === scope || path === abs('index.html'))) {
    e.respondWith(networkFirst(scope, true));
  } else if (SHELL.map(abs).indexOf(path) >= 0 || DATA.map(abs).indexOf(path) >= 0) {
    e.respondWith(networkFirst(path, true));
  } else if (/\/books\/[^/]+\/(book|cards)\.json$/.test(url.pathname)) {
    e.respondWith(networkFirst(path, false)); // offline: the downloaded copy
  } else {
    // pictures and other book files: the downloaded copy if there is one, otherwise the network
    e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(function (hit) { return hit || fetch(e.request); }));
  }
});
