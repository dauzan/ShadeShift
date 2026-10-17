"""Dasbor SHADESHIFT (lapis L1 digitalisasi). Jalankan dari folder dasbor:  streamlit run app.py
Mode langsung: ESP32 lewat serial, atau TIRUAN (memutar ulang data lab, cadangan demo). Mode putar ulang: berkas CSV.
Semua angka di layar berlabel sumbernya: terukur (lab/ESP32), kembaran (simulasi lampu lab, galat daya sekitar 8%)."""
import os, time, threading
import numpy as np, pandas as pd, altair as alt
import streamlit as st
import inti, koneksi

st.set_page_config(page_title="SHADESHIFT", page_icon="☀️", layout="wide")
WARNA = {"4S": "#1F77B4", "2S2P": "#FF7F0E", "TCT": "#2CA02C", "4P": "#9467BD", "kembaran": "#7F7F7F"}


@st.cache_resource
def bobot(): return inti.muat_bobot()


@st.cache_resource
def tau_paranet(): return inti.transmisi_paranet()


@st.cache_data(max_entries=64)
def kembaran(skala, nama_bayangan):
    tp = inti.simulasi_kembaran(skala, inti.bayangan_kembaran(nama_bayangan, tau_paranet()))
    kurva = {t: (tp[t].V.copy(), tp[t].I.copy()) for t in inti.TOPO}
    return inti.daya_harapan(tp), kurva


def kurva_harapan(kurva, t, voc):
    V, I = kurva[t]; o = np.argsort(V)
    Vg = np.linspace(0, voc * 1.02, 250)
    return Vg, np.clip(np.interp(Vg, V[o], I[o]), 0, None)


def grafik(lapisan, sumbu_y, judul_y):
    df = pd.concat(lapisan, ignore_index=True)
    if df.empty: return None
    warna = alt.Color("seri:N", scale=alt.Scale(domain=list(df.seri.unique()),
                      range=[WARNA.get(s.split(" ")[0], "#7F7F7F") for s in df.seri.unique()]), legend=alt.Legend(title=None, orient="bottom"))
    garis = alt.Chart(df).mark_line().encode(
        x=alt.X("V:Q", title="Tegangan (V)"), y=alt.Y(f"{sumbu_y}:Q", title=judul_y), color=warna,
        strokeDash=alt.condition(alt.datum.jenis == "kembaran", alt.value([5, 4]), alt.value([1, 0])),
        tooltip=["seri", alt.Tooltip("V:Q", format=".2f"), alt.Tooltip(f"{sumbu_y}:Q", format=".4f")])
    return garis.properties(height=320).interactive()


def lapis_sapuan(s, nama):
    return pd.DataFrame({"V": s.V, "I_mA": s.I * 1000, "P_W": s.P, "seri": nama, "jenis": "terukur"})


def lapis_kembaran(kurva, t, voc, nama):
    V, I = kurva_harapan(kurva, t, voc)
    return pd.DataFrame({"V": V, "I_mA": I * 1000, "P_W": V * I, "seri": nama, "jenis": "kembaran"})


def selisih(pm, ph):
    return (pm - ph) / ph if ph > 0 else float("nan")


# ---------------- sisi kiri: pengaturan bersama ----------------
st.sidebar.title("☀️ SHADESHIFT")
halaman = st.sidebar.radio("Mode", ["Langsung (ESP32 / tiruan)", "Putar ulang berkas"])
st.sidebar.markdown("**Kembaran digital (daya harapan)**")
if "skala_baru" in st.session_state:                     # dari tombol kalibrasi; harus diisi sebelum slider dibuat
    st.session_state.skala = min(2.0, max(0.2, st.session_state.pop("skala_baru")))
