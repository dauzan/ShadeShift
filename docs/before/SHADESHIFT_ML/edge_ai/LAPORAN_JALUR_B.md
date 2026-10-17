# Laporan: perbaikan pemilih dan jalur B (8 Oktober 2026)

## 1. Bug Voc di simulasi (ditemukan di awal jalur B)
Sapuan simulasi melewati Voc sampai arus negatif. Diperbaiki, semua dataset dibuat ulang. Rincian dan dampak: `../CATATAN_BUG_VOC.md`.
Ringkas: angka daya aman; diagnosis simulasi 83-89% menjadi **78-82%**.

## 2. Perbaikan model pemilih (`pemilih/perbaiki.py`, `pemilih/evaluasi.py`)
Metrik sama dengan proposal: poin % daya MLPE yang hilang (skenario MLPE > 1 W).

| Model (sapuan 4S) | Simulasi | Lab (6 pola) |
|---|---|---|
| **Regresi logistik (dipakai di ESP32)** | **2,94-3,00 poin** | **0,82%** |
| Regresi kuadratik rasio daya | 2,53 | 3,45% |
| MLP kecil rasio daya | 2,82 | 5,24% |
| Sensitif biaya / kelas seimbang | 3,37 / 4,87 | 10,04% / 0,70% |
| Susunan tetap terbaik | 6,35 (TCT) | 2,71% (2S2P) |

- Model sekarang memangkas rugi sekitar setengahnya di simulasi; tidak ada kandidat yang lebih baik sekaligus di simulasi dan lab.
- Catatan koreksi: evaluasi sebelumnya (persen terhadap daya terbaik) menyimpulkan keunggulan "tipis"; itu artefak skenario berdaya
  sangat kecil. Dengan metrik yang benar keunggulannya jelas.
- Sapuan TCT lebih baik di simulasi (1,3-1,4 poin) tetapi lebih buruk di lab (4,0%); sapuan 4S dipertahankan.
- **Keputusan: model regresi logistik tetap dipakai.** Berkas ESP32 tidak berubah.

## 3. Jalur B langkah 1: kembaran digital lampu lab (`kembaran_lab/cocokkan_lampu.py`)
Model cahaya per sel (sumber titik di atas susunan 2x2, sebaran antarsel, suhu, pengali hambatan paralel), 7 parameter dicocokkan
hanya pada V1c (tanpa bayangan). Transmisi paranet diukur dari satu rasio Isc 4P (hasil: 0,11).
- Parameter: G0 237 W/m2 di pusat, h 5 lebar sel (cahaya turun tajam ke tepi), sebaran 7%, suhu 34 C, hambatan paralel 0,31 x datasheet.
- Ramalan 7 kondisi bayangan yang tidak dipakai mencocokkan: galat Pmax **8,0%** (simulator lama 18,6%), galat kurva 0,117 (lama 0,165),
  susunan terbaik sama dengan lab 5/7 (dua yang meleset: bayangan diagonal V6, sama dengan kesalahan model pemilih).
- Gambar: `kembaran_lab/kembaran_vs_lab.png`.

## 4. Jalur B langkah 2-3: diagnosis dengan domain randomization dan CNN (`kembaran_lab/uji_kembaran.py`, `cnn_diagnosis.py`)
Data latih 9.000 kurva kembaran teracak (6 kelas, cahaya merata sampai tidak merata, 60-1000 W/m2, 15-65 C, hambatan paralel 0,15-1,5x).
Tidak ada kurva lab yang dipakai melatih.

| Model | Akurasi data kembaran tahan | Akurasi lab (normal/opak/paranet, 30 set) |
|---|---|---|
| Model simulasi lama (sesudah perbaikan bug) | - | 3-13% |
| Reg. logistik / MLP / hutan acak, 4 sapuan | 74-76% | 13-27% |
| CNN 1D (6.230 parameter, 4 x 64 titik, PyTorch) | 69% | 13% |

- Kurva lab normal tidak pernah dikenali sebagai normal (ditebak "dioda terbuka" atau "bayangan opak"); paranet kebanyakan ditebak opak.
- **Kesimpulan: diagnosis tidak bisa divalidasi dengan data lampu halogen, berapa pun canggih modelnya.** Kembaran cukup akurat untuk
  daya (8%), tetapi diagnosis membutuhkan detail bentuk kurva yang lebih halus daripada yang bisa ditiru simulasi kondisi lampu ini.
  CNN tidak lebih baik dari model sederhana.
- Yang dibutuhkan: data nyata berlabel (jalur C), sebaiknya di bawah matahari (cahaya merata), dengan gangguan sengaja.

## 5. Yang bisa dipakai untuk Demo Day
- Pemilih susunan di ESP32 (terbukti di lab: rugi 0,82% vs 2,71% susunan tetap).
- Kembaran digital: "daya yang seharusnya" per susunan dengan galat sekitar 8% di lab; bisa dipakai dasbor untuk membandingkan daya
  terukur dengan daya harapan (indikasi kelainan), tanpa mengklaim diagnosis penyebab.
- Diagnosis penyebab: tetap berlabel simulasi (78-82%) sampai ada data jalur C.
