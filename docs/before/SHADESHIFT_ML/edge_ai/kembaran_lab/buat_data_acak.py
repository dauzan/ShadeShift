"""Data latih dengan domain randomization di sekitar kembaran lab (jalur B langkah 2). Tidak memakai kurva lab sama sekali.
Acak: G0 60-1000 (log), ketidakmerataan cahaya h 3-200 lebar sel (log; besar = merata), pusat +-3, sebaran antarsel 0-0,12,
suhu 15-65 C, pengali hambatan paralel 0,15-1,5 (log), faktor modul 0,85-1,10, derau ukur I 1% V 0,12%.
Kelas: 0 normal, 1 bayangan opak sebagian sel, 2 bayangan tembus cahaya (paranet) 1-4 modul, 3 dioda bypass terbuka (modul terbayangi),
4 dioda bypass hubung singkat, 5 hambatan seri naik (x2-6).
Jalankan dari SHADESHIFT_ML: python edge_ai/kembaran_lab/buat_data_acak.py <n_per_kelas> <seed> <keluaran.csv>"""
import os, sys, time
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_core as sc
from sim_core import PARAMS, module_curve
from fitur import sapuan, fitur, NAMA_FITUR
import cocokkan_lampu as K

TOPO = ["4S", "2S2P", "TCT", "4P"]


def satu(c, rng):
    G0 = float(np.exp(rng.uniform(np.log(60), np.log(1000)))); h = float(np.exp(rng.uniform(np.log(3), np.log(200))))
    cx, cy = rng.uniform(-3, 3, 2); sig = float(rng.uniform(0, 0.12)); T = float(rng.uniform(15, 65))
    ksh = float(np.exp(rng.uniform(np.log(0.15), np.log(1.5)))); fm = rng.uniform(0.85, 1.10, 4)
    par = [G0, h, cx, cy, sig]
    gs = [g * fm[m] for m, g in enumerate(K.g_sel(par, {}))]
    ubah = [{} for _ in range(4)]
    if c == 1:                                   # opak pada sebagian sel
        for m in rng.choice(4, rng.integers(1, 4), replace=False):
            n = int(rng.choice([1, 2, 3, 6, 12])); idx = rng.choice(36, n, replace=False); gs[m] = gs[m].copy(); gs[m][idx] *= rng.uniform(0.0, 0.3)
    elif c == 2:                                 # paranet seluruh modul
        for m in rng.choice(4, rng.integers(1, 5), replace=False): gs[m] = gs[m] * rng.uniform(0.05, 0.85)
    elif c == 3:                                 # dioda terbuka pada modul terbayangi (rusak hanya tampak bila terbayangi)
        for m in rng.choice(4, rng.integers(1, 3), replace=False):
            ubah[m] = {"bypass": False}
            if rng.random() < 0.5: gs[m] = gs[m] * rng.uniform(0.05, 0.85)
            else: n = int(rng.choice([1, 3, 6, 12])); idx = rng.choice(36, n, replace=False); gs[m] = gs[m].copy(); gs[m][idx] *= rng.uniform(0.0, 0.3)
    elif c == 4:
        ubah[rng.integers(4)] = {"bypass": "pendek"}
    elif c == 5:
        for m in rng.choice(4, rng.integers(1, 3), replace=False): ubah[m] = {"R_s": PARAMS[m]["R_s"] * float(rng.uniform(2, 6))}
    gs = [np.round(g, 2) for g in gs]
    ps = [{**PARAMS[i], "R_sh_ref": PARAMS[i]["R_sh_ref"] * ksh, **ubah[i]} for i in range(4)]
    imax = max(g.max() for g in gs) / 1000 * 0.65
    Ig = np.linspace(-0.3 * imax, 1.3 * imax, 3000)
    tp = K.topologi([module_curve(ps[i], gs[i], Ig, T) for i in range(4)], imax)
    r = dict(kelas=c, G0=G0, h=h, sigma=sig, T=T, k_sh=ksh)
    for t in TOPO:
        r[f"P_bebas_{t}"] = float(tp[t].pmax()[0]); r[f"P_W24_{t}"] = float(tp[t].pmax(30.0, 100.0)[0])
        V, I = sapuan(tp[t], rng)
        for n, v in zip(NAMA_FITUR, fitur(V, I)): r[f"{t}:{n}"] = v
        isc = I[0] if I[0] > 0 else 1.0                      # kurva mentah ternormalisasi untuk CNN: I/Isc pada 64 titik V/Voc
        for j, v in enumerate(np.interp(np.linspace(0, 1, 64) * V[-1], V, I) / isc): r[f"{t}~{j}"] = round(float(v), 5)
    return r


if __name__ == "__main__":
    n, seed, keluar = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    rng = np.random.default_rng(seed); rows = []; t0 = time.time()
    for c in range(6):
        for _ in range(n): rows.append(satu(c, rng))
        print("kelas", c, "%.0f s" % (time.time() - t0), flush=True)
    pd.DataFrame(rows).to_csv(keluar, index=False); print("tersimpan", keluar, len(rows))
