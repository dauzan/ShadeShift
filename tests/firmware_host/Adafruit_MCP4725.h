// Host stand-in for Adafruit_MCP4725 (TEST ONLY): the DAC code sets the simulated load point.
#pragma once
#include "arduino_stub.h"
class Adafruit_MCP4725 {
 public:
  bool begin(uint8_t a) { return a == 0x60; }
  bool setVoltage(uint16_t kode, bool) { hw().dac = kode; return true; }
};
