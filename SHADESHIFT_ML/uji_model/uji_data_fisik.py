"""Uji model pada kurva I-V fisik (lampu halogen). Jalankan dari folder SHADESHIFT_ML: python uji_model/uji_data_fisik.py
A. Selisih domain: posisi fitur bentuk kurva lab terhadap sebaran simulasi kelas yang sama.
B. Pemilihan susunan (4S, 2S2P, TCT; 4P gugur di jendela 24 V): pembagian leave-one-condition-out (ketiga ulangan satu
   kondisi selalu keluar bersama). Metrik: rugi daya (%) terhadap susunan terbaik terukur.
C. Diagnosis pada label yang ada di data lab: normal / bayangan opak / bayangan tembus cahaya (paranet).
   V5 (dioda bypass modul C tampak tidak berfungsi) hanya uji eksplorasi; labelnya tidak pasti.
Berkas mentah tidak diubah; baris rusak (jumlah kolom != 3) dibuang saat dibaca."""
import os, sys, glob, re, warnings
sys.path.insert(0, os.getcwd())
import numpy as np, pandas as pd
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from fitur import NAMA_FITUR, fitur
warnings.filterwarnings("ignore")
OUT = "uji_model/hasil"; os.makedirs(OUT, exist_ok=True)
TOPO3 = ["4S", "2S2P", "TCT"]; TOPO4 = TOPO3 + ["4P"]
BENTUK = [n for n in NAMA_FITUR if n not in ("Voc", "Isc", "Pmax")]          # fitur tanpa skala mutlak
IB = [NAMA_FITUR.index(n) for n in BENTUK]
LAB = {"V1": "normal", "V1b": "normal", "V1c": "normal", "V3_opak": "opak", "V3_paranet65": "paranet", "V3_paranet75": "paranet",
       "V4_paranet65": "paranet", "V4_paranet75": "paranet", "V6_paranet65": "paranet", "V6_paranet75": "paranet"}
# kelompok pola untuk pembagian data: kondisi kembar (V1/V1b; paranet 65%/75% dengan bayangan efektif sama) keluar bersama
GRUP = {"V1": "V1+V1b", "V1b": "V1+V1b", "V1c": "V1c", "V3_opak": "V3 opak", "V3_paranet65": "V3 paranet", "V3_paranet75": "V3 paranet",
        "V4_paranet65": "V4 paranet", "V4_paranet75": "V4 paranet", "V6_paranet65": "V6 paranet", "V6_paranet75": "V6 paranet"}
SIMK = {"normal": 0, "opak": 1, "paranet": 2}                                 # kelas simulasi: 0 normal, 1 bayangan (opak), 2 "redup merata" (= paranet)
KELAS_SIM = ["normal", "bayangan sebagian", "tembus cahaya", "dioda terbuka", "dioda hubung singkat", "hambatan seri naik"]
lines = []
def tulis(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)


def baca(path):
    rows = []
    for ln in open(path, encoding="utf8"):
        p = ln.strip().split(",")
        if ln.startswith("#") or len(p) != 3 or p[0] == "V": continue
        try: rows.append([float(x) for x in p])
        except ValueError: continue
    d = pd.DataFrame(rows, columns=["V", "I", "P"]); d["I"] = d.I.clip(lower=0)
    d = d[d.V > 0].groupby("V", as_index=False).I.mean()                      # V kembar: rata-rata I (urutan tidak lagi acak)
    V = np.linspace(d.V.min(), d.V.max(), 201); I = np.interp(V, d.V, d.I)
    return V, I


# ---------------- muat kurva lab: satu baris = satu (kondisi, ulangan) dengan keempat susunan
def muat(pola, kond_label):
    out = []
    for f in sorted(glob.glob(pola)):
        m = re.match(r"(.+)_(4S|2S2P|TCT|4P)_u(\d)\.csv$", os.path.basename(f))
        if m: out.append((m.group(1), m.group(2), int(m.group(3)), f))
    rows = {}
    for k, t, u, f in out:
        if k not in kond_label: continue
        V, I = baca(f); r = rows.setdefault((k, u), dict(kond=k, u=u, label=kond_label[k]))
        r[f"P_{t}"] = float((V * I).max()); r[f"F_{t}"] = fitur(V, I)
    return [r for r in rows.values() if all(f"F_{t}" in r for t in TOPO4)]


