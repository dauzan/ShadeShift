/*
  SHADESHIFT — firmware ESP32 v3 (18-10-2026), dibangun dari v2 (30-09-2026).
  Penjejak kurva I-V + pemilih topologi 4S / 2S2P / TCT / 4P, dengan PEMILIH (Edge AI / TinyML) DI ESP32.
  Suhu panel diukur manual pakai termometer tembak (tidak ada sensor suhu).

  Papan    : ESP32 Dev Module (DevKit V1 30 pin, WROOM-32)
  Pustaka  : Adafruit ADS1X15, Adafruit MCP4725
  Serial   : 115200 baud, akhir baris "Newline"
  Berkas   : pemilih.h, pemilih_bobot.h, pemilih_sidik.h harus ada di folder sketsa ini.

  BARU di v3 (lihat firmware/CARA_PAKAI_v3.md):
    - Setiap SWEEP pada 4S menjalankan pemilih.h di ESP32 dan mencetak, sebelum "# SELESAI":
        # pemilih=TCT, skor=<s4S>;<s2S2P>;<sTCT>, t_us=<waktu cuplik ulang + 14 fitur + model>
    - PILIH         4S -> SWEEP -> pemilih (di ESP32) -> pindah ke pilihan (urutan aman) -> SWEEP. OFF menghentikannya.
    - INFO          # INFO fw=3.0.0, id=<chip>, n=201, w=<sidik bobot 12 hex>  (gateway memeriksa w = bobot laptop)
    - "# meta t_ms=<millis>, seq=<nomor sapuan>" sesudah "# MULAI"
    - Keselamatan: OFF/STOP/BATAL berlaku di dalam SIKLUS dan PILIH (di antara langkah dan saat menunggu LANJUT);
      sapuan gagal menghentikan SIKLUS; RELAI, UJIRELAI dan DAC hanya dalam mode BENCH 1 (TANPA PANEL, tanpa susunan aktif);
      DAC menolak nilai di luar 0-4095.
  TIDAK berubah: urutan aman pindah susunan (pindah()), format sapuan, perintah v2 lainnya.
  Status: dikompilasi dan diuji di laptop dengan tiruan perangkat keras (tests/test_firmware_v3.py); BELUM dijalankan di papan.

  Perintah (ketik di Serial Monitor atau lewat gateway):
    BANTUAN          daftar perintah
    INFO             versi firmware, id chip, sidik bobot pemilih
    SCAN             cari perangkat I2C (harus ada 0x48 dan 0x60/0x62)
    KAL              baca mentah ADC (untuk kalibrasi & offset)
    BENCH 1|0        mode uji bangku TANPA PANEL: membuka RELAI, UJIRELAI, DAC (OFF juga mengakhiri mode ini)
    DAC <0-4095>     atur DAC manual (hanya BENCH 1)
    UJIRELAI         nyalakan relai satu per satu (hanya BENCH 1)
    RELAI <0-10> <0|1>   nyalakan / matikan SATU relai manual (hanya BENCH 1)
    4S | 2S2P | TCT | 4P   pindah topologi dengan urutan aman
    OFF / STOP       matikan semua (MOSFET mati, semua relai buka); juga menghentikan SIKLUS dan PILIH
    VOC              baca tegangan array saat ini
    PANTAU 1|0       tampilkan tegangan array otomatis tiap 0,5 detik (0 = berhenti)
    SWEEP <label>    ukur kurva I-V; pada 4S pemilih ikut berjalan
    PILIH            pilih susunan otomatis di ESP32 (lihat di atas)
    SIKLUS <label> <ulangan>   ukur SEMUA topologi, urutan diacak; berhenti tiap putaran untuk catat suhu (LANJUT / BATAL)
    VPANEL <volt>    Voc satu panel saat ini (bawaan 21). Batas cek Voc = 0,5-1,2 x jumlah panel seri x nilai ini
    CEKVOC 0|1       matikan/nyalakan pengecekan Voc (0 = uji tanpa panel)
    STATUS           tampilkan keadaan
*/
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <Adafruit_MCP4725.h>
#include "pemilih.h"
#include "pemilih_sidik.h"

