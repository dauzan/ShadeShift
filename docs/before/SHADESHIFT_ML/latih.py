import numpy as np, pandas as pd, warnings
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from fitur import NAMA_FITUR
warnings.filterwarnings("ignore")
KELAS = ["4S", "2S2P", "TCT"]          # 4P gugur pada jendela 30-100 V (daya 0), jadi bukan kelas
acak = pd.read_csv("data/sim_acak.csv"); grid = pd.read_csv("data/sim_grid625.csv")

def siapkan(df, ref):
    X = df[[f"{ref}:{n}" for n in NAMA_FITUR]].values
    P = df[[f"P_W24_{t}" for t in KELAS]].values
    return X, P, df["mlpe"].values

def regret(P, ml, pilih):                 # poin % MLPE yang hilang dibanding pilihan optimal
    ok = P.max(1); got = P[np.arange(len(P)), pilih]
    m = ml > 1.0
    return ((ok - got)[m] / ml[m] * 100)

def ringkas(P, ml, pilih):
    r = regret(P, ml, pilih); m = ml > 1.0
    return dict(pct_mlpe=float((P[np.arange(len(P)), pilih][m] / ml[m]).mean() * 100), regret_rata=float(r.mean()),
                regret_p95=float(np.percentile(r, 95)), regret_maks=float(r.max()),
                tepat=float((r < 0.5).mean() * 100))

rng = np.random.default_rng(0); idx = rng.permutation(len(acak)); ntr = int(0.75 * len(acak))
tr, te = acak.iloc[idx[:ntr]], acak.iloc[idx[ntr:]]
MODEL = {
 "pohon d=2": lambda: DecisionTreeClassifier(max_depth=2, random_state=0),
 "pohon d=3": lambda: DecisionTreeClassifier(max_depth=3, random_state=0),
 "pohon d=4": lambda: DecisionTreeClassifier(max_depth=4, random_state=0),
 "pohon d=6": lambda: DecisionTreeClassifier(max_depth=6, random_state=0),
 "regresi logistik": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
 "kNN k=15": lambda: make_pipeline(StandardScaler(), KNeighborsClassifier(15)),
 "hutan acak (batas)": lambda: RandomForestClassifier(200, random_state=0, n_jobs=-1),
}
baris = []
for ref in ["4S", "2S2P", "TCT", "4P"]:
    Xtr, Ptr, Mtr = siapkan(tr, ref); ytr = Ptr.argmax(1)
    w = (Ptr.max(1) - Ptr.min(1)) / np.maximum(Mtr, 1) + 1e-3           # bobot: selisih daya antar kelas
    for nm, f in MODEL.items():
        mdl = f()
        try: mdl.fit(Xtr, ytr, **({"sample_weight": w} if "pohon" in nm or "hutan" in nm else {}))
        except TypeError: mdl.fit(Xtr, ytr)
        for uji, d in [("acak-uji", te), ("grid625", grid)]:
            X, P, ml = siapkan(d, ref)
            baris.append(dict(ref=ref, model=nm, uji=uji, **ringkas(P, ml, mdl.predict(X))))
df = pd.DataFrame(baris)
# pembanding tanpa model
for uji, d in [("acak-uji", te), ("grid625", grid)]:
    _, P, ml = siapkan(d, "4S")
    for nm, pil in [("tetap 4S", np.zeros(len(P), int)), ("tetap 2S2P", np.ones(len(P), int)), ("tetap TCT", np.full(len(P), 2)),
                    ("sapuan semua (batas atas)", P.argmax(1))]:
        df.loc[len(df)] = dict(ref="-", model=nm, uji=uji, **ringkas(P, ml, pil))
df.to_csv("hasil/langkah1_ringkasan.csv", index=False)
pd.set_option("display.width", 200); pd.set_option("display.max_rows", 200)
for uji in ["acak-uji", "grid625"]:
    print("\n=====", uji, "=====")
    print(df[df.uji == uji].drop(columns="uji").round(2).to_string(index=False))
