# Progress SHADESHIFT: DeepTech for Smart-X Hackathon 2026

Tim: Nando (ketua), Bu Deasy (dosen), Dauzan, Mujibur. Demo Day 21-23 Okt 2026, ITB Ganesha (Gedung PAU Auditorium Lt. 8).
Berkas ini memuat seluruh kemajuan (teknis, dokumen, keputusan, rencana) dan diperbarui setiap ada perubahan. Entri terbaru di bagian "Log".
Semua angka model berlabel sumbernya (simulasi atau lab). Folder kerja: `SHADESHIFT_ML/`.

## 1. Status ringkas (16 Okt 2026)
| Bagian | Status |
|---|---|
| Proposal, dokumen pendaftaran, presentasi | Terkirim. Proposal lolos ke Demo Day. |
| Penjejak I-V + 4 susunan (relai) | Berfungsi di lab (lampu halogen). |
| Pemilih susunan (Edge AI, ESP32) | Model siap, terkompilasi, BELUM dijalankan di papan. |
| Diagnosis penyebab | Hanya simulasi (78-82%). Tidak tervalidasi di data lab. |
| Dasbor dan logger | Logger Python ada. Dasbor Streamlit ada (`dasbor/`), diuji dengan ESP32 tiruan, BELUM dengan alat. |
| Saklar semikonduktor | Rancangan dan hitungan, belum dibangun. |
| Data luar ruangan (matahari) | BELUM ada. Protokol sudah ada, koreksi belum diterapkan. |
| PCB | Desain KiCad ada; tidak sempat dipesan sebelum 21 Okt. |

## 2. Konsep dan posisi terhadap MLPE
- MLPE (module-level power electronics) = microinverter atau power optimizer yang dipasang di SETIAP panel. Tiap panel punya pelacak titik daya maksimum (MPPT) sendiri, jadi panel yang terbayangi tidak menarik turun panel lain. Pada susunan seri biasa, arus seluruh string dibatasi panel terlemah.
- Metrik kita: "% daya MLPE ideal" = daya yang ditangkap sebuah susunan dibanding jumlah daya maksimum tiap modul sendiri-sendiri (batas atas, efisiensi konversi dianggap 100%). MLPE nyata sedikit di bawah itu (kira-kira 96-99%, perlu dicek di lembar data) dan menambah biaya di setiap modul.
- SHADESHIFT: satu unit per 4 panel, mengukur kurva I-V, memilih susunan 4S, 2S2P, TCT, atau 4P lewat saklar, tanpa elektronika daya di tiap modul. Ia MENUTUP SEBAGIAN selisih terhadap MLPE, tidak menyamainya.
- Berapa persen (simulasi, rata-rata skenario terbayangi acak, sistem 24 V, 4 x 10 W, hasil dari `RINGKASAN_LANGKAH1.md`):
  - Susunan tetap terbaik menangkap 78,8% (grid 625) dan 84,8% (uji acak) dari daya MLPE ideal.
  - Dengan pemilihan adaptif: 84,2% dan 89,5%. Pemulihan 5,5 dan 4,7 poin.
  - Artinya sekitar seperempat sampai sepertiga selisih terhadap MLPE ditutup (5,4 dari 21,2 poin dan 4,7 dari 15,2 poin). Sisanya (sekitar 10-16% dari daya MLPE ideal) tidak terpulihkan.
  - Modul sintetis 415 W (simulasi): adaptif 96,1-97,7% (sistem 12/24 V) dan 82,5-93,2% (48 V, 150-250 V); selisih terhadap tetap terbaik 0,7-4,6 poin.
