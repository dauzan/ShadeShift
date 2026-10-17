# Desain matriks saklar semikonduktor SHADESHIFT (lapisan "semikonduktor hemat daya")

Status: **desain dan analisis**, belum dibangun. Tujuan: mengganti 11 relai elektromekanis (R0-R10) dengan saklar semikonduktor
agar daya penahan hilang dan keuntungan pemilihan topologi tidak habis oleh beban kendali.

Berkas: `1_matriks_saklar_semikonduktor.png` (peta saklar), `2_sel_saklar_semikonduktor.png` (satu sel saklar),
`3_perbandingan_relai_semikonduktor.png` (hasil), tabel di `*.csv`, skrip `analisis_saklar.py` dan `gambar_saklar.py`.

## 1. Arsitektur
- Peta sambungan sama dengan matriks relai sekarang (firmware dan `rangkaian/daftar_kabel.md`): 10 saklar S1-S10 antar simpul
  panel A-D, ditambah S0 (pemutus utama ke sekring dan penjejak I-V). Hanya jenis saklarnya yang berganti.
- Topologi (saklar tertutup): 4S = S1, S4, S5; 2S2P = S1-S4; TCT = S1-S4, S6; 4P = S2, S3, S7-S10 (sama dengan masker relai di firmware).
- Satu sel saklar = dua MOSFET-N punggung-ke-punggung (sumber bersama) agar memblokir di kedua arah, pengemudi gerbang
  fotovoltaik terisolasi (contoh: VOM1271), LED pengemudi digerakkan dari ESP32, dan peredam lonjakan (TVS) paralel di kedua ujung.
- Urutan pindah topologi tetap seperti firmware sekarang: S0 dibuka, pindah saklar, tunggu, S0 ditutup. Dengan begitu tidak ada
  arus saat saklar berganti, dan tidak ada kondisi dua topologi tertutup bersamaan (tanpa risiko hubung singkat antarsimpul).

## 2. Spesifikasi yang dihitung (modul sama, Voc x 1,12 pada suhu dingin, Rds(on) x 1,5 pada suhu kerja: kedua faktor ASUMSI)
| Array | Tegangan blokir maks | Arus saklar maks | Arus S0 (4P) | Kelas MOSFET |
|---|---|---|---|---|
| 4 x 10 W (Voc 22,3 V) | 75 V | 0,62 A | 2,5 A | 100 V cukup tipis (75 %), 150 V lebih aman |
| 4 x ~415 W (sintetis, Voc 44,6 V) | 150 V | 12,5 A | 50 A | kelas 200 V dengan Rds(on) rendah atau MOSFET paralel |
Tegangan blokir terbesar ada di S7 dan S10 (3 x Voc modul pada konfigurasi 4S).

## 3. Hasil analisis (array 4 x 10 W, sistem 24 V)
**Daya kendali (menahan saklar tetap tertutup):** relai 1,43-2,50 W (4S-4P) dibanding 0,13-0,23 W untuk saklar semikonduktor,
sekitar 11 kali lebih kecil. Angka relai memakai asumsi 0,357 W per kumparan (5 V x 71,4 mA, kelas relai SRD-05VDC), dan
4 kumparan menyala pada 4S memberi 1,43 W, dekat dengan angka rugi relai biasa + MCU 1,42 W di naskah BREYI
(angka naskah mencakup MCU dan asumsi lain, jadi kecocokannya hanya kasar).
Angka semikonduktor memakai LED 10 mA dari rel 3,3 V (pengemudi VOM1271 diuji pada IF = 10 mA menurut lembar datanya).

**Rugi hantaran:** I^2 x (2 x Rds(on) x 1,5) pada saklar yang dilalui arus. Untuk array 10 W: 0,05-0,2 % (Rds 4,8-11,8 mOhm) hingga
0,4-0,8 % (44 mOhm). Pada array ~415 W, rugi 0,45-0,9 % memerlukan MOSFET sekitar 5 mOhm per perangkat di jalur arus besar.

**Keuntungan bersih memilih topologi (simulasi 10 W, G >= 700 W/m^2, hanya topologi layak 4S, 2S2P, TCT):**
keuntungan kotor +1,06 W dibanding topologi tetap terbaik (TCT).
- relai: **-0,73 W** (rugi bersih),
- MOSFET 100 V (kelas IRF540N, 44 mOhm): **+0,62 W**,
- MOSFET 150 V (kelas IRFB4115, <= 11,8 mOhm): **+0,82 W**.
Jadi relai menghapus keuntungan, sedangkan saklar semikonduktor mempertahankan sekitar 60-80 % keuntungan kotornya.

## 4. Nilai yang diverifikasi dari lembar data dan nilai yang masih asumsi
Dari lembar data (hasil pencarian): IRF540N 100 V, 44 mOhm, 33 A; IRFB4115 150 V, Rds(on) maks sekitar 11-11,8 mOhm; VOM1271:
Voc 8,4 V dan Isc 15 uA pada IF = 10 mA, isolasi 4500 V rms, ada rangkaian pematian internal.
Asumsi yang harus diukur atau dicek: daya kumparan relai (ukur arus catu 5 V), faktor suhu Rds(on) dan Voc dingin, waktu nyala saklar,
batas arus GPIO ESP32.

## 5. Catatan teknis dan risiko
- **Waktu nyala:** pengemudi fotovoltaik mengisi gerbang dengan arus mikroampere. Perkiraan hitung: sekitar 2-10 ms per saklar
  (muatan gerbang puluhan sampai ratusan nC dibagi 15 uA), belum diukur. Cukup untuk pindah topologi (bukan penyaklaran cepat),
  tetapi urutan firmware perlu jeda yang sesuai.
- **Arus LED:** 4-7 LED x 10 mA melebihi anjuran arus GPIO. Gerakkan LED lewat penyangga atau IC pembenam arus (mis. ULN2803).
- **Mati saat ESP32 restart:** beri resistor pembuang muatan gerbang agar saklar mati (aman) saat sinyal hilang.
- **Dioda pelewat modul:** tetap dipakai; dioda badan MOSFET punggung-ke-punggung tidak menghantar saat saklar mati.
- **Lonjakan induktif:** kabel panjang dan beban induktif bisa menimbulkan lonjakan, makanya TVS dipasang; nilainya mengikuti tegangan blokir.
- **Skala besar:** jalur S0 dan saklar arus besar memerlukan MOSFET paralel atau perangkat berarus tinggi; ini desain konsep, belum dihitung termal.

## 6. Langkah berikutnya (bila ingin dibangun)
1. Bangun satu sel saklar di papan uji dan ukur: waktu nyala/mati, Rds(on) terukur, arus LED, kenaikan suhu pada 0,6 A.
2. Ukur daya kumparan relai sebenarnya (arus catu 5 V per topologi) dan perbarui angka relai.
3. Bila sel saklar lolos, ganti satu relai di purwarupa dan bandingkan hasil sapuan I-V.
