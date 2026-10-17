"""Eksperimen perbaikan model pemilih susunan (semua tetap kecil untuk ESP32).
Metrik utama sama dengan latih.py (sumber angka proposal): rugi = poin % daya MLPE yang hilang dibanding susunan terbaik,
hanya skenario dengan MLPE > 1 W. Data lab: rugi % terhadap susunan terbaik terukur (MLPE tidak diukur).
Pembagian simulasi sama dengan latih.py (permutasi seed 0, 75% latih). Jalankan dari folder SHADESHIFT_ML."""
import os, sys, glob, re, warnings
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.pipeline import make_pipeline
from sklearn.neural_network import MLPRegressor, MLPClassifier
from sklearn.ensemble import HistGradientBoostingRegressor
from fitur import NAMA_FITUR, fitur
warnings.filterwarnings("ignore")
H = os.path.dirname(os.path.abspath(__file__)); TOPO3 = ["4S", "2S2P", "TCT"]
BENTUK = [n for n in NAMA_FITUR if n not in ("Voc", "Isc", "Pmax")]; IB = [NAMA_FITUR.index(n) for n in BENTUK]
GRUP = {"V1": "V1", "V1b": "V1", "V1c": "V1c", "V3_opak": "V3o", "V3_paranet65": "V3p", "V3_paranet75": "V3p",
        "V4_paranet65": "V4", "V4_paranet75": "V4", "V6_paranet65": "V6", "V6_paranet75": "V6"}

acak = pd.read_csv("data/sim_acak.csv"); grid = pd.read_csv("data/sim_grid625.csv")
rng = np.random.default_rng(0); idx = rng.permutation(len(acak)); ntr = int(0.75 * len(acak))
tr, te = acak.iloc[idx[:ntr]], acak.iloc[idx[ntr:]]


def siap(df, ref):
    return df[[f"{ref}:{n}" for n in BENTUK]].values, df[[f"P_W24_{t}" for t in TOPO3]].values, df.mlpe.values


def rugi_poin(P, ml, pil):
    m = ml > 1.0; return (P.max(1) - P[np.arange(len(P)), pil])[m] / ml[m] * 100


# ---- data lab (fitur bentuk tiap susunan sapuan + daya tiap susunan)
def baca(path):
    rows = []
    for ln in open(path, encoding="utf8"):
        p = ln.strip().split(",")
        if ln.startswith("#") or len(p) != 3 or p[0] == "V": continue
        try: rows.append([float(x) for x in p[:2]])
        except ValueError: pass
    d = pd.DataFrame(rows, columns=["V", "I"]); d["I"] = d.I.clip(lower=0)
    d = d[d.V > 0].groupby("V", as_index=False).I.mean()
    V = np.linspace(d.V.min(), d.V.max(), 201); I = np.interp(V, d.V, d.I); return V, I


lab = {}
for f in glob.glob("data/data_lab/*.csv"):
    m = re.match(r"(.+)_(4S|2S2P|TCT|4P)_u(\d)\.csv$", os.path.basename(f))
    if not m or m.group(1) not in GRUP: continue
    V, I = baca(f); r = lab.setdefault((m.group(1), int(m.group(3))), {"kond": m.group(1)})
    r[f"P_{m.group(2)}"] = float((V * I).max()); r[f"F_{m.group(2)}"] = fitur(V, I)[IB]
lab = [r for r in lab.values() if all(f"P_{t}" in r for t in TOPO3)]


def lab_rugi(predict, ref):
    X = np.array([r[f"F_{ref}"] for r in lab]); P = np.array([[r[f"P_{t}"] for t in TOPO3] for r in lab])
    pil = predict(X); return (P.max(1) - P[np.arange(len(P)), pil]) / P.max(1) * 100, pil


# ---- kandidat: (nama, pembuat, jenis) ; jenis 'kelas' = klasifikasi, 'rasio' = regresi P_t/MLPE lalu argmax
def wbiaya(P, ml): return (P.max(1) - np.sort(P, 1)[:, -2]) / np.maximum(ml, 1) + 1e-3   # selisih terbaik vs kedua


