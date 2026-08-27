/* Service worker voor de zoekpagina.
 *
 * Doel: na één bezoek werkt de pagina zonder netwerk. Dat is niet alleen
 * comfort - op een universiteitsnetwerk met clientisolatie is dit de enige
 * route die het altijd doet, want er is dan niets meer om te blokkeren.
 *
 * Strategie: cache-first voor de eigen bestanden, met een stille verversing op
 * de achtergrond. De documentatie verandert zelden; wachten op het netwerk
 * voor iets dat al op het toestel staat is verspilde tijd.
 */
var CACHE = 'vu-ea-definities-v3';
var ASSETS = [
  './zoek.html',
  // De startpagina hoort erbij: de zoekpagina linkt ernaar terug, en een
  // terugknop die alleen mét netwerk werkt is precies verkeerd om.
  './',
  './index.html',
  './data/definities.json',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(ASSETS);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(names.map(function (name) {
        return name === CACHE ? null : caches.delete(name);
      }));
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) {
    return;
  }
  event.respondWith(
    caches.match(request).then(function (cached) {
      var network = fetch(request).then(function (response) {
        if (response && response.status === 200) {
          var copy = response.clone();
          caches.open(CACHE).then(function (cache) { cache.put(request, copy); });
        }
        return response;
      }).catch(function () {
        // Offline: het antwoord uit de cache is het antwoord.
        return cached;
      });
      return cached || network;
    })
  );
});
