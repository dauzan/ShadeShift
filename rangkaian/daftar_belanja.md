# SHADESHIFT — Daftar Belanja (versi final, sesuai panduan rakit)

Harga = perkiraan toko online, bisa beda. Kolom "Kata kunci" untuk dicari di Tokopedia/Shopee.

## A. Otak & pengukuran
- [ ] ESP32 DevKit V1 **30 pin, WROOM-32** ×2 (1 cadangan) — "ESP32 DevKit V1 30 pin" — Rp 60–90 rb/buah
- [ ] Kabel USB **data** (bukan cuma charger), sesuai port ESP32 (micro-USB / Type-C) ×1 — Rp 15–25 rb
- [ ] Modul ADS1115 ×1 — "ADS1115 16 bit" — Rp 30–50 rb
- [ ] Modul MCP4725 ×1 — "MCP4725 DAC" — Rp 30–50 rb
- [ ] IC LM358 (DIP-8) ×2 + soket IC 8 pin ×2 — Rp 5–10 rb
- [ ] MOSFET IRFP260N ×2 (1 cadangan) — "IRFP260N" — Rp 25–40 rb/buah
- [ ] Heatsink aluminium untuk TO-247/TO-3P ×1 + **mika isolator TO-247 + ring isolator** + pasta termal — Rp 25–50 rb
- [ ] Resistor semen 0,1 Ω 5 W ×2 — "resistor 0.1 ohm 5 watt" — Rp 5 rb
- [ ] Resistor metal film 1%: 330 kΩ ×2, 10 kΩ ×10, 4,7 kΩ ×2, 220 Ω ×2 — Rp 10–20 rb
- [ ] Kapasitor keramik 100 nF ×5 — Rp 3 rb
- [ ] Sensor DS18B20 kemasan **TO-92** (bukan probe) ×5 — Rp 10–15 rb/buah
- [ ] Selotip aluminium (untuk tempel sensor di panel) ×1 — Rp 15 rb

## B. Relai & daya
- [ ] Modul relai 8 kanal 5 V, **ada optocoupler + jumper JD-VCC** ×2 — CEK DULU yang sudah ada di lab
- [ ] Adaptor 12 V 2 A ×1 — Rp 40–60 rb
- [ ] Modul step-down LM2596 ×1 — Rp 15–25 rb
- [ ] Dudukan sekring tabung 5×20 mm (inline/PCB) ×1 + **sekring 4 A** ×3 — Rp 10–20 rb
- [ ] Dioda Schottky 1N5822 ×6 — Rp 10 rb

## C. Kabel & sambungan
- [ ] Kabel serabut 1–1,5 mm² (NYAF) merah 5 m + hitam 5 m — Rp 40–60 rb
- [ ] Wago 221-415 (5 lubang) ×12 — Rp 60–100 rb (versi KW lebih murah, boleh)
- [ ] Kabel jumper dupont 20 cm: male-male, male-female, female-female (1 set @40) — Rp 30 rb
- [ ] PCB lubang 7×9 cm ×2 + pin header male & female — Rp 25 rb
- [ ] Timah solder + selongsong bakar (heat shrink) aneka ukuran — Rp 20–30 rb
- [ ] Kabel ties / label stiker (A, B, C, D, P, N, dst.) — Rp 10 rb

## D. Bahan uji
- [ ] Paranet 50% ×1 m dan 75% ×1 m — Rp 20–40 rb
- [ ] Karton hitam tebal / plastik hitam + cutter + penggaris — Rp 15 rb

## E. Cek di lab dulu (kalau tidak ada, baru beli)
- [ ] Multimeter (wajib ada)
- [ ] Solder + penyangga
- [ ] Solar power meter (SM206 / TES-1333) — Rp 300–600 rb
- [ ] Obeng kecil (untuk sekrup terminal relai)

**Total perkiraan A–D: Rp 0,7–1,1 juta** (tanpa solar power meter dan modul relai kalau sudah ada).

## Jangan sampai salah beli
1. ESP32 **30 pin WROOM**, bukan WROVER/38 pin (pin GPIO16/17 dipakai).
2. Modul relai **dengan jumper JD-VCC**. Kalau yang di lab tidak ada jumper itu, kirim fotonya dulu.
3. DS18B20 **TO-92** (kecil seperti transistor), bukan versi probe stainless.
4. Sekring **4 A**, bukan 3 A.
5. Kabel USB harus **kabel data**.
