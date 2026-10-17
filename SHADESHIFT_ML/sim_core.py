"""Inti simulasi SHADESHIFT (disalin dari SHADESHIFT_Tahap1_Simulasi_v7.ipynb, tanpa ekstraksi ulang
parameter: parameter dibaca dari data/shadeshift_parameter_final.csv). Folder ini terpisah dari berkas
naskah BREYI agar tidak mengganggu."""
import os
import numpy as np
import pandas as pd
from scipy.constants import k as kB, e as qe
from pvlib.pvsystem import calcparams_desoto, v_from_i

AQUI = os.path.dirname(os.path.abspath(__file__))
V_BYPASS, R_D = -0.5, 0.05
G_REF, T_REF = 1000.0, 25.0
# Jendela tegangan masukan pengendali (V). W24 = nilai asli proyek. V12/V24/V48 mengikuti rentang MPPT pada lembar data
# Victron SmartSolar 150/35 (13-145, 25-145, 49-145 V); V48x = kelas 250 V (asumsi 49-245 V). Topologi yang Voc-nya
# melampaui Vmax dianggap tidak layak (daya 0), karena merusak pengendali.
JENDELA = {"bebas": (-1e9, 1e9), "W24": (30.0, 100.0), "V12": (13.0, 145.0), "V24": (25.0, 145.0),
           "V48": (49.0, 145.0), "V48x": (49.0, 245.0)}
TOPO = ["4S", "2S2P", "TCT", "4P"]
ISC_DS = [0.60, 0.59, 0.62, 0.62]

_df = pd.read_csv(os.path.join(AQUI, "data", "shadeshift_parameter_final.csv"))
PARAMS = []
for (_, r), isc in zip(_df.iterrows(), ISC_DS):
    Ns = 36
    PARAMS.append(dict(I_L_ref=r.I_L, I_o_ref=r.I_0, R_s=r.R_s, R_sh_ref=r.R_sh,
                       a_ref=r.n * Ns * kB * (T_REF + 273.15) / qe, alpha_sc=0.0006 * isc,
                       EgRef=1.121, dEgdT=-0.0002677, Ns=Ns, N_GROUP=1))
ISC = max(ISC_DS)
VOC = 22.30
I_GRID = np.linspace(-0.3 * ISC, 1.3 * ISC, 4000)
VOC_TOPO = {t: 0.0 for t in ['4S', '2S2P', 'TCT', '4P']}


class Curve:
    def __init__(self, I, V):
        I = np.asarray(I, float); V = np.asarray(V, float)
        o = np.argsort(I, kind="stable"); I, V = I[o], V[o]
        I, idx = np.unique(I, return_index=True); V = V[idx]
        V = np.minimum.accumulate(V)
        V = V - 1e-12 * np.arange(len(V))
        self.I, self.V = I, V

    def V_of_I(self, q): return np.interp(q, self.I, self.V)

    def I_of_V(self, q):
        return np.interp(q, self.V[::-1], self.I[::-1])

    def pmax(self, vmin=-np.inf, vmax=np.inf):
        P = self.I * self.V; m = (self.V >= vmin) & (self.V <= vmax)
        if not m.any(): return 0.0, np.nan, np.nan
        k = int(np.flatnonzero(m)[np.argmax(P[m])]); return P[k], self.V[k], self.I[k]


def series(cs, Ig): return Curve(Ig, sum(c.V_of_I(Ig) for c in cs))
def parallel(cs, Vg): return Curve(sum(c.I_of_V(Vg) for c in cs), Vg)


def cell_V(p, G, Ig, T):
    IL, I0, Rs, Rsh, a = calcparams_desoto(max(G, 1e-9), T, p["alpha_sc"], p["a_ref"], p["I_L_ref"],
                                          p["I_o_ref"], p["R_sh_ref"], p["R_s"], EgRef=p["EgRef"], dEgdT=p["dEgdT"])
    N = p["Ns"]
    return Curve(Ig, v_from_i(Ig, IL, I0, Rs / N, Rsh / N, a / N)).V_of_I(Ig)


