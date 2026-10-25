"""Halaman L3: lapisan saklar semikonduktor dari proposal (desain dan hitungan tim, belum dibangun) dan aturan stabilitas
mode otomatis (belum divalidasi). docs/CONTRACT.md §17."""
import os, sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402
from shadeshift import inti  # noqa: E402

st.header("L3: saklar semikonduktor dan aturan stabilitas")
if not U.server_hidup(): st.stop()

alat = [d for d in U.get("/devices") if d["kind"] != "virtual"]
pilih = st.selectbox("Alat (untuk susunan aktif)", [None] + [d["id"] for d in alat],
                     format_func=lambda i: "-" if i is None else i, index=1 if alat else 0)
d = U.get("/l3", **({"device_id": pilih} if pilih else {}))

st.subheader("Daya kendali: relai vs saklar semikonduktor")
st.caption("**Hitungan desain, belum dibangun** (`SHADESHIFT_ML/saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md`). Daya penahan = daya "
           "untuk menjaga saklar tetap tertutup (R0 + saklar susunan). " + d["assumptions"] + ".")
rows = [{"susunan": r["wiring"], "elemen tertutup": r["elements"], "relai (W)": r["relay_w"],
         "semikonduktor (W)": r["semi_w"], "target ≤ 0,25 W": "✅ semikonduktor" if r["semi_w"] <= d["target_w"] else "❌"}
        for r in d["holding_by_wiring"]]
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

live = d.get("live")
if live and live.get("holding"):
    h = live["holding"]
    k = st.columns(3)
    k[0].metric("Susunan aktif", live["wiring"])
    k[1].metric("Daya penahan relai (hitungan)", f"{h['relay_w']:.2f} W")
    k[2].metric("Bila semikonduktor (hitungan)", f"{h['semi_w']:.3f} W")
elif pilih:
    st.caption("Alat ini tidak sedang memegang susunan (semua relai terbuka).")

if d["measured"]:
    st.markdown("**Terukur (multimeter, isian di halaman Target vs Bukti)**")
    st.dataframe(pd.DataFrame([{"tanggal": e["at"][:16].replace("T", " "), "susunan": e.get("topology") or "-",
                                "ESP32 (W)": e["device_power_w"], "relai (W)": e["relay_power_w"], "total (W)": e["value"]}
                               for e in d["measured"]]), hide_index=True, width="stretch")
else:
    st.caption("Belum ada pengukuran daya. Isi di halaman **Target vs Bukti** (ukur dengan WiFi ESP32 mati dan menyala).")

st.markdown("**Keuntungan bersih memilih susunan** (simulasi modul 10 W, G ≥ 700 W/m², keuntungan kotor +1,06 W dibanding TCT tetap)")
st.dataframe(pd.DataFrame([{"skema": r["skema"], "beban kendali (W)": float(r["beban_W"]), "bersih (W)": float(r["bersih_W"])}
                           for r in d["net_gain"]]), hide_index=True, width="stretch")
st.caption("Relai menghabiskan keuntungan (bersih negatif); saklar semikonduktor mempertahankan sekitar 60-80 %. "
           "Itulah alasan lapisan L3 di proposal.")

gambar = Path(inti.ML) / "saklar"
a, b = st.columns(2)
for kol, nama, ket in ((a, "1_matriks_saklar_semikonduktor.png", "Peta saklar S0-S10 (desain)"),
                       (b, "3_perbandingan_relai_semikonduktor.png", "Relai vs semikonduktor (hitungan)")):
    if (gambar / nama).is_file():
        kol.image(str(gambar / nama), caption=ket, width="stretch")

# ---------------- aturan stabilitas ----------------
st.subheader("Aturan stabilitas (mode otomatis)")
s = U.get("/stability")
aktif = bool((s.get("setting") or {}).get("enabled"))
st.markdown(f"Aturan: bila daya sapuan pantau naik-turun lebih dari 10 % dalam 30 detik, kunci TCT dan jangan jalankan "
            f"pemilih sampai stabil lagi. Bawaan: **{'menyala' if aktif else 'mati'}**. Bisa dinyalakan per sesi di "
            "halaman Langsung (Mode otomatis). **Belum divalidasi.**")
sim = s.get("sim")
if sim:
    st.markdown(f"**Simulasi** ({sim['label']}): rata-rata % energi MLPE ideal")
    tab = pd.DataFrame(sim["mean_pct_mlpe"]).rename(columns={"daun": "daun bergoyang", "bergerak": "bayangan bergerak pelan",
                                                             "campuran": "campuran"})
    st.dataframe(tab, width="stretch")
    rows = []
    for jenis, per in sim["by_interval"].items():
        for jeda, v in per.items():
            rows.append({"jenis": jenis, "sapuan pantau tiap (s)": int(jeda),
                         "aturan lebih baik / lebih buruk": f"{v['rule_better']} / {v['rule_worse']} dari {v['of']}",
                         "mode otomatis kalah dari TCT tetap": f"{v['auto_worse_than_tct']} dari {v['of']}"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Tiap sapuan pantau memutus daya sekitar 3 detik (alat hanya bisa mengukur daya dengan menyapu), jadi seberapa "
               "sering memantau sangat menentukan. Pemilih dianggap sempurna di simulasi ini; yang diuji hanya aturannya.")
else:
    st.caption("Simulasi belum dijalankan: `cd SHADESHIFT_ML`, `..\\.venv\\Scripts\\python uji_stabilitas.py` (sekitar 7 menit).")
if s["real"]:
    st.markdown("**Data terukur** (scan penuh kondisi dinamis, mis. F1 daun): % dari memilih yang terbaik tiap putaran")
    st.dataframe(pd.DataFrame([{"scan": r["condition"], "putaran": r["rounds"],
                                **{k: v["pct_of_best"] for k, v in r["policies"].items()}} for r in s["real"]]),
                 hide_index=True, width="stretch")
    st.caption("Putaran berjarak 20-40 detik; biaya sapuan dan pindah tidak dihitung di sini.")
else:
    st.caption("Belum ada scan dinamis terukur. Ambil kondisi **F1** (ranting digerakkan) di halaman Ambil data.")
