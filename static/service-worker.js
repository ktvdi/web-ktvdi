const CACHE_NAME = "ktvdi-v2"; // Ganti v2, v3 dst jika ada update besar
const URLS_TO_CACHE = [
  "/",
  "/static/css/style.css",        // PENTING: Cache CSS agar tampilan tidak rusak
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  // Tambahkan font awesome jika ingin ikon muncul offline (opsional, karena load eksternal agak tricky)
];

// 1. INSTALL: Simpan file aset statis
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log("Opened cache");
      return cache.addAll(URLS_TO_CACHE);
    })
  );
});

// 2. ACTIVATE: Hapus cache versi lama agar tidak menumpuk
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log("Menghapus cache lama:", cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// 3. FETCH: Strategi "Network First, Fallback to Cache"
// Coba ambil dari internet dulu (biar data update), kalau offline baru ambil cache.
self.addEventListener("fetch", (event) => {
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Jika berhasil connect internet:
        // Kita copy responnya dan simpan ke cache (update cache otomatis)
        if (!response || response.status !== 200 || response.type !== "basic") {
          return response;
        }
        
        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          // Hanya cache request GET (bukan POST/PUT)
          if (event.request.method === "GET") {
             cache.put(event.request, responseToCache);
          }
        });

        return response;
      })
      .catch(() => {
        // Jika OFFLINE (Gagal connect):
        // Ambil dari cache
        return caches.match(event.request);
      })
  );
});
