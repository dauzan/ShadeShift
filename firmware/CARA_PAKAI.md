# Firmware SHADESHIFT — cara pakai

## 1. Unggah ke ESP32 (sekali saja)
1. Pasang **Arduino IDE 2**. Di *Boards Manager*, pasang **esp32 by Espressif**.
2. Di *Library Manager*, pasang: **Adafruit ADS1X15**, **Adafruit MCP4725**, **OneWire**, **DallasTemperature**.
3. Buka `shadeshift_firmware/shadeshift_firmware.ino`, pilih board **ESP32 Dev Module** dan port COM-nya, lalu klik **Upload**.
   (Kalau upload macet di "Connecting…", tahan tombol **BOOT** di ESP32 sampai mulai mengunggah.)
4. Buka Serial Monitor: **115200 baud**, akhir baris **Newline**.

## 2. Isi dulu bagian "WAJIB DIISI" di atas file .ino
- `R_ATAS`, `R_BAWAH`: nilai asli resistor pembagi (ukur pakai multimeter sebelum dipasang).
- `R_SHUNT`: biasanya biarkan 0,100.
- `URUT_SUHU`: urutan sensor suhu → panel A, B, C, D (lihat langkah 3.3).
Unggah ulang setelah mengubah.

## 3. Urutan uji TANPA panel (hari ini)
| No | Ketik | Yang harus terjadi |
|---|---|---|
| 3.1 | `SCAN` | Muncul `0x48` (ADS1115) dan `0x60` atau `0x62` (MCP4725) |
| 3.2 | `DAC 2048` | Multimeter di kaki OUT LM358 (pin 1): ±3,3 V. `DAC 4095` → ±6,6 V. `DAC 0` → ±0 V |
| 3.3 | `SUHU` | 4 angka suhu ruang. Pegang satu sensor dengan jari → angka yang naik = sensor itu. Isi `URUT_SUHU` |
| 3.4 | `UJIRELAI` | Relai R0 sampai R10 berbunyi klik satu per satu, lampu indikatornya menyala bergantian |
| 3.4b | `RELAI 6 1` lalu `RELAI 6 0` | Menyalakan/mematikan SATU relai (nomor 0–10, lihat tabel relai di daftar_kabel.md). `OFF` mematikan semua. Hanya tanpa panel |
| 3.5 | `CEKVOC 0` lalu `4S` | Relai R1, R4, R5 menyala. Cek kontinuitas dengan multimeter di Wago: hanya A−↔B+, B−↔C+, C−↔D+ |
| 3.6 | `2S2P`, `TCT`, `4P` | Ulangi cek kontinuitas sesuai tabel keadaan relai |
| 3.7 | `KAL` | Saat semua mati: V dan I mendekati 0. Catat angkanya sebagai offset |
| 3.8 | `OFF` lalu `CEKVOC 1` | Nyalakan kembali pengecekan Voc sebelum memasang panel |

Uji sweep tanpa panel: sambungkan **adaptor 12 V lewat resistor 47 Ω 5 W** (atau bohlam 12 V kecil) ke titik P dan N sebagai pengganti panel
(jangan pakai resistor lebih kecil: 10 Ω bisa panas sampai 14 W),
`CEKVOC 0`, `4P`, `SWEEP uji`. Bandingkan V dan I dengan multimeter.

## 4. Pengukuran dengan panel
Jalankan logger di laptop supaya data tersimpan otomatis (tutup Serial Monitor dulu):
```
pip install pyserial
python logger_shadeshift.py COM3
```
Lalu, untuk setiap kondisi dan ulangan (urutan topologi diacak):
```
4S
SWEEP V3_opak_4S_u1
TCT
SWEEP V3_opak_TCT_u1
...
OFF
```
File CSV masuk ke folder `data_lab/`, formatnya sudah bisa langsung dibaca notebook (fungsi `pmax_ukur`).

## Keselamatan
- Pindah topologi **hanya lewat perintah** (firmware memastikan arus nol saat relai bergerak).
- Kalau muncul `GAGAL: Voc di luar …`, semua relai otomatis terbuka. Cek kabel relai sebelum mencoba lagi.
- Ketik `OFF` sebelum menyentuh kabel apa pun. Pada 4S tegangan bisa ±88 V.

## Tambahan firmware v2 (30-09-2026)

| Perintah | Fungsi |
|---|---|
| `PANTAU 1` / `PANTAU 0` | Tegangan array tampil otomatis tiap 0,5 detik / berhenti |
| `VPANEL <volt>` | Voc satu panel pada cahaya saat ini (bawaan 21). Batas cek Voc = 0,5–1,2 × jumlah panel seri × nilai ini. Lampu redup: turunkan, misal `VPANEL 17` |
| `SIKLUS <label> <ulangan>` | Ukur 4 topologi dengan urutan acak tiap putaran, tiap topologi = 1 sweep (CSV otomatis lewat logger). Contoh: `SIKLUS V3_opak 3` |
| `LANJUT` / `BATAL` | Jawaban saat SIKLUS berhenti untuk catat suhu punggung panel (sebelum mulai dan sesudah tiap putaran). Kalau suhu bergeser lebih dari 1 °C, tunggu dingin dulu |

R8 sekarang di modul 4 kanal lama **IN4** (GPIO27 tidak berubah).
