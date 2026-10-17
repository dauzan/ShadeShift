"""Halaman Unggah CSV: kirim berkas kurva I-V ke server; tiap berkas diterima atau ditolak dengan alasannya."""
import os, sys
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

st.header("Unggah CSV")
if not U.server_hidup(): st.stop()
st.markdown(
    "Format yang diterima (maks. 50 berkas, 5 MB per berkas):\n"
    "- **Format firmware / logger**: baris `#` (`# MULAI`, `# topologi=...`), kolom `V,I,P`. Sama dengan berkas `data_lab`.\n"
    "- **CSV biasa**: baris judul berisi kolom tegangan dan arus, misalnya `V,I` (ampere) atau `V,I_mA` (miliampere).\n\n"
    "Susunan dibaca dari isi berkas atau dari nama berkas (`<kondisi>_<susunan>_u<n>.csv`). Untuk sapuan 4S, server "
    "menjalankan pemilih (AI) dan menampilkan keputusannya. Contoh berkas ada di folder `samples/`.")

c1, c2 = st.columns(2)
topo = c1.selectbox("Susunan (bila tidak tertulis di berkas)", ["(dari berkas)"] + U.TOPO)
kond = c2.text_input("Kondisi (opsional, mis. V3_opak)")
berkas = st.file_uploader("Pilih berkas CSV", type=["csv", "txt"], accept_multiple_files=True)

if berkas and st.button("Unggah", type="primary"):
    data = {}
    if topo != "(dari berkas)": data["topology"] = topo
    if kond.strip(): data["condition"] = kond.strip()
    files = [("files", (f.name, f.getvalue(), "text/csv")) for f in berkas]
    try:
        with st.spinner("Mengunggah dan memeriksa..."):
            st.session_state.hasil_unggah = U.api("POST", "/uploads", timeout=300, files=files, data=data)["results"]
    except (RuntimeError, U.ServerMati) as e:
        st.error(f"Unggah gagal: {e}")

hasil = st.session_state.get("hasil_unggah")
if hasil:
    STATUS = {"ok": "diterima", "rejected": "DITOLAK", "duplicate": "sudah ada (tidak disimpan lagi)"}
    rows = []
    for r in hasil:
        sw = r.get("sweeps") or []
        rows.append({"berkas": r["filename"], "status": STATUS.get(r["status"], r["status"]),
                     "alasan": r.get("error") or "", "sapuan": len(sw) or len(r.get("sweep_ids") or []),
                     "susunan": ", ".join(s["topology"] for s in sw),
                     "Pmax (W)": ", ".join(f"{s['pmax']:.4f}" for s in sw if s["pmax"] is not None),
                     "pemilih (AI)": ", ".join(f"{s['decision']['choice']} ({U.label_keputusan(s['decision']['decided_by'])})"
                                               for s in sw if s.get("decision"))})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    ok = [s for r in hasil if r["status"] == "ok" for s in r["sweeps"]][:6]
    if ok:
        sweeps = [U.get(f"/sweeps/{s['id']}") for s in ok]
        lap = [U.lapis_sapuan(sw, f"{sw['topology']} {sw['label']}") for sw in sweeps]
        g1, g2 = st.columns(2)
        g1.altair_chart(U.grafik(lap, "I_mA", "Arus (mA)", "unggahan CSV"), width="stretch")
        g2.altair_chart(U.grafik(lap, "P_W", "Daya (W)", "unggahan CSV"), width="stretch")
        st.caption("Semua unggahan tersimpan; lihat lagi di **Putar ulang → Unggahan CSV**.")