st.session_state.setdefault("skala", 1.0)
skala = st.sidebar.slider("Skala cahaya (1,0 = lampu dekat, kondisi V1c)", 0.2, 2.0, step=0.01, key="skala")
nama_bay = st.sidebar.selectbox("Bayangan yang diasumsikan kembaran", list(inti.BAYANGAN), key="bay")
ambang = st.sidebar.slider("Ambang peringatan selisih daya (%)", 5, 50, 15, 1) / 100
st.sidebar.caption("Kembaran dicocokkan pada V1c (lampu halogen); galat daya sekitar 8% pada 7 kondisi lab. "
                   "Selisih besar = indikasi kelainan, **bukan** diagnosis tervalidasi.")
harapan, kurva_k = kembaran(round(skala, 3), nama_bay)
W = bobot()


# ================= MODE LANGSUNG =================
def halaman_langsung():
    k: koneksi.Koneksi | None = st.session_state.get("kon")
    with st.sidebar:
        st.markdown("**Koneksi**")
        if k is None or not k.hidup:
            try:
                from serial.tools import list_ports
                port = [p.device for p in list_ports.comports()]
            except Exception:
                port = []
            pilihan = ["TIRUAN"] + port + ["(ketik manual)"]
            p = st.selectbox("Port", pilihan, help="TIRUAN = ESP32 tiruan yang memutar ulang data lab (cadangan demo)")
            if p == "(ketik manual)": p = st.text_input("Port", "COM3")
            kond0 = st.selectbox("Kondisi awal tiruan", sorted(inti.daftar_kondisi()), index=sorted(inti.daftar_kondisi()).index("V1c")) if p == "TIRUAN" else None
            if st.button("Sambungkan", type="primary"):
                try:
                    st.session_state.kon = koneksi.Koneksi(p, tiruan_kondisi=kond0 or "V1c"); st.rerun()
                except Exception as e:
                    st.error(f"Gagal membuka {p}: {e}")
            if k is not None and k.galat: st.error(k.galat)
        else:
            st.success(f"Tersambung: {k.port}")
            if k.tiruan:
                daftar = sorted(k.ser.semua)
                k.ser.kondisi = st.selectbox("Kondisi tiruan (ganti = bayangan berubah)", daftar, index=daftar.index(k.ser.kondisi))
            if st.button("Putuskan"):
                if "henti" in st.session_state: st.session_state.henti.set()
                k.kirim("OFF"); time.sleep(0.3); k.tutup(); st.session_state.kon = None; st.rerun()

    st.header("Pemantauan langsung")
    if k is None or not k.hidup:
        st.info("Pilih port di kiri lalu **Sambungkan**. Tanpa alat, pilih **TIRUAN** (memutar ulang kurva lab).")
        return
    if k.tiruan: st.warning("Mode TIRUAN: kurva berasal dari data lab (lampu halogen), bukan pengukuran saat ini.")

    # ---------- kendali ----------
    c = st.columns([1, 1, 1, 1, 1, 1, 1])
    for i, t in enumerate(inti.TOPO):
        if c[i].button(t, width="stretch", disabled=bool(k.kerja)): k.kirim(t)
    if c[4].button("OFF", width="stretch"):
        if "henti" in st.session_state: st.session_state.henti.set()
        k.kirim("OFF")
    if c[5].button("STATUS", width="stretch"): k.kirim("STATUS")
    if c[6].button("VOC", width="stretch"): k.kirim("VOC")

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        label = st.text_input("Label sapuan", f"dasbor_{time.strftime('%H%M%S')}")
        if st.button("SWEEP susunan aktif", disabled=bool(k.kerja) or not k.topo, width="stretch"):
            k.kirim(f"SWEEP {label}")
    with c2:
        st.write("")
        if st.button("Pilih susunan otomatis (sekali)", type="primary", disabled=bool(k.kerja), width="stretch",
                     help="4S → SWEEP → pemilih → pindah ke pilihan → SWEEP. Pemilih dihitung di laptop dengan bobot pemilih_bobot.h."):
            k.mulai_tugas("pilih otomatis", lambda: k.riwayat_pilih.append(k.pilih_sekali(W)))
        if st.button("Kalibrasi skala cahaya dari sapuan terakhir", width="stretch", disabled=not k.sapuan,
                     help="Pakai hanya bila sapuan terakhir TANPA bayangan. Mengatur skala supaya daya kembaran = daya terukur."):
            st.session_state.skala_baru = inti.kalibrasi_skala(k.sapuan[-1]); st.rerun()
    with c3:
        with st.expander("Mode otomatis (uji aturan pemicu di laptop)", expanded=k.kerja == "mode otomatis"):
            jeda = st.number_input("Sapu ulang tiap (s)", 3.0, 600.0, 10.0, 1.0)
            amb = st.number_input("Pilih ulang bila daya berubah > (%)", 5.0, 80.0, 20.0, 1.0)
            tahan = st.number_input("Jeda minimum antar-pindah (s)", 0.0, 3600.0, 30.0, 5.0)
            if k.kerja == "mode otomatis":
                if st.button("Hentikan mode otomatis"): st.session_state.henti.set()
            elif st.button("Mulai mode otomatis", disabled=bool(k.kerja)):
                st.session_state.henti = threading.Event()
                ev = st.session_state.henti
                k.mulai_tugas("mode otomatis", lambda: k.mode_otomatis(W, ev, jeda, amb / 100, tahan))
            st.caption("Aturan dari UNTUK_DAUZAN.md (sim `dinamis.py`: pemicu >20% terbaik). Tiap sapuan memutus daya sesaat.")
    cc = st.columns([4, 1, 1])
    perintah = cc[0].text_input("Perintah bebas (sama dengan Serial Monitor)", key="cmd_bebas", placeholder="contoh: VPANEL 17, CEKVOC 1, SIKLUS V3_opak 3")
    if cc[0].button("Kirim perintah") and perintah: k.kirim(perintah)
    if cc[1].button("LANJUT", width="stretch"): k.kirim("LANJUT")
    if cc[2].button("BATAL", width="stretch"): k.kirim("BATAL")

    tampilan_langsung(k)


