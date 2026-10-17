"""Uji penentu jalur B: model dilatih HANYA pada data kembaran teracak (data/kembaran/kembaran_acak.csv), diuji pada kurva lab.
Diagnosis: label lab normal (V1, V1b, V1c) / opak (V3_opak) / paranet (V3, V4, V6 paranet) dipetakan ke kelas 0 / 1 / 2.
Pemilih: 4S / 2S2P / TCT, rugi % terhadap susunan terbaik terukur. V5 (dioda bermasalah) hanya eksplorasi.
Jalankan dari SHADESHIFT_ML: python edge_ai/kembaran_lab/uji_kembaran.py"""
import os, sys, glob, re, warnings
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import train_test_split
from fitur import NAMA_FITUR, fitur
warnings.filterwarnings("ignore")
H = os.path.dirname(os.path.abspath(__file__)); TOPO4 = ["4S", "2S2P", "TCT", "4P"]; TOPO3 = TOPO4[:3]
BENTUK = [n for n in NAMA_FITUR if n not in ("Voc", "Isc", "Pmax")]; IB = [NAMA_FITUR.index(n) for n in BENTUK]
KELAS = ["normal", "bayangan opak", "tembus cahaya", "dioda terbuka", "dioda hubung singkat", "hambatan seri naik"]
LAB = {"V1": 0, "V1b": 0, "V1c": 0, "V3_opak": 1, "V3_paranet65": 2, "V3_paranet75": 2, "V4_paranet65": 2, "V4_paranet75": 2,
       "V6_paranet65": 2, "V6_paranet75": 2, "V5_paranet65": 3, "V5_paranet75": 3}
out = []
def tulis(*a): s = " ".join(str(x) for x in a); print(s); out.append(s)


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
for f in glob.glob("data/data_lab/*.csv") + glob.glob("data/data_lab/_V5_anomali_dioda/*.csv"):
    m = re.match(r"(.+)_(4S|2S2P|TCT|4P)_u(\d)\.csv$", os.path.basename(f))
    if not m or m.group(1) not in LAB: continue
    V, I = baca(f); r = lab.setdefault((m.group(1), int(m.group(3))), {"kond": m.group(1), "y": LAB[m.group(1)]})
    r[f"P_{m.group(2)}"] = float((V * I).max()); r[f"F_{m.group(2)}"] = fitur(V, I)[IB]
lab = [r for r in lab.values() if all(f"F_{t}" in r for t in TOPO4)]
utama = [r for r in lab if r["y"] < 3]; v5 = [r for r in lab if r["y"] == 3]

d = pd.read_csv("data/kembaran/kembaran_acak.csv")
tr, te = train_test_split(d, test_size=0.2, random_state=0, stratify=d.kelas)
MODEL = {"reg. logistik": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000)),
         "MLP 32-32": lambda: make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(32, 32), max_iter=800, early_stopping=True, random_state=0)),
         "hutan acak": lambda: RandomForestClassifier(300, random_state=0, n_jobs=-1)}

tulis("=== Diagnosis: dilatih kembaran teracak (%d), diuji data kembaran tahan (%d) dan data lab (%d set) ===" % (len(tr), len(te), len(utama)))
rek = []
for sap in [["TCT"], ["4S"], TOPO4]:
    cols = [f"{t}:{n}" for t in sap for n in BENTUK]; xr = lambda r: np.concatenate([r[f"F_{t}"] for t in sap])
    for nm, mk in MODEL.items():
        m = mk().fit(tr[cols].values, tr.kelas.values)
        acc_k = (m.predict(te[cols].values) == te.kelas.values).mean() * 100
        Xl = np.array([xr(r) for r in utama]); yl = np.array([r["y"] for r in utama]); pl = m.predict(Xl)
        per = {k: f"{(pl[yl == i] == i).sum()}/{(yl == i).sum()}" for i, k in enumerate(["normal", "opak", "paranet"])}
        p5 = m.predict(np.array([xr(r) for r in v5])) if v5 else []
        rek.append(dict(sapuan="+".join(sap) if len(sap) < 4 else "4 sapuan", model=nm, akurasi_kembaran=round(acc_k, 1),
                        akurasi_lab=round((pl == yl).mean() * 100, 1), **{f"lab_{k}": v for k, v in per.items()},
                        V5_tebakan=", ".join(KELAS[int(x)][:12] for x in p5)))
R = pd.DataFrame(rek); pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80); tulis(R.to_string(index=False))
tulis("Pembanding (model simulasi lama yang sudah diperbaiki bug Voc): akurasi lab 3-13%, hampir semua ditebak 'bayangan'.")

tulis("\n=== Pemilih susunan: dilatih kembaran teracak, diuji lab (rugi %% terhadap susunan terbaik terukur) ===")
ok = d[[f"P_W24_{t}" for t in TOPO3]].max(1) > 0
dd = d[ok]
for sap in ["4S", "TCT"]:
    cols = [f"{sap}:{n}" for n in BENTUK]; y = dd[[f"P_W24_{t}" for t in TOPO3]].values.argmax(1)
    m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=4000)).fit(dd[cols].values, y)
    X = np.array([r[f"F_{sap}"] for r in utama]); P = np.array([[r[f"P_{t}"] for t in TOPO3] for r in utama]); pil = m.predict(X)
    rg = (P.max(1) - P[np.arange(len(P)), pil]) / P.max(1) * 100
    tulis("sapuan %-4s reg. logistik: rugi rata-rata %.2f%%, maks %.2f%%, tepat %.0f%%" % (sap, rg.mean(), rg.max(), (rg < 0.5).mean() * 100))
open(os.path.join(H, "uji_kembaran.txt"), "w", encoding="utf8").write("\n".join(out))