#define FW_VERSI "3.0.0"

// ================== WAJIB DIISI SETELAH DIUKUR PAKAI MULTIMETER ==================
const float R_ATAS   = 330000.0;   // ohm, resistor pembagi atas (ukur nilai aslinya)
const float R_BAWAH  = 10000.0;    // ohm, resistor pembagi bawah (ukur nilai aslinya)
const float R_SHUNT  = 0.100;      // ohm, shunt
const float V_OFFSET = 0.0;        // V, dari perintah KAL saat semua mati (biasanya ~0)
const float I_OFFSET = 0.0;        // A, dari perintah KAL saat semua mati
const bool  RELAI_AKTIF_LOW = true;          // modul opto biasa: true
// ================================================================================

const uint8_t PIN_R[11] = {13, 16, 17, 18, 19, 23, 25, 26, 27, 32, 33};  // R0..R10
const uint16_t N_TITIK  = 201;
#define BIT_R(i) (1u << (i))

struct Topologi { const char* nama; uint16_t mask; float nSeri; };   // nSeri = jumlah panel seri dalam satu string
const Topologi TOPO[4] = {
  {"4S",   BIT_R(1) | BIT_R(4) | BIT_R(5),                                4},
  {"2S2P", BIT_R(1) | BIT_R(2) | BIT_R(3) | BIT_R(4),                     2},
  {"TCT",  BIT_R(1) | BIT_R(2) | BIT_R(3) | BIT_R(4) | BIT_R(6),          2},
  {"4P",   BIT_R(2) | BIT_R(3) | BIT_R(7) | BIT_R(8) | BIT_R(9) | BIT_R(10), 1},
};
// Kelas pemilih (0 = 4S, 1 = 2S2P, 2 = TCT) sama dengan indeks TOPO.

Adafruit_ADS1115 ads;
Adafruit_MCP4725 dac;
int  topoAktif = -1;
bool cekVoc = true;
bool r0Tutup = false;
bool bench = false;    // mode uji bangku (tanpa panel)
float vPanel = 21.0;   // V, Voc satu panel pada cahaya saat ini (ubah lewat VPANEL)
bool pantau = false;
uint32_t tPantau = 0;
uint32_t nomorSapuan = 0;

// Titik sapuan terakhir (titik Voc pertama + N_TITIK titik), dipakai pemilih. ~1,6 KB.
static float bufV[N_TITIK + 1], bufI[N_TITIK + 1];
static int nBuf = 0;
static float V201[PEMILIH_N], I201[PEMILIH_N];
int pilihanTerakhir = -1;   // keputusan pemilih dari sapuan 4S terakhir (-1 = belum ada / gagal)

// Prototipe (Arduino IDE membuatnya otomatis; ditulis agar urutan fungsi jelas dan bisa dikompilasi di laptop)
void semuaMati();
bool pindah(int idx);
bool sapuan(const String& label);
bool adaPerintahBerhenti(const char* tugas);

// ---------------- dasar ----------------
void setRelai(uint8_t i, bool nyala) {
  bool level = nyala ? !RELAI_AKTIF_LOW : RELAI_AKTIF_LOW;
  digitalWrite(PIN_R[i], level ? HIGH : LOW);
  if (i == 0) r0Tutup = nyala;
}
void dacSet(uint16_t kode) { dac.setVoltage(kode > 4095 ? 4095 : kode, false); }

float bacaV(uint8_t n) {
  ads.setGain(GAIN_ONE);                       // +-4,096 V
  float s = 0;
  for (uint8_t k = 0; k < n; k++) s += ads.computeVolts(ads.readADC_SingleEnded(0));
  return (s / n) * (R_ATAS + R_BAWAH) / R_BAWAH - V_OFFSET;
}
float bacaI(uint8_t n) {
  ads.setGain(GAIN_EIGHT);                     // +-0,512 V
  float s = 0;
  for (uint8_t k = 0; k < n; k++) s += ads.computeVolts(ads.readADC_Differential_1_3());
  return (s / n) / R_SHUNT - I_OFFSET;
}

