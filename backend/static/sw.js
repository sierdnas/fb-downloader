// Minimal service worker: exists only to satisfy Chrome/Android's PWA
// installability requirement (an active service worker with a fetch
// handler). Deliberately does NOT cache anything — this app's data
// (queue, history, logs) changes constantly, so an offline cache would
// only risk showing stale information. Every request just goes to the
// network as normal.
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
