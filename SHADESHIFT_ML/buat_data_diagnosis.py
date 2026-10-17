"""Data diagnosis: 6 kelas penyebab. Fitur dari sapuan 201 titik tiap topologi (derau ukur). Dioda terbuka tanpa tegangan tembus balik (pendekatan)."""
import sys, time, numpy as np, pandas as pd
from sim_core import simulasi, TOPO, JENDELA
from fitur import sapuan, fitur, NAMA_FITUR
KELAS = ["normal", "bayangan sebagian", "redup merata", "dioda terbuka", "dioda hubung singkat", "hambatan seri naik"]

def skenario(c, rng):
    S = [0.0] * 4; mode = ["opak"] * 4; nc = [1] * 4; ubah = [{} for _ in range(4)]
    G = float(np.exp(rng.uniform(np.log(30), np.log(1000)))); T = float(rng.uniform(15, 65)); f = list(rng.uniform(0.9, 1.08, 4))
    if c == 1:
        for i in rng.choice(4, rng.integers(1, 4), replace=False): S[i] = rng.uniform(20, 100); nc[i] = int(rng.choice([1, 3, 6, 12]))
    elif c == 2:
        for i in rng.choice(4, rng.integers(1, 5), replace=False): S[i] = rng.uniform(15, 70); mode[i] = "paranet"
    elif c == 3:                                   # dioda terbuka pada modul yang terbayangi (kerusakan hanya tampak bila terbayangi)
        idx = rng.choice(4, rng.integers(1, 3), replace=False)
        for i in idx:
            S[i] = rng.uniform(30, 100); mode[i] = str(rng.choice(["opak", "paranet"])); nc[i] = int(rng.choice([1, 3, 6, 12])); ubah[i] = {"bypass": False}
    elif c == 4:
        ubah[rng.integers(4)] = {"bypass": "pendek"}
    elif c == 5:
        for i in rng.choice(4, rng.integers(1, 3), replace=False): ubah[i] = {"R_s": None, "k": float(rng.uniform(2, 6))}
    return S, mode, nc, G, T, f, ubah

def baris(c, rng):
    S, mode, nc, G, T, f, ubah = skenario(c, rng)
    from sim_core import PARAMS
    for i in range(4):
        if "k" in ubah[i]: ubah[i] = {"R_s": PARAMS[i]["R_s"] * ubah[i]["k"]}
    tp, pw, ml = simulasi(S, mode, nc, G, T, f, ubah)
    r = dict(kelas=c, G=G, T=T, mlpe=ml, **{f"P_W24_{t}": pw["W24"][t] for t in TOPO})
    for t in TOPO:
        V, I = sapuan(tp[t], rng)
        for n, v in zip(NAMA_FITUR, fitur(V, I)): r[f"{t}:{n}"] = v
    return r

if __name__ == "__main__":
    rng = np.random.default_rng(5); n = int(sys.argv[1]); out = []; t0 = time.time()
    for c in range(len(KELAS)):
        for _ in range(n): out.append(baris(c, rng))
        print(KELAS[c], round(time.time() - t0), "s", flush=True)
    pd.DataFrame(out).to_csv("data/diagnosis_sim.csv", index=False)
