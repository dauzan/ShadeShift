// Uji model pemilih susunan di ESP32: 12 kurva lab (sapuan 4S) dari data_uji.h.
// Unggah, buka Serial Monitor 115200. Hasil yang diharapkan: "LULUS 12/12" dan waktu per keputusan.
// pemilih.h dan pemilih_bobot.h harus ada di folder sketsa ini (salin dari edge_ai/pemilih/).
#include <Arduino.h>
#include "pemilih.h"
#include "data_uji.h"

static float bufV[N_MAKS_TITIK], bufI[N_MAKS_TITIK];
static float V201[PEMILIH_N], I201[PEMILIH_N];

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("# uji pemilih susunan SHADESHIFT");
  int lulus = 0; uint32_t total_us = 0, maks_us = 0;
  for (int t = 0; t < N_UJI; t++) {
    int n = UJI_N[t];
    for (int k = 0; k < n; k++) { bufV[k] = UJI_V[t][k]; bufI[k] = UJI_I[t][k]; }
    float f[PEMILIH_N_FITUR], skor[PEMILIH_N_KELAS];
    uint32_t t0 = micros();
    int ok = pemilih_cuplik_ulang(bufV, bufI, n, V201, I201);
    pemilih_fitur(V201, I201, f);
    int kelas = pemilih_putuskan(f, skor);
    uint32_t dt = micros() - t0; total_us += dt; if (dt > maks_us) maks_us = dt;
    float sel_maks = 0.0f;
    for (int j = 0; j < PEMILIH_N_FITUR; j++) {
      float d = fabsf(f[j] - UJI_FITUR[t][j]);
      if (d > sel_maks) sel_maks = d;
    }
    bool benar = (ok == 0) && (kelas == UJI_KEPUTUSAN[t]) && (sel_maks < 1e-4f);
    lulus += benar;
    Serial.printf("%-22s pilih %-4s (harap %-4s) selisih fitur %.2e  %lu us  %s\n", UJI_NAMA[t], PEMILIH_NAMA[kelas],
                  PEMILIH_NAMA[UJI_KEPUTUSAN[t]], sel_maks, (unsigned long)dt, benar ? "OK" : "GAGAL");
  }
  Serial.printf("# %s %d/%d | waktu rata-rata %lu us, maks %lu us (cuplik ulang + 14 fitur + model)\n",
                lulus == N_UJI ? "LULUS" : "GAGAL", lulus, N_UJI, (unsigned long)(total_us / N_UJI), (unsigned long)maks_us);
}

void loop() {}
