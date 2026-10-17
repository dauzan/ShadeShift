# Dasbor SHADESHIFT (L1 digitalisasi)

Dasbor Streamlit untuk Demo Day: kurva I-V dan P-V, susunan aktif, keputusan pemilih, daya terukur, dan **daya harapan** dari kembaran digital.
Tidak ada model baru: pemilih memakai bobot `pemilih_bobot.h` (lewat `port_c.py`), kembaran memakai `cocokkan_lampu.py` + `parameter_lampu.json`.

## Menjalankan
Dari folder proyek (bukan dari `dasbor/`), dengan venv di drive D:
```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run dasbor/app.py
```
Lalu buka http://localhost:8501. Pengaturan offline (tanpa telemetri, tanpa tombol Deploy) ada di `.streamlit/config.toml` di folder proyek,
jadi jalankan dari folder proyek. Versi paket dikunci di `requirements.txt` (kode ini butuh streamlit 1.51 atau lebih baru).
Di Windows set `PYTHONIOENCODING=utf-8` bila perlu. Tutup Serial Monitor Arduino dan `logger_shadeshift.py` dulu (port hanya bisa dipakai satu program).
Uji tanpa alat: `.venv\Scripts\python dasbor\uji_dasbor.py` (harus mencetak `SEMUA LULUS`), atau semua uji: `.venv\Scripts\python -m pytest`.

## Mode
**Langsung (ESP32 / tiruan)**
- Port COM = ESP32 dengan firmware v2. **TIRUAN** = ESP32 tiruan yang memutar ulang kurva `data_lab` dan menjawab perintah 4S/2S2P/TCT/4P, SWEEP, OFF, VOC, STATUS.
  Kondisi tiruan bisa diganti saat berjalan (meniru bayangan berubah). Ini cadangan demo bila alat atau cahaya bermasalah; layar memberi label TIRUAN.
- Tombol susunan dan OFF mengirim perintah firmware apa adanya (urutan aman tetap di firmware). Perintah bebas, LANJUT, BATAL untuk SIKLUS.
- **Pilih susunan otomatis (sekali)**: 4S, SWEEP, pemilih, pindah ke pilihan, SWEEP. Pemilih dihitung **di laptop** dengan kode dan bobot yang sama
  dengan `pemilih.h` (38/38 keputusan sama). Setelah firmware memasang `pemilih.h`, cetak baris `# pemilih=TCT` di dalam blok sapuan
  dan dasbor akan menampilkan keputusan dari ESP32.
- **Mode otomatis**: uji aturan dari `UNTUK_DAUZAN.md` di laptop: sapu ulang susunan aktif tiap N detik, jalankan pemilih lagi hanya bila Pmax
  berubah > 20% dan sudah lewat jeda minimum (anti bolak-balik). Belum ada di firmware. Aturan stabilitas (kunci TCT) belum dibuat.
- Setiap sapuan disimpan ke `SHADESHIFT_ML/data/data_dasbor/` (format sama dengan logger). `data_lab/` tidak diubah. Mode TIRUAN tidak menyimpan.

**Putar ulang berkas**: pilih kondisi dan ulangan dari `data_lab` atau `data_dasbor`. Menampilkan keempat kurva, Pmax terukur vs harapan,
keputusan pemilih dari sapuan 4S, dan rugi terhadap susunan terbaik. Ringkasan semua set lab mengulang angka `LAPORAN_UJI_FISIK.md`
(30 set: pemilih 0,82%, tetap 2S2P 2,71%, TCT 4,30%, 4S 12,0%).

## Daya harapan (kembaran digital)
- Dicocokkan pada V1c (lampu halogen didekatkan). Galat daya sekitar 8% pada 7 kondisi lab (`LAPORAN_JALUR_B.md`). Ini simulasi, bukan diagnosis.
- **Skala cahaya**: 1,0 = posisi lampu V1c. Di tempat demo, sapu satu kali tanpa bayangan lalu tekan **Kalibrasi skala cahaya dari sapuan terakhir**.
- **Bayangan yang diasumsikan**: bawaan "Tanpa bayangan", jadi bayangan atau gangguan muncul sebagai selisih negatif. Bila selisih melewati ambang
  (bawaan 15%, di atas galat kembaran 8%), muncul peringatan "indikasi kelainan, bukan diagnosis tervalidasi".
  Preset V3/V4/V6 memakai bayangan nominal yang sama dengan `cocokkan_lampu.py` (transmisi paranet dihitung dari rasio Isc 4P, sekitar 0,14).

## Berkas
| Berkas | Isi |
|---|---|
| `app.py` | Tampilan Streamlit |
| `inti.py` | Baca sapuan, Pmax (aturan data sama dengan `uji_data_fisik.py`), pemilih, kembaran, kalibrasi skala |
| `koneksi.py` | Serial ESP32 (utas pembaca, simpan CSV), ESP32 tiruan, alur pilih otomatis dan mode otomatis |
| `uji_dasbor.py` | Uji tanpa alat (pemilih vs C, angka lab, alur tiruan) |
| `gambar_*.png` | Tangkapan layar mode langsung (TIRUAN) dan putar ulang |

## Belum diuji
- Belum pernah disambungkan ke ESP32 sungguhan (hanya TIRUAN). Uji pertama: Sambungkan ke COM, `STATUS`, `4S`, `SWEEP`.
- Waktu tunggu: pindah susunan 10 s, sapuan 60 s. Waktu sapuan nyata belum diukur.
