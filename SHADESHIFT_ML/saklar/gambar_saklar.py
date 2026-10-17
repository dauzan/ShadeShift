import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
NAVY, HIJAU, OREN, ABU = "#24418C", "#3C8D40", "#D35F00", "#555555"
MIN = "−"; PANAH = "↔"

# ---------- Gambar 1: matriks saklar semikonduktor ----------
simpul = ["P", "A+", "A-", "B+", "B-", "C+", "C-", "D+", "D-", "N"]
x = {s: i for i, s in enumerate(simpul)}
sak = {1: ("A-", "B+"), 2: ("B-", "N"), 3: ("C+", "P"), 4: ("C-", "D+"), 5: ("B-", "C+"), 6: ("B+", "D+"),
       7: ("A-", "N"), 8: ("B+", "P"), 9: ("C-", "N"), 10: ("D+", "P")}
tab = pd.read_csv("tabel_saklar.csv"); kecil = tab[tab.modul.str.startswith("kecil")].set_index("saklar")
fig, ax = plt.subplots(figsize=(13, 8.4)); ax.set_xlim(-1.9, 11.9); ax.set_ylim(-1.9, 12.4); ax.axis("off")
for s in simpul:
    warna = "#B03A2E" if s == "P" else ("black" if s == "N" else ABU)
    ax.plot([x[s], x[s]], [0.4, 11.2], color=warna, lw=3.2 if s in ("P", "N") else 1.8)
    ax.text(x[s], 11.6, s.replace("-", MIN), ha="center", fontsize=13, fontweight="bold", color=warna)
ax.plot([x["P"], x["A+"]], [10.7, 10.7], color="#B03A2E", lw=3.2); ax.plot([x["D-"], x["N"]], [10.7, 10.7], color="black", lw=3.2)
ax.text(0.5, 10.95, "kabel tetap", fontsize=9, color="#B03A2E", ha="center"); ax.text(8.5, 10.95, "kabel tetap", fontsize=9, ha="center")
nama_simpul = {"Am": "A" + MIN, "Bm": "B" + MIN, "Cm": "C" + MIN, "Ap": "A+", "Bp": "B+", "Cp": "C+", "Dp": "D+", "P": "P", "N": "N"}
for r, (a, b) in sak.items():
    y = 10.0 - r * 0.92; xa, xb = x[a], x[b]; lo, hi = min(xa, xb), max(xa, xb)
    ax.plot([lo, hi], [y, y], color=NAVY, lw=2.4); ax.plot([xa, xb], [y, y], "o", color="black", ms=7, zorder=6)
    xc = (lo + hi) / 2
    ax.add_patch(FancyBboxPatch((xc - 0.33, y - 0.27), 0.66, 0.54, boxstyle="round,pad=0.02", fc="#DCE6F5", ec=NAVY, lw=1.8, zorder=3))
    ax.text(xc, y, "S%d" % r, ha="center", va="center", fontsize=11, fontweight="bold", color=NAVY, zorder=4)
    k = kecil.loc["S%d" % r]
    p1, p2 = k.simpul.split("-")
    ax.text(10.1, y, "%s%s%s   %s %.0f V, %.2f A" % (nama_simpul[p1], PANAH, nama_simpul[p2], "≥", k.tegangan_blokir_V, k.arus_maks_A),
            fontsize=8.6, va="center", color=ABU)
ax.text(10.1, 10.45, "simpul yang dihubungkan: tegangan blokir, arus (modul 10 W)", fontsize=8.2, color=ABU, style="italic", va="center")
ax.add_patch(FancyBboxPatch((-1.78, 6.9), 1.5, 1.3, boxstyle="round,pad=0.02", fc="#E3F1E4", ec=HIJAU, lw=2))
ax.text(-1.03, 7.85, "S0", ha="center", fontsize=12, fontweight="bold", color=HIJAU)
ax.text(-1.03, 7.3, "saklar utama" + chr(10) + "(sekring, penjejak)", ha="center", fontsize=7.2, color=HIJAU, va="center")
ax.plot([-0.28, 0], [7.55, 7.55], color=HIJAU, lw=2)
for n, xx in [("Modul A", 1.5), ("Modul B", 3.5), ("Modul C", 5.5), ("Modul D", 7.5)]:
    ax.add_patch(FancyBboxPatch((xx - 0.85, -1.0), 1.7, 0.95, boxstyle="round,pad=0.02", fc="#DCE6F5", ec=NAVY, lw=1.8))
    ax.text(xx, -0.5, n + "\n+ dioda pelewat", ha="center", va="center", fontsize=8.5, color=NAVY)
ax.text(5.0, 12.1, "Matriks saklar semikonduktor SHADESHIFT: S1–S10 + S0 menggantikan relai R0–R10", ha="center", fontsize=13.5, fontweight="bold", color=NAVY)
ax.text(5.0, -1.55, "Tiap S = sepasang MOSFET punggung-ke-punggung + pengemudi gerbang terisolasi (lihat gambar sel). "
        "Topologi: 4S = S1,S4,S5; 2S2P = S1–S4; TCT = S1–S4,S6; 4P = S2,S3,S7–S10.", ha="center", fontsize=8.2, color=ABU)
