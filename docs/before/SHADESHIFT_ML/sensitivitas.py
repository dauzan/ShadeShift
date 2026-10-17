import numpy as np, pandas as pd, warnings
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from fitur import NAMA_FITUR
warnings.filterwarnings("ignore")
T4 = ["4S", "2S2P", "TCT", "4P"]; FT = [f"TCT:{n}" for n in NAMA_FITUR]
WIN = [("V12", "12 V (13-145 V)"), ("V24", "24 V (25-145 V)"), ("V48", "48 V (49-145 V)"), ("V48x", "48 V (49-245 V)")]
def P(d, w): return d[[f"P_{w}_{t}" for t in T4]].values
def pct(d, w, pil):
    m = d.mlpe.values > 1; return (P(d, w)[np.arange(len(d)), pil][m] / d.mlpe.values[m]).mean() * 100
rows = []
for modul, fa, fg in [("10 W", "data/sim_acak.csv", "data/sim_grid625.csv"), ("~415 W", "data/sim_acak_besar.csv", "data/sim_grid625_besar.csv")]:
    acak = pd.read_csv(fa); grid = pd.read_csv(fg)
    rng = np.random.default_rng(0); idx = rng.permutation(len(acak)); ntr = int(.75 * len(acak))
    tr, te = acak.iloc[idx[:ntr]], acak.iloc[idx[ntr:]]
    for w, V in WIN:
        Ptr = P(tr, w); wt = (Ptr.max(1) - Ptr.min(1)) / np.maximum(tr.mlpe.values, 1) + 1e-3
        mdls = {}
        for mn, mdl in [("pohon d=4", DecisionTreeClassifier(max_depth=4, random_state=0)),
                        ("reg. logistik", make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)))]:
            mdl.fit(tr[FT].values, Ptr.argmax(1), **({"sample_weight": wt} if "pohon" in mn else {})); mdls[mn] = mdl
        for nm, d in [("grid625", grid), ("acak-uji", te)]:
            p = P(d, w); r = {"modul": modul, "sistem": V, "data": nm}
            tetap = {t: pct(d, w, np.full(len(d), i)) for i, t in enumerate(T4)}
            bt = max(tetap, key=tetap.get); r["tetap terbaik"] = f"{bt} {tetap[bt]:.1f}"
            r["layak"] = "/".join(t for i, t in enumerate(T4) if p[:, i].max() > 0.1) or "-"
            r["adaptif"] = pct(d, w, p.argmax(1)); r["selisih"] = r["adaptif"] - tetap[bt]
            win = p.argmax(1)[(d.mlpe.values > 1) & (p.max(1) > 0.1)]
            r["optimal"] = ", ".join(f"{T4[i]} {np.mean(win == i) * 100:.0f}%" for i in range(4) if (win == i).any())
            for mn, mdl in mdls.items(): r[f"{mn} %MLPE"] = pct(d, w, mdl.predict(d[FT].values))
            rows.append(r)
df = pd.DataFrame(rows); df.to_csv("hasil/sensitivitas_12_24_48V.csv", index=False)
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30); pd.set_option("display.max_colwidth", 60)
print(df.round(1).to_string(index=False))
