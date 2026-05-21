const CACHE_NAME = 'stockvn-cache-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/stock.html',
  '/watchlist.html',
  '/portfolio.html',
  '/scanner.html',
  '/css/style.css',
  '/manifest.json',
  '/icons/icon.svg'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
});

self.addEventListener('fetch', (e) => {
  // Only cache static frontend assets, let API calls pass through
  if (e.request.url.includes('/api/')) {
    return;
  }
  
  e.respondWith(
    caches.match(e.request).then((response) => {
      return response || fetch(e.request);
    })
  );
});
