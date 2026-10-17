# Rencana SHADESHIFT tahap lomba berikutnya

**Judul kerja:** SHADESHIFT: Pengganti Susunan Panel Surya Otomatis Berbasis Relai dan TinyML untuk Memulihkan Daya PLTS
Terbayangi Sebagian sebagai Alternatif Berbiaya Rendah Microinverter

## 1. Status klaim judul (jujur)
| Klaim di judul | Status | Bukti yang ada | Yang kurang |
|---|---|---|---|
| Pengganti susunan otomatis berbasis relai | Ada | Purwarupa relai + ESP32, 96 kurva terukur, protokol acak | Satu relai rusak; relai *latching* belum diuji |
| TinyML | Sebagian | Simulasi: selisih ~1 poin dari batas atas | Uji fisik belum konsisten; belum jalan di ESP32 |
| Memulihkan daya | Sebagian | Sim: +5 poin (24 V); lab: akumulasi 110,9 vs 100 | Belum di luar ruangan/bayangan nyata |
| PLTS terbayangi sebagian | Belum | Hanya lampu halogen + paranet | Pengukuran luar ruangan |
| Alternatif berbiaya rendah | Belum | Klaim tanpa angka | Daftar biaya (BoM) vs microinverter/optimizer |

## 2. Tahapan
**A. Fondasi (tanpa alat, bisa langsung)**
- A1. Perbandingan biaya: BoM purwarupa vs microinverter/optimizer untuk 4 modul (harga nyata dengan sumber).
- A2. Putuskan kasus pengguna nyata (satu lokasi/pengguna yang bisa difoto dan diukur).
- A3. Putuskan modul nyata 400-500 W bila ingin klaim skala besar (ganti modul sintetis).

**B. Perangkat keras**
- B1. Ganti relai rusak; uji relai *latching* (rugi peralihan, umur).
- B2. Tambah sensor suhu panel dan satu acuan iradiansi (Isc modul referensi tanpa bayangan).
- B3. Keselamatan luar ruangan: sekring, isolasi, wadah tahan hujan, tegangan 4S bisa tinggi.

**C. Pengambilan data luar ruangan**
- C1. 20-30 kondisi bayangan (opak: papan, tiang, pohon; tembus cahaya: paranet, awan) pada jam berbeda.
- C2. 3 ulangan, urutan topologi diacak, catat suhu, Isc acuan, waktu.
- C3. Bagi data: kondisi latih dan kondisi uji yang TIDAK dipakai melatih.
- C4. Data lama (lab) tetap dipakai sebagai pembanding.

**D. Model (kode ada di SHADESHIFT_ML/)**
- D1. Latih ulang pohon keputusan/regresi logistik dengan simulasi + data nyata; uji pada kondisi baru.
- D2. Aturan biaya peralihan: beralih hanya bila selisih daya > rugi relai.
- D3. Ekspor ke C, jalankan di ESP32; ukur ukuran kode, waktu inferensi, akurasi di perangkat.
- D4. Pembanding wajib: topologi tetap, sapuan semua topologi, aturan manual.

**E. Demo dan bukti**
- E1. Tampilan real-time (OLED/web lokal): topologi aktif, daya, daya tanpa beralih.
- E2. Video 30-60 detik sebagai cadangan; uji berulang sebelum presentasi.

**F. Naskah dan pitchdeck**
- F1. Perbarui angka dengan data nyata; cantumkan keterbatasan.
- F2. Judul final tergantung gerbang di bawah.

## 3. Gerbang keputusan (go / no-go)
- Jika model lolos uji kondisi baru (selisih <= 2 poin dari terbaik, mengalahkan topologi tetap terbaik) dan jalan di ESP32:
  pertahankan kata TinyML di judul.
- Jika tidak: hapus TinyML dari judul, posisikan sebagai hasil simulasi + pengembangan lanjutan.
- Angka "[X]%" dan lokasi hanya dicantumkan bila ada data nyata.

## 4. Metrik sukses
1. Daya pulih terhadap topologi tetap terbaik (% dan W) pada kondisi uji.
2. Selisih dari pilihan terbaik (regret, poin).
3. Jumlah peralihan relai per hari dan rugi peralihan.
4. Biaya total vs microinverter/optimizer 4 modul.

## 5. Urutan bila waktu terbatas
A1 -> B1/B2 -> C -> D1/D3 -> E -> F. D2 dan relai *latching* menyusul bila sempat.

## 6. Masukan yang dibutuhkan dari tim
- Tanggal lomba berikutnya dan kriterianya.
- Kasus pengguna/lokasi nyata.
- Kemampuan membeli komponen (relai *latching*, sensor suhu, modul 400-500 W bila perlu).
