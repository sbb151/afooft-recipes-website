// Offline support: the app shell is cached up front; recipes and photos are
// cached as they are opened, so anything you've cooked from works offline.
const VERSION = 'afooft-v3';
const SHELL = ['./', 'index.html', 'style.css', 'app.js', 'manifest.webmanifest', 'icon.svg', 'icon-192.png', 'icon-512.png', 'icon-180.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  // pages and recipe data: network first so updates and edits show, cache when offline; photos: cache first
  const isPhoto = /\/img\//.test(url.pathname);
  if (!isPhoto) {
    // network first so updates show up, cache as fallback
    e.respondWith(fetch(e.request).then(r => { if (r.ok) { const c = r.clone(); caches.open(VERSION).then(x => x.put(e.request, c)); } return r; })
      .catch(() => caches.match(e.request, { ignoreSearch: true })));
  } else {
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
      if (r.ok) { const c = r.clone(); caches.open(VERSION).then(x => x.put(e.request, c)); }
      return r;
    })));
  }
});
