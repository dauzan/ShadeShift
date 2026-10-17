# Uji model pada data fisik (8 Oktober 2026)

Skrip: `uji_model/uji_data_fisik.py` (hasil di `uji_model/hasil/`), grafik: `uji_model/grafik_uji_fisik.py`.

## Data
- 120 kurva I-V lampu halogen: 10 kondisi × 4 susunan × 3 ulangan. Kondisi normal: V1 (lampu jauh), V1b (pengulangan V1), V1c (lampu didekatkan; posisi yang sama dengan semua kondisi bayangan).
- Kondisi kembar dikelompokkan agar tidak bocor antara latih dan uji: {V1, V1b}, {V1c}, {V3 opak}, {V3 paranet 65/75}, {V4 paranet 65/75}, {V6 paranet 65/75}.
  Jadi hanya **6 pola independen**.
- Tidak ada data gangguan berlabel (dioda, hambatan seri). V5 (dioda bypass modul C tampak tidak berfungsi, 5 set) hanya eksplorasi.
- Satu berkas berbaris rusak (`V3_paranet75_TCT_u2`); baris dibuang saat dibaca, berkas mentah tidak diubah.
- Sapuan mencakup 0 sampai Voc (kecuali dua kurva TCT V3 paranet 75% yang mulai dari sekitar 10% Voc).

## A. Selisih domain
Fitur bentuk kurva lab berada di luar 95% sebaran simulasi kelasnya pada sebagian besar fitur. Kurva **normal** lab berada di luar sebaran
simulasi normal pada 10 dari 14 fitur (termasuk FF). Penyebab utama yang paling mungkin: iradiansi lampu sangat rendah (arus per modul
puluhan mA), sehingga hambatan paralel sel membuat kurva normal tampak "cacat" bagi model simulasi.

## B. Pemilihan susunan (4S, 2S2P, TCT)

| Metode | Rugi rata-rata | Rugi maks | Tepat (rugi < 0,5%) |
|---|---|---|---|
| Sapu ketiga susunan, pilih terbesar (butuh 3 sapuan dan 2 kali ganti) | 0,00% | 0,00% | 100% |
| **Model dilatih simulasi, regresi logistik, satu sapuan 4S** | **0,82%** | 4,98% | 67% |
| Model dilatih simulasi, pohon d=3, satu sapuan 4S | 1,23% | 12,4% | 63% |
| Model dilatih data lab per pola, regresi logistik, sapuan 4S | 1,60% | 9,7% | 53% |
| Susunan tetap terbaik (2S2P) | 2,71% | 10,3% | 43% |
| Susunan tetap TCT | 4,30% | 16,0% | 37% |
| Susunan tetap 4S | 12,0% | 21,9% | 30% |

- Model yang **hanya dilatih simulasi** (tidak pernah melihat data lab) dan membaca satu sapuan 4S memangkas rugi rata-rata dari 2,71%
  (susunan tetap terbaik) menjadi 0,82%. Ini satu-satunya hasil yang bebas kebocoran data dan bisa diklaim.
- Kesalahan terbesar pada V6 paranet 65% (A+D): memilih TCT, padahal 2S2P lebih baik 4,9%.
- Sapuan TCT jauh lebih buruk daripada sapuan 4S untuk keputusan ini (rugi 4,0–9,5%).
- Batasan: 6 pola independen, iradiansi rendah, 4P tidak dinilai (gugur di jendela 24 V).

## C. Diagnosis
- Model diagnosis 6 kelas yang dilatih simulasi **gagal** pada data lab: hampir semua kurva (termasuk normal) ditebak "bayangan
  sebagian" (akurasi 7–13% pada label normal/opak/paranet). Akibat selisih domain di bagian A.
- Model dilatih data lab (3 kelas, per pola): 37–57% dengan 4 sapuan; 0–10% dengan satu sapuan TCT. Pembagian per kondisi sempat
  memberi 87–90%, tetapi itu kebocoran dari kondisi kembar dan tidak boleh dipakai.
- V5 (dioda bermasalah): model tidak konsisten mengenalinya.
- **Kesimpulan: diagnosis belum tervalidasi pada data fisik.** Klaim akurasi 83–89% tetap harus diberi label "simulasi".

## Catatan penamaan
Di simulasi, kelas "redup merata" sebenarnya adalah bayangan tembus cahaya (paranet) pada 1–4 modul. Nama yang tepat: "bayangan tembus cahaya".

## Yang dibutuhkan agar diagnosis bisa diuji
1. Data berlabel dengan gangguan sengaja: dioda bypass dilepas, resistor seri ditambah, satu modul dilepas, tutup merata.
2. Acuan iradiansi (BH1750 atau sel acuan) dan suhu, agar model bisa dinormalisasi terhadap iradiansi.
3. Iradiansi lebih tinggi (matahari atau lampu lebih kuat), atau simulasi diperluas ke iradiansi sangat rendah dengan hambatan paralel terukur.
4. Minimal dua hari pengukuran; hari kedua khusus untuk uji.
