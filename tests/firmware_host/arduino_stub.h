// Host (laptop) stand-in for the Arduino/ESP32 APIs used by the firmware, plus a small hardware simulation.
// TEST ONLY: lets tests/test_firmware_v3.py compile the unchanged .ino with g++ and drive it with serial commands.
// The "hardware" replays a REAL lab I-V curve per topology: the relays decide which topology is wired, the DAC code
// moves the load point along that curve, and each ADS1115 read costs 1.16 ms (860 SPS) of simulated time.
// This proves the firmware logic and its output format; it is NOT a substitute for running on the real board.
#pragma once
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

#define HIGH 1
#define LOW 0
#define OUTPUT 1
using std::max;
using std::min;

// ---------------- String (subset of Arduino String) ----------------
class String {
 public:
  std::string s;
  String() {}
  String(const char* c) : s(c ? c : "") {}
  String(const std::string& x) : s(x) {}
  String(int v) : s(std::to_string(v)) {}
  String(unsigned int v) : s(std::to_string(v)) {}
  String(long v) : s(std::to_string(v)) {}
  String(unsigned long v) : s(std::to_string(v)) {}
  unsigned length() const { return (unsigned)s.size(); }
  const char* c_str() const { return s.c_str(); }
  void trim() {
    size_t a = s.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) { s.clear(); return; }
    size_t b = s.find_last_not_of(" \t\r\n");
    s = s.substr(a, b - a + 1);
  }
  void toUpperCase() { for (auto& c : s) c = (char)toupper((unsigned char)c); }
  int indexOf(char c) const { size_t p = s.find(c); return p == std::string::npos ? -1 : (int)p; }
  int lastIndexOf(char c) const { size_t p = s.rfind(c); return p == std::string::npos ? -1 : (int)p; }
  String substring(unsigned a) const { return a >= s.size() ? String() : String(s.substr(a)); }
  String substring(unsigned a, unsigned b) const { return a >= s.size() ? String() : String(s.substr(a, b - a)); }
  long toInt() const { return atol(s.c_str()); }
  float toFloat() const { return (float)atof(s.c_str()); }
  char operator[](unsigned i) const { return i < s.size() ? s[i] : 0; }
  bool operator==(const char* o) const { return s == o; }
  bool operator==(const String& o) const { return s == o.s; }
  bool operator!=(const char* o) const { return s != o; }
  String operator+(const String& o) const { return String(s + o.s); }
  String operator+(const char* o) const { return String(s + o); }
  String& operator+=(const String& o) { s += o.s; return *this; }
  String& operator+=(const char* o) { s += o; return *this; }
  String& operator+=(char c) { s += c; return *this; }
  void reserve(unsigned n) { s.reserve(n); }
};
inline String operator+(const char* a, const String& b) { return String(std::string(a) + b.s); }
inline bool isDigit(char c) { return c >= '0' && c <= '9'; }

// ---------------- simulated time ----------------
inline uint64_t& sim_us() { static uint64_t t = 0; return t; }
inline uint64_t host_us() {
  static auto t0 = std::chrono::steady_clock::now();
  return (uint64_t)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t0).count();
}
inline unsigned long millis() { return (unsigned long)(sim_us() / 1000); }
inline unsigned long micros() { return (unsigned long)(sim_us() + host_us()); }   // compute time is real host time
void sim_delay_hook();
// Script lines starting with "##" are simulation directives, applied when the simulated clock reaches their time.
void sim_proses_direktif();
inline void delay(unsigned long ms) { sim_us() += (uint64_t)ms * 1000; sim_delay_hook(); }

// ---------------- serial: scripted input "<t_ms> <line>", output to stdout ----------------
struct SimLine { uint64_t t_ms; std::string line; };
inline std::deque<SimLine>& sim_input() { static std::deque<SimLine> q; return q; }

struct SerialStub {
  void begin(long) {}
  void setTimeout(long) {}
  int available() {
    sim_proses_direktif();
    return !sim_input().empty() && sim_input().front().t_ms * 1000 <= sim_us();
  }
  String readStringUntil(char) {
    if (!available()) return String();
    std::string l = sim_input().front().line; sim_input().pop_front();
    std::printf("##RX %s\n", l.c_str());
    return String(l);
  }
  void println(const char* t = "") { std::printf("%s\n", t); fflush(stdout); }
  void println(const String& t) { println(t.c_str()); }
  void printf(const char* fmt, ...) __attribute__((format(printf, 2, 3))) {
    va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); fflush(stdout);
  }
};
inline SerialStub Serial;

