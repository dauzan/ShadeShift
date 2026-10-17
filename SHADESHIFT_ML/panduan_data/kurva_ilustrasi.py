"""Kurva ilustrasi per kelas gangguan untuk panduan pengambilan data. Model simulasi (sim_core), BUKAN data lab.
Susunan 4S (empat modul seri); gangguan hanya pada modul A. Sumbu dinormalisasi: V/Voc, I/Isc, P/Pmax.
Keluaran: panduan_data/kurva_ilustrasi.json (dibaca panduan_data.html).
Jalankan dari SHADESHIFT_ML: python panduan_data/kurva_ilustrasi.py"""
import os, sys, json
import numpy as np
sys.path.insert(0, os.getcwd())
import sim_core as sc

H = os.path.dirname(os.path.abspath(__file__))
N_TITIK = 121

KASUS = [
    ("normal", "Normal, tanpa bayangan", dict()),
    ("opak", "Bayangan opak, 6 sel modul A", dict(S=[100, 0, 0, 0], mode=["opak"] * 4, nc=[6, 1, 1, 1])),
    ("paranet", "Redup merata 75 %, modul A", dict(S=[75, 0, 0, 0], mode=["paranet"] + ["opak"] * 3)),
    ("dioda_terbuka", "Dioda terbuka, modul A terbayangi 75 %",
     dict(S=[75, 0, 0, 0], mode=["paranet"] + ["opak"] * 3, ubah=[{"bypass": False}, {}, {}, {}])),
    ("dioda_pintas", "Dioda hubung singkat, modul A dipintas",
     dict(ubah=[{"bypass": "pendek"}, {}, {}, {}])),
    ("seri_naik", "Resistansi seri modul A naik 4x",
     dict(ubah=[{"R_s": sc.PARAMS[0]["R_s"] * 4}, {}, {}, {}])),
]


def kurva_4s(**kw):
    S = kw.pop("S", [0, 0, 0, 0]); mode = kw.pop("mode", ["opak"] * 4)
    tp, pw, mlpe = sc.simulasi(S, mode, nc=kw.get("nc"), ubah=kw.get("ubah"))
    c = tp["4S"]
    voc = float(c.V_of_I(0.0)); isc = float(c.I_of_V(0.0))
    V = np.linspace(0.0, voc, N_TITIK)
    I = np.clip(c.I_of_V(V), 0.0, None)
    P = V * I
    return dict(voc=voc, isc=isc, pmax=float(P.max()), vn=V / voc, i_n=I / isc, p_n=P / P.max(),
                vmp_n=float(V[P.argmax()] / voc))


if __name__ == "__main__":
    print("R_s modul (ohm):", [round(p["R_s"], 4) for p in sc.PARAMS])
    hasil = []; normal = None
    for kode, nama, kw in KASUS:
        k = kurva_4s(**dict(kw))
        if kode == "normal": normal = k["pmax"]
        hasil.append((kode, nama, k))
        print("%-14s Voc %6.2f V  Isc %5.3f A  Pmax %6.3f W  Vmp/Voc %.2f" % (kode, k["voc"], k["isc"], k["pmax"], k["vmp_n"]))
    out = []
    for kode, nama, k in hasil:
        out.append(dict(kode=kode, nama=nama, voc=round(k["voc"], 2), isc=round(k["isc"], 4),
                        pmax=round(k["pmax"], 3), pct=round(100 * k["pmax"] / normal, 1),
                        vn=[round(float(x), 4) for x in k["vn"]], i_n=[round(float(x), 4) for x in k["i_n"]],
                        p_n=[round(float(x), 4) for x in k["p_n"]]))
    json.dump(out, open(os.path.join(H, "kurva_ilustrasi.json"), "w", encoding="utf8"), ensure_ascii=False)
    print("tersimpan kurva_ilustrasi.json", len(out), "kasus")
