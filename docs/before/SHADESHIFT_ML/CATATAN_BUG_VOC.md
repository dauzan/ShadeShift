# Bug Voc pada sapuan simulasi (ditemukan dan diperbaiki 8 Okt 2026)

**Masalah.** `fitur.sapuan()` menghitung Voc dengan `np.interp(0.0, curve.I[::-1], curve.V[::-1])`. `np.interp` mensyaratkan
sumbu-x naik, tetapi `I[::-1]` menurun, sehingga hasilnya selalu tegangan di ujung kisi arus (I = -0,3 x Isc maksimum), bukan di I = 0.
Akibatnya setiap kurva simulasi disapu melewati Voc sampai ke arus negatif (pada 100 W/m2 sampai -3 x Isc), dan fitur bentuk
(Voc, FF, I@xVoc) dihitung dari bagian kurva yang tidak pernah terukur di alat nyata.

**Perbaikan.** `voc = float(curve.V_of_I(0.0))`. Semua dataset simulasi dibuat ulang (seed sama); data lama di `data/_lama_bug_voc/`.

**Dampak**
| Hasil | Sebelum | Sesudah | Keterangan |
|---|---|---|---|
| Daya tiap susunan, MLPE, pemulihan daya (24 V: +4,7-5,5 poin) | - | identik | Tidak terdampak (dihitung dari kurva, bukan dari sapuan) |
| Analisis saklar MOSFET, data fisik | - | - | Tidak terdampak |
| Diagnosis 6 kelas, 4 sapuan, fitur bentuk (pohon d=6 / reg. log. / hutan acak) | 83,2 / 85,5 / 89,2% | **78,5 / 80,4 / 82,1%** | Angka lama terlalu tinggi; proposal Smart-X (terkirim) memakai 83-89% |
| Model satu sapuan TCT, selisih dari pilihan optimal (uji acak) | 0,89-0,90 poin | 0,80-1,03 poin | Klaim "sekitar 1 poin" tetap benar |
| Pemilih ESP32 (reg. log., sapuan 4S), simulasi uji-tahan | akurasi 73,1%, rugi 3,39% | **akurasi 68,9%, rugi 5,34%** | Pembanding tetap 4S: 6,76% |
| Pemilih ESP32 pada data fisik | rugi 0,82% | rugi 0,82% | Keputusan sama |
| Diagnosis model simulasi pada data lab | gagal | **tetap gagal** | Bug bukan penyebab utama; selisih bentuk kurva lab (FF 0,46-0,54 vs simulasi sekitar 0,69) |

**Tindak lanjut**
- Angka diagnosis yang dipakai ke depan: **78-82% (simulasi)**. Bila panitia meminta revisi proposal, perbarui.
- Presentasi Demo Day dan dokumen baru memakai angka sesudah perbaikan.