- Manfaat hanya muncul saat ada bayangan sebagian dan lebih dari satu susunan layak pada jendela pengendali. Tanpa bayangan tidak ada keuntungan. Pada 10 W dan 48 V hanya 4S layak, selisih 0.
- Bayangan bergerak (pohon, daun), simulasi 20 menit, sapuan 3 s tanpa daya, peralihan relai 0,6 s (perkiraan dari firmware, BELUM diukur), skenario sintetis belum dibandingkan data nyata (`dinamis.py`, `hasil/dinamis_ringkasan.csv`), % energi MLPE ideal:
  - tetap 4S 78,6 (daun) / 89,7 (bergerak) / 77,4 (campuran); tetap TCT 89,6 / 89,2 / 80,9.
  - berpindah tiap detik (batas teori, mengejar bayangan): 83,5 / 93,3 / 75,4 dengan 189 peralihan per 20 menit untuk daun, malah merugi.
  - sapuan tiap 30 s: 80,7 / 84,5 / 75,4. Sapuan tiap 10 menit: 89,6 / 90,4 / 81,2.
  - sapuan hanya bila daya menyimpang >20%: 89,7 / 91,8 / 83,1, tidak pernah lebih buruk dari susunan tetap terbaik (+0 sampai +2,2 poin).
  - MLPE mengikuti bayangan yang bergerak secara kontinu (dalam milidetik). SHADESHIFT tidak bisa: untuk bayangan daun ia bertahan di susunan yang kuat (TCT) dan hanya menyapu ulang saat daya berubah besar. Pada bayangan yang bergeser pelan (menit) ia mengikuti. Untuk bayangan cepat, MLPE lebih unggul.

## 3. Perangkat keras (purwarupa lab)
- Array: 4 modul kelas 10 W (Voc 22,3 V; Isc 0,60/0,59/0,62/0,62 A), satu dioda pelewat eksternal 1N5822 per modul, tersusun 2 x 2 di bawah lampu halogen.
- ESP32 DevKit V1 30 pin. ADS1115: A0 = tegangan array lewat pembagi 330 k / 10 k (batas efektif sekitar 110-120 V karena catu 3,3 V); A1-A3 diferensial = arus lewat shunt 0,1 Ω (batas 5,12 A). MCP4725 -> LM358 (penguat x2) -> gerbang MOSFET IRFP260N sebagai beban elektronik untuk sapuan.
- 11 relai (R0-R10) dari modul relai 5 V beroptokopler (rencana PCB: 3 modul 4 kanal), sekring 4 A. R0 = pemutus utama; firmware memastikan arus nol saat relai berpindah.
- Topologi (relai tertutup): 4S = R1,R4,R5; 2S2P = R1-R4; TCT = R1-R4,R6; 4P = R2,R3,R7-R10.
- Firmware v2 (`firmware/shadeshift_firmware/`): perintah SWEEP (201 titik), SIKLUS (4 topologi acak per putaran), 4S/2S2P/TCT/4P, CEKVOC, VPANEL, KAL, PANTAU, OFF. Logger Python `firmware/logger_shadeshift.py`. Belum ada kode suhu atau LDR (suhu dicatat manual dengan termometer tembak).
- Batas alat sekarang (hitungan dari komponen, belum diuji): Voc modul <= 24 V, Isc <= 0,9 A, total sekitar 40-60 W (sekring 4 A, MOSFET dan heatsink kecil). Panel rumah 400 W lebih memerlukan penggantian pembagi, shunt, sekring, beban sapuan, dan saklar semikonduktor. Untuk skala rumah: bagi array menjadi blok 2 x 2, satu unit per blok. Matriks lain butuh simulasi dan pelatihan ulang.
- Sensor (dana terbatas): LDR yang sudah ada, 1 buah, hanya indikator cahaya relatif (bukan W/m2; sebidang dengan panel, jangan ikut ditutup). Suhu pakai termometer tembak. DS18B20 maksimal 1 bila perlu. Tidak ada pembelian lain.
- Wadah 3D (`wadah_3d/`, `analisis/`), rangkaian dan panduan rakit (`rangkaian/`), desain PCB KiCad (`SHADESHIFT_ML/pcb/`).

