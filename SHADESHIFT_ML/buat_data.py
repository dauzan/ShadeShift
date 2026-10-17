"""Membangun data latih/uji. 'acak': skenario acak diperluas (S kontinu, jenis naungan per modul, jumlah sel
tertutup, iradiansi 30-1000 W/m2 (log-seragam) dengan ketidakcocokan antarmodul 0,85-1,10, suhu 15-65 C). 'grid': 625 kombinasi asli (G=1000, T=25) sebagai uji lain-sebaran."""
import sys, itertools, time, numpy as np, pandas as pd
from sim_core import *
from fitur import *

def baris(S, mode, nc, G, T, rng, label, f=None):
    tp, pw, ml = simulasi(S, mode, nc, G, T, f)
    r = dict(f_min=min(f) if f is not None else 1.0, S_A=S[0], S_B=S[1], S_C=S[2], S_D=S[3], G=G, T=T, mlpe=ml,
             n_tutup=sum(s > 0 for s in S), jenis="/".join(sorted(set(m for m, s in zip(mode, S) if s > 0))) or "-")
    for w in JENDELA:
        for t in TOPO: r[f"P_{w}_{t}"] = pw[w][t]
    for t in TOPO:
        V, I = sapuan(tp[t], rng)
        for n, v in zip(NAMA_FITUR, fitur(V, I)): r[f"{t}:{n}"] = v
    r["asal"] = label
    return r

def acak(n, seed, glo=30, ghi=1000, flo=0.85, fhi=1.1):
    rng = np.random.default_rng(seed); out = []
    for _ in range(n):
        k = rng.choice(5, p=[0.05, 0.35, 0.35, 0.15, 0.10])
        pos = rng.choice(4, k, replace=False)
        S = [0.0] * 4; mode = ["opak"] * 4; nc = [1] * 4
        for p in pos:
            S[p] = float(rng.uniform(10, 100)); mode[p] = rng.choice(["opak", "paranet"])
            nc[p] = int(rng.choice([1, 3, 6, 12]))
        out.append(baris(S, mode, nc, float(np.exp(rng.uniform(np.log(glo), np.log(ghi)))), float(rng.uniform(15, 65)), rng, "acak",
                        f=list(rng.uniform(flo, fhi, 4))))
    return out

def grid(seed=1):
    rng = np.random.default_rng(seed); out = []
    for m in ["opak", "paranet"]:
        for S in itertools.product([0, 30, 50, 80, 100], repeat=4):
            out.append(baris(list(map(float, S)), [m] * 4, [1] * 4, G_REF, T_REF, rng, "grid_" + m))
    return out

if __name__ == "__main__":
    t0 = time.time()
    pd.DataFrame(acak(int(sys.argv[1]), 42)).to_csv("data/sim_acak.csv", index=False)
    print("acak selesai", time.time() - t0)
    pd.DataFrame(grid()).to_csv("data/sim_grid625.csv", index=False)
    print("grid selesai", time.time() - t0)
