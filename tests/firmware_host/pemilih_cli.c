// TEST ONLY: runs the firmware's pemilih.h (the exact C compiled into the ESP32) on curves read from stdin.
// Input per curve: "<n>\n" then n lines "<V> <I>". Output per curve: "<class> <s0> <s1> <s2> <f0> ... <f13>" or "-1".
#include <stdio.h>
#include "pemilih.h"

int main(void) {
  static float V[6000], I[6000];
  float Vo[PEMILIH_N], Io[PEMILIH_N], f[PEMILIH_N_FITUR], s[PEMILIH_N_KELAS];
  int n;
  while (scanf("%d", &n) == 1) {
    if (n < 0 || n > 6000) return 2;
    for (int i = 0; i < n; i++) if (scanf("%f %f", &V[i], &I[i]) != 2) return 3;
    if (pemilih_cuplik_ulang(V, I, n, Vo, Io) != 0) { printf("-1\n"); continue; }
    pemilih_fitur(Vo, Io, f);
    int k = pemilih_putuskan(f, s);
    printf("%d %.9g %.9g %.9g", k, s[0], s[1], s[2]);
    for (int j = 0; j < PEMILIH_N_FITUR; j++) printf(" %.9g", f[j]);
    printf("\n");
  }
  return 0;
}
