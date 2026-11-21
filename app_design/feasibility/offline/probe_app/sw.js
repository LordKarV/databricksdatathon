// Probe SW: precache the shell, serve it when the network fails.
const CACHE = 'probe-v1';
self.addEventListener('install', e => e.waitUntil(
  caches.open(CACHE).then(c => c.addAll(['/', '/manifest.webmanifest'])).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  // 5xx too: a stopped app answers with a proxy error page, not a network error.
  if (e.request.mode === 'navigate') e.respondWith(fetch(e.request)
    .then(res => res.status >= 500 ? caches.match('/') : res).catch(() => caches.match('/')));
});