void semuaMati() {
  dacSet(0); delay(30);
  setRelai(0, false); delay(80);
  for (uint8_t i = 1; i <= 10; i++) setRelai(i, false);
  topoAktif = -1;
  bench = false;
  Serial.println("# semua relai terbuka, MOSFET mati");
}

bool kataBerhenti(String t) {                 // OFF / STOP / BATAL menghentikan tugas yang sedang berjalan
  t.trim(); t.toUpperCase();
  return t == "OFF" || t == "STOP" || t == "BATAL";
}

// Baca baris yang menunggu tanpa memblokir. True bila ada OFF/STOP/BATAL; perintah lain diabaikan (dan dilaporkan).
bool adaPerintahBerhenti(const char* tugas) {
  bool berhenti = false;
  while (Serial.available()) {
    String t = Serial.readStringUntil('\n'); t.trim();
    if (t.length() == 0) continue;
    if (kataBerhenti(t)) berhenti = true;
    else Serial.printf("# diabaikan selama %s: %s (ketik OFF untuk berhenti)\n", tugas, t.c_str());
  }
  return berhenti;
}

// ---------------- pindah topologi (urutan aman, TIDAK diubah dari v2) ----------------
bool pindah(int idx) {
  const Topologi& t = TOPO[idx];
  dacSet(0); delay(30);                        // 1. MOSFET mati -> arus nol
  setRelai(0, false); delay(80);               // 2. buka pemutus utama
  for (uint8_t i = 1; i <= 10; i++) setRelai(i, false);   // 3. buka semua relai topologi
  delay(150);
  for (uint8_t i = 1; i <= 10; i++) if (t.mask & BIT_R(i)) setRelai(i, true);   // 4. tutup relai target
  delay(250);
  float voc = bacaV(16);                        // 5. cek Voc (pembagi ada sebelum R0)
  Serial.printf("# topologi %s, Voc = %.2f V\n", t.nama, voc);
  float vMin = 0.5f * t.nSeri * vPanel, vMaks = 1.2f * t.nSeri * vPanel;
  if (cekVoc && (voc < vMin || voc > vMaks)) {
    Serial.printf("# GAGAL: Voc di luar %.0f-%.0f V (VPANEL=%.1f). Cek kabel relai atau cahaya! Semua dimatikan.\n", vMin, vMaks, vPanel);
    semuaMati();
    return false;
  }
  setRelai(0, true); delay(100);               // 6. tutup pemutus utama
  topoAktif = idx;
  Serial.printf("# siap: %s\n", t.nama);
  return true;
}

// ---------------- pemilih susunan (Edge AI / TinyML) ----------------
// Pakai titik sapuan terakhir (bufV/bufI, DIUBAH di tempat). Mengembalikan kelas 0/1/2 atau -1 bila titik valid kurang.
int jalankanPemilih(float skor[PEMILIH_N_KELAS], uint32_t* t_us) {
  float f[PEMILIH_N_FITUR];
  uint32_t t0 = micros();
  if (pemilih_cuplik_ulang(bufV, bufI, nBuf, V201, I201) != 0) { *t_us = micros() - t0; return -1; }
  pemilih_fitur(V201, I201, f);
  int k = pemilih_putuskan(f, skor);
  *t_us = micros() - t0;
  return k;
}

// ---------------- sweep kurva I-V ----------------
// Cetak satu titik (format v2 "V,I,P") dan simpan ANGKA YANG DICETAK ke bufV/bufI. Jadi pemilih di ESP32 memakai data
// yang persis sama dengan yang diterima laptop: keputusan papan bisa dihitung ulang dari log, tanpa selisih pembulatan.
void cetakTitik(float v, float i, float p) {
  char baris[48]; char* akhir;
  snprintf(baris, sizeof(baris), "%.4f,%.5f,%.4f", v, i, p);
  Serial.println(baris);
  bufV[nBuf] = strtof(baris, &akhir);
  bufI[nBuf] = strtof(akhir + 1, NULL);
  nBuf++;
}