lab = muat("data/data_lab/*.csv", LAB)
v5 = muat("data/data_lab/_V5_anomali_dioda/*.csv", {"V5_paranet65": "dioda?", "V5_paranet75": "dioda?"})
tulis("Kurva lab: %d (kondisi, ulangan) x 4 susunan = %d kurva; kondisi: %d. V5 (eksplorasi): %d set." % (len(lab), 4 * len(lab), len({r['kond'] for r in lab}), len(v5)))

sim_d = pd.read_csv("data/diagnosis_sim.csv"); sim_a = pd.read_csv("data/sim_acak.csv")
cols = lambda ref: [f"{ref}:{n}" for n in BENTUK]
fb = lambda r, ref: r[f"F_{ref}"][IB]

# ================= A. selisih domain
tulis("\n=== A. Selisih domain (sapuan TCT, fitur bentuk): persentil nilai lab di dalam sebaran simulasi kelas yang sama ===")
recA = []
for lb, kc in SIMK.items():
    S = sim_d[sim_d.kelas == kc][cols("TCT")].values
    L = np.array([fb(r, "TCT") for r in lab if r["label"] == lb])
    for j, n in enumerate(BENTUK):
        pct = [(S[:, j] < x).mean() * 100 for x in L[:, j]]
        recA.append(dict(label=lb, fitur=n, lab_median=np.median(L[:, j]), sim_p5=np.percentile(S[:, j], 5), sim_p50=np.median(S[:, j]),
                         sim_p95=np.percentile(S[:, j], 95), persentil_lab_median=np.median(pct), luar_rentang_pct=np.mean([(p < 2.5) or (p > 97.5) for p in pct]) * 100))
A = pd.DataFrame(recA); A.to_csv(f"{OUT}/A_selisih_domain.csv", index=False)
pd.set_option("display.width", 220)
tulis(A.pivot_table(index="fitur", columns="label", values="luar_rentang_pct").round(0).to_string())
tulis("(angka = %% kurva lab yang berada di luar 95%% sebaran simulasi kelasnya; tinggi = selisih domain besar)")

# ================= B. pemilihan susunan
tulis("\n=== B. Pemilihan susunan di antara 4S, 2S2P, TCT (leave-one-pattern-out: 6 kelompok pola) ===")
P = lambda r: np.array([r[f"P_{t}"] for t in TOPO3])
def rugi(r, i): p = P(r); return (p.max() - p[i]) / p.max() * 100
kond = sorted({r["kond"] for r in lab}); grup = sorted(set(GRUP.values()))
hasilB = []
# pembanding tetap
for i, t in enumerate(TOPO3): hasilB += [dict(metode=f"tetap {t}", kond=r["kond"], u=r["u"], rugi=rugi(r, i)) for r in lab]
# model dilatih simulasi (seperti uji lama), sapuan 4S dan TCT
for ref in ["4S", "TCT"]:
    X = sim_a[cols(ref)].values; Ps = sim_a[[f"P_W24_{t}" for t in TOPO3]].values; y = Ps.argmax(1)
    w = (Ps.max(1) - Ps.min(1)) / np.maximum(sim_a.mlpe.values, 1) + 1e-3
    for nm, m in [("pohon d=3", DecisionTreeClassifier(max_depth=3, random_state=0)), ("reg. logistik", make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)))]:
        m.fit(X, y, **({"sample_weight": w} if "pohon" in nm else {}))
        for r in lab: hasilB.append(dict(metode=f"simulasi, {nm}, sapuan {ref}", kond=r["kond"], u=r["u"], rugi=rugi(r, int(m.predict([fb(r, ref)])[0]))))
# model dilatih data lab, leave-one-condition-out
for ref in ["4S", "TCT"]:
    for nm, mk in [("pohon d=2", lambda: DecisionTreeClassifier(max_depth=2, random_state=0)),
                   ("reg. logistik", lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=0.5)))]:
        for g in grup:
            tr = [r for r in lab if GRUP[r["kond"]] != g]; te = [r for r in lab if GRUP[r["kond"]] == g]
            ytr = np.array([int(P(r).argmax()) for r in tr])
            if len(set(ytr)) == 1: pred = [ytr[0]] * len(te)
            else: m = mk().fit(np.array([fb(r, ref) for r in tr]), ytr); pred = m.predict(np.array([fb(r, ref) for r in te]))
            hasilB += [dict(metode=f"lab per pola, {nm}, sapuan {ref}", kond=r["kond"], u=r["u"], rugi=rugi(r, int(p))) for r, p in zip(te, pred)]
