# Firmware SHADESHIFT v3: pemilih (AI) berjalan di ESP32

v3 = v2 + **pemilih susunan di papan** (TinyML) + perbaikan keselamatan. Urutan aman pindah susunan **tidak berubah**,
format sapuan sama dengan v2 (logger, dasbor, dan skrip lama tetap bisa membacanya). Firmware v2 tetap ada di
`firmware/shadeshift_firmware/` sebagai cadangan.

**Status:** v3 dikompilasi dan diuji di laptop dengan tiruan perangkat keras yang memutar ulang kurva lab
(`tests/test_firmware_v3.py`). **Belum pernah dijalankan di papan.** Ikuti daftar periksa di bawah dan catat hasilnya.

## Yang baru
| Perintah / keluaran | Arti |
|---|---|
| `# pemilih=TCT, skor=a;b;c, t_us=850` | Muncul di setiap SWEEP pada **4S**, sebelum `# SELESAI`. Keputusan dihitung **di ESP32** (`pemilih.h`, 73 angka bobot). `t_us` = waktu cuplik ulang + 14 fitur + model di ESP32 (untuk laporan teknis: latensi) |
| `PILIH` | Pilih susunan otomatis **di papan**: 4S → SWEEP → pemilih → pindah ke pilihan (urutan aman) → SWEEP → `# PILIH SELESAI: TCT`. OFF menghentikannya |
| `INFO` | `# INFO fw=3.0.0, id=<chip>, n=201, w=cbe60e1a8194`. `w` = sidik bobot pemilih; harus sama dengan model laptop (`run.py check` / halaman Status). Gateway memeriksa otomatis |
| `# meta t_ms=..., seq=...` | Waktu sejak menyala dan nomor sapuan, sesudah `# MULAI` |
| `BENCH 1` / `BENCH 0` | Mode uji bangku **TANPA PANEL**. `RELAI`, `UJIRELAI`, `DAC` hanya jalan dalam mode ini (v2 menerimanya kapan saja bila tidak ada susunan aktif). `OFF` juga mengakhiri mode ini |
| OFF di dalam SIKLUS | `OFF`, `STOP`, `BATAL` sekarang dibaca di antara langkah SIKLUS dan saat menunggu LANJUT (v2 mengabaikannya). Sapuan yang sedang berjalan (~3-4 s) tetap diselesaikan dulu |
| Sapuan gagal | SIKLUS berhenti dan semua relai dibuka (v2 melanjutkan dengan berkas hilang) |
| `STATUS` | `# topologi=..., R0=..., cekVoc=..., bench=..., fw=3.0.0` |

Pemilih memakai angka yang **sama persis dengan yang dicetak** lewat serial, jadi keputusan papan bisa dihitung ulang dari log.

## Daftar periksa di papan (19-20 Okt), catat hasil tiap langkah
Siapkan: Arduino IDE + board **esp32 by Espressif**, pustaka **Adafruit ADS1X15** dan **Adafruit MCP4725**.
Tutup gateway (`run.py live`) dan Serial Monitor lain sebelum mengunggah.

1. **Uji model saja**: buka `SHADESHIFT_ML/edge_ai/pemilih/uji_pemilih/uji_pemilih.ino`, unggah, Serial Monitor 115200.
   Harus muncul `LULUS 12/12` dan `waktu rata-rata ... us`. **Catat waktunya** (latensi di papan untuk laporan teknis).
2. **Unggah v3**: buka `firmware/shadeshift_firmware_v3/shadeshift_firmware_v3.ino` (tiga berkas `.h` di folder yang sama
   ikut terbuka sebagai tab). Isi bagian "WAJIB DIISI" sama seperti v2 (`R_ATAS`, `R_BAWAH`, offset). Unggah.
3. **Serial Monitor** (115200, Newline): saat menyala muncul `# SHADESHIFT firmware v3` dan baris `# INFO ... w=cbe60e1a8194`.
   Bila `w` lain: header bobot salah salin; salin ulang `pemilih_bobot.h` dari `SHADESHIFT_ML/edge_ai/pemilih/`.
4. **Uji tanpa panel** (sama dengan CARA_PAKAI.md bagian 3, tetapi dengan BENCH): `RELAI 6 1` harus ditolak;
   `BENCH 1`, lalu `RELAI 6 1` / `RELAI 6 0`, `DAC 2048`, `UJIRELAI` berjalan; `OFF` mengakhiri mode bench.
5. **Dengan panel, di bawah lampu**: `STATUS`, `4S`, `SWEEP uji_4S` → blok sapuan dengan baris `# pemilih=...`.
   **Catat `t_us`.** Lalu `PILIH` → harus berakhir dengan `# PILIH SELESAI: <susunan>` dan relai pada susunan itu.
6. **OFF di tengah tugas**: `PILIH`, lalu ketik `OFF` selama sapuan 4S → `# PILIH dihentikan`, semua relai terbuka.
   `SIKLUS uji 1`, `LANJUT`, lalu `OFF` di tengah → `# siklus dihentikan (OFF)`.
7. **Dengan laptop**: tutup Serial Monitor, jalankan `.venv\Scripts\python run.py live`. Di dasbor halaman **Status** kolom
   firmware harus `v3 (3.0.0)`. Di halaman **Langsung** tekan **Pilih susunan otomatis**: keputusan harus tertulis
   **"Diputuskan oleh: ESP32 (di papan)"**, dengan pemeriksaan silang laptop di riwayat keputusan.
8. **Ukur daya** ESP32 + relai dengan multimeter yang ada (arus catu 5 V relai per susunan, arus USB ESP32) untuk laporan
   teknis. Tidak perlu membeli alat.

Bila v3 bermasalah di papan: unggah kembali v2 (`firmware/shadeshift_firmware/`). Dasbor, gateway, dan mode demo tetap
berjalan dengan v2; keputusan AI lalu dihitung di gateway laptop dan tertulis "gateway laptop (ONNX Runtime)".

## Belum ada di v3 (sengaja)
- `TAHAN` (menahan MOSFET di titik daya maksimum untuk memantau daya tanpa menyapu): risiko panas pada MOSFET dan heatsink
  kecil. Baru ditambahkan setelah uji panas di papan.
- Anti bolak-balik dan pemicu 20 % di papan: sekarang dijalankan gateway (mode otomatis), memakai keputusan ESP32.
