/*
 * The service worker (UX-09, UX-10, SEC-29) - hand-written, committed, served
 * at /ZBDGT/sw.js so its scope is the whole app.
 *
 * What it keeps, and what it never keeps:
 *
 *   the app shell (HTML)    network first; the last good copy when offline,
 *                           so the app opens and can say it is offline
 *   the bundle and icons    cache first - hashed file names never change
 *   ANY /api/ response      never touched. Every figure in this app comes
 *                           from the API, so no figure is ever in this cache
 *
 * Cache storage is shared by every app on this host, which is why the rule is
 * absolute rather than "cache, then clear". On lock and sign-out the page asks
 * it to clear everything anyway.
 */
const BASE = '/ZBDGT';
const CACHE = 'zbdgt-shell-v1';
const SHELL = `${BASE}/`;

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('zbdgt-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'clear') {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith('zbdgt-')).map((k) => caches.delete(k)))));
  }
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith(BASE)) return;
  if (url.pathname.startsWith(`${BASE}/api/`)) return; // never cached, never answered from a cache

  if (url.pathname.startsWith(`${BASE}/static/dist/assets/`) || url.pathname.startsWith(`${BASE}/static/icons/`)) {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(request).then((hit) => hit || fetch(request).then((response) => {
          if (response.ok) cache.put(request, response.clone());
          return response;
        })),
      ),
    );
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Clone NOW: the page starts reading the body as soon as this returns, and a clone
          // taken later - inside caches.open's callback - finds it already used.
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(SHELL, copy));
          }
          return response;
        })
        .catch(() => caches.open(CACHE).then((cache) => cache.match(SHELL)).then((hit) => hit || new Response(
          '<!doctype html><meta name="viewport" content="width=device-width"><title>Offline</title>' +
          '<body style="font-family:system-ui;padding:2rem"><h1>You are offline</h1>' +
          '<p>Budget App needs a connection. Nothing is stored on this device.</p></body>',
          { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } },
        ))),
    );
  }
});