// Mengembalikan true bila sapuan selesai (blok "# MULAI ... # SELESAI" tercetak lengkap).
bool sapuan(const String& label) {
  if (topoAktif < 0 || !r0Tutup) { Serial.println("# GAGAL: pilih topologi dulu (4S/2S2P/TCT/4P)"); return false; }
  dacSet(0); delay(150);
  float voc = bacaV(16);
  // 1) sweep kasar: cari rentang kode DAC tempat MOSFET mulai menghantar sampai hampir hubung singkat
  int lo = -1, hi = 4095;
  for (int kode = 0; kode <= 4095; kode += 32) {
    dacSet(kode); delay(3);
    float i = bacaI(1), v = bacaV(1);
    if (lo < 0 && i > 0.005) lo = kode;
    if (v < 0.2 + 0.02 * voc) { hi = kode; break; }
  }
  dacSet(0);
  if (lo < 0) { Serial.println("# GAGAL: arus tidak terdeteksi. Cek sekring, R0, MOSFET, dan shunt."); return false; }
  lo = max(0, lo - 96); hi = min(4095, hi + 32);
  delay(300);
  // 2) sweep halus; titik disimpan ke bufV/bufI untuk pemilih
  nomorSapuan++;
  Serial.printf("# MULAI %s\n", label.c_str());
  Serial.printf("# meta t_ms=%lu, seq=%lu\n", (unsigned long)millis(), (unsigned long)nomorSapuan);
  Serial.printf("# topologi=%s, Voc=%.3f V, dac=%d..%d, N=%u\n", TOPO[topoAktif].nama, voc, lo, hi, N_TITIK);
  Serial.println("V,I,P");
  nBuf = 0;
  cetakTitik(voc, 0.0f, 0.0f);
  float pmaks = 0, vmp = 0, imp = 0;
  for (uint16_t k = 0; k < N_TITIK; k++) {
    uint16_t kode = lo + (uint32_t)(hi - lo) * k / (N_TITIK - 1);
    dacSet(kode); delay(4);
    float v = bacaV(2), i = bacaI(2);
    if (i < 0) i = 0;
    float p = v * i;
    if (p > pmaks) { pmaks = p; vmp = v; imp = i; }
    cetakTitik(v, i, p);
  }
  dacSet(0);
  Serial.printf("# Pmax=%.4f W, Vmp=%.3f V, Imp=%.4f A\n", pmaks, vmp, imp);
  if (topoAktif == 0) {                         // pemilih hanya dilatih untuk sapuan 4S
    float skor[PEMILIH_N_KELAS]; uint32_t t_us;
    pilihanTerakhir = jalankanPemilih(skor, &t_us);
    if (pilihanTerakhir >= 0)
      Serial.printf("# pemilih=%s, skor=%.4f;%.4f;%.4f, t_us=%lu\n", PEMILIH_NAMA[pilihanTerakhir], skor[0], skor[1], skor[2], (unsigned long)t_us);
    else
      Serial.println("# pemilih=GAGAL (titik valid kurang dari 2)");
  }
  Serial.println("# catat suhu punggung panel A-D sesudah sweep (termometer tembak)");
  Serial.println("# SELESAI");
  return true;
}