@st.fragment(run_every=1.0)
def tampilan_langsung(k):
    harapan, kurva_k = kembaran(round(st.session_state.skala, 3), st.session_state.bay)
    m = st.columns(5)
    m[0].metric("Susunan aktif", k.topo or "terbuka")
    m[1].metric("Tugas", k.kerja or "-")
    if k.sapuan:
        s = k.sapuan[-1]; ph = harapan.get(s.topologi, 0.0); d = selisih(s.pmax, ph)
        m[2].metric(f"Pmax terukur ({s.topologi})", f"{s.pmax:.3f} W")
        m[3].metric("Daya harapan (kembaran)", f"{ph:.3f} W", f"{d * 100:+.1f}%" if np.isfinite(d) else None)
        if np.isfinite(d) and abs(d) > ambang:
            st.error(f"⚠️ Daya terukur {d * 100:+.1f}% dari harapan kembaran ({st.session_state.bay}). Indikasi kelainan: "
                     "bayangan, kotoran, atau gangguan modul. Bukan diagnosis tervalidasi.")
    if k.riwayat_pilih:
        h = k.riwayat_pilih[-1]
        m[4].metric("Keputusan pemilih", h.get("pilihan") or "-", h.get("galat") or (f"{(h['pmax_pilihan'] / h['pmax_4S'] - 1) * 100:+.1f}% vs 4S" if h.get("pmax_4S") else None))

    if k.sapuan:
        s = k.sapuan[-1]
        terakhir = {}
        for sp in k.sapuan: terakhir[sp.topologi] = sp
        lap_i = [lapis_sapuan(sp, f"{t} terukur" + (" (terakhir)" if sp is s else "")) for t, sp in terakhir.items()]
        if s.topologi in kurva_k: lap_i.append(lapis_kembaran(kurva_k, s.topologi, s.voc, f"{s.topologi} kembaran"))
        g1, g2 = st.columns(2)
        g1.markdown(f"**Kurva I-V** (sapuan terakhir tiap susunan; terbaru: `{s.label}`)")
        g1.altair_chart(grafik(lap_i, "I_mA", "Arus (mA)"), width="stretch")
        g2.markdown("**Kurva P-V**")
        g2.altair_chart(grafik(lap_i, "P_W", "Daya (W)"), width="stretch")

        baris = []
        for sp in reversed(k.sapuan[-30:]):
            ph = harapan.get(sp.topologi, float("nan")); d = selisih(sp.pmax, ph)
            pil = inti.pilih_susunan(sp, W)[0] if sp.topologi == "4S" else ""
            baris.append({"waktu": time.strftime("%H:%M:%S", time.localtime(sp.waktu)), "label": sp.label, "susunan": sp.topologi,
                          "Voc (V)": round(sp.voc, 2), "Pmax terukur (W)": round(sp.pmax, 4), "harapan kembaran (W)": round(ph, 4),
                          "selisih (%)": round(d * 100, 1), "pemilih (dari sapuan 4S)": sp.pemilih_esp or pil,
                          "berkas": os.path.basename(sp.sumber) if sp.sumber and sp.sumber != k.port else ""})
        st.markdown("**Riwayat sapuan**")
        st.dataframe(pd.DataFrame(baris), hide_index=True, width="stretch")
    else:
        st.info("Belum ada sapuan. Pilih susunan lalu SWEEP, atau tekan **Pilih susunan otomatis**.")

    if k.riwayat_pilih:
        with st.expander(f"Riwayat keputusan pemilih ({len(k.riwayat_pilih)})"):
            st.dataframe(pd.DataFrame([{kk: (round(v, 4) if isinstance(v, float) else v) for kk, v in h.items() if kk != "skor"}
                                       for h in reversed(k.riwayat_pilih)]), hide_index=True, width="stretch")
    with st.expander("Log serial", expanded=False):
        st.code("\n".join(s for _, s in list(k.log)[-60:]) or "(kosong)", language=None)
    if k.galat: st.error(k.galat)


