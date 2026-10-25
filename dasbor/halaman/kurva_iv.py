"""Kurva I-V untuk pemilik rumah (docs/CONTRACT.md §19, §20, §26). Sederhana dulu: kotak analisis AI (yang baru sejak
kunjungan terakhir, 24 jam, saat ini), kartu angka dalam kata sehari-hari, daya dari waktu ke waktu dibanding perkiraan
normal, dan daya tiap panel. Kurva lengkap (arus dan daya terhadap tegangan, setiap titik dijelaskan saat disentuh
penunjuk, enam tanda gangguan, kurva tiap panel) ada di bagian Lihat kurva lengkap."""
import html
import os, sys
from datetime import datetime, timedelta

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

HALAMAN = "Kurva I-V"
WARNA_PANEL = {"A": "#1D4ED8", "B": "#0F766E", "C": "#B45309", "D": "#7C3AED"}
SUSUNAN = {"4S": "seri (4S)", "2S2P": "seri-paralel (2S2P)", "TCT": "silang (TCT)", "4P": "paralel (4P)"}
# the six signs: plain name, what it usually means, the technical name (small print for the curious)
TANDA = [(1, "Sebagian panel terhalang", "Bayangan, kotoran, atau sel retak.", "anak tangga pada kurva"),
         (2, "Cahaya yang masuk berkurang", "Mendung, debu merata, atau bayangan besar.", "arus lebih rendah"),
         (3, "Ada bagian panel yang tidak ikut bekerja", "Dioda rusak, sel rusak, atau panel terlalu panas.", "tegangan lebih rendah"),
         (4, "Panel kurang efisien", "Sering karena usia panel.", "lutut kurva membulat"),
         (5, "Sambungan kabel kurang baik", "Konektor longgar atau berkarat.", "hambatan seri"),
         (6, "Ada kebocoran listrik di panel", "Arus bocor di dalam panel, atau cahaya tidak merata.", "hambatan shunt")]


