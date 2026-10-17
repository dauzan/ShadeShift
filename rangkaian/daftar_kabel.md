# SHADESHIFT — Daftar Kabel (dari → ke)

Modul relai: 8 kanal (R1–R4), 4 kanal baru (R0, R5, R6, R7), 4 kanal lama (R8–R10). Asumsi: 5 V, ada optocoupler + jumper JD-VCC, aktif LOW. Kalau modulnya beda, cek ulang bagian E.
Kabel tebal (1–1,5 mm², merah/hitam) untuk jalur daya (A–C). Kabel dupont untuk sinyal (D–G).

## A. Persiapan panel (tiap panel A, B, C, D)

| No | Dari | Ke | Catatan |
|---|---|---|---|
| A1 | 1N5822 kaki **bergaris** (katoda) | terminal **+** panel | sedekat mungkin dengan terminal |
| A2 | 1N5822 kaki **polos** (anoda) | terminal **−** panel | |
| A3 | Panel dari kiri-atas | Label **A** | susunan fisik: A kiri-atas, B kiri-bawah, C kanan-atas, D kanan-bawah |

## B. Titik sambung (Wago) — buat 10 titik

| Titik | Isi kabel yang masuk | Jumlah |
|---|---|---|
| **P** (bus +) | Panel A+, R3-COM, R8-COM, R10-COM, R0-COM, resistor 330 kΩ | 6 |
| **N** (bus −) | Panel D−, R2-NO, R7-NO, R9-NO, kabel ke kaki bawah shunt | 5 |
| **A−** | Panel A−, R1-COM, R7-COM | 3 |
| **B+** | Panel B+, R1-NO, R6-COM, R8-NO | 4 |
| **B−** | Panel B−, R2-COM, R5-COM | 3 |
| **C+** | Panel C+, R3-NO, R5-NO | 3 |
| **C−** | Panel C−, R4-COM, R9-COM | 3 |
| **D+** | Panel D+, R4-NO, R6-NO, R10-NO | 4 |

Titik dengan 6 kabel: pakai dua Wago 5-lubang yang disambung satu kabel pendek.
Panel A+ langsung masuk titik P, panel D− langsung masuk titik N (ini "kabel tetap").

## C. Matriks relai (kontak: pakai COM dan NO, NC dibiarkan kosong)

Tiga modul: **8 kanal** (hanya IN2–IN5 yang sehat), **4 kanal baru**, dan **4 kanal lama**.

| Relai | Modul – channel | COM ke | NO ke |
|---|---|---|---|
| R0 | 4 kanal **baru** – IN1 | P | Sekring (masuk) |
| R1 | 8 kanal – IN2 | A− | B+ |
| R2 | 8 kanal – IN3 | B− | N |
| R3 | 8 kanal – IN4 | P | C+ |
| R4 | 8 kanal – IN5 | C− | D+ |
| R5 | 4 kanal **baru** – IN2 | B− | C+ |
| R6 | 4 kanal **baru** – IN3 | B+ | D+ |
| R7 | 4 kanal **baru** – IN4 | A− | N |
| R8 | 4 kanal **lama** – IN4 | P | B+ |
| R9 | 4 kanal **lama** – IN2 | C− | N |
| R10 | 4 kanal **lama** – IN3 | P | D+ |

Tidak dipakai: 8 kanal IN1, IN6, IN7, IN8 (rusak); 4 kanal lama IN1 (relai tidak bunyi).

## D. Jalur ukur (kabel tebal)

| No | Dari | Ke | Catatan |
|---|---|---|---|
| D1 | Sekring (keluar) | MOSFET kaki **tengah** (Drain) | IRFP260N dilihat dari depan (tulisan menghadap kita, kaki di bawah): kiri = Gate, tengah = Drain, kanan = Source |
| D2 | MOSFET kaki **kanan** (Source) | Shunt 0,1 Ω ujung 1 | titik ini disebut **node S** |
| D3 | Shunt ujung 2 | Titik **N** | kaki bawah shunt = **titik bintang GND** |
| D4 | MOSFET | Heatsink | pakai mika isolator + pasta; tanpa mika, heatsink ikut bertegangan (Drain) |

## E. Catu daya

| No | Dari | Ke | Catatan |
|---|---|---|---|
| E1 | Adaptor 12 V (+) | Step-down LM2596 IN+ | |
| E2 | Adaptor 12 V (−) | Step-down IN− | |
| E3 | Adaptor 12 V (+) | LM358 pin 8 | |
| E4 | Adaptor 12 V (−) | Titik bintang GND (kaki bawah shunt) | satu kabel saja |
| E5 | Step-down OUT+ (**atur ke 5,0 V dulu** pakai multimeter) | **Ketiga** modul relai, pin **JD-VCC** (kalau ada modul tanpa JD-VCC: ke pin VCC-nya) | jumper JD-VCC **dilepas** |
| E6 | Step-down OUT− | **Ketiga** modul relai, pin **GND** (di sebelah JD-VCC) | |
| E7 | ESP32 | USB laptop | ESP32 hanya dari USB; jangan sambung step-down ke pin VIN ESP32 |

