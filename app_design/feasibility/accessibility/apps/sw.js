// Cache the shell and the offline pack on install; serve cache first, network fallback.
// ponytail: no versioned cache busting; bump CACHE when the pack or page changes.
const CACHE = 'care-v1';
self.addEventListener('install', e => e.waitUntil(
  caches.open(CACHE).then(c => c.addAll(['pwa', 'pack.json'])).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => e.respondWith(
  caches.match(e.request).then(r => r || fetch(e.request))));
