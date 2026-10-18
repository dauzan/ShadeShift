// Host simulation of firmware v3 (TEST ONLY). Build: g++ -std=c++17 -I<sketch> -I<this folder> sim_main.cpp
// Usage: sim.exe <4S.csv> <2S2P.csv> <TCT.csv> <4P.csv>  < script
// Script lines: "<t_ms> <command>" (sent when the simulated clock reaches t_ms). Output = the firmware's serial output,
// "##RX <line>" when the firmware reads a line, and a final "##SIM ..." line with the relay/DAC state.
#include "arduino_stub.h"
#include "shadeshift_firmware_v3.ino"

#include <fstream>
#include <iostream>
#include <sstream>

static uint64_t g_last_input_ms = 0;

static void tulis_akhir(const char* alasan) {
  int t = sim_topologi();
  std::printf("##SIM %s R0=%d topologi=%s dac=%d bench=%d t_ms=%llu\n", alasan, sim_relai(0) ? 1 : 0,
              t >= 0 ? SIM_NAMA[t] : "-", hw().dac, bench ? 1 : 0, (unsigned long long)(sim_us() / 1000));
  fflush(stdout);
}

void sim_delay_hook() {        // a firmware stuck waiting (e.g. for LANJUT) after the script ended: stop the simulation
  if (sim_input().empty() && sim_us() / 1000 > g_last_input_ms + 600000) { tulis_akhir("habis-waktu"); std::exit(0); }
}

static SimKurva baca_kurva(const char* path) {
  SimKurva k;
  std::ifstream f(path);
  std::string ln;
  std::vector<std::pair<double, double>> p;
  while (std::getline(f, ln)) {
    if (!ln.empty() && ln.back() == '\r') ln.pop_back();
    if (ln.rfind("#", 0) == 0) {
      size_t a = ln.find("Voc=");
      if (a != std::string::npos && ln.find("topologi=") != std::string::npos) k.voc = atof(ln.c_str() + a + 4);
      continue;
    }
    std::stringstream ss(ln); std::string a, b, c, d;
    if (!std::getline(ss, a, ',') || !std::getline(ss, b, ',') || !std::getline(ss, c, ',') || std::getline(ss, d, ',')) continue;
    char* e1; char* e2; double v = strtod(a.c_str(), &e1), i = strtod(b.c_str(), &e2);
    if (*e1 || *e2 || v <= 0) continue;
    p.push_back({v, std::max(i, 0.0)});
  }
  std::sort(p.begin(), p.end());
  for (auto& q : p) { if (!k.V.empty() && q.first == k.V.back()) continue; k.V.push_back(q.first); k.I.push_back(q.second); }
  if (k.voc <= 0 && !k.V.empty()) k.voc = k.V.back();
  k.ada = k.V.size() >= 2;
  return k;
}

int main(int argc, char** argv) {
  if (argc != 5) { std::fprintf(stderr, "usage: sim 4S.csv 2S2P.csv TCT.csv 4P.csv < script\n"); return 2; }
  for (int t = 0; t < 4; t++) hw().kurva[t] = baca_kurva(argv[t + 1]);
  std::string ln;
  while (std::getline(std::cin, ln)) {
    if (!ln.empty() && ln.back() == '\r') ln.pop_back();
    size_t sp = ln.find(' ');
    if (ln.empty() || sp == std::string::npos) continue;
    uint64_t t = std::strtoull(ln.substr(0, sp).c_str(), nullptr, 10);
    sim_input().push_back({t, ln.substr(sp + 1)});
    g_last_input_ms = std::max(g_last_input_ms, t);
  }
  setup();
  while (true) {
    loop();
    if (!Serial.available()) {
      if (sim_input().empty()) break;
      sim_us() = std::max(sim_us(), sim_input().front().t_ms * 1000);
    }
  }
  tulis_akhir("akhir");
  return 0;
}