## 4. Model pemilih susunan (Edge AI) `edge_ai/pemilih/`
- Regresi logistik multinomial (L2, C=1), StandardScaler, 14 fitur bentuk dari satu sapuan 4S (Vmp/Voc, Imp/Isc, FF, jumlah puncak, P2/Pmax, I pada 0,1-0,9 Voc/Isc). Keluaran 4S/2S2P/TCT (4P tidak layak di jendela 24 V). 73 float = 292 byte. Kode C float32 tanpa malloc (`pemilih.h`, `pemilih_bobot.h`); tiruan Python `port_c.py` cocok dengan model asli (selisih fitur < 1,5e-6). Terkompilasi untuk ESP32: 292 KB flash, 25 KB RAM. Sketsa uji `uji_pemilih/` (harus mencetak LULUS 12/12) BELUM dijalankan di papan.
- Dilatih pada simulasi `sim_acak` 12.000 skenario (uji-tahan 25%). Metrik poin % daya MLPE (skenario MLPE > 1 W), simulasi: rugi 3,00 poin vs tetap 4S 6,37 / tetap TCT 6,35 (memangkas sekitar setengah). Akurasi 68,9%, akurasi seimbang 47,5%, recall 2S2P 0% (model tidak pernah memilih 2S2P; 2S2P terbaik hanya 4,4% skenario). Jangan klaim akurasi tinggi.
- Data lab (30 set, 6 pola, tidak dipakai melatih): rugi rata-rata 0,82% (maks 5,0%) vs tetap 2S2P 2,71%. Salah pada bayangan diagonal V6. Hasil lab terlihat bagus karena polanya sederhana.
- Kandidat perbaikan (sensitif biaya, regresi rasio, MLP) tidak lebih baik di simulasi dan lab sekaligus, jadi regresi logistik tetap. Sapuan TCT lebih baik di simulasi tetapi lebih buruk di lab, jadi tetap sapuan 4S.
- Pembersihan data: V <= 0 dibuang, I dijepit >= 0, titik V kembar dirata-ratakan.
- README untuk Dauzan: `edge_ai/pemilih/README.md`. Pekerjaan firmware: ubah `sapuan()` agar menyimpan titik ke larik, pasang `pemilih.h`, tambah ambang anti bolak-balik relai.

## 5. Diagnosis penyebab (6 kelas) dan kembaran digital
- Kelas: normal, bayangan sebagian, redup merata, dioda pelewat terbuka, dioda hubung singkat, hambatan seri naik. Simulasi (9.000 skenario), 4 sapuan lintas topologi: 83,2 / 85,5 / 89,2% (pohon / logistik / hutan) SEBELUM perbaikan bug Voc, 78-82% SESUDAH. Dengan 1 sapuan hanya 60-69%. Hanya boleh disebut "simulasi".
- Gagal di data lab halogen: model simulasi menebak "bayangan" untuk semua kurva (3-13% benar). Kembaran + domain randomization: 10-30%. CNN 1D 6.230 parameter (PyTorch): data kembaran 69%, lab 13%. Penyebab utama: bentuk kurva lab (FF 0,46-0,54) beda dari simulasi (sekitar 0,69). Angka 87-90% dari uji lab lama adalah kebocoran data dan tidak boleh dipakai.
- Kembaran digital lampu lab (`edge_ai/kembaran_lab/`): model cahaya per sel, 7 parameter dicocokkan pada V1c; ramalan daya 7 kondisi bayangan galat 8,0% (simulator lama 18,6%). Berguna untuk "daya harapan" di dasbor, bukan untuk diagnosis.
- Laporan lengkap: `edge_ai/LAPORAN_JALUR_B.md`, `uji_model/LAPORAN_UJI_FISIK.md`.

## 6. Data fisik (lampu halogen, `data/data_lab/README.md`)
- Kondisi: V1 (tanpa bayangan, lampu jauh), V1b (ulangan V1), V1c (tanpa bayangan, lampu didekatkan; semua kondisi bayangan diambil pada posisi ini), V3 opak (satu sel modul A), V3/V4/V6 paranet 65% dan 75% (modul A; A+B; A+D). V5 anomali dioda dan V1d gagal dipisah ke subfolder dan tidak dipakai. V2 dan V7 belum diukur.
- Keterbatasan: tanpa sensor iradiansi dan suhu, cahaya halogen tidak merata, arus per modul hanya puluhan mA.
- Bug Voc (8 Okt): `fitur.sapuan()` memakai np.interp dengan I menurun sehingga sapuan melewati Voc. Diperbaiki, semua dataset dibuat ulang (`CATATAN_BUG_VOC.md`; data lama di `data/_lama_bug_voc/`). Angka daya aman; diagnosis simulasi turun dari 83-89% ke 78-82%.

