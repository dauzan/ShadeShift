"""Halaman Putar ulang: kurva tersimpan di basis data (data lab, unggahan CSV, dan sesi rekaman alat/demo)."""
import os, sys
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

st.header("Putar ulang kurva tersimpan")
if not U.server_hidup(): st.stop()

SARAN = {"V3_opak": "opak_A", "V3_paranet": "paranet_A", "V4_paranet": "paranet_AB", "V6_paranet": "paranet_AD"}
KLAIM_LAB = ("lab (lampu halogen, 30 set, 6 pola): rugi pemilih 0,82 % vs 2,71 % susunan tetap terbaik (2S2P), di antara "
             "4S/2S2P/TCT; 4P dikecualikan oleh jendela 24 V (4P terukur tertinggi di 30 set lab)")


def grafik_set(sweeps, catatan=None, harapan=None, shading="none", scale=1.0):
    lap = [U.lapis_sapuan(sw, f"{sw['topology']} terukur") for sw in sweeps]
    if harapan:
        for sw in sweeps:
            kv = U.kurva_kembaran(sw["topology"], max(sw["points"]["v"]), scale, shading)
            if kv: lap.append(U.lapis_kembaran(kv["v"], kv["i"], sw["topology"]))
    g1, g2 = st.columns(2)
    g1.markdown("**Kurva I-V**"); g1.altair_chart(U.grafik(lap, "I_mA", "Arus (mA)", catatan), width="stretch")
    g2.markdown("**Kurva P-V**"); g2.altair_chart(U.grafik(lap, "P_W", "Daya (W)", catatan), width="stretch")


sumber = st.radio("Sumber", ["Data lab (lampu halogen)", "Unggahan CSV", "Sesi rekaman (alat / demo)"], horizontal=True)

# ============ data lab ============
if sumber.startswith("Data lab"):
    kond = U.get("/conditions", source="lab")
    if not kond:
        st.info("Data lab belum diimpor ke basis data.")
        if st.button("Impor 120 kurva lab", type="primary"):
            with st.spinner("Mengimpor (berkas lab hanya dibaca, tidak diubah)..."):
                r = U.api("POST", "/import/lab", timeout=300, json={"include_anomalies": False})
            st.success(f"{r['imported']} kurva diimpor."); st.rerun()
        st.stop()
    nama = [k["condition"] for k in kond]
    c1, c2, c3 = st.columns([3, 1, 2])
    k = c1.selectbox("Kondisi", nama, index=nama.index("V4_paranet65") if "V4_paranet65" in nama else 0)
    reps = next(x["repeats"] for x in kond if x["condition"] == k)
    u = c2.selectbox("Ulangan", sorted(reps, key=int))
    saran = next((v for p, v in SARAN.items() if k.startswith(p)), "none")
    shading = c3.selectbox("Bayangan yang diasumsikan kembaran", list(U.BAYANGAN), index=list(U.BAYANGAN).index(saran),
                           format_func=U.BAYANGAN.get, help="Kembaran dicocokkan pada V1c (galat daya ~8 % di 7 kondisi lab). "
                           "Untuk V1/V1b (lampu jauh) daya harapan terlalu tinggi.")
    ids = reps[u]
    sweeps = [U.get(f"/sweeps/{ids[t]}") for t in U.TOPO if t in ids]
    try: harapan = U.get("/twin/expected", scale=1.0, shading=shading)["pmax"]
    except (RuntimeError, U.ServerMati): harapan = {}
    rows = []
    for sw in sweeps:
        ph = harapan.get(sw["topology"])
        rows.append({"susunan": sw["topology"], "Voc (V)": round(sw["voc"], 2), "Pmax terukur (W)": round(sw["pmax"], 4),
                     "Vmp (V)": round(sw["vmp"], 2), "harapan kembaran (W)": round(ph, 4) if ph else None,
                     "selisih (%)": round((sw["pmax"] - ph) / ph * 100, 1) if ph else None,
                     "lengkap": "ya" if sw["complete"] else "TIDAK (baris hilang)",
                     "layak 24 V": "ya" if sw["topology"] != "4P" else "tidak (Voc di bawah 30 V)"})
    s4 = next((sw for sw in sweeps if sw["topology"] == "4S"), None)
    layak = {sw["topology"]: sw["pmax"] for sw in sweeps if sw["topology"] in ("4S", "2S2P", "TCT")}
    m = st.columns(4)
    if s4 and s4.get("decision") and layak:
        pil, best = s4["decision"]["choice"], max(layak, key=layak.get)
        m[0].metric("Pemilih (dari sapuan 4S)", pil)
        m[1].metric("Terbaik terukur (4S/2S2P/TCT)", best)
        if pil in layak: m[2].metric("Rugi pilihan pemilih", f"{(layak[best] - layak[pil]) / layak[best] * 100:.2f}%")
        if "2S2P" in layak: m[3].metric("Rugi bila tetap 2S2P", f"{(layak[best] - layak['2S2P']) / layak[best] * 100:.2f}%")
        st.caption(f"Keputusan dihitung oleh {U.label_keputusan(s4['decision']['decided_by'])} dari kurva lab.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    tampil = st.multiselect("Tampilkan", [sw["topology"] for sw in sweeps],
                            default=[sw["topology"] for sw in sweeps if sw["topology"] != "4P"])
    grafik_set([sw for sw in sweeps if sw["topology"] in tampil], harapan=bool(harapan), shading=shading)

    with st.expander("Ringkasan semua set lab (pemilih vs susunan tetap)"):
        semua = U.get("/sweeps", source="lab", limit=1000)
        per = {}
        for s in semua:
            per.setdefault((s["condition"], s["repeat"]), {})[s["topology"]] = s
        baris = []
        for (kd, rp), t in sorted(per.items()):
            if not all(x in t for x in ("4S", "2S2P", "TCT")) or not t["4S"].get("decision"): continue
            pm = {x: t[x]["pmax"] for x in ("4S", "2S2P", "TCT")}; b = max(pm.values()); pil = t["4S"]["decision"]["choice"]
            baris.append({"kondisi": kd, "ulangan": rp, "terbaik": max(pm, key=pm.get), "pemilih": pil,
                          "rugi pemilih (%)": (b - pm[pil]) / b * 100, "rugi tetap 2S2P (%)": (b - pm["2S2P"]) / b * 100,
                          "rugi tetap TCT (%)": (b - pm["TCT"]) / b * 100, "rugi tetap 4S (%)": (b - pm["4S"]) / b * 100})
        df = pd.DataFrame(baris)
        if not df.empty:
            st.write(f"{len(df)} set. **{KLAIM_LAB}**. Rata-rata rugi terhadap terbaik terukur:")
            st.dataframe(df.drop(columns=["kondisi", "ulangan", "terbaik", "pemilih"]).mean().round(2).to_frame("rata-rata").T,
                         width="stretch")
            st.dataframe(df.round(2), hide_index=True, width="stretch")