# ================= MODE PUTAR ULANG =================
KOND_BAYANGAN = {"V3_opak": "Opak 1 sel modul A (V3_opak)", "V3_paranet": "Paranet modul A (V3)",
                 "V4_paranet": "Paranet modul A+B (V4)", "V6_paranet": "Paranet modul A+D diagonal (V6)"}


def bayangan_untuk(kond):
    for awal, nama in KOND_BAYANGAN.items():
        if kond.startswith(awal): return nama
    return "Tanpa bayangan"


@st.cache_data
def ringkasan_lab():
    """Rugi pemilih vs susunan tetap pada semua set lab yang dipakai (tanpa V5 dan V1d), seperti LAPORAN_UJI_FISIK.md."""
    rows = []
    for kond, ul in inti.daftar_kondisi().items():
        for u, f in ul.items():
            if not all(t in f for t in inti.KELAS): continue
            pm = {t: inti.baca_berkas(f[t]).pmax for t in inti.KELAS}; best = max(pm.values())
            pil = inti.pilih_susunan(inti.baca_berkas(f["4S"]), bobot())[0]
            rows.append({"kondisi": kond, "ulangan": u, "terbaik": max(pm, key=pm.get), "pemilih": pil,
                         "rugi pemilih (%)": (best - pm[pil]) / best * 100, "rugi tetap 2S2P (%)": (best - pm["2S2P"]) / best * 100,
                         "rugi tetap TCT (%)": (best - pm["TCT"]) / best * 100, "rugi tetap 4S (%)": (best - pm["4S"]) / best * 100})
    return pd.DataFrame(rows)


