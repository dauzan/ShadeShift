# SHADESHIFT: peta folder

Proyek aktif: DeepTech for Smart-X Hackathon 2026 (tim ShadeShift). Lomba BREYI 2026 selesai (tidak lolos); semua berkasnya ada di `_arsip/`.

| Folder | Isi | Status |
|---|---|---|
| `SHADESHIFT_ML/` | Proyek utama: simulasi, model, uji data fisik, PCB, proposal, dokumentasi, presentasi | Aktif |
| `SHADESHIFT_ML/berkas_kirim/` | Tiga berkas yang diunggah ke Smart-X (proposal, dokumen pendaftaran, presentasi) | Final, terkirim 7 Okt 2026 |
| `SHADESHIFT_ML/data/data_lab/` | Kurva I-V fisik mentah (lampu halogen) | Aktif, lihat README di dalamnya |
| `SHADESHIFT_ML/uji_model/` | Uji model pada data fisik dan laporannya | Aktif |
| `SHADESHIFT_ML/pcb/` | PCB induk KiCad (skema, tata letak, Gerber di `produksi/`) | Siap pesan, belum dicetak |
| `analisis/` | Skrip wadah 3D, render, cek benturan, diagram blok, skema lama | Aktif |
| `wadah_3d/` | STL wadah v4 dan gambar dokumentasi | Siap cetak, belum dicetak |
| `firmware/` | Firmware ESP32, logger, siklus otomatis | Aktif |
| `foto/` | Foto purwarupa | Aktif (dipakai dokumen dan presentasi) |
| `gambar/` | Gambar hasil. `Gbr_hasil_fisik_awal.png` masih dipakai; `gbr1`-`gbr11` dan `hasil/` adalah gambar naskah BREYI | Campuran |
| `rangkaian/` | Panduan rakit, daftar belanja, daftar kabel, gambar rangkaian versi BREYI | Rujukan; lihat catatan |
| `_arsip/` | Semua berkas BREYI 2026 dan versi lama | Arsip, tidak dipakai skrip |

## Catatan
- `rangkaian/daftar_kabel.md` dan `rangkaian/skema_shadeshift.png` masih memakai susunan relai lama (8 kanal + dua 4 kanal).
  Susunan yang berlaku: tiga modul relai 4 kanal (M1 = R1-R4, M2 = R0 dan R5-R7, M3 = R8-R10), lihat `SHADESHIFT_ML/pcb/README.md`
  dan `SHADESHIFT_ML/pendaftaran/gambar/gbr_matriks_relai.png`.
- Gambar skema dan matriks versi terbaru ada di `SHADESHIFT_ML/pendaftaran/gambar/`.
- Penataan 8 Okt 2026: tidak ada berkas yang dihapus; daftar semua pemindahan ada di `_arsip/DAFTAR_PEMINDAHAN.csv`.
