"""Halaman Peristiwa: jejak audit (perintah, perpindahan, keputusan AI, peringatan, galat) dengan ekspor CSV."""
import os, sys
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

st.header("Peristiwa (jejak audit)")
if not U.server_hidup(): st.stop()

alat = ["(semua)"] + [d["id"] for d in U.get("/devices")]
c1, c2, c3 = st.columns([2, 2, 1])
dev = c1.selectbox("Alat", alat)
jenis = c2.selectbox("Jenis", ["(semua)", "command", "switch", "alert", "error", "status", "info"])
n = c3.number_input("Jumlah", 20, 5000, 200, 20)
params = {"limit": int(n)}
if dev != "(semua)": params["device_id"] = dev
if jenis != "(semua)": params["kind"] = jenis
ev = U.get("/events", **params)
dec = U.get("/decisions", limit=int(n), **({"device_id": dev} if dev != "(semua)" else {})) if jenis == "(semua)" else []

rows = [{"waktu (UTC)": e["created_at"].replace("T", " ")[:19], "alat": e["device_id"] or "-",
         "sumber": U.label_sumber(e.get("source", "")) if e.get("source") in U.SUMBER else (e.get("source") or ""),
         "jenis": e["kind"], "pesan": e["message"]} for e in ev]
rows += [{"waktu (UTC)": d["created_at"].replace("T", " ")[:19], "alat": d["device_id"], "sumber": "",
          "jenis": "keputusan AI", "pesan": f"{d['choice']} oleh {U.label_keputusan(d['decided_by'])} ({d['trigger']}, "
          f"{'diterapkan' if d['applied'] else 'pengamatan'}, {d['latency_us'] / 1000:.1f} ms)" if d.get("latency_us")
          else f"{d['choice']} oleh {U.label_keputusan(d['decided_by'])} ({d['trigger']})"} for d in dec]
df = pd.DataFrame(rows)
if df.empty:
    st.info("Belum ada peristiwa.")
else:
    st.dataframe(df.sort_values("waktu (UTC)", ascending=False), hide_index=True, width="stretch")
st.download_button("Unduh jejak audit (CSV)", U.api("GET", "/events.csv",
                   params={"device_id": dev} if dev != "(semua)" else {}),
                   file_name="shadeshift_peristiwa.csv", mime="text/csv")
