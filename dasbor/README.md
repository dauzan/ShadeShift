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
| Halaman | Isi |
|---|---|
| **Langsung** | Pilih alat (ESP32 atau tiruan). Tombol susunan, SWEEP, STATUS, pilih otomatis, mode otomatis, STOP. Metrik Pmax, daya harapan, keputusan AI dengan "diputuskan oleh" dan waktu keputusan. Grafik, riwayat sapuan, peristiwa, log serial. Diperbarui tiap detik |
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