## 7. Saklar semikonduktor (rancangan, `saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md`)
- 10 saklar S1-S10 plus S0, tiap sel = 2 MOSFET-N punggung-ke-punggung + pengemudi VOM1271 + TVS. Peta sama dengan relai.
- Daya penahan: relai 1,43-2,50 W vs semikonduktor 0,13-0,23 W (sekitar 11 kali lebih kecil). Keuntungan bersih memilih susunan (10 W, G >= 700 W/m2): relai -0,73 W, MOSFET 100 V +0,62 W, MOSFET 150 V +0,82 W (hitungan dengan asumsi, belum diukur).
- Skala 4 x 415 W: blokir 150 V, arus saklar 12,5 A, arus S0 50 A (MOSFET kelas 200 V atau paralel).
- Langkah bila dibangun: satu sel di papan uji, ukur waktu nyala, Rds(on), suhu, arus LED.

## 8. Protokol luar ruangan dan koreksi
- Protokol: `PROTOKOL_LUAR_RUANGAN.md` (belum diubah). Halaman panduan interaktif: https://claude.ai/artifact/PkAVyvYqv5oMzu2E9Xwqk4 (`panduan_data/`).
- Koreksi (dasar simulasi dengan parameter model, R_s modul 2,46 / 2,90 / 0,75 / 0,75 Ω):
  - E3 dan E4 (1 Ω dan 2,2 Ω) terlalu kecil: daya turun hanya 0,8% dan 1,7%. Usul 5 Ω (5 W, turun 3,8%) dan 10 Ω (10 W, turun 7,5%); uji satu siklus dulu. Resistor itu membutuhkan sedikit biaya.
  - E1 (dioda terbuka tanpa bayangan) hampir tak terlihat (daya sama, Isc turun sekitar 2%): jadikan kontrol; dioda terbuka diuji lewat E2.
  - E5 (modul dipintas) = kelas dioda hubung singkat; beri label dioda_pintas.
- Opak, redup 75%, dan dioda hubung singkat memberi daya maksimum hampir sama (sekitar 74%); pembeda hanya Voc dan lutut kurva (opak vs hubung singkat beda sekitar 4 V).
- Sumber data eksternal yang ditemukan (belum diunduh, lisensi belum dicek): TECNALIA (Zenodo 2026, kurva tiap 5 menit dengan iradiansi dan suhu, kasus seri naik, modul tunggal), mini-panel Medellin (Mendeley 2025, bayangan parsial luar ruangan), cadangan: Mendeley xjs42j8dtf, z93gzbptf7, yy288mjcn2. Tidak ada sumber eksternal untuk susunan 4 modul, dioda terbuka, dan dioda hubung singkat; ketiganya harus dari ukuran sendiri.
- Rencana satu sesi matahari sebelum Demo Day: normal, opak, paranet, E2, E5 (dan resistor seri bila ada), catat suhu dan cahaya relatif. Target penuh proposal ±360 kurva ada di bulan 1-2 pascakompetisi.

## 9. Dokumen terkirim (`SHADESHIFT_ML/berkas_kirim/`)
- ShadeShift_Proposal.pdf/.docx (docx hasil edit user, memuat NIK; jangan ditimpa), ShadeShift_Dokumen Pendaftaran.pdf (CV, pakta bertanda tangan, dokumentasi), ShadeShift_Peningkatan Renewable Energy.pdf/.pptx (5 slide).
- Target kinerja di proposal: pulihkan >= 4 poin daya terhadap susunan tetap terbaik, akurasi diagnosis >= 85% di data luar ruangan, daya kendali <= 0,25 W, keputusan dalam milidetik. TKT awal 3-4, target 5-6. Mitra belum formal; PLN dan Len Industri akan didekati di klinik.
- Koreksi angka untuk pitch: proposal menulis diagnosis simulasi 83-89%; yang benar 78-82%. Pakai angka koreksi dan sebut "simulasi".

## 10. Ketentuan resmi Smart-X (aisx.itb.ac.id/deeptech, PDF bootcamp)
- Demo Day 21 Okt eksplor, 22 Okt bangun dan integrasi akhir, 23 Okt pitch (18 tim, sekitar 15 menit per tim). Nilai akhir = 20% proposal + 80% demo; nilai demo minimal 2,80, kurang dari itu tidak direkomendasikan mendapat dana.
- Wajib: purwarupa berfungsi tanpa bug kritis atau workaround, laporan teknis (daya, latensi, akurasi terhadap target mitra), pitch deck (teknis, komersialisasi, efisiensi biaya operasi, kelayakan produksi massal).
- Tiga lapis: L1 digitalisasi, L2 Edge AI, L3 semikonduktor hemat daya atau IP core (website menyebut target, PDF menyebut wajib) dengan rencana TKDN. TKT program 4-7.
- Panitia menyediakan bahan prototyping dengan jatah per tim dan akomodasi terbatas.

