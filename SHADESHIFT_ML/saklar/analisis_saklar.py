"""Analisis matriks saklar semikonduktor (pengganti relai R0-R10). Keluaran: tabel tegangan blokir dan arus per saklar,
rugi hantaran, daya kendali, dan keuntungan bersih terhadap relai. Asumsi ditandai di bawah; tidak ada angka lembar data yang dikarang."""
import itertools, numpy as np, pandas as pd, sys
sys.path.insert(0, "..")
# ---- tata letak matriks (dari firmware & daftar_kabel.md): saklar = (simpul1, simpul2)
SAKLAR = {1: ("Am", "Bp"), 2: ("Bm", "N"), 3: ("Cp", "P"), 4: ("Cm", "Dp"), 5: ("Bm", "Cp"),
          6: ("Bp", "Dp"), 7: ("Am", "N"), 8: ("Bp", "P"), 9: ("Cm", "N"), 10: ("Dp", "P")}
TUTUP = {"4S": [1, 4, 5], "2S2P": [1, 2, 3, 4], "TCT": [1, 2, 3, 4, 6], "4P": [2, 3, 7, 8, 9, 10]}
ARUS_JALUR = {"4S": {1: 1, 4: 1, 5: 1}, "2S2P": {1: 1, 4: 1, 2: 1, 3: 1},        # kelipatan arus satu modul (modul sama)
              "TCT": {1: 1, 4: 1, 2: 1, 3: 1, 6: 0.3}, "4P": {2: 1, 3: 1, 7: 1, 8: 1, 9: 1, 10: 1}}  # R6 (TCT): hanya arus ketidakcocokan, asumsi 0,3
ARUS_TOTAL = {"4S": 1, "2S2P": 2, "TCT": 2, "4P": 4}                              # arus lewat S0 dan penjejak (kelipatan)
MODUL = {"kecil (10 W)": dict(Voc=22.3, Isc=0.62, Imp=0.56, Pmp=10.0), "besar (~415 W, sintetis)": dict(Voc=44.6, Isc=12.5, Imp=11.4, Pmp=415.0)}
FAKTOR_DINGIN, FAKTOR_SUHU_RDS = 1.12, 1.5      # asumsi: Voc +12 % pada suhu dingin; Rds(on) x1,5 pada suhu kerja (cek kurva lembar data)
KUMPARAN_W = 0.357                              # asumsi: 5 V x 71,4 mA per kumparan relai kelas SRD-05VDC; UKUR dari catu 5 V sebelum dipakai di naskah
LED_MA, V_RAIL = 10.0, 3.3                      # arus LED pengemudi (VOM1271 diuji pada IF = 10 mA), dari rel 3,3 V

def potensial(tutup, Vm):
    """Potensial simpul (N = 0) untuk modul sama bertegangan Vm (rangkaian terbuka); sambungan tetap A+ = P dan D- = N."""
    simpul = ["P", "Ap", "Am", "Bp", "Bm", "Cp", "Cm", "Dp", "Dm", "N"]; induk = {s: s for s in simpul}
    def cari(s):
        while induk[s] != s: s = induk[s]
        return s
    def gabung(a, b): induk[cari(a)] = cari(b)
    gabung("P", "Ap"); gabung("Dm", "N")
    for k in tutup: gabung(*SAKLAR[k])
    modul = [("Ap", "Am"), ("Bp", "Bm"), ("Cp", "Cm"), ("Dp", "Dm")]
    pot = {cari("N"): 0.0}
    for _ in range(6):                          # sebar potensial lewat modul sampai semua kelompok terisi
        for (p, m) in modul:
            gp, gm = cari(p), cari(m)
            if gm in pot and gp not in pot: pot[gp] = pot[gm] + Vm
            if gp in pot and gm not in pot: pot[gm] = pot[gp] - Vm
    return {s: pot.get(cari(s), np.nan) for s in simpul}

baris = []; ringkas = []
for nm, m in MODUL.items():
    Vm = m["Voc"] * FAKTOR_DINGIN
    blok = {k: 0.0 for k in SAKLAR}
    for top, tutup in TUTUP.items():
        pot = potensial(tutup, Vm)
        for k, (a, b) in SAKLAR.items():
            if k in tutup: continue
            blok[k] = max(blok[k], abs(pot[a] - pot[b]))
    imax = {k: 0.0 for k in SAKLAR}
    for top, d in ARUS_JALUR.items():
        for k, f in d.items(): imax[k] = max(imax[k], f * m["Isc"])
    for k in SAKLAR: baris.append(dict(modul=nm, saklar=f"S{k}", simpul=f"{SAKLAR[k][0]}-{SAKLAR[k][1]}", tegangan_blokir_V=round(blok[k], 1), arus_maks_A=round(imax[k], 2)))
    ringkas.append((nm, max(blok.values()), 4 * m["Isc"]))
