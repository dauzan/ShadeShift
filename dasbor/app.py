"""Dasbor SHADESHIFT. Jalankan dari folder proyek:  .venv\\Scripts\\python run.py dashboard
(atau semuanya sekaligus: run.py demo / run.py live).

Tampilan konsumen (docs/CONTRACT.md §19, §25, §29): Beranda (model 3D dan kondisi panel), Kurva I-V, Riwayat, Perangkat
(status semua bagian sistem), Rekomendasi Rangkaian (saran AI dan perubahan rangkaian yang disetujui pengguna). Halaman tim (Bukti: janji proposal dan target, §24) dan halaman teknis lama (Langsung, Ambil data,
Target vs Bukti, Model AI, L3, Putar ulang, Unggah CSV, Peristiwa, Status, Kembaran Digital)
tetap ada di folder halaman/ tetapi tidak ditampilkan; tambahkan kembali ke daftar di bawah bila dibutuhkan.

Dasbor ini klien API server lokal (http://127.0.0.1:8000): tidak membuka port serial dan tidak menjalankan model AI.
Semua angka berlabel sumbernya; data demo selalu ditandai mode demo."""
import os, sys
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import umum as U  # noqa: E402,F401

st.set_page_config(page_title="SHADESHIFT", layout="wide", menu_items={"About": "SHADESHIFT"})
# The page shows only SHADESHIFT: hide the framework's menu and deploy button, its run-status indicator, the coloured
# top line and the footer. The toolbar container stays: it holds the top navigation links.
st.html("""<style>
[data-testid="stMainMenu"], [data-testid="stAppDeployButton"], [data-testid="stStatusWidget"], [data-testid="stDecoration"],
footer { display: none !important; }
header[data-testid="stHeader"] { background: #ffffff; border-bottom: 1px solid #e2e8f0; }
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
[data-testid="stElementToolbar"] { display: none !important; }
</style>""")
H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "halaman")
halaman = st.navigation([
    st.Page(os.path.join(H, "beranda.py"), title="Beranda", default=True),
    st.Page(os.path.join(H, "kurva_iv.py"), title="Kurva I-V", url_path="kurva-iv"),
    st.Page(os.path.join(H, "riwayat.py"), title="Riwayat"),
    st.Page(os.path.join(H, "perangkat.py"), title="Perangkat"),
    st.Page(os.path.join(H, "rangkaian.py"), title="Rekomendasi Rangkaian", url_path="rangkaian"),
], position="top")
halaman.run()
