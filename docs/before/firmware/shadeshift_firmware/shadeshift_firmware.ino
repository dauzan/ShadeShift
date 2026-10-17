/*
  SHADESHIFT — firmware ESP32 (v2 final, 30-09-2026)
  Penjejak kurva I-V + pemilih topologi 4S / 2S2P / TCT / 4P.
  Suhu panel diukur manual pakai termometer tembak (tidak ada sensor suhu).

  Papan    : ESP32 Dev Module (DevKit V1 30 pin, WROOM-32)
  Pustaka  : Adafruit ADS1X15, Adafruit MCP4725
             (pasang lewat Arduino IDE > Tools > Manage Libraries)
  Serial   : 115200 baud, akhir baris "Newline"

  Perintah (ketik di Serial Monitor atau lewat logger_shadeshift.py):
    BANTUAN          daftar perintah
    SCAN             cari perangkat I2C (harus ada 0x48 dan 0x60/0x62)
    KAL              baca mentah ADC (untuk kalibrasi & offset)
    DAC <0-4095>     atur DAC manual (uji LM358; ukur keluarannya pakai multimeter)
    UJIRELAI         nyalakan relai satu per satu (HANYA TANPA PANEL)
    RELAI <0-10> <0|1>   nyalakan (1) / matikan (0) SATU relai manual, contoh: RELAI 6 1
                         (HANYA TANPA PANEL; ditolak kalau ada topologi aktif; OFF mematikan semua)
    4S | 2S2P | TCT | 4P   pindah topologi dengan urutan aman
    OFF / STOP       matikan semua (MOSFET mati, semua relai buka)
    VOC              baca tegangan array saat ini
    PANTAU 1|0       tampilkan tegangan array otomatis tiap 0,5 detik (0 = berhenti)
    SWEEP <label>    ukur kurva I-V, contoh: SWEEP V3_opak_4S_u1
    SIKLUS <label> <ulangan>   ukur SEMUA topologi, urutan diacak tiap putaran, tiap topologi = 1 SWEEP
                         contoh: SIKLUS V3_opak 3. Berhenti tiap putaran untuk catat suhu; ketik LANJUT / BATAL
    VPANEL <volt>    Voc satu panel saat ini (bawaan 21). Batas cek Voc = 0,5-1,2 x jumlah panel seri x nilai ini
    CEKVOC 0|1       matikan/nyalakan pengecekan Voc (0 = uji tanpa panel)
    STATUS           tampilkan keadaan
*/
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <Adafruit_MCP4725.h>

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

Adafruit_ADS1115 ads;
Adafruit_MCP4725 dac;
int  topoAktif = -1;
bool cekVoc = true;
bool r0Tutup = false;
float vPanel = 21.0;   // V, Voc satu panel pada cahaya saat ini (ubah lewat VPANEL)
bool pantau = false;
uint32_t tPantau = 0;

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
  Serial.println("# semua relai terbuka, MOSFET mati");
}

// ---------------- pindah topologi (urutan aman) ----------------
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

// ---------------- sweep kurva I-V ----------------
void sapuan(const String& label) {
  if (topoAktif < 0 || !r0Tutup) { Serial.println("# GAGAL: pilih topologi dulu (4S/2S2P/TCT/4P)"); return; }
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
  if (lo < 0) { Serial.println("# GAGAL: arus tidak terdeteksi. Cek sekring, R0, MOSFET, dan shunt."); return; }
  lo = max(0, lo - 96); hi = min(4095, hi + 32);
  delay(300);
  // 2) sweep halus
  Serial.printf("# MULAI %s\n", label.c_str());
  Serial.printf("# topologi=%s, Voc=%.3f V, dac=%d..%d, N=%u\n", TOPO[topoAktif].nama, voc, lo, hi, N_TITIK);
  Serial.println("V,I,P");
  Serial.printf("%.4f,%.5f,%.4f\n", voc, 0.0, 0.0);
  float pmaks = 0, vmp = 0, imp = 0;
  for (uint16_t k = 0; k < N_TITIK; k++) {
    uint16_t kode = lo + (uint32_t)(hi - lo) * k / (N_TITIK - 1);
    dacSet(kode); delay(4);
    float v = bacaV(2), i = bacaI(2);
    if (i < 0) i = 0;
    float p = v * i;
    if (p > pmaks) { pmaks = p; vmp = v; imp = i; }
    Serial.printf("%.4f,%.5f,%.4f\n", v, i, p);
  }
  dacSet(0);
  Serial.printf("# Pmax=%.4f W, Vmp=%.3f V, Imp=%.4f A\n", pmaks, vmp, imp);
  Serial.println("# catat suhu punggung panel A-D sesudah sweep (termometer tembak)");
  Serial.println("# SELESAI");
}

bool tungguLanjut(const char* pesan) {
  Serial.printf("# %s. Ketik LANJUT (atau BATAL).\n", pesan);
  while (true) {
    if (Serial.available()) {
      String t = Serial.readStringUntil('\n'); t.trim(); t.toUpperCase();
      if (t == "LANJUT") return true;
      if (t == "BATAL") return false;
    }
    delay(20);
  }
}

