// Host stand-in for <Wire.h> (TEST ONLY): the ADS1115 (0x48) and MCP4725 (0x60) answer a scan.
#pragma once
#include "arduino_stub.h"
struct WireStub {
  uint8_t adres = 0;
  void begin(int, int) {}
  void beginTransmission(uint8_t a) { adres = a; }
  uint8_t endTransmission() { return (adres == 0x48 || adres == 0x60) ? 0 : 2; }
};
inline WireStub Wire;
