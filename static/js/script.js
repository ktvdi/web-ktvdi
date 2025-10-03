async function loadComponent(id, file) {
  try {
    const res = await fetch(file);
    
    // Cek apakah permintaan berhasil
    if (!res.ok) {
      throw new Error(`Gagal memuat ${file}: ${res.status} ${res.statusText}`);
    }

    // Ambil teks HTML dari respons
    const html = await res.text();

    // Sisipkan HTML ke dalam elemen dengan id yang sesuai
    document.getElementById(id).innerHTML = html;
  } catch (error) {
    // Tangani jika terjadi kesalahan dalam pemuatan
    console.error("Terjadi kesalahan saat memuat komponen:", error);
    
    // Bisa menambahkan pesan ke halaman atau elemen tertentu agar pengguna tahu terjadi masalah
    document.getElementById(id).innerHTML = `<p>Gagal memuat konten. Coba lagi nanti.</p>`;
  }
}

// Muat header dan footer ketika DOM siap
document.addEventListener("DOMContentLoaded", () => {
  loadComponent("header", "/static/partials/header.html"); 
  loadComponent("footer", "/static/partials/footer.html");
});