// ---------------- siklus: semua topologi, urutan acak, beberapa ulangan ----------------
void siklus(const String& arg) {
  String label = arg; int ulang = 3;
  int sp = arg.lastIndexOf(' ');
  if (sp > 0 && arg.substring(sp + 1).toInt() > 0) { ulang = arg.substring(sp + 1).toInt(); label = arg.substring(0, sp); }
  label.trim(); if (label.length() == 0) label = "siklus";
  if (topoAktif >= 0) semuaMati();
  if (!tungguLanjut("SIKLUS: ukur suhu punggung panel A-D (termometer tembak) sebelum mulai")) { Serial.println("# siklus dibatalkan"); return; }
  for (int u = 1; u <= ulang; u++) {
    int urut[4] = {0, 1, 2, 3};
    for (int i = 3; i > 0; i--) { int j = esp_random() % (i + 1); int t = urut[i]; urut[i] = urut[j]; urut[j] = t; }
    Serial.printf("# putaran %d/%d, urutan: %s %s %s %s\n", u, ulang, TOPO[urut[0]].nama, TOPO[urut[1]].nama, TOPO[urut[2]].nama, TOPO[urut[3]].nama);
    for (int k = 0; k < 4; k++) {
      if (!pindah(urut[k])) { Serial.println("# siklus dihentikan (topologi gagal)"); return; }
      delay(1500);
      sapuan(label + "_" + TOPO[urut[k]].nama + "_u" + String(u));
      if (topoAktif < 0) { Serial.println("# siklus dihentikan (sweep gagal)"); return; }
    }
    semuaMati();
    if (u < ulang && !tungguLanjut("catat suhu punggung panel A-D; bila bergeser >1 C dari awal, tunggu dingin dulu")) { Serial.println("# siklus dibatalkan"); return; }
  }
  Serial.println("# SIKLUS SELESAI, catat suhu akhir");
}

// ---------------- perintah lain ----------------
void scanI2C() {
  Serial.println("# scan I2C:");
  for (uint8_t a = 1; a < 127; a++) { Wire.beginTransmission(a); if (Wire.endTransmission() == 0) Serial.printf("#   ditemukan 0x%02X\n", a); }
}
void ujiRelai() {
  if (topoAktif >= 0) { Serial.println("# GAGAL: ketik OFF dulu"); return; }
  Serial.println("# UJI RELAI: pastikan PANEL TIDAK TERSAMBUNG. Tiap relai menyala 1 detik.");
  for (uint8_t i = 0; i <= 10; i++) {
    Serial.printf("#   R%u nyala (GPIO%u)\n", i, PIN_R[i]);
    setRelai(i, true); delay(1000); setRelai(i, false); delay(300);
  }
  Serial.println("# uji relai selesai");
}
void relaiManual(const String& arg) {
  if (topoAktif >= 0) { Serial.println("# GAGAL: ketik OFF dulu"); return; }
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
void kalibrasi() {
  ads.setGain(GAIN_ONE);   float a0 = ads.computeVolts(ads.readADC_SingleEnded(0));
  ads.setGain(GAIN_EIGHT); float d13 = ads.computeVolts(ads.readADC_Differential_1_3());
  Serial.printf("# A0=%.5f V -> V_array=%.3f V | A1-A3=%.6f V -> I=%.5f A\n",
                a0, a0 * (R_ATAS + R_BAWAH) / R_BAWAH, d13, d13 / R_SHUNT);
}
void status() {
  Serial.printf("# topologi=%s, R0=%s, cekVoc=%s\n",
                topoAktif < 0 ? "-" : TOPO[topoAktif].nama, r0Tutup ? "tutup" : "buka", cekVoc ? "ON" : "OFF");
}
void bantuan() {
  Serial.println("# Perintah: BANTUAN, SCAN, KAL, DAC <0-4095>, UJIRELAI, RELAI <0-10> <0|1>, 4S, 2S2P, TCT, 4P, OFF, VOC, PANTAU 1|0, SWEEP <label>, SIKLUS <label> <ulangan>, VPANEL <V>, CEKVOC 0|1, STATUS");
}

void setup() {
  for (uint8_t i = 0; i <= 10; i++) {           // tulis level MATI dulu, baru jadikan output -> relai tidak berkedip
    digitalWrite(PIN_R[i], RELAI_AKTIF_LOW ? HIGH : LOW);
    pinMode(PIN_R[i], OUTPUT);
  }
  Serial.begin(115200);
  delay(300);
  Wire.begin(21, 22);
  Serial.println("\n# SHADESHIFT firmware v2");
  if (!ads.begin(0x48)) Serial.println("# PERINGATAN: ADS1115 (0x48) tidak ditemukan");
  ads.setDataRate(RATE_ADS1115_860SPS);
  if (!dac.begin(0x60) && !dac.begin(0x62)) Serial.println("# PERINGATAN: MCP4725 (0x60/0x62) tidak ditemukan");
  dacSet(0);
  semuaMati();
  bantuan();
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
  else if (cmd == "SCAN") scanI2C();
  else if (cmd == "KAL") kalibrasi();
  else if (cmd == "DAC") { int k = arg.toInt(); dacSet(k); Serial.printf("# DAC=%d (keluaran LM358 harus ~%.2f V)\n", k, 6.6 * k / 4095.0); }
  else if (cmd == "UJIRELAI") ujiRelai();
  else if (cmd == "RELAI") relaiManual(arg);
  else if (cmd == "OFF" || cmd == "STOP") semuaMati();
  else if (cmd == "VOC") Serial.printf("# V_array = %.3f V\n", bacaV(16));
  else if (cmd == "PANTAU") { pantau = (arg != "0"); Serial.printf("# pantau %s\n", pantau ? "ON" : "OFF"); }
  else if (cmd == "SIKLUS") siklus(arg);
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
