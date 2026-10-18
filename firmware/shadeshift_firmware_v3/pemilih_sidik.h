// SHADESHIFT: sidik (fingerprint) bobot pemilih = SHA-256 dari 73 float32 (little-endian) dengan urutan
// RERATA (14), SKALA (14), BOBOT (3 x 14, baris demi baris), BIAS (3). Sama persis dengan weights_sha256() di
// shadeshift/edge/selector.py, sehingga gateway bisa memeriksa bahwa ESP32 memakai bobot yang sama (CONTRACT.md §4).
// SHA-256 ditulis sendiri (C murni, tanpa pustaka) agar sama di ESP32 dan di laptop (uji: tests/test_firmware_v3.py).
#pragma once
#include <stdint.h>
#include <string.h>
#include "pemilih_bobot.h"

typedef struct { uint32_t h[8]; uint8_t buf[64]; uint64_t panjang; uint32_t n; } sidik_sha256_t;

static const uint32_t SIDIK_K[64] = {
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

#define SIDIK_ROTR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sidik_blok(sidik_sha256_t* s, const uint8_t* p) {
  uint32_t w[64], a, b, c, d, e, f, g, h;
  for (int i = 0; i < 16; i++) w[i] = ((uint32_t)p[4 * i] << 24) | ((uint32_t)p[4 * i + 1] << 16) | ((uint32_t)p[4 * i + 2] << 8) | p[4 * i + 3];
  for (int i = 16; i < 64; i++) {
    uint32_t s0 = SIDIK_ROTR(w[i - 15], 7) ^ SIDIK_ROTR(w[i - 15], 18) ^ (w[i - 15] >> 3);
    uint32_t s1 = SIDIK_ROTR(w[i - 2], 17) ^ SIDIK_ROTR(w[i - 2], 19) ^ (w[i - 2] >> 10);
    w[i] = w[i - 16] + s0 + w[i - 7] + s1;
  }
  a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3]; e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
  for (int i = 0; i < 64; i++) {
    uint32_t t1 = h + (SIDIK_ROTR(e, 6) ^ SIDIK_ROTR(e, 11) ^ SIDIK_ROTR(e, 25)) + ((e & f) ^ (~e & g)) + SIDIK_K[i] + w[i];
    uint32_t t2 = (SIDIK_ROTR(a, 2) ^ SIDIK_ROTR(a, 13) ^ SIDIK_ROTR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
    h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
  }
  s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d; s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void sidik_mulai(sidik_sha256_t* s) {
  static const uint32_t awal[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  memcpy(s->h, awal, sizeof(awal)); s->panjang = 0; s->n = 0;
}

static void sidik_tambah(sidik_sha256_t* s, const void* data, uint32_t len) {
  const uint8_t* p = (const uint8_t*)data;
  for (uint32_t i = 0; i < len; i++) {
    s->buf[s->n++] = p[i]; s->panjang++;
    if (s->n == 64) { sidik_blok(s, s->buf); s->n = 0; }
  }
}

static void sidik_selesai(sidik_sha256_t* s, uint8_t keluar[32]) {
  uint64_t bit = s->panjang * 8;
  uint8_t satu = 0x80, nol = 0;
  sidik_tambah(s, &satu, 1);
  while (s->n != 56) sidik_tambah(s, &nol, 1);
  uint8_t pj[8];
  for (int i = 0; i < 8; i++) pj[i] = (uint8_t)(bit >> (56 - 8 * i));
  sidik_tambah(s, pj, 8);
  for (int i = 0; i < 8; i++) { keluar[4 * i] = s->h[i] >> 24; keluar[4 * i + 1] = s->h[i] >> 16; keluar[4 * i + 2] = s->h[i] >> 8; keluar[4 * i + 3] = s->h[i]; }
}

// Tambahkan float sebagai 4 byte little-endian (ESP32 dan x86 sama-sama little-endian, tapi ditulis eksplisit).
static void sidik_tambah_float(sidik_sha256_t* s, const float* x, int n) {
  for (int k = 0; k < n; k++) {
    uint32_t u; memcpy(&u, &x[k], 4);
    uint8_t b[4] = {(uint8_t)u, (uint8_t)(u >> 8), (uint8_t)(u >> 16), (uint8_t)(u >> 24)};
    sidik_tambah(s, b, 4);
  }
}

// hex13: 12 karakter heksadesimal pertama dari SHA-256 + '\0' (sama dengan model_id "pemilih-logreg-v1@<12 hex>").
static void pemilih_sidik(char hex13[13]) {
  sidik_sha256_t s; uint8_t d[32];
  sidik_mulai(&s);
  sidik_tambah_float(&s, PEMILIH_RERATA, PEMILIH_N_FITUR);
  sidik_tambah_float(&s, PEMILIH_SKALA, PEMILIH_N_FITUR);
  for (int c = 0; c < PEMILIH_N_KELAS; c++) sidik_tambah_float(&s, PEMILIH_BOBOT[c], PEMILIH_N_FITUR);
  sidik_tambah_float(&s, PEMILIH_BIAS, PEMILIH_N_KELAS);
  sidik_selesai(&s, d);
  static const char HEX[] = "0123456789abcdef";
  for (int i = 0; i < 6; i++) { hex13[2 * i] = HEX[d[i] >> 4]; hex13[2 * i + 1] = HEX[d[i] & 15]; }
  hex13[12] = '\0';
}
