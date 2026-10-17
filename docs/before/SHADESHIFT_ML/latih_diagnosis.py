import numpy as np, pandas as pd, warnings, glob, os
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import confusion_matrix
from fitur import NAMA_FITUR, fitur
from buat_data_diagnosis import KELAS
from uji_fisik import baca
warnings.filterwarnings("ignore")
d = pd.read_csv("data/diagnosis_sim.csv"); rng = np.random.default_rng(0); idx = rng.permutation(len(d)); n = int(.75 * len(d))
tr, te = d.iloc[idx[:n]], d.iloc[idx[n:]]
BENTUK = [x for x in NAMA_FITUR if x not in ("Voc", "Isc", "Pmax")]
def M(nm):
    return {"pohon d=4": DecisionTreeClassifier(max_depth=4, random_state=0), "pohon d=6": DecisionTreeClassifier(max_depth=6, random_state=0),
            "reg. logistik": make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)),
            "hutan acak": RandomForestClassifier(300, random_state=0, n_jobs=-1)}[nm]
rows = []; best = None
for ref in ["TCT", "4S", "2S2P", "4P", "semua 4 sapuan"]:
    for fs, F in [("semua fitur", NAMA_FITUR), ("bentuk saja", BENTUK)]:
        cols = [f"{t}:{x}" for t in (["4S", "2S2P", "TCT", "4P"] if ref.startswith("semua") else [ref]) for x in F]
        for mn in ["pohon d=4", "pohon d=6", "reg. logistik", "hutan acak"]:
            m = M(mn).fit(tr[cols].values, tr.kelas.values); acc = (m.predict(te[cols].values) == te.kelas.values).mean() * 100
            rows.append(dict(sapuan=ref, fitur=fs, model=mn, akurasi=acc))
r = pd.DataFrame(rows); r.to_csv("hasil/diagnosis_ringkasan.csv", index=False)
pd.set_option("display.width", 200); print(r.pivot_table(index=["sapuan", "fitur"], columns="model", values="akurasi").round(1))
# matriks kebingungan: sapuan TCT, bentuk saja, pohon d=6 (model yang mungkin dipasang di alat) dan hutan acak sebagai batas
for ref, fs, mn in [("TCT", BENTUK, "pohon d=6"), ("TCT", BENTUK, "hutan acak")]:
    cols = [f"{ref}:{x}" for x in fs]; m = M(mn).fit(tr[cols].values, tr.kelas.values); p = m.predict(te[cols].values)
    cm = confusion_matrix(te.kelas.values, p); print(f"\nMatriks kebingungan ({ref}, bentuk saja, {mn}); baris = benar, kolom = tebakan; kelas: {KELAS}")
    print(pd.DataFrame(cm, index=KELAS, columns=[k[:8] for k in KELAS])); print("recall per kelas (%):", dict(zip(KELAS, (cm.diagonal() / cm.sum(1) * 100).round(0))))
# uji pada kurva fisik (V5 = bayangan tembus cahaya A dan C, dioda modul C tidak berfungsi)
FIS = {"V1c": 0, "V3_opak": 1, "V3_paranet65": 2, "V3_paranet75": 2, "V4_paranet65": 2, "V4_paranet75": 2, "V6_paranet65": 2, "V6_paranet75": 2, "V5_paranet65": 3, "V5_paranet75": 3}
cols = [f"TCT:{x}" for x in BENTUK]; mm = {mn: M(mn).fit(tr[cols].values, tr.kelas.values) for mn in ["pohon d=6", "reg. logistik", "hutan acak"]}
print("\nUji fisik (sapuan TCT, fitur bentuk): kondisi -> label benar -> tebakan per ulangan")
for k, lab in FIS.items():
    out = {mn: [] for mn in mm}
    for u in (1, 2, 3):
        pth = f"data/data_lab/{k}_TCT_u{u}.csv" if not k.startswith("V5") else f"data/data_lab/_V5_anomali_dioda/{k}_TCT_u{u}.csv"
        if not os.path.exists(pth): continue
        V, I = baca(pth); x = np.array([fitur(V, I)[NAMA_FITUR.index(b)] for b in BENTUK])[None]
        for mn, m in mm.items(): out[mn].append(KELAS[int(m.predict(x)[0])][:10])
    print(f"{k:14s} benar={KELAS[lab][:10]:10s}", {mn: v for mn, v in out.items()})