## F. ESP32 ↔ sinyal

| No | Dari (ESP32) | Ke | Catatan |
|---|---|---|---|
| F1 | 3V3 | **Ketiga** modul relai, pin **VCC** (sisi input) | hanya untuk LED optocoupler |
| F2 | GPIO13 | 4 kanal **baru** IN1 (R0) | |
| F3 | GPIO16 (RX2) | 8 kanal IN2 (R1) | |
| F4 | GPIO17 (TX2) | 8 kanal IN3 (R2) | |
| F5 | GPIO18 | 8 kanal IN4 (R3) | |
| F6 | GPIO19 | 8 kanal IN5 (R4) | |
| F7 | GPIO23 | 4 kanal **baru** IN2 (R5) | |
| F8 | GPIO25 | 4 kanal **baru** IN3 (R6) | |
| F9 | GPIO26 | 4 kanal **baru** IN4 (R7) | |
| F10 | GPIO27 | 4 kanal **lama** IN4 (R8) | dipindah dari IN1 karena relai itu tidak bunyi |
| F11 | GPIO32 | 4 kanal **lama** IN2 (R9) | |
| F12 | GPIO33 | 4 kanal **lama** IN3 (R10) | |
| F13 | GPIO21 (SDA) | ADS1115 SDA **dan** MCP4725 SDA | |
| F14 | GPIO22 (SCL) | ADS1115 SCL **dan** MCP4725 SCL | |
| F15 | 3V3 | ADS1115 VDD, MCP4725 VCC | |
| F16 | GND | ADS1115 GND, MCP4725 GND, titik bintang GND, **dan (−) adaptor / pin 4 LM358** | **GND ESP32 harus satu dengan GND adaptor**, kalau tidak LM358 tidak bekerja |

Pin IN relai **tanpa** resistor ke GND (untuk modul aktif LOW).

## G. Pengukuran tegangan, arus, dan penggerak gate

| No | Dari | Ke | Catatan |
|---|---|---|---|
| G1 | Titik **P** | Resistor 330 kΩ | pembagi tegangan, sebelum R0 |
| G2 | 330 kΩ ujung lain | Resistor 10 kΩ | sambungan tengah = **V_sense** |
| G3 | 10 kΩ ujung lain | GND | |
| G4 | V_sense | ADS1115 **A0** | |
| G5 | V_sense | Kapasitor 100 nF → GND | peredam derau |
| G6 | Node S (shunt ujung 1) | ADS1115 **A1** | |
| G7 | Shunt ujung 2 (langsung di kakinya) | ADS1115 **A3** | kabel sendiri, jangan numpang kabel GND lain. Arus dibaca sebagai selisih A1−A3 |
| G8 | ADS1115 ADDR | GND | alamat 0x48 |
| G9 | MCP4725 A0/ADDR | GND | alamat 0x60 (cek dengan I²C scanner, ada modul yang 0x62) |
| G10 | MCP4725 OUT | LM358 pin 3 (IN+) | |
| G11 | LM358 pin 2 (IN−) | Resistor 10 kΩ → GND | penguat ×2 |
| G12 | LM358 pin 2 (IN−) | Resistor 10 kΩ → LM358 pin 1 (OUT) | |
| G13 | LM358 pin 4 | GND | |
| G14 | LM358 pin 1 (OUT) | Resistor 220 Ω → MOSFET kaki **kiri** (Gate) | |
| G15 | MOSFET Gate | Resistor 10 kΩ → GND | MOSFET mati saat ESP32 restart |
| G16 | LM358 pin 5 | GND | op-amp kedua tidak dipakai |
| G17 | LM358 pin 6 | LM358 pin 7 | op-amp kedua tidak dipakai |

## H. Urutan menyalakan pertama kali (tanpa panel dulu)

1. Atur step-down ke 5,0 V **sebelum** disambung ke relai.
2. Sambung semua kecuali panel. Unggah firmware, jalankan I²C scanner: harus muncul 0x48 dan 0x60.
3. Uji tiap topologi dengan multimeter mode kontinuitas di titik-titik Wago (panel belum terpasang).
4. Ganti panel dengan adaptor/baterai + resistor, uji sweep, bandingkan dengan multimeter.
5. Baru pasang panel satu per satu.

Keselamatan: pada 4S tegangan sampai ±88 V. Jangan ubah kabel saat R0 tertutup. Heatsink dianggap bertegangan kalau tanpa mika.
