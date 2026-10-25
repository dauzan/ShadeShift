"""Halaman Kembaran Digital: model kawat 4 panel surya dan kotak kendali, tampak atas terkunci. Cermin langsung (hanya yang
terukur) dan What-if (simulasi: kuas bayangan, perkiraan daya tiap susunan, pilihan AI, banding dengan nyata).
Halamannya disajikan server lokal (/twin, docs/CONTRACT.md §18) dan ditanam di sini; tidak ada yang dimuat dari internet."""
import os, sys

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

if not U.server_hidup(): st.stop()
alat = [d for d in U.get("/devices") if d["kind"] != "virtual"]
if not alat:
    st.info("Belum ada alat. Jalankan `run.py live` (ESP32) atau `run.py demo`.")
    st.stop()
alat.sort(key=lambda d: (not d["online"], d["kind"] != "esp32", d["id"]))
ids = [d["id"] for d in alat]
if st.session_state.get("alat_kembaran") not in ids: st.session_state.alat_kembaran = ids[0]
pilih = st.selectbox("Alat", ids, key="alat_kembaran",
                     format_func=lambda i: next(f"{d['id']}  ({'ESP32' if d['kind'] == 'esp32' else 'TIRUAN / demo'}, "
                                                f"{'online' if d['online'] else 'offline'})" for d in alat if d["id"] == i))
components.iframe(f"{U._settings().api_url}/twin?device_id={pilih}", height=860, scrolling=True)
st.caption("Kembaran = simulasi yang dicocokkan pada lampu lab (galat daya ~8 % di 7 kondisi lab); di bawah matahari "
           "ketelitiannya belum diketahui walau sudah dikalibrasi. Mode What-if tidak mengubah data alat.")