// ---------------- PILIH: pemilihan susunan di ESP32 ----------------
void pilihOtomatis() {                         // dari susunan mana pun: pindah() selalu lewat urutan aman
  String dasar = "pilih_" + String((unsigned long)(nomorSapuan + 1));
  if (!pindah(0)) { Serial.println("# PILIH GAGAL: pindah ke 4S"); return; }
  if (adaPerintahBerhenti("PILIH")) { semuaMati(); Serial.println("# PILIH dihentikan"); return; }
  delay(300);
  if (!sapuan(dasar + "_4S")) { Serial.println("# PILIH GAGAL: sapuan 4S"); return; }
  if (pilihanTerakhir < 0) { Serial.println("# PILIH GAGAL: pemilih tidak bisa memutuskan"); return; }
  int k = pilihanTerakhir;
  if (adaPerintahBerhenti("PILIH")) { semuaMati(); Serial.println("# PILIH dihentikan"); return; }
  if (k != 0) {
    if (!pindah(k)) { Serial.println("# PILIH GAGAL: pindah ke pilihan"); return; }
    if (adaPerintahBerhenti("PILIH")) { semuaMati(); Serial.println("# PILIH dihentikan"); return; }
    delay(300);
    if (!sapuan(dasar + "_" + TOPO[k].nama)) { Serial.println("# PILIH GAGAL: sapuan pilihan"); return; }
  }
  Serial.printf("# PILIH SELESAI: %s\n", TOPO[k].nama);
}

// ---------------- siklus: semua topologi, urutan acak, beberapa ulangan ----------------
// LANJUT melanjutkan; BATAL, OFF dan STOP membatalkan (v2 mengabaikan OFF di sini).
bool tungguLanjut(const char* pesan) {
  Serial.printf("# %s. Ketik LANJUT (atau BATAL / OFF).\n", pesan);
  while (true) {
    if (Serial.available()) {
      String t = Serial.readStringUntil('\n'); t.trim(); t.toUpperCase();
      if (t == "LANJUT") return true;
      if (kataBerhenti(t)) return false;
      if (t.length()) Serial.printf("# diabaikan selama SIKLUS: %s (ketik LANJUT, BATAL atau OFF)\n", t.c_str());
    }
    delay(20);
  }
}

void siklus(const String& arg) {
  String label = arg; int ulang = 3;
  int sp = arg.lastIndexOf(' ');
  if (sp > 0 && arg.substring(sp + 1).toInt() > 0) { ulang = arg.substring(sp + 1).toInt(); label = arg.substring(0, sp); }
  label.trim(); if (label.length() == 0) label = "siklus";
  if (topoAktif >= 0) semuaMati();
  if (!tungguLanjut("SIKLUS: ukur suhu punggung panel A-D (termometer tembak) sebelum mulai")) { semuaMati(); Serial.println("# siklus dibatalkan"); return; }
  for (int u = 1; u <= ulang; u++) {
    int urut[4] = {0, 1, 2, 3};
    for (int i = 3; i > 0; i--) { int j = esp_random() % (i + 1); int t = urut[i]; urut[i] = urut[j]; urut[j] = t; }
    Serial.printf("# putaran %d/%d, urutan: %s %s %s %s\n", u, ulang, TOPO[urut[0]].nama, TOPO[urut[1]].nama, TOPO[urut[2]].nama, TOPO[urut[3]].nama);
    for (int k = 0; k < 4; k++) {
      if (adaPerintahBerhenti("SIKLUS")) { semuaMati(); Serial.println("# siklus dihentikan (OFF)"); return; }
      if (!pindah(urut[k])) { Serial.println("# siklus dihentikan (topologi gagal)"); return; }
      delay(1500);
      if (adaPerintahBerhenti("SIKLUS")) { semuaMati(); Serial.println("# siklus dihentikan (OFF)"); return; }
      if (!sapuan(label + "_" + TOPO[urut[k]].nama + "_u" + String(u))) {     // v2: kegagalan sapuan tidak terdeteksi
        semuaMati(); Serial.println("# siklus dihentikan (sweep gagal)"); return;
      }
    }
    semuaMati();
    if (u < ulang && !tungguLanjut("catat suhu punggung panel A-D; bila bergeser >1 C dari awal, tunggu dingin dulu")) { semuaMati(); Serial.println("# siklus dibatalkan"); return; }
  }
  Serial.println("# SIKLUS SELESAI, catat suhu akhir");
}

