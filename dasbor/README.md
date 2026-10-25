# Dasbor SHADESHIFT (L1 digitalisasi)

Dasbor Streamlit untuk Demo Day: kurva I-V dan P-V, susunan aktif, keputusan pemilih (AI) dan **di mana** ia dihitung,
daya terukur vs **daya harapan** dari kembaran digital, riwayat, unggah CSV, dan jejak audit.

Sejak 18 Okt 2026 dasbor ini **klien API server lokal**. Alurnya: ESP32 → gateway (laptop) → server (basis data SQLite)
→ dasbor. Dasbor tidak lagi membuka port serial: menyegarkan halaman atau membuka tab kedua aman, dan semua data tersimpan.

## Menjalankan
Dari folder proyek, dengan venv di drive D:
```
.venv\Scripts\python run.py demo      tanpa alat: ESP32 tiruan memutar ulang kurva lab (berlabel DEMO)
.venv\Scripts\python run.py live      dengan ESP32 di USB (port dicari otomatis; --port COM5 untuk memilih)
```
Browser terbuka ke http://127.0.0.1:8501. Hentikan dengan **Ctrl+C** di jendela yang sama: gateway membuka semua relai
dulu. Menutup jendela juga mengirim OFF, tetapi Ctrl+C lebih aman. Dasbor hanya bisa dibuka dari laptop ini.

## Halaman

Tampilan konsumen (22 Okt, CONTRACT bagian 19): navigasi atas dengan tiga halaman, latar putih, hanya kata-kata.

| Halaman | Isi |
|---|---|
| **Beranda** | Model 3D susunan panel dengan kondisi tiap panel, kartu masalah (apa, di mana, seberapa besar, sejak kapan, saran), daya susunan, harapan model kembaran, kendali pemantauan |
| **Kurva I-V** | Sederhana dulu: kotak AI (yang baru, 24 jam, saat ini), daya sekarang dan dibanding normal, daya dari waktu ke waktu, daya tiap panel; kurva lengkap, enam tanda gangguan dan kurva tiap panel di Lihat kurva lengkap |
| **Rekomendasi Rangkaian** | Model 3D panel dan rangkaiannya dengan aliran listrik; saran AI dengan alasan dan keuntungan terukur; Bandingkan semua rangkaian; Terapkan saran (minta persetujuan, lalu pindah dengan aman dan tampilkan sebelum dan sesudah) |
| **Perangkat** | Pusat status semua bagian: server, gateway, ESP32 (port, firmware, AI, halaman Wi-Fi), ADS1115 dan MCP4725 di jalur I2C, sensor tegangan, jalur arus, sensor cahaya, relai, panel A sampai D, pemantauan. Tombol Periksa ulang perangkat |
| **Riwayat** | Tab Ringkasan: 24 jam terakhir, garis waktu kondisi tiap panel, daya susunan terhadap harapan, kejadian dan ringkasan; pengukuran terbaru. Tab Jejak audit: siapa melakukan apa dan kapan (24 jam, 7 hari, 30 hari, semua, atau rentang tanggal), 100 baris per halaman, unduhan CSV |

