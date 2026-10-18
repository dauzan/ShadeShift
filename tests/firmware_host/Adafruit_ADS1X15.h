// Host stand-in for Adafruit_ADS1X15 (TEST ONLY). A0 = array voltage through the 330k/10k divider,
// A1-A3 = shunt voltage (0.1 ohm). Each conversion costs 1.163 ms of simulated time (860 SPS single-shot).
#pragma once
#include "arduino_stub.h"
enum adsGain_t { GAIN_TWOTHIRDS, GAIN_ONE, GAIN_TWO, GAIN_FOUR, GAIN_EIGHT, GAIN_SIXTEEN };
#define RATE_ADS1115_860SPS 0x00E0
class Adafruit_ADS1115 {
 public:
  adsGain_t gain = GAIN_TWOTHIRDS;
  bool begin(uint8_t) { return true; }
  void setDataRate(uint16_t) {}
  void setGain(adsGain_t g) { gain = g; }
  double fsr() const { return gain == GAIN_ONE ? 4.096 : gain == GAIN_EIGHT ? 0.512 : 6.144; }
  int16_t konversi(double volt) {
    sim_us() += 1163;
    double c = std::round(volt / fsr() * 32768.0);
    return (int16_t)std::clamp(c, -32768.0, 32767.0);
  }
  int16_t readADC_SingleEnded(uint8_t) { double v, i; sim_titik(v, i); return konversi(v * 10000.0 / 340000.0); }
  int16_t readADC_Differential_1_3() { double v, i; sim_titik(v, i); return konversi(i * 0.1); }
  float computeVolts(int16_t c) { return (float)(c * fsr() / 32768.0); }
};
