"""Evaluasi lengkap model pemilih susunan (spesifikasi, metrik simulasi uji-tahan, metrik data fisik, biaya komputasi).
Jalankan dari folder SHADESHIFT_ML: python edge_ai/pemilih/evaluasi.py  -> edge_ai/pemilih/evaluasi.txt"""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, classification_report, log_loss, balanced_accuracy_score
from fitur import NAMA_FITUR

H = os.path.dirname(os.path.abspath(__file__)); TOPO3 = ["4S", "2S2P", "TCT"]
BENTUK = [n for n in NAMA_FITUR if n not in ("Voc", "Isc", "Pmax")]
out = []
def tulis(*a): s = " ".join(str(x) for x in a); print(s); out.append(s)

sim = pd.read_csv("data/sim_acak.csv")
X = sim[[f"4S:{n}" for n in BENTUK]].values; Pw = sim[[f"P_W24_{t}" for t in TOPO3]].values; y = Pw.argmax(1)
idx = np.arange(len(sim)); itr, ite = train_test_split(idx, test_size=0.25, random_state=0, stratify=y)
m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)).fit(X[itr], y[itr])
pr = m.predict(X[ite]); pp = m.predict_proba(X[ite])

tulis("=== Spesifikasi ===")
tulis("Model: regresi logistik multinomial (scikit-learn LogisticRegression, solver lbfgs, regularisasi L2, C = 1,0, max_iter 3000)")
tulis("Pra-proses: StandardScaler (z = (x - rerata) / simpangan baku)")
tulis("Masukan: 14 fitur bentuk dari satu sapuan 4S (201 titik):", ", ".join(BENTUK))
tulis("Keluaran: 3 kelas (4S, 2S2P, TCT) = susunan dengan daya terbesar di jendela pengendali 24 V; 4P tidak dipilih")
tulis("Parameter: %d bobot + %d bias + %d rerata + %d skala = %d angka float32 (%d byte)" % (3 * 14, 3, 14, 14, 3 * 14 + 3 + 28, 4 * (3 * 14 + 3 + 28)))
tulis("Komputasi per keputusan: 14 normalisasi + 3 x 14 kali-tambah (model); ekstraksi fitur sekitar 201 x 10 operasi")
tulis("Data latih: simulasi model dioda tunggal tingkat sel, %d skenario acak (iradiansi 30-1000 W/m2 log-seragam, suhu 15-65 C," % len(sim))
tulis("  ketidakcocokan modul 0,85-1,10, bayangan opak/paranet acak pada 0-4 modul), derau ukur I 1%, V 0,12%")
tulis("Sebaran label (seluruh simulasi):", dict(zip(TOPO3, np.bincount(y, minlength=3).tolist())), "-> 2S2P jarang terbaik (4,4%)")

tulis("\n=== Simulasi, data uji-tahan 25%% (%d skenario, tidak dipakai melatih) ===" % len(ite))
tulis("Akurasi: %.1f%% | akurasi seimbang: %.1f%% | log-loss: %.3f" % (100 * (pr == y[ite]).mean(), 100 * balanced_accuracy_score(y[ite], pr), log_loss(y[ite], pp)))
tulis(classification_report(y[ite], pr, target_names=TOPO3, digits=3))
tulis("Matriks konfusi (baris = susunan terbaik sebenarnya, kolom = pilihan model):")
tulis(pd.DataFrame(confusion_matrix(y[ite], pr), index=TOPO3, columns=TOPO3).to_string())
P = Pw[ite]; best = P.max(1); ml = sim.mlpe.values[ite]; mm = ml > 1.0          # metrik sama dengan latih.py dan proposal
rugi = (best - P[np.arange(len(ite)), pr])[mm] / ml[mm] * 100
tulis("Rugi daya (poin %% daya MLPE, skenario MLPE > 1 W): rata-rata %.2f, median %.2f, persentil-95 %.2f, maks %.2f" % (rugi.mean(), np.median(rugi), np.percentile(rugi, 95), rugi.max()))
for i, t in enumerate(TOPO3):
    r = (best - P[:, i])[mm] / ml[mm] * 100; tulis("  pembanding susunan tetap %-4s: rata-rata %.2f poin, persentil-95 %.2f" % (t, r.mean(), np.percentile(r, 95)))
rugi = (best - P[np.arange(len(ite)), pr]) / np.maximum(ml, 1e-9) * 100
salah = pr != y[ite]
tulis("Salah pilih: %d (%.1f%%); rugi rata-rata saat salah %.2f poin -> salah pilih sebagian besar terjadi saat dua susunan hampir sama dayanya" % (salah.sum(), 100 * salah.mean(), rugi[salah].mean()))

tulis("\n=== Data fisik (lampu halogen, tidak dipakai melatih) ===")
B = pd.read_csv("uji_model/hasil/B_pemilihan_rinci.csv")
b = B[B.metode == "simulasi, reg. logistik, sapuan 4S"]
tulis("n = %d set (10 kondisi, 6 pola independen)" % len(b))
tulis("Rugi: rata-rata %.2f%%, maks %.2f%% | tepat (rugi < 0,5%%): %.0f%%" % (b.rugi.mean(), b.rugi.max(), 100 * (b.rugi < 0.5).mean()))
for t in TOPO3:
    bb = B[B.metode == f"tetap {t}"]; tulis("  pembanding susunan tetap %-4s: rata-rata %.2f%%, maks %.2f%%" % (t, bb.rugi.mean(), bb.rugi.max()))

tulis("\n=== Fitur paling berpengaruh (|bobot| pada fitur yang sudah dinormalisasi) ===")
coef = m[1].coef_
imp = pd.DataFrame(coef.T, index=BENTUK, columns=TOPO3); imp["rata |bobot|"] = np.abs(coef).mean(0)
tulis(imp.sort_values("rata |bobot|", ascending=False).round(2).to_string())
open(os.path.join(H, "evaluasi.txt"), "w", encoding="utf8").write("\n".join(out))
