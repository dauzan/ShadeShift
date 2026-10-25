"""Halaman Model AI: melatih model diagnosis dan pemilih dengan data terukur, menguji dengan adil (hari lain, atau scan
lain), menyimpan semua versi, dan memilih yang aktif (docs/CONTRACT.md §14)."""
import os, sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402
from shadeshift import fieldwork  # noqa: E402

st.header("Model AI")
if not U.server_hidup(): st.stop()

SUMBER = {"real": "terukur (sesi Ambil data)", "lab": "lab (lampu halogen, 30 putaran)", "sim": "simulasi"}
TUGAS = {"diagnosis": "Diagnosis penyebab (6 kelas)", "pattern": "Pola modul terdampak (dari sapuan topologi)",
         "selector": "Pemilih susunan (4S / 2S2P / TCT)"}
JENIS = {"logreg": "regresi logistik", "tree": "pohon keputusan"}
NAMA_KELAS = {**fieldwork.DIAGNOSIS, **U.POLA, "4S": "4S", "2S2P": "2S2P", "TCT": "TCT"}

# ---------------- data ----------------
st.subheader("Data yang tersedia")
ringkas = U.get("/training/data")
rows = []
for src in ("real", "lab"):
    d = ringkas.get(src)
    if d:
        rows.append({"sumber": SUMBER[src], "putaran": d["rounds"], "hari": ", ".join(d["days"]),
                     **{fieldwork.DIAGNOSIS.get(k, k): v for k, v in d["by_class"].items()}})
if rows:
    st.dataframe(pd.DataFrame(rows).fillna(0), hide_index=True, width="stretch")
sim = ringkas["sim"]
st.caption(f"Simulasi: {sim['rounds']} putaran ({sim['note']}). Satu putaran = bayangan yang sama dilihat lewat 4S, 2S2P, "
           "TCT dan 4P. Uji yang adil butuh data terukur dari **dua hari** (latih di satu hari, uji di hari lain); dengan satu "
           "hari dipakai uji 'scan lain' dan hasilnya ditandai bukti lebih lemah. Kelas tanpa contoh terukur tidak bisa diuji.")
if not ringkas.get("real"):
    st.info("Belum ada sesi terukur. Ambil data di halaman **Ambil data**, atau impor zip sesi dari laptop lain di bawah.")

with st.expander("Impor zip sesi dari laptop lain"):
    berkas = st.file_uploader("Zip dari halaman Ambil data (Siapkan zip → Unduh zip)", type=["zip"])
    if berkas is not None and st.button("Impor"):
        try:
            r = U.api("POST", "/sessions/import", timeout=300, files={"file": (berkas.name, berkas.getvalue(), "application/zip")})
            st.success(f"Diimpor: sesi {r['session_id']}, {r['scans']} scan, {r['sweeps']} sapuan"
                       + (" (TIRUAN, bukan data nyata)" if r["source"] == "demo" else ""))
        except RuntimeError as e:
            st.error(str(e))

# ---------------- latih ----------------
st.subheader("Latih kandidat baru")
a, b, c = st.columns(3)
tugas = a.selectbox("Tugas", list(TUGAS), format_func=TUGAS.get)
jenis = b.selectbox("Jenis model", ["logreg"] if tugas == "selector" else ["logreg", "tree"], format_func=JENIS.get,
                    help="Pemilih harus regresi logistik: itu yang dijalankan pemilih.h di ESP32.")
bawaan = ["real", "lab"] if ringkas.get("real") else ["lab"]
sumber = c.multiselect("Data latih", list(SUMBER), default=bawaan, format_func=SUMBER.get)
params = {}
d1, d2, d3 = st.columns(3)
if jenis == "tree":
    params["max_depth"] = d1.slider("Kedalaman pohon", 1, 8, 4)
sim_n = d2.select_slider("Putaran simulasi per kelas", [100, 200, 500, 1000], 200, disabled="sim" not in sumber)
hari = (ringkas.get("real") or {}).get("days") or []
uji = d3.selectbox("Hari uji (data terukur)", [None] + hari, format_func=lambda h: "otomatis (hari terakhir)" if h is None else h,
                   disabled=len(hari) < 2)
if st.button("Latih dan uji", type="primary", disabled=not sumber):
    with st.spinner("Melatih dan menguji... (simulasi pertama kali bisa 1-3 menit)"):
        try:
            m = U.api("POST", "/models/train", timeout=900, json={"task": tugas, "kind": jenis, "sources": sumber,
                                                                   "params": params, "test_day": uji, "sim_n": sim_n})
            st.session_state.model_pilih = m["id"]
            st.success(f"Kandidat {m['model_id']} tersimpan (belum aktif).")
        except RuntimeError as e:
            st.error(f"Tidak bisa dilatih: {e}")

