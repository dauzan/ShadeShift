"""Bukti: janji proposal dan empat target di samping buktinya, uji coba di papan, dan daya kendali (docs/CONTRACT.md §24).
Hanya data dari ESP32 nyata yang dihitung sebagai bukti; angka lab, simulasi dan hitungan ditampilkan sebagai pembanding.
Perpindahan susunan otomatis sengaja tidak dimuat (menunggu kepastian standar)."""
import html
import os, sys
import uuid

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

WARNA = {"Terbukti": "#15803D", "Terpenuhi": "#15803D", "Sebagian": "#B45309", "Belum": "#B91C1C",
         "Belum terpenuhi": "#B91C1C", "Belum diukur": "#64748B"}
_GAYA = """<style>
.bk{border:1px solid #E2E8F0;border-radius:8px;overflow:hidden}
.bk table{width:100%;border-collapse:collapse;font-size:.92rem;color:#0F172A}
.bk th{background:#F8FAFC;text-align:left;font-weight:600;padding:9px 12px;border-bottom:1px solid #E2E8F0}
.bk td{padding:9px 12px;border-bottom:1px solid #F1F5F9;vertical-align:top}
.bk td.s{white-space:nowrap;font-weight:600}
.tg{border:1px solid #E2E8F0;border-radius:8px;padding:14px 16px;margin-bottom:12px;color:#0F172A}
.tg .h{display:flex;justify-content:space-between;gap:16px;font-weight:600;font-size:1rem}
.tg .l{margin:8px 0 2px;font-size:.78rem;letter-spacing:.04em;text-transform:uppercase;color:#64748B}
.tg p{margin:2px 0;font-size:.92rem}
.tg p.m{color:#475569}
</style>"""


def kata(status):
    return f"<span style='color:{WARNA.get(status, '#0F172A')}'>{html.escape(status)}</span>"


def tabel(kepala, baris, kolom_status=None):
    th = "".join(f"<th>{html.escape(k)}</th>" for k in kepala)
    tr = "".join("<tr>" + "".join(f"<td class='s'>{kata(v)}</td>" if n == kolom_status else f"<td>{html.escape(str(v))}</td>"
                                  for n, v in enumerate(b)) + "</tr>" for b in baris)
    st.html(_GAYA + f"<div class='bk'><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>")


dev = U.kepala("Bukti")
if not dev:
    st.stop()
try:
    b = U.get("/bukti")
except (U.ServerMati, RuntimeError) as e:
    st.error(f"Bukti tidak dapat dibaca: {e}")
    st.stop()
st.caption(b["catatan"])
if b["demo_only"]:
    st.info("Belum ada ESP32 nyata yang pernah terhubung, jadi bukti dari papan masih kosong. Data mode demo tidak "
            "dihitung sebagai bukti.")

st.subheader("Janji proposal")
tabel(["Janji", "Keadaan", "Bukti"], [(j["janji"], j["status"], j["bukti"]) for j in b["janji"]], kolom_status=1)

st.subheader("Empat target")
kartu = []
for t in b["target"]:
    isi = [f"<div class='h'><span>{html.escape(t['target'])}</span>{kata(t['status'])}</div>", "<div class='l'>Terukur</div>"]
    isi += [f"<p>{html.escape(x)}</p>" for x in t["terukur"]] or ["<p class='m'>Belum ada pengukuran.</p>"]
    if t["pembanding"]:
        isi.append("<div class='l'>Pembanding, bukan bukti</div>")
        isi += [f"<p class='m'>{html.escape(x)}</p>" for x in t["pembanding"]]
    if t["perlu"]:
        isi += ["<div class='l'>Yang dibutuhkan</div>", f"<p>{html.escape(t['perlu'])}</p>"]
    kartu.append("<div class='tg'>" + "".join(isi) + "</div>")
st.html(_GAYA + "".join(kartu))