// ---------------- hardware simulation ----------------
struct SimKurva { std::vector<double> V, I; double voc = 0; bool ada = false; };
struct SimHw {
  int pin_level[64];
  int dac = 0;
  double cahaya = 1.5;          // LDR voltage at ADS1115 A2 (firmware 3.2), set by "##CAHAYA <V>" script lines
  SimKurva kurva[8];            // 4S, 2S2P, TCT, 4P, then single panels A, B, C, D
  SimHw() { for (int& p : pin_level) p = HIGH; }
};
inline SimHw& hw() { static SimHw h; return h; }
static const uint8_t SIM_PIN_R[11] = {13, 16, 17, 18, 19, 23, 25, 26, 27, 32, 33};
inline bool sim_relai(int i) { return hw().pin_level[SIM_PIN_R[i]] == LOW; }      // relay modules are active LOW
inline const char* SIM_NAMA[8] = {"4S", "2S2P", "TCT", "4P", "A", "B", "C", "D"};

// What R1..R10 connect (independent of the firmware's own table): the 4 topologies from UNTUK_DAUZAN.md, and one
// panel alone between P and N from rangkaian/daftar_kabel.md (A: A+ fixed at P, R7 A- to N; B: R8 P-B+, R2 B- to N;
// C: R3 P-C+, R9 C- to N; D: R10 P-D+, D- fixed at N). -1 if none or a mix.
inline int sim_topologi() {
  static const int peta[8][10] = {
      {1, 0, 0, 1, 1, 0, 0, 0, 0, 0},   // 4S   = R1, R4, R5
      {1, 1, 1, 1, 0, 0, 0, 0, 0, 0},   // 2S2P = R1-R4
      {1, 1, 1, 1, 0, 1, 0, 0, 0, 0},   // TCT  = R1-R4, R6
      {0, 1, 1, 0, 0, 0, 1, 1, 1, 1},   // 4P   = R2, R3, R7-R10
      {0, 0, 0, 0, 0, 0, 1, 0, 0, 0},   // A    = R7
      {0, 1, 0, 0, 0, 0, 0, 1, 0, 0},   // B    = R2, R8
      {0, 0, 1, 0, 0, 0, 0, 0, 1, 0},   // C    = R3, R9
      {0, 0, 0, 0, 0, 0, 0, 0, 0, 1}};  // D    = R10
  for (int t = 0; t < 8; t++) {
    bool sama = true;
    for (int r = 1; r <= 10; r++) if (sim_relai(r) != (bool)peta[t][r - 1]) sama = false;
    if (sama) return t;
  }
  return -1;
}

// Operating point of the array: R0 open or DAC low -> open circuit (Voc, 0); otherwise along the lab curve.
inline void sim_titik(double& v, double& i) {
  int t = sim_topologi();
  v = 0; i = 0;
  if (t < 0 || !hw().kurva[t].ada) return;
  const SimKurva& k = hw().kurva[t];
  double s = sim_relai(0) ? std::clamp((hw().dac - 2000) / 320.0, 0.0, 1.0) : 0.0;
  v = k.voc * (1.0 - s);
  if (s <= 0) return;
  // interpolate I(V) on the ascending V grid
  if (v <= k.V.front()) { i = k.I.front(); return; }
  if (v >= k.V.back()) { i = 0; return; }
  size_t j = std::upper_bound(k.V.begin(), k.V.end(), v) - k.V.begin();
  double f = (v - k.V[j - 1]) / (k.V[j] - k.V[j - 1]);
  i = k.I[j - 1] + f * (k.I[j] - k.I[j - 1]);
}

inline void digitalWrite(uint8_t pin, int level) { hw().pin_level[pin] = level; }
inline void pinMode(uint8_t, int) {}
inline uint32_t esp_random() { static uint32_t x = 12345; x = x * 1103515245u + 12345u; return x >> 8; }
struct EspStub { uint64_t getEfuseMac() { return 0x0000A1B2C3D4E5F6ULL; } };
inline EspStub ESP;
