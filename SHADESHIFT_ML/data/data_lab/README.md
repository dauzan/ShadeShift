# Data I-V fisik (lampu halogen)

Format nama: `<kondisi>_<susunan>_u<ulangan>.csv`, susunan 4S / 2S2P / TCT / 4P, 3 ulangan (urutan susunan diacak tiap putaran).
Setiap berkas: header `#` (topologi, Voc, rentang DAC, Pmax) lalu kolom `V,I,P`, sekitar 201 titik. Berkas mentah tidak boleh diubah.

Alat: empat modul 2 x 2 di bawah lampu halogen di dalam ruangan, satu dioda bypass eksternal (1N5822) per modul, pengalih relai.
Tanpa sensor iradiansi dan suhu; tingkat bayangan diperkirakan dari Isc. Arus per modul hanya puluhan mA (jauh di bawah matahari).

| Kondisi | Keterangan | Status |
|---|---|---|
| `V1` | Tanpa bayangan, lampu posisi jauh (iradiansi lebih rendah, daya sekitar 40-50% di bawah V1c) | Dipakai sebagai "normal, iradiansi rendah" |
| `V1b` | Pengulangan V1 (lampu posisi jauh yang sama); hasil praktis identik dengan V1 | Dipakai; satu pola dengan V1 |
| `V1c` | Tanpa bayangan, **lampu didekatkan**; acuan naskah BREYI. Semua kondisi bayangan (V3, V4, V6) diambil pada posisi lampu ini | Dipakai |
| `V3_opak` | Satu sel modul A ditutup benda opak | Dipakai |
| `V3_paranet65`, `V3_paranet75` | Seluruh modul A ditutup paranet 65% / 75% | Dipakai |
| `V4_paranet65`, `V4_paranet75` | Modul A + B (berdekatan, satu string) ditutup paranet | Dipakai |
| `V6_paranet65`, `V6_paranet75` | Modul A + D (diagonal) ditutup paranet | Dipakai |
| `_V5_anomali_dioda/` | Modul A + C ditutup paranet; dioda bypass modul C tampak tidak berfungsi, lalu satu relai rusak | **Anomali**: tidak dilaporkan; hanya untuk eksplorasi diagnosis |
| `_V1d_gagal_R1/` | Percobaan tanpa bayangan yang gagal karena relai R1 | **Gagal**: jangan dipakai |

Catatan data:
- Paranet 65% dan 75% memberi bayangan efektif hampir sama (sekitar 0,7 dari Isc); untuk pembagian latih/uji, perlakukan sebagai satu pola.
- `V3_paranet75_TCT_u2.csv`: baris data pertama rusak (4 kolom); skrip membuang baris dengan jumlah kolom bukan 3.
- `V3_paranet75_TCT_u1/u3`: sapuan mulai dari sekitar 10% Voc, bukan dari 0.
- Kondisi V2 dan V7 (bayangan opak dua modul) belum diukur.