# sapu ketiga susunan lalu pilih yang terbesar (batas atas, butuh 3 sapuan)
hasilB += [dict(metode="sapu 3 susunan, pilih terbesar", kond=r["kond"], u=r["u"], rugi=0.0) for r in lab]
B = pd.DataFrame(hasilB); B.to_csv(f"{OUT}/B_pemilihan_rinci.csv", index=False)
ringB = B.groupby("metode").agg(rugi_rata=("rugi", "mean"), rugi_maks=("rugi", "max"), tepat_pct=("rugi", lambda s: (s < 0.5).mean() * 100)).round(2).sort_values("rugi_rata")
ringB.to_csv(f"{OUT}/B_pemilihan_ringkas.csv"); tulis(ringB.to_string())
tulis("(n = %d set dari %d kondisi = %d pola independen; 'tepat' = rugi < 0,5%%. Ulangan dan kondisi kembar saling berkorelasi.)" % (len(lab), len(kond), len(grup)))
tulis("Susunan terbaik terukur per kondisi (rata-rata ulangan):")
for k in kond:
    pm = np.mean([P(r) for r in lab if r["kond"] == k], axis=0); tulis("  %-14s %s  terbaik %s" % (k, np.round(pm, 3), TOPO3[int(pm.argmax())]))

# ================= C. diagnosis
tulis("\n=== C. Diagnosis pada label data lab (normal / opak / paranet) ===")
recC = []
for ref in ["TCT", "semua 4 sapuan"]:
    rr = TOPO4 if ref.startswith("semua") else [ref]
    Xs = sim_d[[f"{t}:{n}" for t in rr for n in BENTUK]].values; ys = sim_d.kelas.values
    xr = lambda r: np.concatenate([r[f"F_{t}"][IB] for t in rr])
    for nm, m in [("pohon d=6", DecisionTreeClassifier(max_depth=6, random_state=0)), ("reg. logistik", make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)))]:
        m.fit(Xs, ys)
        for r in lab + v5:
            recC.append(dict(sumber="model simulasi (6 kelas)", sapuan=ref, model=nm, kond=r["kond"], u=r["u"], label=r["label"],
                             tebakan=KELAS_SIM[int(m.predict([xr(r)])[0])]))
    # model dilatih data lab, leave-one-condition-out, 3 kelas
    for nm, mk in [("pohon d=2", lambda: DecisionTreeClassifier(max_depth=2, random_state=0)),
                   ("reg. logistik", lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=0.5)))]:
        for g in grup:
            tr = [r for r in lab if GRUP[r["kond"]] != g]; te = [r for r in lab if GRUP[r["kond"]] == g]
            ytr = [r["label"] for r in tr]
            m = mk().fit(np.array([xr(r) for r in tr]), ytr)
            recC += [dict(sumber="lab per pola (3 kelas)", sapuan=ref, model=nm, kond=r["kond"], u=r["u"], label=r["label"], tebakan=p)
                     for r, p in zip(te, m.predict(np.array([xr(r) for r in te])))]
C = pd.DataFrame(recC); C.to_csv(f"{OUT}/C_diagnosis_rinci.csv", index=False)
peta = {"normal": "normal", "bayangan sebagian": "opak", "tembus cahaya": "paranet"}
Cl = C[C.label != "dioda?"].copy(); Cl["benar"] = [peta.get(t, t) == l for t, l in zip(Cl.tebakan, Cl.label)]
ringC = Cl.groupby(["sumber", "sapuan", "model"]).benar.agg(n="size", benar="sum").assign(akurasi_pct=lambda d: (d.benar / d.n * 100).round(0))
ringC.to_csv(f"{OUT}/C_diagnosis_ringkas.csv"); tulis(ringC.to_string())
tulis("(label lab: 3 kondisi normal, 1 opak, 6 paranet; n = set (kondisi, ulangan). Kelas dioda/hambatan seri tidak ada di data lab.)")
for (src, ref, nm), g in Cl.groupby(["sumber", "sapuan", "model"]):
    tulis(f"\nMatriks konfusi: {src}, {ref}, {nm} (baris = label, kolom = tebakan)")
    tulis(pd.crosstab(g.label, g.tebakan).to_string())
tulis("\nV5 (eksplorasi, dioda bypass modul C tampak tidak berfungsi): tebakan model simulasi")
tulis(C[(C.label == "dioda?") & (C.sumber.str.startswith("model"))].groupby(["sapuan", "model"]).tebakan.value_counts().to_string())
open(f"{OUT}/ringkasan.txt", "w", encoding="utf8").write("\n".join(lines))