fig.savefig("1_matriks_saklar_semikonduktor.png", dpi=170, bbox_inches="tight"); plt.close(fig)

# ---------- Gambar 2: sel saklar (satu saklar dua arah), simbol MOSFET yang benar ----------
fig, ax = plt.subplots(figsize=(12, 6.6)); ax.set_xlim(0, 12); ax.set_ylim(0, 6.6); ax.axis("off")

def mosfet(cx, cy, g, label):
    """g = +1: gerbang di kanan kanal, terminal D/S di kiri; g = -1: sebaliknya. Kembalikan x terminal."""
    xt = cx - g * 0.45
    ax.plot([cx + g * 0.2, cx + g * 0.2], [cy - 0.6, cy + 0.6], color="black", lw=2.2)               # pelat gerbang
    for dy in (-0.45, 0.0, 0.45):
        ax.plot([cx, cx], [cy + dy - 0.17, cy + dy + 0.17], color="black", lw=2.2)                   # kanal terputus-putus
        ax.plot([cx, xt], [cy + dy, cy + dy], color="black", lw=2)                                  # terminal D (atas), badan (tengah), S (bawah)
    ax.plot([xt, xt], [cy, cy - 0.45], color="black", lw=2)                                         # badan terikat ke source
    ax.plot([cx + g * 0.2, cx + g * 0.2 + g * 0.45], [cy, cy], color=HIJAU, lw=2)                    # kawat gerbang
    ax.text(cx, cy + 0.85, label, fontsize=11, fontweight="bold", color=NAVY, ha="center")
    return xt

yb = 3.2
x1 = mosfet(3.2, yb, +1, "Q1"); x2 = mosfet(5.8, yb, -1, "Q2")
ax.plot([x1, x1], [yb + 0.45, yb + 1.0], color=NAVY, lw=2.4); ax.plot([0.6, x1], [yb + 1.0, yb + 1.0], color=NAVY, lw=2.4)
ax.text(0.2, yb + 1.15, "X", fontsize=13, fontweight="bold")
ax.plot([x2, x2], [yb + 0.45, yb + 1.0], color=NAVY, lw=2.4); ax.plot([x2, 7.4], [yb + 1.0, yb + 1.0], color=NAVY, lw=2.4)
ax.text(7.5, yb + 1.15, "Y", fontsize=13, fontweight="bold")
ax.plot([x1, x1], [yb - 0.45, yb - 1.0], color=NAVY, lw=2.4); ax.plot([x2, x2], [yb - 0.45, yb - 1.0], color=NAVY, lw=2.4)
ax.plot([x1, x2], [yb - 1.0, yb - 1.0], color=NAVY, lw=2.4)
ax.text(4.5, yb - 1.35, "sumber bersama (CS)", fontsize=9, color=ABU, ha="center")
ax.plot([3.4 + 0.45 * 0 + 0.2, 4.5], [yb, yb], color=HIJAU, lw=2); ax.plot([5.6 - 0.0, 4.5], [yb, yb], color=HIJAU, lw=2)
ax.plot([4.5, 4.5], [yb, yb + 0.7], color=HIJAU, lw=2); ax.text(4.5, yb + 0.8, "G (+)", fontsize=9.5, color=HIJAU, ha="center", fontweight="bold")
ax.plot([4.5, 4.5], [yb - 1.0, yb - 1.25], color=NAVY, lw=1.6)
# TVS di bawah
ax.plot([1.2, 1.2], [yb + 1.0, 0.9], color=OREN, lw=1.8); ax.plot([1.2, 3.1], [0.9, 0.9], color=OREN, lw=1.8)
ax.plot([5.2, 6.9], [0.9, 0.9], color=OREN, lw=1.8); ax.plot([6.9, 6.9], [0.9, yb + 1.0], color=OREN, lw=1.8)
ax.plot([0.6, 1.2], [yb + 1.0, yb + 1.0], color=OREN, lw=1.8); ax.plot([6.9, 7.4], [yb + 1.0, yb + 1.0], color=OREN, lw=1.8)
ax.add_patch(Rectangle((3.1, 0.65), 2.1, 0.5, fc="white", ec=OREN, lw=1.8, zorder=3)); ax.text(4.15, 0.9, "TVS (paralel X–Y)", fontsize=9.5, ha="center", va="center", color=OREN, fontweight="bold", zorder=4)
ax.text(1.2, 0.3, "peredam lonjakan; nilai sesuai tegangan blokir pada gambar matriks", fontsize=8.6, color=OREN)
# pengemudi
ax.add_patch(FancyBboxPatch((8.2, 3.2), 3.4, 1.9, boxstyle="round,pad=0.03", fc="#E3F1E4", ec=HIJAU, lw=2))
ax.text(9.9, 4.7, "Pengemudi fotovoltaik", fontsize=10.5, fontweight="bold", ha="center", color=HIJAU)
ax.text(9.9, 4.3, "contoh: VOM1271 (Vishay)", fontsize=9, ha="center", color=HIJAU)
ax.text(9.9, 3.9, "keluaran 8,4 V, 15 µA pada IF = 10 mA", fontsize=8.4, ha="center", color=HIJAU)
ax.text(9.9, 3.5, "terisolasi 4500 V rms (lembar data)", fontsize=8.4, ha="center", color=HIJAU, style="italic")
ax.plot([7.9, 8.2], [4.5, 4.5], color=HIJAU, lw=2); ax.text(7.85, 4.62, "G (+)", fontsize=9, color=HIJAU, ha="right", fontweight="bold")
ax.plot([7.9, 8.2], [3.6, 3.6], color=NAVY, lw=1.8); ax.text(7.85, 3.72, "CS (−)", fontsize=9, color=NAVY, ha="right", fontweight="bold")
ax.text(4.5, yb - 1.55, "(CS tersambung ke pengemudi)", fontsize=8, color=ABU, ha="center")
# ESP32
ax.add_patch(FancyBboxPatch((8.6, 0.4), 2.6, 1.0, boxstyle="round,pad=0.03", fc="#F4F4F4", ec=ABU, lw=1.6))
ax.text(9.9, 1.05, "ESP32 (GPIO)", fontsize=10, fontweight="bold", ha="center", color=ABU); ax.text(9.9, 0.65, "3,3 V, sinyal logika", fontsize=8.6, ha="center", color=ABU)
ax.plot([9.9, 9.9], [1.4, 3.2], color=ABU, lw=1.8); ax.text(10.05, 2.15, "~210 Ω → LED" + chr(10) + "≈ 10 mA", fontsize=8.8, color=ABU)
ax.text(6.0, 6.4, "Sel saklar semikonduktor dua arah (satu dari S0–S10)", fontsize=13.5, fontweight="bold", ha="center", color=NAVY)
ax.text(6.0, 6.0, "Dua MOSFET-N punggung-ke-punggung memblokir tegangan di kedua arah; tidak ada arus tahan selain LED pengemudi.", fontsize=9, ha="center", color=ABU)
fig.savefig("2_sel_saklar_semikonduktor.png", dpi=170, bbox_inches="tight"); plt.close(fig)

