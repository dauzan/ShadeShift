"""Halaman Langsung: alat yang sedang terhubung lewat gateway (ESP32 nyata atau ESP32 tiruan untuk demo)."""
import os, sys
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import umum as U  # noqa: E402

st.header("Pemantauan langsung")
if not U.server_hidup(): st.stop()

alat = [d for d in U.get("/devices") if d["kind"] != "virtual"]
if not alat:
    st.info("Belum ada alat. Jalankan gateway:  `.venv\\Scripts\\python run.py demo` (tanpa alat) atau "
            "`run.py live` (dengan ESP32 di USB).")
    st.stop()


def urutan(d):            # ESP32 nyata yang online lebih dulu, demo tidak pernah jadi bawaan bila ESP32 online
    return (not d["online"], d["kind"] != "esp32", d["id"])


alat.sort(key=urutan)
ids = [d["id"] for d in alat]
if st.session_state.get("alat") not in ids: st.session_state.alat = ids[0]
pilih = st.selectbox("Alat", ids, key="alat",
                     format_func=lambda i: next(f"{d['id']}  ({'ESP32' if d['kind'] == 'esp32' else 'TIRUAN / demo'}, "
                                                f"{'online' if d['online'] else 'offline'})" for d in alat if d["id"] == i))
dev = next(d for d in alat if d["id"] == pilih)
demo = dev["kind"] == "emulator"
if demo:
    st.warning("**DEMO**: alat ini ESP32 tiruan yang memutar ulang kurva lab (lampu halogen), bukan pengukuran saat ini. "
               "Waktu pindah dan sapuan adalah perkiraan.")
elif not dev["online"]:
    st.error("ESP32 offline: gateway tidak mengirim detak. Cek kabel USB dan jendela gateway.")

# ---------------- kendali ----------------
c = st.columns([1, 1, 1, 1, 1, 1])
for i, t in enumerate(U.TOPO):
    if c[i].button(t + (" (manual)" if t == "4P" else ""), key=f"t_{t}", width="stretch",
                   help="Pindah susunan lewat urutan aman firmware. 4S bisa sekitar 88 V DC." if t != "4P" else
                        "4P tidak pernah dipilih pemilih (Voc di bawah jendela 24 V); hanya manual."):
        U.kirim_perintah(pilih, "raw", t)
if c[4].button("SWEEP", width="stretch"): U.kirim_perintah(pilih, "raw", "SWEEP dasbor")
if c[5].button("STATUS", width="stretch"): U.kirim_perintah(pilih, "raw", "STATUS")
st.caption("⚠️ Pada 4S tegangan array bisa sekitar 88 V DC. Tekan STOP sebelum menyentuh kabel.")

k1, k2, k3 = st.columns([2, 2, 2])
with k1:
    if st.button("Pilih susunan otomatis (sekali)", type="primary", width="stretch",
                 help="4S → SWEEP → pemilih (AI) → pindah ke pilihan → SWEEP. Pemilih berjalan di gateway laptop "
                      "(ONNX Runtime); di ESP32 baru setelah firmware v3."):
        U.kirim_perintah(pilih, "action", "auto_select")
    U.tombol_stop("stop_langsung")
with k2:
    with st.expander("Mode otomatis (pemicu perubahan daya)"):
        jeda = st.number_input("Sapu ulang tiap (s)", 3.0, 600.0, 10.0, 1.0)
        amb = st.number_input("Pilih ulang bila daya berubah > (%)", 5.0, 80.0, 20.0, 1.0)
        tahan = st.number_input("Jeda minimum antar-pindah (s)", 0.0, 3600.0, 30.0, 5.0)
        if st.button("Mulai mode otomatis", width="stretch"):
            U.kirim_perintah(pilih, "action", "auto_mode_start", {"interval_s": jeda, "trigger_pct": amb, "hold_s": tahan})
        if st.button("Hentikan mode otomatis", width="stretch"): U.kirim_perintah(pilih, "action", "auto_mode_stop")
        st.caption("Simulasi (skenario sintetis): pemicu 20 % rata-rata lebih baik dari TCT tetap per jenis bayangan, "
                   "tetapi lebih buruk pada 10 dari 12 skenario daun. Tiap sapuan memutus daya beberapa detik.")
with k3:
    if demo:
        info_demo = dev["state"].get("demo") or {}
        skenario = info_demo.get("scenarios") or []
        if skenario:
            with st.container(border=True):
                st.markdown("**Mode demo: skenario bayangan**")
                nama = st.selectbox("Skenario", skenario, index=skenario.index("default") if "default" in skenario else 0,
                                    help="default: tiga perubahan bayangan, pemilih benar di tiap langkah. kilat: sama, 3x "
                                         "lebih cepat. v6_kelemahan: kasus yang diketahui salah (jujur).")
                cepat = st.selectbox("Kecepatan", [None, 1.0, 2.0, 3.0, 5.0, 10.0],
                                     format_func=lambda x: "bawaan skenario" if x is None else f"{x:g}x")
                a, b = st.columns(2)
                if a.button("Mulai skenario", width="stretch", type="primary"):
                    U.kirim_perintah(pilih, "action", "demo_scenario_start",
                                     {"name": nama, **({"speed": cepat} if cepat else {})})
                if b.button("Hentikan", width="stretch"):
                    U.kirim_perintah(pilih, "action", "demo_scenario_stop")
        kondisi = info_demo.get("available_conditions") or []
        now = info_demo.get("condition")
        if kondisi:
            baru = st.selectbox("Atau ganti kondisi bayangan manual", kondisi, index=kondisi.index(now) if now in kondisi else 0,
                                help="Ganti = bayangan berubah. Data tetap kurva lab yang diputar ulang.")
            if baru != now and st.button("Terapkan kondisi", width="stretch"):
                U.kirim_perintah(pilih, "action", "demo_condition", {"condition": baru})
    else:
        perintah = st.text_input("Perintah firmware", placeholder="contoh: VPANEL 17, VOC, CEKVOC 1")
        if st.button("Kirim perintah", width="stretch") and perintah: U.kirim_perintah(pilih, "raw", perintah)
        st.caption("RELAI, UJIRELAI, DAC, CEKVOC 0, SIKLUS dan TAHAN 1 diblokir demi keselamatan: pakai Serial Monitor "
                   "Arduino tanpa panel, dengan gateway dimatikan.")