def lokal(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def lapis(v, i, nama, jenis="ukur"):
    df = pd.DataFrame({"V": v, "I_mA": np.asarray(i, float) * 1000})
    df = df[df.V > 0]
    df["P_W"] = df.V * df.I_mA / 1000
    df["seri"], df["jenis"] = nama, jenis
    return df


def grafik_kurva(curve, harapan, sumbu_y, judul_y, label_titik):
    """The full curve: measured (each point explained on hover), the normal curve dashed, the signs highlighted."""
    ukur = pd.DataFrame(curve["points"]).rename(columns={"v": "V"})
    ukur["I_mA"] = ukur["i"] * 1000
    ukur["P_W"] = ukur["V"] * ukur["i"]
    ukur = ukur[ukur.V > 0]
    x = alt.X("V:Q", title="Tegangan (volt)")
    y = alt.Y(f"{sumbu_y}:Q", title=judul_y)
    lapisan = []
    if harapan is not None:
        lapisan.append(alt.Chart(harapan).mark_line(strokeWidth=1.8, strokeDash=[6, 4], color="#94A3B8").encode(x=x, y=y))
    lapisan.append(alt.Chart(ukur).mark_line(strokeWidth=2.4, color="#0F172A").encode(x=x, y=y))
    for n, a in enumerate(curve["anomalies"]):                       # each sign: a wide red band over its points
        seg = ukur[(ukur.V >= a["v0"]) & (ukur.V <= a["v1"])]
        if len(seg) >= 2:
            lapisan.append(alt.Chart(seg).mark_line(strokeWidth=10, opacity=0.22, color="#DC2626").encode(x=x, y=y))
            mid = seg.iloc[[len(seg) // 2]].assign(teks=a.get("mudah", a["title"]))
            lapisan.append(alt.Chart(mid).mark_text(dy=-16 - 14 * (n % 2), fontSize=12, fontWeight=600, color="#B91C1C")
                           .encode(x=x, y=y, text="teks:N"))
    titik = ukur.iloc[[int(ukur["P_W"].values.argmax())]].assign(teks=label_titik)
    lapisan.append(alt.Chart(titik).mark_point(size=80, filled=True, color="#DC2626").encode(x=x, y=y))
    lapisan.append(alt.Chart(titik).mark_text(align="right", dx=-8, dy=-12, fontSize=12, color="#0F172A")
                   .encode(x=x, y=y, text="teks:N"))
    dekat = alt.selection_point(name=f"dekat_{sumbu_y}", on="pointerover", nearest=True, fields=["V"], empty=False, clear="pointerout")
    lapisan.append(alt.Chart(ukur).mark_circle(size=140, opacity=0).encode(
        x=x, y=y, tooltip=[alt.Tooltip("bagian:N", title="Bagian"), alt.Tooltip("arti:N", title="Artinya"),
                           alt.Tooltip("V:Q", title="Tegangan (volt)", format=".1f"),
                           alt.Tooltip("I_mA:Q", title="Arus (miliampere)", format=".1f"),
                           alt.Tooltip("P_W:Q", title="Daya (watt)", format=".2f")]).add_params(dekat))
    lapisan.append(alt.Chart(ukur).mark_circle(size=90, color="#1D4ED8").encode(x=x, y=y).transform_filter(dekat))
    lapisan.append(alt.Chart(ukur).mark_rule(color="#94A3B8", strokeDash=[2, 3]).encode(x=x).transform_filter(dekat))
    return alt.layer(*lapisan).properties(height=300)


def daftar_tanda(curve):
    ada = {a["code"] for a in curve["anomalies"]}
    rows = "".join(
        f"<div style='display:flex;gap:10px;padding:8px 0;border-top:1px solid #e2e8f0'>"
        f"<div style='flex:1'><div style='font-weight:600;color:{'#B91C1C' if c in ada else '#0F172A'}'>{html.escape(t)}</div>"
        f"<div style='color:#64748B;font-size:13px'>{html.escape(m)} Istilah teknis: {html.escape(tek)}.</div></div>"
        f"<div style='font-size:13px;font-weight:600;color:{'#B91C1C' if c in ada else '#94A3B8'};white-space:nowrap'>"
        f"{'Terlihat sekarang' if c in ada else 'Tidak terlihat'}</div></div>" for c, t, m, tek in TANDA)
    st.html(f"<div style='font:14px/1.45 system-ui,sans-serif;color:#0F172A'><div style='font-weight:600;margin-bottom:4px'>"
            f"Enam tanda gangguan yang dicari</div>{rows}</div>")


dev = U.kepala(HALAMAN)
if not dev:
    st.stop()
pilih = dev["id"]
st.caption("Berapa listrik yang dihasilkan panel sekarang, apakah itu normal, dan apa artinya.")
if dev["kind"] == "emulator":
    st.warning("Mode demo: kurva susunan adalah rekaman lab, kurva panel tunggal dari model kembaran. Bukan pengukuran saat ini.")

a, b, c, _ = st.columns([1, 1, 1, 2])
if a.button("Ukur sekarang", width="stretch", help="Alat mengukur panel sekali sekarang."):
    U.kirim_perintah(pilih, "action", "measure_now", nama="Perintah ukur")
if b.button("Periksa setiap panel", width="stretch",
            help="Keempat panel diukur satu per satu untuk mencari panel yang bermasalah. Sekitar 20 detik."):
    U.kirim_perintah(pilih, "action", "panel_check", nama="Perintah periksa setiap panel")
try:
    diag = U.get(f"/devices/{pilih}/diag")
except (U.ServerMati, RuntimeError):
    diag = {"available": False, "why": "server tidak menjawab."}
if c.button("Diagnosis dengan AI", width="stretch", disabled=not diag["available"],
            help="AI di ESP32 mencari penyebab gangguan dengan mengukur panel dalam empat cara merangkai. Hasilnya muncul "
                 "di kotak AI dan di Beranda." if diag["available"] else "Belum dapat dijalankan: " + (diag.get("why") or "-")):
    U.kirim_perintah(pilih, "action", "diagnose", nama="Perintah diagnosis dengan AI")


@st.fragment(run_every=10.0)
def isi(device_id):
    try:
        an = U.get("/analisis", device_id=device_id, hours=24, **({"sejak": s} if (s := U.sejak(HALAMAN, device_id)) else {}))
        h = U.get("/riwayat", device_id=device_id, hours=24)
        snap = U.get(f"/devices/{device_id}/snapshot", n_recent=1)
    except (U.ServerMati, RuntimeError) as e:
        st.error(f"Data tidak dapat dibaca: {e}")
        return
    U.kotak_analisis(an, HALAMAN)
    U.ingat_terbaru(HALAMAN, device_id, an)
    curve = an.get("curve")
    if not curve or not curve.get("ok"):
        st.info("Belum ada pengukuran dalam 24 jam terakhir. Tekan Ukur sekarang, atau nyalakan pemantauan di Beranda.")
        return

    # ---- plain cards ----
    t = curve["topology"]
    exp = (h["array"][-1].get("expected_w") if h["array"] else None)
    nama_tanda = list(dict.fromkeys(a.get("mudah", a["title"]).lower() for a in curve["anomalies"]))
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Daya sekarang", f"{U.angka(curve['pmax'], 2)} watt")
    k2.metric("Dibanding normal", f"{round(curve['pmax'] / exp * 100)} persen" if exp else "-",
              help="Perkiraan normal: daya yang diharapkan bila panel bersih dan tidak terhalang.")
    k3.metric("Tanda gangguan", "Ada" if nama_tanda else "Tidak ada")
    k4.metric("Diukur", U.umur(curve["at"]))
    st.caption(("Tanda gangguan: " + ", ".join(nama_tanda) + ". " if nama_tanda else "") + f"Panel sedang dirangkai {SUSUNAN.get(t, t)}.")

    # ---- power over time vs normal ----
    st.markdown("**Daya dari waktu ke waktu**")
    if h["array"]:
        rows = [{"waktu": lokal(x["at"]), "Daya (watt)": x["pmax_w"], "seri": "Terukur"} for x in h["array"]]
        rows += [{"waktu": lokal(x["at"]), "Daya (watt)": x["expected_w"], "seri": "Perkiraan normal"} for x in h["array"] if x["expected_w"]]
        akhir = datetime.now().replace(microsecond=0)
        st.altair_chart(alt.Chart(pd.DataFrame(rows)).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("waktu:T", title=None, axis=alt.Axis(format="%H.%M"),
                    scale=alt.Scale(domain=[(akhir - timedelta(hours=24)).isoformat(), akhir.isoformat()])),
            y=alt.Y("Daya (watt):Q"),
            color=alt.Color("seri:N", title=None, legend=alt.Legend(orient="bottom"),
                            scale=alt.Scale(domain=["Terukur", "Perkiraan normal"], range=["#0F172A", "#94A3B8"])),
            strokeDash=alt.condition(alt.datum.seri == "Perkiraan normal", alt.value([6, 4]), alt.value([1, 0])),
            tooltip=[alt.Tooltip("waktu:T", title="Pukul", format="%H.%M"), alt.Tooltip("seri:N", title="Garis"),
                     alt.Tooltip("Daya (watt):Q", format=".2f")]).properties(height=230), width="stretch")
        st.caption("Garis hitam: daya yang terukur. Garis putus-putus: perkiraan daya bila panel bersih dan tidak terhalang.")

    # ---- each panel ----
    panel = snap.get("latest_by_panel") or {}
    st.markdown("**Daya tiap panel**")
    if panel:
        terbaik = max((s["pmax"] or 0) for s in panel.values()) or 1
        bacaan = an.get("panels") or {}
        dp = pd.DataFrame([{"Panel": f"Panel {m}", "Persen": round((s["pmax"] or 0) / terbaik * 100),
                            "Keadaan": "Ada tanda gangguan" if (bacaan.get(m) or {}).get("anomalies") else "Normal",
                            "Daya (watt)": round(s["pmax"] or 0, 2)} for m, s in sorted(panel.items())])
        urut = [f"Panel {m}" for m in sorted(panel)]
        st.altair_chart(alt.Chart(dp).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("Panel:N", title=None, sort=urut, scale=alt.Scale(domain=urut, paddingInner=0.3),
                    axis=alt.Axis(labelOverlap=False)),
            x=alt.X("Persen:Q", title="Dibanding panel terbaik (persen)", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("Keadaan:N", legend=None,           # a bottom legend squeezes the bars; the caption says the colours
                            scale=alt.Scale(domain=["Normal", "Ada tanda gangguan"], range=["#15803D", "#DC2626"])),
            tooltip=["Panel", "Keadaan", alt.Tooltip("Persen:Q", title="Dibanding panel terbaik"),
                     alt.Tooltip("Daya (watt):Q")]).properties(height=40 * len(urut)), width="stretch")
        st.caption(f"Dari pemeriksaan panel {U.umur(max(s['captured_at'] for s in panel.values()))}. Hijau: normal. Merah: ada "
                   "tanda gangguan. Panel yang jauh lebih pendek dari yang lain kemungkinan terhalang atau bermasalah.")
    else:
        st.caption("Belum ada pemeriksaan panel. Tekan Periksa setiap panel.")

    # ---- the full curve, for the curious ----
    with st.expander("Lihat kurva lengkap"):
        st.caption("Kurva ini adalah sidik jari listrik panel: alat mengukur arus pada setiap tegangan. Bentuknya "
                   "menunjukkan bayangan, kotoran, dan masalah listrik. Sentuh titik mana pun pada kurva untuk melihat artinya.")
        sett = snap["settings"]
        kv = U.kurva_kembaran(t, max(p["v"] for p in curve["points"]), sett.get("twin_scale", 1.0), "none")
        harapan = lapis(kv["v"], kv["i"], "Perkiraan normal", "harapan") if kv else None
        g1, g2 = st.columns(2)
        g1.markdown("**Arus pada setiap tegangan**")
        g1.altair_chart(grafik_kurva(curve, harapan, "I_mA", "Arus (miliampere)", f"Daya terbaik {U.angka(curve['pmax'], 2)} watt"),
                        width="stretch")
        g2.markdown("**Daya pada setiap tegangan**")
        g2.altair_chart(grafik_kurva(curve, harapan, "P_W", "Daya (watt)", f"Daya terbaik {U.angka(curve['pmax'], 2)} watt"),
                        width="stretch")
        st.caption(f"Garis hitam: kurva terukur. Garis putus-putus: kurva normal bila panel bersih dan tidak terhalang. Pita "
                   f"merah: bagian kurva yang menunjukkan tanda gangguan. Tegangan tertinggi {U.angka(curve['voc'], 1)} volt, "
                   f"arus terbesar {U.angka(curve['isc'] * 1000, 1)} miliampere.")
        daftar_tanda(curve)
        if panel:
            st.markdown("**Kurva tiap panel**")
            dfp = pd.concat([lapis(s["points"]["v"], s["points"]["i"], f"Panel {m}") for m, s in sorted(panel.items())],
                            ignore_index=True)
            st.altair_chart(alt.Chart(dfp).mark_line(strokeWidth=2.2).encode(
                x=alt.X("V:Q", title="Tegangan (volt)"), y=alt.Y("I_mA:Q", title="Arus (miliampere)"),
                color=alt.Color("seri:N", title=None, legend=alt.Legend(orient="bottom"),
                                scale=alt.Scale(domain=[f"Panel {m}" for m in sorted(panel)], range=[WARNA_PANEL[m] for m in sorted(panel)])),
                tooltip=[alt.Tooltip("seri:N", title="Kurva"), alt.Tooltip("V:Q", title="Tegangan (volt)", format=".1f"),
                         alt.Tooltip("I_mA:Q", title="Arus (miliampere)", format=".1f")]).properties(height=280), width="stretch")
            st.caption("Arus yang lebih rendah: cahaya ke panel itu tertutup. Tegangan yang lebih rendah: ada bagian panel yang "
                       "tidak ikut bekerja. Daya lebih rendah dengan arus dan tegangan normal: sambungan kabel kurang baik.")
        if st.button("Jadikan pengukuran ini patokan normal",
                     help="Pakai hanya saat panel bersih dan tidak terhalang, misalnya di bawah lampu tempat demo. Perkiraan "
                          "normal disetel agar sama dengan pengukuran ini."):
            try:
                U.post("/twin/calibrate", {"sweep_id": curve["sweep_id"]})
                st.toast("Patokan normal disimpan")
            except (RuntimeError, U.ServerMati) as e:
                st.error(f"Patokan tidak dapat disimpan: {e}")


isi(pilih)
