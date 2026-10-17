# Pemilih susunan di ESP32 (untuk Dauzan)

Model: regresi logistik, dilatih **simulasi** (12.000 skenario), membaca **satu sapuan 4S** dan memilih **4S / 2S2P / TCT**
(4P tidak dipilih karena di bawah jendela pengendali 24 V). Diuji pada data lab (tidak pernah dilatih dengannya): rugi rata-rata
0,82% terhadap susunan terbaik, dibanding 2,71% bila susunan tetap 2S2P (lihat `../../uji_model/LAPORAN_UJI_FISIK.md`).

## Berkas
| Berkas | Isi |
|---|---|
| `pemilih.h` | Kode C (float32, tanpa malloc): cuplik ulang, 14 fitur, keputusan |
| `pemilih_bobot.h` | Bobot model (dibuat otomatis) |
| `uji_pemilih/` | Sketsa uji ESP32 dengan 12 kurva lab dan hasil harapan dari Python |
| `latih_ekspor.py` | Melatih, mengekspor bobot, memverifikasi, membuat data uji |
| `port_c.py` | Tiruan Python dari `pemilih.h` (dipakai verifikasi) |
| `referensi_lab_4S.csv` | Fitur dan keputusan untuk semua kurva lab 4S |

## Status verifikasi
- Tiruan C vs pipeline Python asli (numpy/scipy/scikit-learn): selisih fitur < 1,5e-6, keputusan sama pada 38 kurva lab dan 300 kurva simulasi.
- Sketsa uji terkompilasi untuk ESP32 (esp32:esp32 3.3.12): 292 KB flash, 25 KB RAM global (sebagian besar data uji).
- **Belum dijalankan di papan.** Langkah pertama: unggah `uji_pemilih`, buka Serial Monitor 115200, harus muncul `LULUS 12/12`.

## Cara pakai di firmware
```c
#include "pemilih.h"
// setelah SWEEP pada susunan 4S, simpan titik ke larik (jangan hanya dicetak):
float bufV[210], bufI[210]; int n = ...;            // n titik termasuk titik Voc pertama
float V201[PEMILIH_N], I201[PEMILIH_N], f[PEMILIH_N_FITUR], skor[PEMILIH_N_KELAS];
if (pemilih_cuplik_ulang(bufV, bufI, n, V201, I201) == 0) {    // bufV/bufI diubah di tempat
  pemilih_fitur(V201, I201, f);
  int k = pemilih_putuskan(f, skor);                           // 0 = 4S, 1 = 2S2P, 2 = TCT
  // pindah(k) bila berbeda dari susunan sekarang
}
```
Fungsi `sapuan()` di `firmware/shadeshift_firmware.ino` sekarang hanya mencetak titik lewat Serial; perlu ditambah penyimpanan ke larik.

## Aturan data yang harus sama
- Titik dengan V <= 0 dibuang; arus negatif dijepit ke 0.
- Titik dengan tegangan sama persis dirata-ratakan arusnya (sebelumnya urutannya acak dan mengubah fitur).
- Model melihat **bentuk** kurva saja (rasio terhadap Voc dan Isc), jadi tidak bergantung pada kalibrasi arus mutlak, tetapi
  bergantung pada rentang sapuan penuh dari dekat 0 V sampai Voc.

## Batasan
- Hanya memilih susunan; **belum** mendiagnosis penyebab.
- Diuji pada 6 pola bayangan di bawah lampu halogen; kesalahan terbesar pada bayangan diagonal A+D (memilih TCT, 2S2P lebih baik 4,9%).
- Sebaiknya tambahkan ambang: pindah hanya bila susunan baru diperkirakan lebih baik dari rugi pensaklaran, agar relai tidak bolak-balik.
