# Protokol pengukuran luar ruangan SHADESHIFT (draf 1)

Tujuan: mengumpulkan kurva I-V nyata berlabel untuk (1) melatih dan menguji model diagnosis dan pemilih topologi,
(2) membuktikan pemulihan daya di bawah matahari, (3) menguji aturan pemicu sapuan pada bayangan bergerak.
Alat dan perintah mengikuti `firmware/CARA_PAKAI.md` (SIKLUS, SUHU, logger_shadeshift.py).

## 0. Uji pendahuluan (1 jam, sebelum pengukuran sungguhan)
- [ ] Cek Voc 4S di bawah matahari tidak melewati batas pembagi tegangan (maks sekitar 139 V pada GAIN_ONE; 4S sekitar 88 V). Ubah `VPANEL`.
- [ ] Cek arus 4P tidak menjenuhkan ADS1115 (GAIN_EIGHT: batas 5,12 A pada shunt 0,1 ohm; Isc 4P sekitar 2,4 A).
- [ ] Setelah 10 siklus berturut-turut, raba/ukur suhu MOSFET IRFP260N dan shunt. Bila panas, pasang pendingin atau beri jeda antarsiklus.
- [ ] Pastikan sekring 4 A, wadah dan kabel aman dari hujan, tegangan 4S bisa 88 V DC.
- [ ] Tambahkan acuan iradiansi: modul sensor cahaya BH1750 (I2C, tanpa kabel analog) atau sel surya kecil acuan dengan shunt ke kanal A2.
      Tanpa acuan, tingkat bayangan hanya bisa diperkirakan dari Isc.
- [ ] Laptop dan logger siap (daya baterai penuh), jam laptop dicocokkan dengan jam alat.

## 1. Pembagian sesi
| Sesi | Waktu | Catatan |
|---|---|---|
| Pagi | 08.00-10.00 | sudut matahari rendah |
| Siang | 11.00-13.00 | iradiansi tertinggi |
| Sore | 15.00-17.00 | sudut rendah, suhu panel lebih tinggi |
Lakukan di minimal 2 hari berbeda (satu cerah, satu berawan). Hari pertama untuk melatih, hari kedua (kondisi yang tidak dipakai melatih) khusus menguji.

## 2. Daftar kondisi (satu kondisi = 3 siklus, urutan topologi diacak oleh perintah SIKLUS)
**A. Normal**
- A1 tanpa bayangan (acuan tiap sesi, ulangi di awal dan akhir sesi untuk memeriksa hanyut).

**B. Bayangan sebagian (opak: papan/karton)**
- B1 modul A tertutup 25 %, B2 50 %, B3 75 % (menutup dari tepi).
- B4 satu sel (strip sempit) modul A.
- B5 modul A dan B (satu string), B6 modul A dan D (diagonal), B7 modul A dan C (beda string).

**C. Redup merata / tembus cahaya**
- C1 paranet 65 % pada modul A, C2 paranet 75 %.
- C3 paranet pada dua modul (A+B), C4 (A+D).
- C5 modul A kotor merata (bila ada debu/film tipis, opsional).

**D. Bayangan alami (foto wajib)**
- D1 bayangan pohon/tiang/bangunan pada jam-jam berbeda; catat jam, arah, dan foto.
- D2 awan lewat: tandai sebagai dinamis, ulangi sapuan tiap 30 detik selama 20 menit.

**E. Gangguan yang disuntikkan (array dimatikan `OFF` saat mengubah kabel)**
- E1 dioda pelewat modul C dilepas, tanpa bayangan.
- E2 dioda pelewat modul C dilepas + bayangan opak 50 % pada modul C.
- E3 resistor seri 1 ohm (2 W) pada satu modul, E4 2,2 ohm (2 W).
- E5 modul C dipintas dengan kabel pendek (modul hilang dari susunan).
Setiap gangguan dilepas/dikembalikan dan dicatat jam serta foto.

**F. Bayangan bergerak (daun)**
- F1 ranting digerak-gerakkan di atas modul A, sapuan SIKLUS berulang tiap 30 detik selama 20 menit.
  Gunakan data ini untuk menguji aturan pemicu sapuan (lihat `dinamis.py`).

## 3. Yang dicatat untuk setiap siklus
Tanggal-jam, kode kondisi, suhu punggung A-D (`SUHU`), lux/iradiansi acuan, kondisi langit (cerah/berawan/mendung),
sudut dan arah panel, foto kondisi, catatan (angin, awan lewat, gangguan alat).
Buang atau tandai siklus bila iradiansi acuan berubah lebih dari 5 % di tengah siklus (awan lewat).

## 4. Penamaan berkas
`LRtanggal_kodekondisi_topologi_uN.csv`, contoh: `LR1010_B2_TCT_u1.csv`.
Gangguan: awalan `E` (mis. `LR1010_E2_4S_u2.csv`). Berkas gagal dipisah ke subfolder `_dibuang/` dengan alasan.
Jangan mengubah berkas mentah; baris rusak ditangani skrip analisis.

## 5. Jumlah dan target
- Sekitar 30 kondisi x 3 ulangan x 4 topologi = 360 kurva, ditambah 1-2 sesi dinamis (F1, D2).
- Hari uji dipisah dari hari latih; tidak ada kurva kondisi uji yang dipakai melatih.
- Pembanding yang selalu dihitung dari data nyata: topologi tetap terbaik, sapuan semua topologi, dan model.

## 6. Keselamatan
- 4S bisa 88 V DC: kabel berinsulasi, tidak menyentuh terminal terbuka, tidak bekerja saat hujan atau basah.
- Ketik `OFF` sebelum menyentuh kabel atau memasang resistor/dioda/pintas.
- Panel dan MOSFET bisa panas. Beri jeda antarsiklus dan pakai sarung tangan bila perlu.
- Dua orang: satu mengoperasikan alat, satu mengubah kondisi bayangan.

## 7. Setelah pengukuran
1. Susun tabel kondisi-label-berkas (nama kondisi -> kelas diagnosis).
2. Hitung drift (A1 awal vs akhir sesi) dan simpangan baku antarulangan; laporkan.
3. Latih ulang model dengan data nyata, uji pada hari/kondisi yang tidak dipakai melatih.
4. Laporkan matriks kebingungan dan selisih daya dari pilihan terbaik; cantumkan keterbatasan.
