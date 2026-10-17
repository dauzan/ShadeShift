"""Model pemilih susunan untuk ESP32 (jalur A).
1. Latih regresi logistik pada simulasi (sapuan 4S, 14 fitur bentuk) -> pilih 4S / 2S2P / TCT (jendela 24 V).
2. Ekspor bobot ke pemilih_bobot.h (float32).
3. Tiruan C (port_c.py, langkah sama dengan pemilih.h) dibandingkan dengan pipeline asli (numpy/scipy/sklearn) pada
   kurva lab dan simulasi: fitur dan keputusan harus sama.
4. Kurva uji untuk sketsa ESP32: uji_pemilih/data_uji.h (kurva 4S lab yang sudah dicuplik ulang + keputusan harapan).
Jalankan dari folder SHADESHIFT_ML: python edge_ai/pemilih/latih_ekspor.py"""
import os, sys, glob, re
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from fitur import NAMA_FITUR, fitur
import port_c

H = os.path.dirname(os.path.abspath(__file__))
TOPO3 = ["4S", "2S2P", "TCT"]
BENTUK = [n for n in NAMA_FITUR if n not in ("Voc", "Isc", "Pmax")]
IB = [NAMA_FITUR.index(n) for n in BENTUK]

# ---------------- 1. latih
sim = pd.read_csv("data/sim_acak.csv")
X = sim[[f"4S:{n}" for n in BENTUK]].values; y = sim[[f"P_W24_{t}" for t in TOPO3]].values.argmax(1)
m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)).fit(X, y)
sc, lr = m[0], m[1]
print("kelas latih:", dict(zip(TOPO3, np.bincount(y, minlength=3))), "| akurasi latih: %.1f%%" % (100 * (m.predict(X) == y).mean()))

# ---------------- 2. ekspor
def _lit(v):
    t = "%.9g" % v
    return (t if any(c in t for c in ".eEn") else t + ".0") + "f"           # literal float C yang sah (2 -> 2.0f)
f32 = lambda a: ", ".join(_lit(v) for v in np.asarray(a, dtype=np.float32).ravel())
with open(os.path.join(H, "pemilih_bobot.h"), "w") as f:
    f.write("// Bobot model pemilih susunan SHADESHIFT (regresi logistik, dilatih simulasi, sapuan 4S). Dibuat otomatis oleh latih_ekspor.py.\n")
    f.write("// Urutan fitur: " + ", ".join(BENTUK) + "\n// Urutan kelas: 0 = 4S, 1 = 2S2P, 2 = TCT\n#pragma once\n")
    f.write("#define PEMILIH_N_FITUR %d\n#define PEMILIH_N_KELAS 3\n" % len(BENTUK))
    f.write("static const float PEMILIH_RERATA[PEMILIH_N_FITUR] = {%s};\n" % f32(sc.mean_))
    f.write("static const float PEMILIH_SKALA[PEMILIH_N_FITUR] = {%s};\n" % f32(sc.scale_))
    f.write("static const float PEMILIH_BOBOT[PEMILIH_N_KELAS][PEMILIH_N_FITUR] = {\n")
    for row in lr.coef_: f.write("  {%s},\n" % f32(row))
    f.write("};\nstatic const float PEMILIH_BIAS[PEMILIH_N_KELAS] = {%s};\n" % f32(lr.intercept_))
W = dict(mean=sc.mean_.astype(np.float32), scale=sc.scale_.astype(np.float32), coef=lr.coef_.astype(np.float32), bias=lr.intercept_.astype(np.float32))


# ---------------- 3. bandingkan tiruan C dengan pipeline asli
def baca_mentah(path):
    V, I = [], []
    for ln in open(path, encoding="utf8"):
        p = ln.strip().split(",")
        if ln.startswith("#") or len(p) != 3 or p[0] == "V": continue
        try: V.append(float(p[0])); I.append(float(p[1]))
        except ValueError: pass
    return np.array(V), np.array(I)


def asli(Vm, Im):
    d = pd.DataFrame({"V": Vm, "I": np.clip(Im, 0, None)}); d = d[d.V > 0].groupby("V", as_index=False).I.mean()   # V kembar: rata-rata I
    V = np.linspace(d.V.min(), d.V.max(), 201); I = np.interp(V, d.V, d.I)
    return V, I, fitur(V, I)[IB]


lab = sorted(glob.glob("data/data_lab/*_4S_u*.csv")) + sorted(glob.glob("data/data_lab/*/*_4S_u*.csv"))
maks_selisih, beda, rows = 0.0, [], []
for p in lab:
    Vm, Im = baca_mentah(p)
    V, I, fa = asli(Vm, Im)
    Vc, Ic = port_c.cuplik_ulang(Vm.astype(np.float32), Im.astype(np.float32))
    fc = port_c.fitur_bentuk(Vc, Ic)
    ka = int(m.predict([fa])[0]); kc, skor = port_c.pilih(fc, W)
    maks_selisih = max(maks_selisih, float(np.max(np.abs(fa - fc))))
    if ka != kc: beda.append(os.path.basename(p))
    rows.append(dict(berkas=os.path.basename(p), keputusan_python=TOPO3[ka], keputusan_c=TOPO3[kc], **{n: v for n, v in zip(BENTUK, fc)}))
