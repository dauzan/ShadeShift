# Langkah 1: model keputusan topologi (ML kecil), hasil awal

Folder ini terpisah dari berkas naskah BREYI. Semua angka dihasilkan ulang oleh skrip di sini.

## Alur kerja
1. `sim_core.py` : inti simulasi dari notebook v7 (parameter dari `data/shadeshift_parameter_final.csv`).
   Diperiksa terhadap `shadeshift_625_final.csv`: selisih maksimum 0,28 mW (karena parameter dibulatkan).
2. `buat_data.py` : 12.000 skenario acak yang diperluas + 1.250 skenario grid asli (625 x 2 jenis naungan).
   Perluasan: S kontinu 10-100 %, jenis naungan per modul (opak/tembus cahaya), 1/3/6/12 sel tertutup,
   iradiansi 30-1000 W/m2 (log-seragam), suhu 15-65 C, ketidakcocokan antarmodul 0,85-1,10.
3. `fitur.py` : 17 fitur dari satu sapuan 201 titik (derau 1 % arus, 0,12 % tegangan).
4. `latih.py` : pohon keputusan, regresi logistik, kNN, hutan acak; metrik utama regret (poin % daya MLPE
   yang hilang dibanding memilih topologi optimal pada jendela 30-100 V).
5. `uji_fisik.py` : model dari simulasi diuji pada 24 kurva fisik (8 kondisi x 3 ulangan), fitur tanpa skala mutlak.

## Hasil simulasi (regret rata-rata, poin % MLPE; makin kecil makin baik)
| Kebijakan | uji acak (3.000) | grid 625 asli |
|---|---|---|
| tetap 4S | 6,46 | 5,45 |
| tetap TCT | 6,01 | 11,18 |
| pohon d=3, sapuan di TCT | 1,11 | 1,34 |
| pohon d=4, sapuan di TCT | 0,90 | 0,90 |
| regresi logistik, sapuan di TCT | 0,90 | 0,90 |
| sapuan semua topologi (batas atas) | 0 | 0 |

Sapuan di 4S saja kurang informatif (regret 2,2-2,5 pada uji acak dan 6-6,5 pada grid), jadi topologi tempat
sapuan dilakukan sangat memengaruhi hasil.

## Uji fisik (24 kurva; hanya 4S, 2S2P, TCT karena 4P gugur di jendela 24 V)
Rugi rata-rata terhadap topologi terbaik terukur: tetap 2S2P 2,76 %, tetap TCT 5,36 %, tetap 4S 10,73 %.
Model dari simulasi: 1,0-2,2 % (sapuan 4S, regresi logistik 1,01 %; pohon d=3 sapuan 4S 1,52 %), tetapi dengan
sapuan TCT hasil fisiknya lebih buruk (2,19 % regresi logistik, 7,55 % pohon d=3). Sampel kecil (8 kondisi,
ulangan saling berkorelasi) dan arah hasil tidak konsisten dengan simulasi, jadi belum dapat disimpulkan.

## Catatan data
- `V3_paranet75_TCT_u2.csv` baris data pertama rusak ("35.2742,02113,0.00219,0.0770", 4 kolom). Berkas mentah tidak
  diubah; `uji_fisik.py` membuang baris dengan jumlah kolom bukan 3.
- Pohon d=3 hampir tidak pernah memilih 2S2P (hanya 4S atau TCT): pada jendela 24 V, 2S2P jarang optimal.

## Langkah berikutnya
1. Kumpulkan lebih banyak kurva fisik (otomatis lewat firmware) untuk melatih dan menguji dengan data nyata.
2. Tambahkan biaya peralihan relai pada keputusan (beralih hanya bila selisih daya > rugi peralihan).
3. Ekspor model ke C untuk ESP32 dan ukur ukuran kode serta waktu inferensi.

## Sensitivitas tegangan sistem dan ukuran modul (jendela dari lembar data pengendali)
Jendela MPPT: Victron SmartSolar 150/35 (12 V: 13-145, 24 V: 25-145, 48 V: 49-145 V) dan 250/60 (48 V: 49-245 V).
Topologi yang Voc-nya melebihi Vmax dianggap tidak layak (Voc tanpa bayangan pada 25 C, tanpa koreksi suhu dingin).
Modul besar adalah modul SINTETIS ~415 W (72 sel setara, 3 dioda pelewat, Voc 44,6 V, Isc 12,5 A, Vmp 36,4 V),
diskalakan dari parameter modul 10 W, bukan dari lembar data modul nyata. Batas daya pengendali tidak dimodelkan.
Angka: % daya MLPE ideal. Data: `hasil/sensitivitas_12_24_48V.csv`; skrip: `sensitivitas.py`.

