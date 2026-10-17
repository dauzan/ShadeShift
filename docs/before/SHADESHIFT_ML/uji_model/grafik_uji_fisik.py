"""Grafik hasil uji pemilihan susunan pada data fisik (gaya polos). Jalankan dari folder SHADESHIFT_ML setelah uji_data_fisik.py."""
import pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.family": "Arial", "font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False})
B = pd.read_csv("uji_model/hasil/B_pemilihan_rinci.csv")
M = [("tetap 2S2P", "Susunan tetap 2S2P", "#C5CAD1"), ("tetap TCT", "Susunan tetap TCT", "#8E97A3"),
     ("simulasi, reg. logistik, sapuan 4S", "Model (dilatih simulasi), satu sapuan 4S", "#1F3A6E")]
K = ["V1c", "V3_opak", "V3_paranet65", "V3_paranet75", "V4_paranet65", "V4_paranet75", "V6_paranet65", "V6_paranet75"]
NK = ["Tanpa\nbayangan", "Opak\n1 sel", "Paranet\nA (65%)", "Paranet\nA (75%)", "Paranet\nA+B (65%)", "Paranet\nA+B (75%)", "Paranet\nA+D (65%)", "Paranet\nA+D (75%)"]
fig, ax = plt.subplots(figsize=(10, 3.6)); w = 0.26
for j, (m, lab, c) in enumerate(M):
    v = [B[(B.metode == m) & (B.kond == k)].rugi.mean() for k in K]
    ax.bar(np.arange(len(K)) + (j - 1) * w, v, w, color=c, label=lab)
ax.set_xticks(range(len(K))); ax.set_xticklabels(NK, fontsize=9); ax.set_ylabel("Rugi terhadap susunan terbaik (%)")
ax.legend(frameon=False, fontsize=9.5, loc="upper right"); ax.set_ylim(0, 17)
fig.tight_layout(); fig.savefig("uji_model/hasil/grafik_pemilihan_fisik.png", dpi=220, facecolor="white"); print("ok")
