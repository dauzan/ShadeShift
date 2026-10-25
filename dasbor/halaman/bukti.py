"""Halaman Target vs Bukti: empat target proposal di samping buktinya, tiap angka berlabel sumbernya
(terukur, lab, simulasi, hitungan). docs/CONTRACT.md §13. Target dinyatakan terpenuhi hanya dari bukti terukur."""
import os, sys, uuid

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

st.header("Target vs Bukti")
if not U.server_hidup(): st.stop()

JUDUL = {"recovery": "Memulihkan ≥ 4 poin daya MLPE ideal dibanding susunan tetap terbaik",
         "diagnosis": "Diagnosis penyebab (6 kelas) ≥ 85 % pada data uji luar ruangan",
         "power": "Daya kendali ≤ 0,25 W",
         "latency": "Keputusan susunan di ESP32 dalam orde milidetik (< 1 s)"}
STATUS = {"met": "✅ terpenuhi", "not met": "❌ belum terpenuhi", "no measurement yet": "⏳ belum diukur"}
SUMBER = {"measured": "terukur", "measured (laptop)": "terukur (laptop)", "lab": "lab (lampu halogen)",
          "sim": "simulasi", "calc": "hitungan"}

sumber = st.radio("Data", ["device", "demo"], horizontal=True,
                  format_func=lambda s: "terukur (ESP32)" if s == "device" else "DEMO (data lab diputar ulang)")
if sumber == "demo":
    st.warning("DEMO bukan bukti: hanya untuk melihat cara kerja halaman. Tiruan tidak punya sapuan per panel, jadi "
               "tidak ada acuan MLPE.")
ev = U.get("/evidence", source=sumber)
st.caption(f"{ev['rounds_used']} dari {ev['rounds_total']} putaran scan/audit dipakai. Target dinyatakan terpenuhi "
           "hanya dari bukti **terukur**; angka lab dan simulasi ditampilkan sebagai pembanding.")

for tg in ev["targets"]:
    with st.container(border=True):
        a, b = st.columns([4, 1])
        a.markdown(f"**{JUDUL.get(tg['id'], tg['target'])}**")
        b.markdown(STATUS.get(tg["status"], tg["status"]))
        if tg.get("needs"): st.caption(f"Yang dibutuhkan: {tg['needs']}")
        st.dataframe(pd.DataFrame([{"nilai": f"{e['value']:g}" if isinstance(e["value"], (int, float)) else str(e["value"]),
                                    "satuan": e["unit"], "sumber": SUMBER.get(e["source"], e["source"]),
                                    "n": e["n"], "keterangan": e["detail"]} for e in tg["evidence"]]),
                     hide_index=True, width="stretch")

# ---------------- pemulihan daya: rincian ----------------
st.subheader("Pemulihan daya terhadap MLPE ideal")
rr = U.get("/evidence/rounds", source=sumber)
m = rr["summary"]["mlpe"]
if m:
    k = st.columns(4)
    k[0].metric("Pemulihan (AI − tetap terbaik)", f"{m['recovery_pts']:+.2f} poin", f"target ≥ {m['target_pts']:g} poin",
                delta_color="off")
    k[1].metric("AI (pemilih)", f"{m['ai_pct']:.1f} % MLPE")
    k[2].metric(f"Tetap terbaik ({m['best_fixed']})", f"{m['best_fixed_pct']:.1f} % MLPE")
    k[3].metric("Putaran dengan acuan MLPE", m["n"])
    rows = [{"pilihan": f"{t} tetap", "persen": v, "jenis": "tetap"} for t, v in m["pct_mlpe_by_fixed"].items()]
    rows += [{"pilihan": "AI (pemilih)", "persen": m["ai_pct"], "jenis": "AI"},
             {"pilihan": "Sapu semua, pilih terbaik (batas atas)", "persen": m["sweep_all_pct"], "jenis": "batas"}]
    df = pd.DataFrame(rows)
    urut = list(df.pilihan)
    dasar = alt.Chart(df).encode(
        y=alt.Y("pilihan:N", sort=urut, title=None),
        x=alt.X("persen:Q", title="Rata-rata daya (% dari MLPE ideal)", scale=alt.Scale(domain=[0, 100])),
        tooltip=[alt.Tooltip("pilihan:N", title="Pilihan"), alt.Tooltip("persen:Q", title="% MLPE", format=".2f")])
    batang = dasar.mark_bar(size=18, cornerRadiusEnd=4).encode(
        color=alt.condition(alt.datum.jenis == "AI", alt.value("#2a6fdb"), alt.value("#9aa3ad")))
    label = dasar.mark_text(align="left", dx=4).encode(text=alt.Text("persen:Q", format=".1f"))
    st.altair_chart((batang + label).properties(height=200), width="stretch")
    st.caption("Susunan tetap terbaik dipilih sesudah melihat semua data (pesaing terkuat). 4P bukan kandidat (di luar "
               f"jendela 24 V pengendali){'; 4P rata-rata ' + format(m['pct_mlpe_4p'], '.1f') + ' % MLPE' if m.get('pct_mlpe_4p') else ''}.")