# ---------- Gambar 3: perbandingan relai vs semikonduktor ----------
dk = pd.read_csv("daya_kendali.csv"); kb = pd.read_csv("keuntungan_bersih.csv")
fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.6))
w = 0.38; xx = np.arange(len(dk))
ax[0].bar(xx - w / 2, dk.relai_W, w, color=OREN, label="relai (kumparan terus menyala)"); ax[0].bar(xx + w / 2, dk.semikonduktor_W, w, color=HIJAU, label="saklar semikonduktor")
for i, (a, b) in enumerate(zip(dk.relai_W, dk.semikonduktor_W)):
    ax[0].text(i - w / 2, a + 0.04, "%.2f" % a, ha="center", fontsize=9); ax[0].text(i + w / 2, b + 0.04, "%.2f" % b, ha="center", fontsize=9)
ax[0].set_xticks(xx); ax[0].set_xticklabels(dk.topologi); ax[0].set_ylabel("daya kendali (W)")
ax[0].set_title("Daya untuk menahan saklar tetap tertutup", fontsize=11, color=NAVY, loc="left"); ax[0].legend(frameon=False, fontsize=9)
ax[0].spines[["top", "right"]].set_visible(False)
ax[1].bar(range(len(kb)), kb.bersih_W, color=[OREN, "#7FAF84", HIJAU])
for i, v in enumerate(kb.bersih_W): ax[1].text(i, v + (0.04 if v >= 0 else -0.12), "%+.2f W" % v, ha="center", fontsize=10, fontweight="bold")
ax[1].axhline(0, color="black", lw=1); ax[1].axhline(1.06, color=NAVY, lw=1.2, ls="--"); ax[1].text(2.45, 1.09, "keuntungan kotor +1,06 W", fontsize=8.6, color=NAVY, ha="right")
ax[1].set_xticks(range(len(kb))); ax[1].set_xticklabels(["relai", "MOSFET 100 V\n(kelas IRF540N)", "MOSFET 150 V\n(kelas IRFB4115)"], fontsize=9); ax[1].set_ylim(-1.1, 1.35)
ax[1].set_ylabel("keuntungan bersih (W)"); ax[1].set_title("Keuntungan bersih memilih topologi (array 4 x 10 W)", fontsize=11, color=NAVY, loc="left")
ax[1].spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig("3_perbandingan_relai_semikonduktor.png", dpi=170); plt.close(fig)
print("selesai")