# ---------------- tampilan yang diperbarui tiap detik ----------------
@st.fragment(run_every=1.0)
def tampilan(device_id, demo):
    try:
        snap = U.get(f"/devices/{device_id}/snapshot", n_recent=30)
    except (U.ServerMati, RuntimeError) as e:
        st.error(f"Tidak bisa membaca data: {e}"); return
    d, sett, harapan = snap["device"], snap["settings"], snap["expected"] or {}
    state = d.get("state") or {}
    sk = (state.get("demo") or {}).get("scenario")
    if sk:
        st.info(f"▶ **Skenario DEMO '{sk['name']}'** ({sk['speed']:g}x) · langkah {sk['step']}/{sk['steps']}: "
                f"**{sk['condition']}** · {sk['note']} · t = {sk['t_s']:.0f} s")
    m = st.columns(5)
    m[0].metric("Susunan aktif", state.get("active_topology") or "terbuka")
    tugas = state.get("task") or ("mode otomatis" if (state.get("auto_mode") or {}).get("on") else "-")
    m[1].metric("Tugas", tugas)
    rec = snap["recent_sweeps"]
    if rec:
        s = rec[0]
        m[2].metric(f"Pmax terukur ({s['topology']})" if s["source"] == "device" else f"Pmax DEMO ({s['topology']})",
                    f"{s['pmax']:.3f} W" if s["pmax"] is not None else "-")
        ph = harapan.get(s["topology"])
        if ph and s["pmax"] is not None:
            m[3].metric("Daya harapan (kembaran)", f"{ph:.3f} W", f"{(s['pmax'] - ph) / ph * 100:+.1f}%")
    dec = snap["latest_decision"]
    if dec:
        m[4].metric("Keputusan pemilih (AI)", dec["choice"],
                    f"{dec['latency_us'] / 1000:.1f} ms" if dec.get("latency_us") else None, delta_color="off")
        st.caption(f"Diputuskan oleh: **{U.label_keputusan(dec['decided_by'])}** · model `{dec['model_id']}` · "
                   f"pemicu {dec['trigger']} · {'diterapkan' if dec['applied'] else 'hanya pengamatan'}")
    gw = d.get("gateway") or {}
    if gw.get("fallback_reason"):
        st.caption(f"ONNX Runtime tidak dipakai: {gw['fallback_reason']} (memakai numpy, hasil sama).")
    if state.get("last_error"): st.error(state["last_error"])

    latest = snap["latest_by_topology"]
    if latest:
        lap = [U.lapis_sapuan(sw, f"{t} {'terukur' if sw['source'] == 'device' else 'DEMO'}") for t, sw in latest.items()]
        if rec and rec[0]["topology"] in harapan:
            t = rec[0]["topology"]
            kv = U.kurva_kembaran(t, max(latest[t]["points"]["v"]), sett.get("twin_scale", 1.0), sett.get("twin_shading", "none"))
            if kv: lap.append(U.lapis_kembaran(kv["v"], kv["i"], t))
        catatan = "DEMO: kurva lab diputar ulang" if demo else None
        g1, g2 = st.columns(2)
        g1.markdown("**Kurva I-V** (sapuan terakhir tiap susunan; garis putus = kembaran digital, simulasi)")
        g1.altair_chart(U.grafik(lap, "I_mA", "Arus (mA)", catatan), width="stretch")
        g2.markdown("**Kurva P-V**")
        g2.altair_chart(U.grafik(lap, "P_W", "Daya (W)", catatan), width="stretch")
        st.markdown("**Riwayat sapuan** (tersimpan di basis data)")
        st.dataframe(U.tabel_sapuan(rec), hide_index=True, width="stretch")
    else:
        st.info("Belum ada sapuan. Tekan **Pilih susunan otomatis**, atau pilih susunan lalu **SWEEP**.")
    ev = snap["recent_events"]
    if ev:
        with st.expander(f"Peristiwa terbaru ({len(ev)})", expanded=False):
            st.dataframe(pd.DataFrame([{"waktu (UTC)": e["created_at"][11:19], "jenis": e["kind"], "pesan": e["message"]}
                                       for e in ev]), hide_index=True, width="stretch")
    with st.expander("Log serial", expanded=False):
        st.code("\n".join(("» " if x["dir"] == "tx" else "") + x["line"] for x in snap["log_tail"]) or "(kosong)", language=None)


tampilan(pilih, demo)
