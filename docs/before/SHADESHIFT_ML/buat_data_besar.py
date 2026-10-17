import sys, time, numpy as np, pandas as pd
import modul_besar, sim_core as sc
import buat_data as bd
p = modul_besar.pasang()
m = sc.module_curve(p, sc.cell_irradiance(p, 0, "opak", 1, 1000.0), sc.I_GRID, 25.0)
P, V, I = m.pmax(); voc = float(np.interp(0.0, m.I, m.V))
print(f"modul sintetis: Pmp={P:.0f} W, Vmp={V:.1f} V, Imp={I:.2f} A, Voc={voc:.1f} V, Isc={float(np.interp(0.0, m.V[::-1], m.I[::-1])):.2f} A")
print("Voc topologi tanpa bayangan:", {k: round(v, 1) for k, v in sc.VOC_TOPO.items()})
t0 = time.time()
pd.DataFrame(bd.acak(int(sys.argv[1]), 7, 100, 1000, 0.92, 1.05)).to_csv("data/sim_acak_besar.csv", index=False)
pd.DataFrame(bd.grid()).to_csv("data/sim_grid625_besar.csv", index=False)
print("selesai", time.time() - t0)
