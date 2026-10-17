# Serah terima untuk Dauzan: Edge AI, firmware, dan dasbor SHADESHIFT

Dibaca oleh Dauzan dan Claude Code miliknya. Tim ShadeShift, Smart-X Hackathon ITB 2026. Demo Day 21-23 Okt 2026 (80% nilai dari demo langsung tanpa bug kritis).
Laporan kemajuan lengkap: `progress.md`. Ketentuan panitia: `DeepTech for Smart-X Hackathon 2026_Bootcamp.pdf`.

## Produk dalam 5 kalimat
Alat untuk 4 panel surya (2 x 2, kelas 10 W). ESP32 menyapu kurva I-V lewat beban MOSFET (MCP4725 + LM358 + IRFP260N), ADS1115 membaca tegangan dan arus,
11 relai memilih susunan 4S / 2S2P / TCT / 4P. Model kecil di ESP32 memilih susunan terbaik dari bentuk kurva saat terbayangi sebagian.
Tujuan: menutup sebagian selisih daya terhadap MLPE (microinverter/optimizer) dengan biaya lebih rendah. PLN (bidang transmisi) tertarik pada deteksi gangguan
dan penunjukan panel yang rusak di PLTS 2 MW, jadi diagnosis dan lokalisasi menjadi nilai tambah.
Lapisan yang diminta panitia: L1 digitalisasi (dasbor), L2 Edge AI (pemilih di ESP32), L3 semikonduktor hemat daya (rancangan saklar MOSFET di `SHADESHIFT_ML/saklar/`, belum dibangun).

## Perangkat keras dan konteks alat
Foto purwarupa: `foto/` (`purwarupa_elektronik.jpg`, `papan_elektronik.jpg`, `susunan_modul_lampu.jpg`). Sambungan kabel lengkap: `rangkaian/daftar_kabel.md`, gambar di `rangkaian/*.png`, panduan rakit `rangkaian/Panduan_Rakit_SHADESHIFT.pdf`.

**Rantai sinyal:**
```
Panel A,B,C,D (+ dioda 1N5822 per panel) -> matriks relai R0..R10 -> titik P/N (bus) -> sekring 4 A -> MOSFET IRFP260N (beban elektronik) -> shunt 0,1 ohm -> GND
ESP32 --I2C(SDA21,SCL22)--> ADS1115 (0x48) dan MCP4725 (0x60 atau 0x62)
MCP4725 -> LM358 (penguat x2) -> resistor 220 ohm -> gate MOSFET     (DAC menentukan arus yang ditarik dari panel = titik kurva I-V)
Tegangan: titik P -> 330 kohm -> V_sense -> 10 kohm -> GND; V_sense -> ADS1115 A0 (GAIN_ONE, +-4,096 V; faktor (330k+10k)/10k = 34)
Arus: tegangan di shunt dibaca diferensial A1-A3 (GAIN_EIGHT, +-0,512 V); I = V_shunt / 0,1
```
- **Array**: 4 panel kelas 10 W (Voc sekitar 22,3 V; Isc 0,59-0,62 A), posisi A kiri-atas, B kiri-bawah, C kanan-atas, D kanan-bawah, di bawah lampu halogen di dalam ruangan. Dioda pelewat eksternal 1N5822 per panel (katoda ke terminal +).
- **Relai**: 11 relai 5 V aktif LOW (`RELAI_AKTIF_LOW = true`) dari tiga modul (8 kanal untuk R1-R4, 4 kanal baru untuk R0 dan R5-R7, 4 kanal lama untuk R8-R10; beberapa kanal modul lama rusak dan tidak dipakai). Rencana PCB memakai tiga modul 4 kanal (M1 = R1-R4, M2 = R0 dan R5-R7, M3 = R8-R10); purwarupa sekarang masih modul campuran. Peta pin ESP32 per relai ada di `PIN_R[]` di `.ino` dan `daftar_kabel.md` bagian F.
- **Fungsi relai**: R0 = pemutus utama (P ke sekring). R1 = A- ke B+, R4 = C- ke D+, R5 = B- ke C+ (menyambung seri). R2 = B- ke N, R3 = P ke C+ (membuat dua string paralel). R6 = B+ ke D+ (tautan silang TCT). R7, R8, R9, R10 = jalur paralel penuh.
- **Topologi (relai yang ditutup)**: 4S = R1,R4,R5; 2S2P = R1-R4; TCT = R1-R4 dan R6; 4P = R2,R3,R7-R10. R0 ditutup terakhir.
- **Urutan pindah topologi (keselamatan, jangan diubah)**: DAC ke 0, buka R0, buka semua relai lain, tutup relai target, tunda 250 ms, cek Voc terhadap batas (`VPANEL`), baru tutup R0. Arus selalu nol saat relai bergerak.
- **Sapuan** (`sapuan()`): sapuan kasar kode DAC 0-4095 langkah 32 untuk mencari rentang MOSFET mulai menghantar sampai hampir hubung singkat; lalu sapuan halus 201 titik (tunda 4 ms, rata-rata 2 bacaan). Keluaran serial: `# MULAI label`, `V,I,P`, titik pertama = Voc dengan I = 0, lalu `# Pmax=...`. Waktu total sapuan belum diukur (simulasi memakai perkiraan 3 s).
- **Catu**: adaptor 12 V (LM358 dan MOSFET), step-down LM2596 diatur 5,0 V untuk relai (jumper JD-VCC dilepas), ESP32 hanya dari USB. GND ESP32 harus satu dengan GND adaptor (titik bintang di kaki bawah shunt).
- **Keselamatan**: 4S bisa sekitar 88 V DC. Selalu `OFF` sebelum menyentuh kabel. Heatsink MOSFET memakai mika isolator (bertegangan Drain bila tanpa mika).
- **Batas alat**: tegangan array sekitar 110-120 V (pembagi dan catu 3,3 V ADS1115), arus sekitar 4 A (sekring), kelas 10 W per modul. Tidak ada sensor suhu (suhu pakai termometer tembak) dan tidak ada sensor cahaya terpasang. GPIO yang masih bebas: 4, 5, 12, 14, 15 (hati-hati strapping pada 5, 12, 15), serta 34, 35, 36, 39 (hanya masukan). Kanal A2 ADS1115 kosong.
- **Data lab** diambil dengan alat ini di bawah lampu halogen (arus per modul hanya puluhan mA, cahaya tidak merata); lihat `SHADESHIFT_ML/data/data_lab/README.md`.