// ---------------- perintah lain ----------------
void scanI2C() {
  Serial.println("# scan I2C:");
  for (uint8_t a = 1; a < 127; a++) { Wire.beginTransmission(a); if (Wire.endTransmission() == 0) Serial.printf("#   ditemukan 0x%02X\n", a); }
}
bool perluBench(const char* perintah) {
  if (!bench) { Serial.printf("# GAGAL: %s hanya dalam mode uji bangku TANPA PANEL. Ketik OFF, lepas panel, lalu BENCH 1\n", perintah); return false; }
  if (topoAktif >= 0) { Serial.println("# GAGAL: ketik OFF dulu"); return false; }
  return true;
}
void ujiRelai() {
  if (!perluBench("UJIRELAI")) return;
  Serial.println("# UJI RELAI: pastikan PANEL TIDAK TERSAMBUNG. Tiap relai menyala 1 detik.");
  for (uint8_t i = 0; i <= 10; i++) {
    Serial.printf("#   R%u nyala (GPIO%u)\n", i, PIN_R[i]);
    setRelai(i, true); delay(1000); setRelai(i, false); delay(300);
  }
  Serial.println("# uji relai selesai");
}
void relaiManual(const String& arg) {
  if (!perluBench("RELAI")) return;
  int sp = arg.indexOf(' ');
  String sn = (sp < 0 ? arg : arg.substring(0, sp)); sn.trim();
  String sv = (sp < 0 ? String("") : arg.substring(sp + 1)); sv.trim();
  bool angka = sn.length() > 0;
  for (unsigned k = 0; k < sn.length(); k++) if (!isDigit(sn[k])) angka = false;
  if (!angka || sn.toInt() > 10 || (sv != "0" && sv != "1")) {
    Serial.println("# format: RELAI <0-10> <0|1>, contoh: RELAI 6 1");
    return;
  }
  uint8_t n = sn.toInt(); bool nyala = (sv == "1");
  setRelai(n, nyala);
  Serial.printf("# R%u %s (GPIO%u). Ingat: HANYA TANPA PANEL, ketik OFF setelah selesai\n",
                n, nyala ? "NYALA" : "mati", PIN_R[n]);
}
void dacManual(const String& arg) {
  if (!perluBench("DAC")) return;
  bool angka = arg.length() > 0;
  for (unsigned k = 0; k < arg.length(); k++) if (!isDigit(arg[k])) angka = false;
  long k = angka ? arg.toInt() : -1;
  if (!angka || k < 0 || k > 4095) { Serial.println("# format: DAC <0-4095>"); return; }
  dacSet((uint16_t)k);
  Serial.printf("# DAC=%ld (keluaran LM358 harus ~%.2f V)\n", k, 6.6 * k / 4095.0);
}
void kalibrasi() {
  ads.setGain(GAIN_ONE);   float a0 = ads.computeVolts(ads.readADC_SingleEnded(0));
  ads.setGain(GAIN_EIGHT); float d13 = ads.computeVolts(ads.readADC_Differential_1_3());
  Serial.printf("# A0=%.5f V -> V_array=%.3f V | A1-A3=%.6f V -> I=%.5f A\n",
                a0, a0 * (R_ATAS + R_BAWAH) / R_BAWAH, d13, d13 / R_SHUNT);
}
void status() {
  Serial.printf("# topologi=%s, R0=%s, cekVoc=%s, bench=%s, fw=%s\n",
                topoAktif < 0 ? "-" : TOPO[topoAktif].nama, r0Tutup ? "tutup" : "buka", cekVoc ? "ON" : "OFF",
                bench ? "ON" : "OFF", FW_VERSI);
}
void info() {
  char w[13]; pemilih_sidik(w);
  uint64_t mac = ESP.getEfuseMac();
  Serial.printf("# INFO fw=%s, id=%04x%08lx, n=%u, w=%s\n", FW_VERSI, (unsigned)(mac >> 32), (unsigned long)(uint32_t)mac, N_TITIK, w);
}
void bantuan() {
  Serial.println("# Perintah: BANTUAN, INFO, SCAN, KAL, BENCH 1|0, DAC <0-4095>, UJIRELAI, RELAI <0-10> <0|1>, 4S, 2S2P, TCT, 4P, OFF, VOC, PANTAU 1|0, SWEEP <label>, PILIH, SIKLUS <label> <ulangan>, VPANEL <V>, CEKVOC 0|1, STATUS");
}

