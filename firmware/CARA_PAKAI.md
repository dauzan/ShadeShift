# Firmware SHADESHIFT 3.2: cara pakai

**Satu firmware untuk semuanya** (pengambilan data dan Demo Day): `firmware/shadeshift_firmware/shadeshift_firmware.ino`.
Isinya: penjejak kurva I-V dengan urutan aman pindah susunan (sama dengan v2), sapuan satu panel A-D, sensor cahaya LDR,
**pemilih susunan (AI) di ESP32**, **diagnosis penyebab (AI) di ESP32** (`DIAG`), dan **halaman web dari ESP32**.

**Status:** dikompilasi dan diuji di laptop dengan tiruan perangkat keras yang memutar ulang kurva lab
(`tests/test_firmware*.py`). Uji itu juga membuktikan bahwa untuk perintah lama, hasil ukurnya **sama persis dengan
firmware v2 asli**. **Belum pernah dijalankan di papan**: lakukan "Cek pertama" (bagian 5) sebelum sesi data pertama.

**Cadangan darurat:** firmware v2 asli tersimpan tanpa diubah di `docs/before/firmware/shadeshift_firmware/`. Pakai hanya
bila firmware 3.2 gagal di papan: salin folder itu ke tempat lain, unggah. Dasbor tetap jalan, tetapi tanpa sapuan per
panel, tanpa sensor cahaya dan tanpa AI di ESP32 (AI berjalan di laptop).

## 1. Unggah ke ESP32
1. **Arduino IDE 2**, *Boards Manager*: **esp32 by Espressif**. *Library Manager*: **Adafruit ADS1X15**, **Adafruit MCP4725**.
   (WiFi dan WebServer sudah termasuk paket esp32.)
2. Buka `firmware/shadeshift_firmware/shadeshift_firmware.ino`. Berkas `.h` lain di folder yang sama ikut terbuka sebagai tab.
3. Isi bagian **"WAJIB DIISI"** di atas berkas: `R_ATAS`, `R_BAWAH` (ukur resistor pembagi dengan multimeter), `R_SHUNT`
   (biasanya 0,100), `V_OFFSET`, `I_OFFSET` (dari perintah `KAL`, bagian 3).
4. **Ganti sandi WiFi**: `#define WEB_SANDI "ganti-sandi-ini"` (minimal 8 karakter, jangan sandi pribadi).
   `#define WEB_SAAT_NYALA 1` = WiFi menyala saat ESP32 menyala; ubah ke `0` bila ingin WiFi mati sampai diketik `WEB 1`.
5. Board **ESP32 Dev Module**, pilih port COM, **Upload**. Bila macet di "Connecting...", tahan tombol **BOOT**.
6. Serial Monitor **115200 baud**, akhir baris **Newline**. Harus muncul `# SHADESHIFT firmware 3.2.0` dan baris `# INFO fw=3.2.0, ...`.
7. Tutup Serial Monitor sebelum menjalankan dasbor (`start_live.bat`): hanya satu program boleh memakai port USB.

## 2. Pasang sensor cahaya (LDR) — tanpa beli: LDR yang ada + resistor 10 kΩ
```
3,3 V ──── LDR ────┬──── ADS1115 A2
                   │
                 10 kΩ
                   │
GND ───────────────┘
```
- Makin terang = tegangan A2 makin **tinggi** (0-3,3 V). Angkanya **relatif** (bukan W/m²).
- A0 = tegangan array, A1/A3 = shunt arus: **jangan** sambungkan LDR ke kanal itu.
- Tanpa LDR, angka `# cahaya=` acak dan tidak berarti; sapuan tetap jalan normal.

## 3. Uji TANPA panel (uji bangku)
Perintah yang menggerakkan relai/DAC secara manual hanya jalan di **mode bangku** (`BENCH 1`), dan hanya **tanpa panel**.

| Ketik | Yang harus terjadi |
|---|---|
| `SCAN` | Muncul `0x48` (ADS1115) dan `0x60` atau `0x62` (MCP4725) |
| `BENCH 1` | `# BENCH ON: HANYA TANPA PANEL ...` |
| `DAC 2048` | Multimeter di kaki OUT LM358 (pin 1): ±3,3 V. `DAC 4095` → ±6,6 V. `DAC 0` → ±0 V |
| `UJIRELAI` | Relai R0 sampai R10 berbunyi klik satu per satu |
| `RELAI 6 1` lalu `RELAI 6 0` | Satu relai menyala/mati (nomor 0-10, tabel relai di `rangkaian/daftar_kabel.md`) |
| `OFF` | Semua mati; mode bangku berakhir |
| `CEKVOC 0` lalu `4S` | Relai R1, R4, R5 menyala. Cek kontinuitas di Wago: hanya A−↔B+, B−↔C+, C−↔D+. Ulangi `2S2P`, `TCT`, `4P` dan panel `A`, `B`, `C`, `D` (relai: A = R7, B = R2+R8, C = R3+R9, D = R10) |
| `KAL` | Saat semua mati: V dan I mendekati 0. Catat sebagai offset (bagian 1 langkah 3) |
| `OFF` lalu `CEKVOC 1` | **Wajib**: nyalakan lagi pengecekan Voc sebelum memasang panel |