## Alasan keputusan (supaya tidak diusulkan ulang)
- **Regresi logistik, bukan CNN atau model besar**: kecil (73 float = 292 byte), diuji di data lab, dan kandidat lain (kuadratik, MLP, sensitif biaya, CNN 1D) tidak lebih baik sekaligus di simulasi dan lab.
- **Sapuan di 4S**: sapuan TCT lebih baik di simulasi (1,3-1,4 poin) tetapi lebih buruk di lab (4,0%).
- **Keluaran 4S/2S2P/TCT saja**: 4P Voc-nya di bawah jendela pengendali 24 V (30-100 V).
- **Metrik "poin % daya MLPE"** (skenario MLPE > 1 W): sama dengan proposal. Metrik persen terhadap daya terbaik menyesatkan saat daya mendekati nol.
- **Tidak mengejar bayangan cepat**: berpindah tiap detik merugi di simulasi; pemicu perubahan daya lebih dari 20% paling baik.
- **Relai dulu untuk demo**: sudah ada. Saklar semikonduktor (hemat daya) masih rancangan sesuai proposal.
- **Tidak FPGA dan tidak belanja baru**: tim tidak punya keahlian FPGA dan dana habis.

## Tugasmu, urut prioritas (sampai 21 Okt)
1. **Jalankan `SHADESHIFT_ML/edge_ai/pemilih/uji_pemilih/uji_pemilih.ino` di ESP32.** Harus mencetak `LULUS 12/12` dan waktu per keputusan. Belum pernah dijalankan di papan (hanya terkompilasi: 292 KB flash). Catat waktunya untuk laporan teknis.
2. **Firmware**: ubah `sapuan()` di `firmware/shadeshift_firmware/shadeshift_firmware.ino` agar menyimpan titik ke larik (sekarang hanya mencetak). Lalu pasang `pemilih.h` mengikuti `SHADESHIFT_ML/edge_ai/pemilih/README.md`
   (`pemilih_cuplik_ulang` -> `pemilih_fitur` -> `pemilih_putuskan`; 0 = 4S, 1 = 2S2P, 2 = TCT). Tambahkan:
   - anti bolak-balik relai: pindah hanya bila susunan baru jelas lebih baik, dengan jeda minimum;
   - pemicu sapuan: sapu ulang hanya bila daya berubah lebih dari 20% (di simulasi `dinamis.py` ini terbaik dan tidak pernah lebih buruk dari susunan tetap terbaik);
   - aturan stabilitas (belum diuji): bila daya bergoyang dalam beberapa detik terakhir, kunci TCT; bila stabil, jalankan pemilih;
   - (opsional) pembacaan LDR (kanal A2 ADS1115 kosong, atau GPIO34/35) sebagai indikator cahaya relatif. Tidak ada sensor suhu terpasang (dana habis; suhu manual). Jangan menambah belanja.
3. **Ukur untuk laporan teknis** (wajib dari panitia: daya, latensi, akurasi): waktu satu sapuan, waktu peralihan relai (simulasi bayangan bergerak memakai perkiraan 3 s dan 0,6 s, belum terukur), waktu inferensi, konsumsi daya ESP32 plus relai.
4. **Dasbor Streamlit** (`pip install streamlit pandas matplotlib pyserial`; belum terpasang di komputer Nando): 
   - baca serial (115200, perintah di header `.ino`; format CSV sapuan: `# MULAI label`, `# topologi=..., Voc=...`, kolom `V,I,P`, lihat `SHADESHIFT_ML/data/data_lab/*.csv`) atau mode putar ulang dari berkas itu (cadangan demo kalau perangkat atau cahaya bermasalah);
   - tampilkan kurva I-V dan P-V, susunan aktif, keputusan pemilih, daya terukur, dan **daya harapan** dari kembaran digital (`SHADESHIFT_ML/edge_ai/kembaran_lab/cocokkan_lampu.py`, parameter di `parameter_lampu.json`; galat daya sekitar 8% di lab). Selisih besar = peringatan kelainan. Jangan sebut itu diagnosis tervalidasi.
   - logger lama: `firmware/logger_shadeshift.py` (menyimpan SWEEP ke `data_lab/`).