print("lab 4S: %d kurva | selisih fitur maks %.2e | keputusan beda: %s" % (len(lab), maks_selisih, beda or "tidak ada"))
pd.DataFrame(rows).to_csv(os.path.join(H, "referensi_lab_4S.csv"), index=False)

# simulasi: bandingkan pada kurva yang dibangun ulang dari fitur tidak bisa; pakai kurva sintetis dari sim_core
from sim_core import simulasi
from fitur import sapuan
rng = np.random.default_rng(1); nb = 0; nm = 0; ms = 0.0
for _ in range(300):
    S = list(rng.uniform(0, 90, 4) * (rng.random(4) < 0.5)); mode = [str(rng.choice(["opak", "paranet"])) for _ in range(4)]
    nc = [int(rng.choice([1, 3, 6, 12])) for _ in range(4)]
    tp, pw, ml = simulasi(S, mode, nc, float(rng.uniform(100, 1000)), float(rng.uniform(15, 60)), list(rng.uniform(0.9, 1.08, 4)))
    Vs, Is = sapuan(tp["4S"], rng)
    V, I, fa = asli(Vs, Is)
    Vc, Ic = port_c.cuplik_ulang(Vs.astype(np.float32), Is.astype(np.float32)); fc = port_c.fitur_bentuk(Vc, Ic)
    ms = max(ms, float(np.max(np.abs(fa - fc)))); nm += 1; nb += int(m.predict([fa])[0]) != port_c.pilih(fc, W)[0]
print("simulasi 4S: %d kurva | selisih fitur maks %.2e | keputusan beda: %d" % (nm, ms, nb))

# ---------------- 4. data uji untuk sketsa ESP32 (12 kurva lab 4S, sudah dicuplik ulang 201 titik)
pilih_uji = ["V1c_4S_u1", "V1_4S_u1", "V3_opak_4S_u1", "V3_paranet65_4S_u1", "V3_paranet75_4S_u2", "V4_paranet65_4S_u1",
             "V4_paranet75_4S_u3", "V6_paranet65_4S_u1", "V6_paranet75_4S_u2", "V1b_4S_u2", "V3_opak_4S_u3", "V6_paranet65_4S_u3"]
os.makedirs(os.path.join(H, "uji_pemilih"), exist_ok=True)
with open(os.path.join(H, "uji_pemilih", "data_uji.h"), "w") as f:
    f.write("// Kurva uji (lab, sapuan 4S, mentah dari berkas CSV) + fitur dan keputusan harapan. Dibuat otomatis oleh latih_ekspor.py.\n#pragma once\n")
    f.write("#define N_UJI %d\n" % len(pilih_uji))
    nmax = 0; isi = []
    for nmk in pilih_uji:
        Vm, Im = baca_mentah(f"data/data_lab/{nmk}.csv"); nmax = max(nmax, len(Vm)); isi.append((nmk, Vm, Im))
    f.write("#define N_MAKS_TITIK %d\n" % nmax)
    f.write("static const char* UJI_NAMA[N_UJI] = {%s};\n" % ", ".join('"%s"' % n for n, _, _ in isi))
    f.write("static const uint16_t UJI_N[N_UJI] = {%s};\n" % ", ".join(str(len(v)) for _, v, _ in isi))
    for key, arr in (("V", 1), ("I", 2)):
        f.write("static const float UJI_%s[N_UJI][N_MAKS_TITIK] = {\n" % key)
        for t in isi:
            a = np.zeros(nmax, np.float32); a[:len(t[arr])] = t[arr]; f.write("  {%s},\n" % f32(a))
        f.write("};\n")
    harap_f, harap_k = [], []
    for nmk, Vm, Im in isi:
        Vc, Ic = port_c.cuplik_ulang(Vm.astype(np.float32), Im.astype(np.float32)); fc = port_c.fitur_bentuk(Vc, Ic)
        harap_f.append(fc); harap_k.append(port_c.pilih(fc, W)[0])
    f.write("static const float UJI_FITUR[N_UJI][PEMILIH_N_FITUR] = {\n%s};\n" % "".join("  {%s},\n" % f32(x) for x in harap_f))
    f.write("static const uint8_t UJI_KEPUTUSAN[N_UJI] = {%s};\n" % ", ".join(map(str, harap_k)))
print("data uji ESP32:", len(pilih_uji), "kurva, keputusan harapan:", [TOPO3[k] for k in harap_k])
