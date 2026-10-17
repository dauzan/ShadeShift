"""Dasbor SHADESHIFT (lapis L1 digitalisasi). Jalankan dari folder proyek:  .venv\\Scripts\\python run.py dashboard
(atau semuanya sekaligus: run.py demo / run.py live).

Dasbor ini klien API server lokal (http://127.0.0.1:8000): tidak membuka port serial dan tidak menjalankan model AI.
Data dari ESP32 masuk lewat gateway -> server -> basis data, jadi menyegarkan halaman atau membuka tab kedua aman.
Semua angka berlabel sumbernya: terukur (ESP32), DEMO (data lab diputar ulang), unggahan, lab, kembaran (simulasi)."""
import os, sys
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import umum as U  # noqa: E402

st.set_page_config(page_title="SHADESHIFT", page_icon="☀️", layout="wide")
H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "halaman")
halaman = st.navigation([
    st.Page(os.path.join(H, "langsung.py"), title="Langsung", icon="📡", default=True),
    st.Page(os.path.join(H, "putar_ulang.py"), title="Putar ulang", icon="🔁"),
    st.Page(os.path.join(H, "unggah.py"), title="Unggah CSV", icon="📤"),
    st.Page(os.path.join(H, "peristiwa.py"), title="Peristiwa", icon="📜"),
    st.Page(os.path.join(H, "status.py"), title="Status", icon="🩺"),
])

with st.sidebar:
    st.title("☀️ SHADESHIFT")
    U.tombol_stop("stop_sidebar")
    try:
        s = U.get("/settings")
    except (U.ServerMati, RuntimeError):
        s = None
    if s:
        st.markdown("**Kembaran digital (daya harapan)**")
        skala = st.slider("Skala cahaya (1,0 = lampu dekat, kondisi V1c)", 0.2, 2.0, float(s.get("twin_scale", 1.0)), 0.01)
        bay = st.selectbox("Bayangan yang diasumsikan", list(U.BAYANGAN), format_func=U.BAYANGAN.get,
                           index=list(U.BAYANGAN).index(s.get("twin_shading", "none")))
        amb = st.slider("Ambang peringatan selisih daya (%)", 5, 50, int(s.get("alert_threshold_pct", 15)), 1)
        baru = {"twin_scale": round(skala, 3), "twin_shading": bay, "alert_threshold_pct": amb}
        if any(baru[k] != s.get(k) for k in baru):
            U.put("/settings", baru)
        if st.button("Kalibrasi skala dari sapuan terakhir", width="stretch",
                     help="Pakai hanya bila sapuan terakhir alat TANPA bayangan."):
            rec = [x for x in U.get("/sweeps", limit=200) if x["source"] in ("device", "demo")]
            if rec:
                try:
                    st.toast(f"Skala cahaya = {U.post('/twin/calibrate', {'sweep_id': rec[0]['id']})['scale']}")
                except RuntimeError as e:
                    st.error(str(e))
        st.caption("Kembaran = simulasi yang dicocokkan pada lampu lab (galat daya ~8 % di 7 kondisi lab); di tempat lain "
                   "ketelitiannya belum diketahui walau sudah dikalibrasi. Selisih besar = indikasi kelainan, **bukan** "
                   "diagnosis tervalidasi.")

halaman.run()
