import glob, os, numpy as np, pandas as pd, warnings
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from fitur import NAMA_FITUR, fitur
warnings.filterwarnings("ignore")
KELAS = ["4S", "2S2P", "TCT"]
BENTUK = [n for n in NAMA_FITUR if n not in ("Voc", "Isc", "Pmax")]   # fitur tanpa skala mutlak (alih-daya, iradiansi)

def baca(path):
    rows = []
    for ln in open(path, encoding="utf8"):                     # baris rusak (jumlah kolom != 3) dibuang; berkas mentah tidak diubah
        p = ln.strip().split(",")
        if ln.startswith("#") or len(p) != 3 or p[0] == "V": continue
        rows.append([float(x) for x in p])
    d = pd.DataFrame(rows, columns=["V", "I", "P"]); d = d[d.V > 0].sort_values("V")
    V = np.linspace(d.V.min(), d.V.max(), 201); I = np.interp(V, d.V, d.I.clip(lower=0))
    return V, I

KOND = ["V1c", "V3_opak", "V3_paranet65", "V3_paranet75", "V4_paranet65", "V4_paranet75", "V6_paranet65", "V6_paranet75"]
fis = []
for k in KOND:
    for u in (1, 2, 3):
        row = dict(kond=k, u=u)
        for t in ["4S", "2S2P", "TCT", "4P"]:
            V, I = baca(f"data/data_lab/{k}_{t}_u{u}.csv"); row[f"P_{t}"] = (V * I).max()
            row[t] = fitur(V, I)
        fis.append(row)

def ambil(df, ref):
    return df[[f"{ref}:{n}" for n in BENTUK]].values
acak = pd.read_csv("data/sim_acak.csv")
Xcols = lambda ref: [f"{ref}:{n}" for n in BENTUK]
out = []
for ref in ["TCT", "4S"]:
    X = acak[Xcols(ref)].values; P = acak[[f"P_W24_{t}" for t in KELAS]].values; y = P.argmax(1)
    w = (P.max(1) - P.min(1)) / np.maximum(acak.mlpe.values, 1) + 1e-3
    for nm, mdl in [("pohon d=3", DecisionTreeClassifier(max_depth=3, random_state=0)),
                    ("regresi logistik", make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)))]:
        mdl.fit(X, y, **({"sample_weight": w} if "pohon" in nm else {}))
        for r in fis:
            Pm = np.array([r[f"P_{t}"] for t in KELAS])
            pil = int(mdl.predict(np.array([[*r[ref][[NAMA_FITUR.index(n) for n in BENTUK]]]]))[0])
            out.append(dict(ref=ref, model=nm, kond=r["kond"], u=r["u"], pilih=KELAS[pil], terbaik=KELAS[int(Pm.argmax())],
                            rugi_pct=(Pm.max() - Pm[pil]) / Pm.max() * 100))
df = pd.DataFrame(out); df.to_csv("hasil/uji_fisik_rinci.csv", index=False)
print(df.groupby(["ref", "model"]).agg(n=("u", "size"), tepat=("rugi_pct", lambda s: (s < 1).mean() * 100), rugi_rata=("rugi_pct", "mean"), rugi_maks=("rugi_pct", "max")).round(2))
t = pd.DataFrame(fis)
for k in KOND:
    s = t[t.kond == k]; print(k, {x: round(s[f"P_{x}"].mean(), 3) for x in ["4S", "2S2P", "TCT", "4P"]})
print("\nPembanding tetap (rugi vs terbaik-3-topologi, rata-rata 24 kurva):")
for tt in KELAS:
    print(tt, round(np.mean([(max(r[f"P_{x}"] for x in KELAS) - r[f"P_{tt}"]) / max(r[f"P_{x}"] for x in KELAS) * 100 for r in fis]), 2))
print(df[(df.ref == "TCT") & (df.model == "pohon d=3")].to_string(index=False))