tab = pd.DataFrame(baris); tab.to_csv("tabel_saklar.csv", index=False)
print(tab.to_string(index=False)); print()
for nm, vb, it in ringkas: print(f"{nm}: tegangan blokir maks = {vb:.0f} V (Voc x {FAKTOR_DINGIN}), arus total maks (4P, S0) = {it:.1f} A")

# ---- rugi hantaran vs Rds(on) per MOSFET (pasangan punggung-ke-punggung = 2 x Rds)
print("\nRugi hantaran saklar semikonduktor, % daya array (pada Imp, Pmax tanpa bayangan):")
RDS = [4.8, 10, 20, 44]   # mOhm per MOSFET (nilai contoh; IRFB4115 maks sekitar 11 mOhm, IRF540N 44 mOhm menurut lembar data)
rows = []
for nm, m in MODUL.items():
    for rds in RDS:
        for top in TUTUP:
            P_arr = 4 * m["Pmp"]
            R = 2 * rds / 1000 * FAKTOR_SUHU_RDS
            rug = sum((f * m["Imp"]) ** 2 * R for f in ARUS_JALUR[top].values() if f > 0.5)       # saklar di jalur arus
            rug += (ARUS_TOTAL[top] * m["Imp"]) ** 2 * R                                      # S0 (satu pasang) membawa arus total
            rows.append(dict(modul=nm, rds_mOhm=rds, topologi=top, rugi_W=round(rug, 3), rugi_persen=round(rug / P_arr * 100, 3)))
rr = pd.DataFrame(rows); rr.to_csv("rugi_hantaran.csv", index=False)
print(rr.pivot_table(index=["modul", "rds_mOhm"], columns="topologi", values="rugi_persen").round(3))

# ---- daya kendali: relai vs saklar semikonduktor (jumlah elemen menyala = saklar topologi + S0)
print("\nDaya kendali (W):")
dk = []
for top, tutup in TUTUP.items():
    n = len(tutup) + 1
    dk.append(dict(topologi=top, elemen_menyala=n, relai_W=round(n * KUMPARAN_W, 2), semikonduktor_W=round(n * LED_MA / 1000 * V_RAIL, 3)))
dk = pd.DataFrame(dk); dk["rasio"] = (dk.relai_W / dk.semikonduktor_W).round(0); dk.to_csv("daya_kendali.csv", index=False); print(dk.to_string(index=False))

# ---- keuntungan bersih: gain adaptif (simulasi 10 W, 24 V, G >= 700; hanya topologi layak 4S, 2S2P, TCT) dikurangi beban kendali
d = pd.read_csv("../data/sim_acak.csv"); d = d[(d.G >= 700) & (d.mlpe > 1)]
K = ["4S", "2S2P", "TCT"]; P = d[[f"P_W24_{t}" for t in K]].values
adaptif = P.max(1).mean(); tetap = P.mean(0).max(); tbest = K[int(P.mean(0).argmax())]; gain = adaptif - tetap
dk3 = dk[dk.topologi.isin(K)]; rata_relai = dk3.relai_W.mean(); rata_ss = dk3.semikonduktor_W.mean()
print(f"\nSkenario simulasi 10 W (G >= 700 W/m2, n={len(d)}): adaptif {adaptif:.2f} W, tetap terbaik ({tbest}) {tetap:.2f} W -> selisih {gain:+.2f} W")
print(f"relai: beban kendali rata-rata {rata_relai:.2f} W -> keuntungan bersih {gain - rata_relai:+.2f} W")
hasil = [dict(skema="relai (kumparan terus menyala)", rds_mOhm=None, beban_W=round(rata_relai, 3), bersih_W=round(gain - rata_relai, 2))]
for rds, nama in [(44, "MOSFET 100 V (kelas IRF540N)"), (11.8, "MOSFET 150 V (kelas IRFB4115)")]:
    rg = 2 * rds / 1000 * FAKTOR_SUHU_RDS; m = MODUL["kecil (10 W)"]
    rug = np.mean([sum((f * m["Imp"]) ** 2 * rg for f in ARUS_JALUR[t].values() if f > 0.5) + (ARUS_TOTAL[t] * m["Imp"]) ** 2 * rg for t in K])
    print(f"{nama}: kendali {rata_ss:.2f} W + hantaran {rug:.3f} W -> keuntungan bersih {gain - rata_ss - rug:+.2f} W")
    hasil.append(dict(skema=nama, rds_mOhm=rds, beban_W=round(rata_ss + rug, 3), bersih_W=round(gain - rata_ss - rug, 2)))
pd.DataFrame(hasil).to_csv("keuntungan_bersih.csv", index=False)