def module_curve(p, g_cells, Ig, T):
    """p['bypass']: True (normal), False (dioda pelewat terbuka/rusak), 'pendek' (dioda hubung singkat: modul selalu terlewati)."""
    byp = p.get("bypass", True)
    if byp == "pendek": return Curve(Ig, V_BYPASS - R_D * Ig)
    memo = {}; ng = p.get("N_GROUP", 1); npg = p["Ns"] // ng; gs = []
    for k in range(ng):
        V = 0.0
        for g in g_cells[k * npg:(k + 1) * npg]:
            if g not in memo: memo[g] = cell_V(p, g, Ig, T)
            V = V + memo[g]
        gs.append(Curve(Ig, np.maximum(V, V_BYPASS - R_D * Ig) if byp else V))   # satu dioda pelewat per kelompok sel
    return series(gs, Ig)


def cell_irradiance(p, S, mode, nc, G):
    """opak: nc sel pertama berkurang S% ; paranet: seluruh sel berkurang S% (merata)."""
    g = np.full(p["Ns"], float(G))
    if mode == "opak": g[:nc] = G * (1 - S / 100.0)
    elif mode == "paranet": g[:] = G * (1 - S / 100.0)
    return g


def topologies(mods, n=4000):
    A, B, C, D = mods
    I1 = np.linspace(-0.3 * ISC, 1.3 * ISC, n); I2 = np.linspace(-0.6 * ISC, 2.6 * ISC, n)
    V1 = np.linspace(-2.0, 1.05 * VOC, n);      V2 = np.linspace(-4.0, 2.10 * VOC, n)
    return {"4S": series([A, B, C, D], I1),
            "2S2P": parallel([series([A, B], I1), series([C, D], I1)], V2),
            "TCT": series([parallel([A, C], V1), parallel([B, D], V1)], I2),
            "4P": parallel([A, B, C, D], V1)}


def simulasi(S, mode, nc=None, G=G_REF, T=T_REF, f=None, ubah=None):
    """S, mode, nc: daftar 4 elemen (per modul). Kembalikan kurva 4 topologi + daya MLPE ideal."""
    nc = nc or [1] * 4
    f = f if f is not None else [1.0] * 4          # faktor ketidakcocokan iradiansi/arus antarmodul
    ubah = ubah or [{}] * 4                         # perubahan parameter per modul (gangguan): bypass, R_s
    ps = [{**PARAMS[i], **ubah[i]} for i in range(4)]
    mods = [module_curve(ps[i], cell_irradiance(ps[i], S[i], mode[i], nc[i], G * f[i]), I_GRID, T) for i in range(4)]
    tp = topologies(mods)
    mlpe = float(sum(m.pmax()[0] for m in mods))
    pw = {w: {t: (float(c.pmax(*JENDELA[w])[0]) if VOC_TOPO[t] <= JENDELA[w][1] else 0.0) for t, c in tp.items()} for w in JENDELA}
    return tp, pw, mlpe


def pasang_modul(params, isc, voc):
    """Ganti kumpulan modul (4 buah) dan hitung ulang skala grid serta Voc tiap topologi tanpa bayangan."""
    global ISC, VOC, I_GRID, VOC_TOPO
    PARAMS[:] = params; ISC, VOC = isc, voc
    I_GRID = np.linspace(-0.3 * ISC, 1.3 * ISC, 4000)
    VOC_TOPO = {t: 0.0 for t in TOPO}
    mods = [module_curve(PARAMS[i], cell_irradiance(PARAMS[i], 0, "opak", 1, G_REF), I_GRID, T_REF) for i in range(4)]
    VOC_TOPO = {t: float(np.interp(0.0, c.I, c.V)) for t, c in topologies(mods).items()}
    return VOC_TOPO


pasang_modul(PARAMS, ISC, VOC)
