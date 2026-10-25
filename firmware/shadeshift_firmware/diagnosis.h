// SHADESHIFT: diagnosis penyebab (6 kelas) di ESP32 (C, float32, tanpa alokasi dinamis). docs/CONTRACT.md §15-16.
// Model: diagnosis_model.h, dibuat halaman Model AI (aktifkan model diagnosis -> berkas ditulis ke folder ini). Tanpa berkas
// itu DIAG_ADA = 0 dan perintah DIAG menjawab bahwa model belum dipasang (firmware tetap bisa dikompilasi).
// Masukan 59 angka, urutan sama dengan shadeshift/training/dataset.py ROUND_FEATURES:
//   14 fitur bentuk (pemilih_fitur) sapuan 4S, 2S2P, TCT, 4P, lalu Pmax 2S2P/4S, TCT/4S, 4P/4S
//   (Pmax = maksimum V*I pada kurva 201 titik hasil pemilih_cuplik_ulang, sama dengan laptop).
#pragma once
#include <math.h>

#define DIAG_N_KELAS_SEMUA 6
static const char* const DIAG_NAMA[DIAG_N_KELAS_SEMUA] = {"normal", "partial_shading", "uniform_dimming",
                                                          "bypass_open", "bypass_short", "series_resistance"};

#if __has_include("diagnosis_model.h")
#include "diagnosis_model.h"
#define DIAG_ADA 1
#else
#define DIAG_ADA 0
#endif

#if DIAG_ADA
// Mengembalikan indeks kelas (0..5, urutan DIAG_NAMA); *yakin = peluang (regresi logistik) atau porsi daun (pohon).
static int diag_putuskan(const float* x, float* yakin) {
#ifdef DIAG_N_KELAS
  float s[DIAG_N_KELAS];
  int b = 0;
  for (int c = 0; c < DIAG_N_KELAS; c++) {
    float v = DIAG_BIAS[c];
    for (int j = 0; j < DIAG_N_FITUR; j++) v += DIAG_BOBOT[c][j] * ((x[j] - DIAG_RERATA[j]) / DIAG_SKALA[j]);
    s[c] = v;
    if (v > s[b]) b = c;
  }
  float z = 0.0f;
  for (int c = 0; c < DIAG_N_KELAS; c++) z += expf(s[c] - s[b]);
  *yakin = 1.0f / z;
  return DIAG_KELAS[b];
#else
  int n = 0;
  while (DIAG_FITUR[n] >= 0) n = (x[DIAG_FITUR[n]] <= DIAG_AMBANG[n]) ? DIAG_KIRI[n] : DIAG_KANAN[n];
  *yakin = DIAG_YAKIN[n];
  return DIAG_DAUN[n];
#endif
}
#endif