5. **Opsional, bila waktu ada**: lokalisasi modul (A-D mana yang bermasalah) dari 4 sapuan susunan. Belum ada eksperimennya. Bahan: `SHADESHIFT_ML/edge_ai/kembaran_lab/buat_data_acak.py` (kelas diagnosis) dan `sim_core.py`.

## Peta berkas penting (dari folder proyek)
| Perlu | Berkas |
|---|---|
| Firmware ESP32 dan perintah serial | `firmware/shadeshift_firmware/shadeshift_firmware.ino`, `firmware/CARA_PAKAI.md` |
| Pin dan sambungan relai | `rangkaian/daftar_kabel.md` (relai R0-R10; GPIO13,16,17,18,19,23,25,26,27,32,33; I2C SDA21 SCL22) |
| Pemilih (C + Python + uji) | `SHADESHIFT_ML/edge_ai/pemilih/` (`pemilih.h`, `pemilih_bobot.h`, `latih_ekspor.py`, `port_c.py`, `evaluasi.txt`) |
| Fitur kurva I-V | `SHADESHIFT_ML/fitur.py` (14 fitur bentuk; aturan data harus sama dengan versi C) |
| Simulasi inti | `SHADESHIFT_ML/sim_core.py` (jalankan skrip dari folder `SHADESHIFT_ML`) |
| Data lab (halogen) | `SHADESHIFT_ML/data/data_lab/` dan `README.md` di dalamnya (kondisi V1, V1b, V1c, V3, V4, V6; V5 dan V1d jangan dipakai) |
| Simulasi bayangan bergerak | `SHADESHIFT_ML/dinamis.py`, `hasil/dinamis_ringkasan.csv` |
| Diagnosis, kembaran, CNN | `SHADESHIFT_ML/edge_ai/kembaran_lab/`, `edge_ai/LAPORAN_JALUR_B.md`, `uji_model/LAPORAN_UJI_FISIK.md` |
| Rancangan saklar semikonduktor | `SHADESHIFT_ML/saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md` |
| Protokol ukur luar ruangan dan panduan data | `SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md`, `SHADESHIFT_ML/panduan_data/` |

Lingkungan Python: numpy, pandas, scipy, scikit-learn, pvlib, matplotlib, pyserial. PyTorch hanya untuk `cnn_diagnosis.py` (opsional). Di Windows set `PYTHONIOENCODING=utf-8` bila ada karakter non-ASCII.
Arduino: board `esp32 by Espressif`, pustaka Adafruit ADS1X15 dan Adafruit MCP4725.

## Angka yang boleh dipakai (sebut sumbernya) dan yang tidak
- Pemilih (regresi logistik, 14 fitur dari satu sapuan 4S, 73 float = 292 byte): data lab rugi 0,82% vs 2,71% susunan tetap terbaik (2S2P); simulasi rugi 3,0 vs 6,35 poin dari daya MLPE ideal. Akurasi pilihan di simulasi hanya 68,9% (seimbang 47,5%), recall 2S2P 0%: jangan klaim akurasi tinggi.
- Kenaikan daya saat terbayangi dibanding susunan tetap terbaik: sekitar 5-7% di simulasi 10 W / 24 V, sekitar 2% di lab, sekitar 2-3,5% di simulasi 415 W. Tanpa bayangan: 0%.
- Diagnosis penyebab (6 kelas): HANYA simulasi, 78-82%. Gagal di data lab halogen (3-13%). Jangan sebut akurasi diagnosis di data nyata.
- CNN 1D: hanya eksplorasi simulasi (data kembaran 69%, lab 13%), tidak lebih baik dari model sederhana, tidak dipakai di perangkat. Yang dipasang di ESP32 adalah regresi logistik.
- Proposal menulis diagnosis 83-89%; angka benar setelah perbaikan bug Voc adalah 78-82%.
- Alat tidak mengikuti bayangan yang bergerak cepat (MLPE bisa). Data nyata matahari belum ada.

## Aturan kerja
- Berkas data mentah (`data/data_lab/*.csv`) tidak diubah. Baris rusak ditangani skrip.
- Dana tim habis: jangan menyarankan atau melakukan pembelian baru.
- Catat setiap kemajuan teknis ke `progress.md` (entri terbaru di atas, di bagian Log), supaya Nando dan tim melihatnya.
- Sapuan di perangkat: pindah susunan hanya lewat urutan aman firmware (R0 dibuka dulu, arus nol saat relai berpindah). Pada 4S tegangan array bisa sekitar 88 V DC; selalu `OFF` sebelum menyentuh kabel.
