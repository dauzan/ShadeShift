"""Kembaran digital kondisi lab (lampu halogen) - jalur B langkah 1.
Model cahaya per sel: sumber titik di atas susunan 2x2 (A kiri-atas, B kiri-bawah, C kanan-atas, D kanan-bawah; tiap modul
36 sel = 4 kolom x 9 baris), G(x,y) = G0 / (1 + (r/h)^2)^1.5, ditambah sebaran acak antarsel (sigma, pola tetap), suhu T,
dan pengali hambatan paralel k_sh. Tujuh parameter dicocokkan HANYA pada kurva V1c (tanpa bayangan, 4 susunan).
Uji ramalan: model lampu yang sama + bayangan nominal (opak = satu sel tertutup penuh; paranet = transmisi 0,70 dari Isc)
dibandingkan dengan kurva lab V3/V4/V6 yang tidak dipakai mencocokkan. Pembanding: simulator lama (cahaya merata, T = 25 C).
Jalankan dari folder SHADESHIFT_ML: python edge_ai/kembaran_lab/cocokkan_lampu.py"""
import os, sys, json, time
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
from scipy.optimize import minimize
import sim_core as sc
from sim_core import Curve, series, parallel, module_curve, PARAMS

H = os.path.dirname(os.path.abspath(__file__)); TOPO = ["4S", "2S2P", "TCT", "4P"]
KOLOM, BARIS = 4, 9
# pusat sel (satuan: lebar sel) pada susunan 8 x 18 sel; modul A (0..3, 0..8), B (0..3, 9..17), C (4..7, 0..8), D (4..7, 9..17)
POS = {0: (0, 0), 1: (0, 9), 2: (4, 0), 3: (4, 9)}
XY = {m: np.array([(POS[m][0] + c + 0.5, POS[m][1] + r + 0.5) for r in range(BARIS) for c in range(KOLOM)]) for m in range(4)}
PUSAT = np.array([4.0, 9.0])
ACAK = np.random.default_rng(7).standard_normal((4, 36))          # pola sebaran antarsel tetap


def baca(path):
    rows = []
    for ln in open(path, encoding="utf8"):
        p = ln.strip().split(",")
        if ln.startswith("#") or len(p) != 3 or p[0] == "V": continue
        try: rows.append([float(x) for x in p[:2]])
        except ValueError: pass
    d = pd.DataFrame(rows, columns=["V", "I"]); d["I"] = d.I.clip(lower=0)
    d = d[d.V > 0].groupby("V", as_index=False).I.mean(); return d.V.values, d.I.values


def lab_rata(kond):
    """Kurva lab rata-rata 3 ulangan per susunan, pada 120 titik tegangan merata."""
    out = {}
    for t in TOPO:
        cs = [baca(f"data/data_lab/{kond}_{t}_u{u}.csv") for u in (1, 2, 3)]
        voc = np.mean([c[0].max() for c in cs]); V = np.linspace(0.02 * voc, 0.98 * voc, 120)
        out[t] = (V, np.mean([np.interp(V, c[0], c[1]) for c in cs], axis=0), voc)
    return out


def topologi(mods, imax):
    """Seperti sim_core.topologies, tetapi kisi arus disesuaikan dengan arus kecil di lab."""
    A, B, C, D = mods; n = 3000
    I1 = np.linspace(-0.3 * imax, 1.3 * imax, n); I2 = np.linspace(-0.6 * imax, 2.6 * imax, n)
    V1 = np.linspace(-2.0, 1.05 * sc.VOC, n); V2 = np.linspace(-4.0, 2.10 * sc.VOC, n)
    return {"4S": series([A, B, C, D], I1), "2S2P": parallel([series([A, B], I1), series([C, D], I1)], V2),
            "TCT": series([parallel([A, C], V1), parallel([B, D], V1)], I2), "4P": parallel([A, B, C, D], V1)}