def halaman_putar_ulang():
    st.header("Putar ulang kurva tersimpan")
    sumber = st.radio("Folder", ["data_lab (lampu halogen)", "data_dasbor (sapuan dari dasbor)"], horizontal=True)
    folder = inti.DATA_LAB if sumber.startswith("data_lab") else inti.DATA_DASBOR
    semua = inti.daftar_kondisi(folder)
    if not semua:
        st.info(f"Belum ada berkas bernama <kondisi>_<susunan>_u<n>.csv di `{folder}`."); return
    c1, c2 = st.columns([3, 1])
    kond = c1.selectbox("Kondisi", sorted(semua), index=sorted(semua).index("V4_paranet65") if "V4_paranet65" in semua else 0)
    u = c2.selectbox("Ulangan", sorted(semua[kond]))
    berkas = semua[kond][u]
    if folder == inti.DATA_LAB:
        saran = bayangan_untuk(kond)
        if saran != st.session_state.bay:
            st.caption(f"Kondisi ini cocok dengan asumsi kembaran **{saran}** (atur di kiri). Untuk V1/V1b (lampu jauh), turunkan skala cahaya.")
    sp = {t: inti.baca_berkas(p) for t, p in berkas.items()}

    rows, lap_i = [], []
    for t in inti.TOPO:
        if t not in sp: continue
        s = sp[t]; ph = harapan[t]
        rows.append({"susunan": t, "Voc (V)": round(s.voc, 2), "Pmax terukur (W)": round(s.pmax, 4), "Vmp (V)": round(s.vmp, 2),
                     "harapan kembaran (W)": round(ph, 4), "selisih (%)": round(selisih(s.pmax, ph) * 100, 1),
                     "layak 24 V": "ya" if t != "4P" else "tidak (Voc di bawah 30 V)"})
        lap_i.append(lapis_sapuan(s, f"{t} terukur"))
        lap_i.append(lapis_kembaran(kurva_k, t, s.voc, f"{t} kembaran"))

    m = st.columns(4)
    layak = {t: sp[t].pmax for t in inti.KELAS if t in sp}
    if "4S" in sp:
        pil, skor, x = inti.pilih_susunan(sp["4S"], W)
        best = max(layak, key=layak.get)
        m[0].metric("Pemilih (dari sapuan 4S)", pil)
        m[1].metric("Terbaik terukur (4S/2S2P/TCT)", best)
        if pil in layak: m[2].metric("Rugi pilihan pemilih", f"{(layak[best] - layak[pil]) / layak[best] * 100:.2f}%")
        if "2S2P" in layak: m[3].metric("Rugi bila tetap 2S2P", f"{(layak[best] - layak['2S2P']) / layak[best] * 100:.2f}%")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    pilih_seri = st.multiselect("Tampilkan", sorted({d.seri.iloc[0] for d in lap_i}),
                                default=[d.seri.iloc[0] for d in lap_i if d.jenis.iloc[0] == "terukur" and not d.seri.iloc[0].startswith("4P")])
    lap = [d for d in lap_i if d.seri.iloc[0] in pilih_seri]
    g1, g2 = st.columns(2)
    if lap:
        g1.markdown("**Kurva I-V**"); g1.altair_chart(grafik(lap, "I_mA", "Arus (mA)"), width="stretch")
        g2.markdown("**Kurva P-V**"); g2.altair_chart(grafik(lap, "P_W", "Daya (W)"), width="stretch")
    if "4S" in sp and x is not None:
        with st.expander("Fitur bentuk dan skor pemilih"):
            st.dataframe(pd.DataFrame({"fitur": inti.NAMA_FITUR, "nilai": np.round(x.astype(float), 4)}), hide_index=True, width="stretch")
            st.write({k_: round(v, 3) for k_, v in zip(inti.KELAS, skor)})

    if folder == inti.DATA_LAB:
        with st.expander("Ringkasan semua set lab (pemilih vs susunan tetap)"):
            df = ringkasan_lab()
            st.write(f"{len(df)} set, sumber: **lab** (lampu halogen, 6 pola independen). Rugi rata-rata terhadap terbaik terukur:")
            st.dataframe(df.drop(columns=["kondisi", "ulangan", "terbaik", "pemilih"]).mean().round(2).to_frame("rata-rata").T, width="stretch")
            st.dataframe(df.round(2), hide_index=True, width="stretch")


if halaman.startswith("Langsung"): halaman_langsung()
else: halaman_putar_ulang()
