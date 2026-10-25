// Host stand-in for the ESP32 WiFi library (TEST ONLY): records the access point instead of starting a radio.
#pragma once
#include "arduino_stub.h"
#define WIFI_OFF 0
#define WIFI_AP 2
struct IPAddress {
  String toString() const { return String("192.168.4.1"); }
};
struct WiFiStub {
  int mode_ = WIFI_OFF;
  void mode(int m) { mode_ = m; }
  bool softAP(const char* ssid, const char* pass) {
    bool ok = pass && std::strlen(pass) >= 8;             // the real ESP32 refuses WPA2 passwords shorter than 8
    std::printf("##WIFI AP %s %s\n", ssid, ok ? "ON" : "REFUSED");
    return ok;
  }
  IPAddress softAPIP() { return IPAddress(); }
  bool softAPdisconnect(bool) { std::printf("##WIFI OFF\n"); return true; }
};
inline WiFiStub WiFi;
