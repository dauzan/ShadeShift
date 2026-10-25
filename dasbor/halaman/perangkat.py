"""Perangkat: pusat status semua bagian sistem (docs/CONTRACT.md §25). Tiap baris: bagian, keadaannya (Baik, Perlu dicek,
Belum diperiksa, Tidak terhubung, Tidak tersedia, Mati, Mode demo), apa yang terlihat, dan kapan diperiksa. Sebuah bagian
disebut Baik hanya bila ada laporan atau pengukuran yang menunjukkannya bekerja."""
import html
import os, sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

WARNA = {"Baik": "#15803D", "Perlu dicek": "#B91C1C", "Tidak terhubung": "#B91C1C", "Belum diperiksa": "#64748B",
         "Tidak tersedia": "#64748B", "Mati": "#B45309", "Mode demo": "#92400E"}
RINGKAS = {"ok": "#15803D", "problem": "#B91C1C", "offline": "#64748B", "demo": "#92400E"}
_GAYA = """<style>
.pk{border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;margin-bottom:6px}
.pk table{width:100%;border-collapse:collapse;font-size:.92rem;color:#0F172A}
.pk th{background:#F8FAFC;text-align:left;font-weight:600;padding:9px 12px;border-bottom:1px solid #E2E8F0}
.pk td{padding:9px 12px;border-bottom:1px solid #F1F5F9;vertical-align:top}
.pk td.n{width:30%;font-weight:500}.pk td.s{width:14%;white-space:nowrap;font-weight:600}.pk td.w{width:14%;color:#64748B;white-space:nowrap}
</style>"""

dev = U.kepala("Perangkat")
if not dev:
    st.stop()


@st.fragment(run_every=10.0)
def isi(device_id, demo):
    try:
        d = U.get(f"/devices/{device_id}/perangkat")
    except (U.ServerMati, RuntimeError) as e:
        st.error(f"Status perangkat tidak dapat dibaca: {e}")
        return
    r = d["ringkasan"]
    st.markdown(f"<div style='font-size:1.1rem;font-weight:600;color:{RINGKAS.get(r['level'], '#0F172A')}'>"
                f"{html.escape(r['text'])}</div>", unsafe_allow_html=True)
    for g in d["grup"]:
        st.subheader(g["judul"])
        rows = "".join(
            f"<tr><td class='n'>{html.escape(b['nama'])}</td>"
            f"<td class='s' style='color:{WARNA.get(b['keadaan'], '#0F172A')}'>{html.escape(b['keadaan'])}</td>"
            f"<td>{html.escape(b['rincian'])}</td><td class='w'>{html.escape(U.umur(b['waktu'])) if b['waktu'] else ''}</td></tr>"
            for b in g["baris"])
        st.html(_GAYA + "<div class='pk'><table><thead><tr><th>Bagian</th><th>Keadaan</th><th>Keterangan</th>"
                f"<th>Diperiksa</th></tr></thead><tbody>{rows}</tbody></table></div>")


demo = dev["kind"] == "emulator"
if demo:
    st.warning("Mode demo: ESP32 tiruan memutar ulang kurva lab. Tidak ada perangkat keras untuk diperiksa.")
a, _ = st.columns([1, 3])
if a.button("Periksa ulang perangkat", width="stretch", disabled=demo or not dev["online"],
            help="ESP32 diminta melaporkan versi firmware dan bagian yang terpasang di jalur I2C. Hanya membaca; relai tidak "
                 "berpindah."):
    U.kirim_perintah(dev["id"], "raw", "INFO", nama="Permintaan laporan ESP32")
    U.kirim_perintah(dev["id"], "raw", "SCAN", nama="Pemeriksaan jalur I2C")
st.caption("Halaman ini diperbarui setiap 10 detik. Sebuah bagian disebut Baik hanya bila ESP32 melaporkannya atau "
           "pengukuran menunjukkan bagian itu bekerja.")
isi(dev["id"], demo)