def g_sel(par, bayangan):
    """par: G0, h, cx, cy, sigma (log), T, k_sh. bayangan: {modul: ('paranet', transmisi)} atau {modul: ('opak', indeks_sel)}."""
    G0, h, cx, cy, sig = par[:5]
    gs = []
    for m in range(4):
        r = np.linalg.norm(XY[m] - (PUSAT + [cx, cy]), axis=1)
        g = G0 / (1 + (r / h) ** 2) ** 1.5 * np.exp(sig * ACAK[m])
        if m in bayangan:
            jenis, nilai = bayangan[m]
            if jenis == "paranet": g = g * nilai
            else: g = g.copy(); g[nilai] = g[nilai] * 0.02
        gs.append(np.round(g, 2))
    return gs


def simulasikan(par, bayangan, merata=False):
    G0, h, cx, cy, sig, T, ksh = par
    ps = [{**PARAMS[i], "R_sh_ref": PARAMS[i]["R_sh_ref"] * ksh} for i in range(4)]
    gs = g_sel(par, bayangan) if not merata else [np.full(36, G0) * (bayangan[m][1] if m in bayangan and bayangan[m][0] == "paranet" else 1.0) for m in range(4)]
    if merata:
        for m, (j, v) in bayangan.items():
            if j == "opak": gs[m] = gs[m].copy(); gs[m][v] *= 0.02
    imax = max(g.max() for g in gs) / 1000 * 0.65
    Ig = np.linspace(-0.3 * imax, 1.3 * imax, 3000)
    mods = [module_curve(ps[i], gs[i], Ig, T) for i in range(4)]
    return topologi(mods, imax)


def galat(tp, lab):
    """RMS selisih arus ternormalisasi Isc lab, rata-rata 4 susunan, ditambah penalti selisih Voc relatif."""
    e = []
    for t in TOPO:
        V, I, voc = lab[t]; Is = tp[t].I_of_V(V); isc = I[0]
        e.append(np.sqrt(np.mean(((Is - I) / isc) ** 2)) + abs(float(tp[t].V_of_I(0.0)) - voc) / voc)
    return float(np.mean(e))


def pmax_lab(lab): return {t: float((lab[t][0] * lab[t][1]).max()) for t in TOPO}
def pmax_sim(tp, lab): return {t: float((lab[t][0] * np.clip(tp[t].I_of_V(lab[t][0]), 0, None)).max()) for t in TOPO}