Uji sapuan tanpa panel: adaptor 12 V lewat **resistor 47 Ω 5 W** (atau bohlam 12 V kecil) ke titik P dan N, `CEKVOC 0`,
`4P`, `SWEEP uji`. Bandingkan V dan I dengan multimeter. Jangan pakai resistor lebih kecil (10 Ω bisa panas sampai 14 W).

## 4. Uji model AI di papan (sekali)
Buka `SHADESHIFT_ML/edge_ai/pemilih/uji_pemilih/uji_pemilih.ino`, unggah, Serial Monitor 115200. Harus muncul
**`LULUS 12/12`** dan `waktu rata-rata ... us`. **Catat waktunya** (latensi AI di papan, untuk laporan teknis).
Lalu unggah kembali `shadeshift_firmware.ino`.

## 5. Cek pertama dengan panel (sekitar 30 menit, sebelum sesi data pertama)
Catat hasil tiap langkah.
1. `INFO` → `fw=3.2.0`, `w=cbe60e1a8194`, `fitur=panel,cahaya,pemilih,web`.
2. `CAHAYA` di terang, lalu tutup LDR dengan jari, `CAHAYA` lagi: angka kedua jauh lebih kecil.
3. `4S`, `SWEEP uji_4S` → blok sapuan dengan `# cahaya=`, `# cahaya_akhir=` dan `# pemilih=...`. **Catat `t_us`**.
4. Tiap panel: `A`, `SWEEP uji_A`, lalu `B`, `C`, `D`. Tiap kali `# siap: <panel>` dan Voc sekitar Voc satu panel
   (18-21 V di bawah lampu). Bila `# GAGAL: Voc di luar ...` pada satu panel: cek kabel relai panel itu dan konektornya.
   Tutup panel A dengan kertas, ulangi `A`, `SWEEP`: Pmax harus turun jelas.
5. Jumlah Pmax A+B+C+D kira-kira sama atau sedikit lebih besar dari Pmax `4P` pada cahaya yang sama. Jauh lebih kecil:
   ada relai yang tidak menutup.
6. **WiFi dan pengukuran**: `WEB 1`, `4S`, `SWEEP wifi_on`; lalu `WEB 0`, `SWEEP wifi_off`. Kedua kurva harus hampir sama.
   Bila berbeda jelas, ambil data dengan `WEB 0` (atau `WEB_SAAT_NYALA 0`).
7. `PILIH` → berakhir `# PILIH SELESAI: <susunan>`. Ulangi `PILIH`, ketik `OFF` selama sapuan → `# PILIH dihentikan`.
8. Dengan laptop: tutup Serial Monitor, `start_live.bat`. Halaman **Status**: firmware `v3.2 (3.2.0)`, "ya, bobot sama",
   fitur `panel, cahaya, pemilih, web`. Halaman **Langsung**: **Pilih susunan otomatis** → "Diputuskan oleh: ESP32 (di papan)".

Semua lulus: pakai firmware ini untuk semua hari. Ada yang gagal: kabari, dan sementara pakai cadangan darurat (atas).

## 6. Hari pengambilan data
- Pakai dasbor, halaman **Ambil data** (sesi, label, scan penuh, suhu, ekspor). Langkahnya di `START_HERE.md` bagian 4.
- Ketik `WEB 0` (lewat kotak **Perintah firmware** di halaman Langsung) bila WiFi mengganggu pengukuran.
- `logger_shadeshift.py` (logger lama, tanpa dasbor) tetap bisa dipakai: `python firmware/logger_shadeshift.py COM3`,
  berkas masuk ke folder `data_lab/` di folder proyek (bukan data lab mentah). Halaman Ambil data lebih lengkap.