# ---------------- registri ----------------
st.subheader("Semua model")
semua = U.get("/models")
if not semua:
    st.caption("Belum ada model."); st.stop()
rows = []
for m in semua:
    r = m["report"]
    if m["task"] == "selector" and r.get("selection"):
        s = r["selection"]["candidate"]["relative"] or {}
        hasil = f"rugi {s.get('ai_loss_pct', 0):.2f} % (aktif saat dilatih: {r['selection']['active']['relative']['ai_loss_pct']:.2f} %)"
    elif "accuracy" in r:
        hasil = f"akurasi {r['accuracy']:.1f} %, seimbang {r['balanced_accuracy']:.1f} %"
    else:
        hasil = r.get("note", "")[:90]
    rows.append({"id": m["id"], "aktif": "✅" if m["active"] else "", "tugas": TUGAS[m["task"]].split(" (")[0],
                 "model": m["model_id"], "jenis": JENIS[m["kind"]], "data latih": ", ".join(m["sources"]),
                 "diuji pada": m["evidence"], "cara uji": r.get("test_mode", "-"), "hasil": hasil,
                 "dibuat": m["created_at"][:16].replace("T", " ")})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

ids = [m["id"] for m in semua]
if st.session_state.get("model_pilih") not in ids: st.session_state.model_pilih = ids[0]
pilih = st.selectbox("Rincian model", ids, key="model_pilih",
                     format_func=lambda i: next(f"{m['model_id']} ({TUGAS[m['task']].split(' (')[0]})" for m in semua if m["id"] == i))
m = U.get(f"/models/{pilih}")
r = m["report"]
if r.get("note"): st.caption(r["note"])
if "confusion" in r:
    k1, k2, k3 = st.columns(3)
    k1.metric("Akurasi", f"{r['accuracy']:.1f} %")
    k2.metric("Akurasi seimbang", f"{r['balanced_accuracy']:.1f} %", help="Rata-rata recall per kelas: tidak tertipu kelas yang banyak.")
    k3.metric("Putaran uji", r["n_test"])
    st.caption(f"Cara uji: {r['test_mode']}. Diuji pada data {r['evidence']}"
               + ("; simulasi tidak pernah dipakai sebagai bukti." if r["evidence"] != "real" else "."))
    nama = [NAMA_KELAS.get(k, k) for k in r["classes"]]
    cm = pd.DataFrame(r["confusion"], index=[f"benar: {n}" for n in nama], columns=[f"tebakan: {n}" for n in nama])
    ada = [i for i, row in enumerate(r["confusion"]) if sum(row)] or list(range(len(nama)))
    st.markdown("Matriks kebingungan (baris = label sebenarnya, kolom = tebakan model)")
    st.dataframe(cm.iloc[ada], width="stretch")
    if r.get("classes_not_tested"):
        st.warning("Kelas tanpa contoh uji (belum bisa dinilai): " + ", ".join(NAMA_KELAS.get(k, k) for k in r["classes_not_tested"]))
    latih = r.get("trained_on", {})
    st.caption("Data latih: " + "; ".join(f"{SUMBER.get(s, s)} {d['rounds']} putaran" for s, d in latih.items()))
if r.get("selection"):
    s = r["selection"]
    c, a_ = s["candidate"]["relative"], s["active"]["relative"]
    st.markdown(f"Pada putaran uji yang sama: kandidat rugi **{c['ai_loss_pct']:.2f} %**, pemilih aktif rugi "
                f"**{a_['ai_loss_pct']:.2f} %**, susunan tetap terbaik ({a_['best_fixed']}) rugi {a_['best_fixed_loss_pct']:.2f} % "
                "(% dari yang terbaik terukur).")
    if s["candidate"].get("mlpe") and s["active"].get("mlpe"):
        st.caption(f"Terhadap MLPE ideal: kandidat {s['candidate']['mlpe']['ai_pct']:.1f} %, aktif {s['active']['mlpe']['ai_pct']:.1f} %.")

x, y = st.columns(2)
nama_h = "pemilih_bobot.h" if m["task"] == "selector" else "diagnosis_model.h"
x.download_button(f"⬇ Unduh {nama_h} (ESP32)", U.api("GET", f"/models/{pilih}/header.h"), file_name=nama_h, mime="text/plain")
if m["active"]:
    y.success("Model ini aktif.")
else:
    if m["task"] == "selector":
        y.warning("Mengaktifkan pemilih menulis ulang bobot di folder model, uji ESP32, firmware dan berkas ONNX. "
                  "Sesudahnya: jalankan ulang run.py live/demo dan unggah ulang firmware ke ESP32.")
    if y.button("Jadikan aktif"):
        try:
            res = U.post(f"/models/{pilih}/activate")
            for d in res["done"]: st.toast(d)
            st.rerun()
        except RuntimeError as e:
            st.error(str(e))
