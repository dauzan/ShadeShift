"""Uji cepat dasbor (tanpa alat). Jalankan dari folder dasbor:  python uji_dasbor.py
1. Pemilih di dasbor = keputusan C pada 38 kurva lab 4S (referensi_lab_4S.csv).
2. Rugi pemilih dan susunan tetap pada 30 set lab = angka LAPORAN_UJI_FISIK.md (0,82 / 2,71 / 4,30 / 12,0%).
3. Alur ESP32 tiruan: pindah 4S, SWEEP, pemilih, pindah, SWEEP."""
import os
import numpy as np, pandas as pd
import inti, koneksi

W = inti.muat_bobot()
gagal = 0

ref = pd.read_csv(os.path.join(inti.PEMILIH, "referensi_lab_4S.csv"))
cocok = 0
for _, r in ref.iterrows():
    p = os.path.join(inti.DATA_LAB, r.berkas)
    if not os.path.exists(p): p = os.path.join(inti.DATA_LAB, "_V5_anomali_dioda", r.berkas)
    cocok += inti.pilih_susunan(inti.baca_berkas(p), W)[0] == r.keputusan_c
print(f"1. pemilih sama dengan C: {cocok}/{len(ref)}"); gagal += cocok != len(ref)

rows = []
for kond, ul in inti.daftar_kondisi().items():
    for u, f in ul.items():
        pm = {t: inti.baca_berkas(f[t]).pmax for t in inti.KELAS}; b = max(pm.values())
        pil = inti.pilih_susunan(inti.baca_berkas(f["4S"]), W)[0]
        rows.append([(b - pm[t]) / b * 100 for t in (pil, "2S2P", "TCT", "4S")])
rata = np.array(rows).mean(0).round(2)
print(f"2. {len(rows)} set lab, rugi rata-rata pemilih / tetap 2S2P / TCT / 4S: {rata.tolist()}")
gagal += len(rows) != 30 or not np.allclose(rata, [0.82, 2.71, 4.30, 12.0], atol=0.01)

k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V6_paranet65", lambat=0)
h = k.pilih_sekali(W)
print("3. alur tiruan V6_paranet65:", {x: h.get(x) for x in ("pilihan", "pmax_4S", "pmax_pilihan", "galat")}, "| susunan aktif:", k.topo)
gagal += bool(h.get("galat")) or k.topo != h.get("pilihan") or len(k.sapuan) != (1 if h["pilihan"] == "4S" else 2)
k.tutup()

print("SEMUA LULUS" if not gagal else f"GAGAL: {gagal}")
raise SystemExit(1 if gagal else 0)