# ============ unggahan ============
elif sumber.startswith("Unggahan"):
    ups = [x for x in U.get("/uploads") if x["status"] == "ok"]
    if not ups:
        st.info("Belum ada unggahan. Pakai halaman **Unggah CSV**."); st.stop()
    up = st.selectbox("Berkas", ups, format_func=lambda x: f"#{x['id']} {x['filename']} ({x['uploaded_at'][:19]})")
    rows = U.get("/sweeps", upload_id=up["id"])
    st.dataframe(U.tabel_sapuan(rows), hide_index=True, width="stretch")
    grafik_set([U.get(f"/sweeps/{s['id']}") for s in rows[:6]], catatan="unggahan CSV")

# ============ sesi rekaman ============
else:
    runs = [r for r in U.get("/runs") if r["source"] in ("device", "demo") and r["n_sweeps"]]
    if not runs:
        st.info("Belum ada sesi berisi sapuan. Jalankan alat atau demo di halaman **Langsung**."); st.stop()
    run = st.selectbox("Sesi", runs, format_func=lambda r: f"#{r['id']} {r['device_id']} · {U.label_sumber(r['source'])} · "
                       f"{r['started_at'][:19]} · {r['n_sweeps']} sapuan")
    rows = U.get("/sweeps", run_id=run["id"], limit=1000)
    if run["source"] == "demo":
        st.warning("DEMO: sesi ini memutar ulang kurva lab; bukan pengukuran.")
    st.dataframe(U.tabel_sapuan(rows), hide_index=True, width="stretch")
    pilihan = st.multiselect("Tampilkan sapuan (id)", [s["id"] for s in rows], default=[s["id"] for s in rows[:2]])
    if pilihan:
        grafik_set([U.get(f"/sweeps/{i}") for i in pilihan[:6]],
                   catatan="DEMO: kurva lab diputar ulang" if run["source"] == "demo" else None)
    st.download_button("Unduh peristiwa sesi (CSV)", U.api("GET", "/events.csv", params={"device_id": run["device_id"],
                       "since": run["started_at"]}), file_name=f"peristiwa_sesi_{run['id']}.csv", mime="text/csv")