void setup() {
  for (uint8_t i = 0; i <= 10; i++) {           // tulis level MATI dulu, baru jadikan output -> relai tidak berkedip
    digitalWrite(PIN_R[i], RELAI_AKTIF_LOW ? HIGH : LOW);
    pinMode(PIN_R[i], OUTPUT);
  }
  Serial.begin(115200);
  Serial.setTimeout(100);
  delay(300);
  Wire.begin(21, 22);
  Serial.println("\n# SHADESHIFT firmware v3");
  if (!ads.begin(0x48)) Serial.println("# PERINGATAN: ADS1115 (0x48) tidak ditemukan");
  ads.setDataRate(RATE_ADS1115_860SPS);
  if (!dac.begin(0x60) && !dac.begin(0x62)) Serial.println("# PERINGATAN: MCP4725 (0x60/0x62) tidak ditemukan");
  dacSet(0);
  semuaMati();
  bantuan();
  info();
}

void loop() {
  if (pantau && millis() - tPantau >= 500) {
    tPantau = millis();
    Serial.printf("# V_array = %.2f V\n", bacaV(8));
  }
  if (!Serial.available()) return;
  String baris = Serial.readStringUntil('\n'); baris.trim();
  if (baris.length() == 0) return;
  int sp = baris.indexOf(' ');
  String cmd = (sp < 0 ? baris : baris.substring(0, sp)); cmd.toUpperCase();
  String arg = (sp < 0 ? "" : baris.substring(sp + 1)); arg.trim();

  if (cmd == "BANTUAN" || cmd == "HELP") bantuan();
  else if (cmd == "INFO") info();
  else if (cmd == "SCAN") scanI2C();
  else if (cmd == "KAL") kalibrasi();
  else if (cmd == "BENCH") {
    if (arg == "1") {
      if (topoAktif >= 0) Serial.println("# GAGAL: ketik OFF dulu");
      else { bench = true; Serial.println("# BENCH ON: HANYA TANPA PANEL. RELAI, UJIRELAI, DAC aktif; OFF mengakhiri"); }
    } else { semuaMati(); Serial.println("# BENCH OFF"); }
  }
  else if (cmd == "DAC") dacManual(arg);
  else if (cmd == "UJIRELAI") ujiRelai();
  else if (cmd == "RELAI") relaiManual(arg);
  else if (cmd == "OFF" || cmd == "STOP" || cmd == "BATAL") semuaMati();
  else if (cmd == "VOC") Serial.printf("# V_array = %.3f V\n", bacaV(16));
  else if (cmd == "PANTAU") { pantau = (arg != "0"); Serial.printf("# pantau %s\n", pantau ? "ON" : "OFF"); }
  else if (cmd == "SIKLUS") siklus(arg);
  else if (cmd == "PILIH") pilihOtomatis();
  else if (cmd == "VPANEL") { float v = arg.toFloat(); if (v > 5 && v < 40) vPanel = v; Serial.printf("# VPANEL = %.1f V\n", vPanel); }
  else if (cmd == "SWEEP") sapuan(arg.length() ? arg : String("tanpa_label"));
  else if (cmd == "CEKVOC") { cekVoc = (arg != "0"); status(); }
  else if (cmd == "STATUS") status();
  else {
    bool ok = false;
    for (int i = 0; i < 4; i++) if (cmd == TOPO[i].nama) { pindah(i); ok = true; }
    if (!ok) Serial.println("# perintah tidak dikenal, ketik BANTUAN");
  }
}