st.subheader("Uji coba di papan")
u = b["uji_coba"]
st.markdown(f"**{u['lengkap']} dari {u['target']} uji coba penuh.** Satu uji coba penuh adalah satu kali gateway berjalan "
            "dengan ESP32 nyata yang memenuhi lima hal: AI di ESP32 aktif, kurva susunan terukur, rekomendasi AI dari "
            "ESP32, empat panel diperiksa, dan berhenti aman dikonfirmasi. Semuanya tercatat otomatis.")
if u["rows"]:
    tabel(["Mulai", "Alat"] + [c["nama"] for c in u["rows"][0]["cek"]] + ["Hasil"],
          [[U.jam(r["mulai"]) + ", " + r["mulai"][:10], r["alat"]] + ["Ya" if c["ok"] else "Belum" for c in r["cek"]]
           + ["Lengkap" if r["lengkap"] else "Kurang: " + ", ".join(r["kurang"]).lower()] for r in u["rows"]])
else:
    st.caption("Belum ada uji coba dengan ESP32 nyata. Jalankan start_live.bat dengan ESP32 di USB, biarkan pemantauan "
               "berjalan sampai panel diperiksa, lalu tekan Hentikan semua.")

st.subheader("Daya kendali")
d = b["daya"]
st.caption("Daya kendali adalah daya untuk menahan saklar tetap tertutup. Angka di tabel ini hitungan desain, bukan "
           "pengukuran: kumparan relai sekitar 0,36 W masing-masing (belum diukur), satu sel saklar semikonduktor sekitar "
           "0,033 W (desain, belum dibangun).")
tabel(["Susunan", "Saklar tertutup", "Relai, hitungan", "Saklar semikonduktor, hitungan"],
      [(r["wiring"], r["elements"], f"{U.angka(r['relay_w'], 2)} W", f"{U.angka(r['semi_w'], 3)} W")
       for r in d["holding_by_wiring"] if r["wiring"] in ("4S", "2S2P", "TCT", "4P")])
if d["measured"]:
    st.markdown("**Terukur dengan multimeter**")
    tabel(["Waktu", "Susunan", "ESP32", "Relai", "Jumlah"],
          [(U.jam(e["at"]) + ", " + e["at"][:10], e.get("topology") or "-", f"{U.angka(e['device_power_w'], 3)} W",
            f"{U.angka(e['relay_power_w'], 3)} W", f"{U.angka(e['value'], 3)} W") for e in d["measured"]])
with st.expander("Catat pengukuran multimeter"):
    with st.form("daya"):
        st.caption("Ukur arus catu ESP32 dan arus catu 5 V relai, lalu kalikan dengan tegangannya. Ulangi untuk tiap "
                   "susunan, karena jumlah relai yang menutup berbeda.")
        a, c, s = st.columns(3)
        p_esp = a.number_input("Daya ESP32 (W)", 0.0, 10.0, 0.0, 0.01, format="%.3f")
        p_rel = c.number_input("Daya relai (W)", 0.0, 20.0, 0.0, 0.01, format="%.3f")
        topo = s.selectbox("Susunan saat diukur", ["4S", "2S2P", "TCT", "4P", "A", "B", "C", "D", "Semua relai terbuka"])
        if st.form_submit_button("Simpan pengukuran"):
            if p_esp <= 0 or p_rel <= 0:
                st.error("Isi kedua angka, daya ESP32 dan daya relai.")
            elif dev["kind"] != "esp32":
                st.error("Pilih ESP32 nyata di atas. Pengukuran pada mode demo tidak dicatat sebagai bukti.")
            else:
                data = {"entry": str(uuid.uuid4()), "topology": None if topo == "Semua relai terbuka" else topo}
                U.post("/ingest/metrics", {"items": [
                    {"device_id": dev["id"], "name": "device_power_w", "value": p_esp, "unit": "W", "provenance": "manual", "data": data},
                    {"device_id": dev["id"], "name": "relay_power_w", "value": p_rel, "unit": "W", "provenance": "manual", "data": data}]})
                st.toast("Pengukuran tersimpan")
                st.rerun()