## 7. Halaman web ESP32 dan DIAG
- **Halaman web**: sambungkan ponsel/laptop ke WiFi **SHADESHIFT**, buka **http://192.168.4.1**. Tampil: susunan aktif,
  Pmax, kurva I-V terakhir, keputusan pemilih dan diagnosis di ESP32, peringatan, tombol **STOP** (juga menghentikan
  PILIH/DIAG/SIKLUS). Hanya baca: pindah susunan tetap lewat laptop/Serial Monitor. Tidak diperbarui selama sapuan (~3-4 s).
  Tanpa internet. Kabel USB ke laptop tetap dipakai untuk dasbor dan penyimpanan data.
- **DIAG**: di dasbor, halaman **Model AI**, latih dan **aktifkan** model diagnosis (sebaiknya dengan data sesi terukur).
  Berkas `diagnosis_model.h` otomatis ditulis ke folder firmware. **Unggah ulang firmware**, lalu ketik `DIAG` (Serial
  Monitor, atau kotak Perintah firmware di halaman Langsung). Sekitar 20 detik: 4 topologi disapu, lalu
  `# diagnosis=<kelas>, yakin=<0-1>, model=<id>, t_us=<waktu>`; semua relai dibuka. **Catat `t_us`**. Tanpa model,
  DIAG menjawab bahwa model belum dipasang.
- **Daya kendali** (target proposal ≤ 0,25 W): ukur arus ESP32 dan relai dengan multimeter **dua kali, `WEB 0` dan `WEB 1`**
  (WiFi menambah arus), isi keduanya di halaman **Target vs Bukti**.

## 8. Semua perintah
| Perintah | Fungsi |
|---|---|
| `4S`, `2S2P`, `TCT`, `4P` | Pindah susunan lewat urutan aman (DAC 0, R0 buka, semua buka, tutup target, 250 ms, cek Voc, R0 tutup) |
| `A`, `B`, `C`, `D` | Satu panel saja, urutan aman yang sama, cek Voc untuk satu panel |
| `SWEEP <label>` | Ukur kurva I-V susunan aktif; pada 4S pemilih AI ikut berjalan (`# pemilih=...`) |
| `PILIH` | Pilih susunan otomatis **di ESP32**: 4S → SWEEP → AI → pindah → SWEEP |
| `DIAG` | Diagnosis penyebab **di ESP32** (bagian 7) |
| `OFF` / `STOP` | Semua relai buka, MOSFET mati; juga menghentikan PILIH, DIAG, SIKLUS di antara langkah |
| `STATUS` | `# topologi=..., R0=..., cekVoc=..., bench=..., fw=3.2.0` |
| `INFO` | Versi, id chip, sidik bobot AI (`w=`), fitur |
| `VOC` / `PANTAU 1` / `PANTAU 0` | Tegangan array sekali / tiap 0,5 detik / berhenti |
| `CAHAYA` | Baca LDR di A2 |
| `VPANEL <volt>` | Voc satu panel saat ini (bawaan 21). Batas cek Voc = 0,5-1,2 × panel seri × nilai ini. Lampu redup: `VPANEL 17` |
| `CEKVOC 0` / `CEKVOC 1` | Matikan / nyalakan cek Voc (0 hanya untuk uji tanpa panel) |
| `SIKLUS <label> <ulangan>` | Ukur 4 topologi acak per putaran, berhenti tiap putaran (`LANJUT` / `BATAL` / `OFF`). Dasbor memakai scan penuh sebagai gantinya |
| `WEB 1` / `WEB 0` | WiFi dan halaman web menyala / mati |
| `BENCH 1` / `BENCH 0` | Mode uji bangku TANPA PANEL: membuka `DAC`, `UJIRELAI`, `RELAI` (bagian 3) |
| `SCAN`, `KAL`, `BANTUAN` | Cari perangkat I2C, baca ADC mentah, daftar perintah |

Dari dasbor, perintah berbahaya (`RELAI`, `UJIRELAI`, `DAC`, `CEKVOC 0`, `SIKLUS`, `BENCH`, `TAHAN 1`) ditolak; pakai Serial
Monitor dengan dasbor dimatikan. `PILIH` diganti tombol **Pilih susunan otomatis**.

## 9. Keselamatan
- Pindah susunan **hanya lewat perintah** (firmware memastikan arus nol saat relai bergerak).
- `# GAGAL: Voc di luar ...` → semua relai terbuka otomatis. Cek kabel relai sebelum mencoba lagi.
- **Ketik `OFF` (atau STOP di dasbor / halaman web) sebelum menyentuh kabel.** Pada 4S tegangan bisa sekitar 88 V DC.
  STOP tanpa perangkat lunak: cabut adaptor 12 V.
- `TAHAN` (menahan MOSFET di titik daya maksimum) sengaja **tidak ada**: risiko panas pada MOSFET dan heatsink kecil.