else:
    st.info("Belum ada putaran dengan sapuan per panel (acuan MLPE). Jalankan scan penuh dengan firmware 3.2 di halaman "
            "**Ambil data**, atau **Audit keputusan AI** di halaman Langsung.")
rel = rr["summary"]["relative"]
if rel:
    st.caption(f"Tanpa MLPE (% dari yang terbaik terukur, seperti klaim lab): AI rugi {rel['ai_loss_pct']:.2f} %, tetap "
               f"terbaik {rel['best_fixed']} rugi {rel['best_fixed_loss_pct']:.2f} %; AI memilih yang terbaik pada "
               f"{rel['ai_matches_best_pct']:.0f} % putaran ({rel['n']} putaran).")
if rr["rounds"]:
    tab = []
    for r in reversed(rr["rounds"]):
        p = r["pct_mlpe"]
        tab.append({"waktu (UTC)": (r.get("at") or "")[:16].replace("T", " "), "jenis": r["kind"],
                    "kondisi": r.get("condition") or "-", "ulangan": f"u{r['repeat']}" if r.get("repeat") else "-",
                    "MLPE (W)": r["mlpe_w"], **{f"{t} % MLPE": p.get(t) for t in ("4S", "2S2P", "TCT", "4P")},
                    "pilihan AI": r["choice"], "oleh": U.label_keputusan(r["decided_by"]), "terbaik": r["best"],
                    "rugi AI (poin)": r["ai_loss_pts"], "rugi AI (%)": r["ai_loss_pct"],
                    "dipakai": "ya" if r["usable"] else "tidak", "alasan": r.get("reason") or ""})
    st.dataframe(pd.DataFrame(tab), hide_index=True, width="stretch")

# ---------------- daya kendali: isian multimeter ----------------
st.subheader("Daya kendali (multimeter)")
esp = [d["id"] for d in U.get("/devices") if d["kind"] == "esp32"]
with st.form("daya"):
    st.caption("Ukur arus catu 5 V ESP32 dan arus kumparan relai dengan multimeter yang ada, kalikan dengan tegangannya. "
               "Ulangi untuk tiap susunan aktif (jumlah relai yang menutup berbeda).")
    a, b, c = st.columns(3)
    p_esp = a.number_input("Daya ESP32 (W)", 0.0, 10.0, 0.0, 0.01, format="%.3f")
    p_rel = b.number_input("Daya relai (W)", 0.0, 20.0, 0.0, 0.01, format="%.3f")
    topo = c.selectbox("Susunan aktif saat diukur", ["4S", "2S2P", "TCT", "4P", "A", "B", "C", "D", "-"])
    alat = st.selectbox("Alat", esp or ["(tanpa alat)"])
    if st.form_submit_button("Simpan pengukuran"):
        if p_esp <= 0 or p_rel <= 0:
            st.error("Isi kedua angka (ESP32 dan relai).")
        else:
            data = {"entry": str(uuid.uuid4()), "topology": None if topo == "-" else topo}
            dev = alat if alat in esp else None
            U.post("/ingest/metrics", {"items": [
                {"device_id": dev, "name": "device_power_w", "value": p_esp, "unit": "W", "provenance": "manual", "data": data},
                {"device_id": dev, "name": "relay_power_w", "value": p_rel, "unit": "W", "provenance": "manual", "data": data}]})
            st.toast("Tersimpan"); st.rerun()

# ---------------- waktu terukur ----------------
st.subheader("Waktu terukur")
ms = U.get("/metrics/summary")
NAMA = {"sweep_ms": "sapuan (ms)", "switch_ms": "pindah susunan (ms)", "decision_us": "keputusan AI (µs)",
        "e2e_decision_ms": "akhir sapuan 4S → perintah pindah (ms)", "diagnosis_us": "diagnosis AI di ESP32 (µs)"}
rows = [{"besaran": NAMA[k], "n": v["n"], "median": v["p50"], "p95": v["p95"], "maks": v["max"],
         "sumber": ", ".join(v["provenance"])} for k, v in ms.items() if k in NAMA]
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("'emulated' = perkiraan dari mode demo, bukan pengukuran. Waktu keputusan selalu terukur (dihitung sungguhan "
               "di laptop atau di ESP32 dengan firmware 3.2).")
else:
    st.caption("Belum ada waktu tercatat.")

st.download_button("⬇ Unduh tabel Target vs Bukti (CSV)", U.api("GET", "/evidence.csv", params={"source": sumber}),
                   file_name="shadeshift_target_vs_bukti.csv", mime="text/csv")
