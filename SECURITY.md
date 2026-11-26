# Kebijakan Keamanan (Security Policy)

Keamanan portal web dan infrastruktur **Komunitas TV Digital Indonesia (KTVDI)** (`ktvdi.my.id`) merupakan prioritas utama kami. Dokumen ini menjelaskan versi sistem yang didukung, perlindungan infrastruktur Cloudflare yang diterapkan, serta prosedur pelaporan kerentanan secara bertanggung jawab (*Coordinated Vulnerability Disclosure*).

---

## Versi yang Didukung (Supported Versions)

Pembaruan keamanan dan penambalan celah (*security patches*) hanya diberikan secara aktif untuk versi produksi terkini:

| Versi / Branch | Status Dukungan | Keterangan |
| -------------- | --------------- | ---------- |
| `main` (v2.x)  | :white_check_mark: Didukung Penuh | Produksi aktif (`ktvdi.my.id`) dengan proteksi Cloudflare WAF |
| `v1.x`         | :x: Tidak Didukung | Arsip lama (*deprecated*), tidak lagi menerima pembaruan keamanan |
| `< 1.0`        | :x: Tidak Didukung | Rilis awal eksperimental |

---

## Perlindungan Infrastruktur & Cloudflare

Layanan web `ktvdi.my.id` dilindungi di belakang jaringan **Cloudflare** dengan lapisan keamanan berikut:

* **Cloudflare Web Application Firewall (WAF):** Penyaringan otomatis terhadap serangan injeksi (SQLi, XSS, SSRF, RCE) dan eksploitasi kerentanan umum.
* **DDoS Mitigation & Rate Limiting:** Pembatasan laju permintaan (*request rate limiting*) pada seluruh rute aplikasi dan endpoint API untuk mencegah penyalahgunaan sumber daya.
* **Bot Fight Mode & Strict SSL/TLS:** Enkripsi *end-to-end* (Full Strict + HSTS) dan mitigasi trafik bot berbahaya.
* **Proteksi Origin Server:** Akses langsung ke server asal dibatasi hanya untuk rentang IP resmi Cloudflare dan jalur manajemen internal terenkripsi.

### Batasan Pengujian pada Infrastruktur Cloudflare
1. **Dilarang melakukan pengujian DoS/DDoS** atau membanjiri trafik (*load testing* / *stress testing*) yang memicu pemblokiran Cloudflare atau mengganggu akses pengguna komunitas.
2. **Dilarang menggunakan pemindai otomatis agresif** (*automated vulnerability scanners* berkonkurensi tinggi) tanpa izin tertulis terlebih dahulu.
3. **Dilarang mencoba melakukan *Origin IP Bypass*** untuk menyerang alamat IP server asal secara langsung di luar proksi Cloudflare.
4. Kerentanan yang berada pada sistem inti **Cloudflare** (bukan konfigurasi atau kode aplikasi KTVDI) harus dilaporkan langsung melalui program Bug Bounty resmi Cloudflare di HackerOne.

---

## Ruang Lingkup (Scope)

### Dalam Ruang Lingkup (*In-Scope*)
* Aplikasi web utama pada domain `ktvdi.my.id`.
* Endpoint API publik, validasi input, autentikasi, serta manajemen sesi pengguna.
* Mekanisme kontrol akses dan validasi host pada fitur *stream relay*.

### Di Luar Ruang Lingkup (*Out-of-Scope*)
* Serangan *Social Engineering*, *phishing*, atau spam yang menargetkan pengurus maupun anggota KTVDI.
* Temuan *automated scanner* tanpa bukti dampak eksploitasi nyata (*Proof of Concept*).
* *Clickjacking* pada halaman informasi statis publik yang tidak memiliki aksi sensitif.
* *Rate limiting* atau *bruteforce* pada formulir publik yang sudah ditangani oleh mitigasi Cloudflare.

---

## Cara Melaporkan Kerentanan (Reporting a Vulnerability)

**JANGAN membuka *Public GitHub Issue* untuk melaporkan celah keamanan.** Pengungkapan celah secara publik sebelum *patch* dirilis membahayakan keamanan seluruh pengguna.

Silakan laporkan temuan Anda melalui salah satu jalur privat berikut:

1. **GitHub Security Advisories (Disarankan):**
   Buka tab **Security** > **Advisories** > klik **Report a vulnerability** pada repositori ini.
2. **Email Keamanan Resmi:**
   Kirim laporan ke **`kom.tvdigitalid@gmail.com`** dengan subjek:
   `[SECURITY] Laporan Kerentanan - <Ringkasan Celah>`

### Informasi yang Wajib Disertakan
* Jenis kerentanan dan tingkat keparahan menurut penilaian Anda (*Low / Medium / High / Critical*).
* URL lengkap, endpoint, atau parameter yang terdampak.
* Langkah-langkah reproduksi secara rinci beserta *Proof of Concept* (PoC) yang aman dan non-destruktif.
* Potensi dampak keamanan dan saran perbaikan (jika ada).

---

## Proses Penanganan & Waktu Respons (SLA)

Setelah laporan diterima, tim pengurus teknis KTVDI berkomitmen mengikuti jadwal penanganan berikut:

| Tahapan | Target Waktu | Keterangan |
| ------- | ------------ | ---------- |
| **Konfirmasi Penerimaan** | Maksimal **48 jam** | Konfirmasi bahwa laporan telah masuk ke antrean evaluasi |
| **Triase & Validasi** | **3 – 5 hari kerja** | Reproduksi celah dan penentuan tingkat keparahan |
| **Mitigasi Darurat WAF** | **< 24 jam** *(Critical)* | Penerapan aturan blokir sementara pada Cloudflare WAF jika diperlukan |
| **Rilis Patch Permanen** | **7 – 14 hari kerja** | Perbaikan kode produksi dan verifikasi ulang bersama pelapor |

---

## Safe Harbor (Perlindungan Peneliti Keamanan)

KTVDI menghargai kontribusi komunitas keamanan siber. Kami tidak akan menempuh jalur hukum terhadap peneliti keamanan yang bertindak dengan itikad baik (*good faith*), dengan ketentuan:

* Mematuhi seluruh aturan dalam kebijakan ini dan tidak melanggar hukum yang berlaku.
* Tidak mengakses, menyalin, mengubah, atau menghapus data milik pengguna lain.
* Hanya menggunakan akun uji milik sendiri saat memverifikasi celah autentikasi atau otorisasi.
* Menjaga kerahasiaan detail kerentanan hingga tim KTVDI mengonfirmasi bahwa perbaikan telah diterapkan di produksi.