KANDIDAT = [
    ("A. reg. logistik (sekarang)", lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)), "kelas", None),
    ("B. reg. logistik sensitif biaya", lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)), "kelas", "biaya"),
    ("C. reg. logistik sensitif biaya + kelas seimbang", lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, class_weight="balanced")), "kelas", "biaya"),
    ("D. regresi linear rasio daya (ridge)", lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)), "rasio", None),
    ("E. regresi kuadratik rasio daya (ridge, derajat 2)", lambda: make_pipeline(StandardScaler(), PolynomialFeatures(2), Ridge(alpha=3.0)), "rasio", None),
    ("F. MLP kecil rasio daya (14-16-16-3)", lambda: make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=(16, 16), max_iter=600, early_stopping=True, random_state=0)), "rasio", None),
    ("G. MLP kecil klasifikasi (14-16-16-3)", lambda: make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(16, 16), max_iter=600, early_stopping=True, random_state=0)), "kelas", None),
    ("Z. gradient boosting rasio (batas atas, tidak untuk ESP32)", lambda: HistGradientBoostingRegressor(max_iter=300, random_state=0), "rasio1", None),
]

rows = []
for ref in ["4S", "TCT"]:
    Xtr, Ptr, Mtr = siap(tr, ref); ytr = Ptr.argmax(1); Rtr = Ptr / np.maximum(Mtr, 1e-6)[:, None]
    for nama, buat, jenis, bobot in KANDIDAT:
        if jenis == "kelas":
            mdl = buat()
            kw = {}
            if bobot == "biaya": kw = {mdl.steps[-1][0] + "__sample_weight": wbiaya(Ptr, Mtr)}
            mdl.fit(Xtr, ytr, **kw); pred = lambda X, m=mdl: m.predict(X).astype(int)
        elif jenis == "rasio":
            mdl = buat().fit(Xtr, Rtr); pred = lambda X, m=mdl: m.predict(X).argmax(1)
        else:
            ms = [buat().fit(Xtr, Rtr[:, j]) for j in range(3)]; pred = lambda X, ms=ms: np.column_stack([m.predict(X) for m in ms]).argmax(1)
        Xte, Pte, Mte = siap(te, ref); Xg, Pg, Mg = siap(grid, ref)
        r_te = rugi_poin(Pte, Mte, pred(Xte)); r_g = rugi_poin(Pg, Mg, pred(Xg)); rl, pl = lab_rugi(pred, ref)
        rows.append(dict(sapuan=ref, model=nama, sim_rugi=r_te.mean(), sim_p95=np.percentile(r_te, 95), sim_tepat=(r_te < 0.5).mean() * 100,
                         grid_rugi=r_g.mean(), lab_rugi=rl.mean(), lab_maks=rl.max(), pilih_2S2P_sim=(pred(Xte) == 1).mean() * 100))
# pembanding
Xte, Pte, Mte = siap(te, "4S")
for nm, k in (("tetap 4S", 0), ("tetap 2S2P", 1), ("tetap TCT", 2)):
    r = rugi_poin(Pte, Mte, np.full(len(Pte), k)); rl, _ = lab_rugi(lambda X, k=k: np.full(len(X), k), "4S")
    rows.append(dict(sapuan="-", model=nm, sim_rugi=r.mean(), sim_p95=np.percentile(r, 95), sim_tepat=(r < 0.5).mean() * 100,
                     grid_rugi=rugi_poin(*siap(grid, "4S")[1:], np.full(len(grid), k)).mean(), lab_rugi=rl.mean(), lab_maks=rl.max(), pilih_2S2P_sim=100.0 * (k == 1)))
out = pd.DataFrame(rows).round(2); out.to_csv(os.path.join(H, "perbaiki_hasil.csv"), index=False)
pd.set_option("display.width", 240); pd.set_option("display.max_colwidth", 60)
print(out.to_string(index=False))
print("\nsim_* = poin %% MLPE (uji-tahan %d skenario), grid = 625 pola G=1000; lab_* = %% terhadap susunan terbaik (30 set, tidak dilatih)." % len(te))
