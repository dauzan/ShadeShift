"""Riwayat (docs/CONTRACT.md §19, §20, §22). Tab Ringkasan: kotak analisis; kiri garis waktu kondisi tiap panel, daya susunan
terhadap harapan, ringkasan dalam kalimat; kanan pengukuran terbaru dengan umurnya dan kejadian. Tab Jejak audit: siapa
melakukan apa dan kapan, per periode (24 jam sampai semua, atau rentang tanggal), halaman 100 baris, unduhan CSV."""
import html
import os, sys
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

dev = U.kepala("Riwayat")
if not dev:
    st.stop()
if dev["kind"] == "emulator":
    st.warning("Mode demo: kurva susunan adalah rekaman lab, kurva panel tunggal dari model kembaran. Bukan pengukuran saat ini.")


def lokal(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


@st.fragment(run_every=10.0)
def isi(device_id):
    try:
        h = U.get("/riwayat", device_id=device_id, hours=24)
        tw = U.get("/twin/state", device_id=device_id)
        an = U.get("/analisis", device_id=device_id, hours=24, **({"sejak": s} if (s := U.sejak("Riwayat", device_id)) else {}))
    except (U.ServerMati, RuntimeError) as e:
        st.error(f"Data tidak dapat dibaca: {e}")
        return
    U.kotak_analisis(an, "Riwayat")
    U.ingat_terbaru("Riwayat", device_id, an)
    k = tw["kondisi"]
    kiri, kanan = st.columns([3, 2], gap="large")

    with kiri:
        st.subheader("24 jam terakhir")
        for kalimat in h["summary"]:
            st.write(kalimat)
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        akhir = datetime.now().replace(microsecond=0)
        hari = [(akhir - timedelta(hours=24)).isoformat(), akhir.isoformat()]          # the axis always shows 24 hours
        for m, items in h["timeline"].items():
            for n, it in enumerate(items):
                end = items[n + 1]["at"] if n + 1 < len(items) else now
                rows.append({"Panel": f"Panel {m}", "mulai": lokal(it["at"]), "selesai": lokal(end),
                             "Kondisi": U.KATA_KONDISI[it["state"]],
                             "Daya dibanding panel terbaik": f"{round(it['power_rel'] * 100)} persen"})
        st.markdown("**Kondisi tiap panel**")
        if rows:
            kata = list(dict.fromkeys(U.KATA_KONDISI[s] for s in ("normal", "object", "diode", "nodata")))
            st.altair_chart(alt.Chart(pd.DataFrame(rows)).mark_bar().encode(
                x=alt.X("mulai:T", title=None, axis=alt.Axis(format="%H.%M"), scale=alt.Scale(domain=hari)), x2="selesai:T",
                y=alt.Y("Panel:N", title=None, sort=["Panel A", "Panel B", "Panel C", "Panel D"],
                        scale=alt.Scale(domain=["Panel A", "Panel B", "Panel C", "Panel D"], paddingInner=0.3),
                        axis=alt.Axis(labelOverlap=False)),
                color=alt.Color("Kondisi:N", title=None, legend=alt.Legend(orient="bottom"),
                                scale=alt.Scale(domain=kata, range=["#15803D", "#DC2626", "#1D4ED8", "#94A3B8"])),
                tooltip=["Panel", alt.Tooltip("mulai:T", title="Mulai", format="%H.%M"), "Kondisi", "Daya dibanding panel terbaik"]
            ).properties(height=260), width="stretch")
        else:
            st.caption("Belum ada pemeriksaan panel dalam 24 jam terakhir. Mulai pemantauan di Beranda.")
        st.markdown("**Daya dibanding perkiraan normal**")
        if h["array"]:
            arr = pd.DataFrame([{"waktu": lokal(a["at"]), "Daya (watt)": a["pmax_w"], "seri": "Terukur"} for a in h["array"]]
                               + [{"waktu": lokal(a["at"]), "Daya (watt)": a["expected_w"], "seri": "Perkiraan normal"}
                                  for a in h["array"] if a["expected_w"]])
            st.altair_chart(alt.Chart(arr).mark_line(point=True, strokeWidth=2).encode(
                x=alt.X("waktu:T", title=None, axis=alt.Axis(format="%H.%M"), scale=alt.Scale(domain=hari)), y=alt.Y("Daya (watt):Q"),
                color=alt.Color("seri:N", title=None, legend=alt.Legend(orient="bottom"),
                                scale=alt.Scale(domain=["Terukur", "Perkiraan normal"], range=["#0F172A", "#94A3B8"])),
                strokeDash=alt.condition(alt.datum.seri == "Perkiraan normal", alt.value([6, 4]), alt.value([1, 0])),
                tooltip=[alt.Tooltip("waktu:T", title="Pukul", format="%H.%M"), alt.Tooltip("seri:N", title="Garis"),
                         alt.Tooltip("Daya (watt):Q", format=".2f")]
            ).properties(height=220), width="stretch")
            st.caption("Garis putus-putus: perkiraan daya bila panel bersih dan tidak terhalang. Alat mengukur daya sesaat, "
                       "bukan jumlah energi harian (kWh).")
        else:
            st.caption("Belum ada pengukuran susunan dalam 24 jam terakhir.")

    with kanan:
        st.subheader("Saat ini")
        warna = {"ok": "#15803D", "problem": "#DC2626", "offline": "#64748B", "nodata": "#64748B"}[k["status"]["level"]]
        st.markdown(f"<div style='font-size:1.05rem;font-weight:600;color:{warna}'>{k['status']['text']}</div>",
                    unsafe_allow_html=True)
        a = k["array"]
        if a:
            c1, c2 = st.columns(2)
            c1.metric("Daya", f"{U.angka(a['pmax_w'], 2)} watt")
            c2.metric("Dibanding normal", f"{round(a['pct_of_expected'])} persen" if a["pct_of_expected"] is not None else "-",
                      help="Perkiraan normal: daya yang diharapkan bila panel bersih dan tidak terhalang.")
            susunan = {"4S": "seri (4S)", "2S2P": "seri-paralel (2S2P)", "TCT": "silang (TCT)", "4P": "paralel (4P)"}
            st.caption(f"Diukur {U.umur(a['at'])} (pukul {U.jam(a['at'])}), panel dirangkai {susunan.get(a['topology'], a['topology'])}. "
                       f"Pada titik daya terbaik: tegangan {U.angka(a['vmp'], 1)} volt, arus {U.angka((a['imp'] or 0) * 1000, 1)} "
                       "miliampere. Listrik hanya mengalir saat alat mengukur, jadi angka ini dari pengukuran terakhir."
                       + (f" Sensor cahaya {U.angka(a['light_v'], 2)} (makin besar makin terang)." if a.get("light_v") is not None else ""))
        else:
            st.caption("Belum ada pengukuran.")
        mon = tw.get("monitor") or {}
        st.caption("Pemantauan aktif." if mon.get("on") else "Pemantauan tidak aktif. Mulai di Beranda.")
        st.markdown("**Kejadian**")
        if h["events"]:
            for e in h["events"][:15]:
                st.write(f"Pukul {U.jam(e['at'])}. {e['text']}.")
        else:
            st.caption("Belum ada perubahan kondisi dalam 24 jam terakhir.")


PERIODE = {"24 jam": 1, "7 hari": 7, "30 hari": 30, "Semua": None, "Rentang tanggal": "rentang"}
JENIS = {"Semua jenis": "semua", "Perintah": "perintah", "Perpindahan relai": "relai", "Keputusan AI": "ai",
         "Peringatan dan galat": "peringatan", "Pemantauan dan perangkat": "sistem"}
_GAYA_JEJAK = """<style>
.jejak{max-height:640px;overflow-y:auto;border:1px solid #E2E8F0;border-radius:8px}
.jejak table{width:100%;border-collapse:collapse;font-size:.9rem;color:#0F172A}
.jejak th{position:sticky;top:0;background:#F8FAFC;text-align:left;font-weight:600;padding:8px 10px;border-bottom:1px solid #E2E8F0}
.jejak td{padding:7px 10px;border-bottom:1px solid #F1F5F9;vertical-align:top}
.jejak td:not(:nth-child(4)){white-space:nowrap}
.jejak td.w{color:#475569}
.jejak tr.r td{background:#F8FAFC;font-weight:600}
.jejak .g{color:#B91C1C;font-weight:600}
.jejak .d{color:#92400E}
</style>"""


def _utc(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _tabel(entries):
    baris = []
    for e in entries:
        jenis = html.escape(e["jenis"])
        if e["jenis"] in ("Galat", "Peringatan"):
            jenis = f"<span class='g'>{jenis}</span>"
        data = "<span class='d'>Mode demo</span>" if e["demo"] else "Nyata"
        baris.append(f"<tr class='{'r' if e['jenis'] == 'Ringkasan harian' else ''}'><td class='w'>{html.escape(e['waktu'])}</td>"
                     f"<td>{html.escape(e['siapa'])}</td><td>{jenis}</td><td>{html.escape(e['teks'])}</td><td>{data}</td></tr>")
    st.html(_GAYA_JEJAK + "<div class='jejak'><table><thead><tr><th>Waktu</th><th>Siapa</th><th>Jenis</th><th>Keterangan</th>"
            "<th>Data</th></tr></thead><tbody>" + "".join(baris) + "</tbody></table></div>")


def _halaman(n):
    st.session_state["jejak_hal"] = n


@st.fragment
def jejak(device_id):
    a, b, c = st.columns([4, 2, 2], vertical_alignment="bottom")
    periode = a.segmented_control("Periode", list(PERIODE), default="24 jam", key="jejak_periode") or "24 jam"
    jenis = b.selectbox("Jenis", list(JENIS), key="jejak_jenis")
    semua = c.toggle("Tampilkan semua", key="jejak_semua",
                     help="Setiap pengukuran dan setiap hasil AI. Tanpa ini: kejadian penting dan satu ringkasan per hari.")
    q = {"device_id": device_id, "kategori": JENIS[jenis], "semua": str(semua).lower()}
    if periode == "Rentang tanggal":
        hari_ini = date.today()
        r = st.date_input("Rentang tanggal", (hari_ini - timedelta(days=7), hari_ini), max_value=hari_ini,
                          format="DD/MM/YYYY", key="jejak_rentang")
        if len(r) != 2:
            st.caption("Pilih tanggal akhir.")
            return
        q["since"] = _utc(datetime.combine(r[0], time.min).astimezone())
        q["until"] = _utc(datetime.combine(r[1], time.max).astimezone())
    elif PERIODE[periode]:
        q["since"] = _utc(datetime.now(timezone.utc) - timedelta(days=PERIODE[periode]))
    tanda = (device_id, periode, jenis, semua, q.get("since", "")[:13], q.get("until"))
    if st.session_state.get("jejak_tanda") != tanda:                     # new filter: back to the first page
        st.session_state["jejak_tanda"] = tanda
        st.session_state["jejak_hal"] = 1
    try:
        d = U.get("/jejak", **q, page=st.session_state.get("jejak_hal", 1), per_page=100)
    except (U.ServerMati, RuntimeError) as e:
        st.error(f"Jejak audit tidak dapat dibaca: {e}")
        return
    if d["demo"]:
        st.caption("Mode demo: catatan ini berasal dari ESP32 tiruan (kurva lab yang direkam dan model kembaran), "
                   "bukan dari perangkat nyata. Setiap baris diberi tanda Mode demo, juga di berkas CSV.")
    if not d["entries"]:
        st.caption("Belum ada catatan pada periode ini.")
    else:
        awal = (d["page"] - 1) * d["per_page"]
        st.caption(f"Menampilkan {awal + 1} sampai {awal + len(d['entries'])} dari {d['total']} catatan, terbaru di atas. "
                   + ("Semua catatan ditampilkan." if semua else "Hanya kejadian penting; pekerjaan rutin diringkas per hari."))
        _tabel(d["entries"])
        if d["pages"] > 1:
            k1, k2, k3 = st.columns([1, 2, 1], vertical_alignment="center")
            k1.button("Sebelumnya", disabled=d["page"] <= 1, on_click=_halaman, args=(d["page"] - 1,), width="stretch")
            k2.markdown(f"<div style='text-align:center'>Halaman {d['page']} dari {d['pages']}</div>", unsafe_allow_html=True)
            k3.button("Berikutnya", disabled=d["page"] >= d["pages"], on_click=_halaman, args=(d["page"] + 1,), width="stretch")
    unduh_q = {k: v for k, v in q.items() if k in ("device_id", "since", "until")}
    st.download_button("Unduh jejak audit (CSV)", data=lambda: U.unduh("/jejak.csv?" + urlencode(unduh_q)),
                       file_name=f"jejak_audit_{device_id}_{date.today():%Y%m%d}.csv", mime="text/csv", on_click="ignore")
    st.caption("Berkas CSV berisi semua catatan pada periode yang dipilih, termasuk setiap pengukuran dan hasil AI, "
               "dengan pesan asli sistem di kolom terakhir.")


ringkas, audit = st.tabs(["Ringkasan", "Jejak audit"])
with ringkas:
    isi(dev["id"])
with audit:
    jejak(dev["id"])
