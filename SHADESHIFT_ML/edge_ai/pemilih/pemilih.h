// SHADESHIFT: pemilih susunan panel di ESP32 (C, float32, tanpa alokasi dinamis).
// Masukan: titik sapuan mentah (V, I) dari sapuan susunan 4S. Keluaran: 0 = 4S, 1 = 2S2P, 2 = TCT.
// Langkah sama persis dengan port_c.py (diverifikasi terhadap numpy/scipy/scikit-learn):
//   1) buang V <= 0, jepit I >= 0, urutkan menurut V, rata-ratakan I pada V kembar, cuplik ulang 201 titik merata
//   2) 14 fitur bentuk kurva (lihat SPESIFIKASI.md)
//   3) skor kelas = bias + bobot . (fitur - rerata) / skala ; pilih skor terbesar
// Memori kerja: sekitar 4 KB stack (larik 201 titik) + buffer masukan milik pemanggil (diurutkan di tempat).
#pragma once
#include <stdint.h>
#include "pemilih_bobot.h"

#define PEMILIH_N 201

static float pemilih_interp(float x, const float* X, const float* Y, int n) {
  if (x <= X[0]) return Y[0];
  if (x >= X[n - 1]) return Y[n - 1];
  int lo = 0, hi = n - 1;                       // j terbesar dengan X[j] <= x
  while (hi - lo > 1) { int mid = (lo + hi) / 2; if (X[mid] <= x) lo = mid; else hi = mid; }
  float dx = X[hi] - X[lo];
  if (dx <= 0.0f) return Y[hi];
  return Y[lo] + (Y[hi] - Y[lo]) * ((x - X[lo]) / dx);
}

// Langkah 1. V, I: buffer masukan (n titik), DIUBAH di tempat (diurutkan, dirapatkan). Vo, Io: 201 titik keluaran.
// Mengembalikan 0 bila sukses, -1 bila titik valid kurang dari 2.
static int pemilih_cuplik_ulang(float* V, float* I, int n, float* Vo, float* Io) {
  int m = 0;
  for (int k = 0; k < n; k++)                    // buang V <= 0, jepit I >= 0
    if (V[k] > 0.0f) { V[m] = V[k]; I[m] = I[k] > 0.0f ? I[k] : 0.0f; m++; }
  for (int a = 1; a < m; a++) {                  // urut sisipan (stabil)
    float kv = V[a], ki = I[a]; int b = a - 1;
    while (b >= 0 && V[b] > kv) { V[b + 1] = V[b]; I[b + 1] = I[b]; b--; }
    V[b + 1] = kv; I[b + 1] = ki;
  }
  int u = 0, a = 0;                              // V kembar: rata-rata I
  while (a < m) {
    int b = a; float s = 0.0f;
    while (b < m && V[b] == V[a]) { s += I[b]; b++; }
    V[u] = V[a]; I[u] = s / (float)(b - a); u++; a = b;
  }
  if (u < 2) return -1;
  float v0 = V[0], v1 = V[u - 1];
  for (int k = 0; k < PEMILIH_N; k++) {
    Vo[k] = v0 + (v1 - v0) * (float)k / (float)(PEMILIH_N - 1);
    Io[k] = pemilih_interp(Vo[k], V, I, u);
  }
  return 0;
}

// Puncak seperti scipy.signal.find_peaks(x, prominence=ambang). Mengembalikan jumlah puncak; h1, h2 = dua nilai tertinggi.
static int pemilih_puncak(const float* x, int n, float ambang, float* h1, float* h2) {
  int jml = 0; *h1 = 0.0f; *h2 = 0.0f;
  int i = 1;
  while (i < n - 1) {
    if (x[i - 1] < x[i]) {
      int ia = i + 1;
      while (ia < n - 1 && x[ia] == x[i]) ia++;
      if (x[ia] < x[i]) {
        int pk = (i + ia - 1) / 2;
        float kmin = x[pk], nmin = x[pk];
        for (int j = pk; j >= 0 && x[j] <= x[pk]; j--) if (x[j] < kmin) kmin = x[j];
        for (int j = pk; j <= n - 1 && x[j] <= x[pk]; j++) if (x[j] < nmin) nmin = x[j];
        float alas = kmin > nmin ? kmin : nmin;
        if (x[pk] - alas >= ambang) {
          jml++;
          float v = x[pk];
          if (v > *h1) { *h2 = *h1; *h1 = v; } else if (v > *h2) { *h2 = v; }
        }
        i = ia;
      }
    }
    i++;
  }
  return jml;
}

// Langkah 2. 14 fitur bentuk dari 201 titik. Urutan sama dengan PEMILIH_RERATA.
static void pemilih_fitur(const float* V, const float* I, float* f) {
  float P[PEMILIH_N], Ps[PEMILIH_N];
  int k = 0;
  for (int a = 0; a < PEMILIH_N; a++) { P[a] = V[a] * I[a]; if (P[a] > P[k]) k = a; }
  float Pmax = P[k], Voc = V[PEMILIH_N - 1], Isc = I[0];
  if (Pmax <= 0.0f || Isc <= 0.0f) { for (int j = 0; j < PEMILIH_N_FITUR; j++) f[j] = 0.0f; return; }
  for (int a = 0; a < PEMILIH_N; a++) {          // rata-rata bergerak 5 titik, tepi diisi nol (np.convolve 'same')
    float s = 0.0f;
    for (int b = a - 2; b <= a + 2; b++) if (b >= 0 && b < PEMILIH_N) s += P[b];
    Ps[a] = s / 5.0f;
  }
  float h1, h2;
  int npk = pemilih_puncak(Ps, PEMILIH_N, 0.02f * Pmax, &h1, &h2);
  f[0] = V[k] / Voc;                             // Vmp/Voc
  f[1] = I[k] / Isc;                             // Imp/Isc
  f[2] = Pmax / (Voc * Isc);                     // fill factor
  f[3] = (float)(npk > 1 ? npk : 1);             // jumlah puncak P-V
  f[4] = npk > 1 ? h2 / h1 : 0.0f;               // rasio puncak kedua
  for (int j = 1; j <= 9; j++) {                 // I pada 0,1..0,9 Voc dibagi Isc
    float fr = 0.1f * (float)j;
    f[4 + j] = pemilih_interp(fr * Voc, V, I, PEMILIH_N) / Isc;
  }
}

// Langkah 3. skor[3] diisi; mengembalikan kelas terpilih (0 = 4S, 1 = 2S2P, 2 = TCT).
static int pemilih_putuskan(const float* f, float* skor) {
  int terbaik = 0;
  for (int c = 0; c < PEMILIH_N_KELAS; c++) {
    float s = PEMILIH_BIAS[c];
    for (int j = 0; j < PEMILIH_N_FITUR; j++) s += PEMILIH_BOBOT[c][j] * ((f[j] - PEMILIH_RERATA[j]) / PEMILIH_SKALA[j]);
    skor[c] = s;
    if (s > skor[terbaik]) terbaik = c;
  }
  return terbaik;
}

static const char* const PEMILIH_NAMA[PEMILIH_N_KELAS] = {"4S", "2S2P", "TCT"};
