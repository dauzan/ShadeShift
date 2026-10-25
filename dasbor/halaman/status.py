"""Halaman Status: kesehatan server, gateway, model AI, kembaran digital, dan arti label sumber data."""
import os, sys
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

st.header("Status sistem")
if not U.server_hidup(): st.stop()

h = U.get("/health")
c = st.columns(3)
c[0].metric("Server", h["status"], f"basis data: {h['db']}", delta_color="off")
c[1].metric("Model AI (pemilih)", h["model"]["model_id"].split("@")[0], h["model"]["runtime"], delta_color="off")
c[2].metric("Kembaran digital", "tersedia" if h["twin"] == "available" else "tidak tersedia", delta_color="off")
if h["twin"] != "available": st.caption(h["twin"])

st.subheader("Alat dan gateway")
rows = []
for d in U.get("/devices"):
    if d["kind"] == "virtual": continue
    gw, stt = d.get("gateway") or {}, d.get("state") or {}
    esp = gw.get("esp32") or {}
    rows.append({"alat": d["id"], "jenis": "ESP32" if d["kind"] == "esp32" else "TIRUAN (demo)",
                 "online": "ya" if d["online"] else "tidak", "sambungan": d.get("transport"), "terakhir": d["last_seen"][:19],
                 "firmware": d.get("firmware") or "-",
                 "AI di ESP32": "-" if d["kind"] != "esp32" else
                                "tidak (firmware v2 asli, tanpa INFO)" if not esp else
                                f"tidak (firmware {esp.get('fw')}, pemilih di laptop)" if not esp.get("weights") else
                                "ya, bobot sama" if esp.get("weights_match") else "BOBOT BERBEDA",
                 "fitur": ", ".join(esp.get("features") or []) or "-",
                 "AI di gateway": gw.get("runtime", "-"), "diputuskan oleh": U.label_keputusan(gw.get("decided_by")),
                 "antrean belum terkirim": stt.get("outbox_pending"), "galat": stt.get("last_error") or ""})
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
else:
    st.info("Belum ada gateway yang terhubung.")

st.subheader("Model AI dan klaim yang boleh dipakai")
m = U.get("/model")
st.write(f"Model `{m['model_id']}`: regresi logistik, 14 fitur bentuk dari satu sapuan 4S, keluaran {', '.join(m['classes'])}. "
         f"Bobot (73 angka) dari `pemilih_bobot.h`, sama dengan yang dikompilasi ke ESP32.")
for k, v in m["claims"].items():
    st.markdown(f"- **{k}**: {v}")
st.caption("Diagnosis penyebab (6 kelas) hanya simulasi (78-82 %) dan gagal di data lab: tidak ditampilkan sebagai fitur.")

st.subheader("Arti label sumber data")
st.dataframe(pd.DataFrame([{"label": v, "arti": a} for v, a in [
    (U.SUMBER["device"], "diukur saat ini oleh ESP32 yang tersambung"),
    (U.SUMBER["demo"], "ESP32 tiruan memutar ulang kurva lab; waktu pindah/sapuan perkiraan"),
    (U.SUMBER["upload"], "berkas CSV yang diunggah pengguna"),
    (U.SUMBER["lab"], "dataset lab lampu halogen (120 kurva, tidak pernah diubah)")]]), hide_index=True, width="stretch")