Halaman lama di bawah tetap ada di `halaman/` tetapi tidak ditampilkan:
| Halaman | Isi |
|---|---|
| **Langsung** | Pilih alat (ESP32 atau tiruan). Tombol susunan, panel A-D (firmware 3.2), SWEEP, STATUS, pilih otomatis, **audit keputusan AI**, mode otomatis, STOP. Diagnosis AI terakhir dengan peta modul 2x2. Metrik Pmax, daya harapan, keputusan AI dengan "diputuskan oleh" dan waktu keputusan. Grafik, riwayat sapuan, peristiwa, log serial. Diperbarui tiap detik |
| **Model AI** | Data yang tersedia (terukur, lab, simulasi) per kelas dan hari; impor zip sesi; latih kandidat diagnosis (regresi logistik atau pohon) atau pemilih; uji adil (hari lain, atau scan lain); semua versi tersimpan dengan hasil ujinya; matriks kebingungan; unduh header ESP32; jadikan aktif (pemilih hanya bila lebih baik dari yang aktif) |
| **L3 dan stabilitas** | Lapisan L3 (saklar semikonduktor, hitungan desain tim): daya penahan per susunan relai vs semikonduktor, keuntungan bersih, susunan aktif, isian multimeter. Aturan stabilitas: hasil simulasi dan putar ulang scan F1 terukur |
| **Target vs Bukti** | Empat target proposal dan buktinya, berlabel terukur / lab / simulasi / hitungan. Pemulihan daya terhadap MLPE ideal (jumlah Pmax panel A-D) per putaran scan dan audit, isian daya kendali dari multimeter, waktu terukur, unduh CSV untuk laporan teknis |
| **Kembaran Digital** | Model kawat susunan panel yang sebenarnya (4 panel 9 x 4 sel dan kotak kendali). Kamera tidak bisa digeser; ia berputar sendiri: ke punggung panel (dioda pelewat) bila penanda biru menunjuk tegangan turun, ke samping (kabel dan konektor) bila hambatan seri. Cermin langsung: rangkaian aktif, relai, penanda per panel (hijau sehat, merah cahaya, biru listrik, abu-abu putus-putus belum pasti), suhu, diagnosis AI. What-if (simulasi): kuas bayangan, perkiraan daya tiap susunan dan pilihan AI, log, banding dengan pengukuran nyata. Kalibrasi kembaran dan ambang peringatan ada di sini (bukan lagi di sisi kiri) |
| **Ambil data** | Sesi pengukuran berlabel: mulai sesi (tempat, langit, lokasi, operator), pilih kode kondisi protokol (A1, B1-B7, C1-C5, D1-D2, E1-E5, F1), modul dan kelas diagnosis, lalu **scan penuh** (4 topologi + panel A-D, urutan acak, jeda suhu antarputaran). Pemeriksaan mutu tiap scan, isian suhu panel per ulangan, koreksi label, ekspor zip (berkas mentah + `labels.csv`) |
| **Putar ulang** | Data lab (120 kurva, ringkasan 30 set: 0,82 / 2,71 / 4,30 / 12,0 %, lab), unggahan CSV, sesi rekaman alat/demo |
| **Unggah CSV** | Unggah berkas format firmware atau CSV biasa `V,I` / `V,I_mA`; tiap berkas diterima atau ditolak dengan alasan; keputusan AI untuk sapuan 4S. Contoh di `samples/` |
| **Peristiwa** | Jejak audit: perintah, perpindahan, keputusan AI, peringatan, galat; unduh CSV |
| **Status** | Server, gateway, runtime AI, kembaran, klaim yang boleh dipakai, arti label sumber data |

## Keselamatan
- STOP (di sisi kiri dan di halaman Langsung) membatalkan tugas otomatis dan membuka semua relai di semua alat.
  Firmware menyelesaikan langkah yang sedang berjalan dulu (sapuan bisa 3-4 s). Tanpa perangkat lunak: cabut adaptor 12 V.
- RELAI, UJIRELAI, DAC, CEKVOC 0, SIKLUS dan TAHAN 1 tidak bisa dikirim dari dasbor. Uji bangku memakai Serial Monitor
  Arduino tanpa panel, dengan gateway dimatikan.

## Label sumber data
terukur (ESP32) · DEMO: data lab diputar ulang · unggahan CSV · data lab (lampu halogen) · kembaran (simulasi, garis putus).
Kembaran dicocokkan pada V1c (galat daya ~8 % di 7 kondisi lab); di tempat lain ketelitiannya belum diketahui. Selisih besar =
indikasi kelainan, bukan diagnosis tervalidasi.

## Berkas
| Berkas | Isi |
|---|---|
| `app.py` | Navigasi dan sisi kiri (STOP, pengaturan kembaran) |
| `halaman/*.py` | Lima halaman |
| `umum.py` | Klien API, grafik, label |
| `inti.py`, `koneksi.py` | Pengalih ke `shadeshift/inti.py` dan `shadeshift/koneksi.py` (dipakai gateway dan skrip lama) |
| `uji_dasbor.py` | Uji lama tanpa alat (pemilih vs C, angka lab, alur tiruan) |

## Belum diuji dengan alat
Jalur serial gateway baru diuji dengan ESP32 tiruan. Uji pertama dengan alat: `run.py live`, lalu STATUS, 4S, SWEEP,
pilih otomatis, STOP.