## 11. Keputusan dan aturan kerja
- Dana tim habis: pakai alat yang sudah ada, tidak ada pembelian baru kecuali sangat perlu.
- FPGA/Verilog tidak dipakai (tim tidak punya keahliannya). L3 di demo = rancangan saklar semikonduktor dan hitungan, sesuai proposal. IP mandiri dan TKDN ditulis sebagai peta jalan.
- Unduhan dan instalasi hanya di drive D. Tidak mengisi atau mengirim formulir atas nama user. Data pribadi (NIK) tidak dikirim ke saya.
- TKT yang aman diklaim: 4. TKT 5 hanya bila sesi matahari selesai dan alur stabil. Jangan klaim 6.

## 12. Yang belum dikerjakan (prioritas sampai 21 Okt)
1. Dauzan: jalankan `uji_pemilih` di ESP32, ubah `sapuan()`, pasang `pemilih.h`, anti bolak-balik relai.
2. Alur ujung ke ujung stabil: sapuan, pemilih, relai pindah, daya terukur, dasbor.
3. Logger dan dasbor Streamlit (daya terukur vs daya harapan dari kembaran).
4. Satu sesi ukur di matahari dengan protokol terkoreksi.
5. Laporan teknis: ukur daya ESP32 plus relai dan latensi pemilih di papan; ukur waktu sapuan dan peralihan relai (dipakai simulasi bayangan bergerak).
6. Skenario demo dan cadangan: video rekaman, putar ulang kurva, lampu halogen dibawa (demo kemungkinan di dalam ruangan), relai dan kabel cadangan.
7. Bagian bisnis pitch deck (penanggung jawab belum ditentukan; angka pasar harus dari sumber atau mitra).
8. Latihan demo minimal 3 kali dan jawaban untuk juri.

## 13. Klinik dengan industri (16 Okt 19.00; sesi kedua 17 Okt 11.00 untuk tim tertentu)
Klinik adalah dengan pemilik masalah dari industri (proposal menyebut PLN dan Len Industri), bukan panitia. Proposal sudah di-ACC. Tunjuk satu pencatat; jawaban dipakai sebagai bukti kebutuhan pengguna.
1. PLTS seperti apa yang mereka urus: skala (kWp), jenis inverter atau MPPT, tegangan sistem, seberapa sering terbayangi sebagian?
2. Masalah terbesar: rugi karena bayangan, diagnosis di lapangan, biaya microinverter atau optimizer, atau perawatan?
3. Ukuran berhasil: berapa persen pemulihan daya dan biaya tambahan maksimum yang masih masuk akal?
4. Ada data lapangan (kurva I-V atau log daya) atau akses atap untuk uji pilot? Siapa kontaknya?
5. Syarat teknis dan keselamatan (DC, interkoneksi, standar PLN)?
6. Apa yang perlu mereka lihat di demo, dan bersediakah jadi mitra pilot (LoI)?
- Ke panitia lewat grup WhatsApp: colokan listrik dan lampu halogen di PAU Lt. 8, akses matahari, jatah bahan prototyping, durasi pitch dan porsi demo, tim hadir di klinik tanggal berapa, apakah L3 wajib.
- Jujur di klinik: SHADESHIFT menutup sebagian selisih terhadap MLPE (sekitar seperempat sampai sepertiga di simulasi), bukan menyamainya; tidak mengikuti bayangan yang bergerak cepat; belum ada data atap nyata.

