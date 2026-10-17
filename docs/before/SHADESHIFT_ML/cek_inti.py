import time, numpy as np, pandas as pd
from sim_core import *
df = pd.read_csv("../_arsip/BREYI_2026/simulasi/shadeshift_625_final.csv")
rng = np.random.default_rng(0)
idx = rng.choice(len(df), 40, replace=False)
err = []; t0 = time.time()
for i in idx:
    r = df.iloc[i]
    S = [r.S_A, r.S_B, r.S_C, r.S_D]
    tp, pw, ml = simulasi(S, [r.jenis_naungan]*4)
    for t in TOPO:
        err.append(abs(pw["bebas"][t]-r[t])); 
    err.append(abs(ml-r.mlpe_ideal))
    for t in TOPO: err.append(abs(pw["W24"][t]-r[t+"_W24"]))
print("selisih maks vs CSV (W):", max(err), " waktu/skenario: %.3f s" % ((time.time()-t0)/40))