| Modul | Sistem | Topologi layak | Tetap terbaik | Adaptif | Selisih (poin) |
|---|---|---|---|---|---|
| 10 W | 12 V | semua | 4P 98,7 | 98,7 | 0,1 |
| 10 W | 24 V | 4S, 2S2P, TCT | 4S 78,8 / TCT 84,8 | 84,2 / 89,5 | 5,5 / 4,7 |
| 10 W | 48 V | 4S saja | 4S 60,9 / 73,7 | sama | 0 |
| ~415 W | 12 V / 24 V | 2S2P, TCT, 4P | 4P 94,3-94,7 | 96,1-97,7 | 1,6-3,4 |
| ~415 W | 48 V, 150 V | 2S2P, TCT | TCT 81,2 / 88,6 | 82,5 / 89,2 | 1,4 / 0,7 |
| ~415 W | 48 V, 250 V | 4S, 2S2P, TCT | 4S 85,8 / TCT 88,6 | 89,6 / 93,2 | 3,7 / 4,6 |
(angka pertama grid 625, kedua uji acak; model sapuan TCT menutup hampir seluruh selisih: 0,1-2 poin dari batas atas)

Kesimpulan: manfaat memilih topologi muncul bila lebih dari satu topologi sama-sama layak pada jendela pengendali,
dan besarnya bergantung pada pasangan (spesifikasi modul, tegangan sistem, pengendali).

## Bayangan bergerak (daun, tepi bayangan bergerak, campuran), simulasi 20 menit, sistem 24 V (jendela 30-100 V)
Skrip: `dinamis.py`; data: `hasil/dinamis_ringkasan.csv`. 12 skenario per jenis (acak, parameter ditetapkan wajar tetapi belum
dibandingkan dengan data nyata). Asumsi: sapuan 3 s (daya 0 selama sapuan, perkiraan dari firmware), peralihan 0,6 s, pelacak
daya maksimum ideal. Angka: energi rata-rata, % energi MLPE ideal.

| Kebijakan | daun | bergerak | campuran | peralihan/20 mnt (daun) |
|---|---|---|---|---|
| tetap 4S | 78,6 | 89,7 | 77,4 | 0 |
| tetap TCT | 89,6 | 89,2 | 80,9 | 0 |
| berpindah setiap detik (batas teori) | 83,5 | 93,3 | 75,4 | 189 |
| sapuan tiap 30 s | 80,7 | 84,5 | 75,4 | 10 |
| sapuan tiap 10 menit | 89,6 | 90,4 | 81,2 | 1 |
| sapuan hanya bila daya menyimpang >20 % | 89,7 | 91,8 | 83,1 | 0,9 |

Kesimpulan: (1) mengejar bayangan yang bergerak cepat justru merugikan (peralihan berlebihan dan waktu sapuan terbuang);
(2) TCT adalah topologi bawaan yang kuat untuk bayangan daun; (3) sapuan dipicu perubahan daya (bukan jadwal) paling baik
dan tidak pernah lebih buruk dari topologi tetap terbaik; keuntungannya +0 sampai +2,2 poin pada skenario ini.

## Diagnosis penyebab penurunan daya (langkah 1 rencana baru)
Skrip: `buat_data_diagnosis.py`, `latih_diagnosis.py`; data: `data/diagnosis_sim.csv` (9.000 skenario, 6 kelas x 1.500),
`hasil/diagnosis_ringkasan.csv`. Kelas: normal, bayangan sebagian, redup merata, dioda pelewat terbuka (saat terbayangi),
dioda hubung singkat (modul selalu terlewati), hambatan seri naik. Dioda terbuka dimodelkan tanpa tegangan tembus balik.
Akurasi simulasi (uji 25%), fitur bentuk saja (tanpa Voc, Isc, Pmax):

| Sumber fitur | pohon d=6 | reg. logistik | hutan acak |
|---|---|---|---|
| 1 sapuan, TCT | 60,2 | 63,0 | 66,0 |
| 1 sapuan, 4S | 61,5 | 61,8 | 68,8 |
| 4 sapuan (4S, 2S2P, TCT, 4P) | 83,2 | 85,5 | 89,2 |

Recall per kelas, 4 sapuan, hutan acak (reg. logistik): normal 85 (79), bayangan 89 (85), redup merata 94 (92),
dioda terbuka 91 (89), dioda hubung singkat 100 (100), hambatan seri naik 74 (67). Dengan 1 sapuan TCT: dioda terbuka hanya 38-40 %.
Temuan: sapuan lintas topologi (yang memang dilakukan saat pemindaian penuh) membuat diagnosis jauh lebih tajam.

Uji fisik: model dari simulasi memprediksi "bayangan sebagian" untuk SEMUA kurva lab (termasuk kondisi normal V1c dan V5), jadi
tidak berlaku pada data fisik (selisih domain: iradiansi lampu halogen, modul tidak identik). Diagnosis belum tervalidasi.
Perlu data fisik berlabel (suntik gangguan sengaja): normal, opak, tembus cahaya, dioda dilepas, resistor seri ditambah, modul dilepas.