## Log
### 18 Okt 2026 (platform IoT lokal, tahap 0)
- Analisis sebelum/sesudah, kontrak antarmuka, dan rencana bangun: `ANALYSIS.md`, `CONTRACT.md`, `PLAN.md` (bahasa Inggris). Isi zip diekstrak utuh ke `docs/before/` (sama persis dengan zip, dicek CRC).
- Tahap 0: pohon kerja dipulihkan dari `docs/before/` (`SHADESHIFT_ML/` tanpa 6 CSV simulasi besar, `firmware/`, `rangkaian/`, `foto/`, `UNTUK_DAUZAN.md`), jadi dasbor jalan lagi di folder ini. Versi paket dikunci (`requirements.txt`, streamlit 1.66), venv di `D:\ShadeShift\.venv`, Streamlit tanpa telemetri dan tanpa tombol Deploy. Salinan bobot di `uji_pemilih/` diganti dengan bobot terbaru (keputusan sama di 38/38 kurva lab). Uji: `.venv\Scripts\python -m pytest` (13 lulus), `data_lab` tetap identik byte demi byte.
- Tahap 1: server lokal (FastAPI + SQLite, `python run.py server`, 127.0.0.1:8000): port ingest HTTP, riwayat/jejak audit di basis data, unggah CSV (`POST /api/v1/uploads`), impor data lab, aliran langsung WebSocket, perintah lewat antrean dengan daftar izin (RELAI/UJIRELAI/DAC/CEKVOC 0/SIKLUS diblokir). Penerbit uji `tools/publish_sample.py` (data lab yang diputar ulang, berlabel `demo`). Impor 120 kurva lab dari basis data menghasilkan angka laporan yang sama (0,82 / 2,71 / 4,30 / 12,0 %, lab).
- Tahap 2: gateway tepi (`python run.py gateway --source serial` atau `--source demo`): satu-satunya program yang memegang port USB ESP32, menjalankan pemilih dengan ONNX Runtime (model `models/pemilih.onnx` dibuat dari `pemilih_bobot.h`; keputusan sama dengan C di 38/38 kurva lab), mengukur waktu pindah/sapuan/keputusan, mengirim ke server lewat antrean (data tidak hilang bila server mati). Stop aman: sesudah Stop tidak ada perintah tugas yang terkirim lagi, hasil "done" hanya bila alat membalas semua relai terbuka. Aturan stabilitas (kunci TCT) dimatikan secara bawaan karena belum divalidasi.
- Tahap 3: dasbor sekarang klien server (`.venv\Scripts\python run.py demo` tanpa alat, `run.py live` dengan ESP32). Lima halaman: Langsung, Putar ulang, Unggah CSV, Peristiwa (jejak audit + CSV), Status. Keputusan AI selalu menyebut di mana dihitung; data demo berlabel DEMO. Satu perintah menyalakan server + gateway + dasbor; Ctrl+C mematikan dengan urutan aman (relai dibuka dulu). Dasbor hanya bisa dibuka dari laptop ini.
- Tahap 4: mode demo. `run.py demo --scenario` (atau tombol "Mulai skenario" di halaman Langsung) memutar skenario bayangan dari `scenarios/`: `default` (V1c → V3_paranet65 → V4_paranet65 → V1c; pemilih benar di tiap langkah: TCT, 4S, TCT), `kilat` (sama, 3x lebih cepat), `v6_kelemahan` (kasus salah yang diketahui, rugi 4,9 % lab). Data = kurva lab asli diputar ulang, berlabel DEMO; mode otomatis berjalan seperti dengan alat nyata. STOP menghentikan skenario.
- Temuan keselamatan untuk firmware: `OFF` tidak dibaca selama `SIKLUS` berjalan (lihat `ANALYSIS.md` §7.1 F1). Sampai firmware diperbaiki, jangan andalkan `OFF` saat SIKLUS.
### 17 Okt 2026 (dasbor)
- Dibuat `dasbor/` (Streamlit): mode langsung (serial ESP32 atau ESP32 TIRUAN yang memutar ulang data lab), putar ulang berkas, daya harapan dari kembaran (skala cahaya bisa dikalibrasi), peringatan selisih > 15%, pilih susunan otomatis dan mode otomatis pemicu 20% (dihitung di laptop, bobot sama dengan `pemilih.h`). Sapuan disimpan ke `data/data_dasbor/`.
- `python dasbor/uji_dasbor.py`: pemilih sama dengan C 38/38; angka lab sama dengan laporan (0,82 / 2,71 / 4,30 / 12,0%). Belum diuji dengan ESP32 sungguhan.
### 16 Okt 2026 (serah terima ke Dauzan)
- Dibuat `UNTUK_DAUZAN.md` (tugas Edge AI, firmware, dasbor; peta berkas; angka yang boleh dipakai) dan `CLAUDE.md` penunjuk untuk Claude Code Dauzan.
- Zip dibuat di `D:\Claude\_kirim_dauzan\SHADESHIFT_untuk_Dauzan.zip` (34 MB) dengan `buat_zip_untuk_dauzan.ps1`. Dikecualikan: berkas terkirim, CV dan pakta (data pribadi), arsip, gambar, 3D, PCB, presentasi, data lama.
### 16 Okt 2026 (sesudah klinik PLN)
- Pemilik masalah: manajer bidang transmisi PLN. Catatan: (1) PLN tidak bisa masuk ke PLTS lahan (tidak ada akses uji dari PLN); (2) topik menarik karena bisa mendeteksi gangguan dan harapan beliau mengetahui panel atau sel mana yang bermasalah pada PLTS 2 MW (sekitar 2 hektar); (3) PLN sekarang memakai drone termal untuk mengidentifikasi masalah sel; PLN belum bisa menjawab cara menskalakan sensor ke skala besar, idenya diharapkan datang dari tim.
- Arah bergeser: dari pemulihan daya atap ke deteksi dan lokalisasi gangguan di PLTS skala besar. Pemulihan daya jadi pelengkap.
- Kekurangan terhadap harapan PLN: model diagnosis sekarang mengklasifikasi PENYEBAB (6 kelas, simulasi 78-82%), belum menentukan LOKASI modul. Belum ada eksperimen lokalisasi. Belum ada rancangan untuk skala string 1000 V lebih.
- Koreksi klaim AI: yang terpasang di rencana ESP32 adalah regresi logistik (proposal: pohon keputusan atau regresi logistik). CNN 1D hanya dieksplorasi di simulasi (data kembaran 69%, lab 13%) dan tidak lebih baik dari model sederhana. Jangan bilang CNN sudah dipakai atau terbukti.
- Ide skala (belum dikerjakan, perlu dikonfirmasi): satu pelacak I-V di combiner box dengan matriks saklar yang menyapu banyak string bergantian; kurva tiap string menunjukkan jumlah substring terpengaruh; string anomali lalu diperiksa lebih lanjut (drone termal atau sapuan sub-string). Komplementer terhadap drone termal, bukan pengganti.
### 16 Okt 2026 (satu jam sebelum klinik)
- Kekurangan diakui: tidak bisa mengikuti bayangan cepat (MLPE bisa). Cara menyiasati yang disepakati untuk dibahas: (1) susunan bawaan TCT saat bayangan berkedip (89,6% di simulasi daun), (2) sapuan ulang hanya bila daya berubah >20% dan dengan jeda minimum, (3) aturan stabilitas sederhana dari variasi daya beberapa detik terakhir: tidak stabil = kunci TCT, stabil = jalankan pemilih, (4) ukur waktu sapuan dan peralihan nyata, perpendek sapuan, (5) saklar semikonduktor agar peralihan lebih cepat. Aturan stabilitas BELUM diuji di simulasi; bisa diuji di `dinamis.py`.
- Peran AI: pemilih susunan (terlatih, lab 0,82% vs 2,71%), penentu kapan menyapu (aturan, bukan model), diagnosis (simulasi saja; di demo sebagai indikator daya terukur vs daya harapan).
### 16 Okt 2026 (malam)
- Dibaca website dan PDF bootcamp (ringkasan di bagian 10).
- Keputusan sensor: tidak beli (LDR dan termometer tembak yang ada).
- Batas skala alat dihitung (bagian 3). Panduan data dan koreksi protokol dibuat (bagian 8). Definisi produk dan posisi terhadap MLPE ditulis (bagian 2).
- Arah dikoreksi: L3 mengikuti proposal (rancangan saklar semikonduktor), klinik dengan industri.
- Berkas ini diperluas menjadi catatan lengkap.
### 10 Okt 2026
- Panduan data, kurva ilustrasi per kelas (`panduan_data/`).
### 8 Okt 2026
- Bug Voc diperbaiki, dataset dibuat ulang; pemilih dievaluasi ulang dengan metrik poin MLPE; jalur B (kembaran digital, CNN) selesai; folder dirapikan, berkas lama di `_arsip/`.
### 7 Okt 2026
- Proposal, dokumen pendaftaran, dan presentasi dikirim.