if __name__ == "__main__":
    t0 = time.time(); acuan = lab_rata("V1c")
    isc4p = acuan["4P"][1][0]; G_awal = 1000 * isc4p / 4 / 0.61                     # perkiraan G efektif dari Isc 4P
    awal = np.array([G_awal * 1.3, 8.0, 0.0, 0.0, 0.05, 45.0, 1.0])
    batas = [(10, 2000), (2, 60), (-6, 6), (-10, 10), (0.0, 0.4), (15, 85), (0.02, 3.0)]
    def f(p):
        p = np.array([min(max(v, lo), hi) for v, (lo, hi) in zip(p, batas)])
        try: return galat(simulasikan(p, {}), acuan)
        except Exception: return 9.0
    hasil = minimize(f, awal, method="Nelder-Mead", options=dict(maxiter=500, xatol=1e-3, fatol=1e-5))
    par = np.array([min(max(v, lo), hi) for v, (lo, hi) in zip(hasil.x, batas)])
    nama = ["G0", "h", "cx", "cy", "sigma", "T", "k_sh"]
    print("cocok V1c: galat %.4f -> %.4f (%d evaluasi, %.0f s)" % (f(awal), hasil.fun, hasil.nfev, time.time() - t0))
    print("parameter:", dict(zip(nama, np.round(par, 3))))
    # pembanding lama: cahaya merata, T 25 C, k_sh 1, G dicocokkan saja
    hm = minimize(lambda g: galat(simulasikan([g[0], 8, 0, 0, 0, 25.0, 1.0], {}, merata=True), acuan), [G_awal], method="Nelder-Mead")
    par_lama = [hm.x[0], 8, 0, 0, 0, 25.0, 1.0]
    print("simulator lama (merata, 25 C), G = %.0f W/m2, galat V1c %.4f" % (hm.x[0], hm.fun))

    # transmisi paranet dari SATU besaran fisik: rasio Isc susunan 4P (V3 paranet / V1c); tidak dicocokkan pada kurva
    def isc4p(tp): return float(tp["4P"].I_of_V(0.05))
    tau = {}
    for jenis in ("V3_paranet65", "V3_paranet75"):
        r_lab = lab_rata(jenis)["4P"][1][0] / acuan["4P"][1][0]; lo, hi = 0.02, 1.0
        for _ in range(25):
            mid = (lo + hi) / 2; r = isc4p(simulasikan(par, {0: ("paranet", mid)})) / isc4p(simulasikan(par, {}))
            lo, hi = (mid, hi) if r < r_lab else (lo, mid)
        tau[jenis[-2:]] = (lo + hi) / 2
    print("transmisi paranet dari rasio Isc 4P:", {k: round(v, 3) for k, v in tau.items()})
    t65, t75 = tau["65"], tau["75"]
    KOND = {"V1c": {}, "V3_opak": {0: ("opak", 4 * 4 + 1)}, "V3_paranet65": {0: ("paranet", t65)}, "V3_paranet75": {0: ("paranet", t75)},
            "V4_paranet65": {0: ("paranet", t65), 1: ("paranet", t65)}, "V4_paranet75": {0: ("paranet", t75), 1: ("paranet", t75)},
            "V6_paranet65": {0: ("paranet", t65), 3: ("paranet", t65)}, "V6_paranet75": {0: ("paranet", t75), 3: ("paranet", t75)}}
    rows = []
    for k, bay in KOND.items():
        lab = lab_rata(k); pl = pmax_lab(lab)
        for versi, p, mer in (("kembaran (baru)", par, False), ("simulator lama", par_lama, True)):
            tp = simulasikan(p, bay, merata=mer); ps = pmax_sim(tp, lab)
            urut_lab = max(["4S", "2S2P", "TCT"], key=lambda t: pl[t]); urut_sim = max(["4S", "2S2P", "TCT"], key=lambda t: ps[t])
            rows.append(dict(kondisi=k, versi=versi, galat_kurva=galat(tp, lab),
                             galat_Pmax_pct=np.mean([abs(ps[t] - pl[t]) / pl[t] * 100 for t in TOPO]),
                             terbaik_lab=urut_lab, terbaik_sim=urut_sim, cocok=urut_lab == urut_sim, dipakai_cocok=(k == "V1c")))
    df = pd.DataFrame(rows); df.to_csv(os.path.join(H, "uji_ramalan.csv"), index=False)
    pd.set_option("display.width", 220); print(df.round(3).to_string(index=False))
    print(df[~df.dipakai_cocok].groupby("versi")[["galat_kurva", "galat_Pmax_pct", "cocok"]].mean().round(3))
    json.dump(dict(zip(nama, map(float, par))), open(os.path.join(H, "parameter_lampu.json"), "w"), indent=1)
    # gambar: V1c dan satu kondisi bayangan
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, axs = plt.subplots(2, 4, figsize=(15, 6.5))
    for row, k in enumerate(["V1c", "V4_paranet65"]):
        lab = lab_rata(k); tpn = simulasikan(par, KOND[k]); tpl = simulasikan(par_lama, KOND[k], merata=True)
        for j, t in enumerate(TOPO):
            ax = axs[row, j]; V, I, voc = lab[t]
            ax.plot(V, I * 1000, "k-", lw=2, label="lab"); Vs = np.linspace(0, voc * 1.05, 300)
            ax.plot(Vs, np.clip(tpn[t].I_of_V(Vs), 0, None) * 1000, "-", color="#1F3A6E", label="kembaran")
            ax.plot(Vs, np.clip(tpl[t].I_of_V(Vs), 0, None) * 1000, "--", color="#9AA3AE", label="simulator lama")
            ax.set_title(f"{k} {t}", fontsize=10); ax.set_xlabel("V"); ax.set_ylabel("I (mA)")
            if row == 0 and j == 0: ax.legend(fontsize=8, frameon=False)
    fig.tight_layout(); fig.savefig(os.path.join(H, "kembaran_vs_lab.png"), dpi=110)
