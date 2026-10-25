"""Bagian bersama dasbor: klien API server lokal, grafik, dan label sumber data (docs/CONTRACT.md §1.2, §5).
Dasbor tidak membuka port serial dan tidak menjalankan model; semuanya lewat server (http://127.0.0.1:8000)."""
import os, sys

import altair as alt
import pandas as pd
import requests
import streamlit as st

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)
from shadeshift import config  # noqa: E402

WARNA = {"4S": "#1F77B4", "2S2P": "#FF7F0E", "TCT": "#2CA02C", "4P": "#9467BD", "?": "#7F7F7F",
         "A": "#8C564B", "B": "#E377C2", "C": "#BCBD22", "D": "#17BECF"}          # panel tunggal (firmware 3.2)
TOPO = ["4S", "2S2P", "TCT", "4P"]
SUMBER = {"device": "terukur (ESP32)", "demo": "DEMO: data lab diputar ulang", "upload": "unggahan CSV",
          "lab": "data lab (lampu halogen)"}
DIPUTUSKAN = {"esp32": "ESP32 (di papan)", "gateway_onnx": "gateway laptop (ONNX Runtime)",
              "gateway_numpy": "gateway laptop (numpy)", "server_onnx": "server (ONNX Runtime)",
              "server_numpy": "server (numpy)"}
BAYANGAN = {"none": "Tanpa bayangan", "opak_A": "Opak 1 sel modul A (V3_opak)", "paranet_A": "Paranet modul A (V3)",
            "paranet_AB": "Paranet modul A+B (V4)", "paranet_AD": "Paranet modul A+D diagonal (V6)"}


class ServerMati(Exception):
    pass


def _settings():
    return config.load()


def api(method, path, timeout=10, **kw):
    """Panggil API server; kembalikan JSON. Galat jaringan -> ServerMati, galat 4xx/5xx -> RuntimeError(detail)."""
    s = _settings()
    headers = {"X-ShadeShift-Token": s.api_token} if s.api_token else {}
    try:
        r = requests.request(method, f"{s.api_url}/api/v1{path}", headers=headers, timeout=timeout, **kw)
    except requests.RequestException as e:
        raise ServerMati(str(e)) from None
    if r.status_code >= 400:
        try: detail = r.json().get("detail")
        except ValueError: detail = r.text
        raise RuntimeError(detail if isinstance(detail, str) else str(detail))
    ct = r.headers.get("content-type", "")
    return r.json() if "json" in ct else r.text


def unduh(path):
    """Berkas biner dari server (mis. ekspor zip sesi)."""
    s = _settings()
    headers = {"X-ShadeShift-Token": s.api_token} if s.api_token else {}
    try:
        r = requests.get(f"{s.api_url}/api/v1{path}", headers=headers, timeout=120)
    except requests.RequestException as e:
        raise ServerMati(str(e)) from None
    if r.status_code >= 400: raise RuntimeError(r.text[:300])
    return r.content


def get(path, **params): return api("GET", path, params=params)
def post(path, json=None, **kw): return api("POST", path, json=json, **kw)
def put(path, json=None): return api("PUT", path, json=json)


def server_hidup():
    """True bila server menjawab; bila tidak, tampilkan petunjuk cara menyalakannya."""
    try:
        get("/health")
        return True
    except ServerMati:
        st.error("Server lokal tidak menjawab di " + _settings().api_url + ". Jalankan dulu:  "
                 "`.venv\\Scripts\\python run.py demo`  (atau `run.py server`).")
        return False


def kirim_perintah(device_id, kind, command, params=None, nama=None):
    """nama: what the toast calls it (the button's words); default the command itself."""
    try:
        r = post(f"/devices/{device_id}/commands", {"kind": kind, "command": command, "params": params or {}})
        st.toast(f"{nama} dikirim ke {device_id}" if nama else f"Perintah {r['command']} dikirim ke {device_id}")
        return r
    except RuntimeError as e:
        st.error(f"Perintah ditolak: {e}")
    except ServerMati:
        st.error("Server tidak menjawab; perintah tidak terkirim.")


def tombol_stop(key="stop"):
    """Tombol Stop untuk semua alat: batalkan tugas, buka semua relai (CONTRACT §5.3)."""
    if st.button("⏹ STOP semua", key=key, type="primary", width="stretch",
                 help="Membatalkan tugas otomatis dan membuka semua relai di semua alat. Firmware menyelesaikan langkah "
                      "yang sedang berjalan dulu (sapuan bisa 3-4 s). Butuh server dan gateway hidup; tanpa perangkat "
                      "lunak: cabut adaptor 12 V."):
        try:
            r = post("/stop_all")
            st.toast(f"Stop dikirim ke {len(r['queued'])} alat")
        except (RuntimeError, ServerMati) as e:
            st.error(f"Stop gagal dikirim: {e}. Cabut adaptor 12 V bila perlu.")


def label_sumber(source):
    return SUMBER.get(source, source)


def label_keputusan(decided_by):
    return DIPUTUSKAN.get(decided_by, decided_by or "-")


def tabel_sapuan(rows):
    """SweepSummary -> DataFrame untuk tampilan, dengan sumber data selalu terlihat."""
    out = []
    for s in rows:
        d = s.get("decision") or {}
        out.append({"id": s["id"], "waktu (UTC)": (s.get("captured_at") or "")[11:19], "label": s["label"],
                    "susunan": s["topology"], "Pmax (W)": s["pmax"], "Voc (V)": s["voc"],
                    "sumber": label_sumber(s["source"]), "lengkap": "ya" if s.get("complete", True) else "TIDAK",
                    "pemilih": f"{d['choice']} ({label_keputusan(d['decided_by'])})" if d else "",
                    "sapuan (ms)": s.get("sweep_ms"), "pindah (ms)": s.get("switch_ms"),
                    "berkas lab": s.get("replay_of") or ""})
    return pd.DataFrame(out)


def lapis_sapuan(sweep, nama=None):
    p = sweep["points"]
    df = pd.DataFrame({"V": p["v"], "I_mA": [x * 1000 for x in p["i"]]})
    df = df[df.V > 0]
    df["P_W"] = df.V * df.I_mA / 1000
    df["seri"] = nama or f"{sweep['topology']} terukur"
    df["jenis"] = "terukur"
    return df


def lapis_kembaran(v, i, topo):
    df = pd.DataFrame({"V": v, "I_mA": [x * 1000 for x in i]})
    df["P_W"] = df.V * df.I_mA / 1000
    df["seri"] = f"{topo} kembaran"
    df["jenis"] = "kembaran"
    return df


def grafik(lapisan, sumbu_y, judul_y, catatan=None):
    lapisan = [d for d in lapisan if d is not None and not d.empty]
    if not lapisan: return None
    df = pd.concat(lapisan, ignore_index=True)
    seri = list(df.seri.unique())
    warna = alt.Color("seri:N", scale=alt.Scale(domain=seri, range=[WARNA.get(s.split(" ")[0], "#7F7F7F") for s in seri]),
                      legend=alt.Legend(title=None, orient="bottom"))
    ch = alt.Chart(df).mark_line().encode(
        x=alt.X("V:Q", title="Tegangan (V)"), y=alt.Y(f"{sumbu_y}:Q", title=judul_y), color=warna,
        strokeDash=alt.condition(alt.datum.jenis == "kembaran", alt.value([5, 4]), alt.value([1, 0])),
        tooltip=["seri", alt.Tooltip("V:Q", format=".2f"), alt.Tooltip(f"{sumbu_y}:Q", format=".4f")])
    return ch.properties(height=300, title=catatan or "").interactive()


@st.cache_data(ttl=300, show_spinner=False)
def kurva_kembaran(topo, voc_max, scale, shading):
    try:
        return get("/twin/curve", topology=topo, voc_max=round(voc_max, 1), scale=scale, shading=shading)
    except (RuntimeError, ServerMati):
        return None


# ---------------- diagnosis dan peta modul (docs/CONTRACT.md §15) ----------------
POLA = {"none": "tidak ada modul terdampak", "one": "satu modul (posisinya tidak bisa dibedakan dari sapuan topologi)",
        "string_pair": "dua modul satu string (A+B atau C+D)", "row_pair": "dua modul satu baris (A+C atau B+D)",
        "diagonal": "dua modul diagonal (A+D atau B+C)", "three": "tiga modul", "all": "keempat modul"}
PETUNJUK = {"shaded_or_dimmed": "arus turun: terbayangi / redup", "bypassed_cells": "tegangan turun: sel/dioda terpintas?",
            "series_resistance": "daya turun, arus dan tegangan normal: hambatan seri?"}
STATUS_MODUL = {"normal": "🟢 normal", "reduced": "🟡 turun", "strongly_reduced": "🔴 turun banyak"}


def _baris_model(p, nama):
    if "error" in p:
        return f"**{nama}**: {p['error']}"
    from shadeshift import fieldwork
    teks = fieldwork.DIAGNOSIS.get(p["class"]) or POLA.get(p["class"], p["class"])
    status = (f"model `{p['model_id']}` diuji pada data {p['evidence']} ({p['test_mode']}), akurasi seimbang "
              f"{p['balanced_accuracy']} %")
    if p["evidence"] != "real":
        status += " · **belum divalidasi dengan data terukur**"
    return f"**{nama}: {teks}** (keyakinan {p['confidence'] * 100:.0f} %)  \n{status}"


def kartu_diagnosis(d, judul=None):
    """Cause and pattern from the active models, and the 2x2 map from the single-panel sweeps."""
    if judul: st.markdown(f"**{judul}**")
    st.markdown(_baris_model(d["diagnosis"], "Penyebab"))
    st.markdown(_baris_model(d["pattern"], "Pola (dari sapuan topologi)"))
    peta = d.get("map")
    if not peta:
        st.caption("Peta modul butuh sapuan panel A-D (firmware 3.2) pada putaran ini.")
        return
    for baris in (("A", "C"), ("B", "D")):          # susunan fisik: A kiri atas, C kanan atas, B kiri bawah, D kanan bawah
        kol = st.columns(2)
        for k, m in zip(kol, baris):
            x = peta["modules"][m]
            with k.container(border=True):
                st.markdown(f"**{m}** · {STATUS_MODUL[x['status']]} · daya {x['power_rel'] * 100:.0f} %")
                st.caption(f"Isc {x['isc_rel'] * 100:.0f} %, Voc {x['voc_rel'] * 100:.0f} %"
                           + (f" · {PETUNJUK[x['hint']]}" if x["hint"] else ""))
    cocok = d.get("agrees")
    st.caption(f"Terukur: {POLA[peta['pattern']]}" + (f" ({peta['affected']})" if peta["affected"] else "")
               + ("" if cocok is None else " · pola dari sapuan topologi " + ("**cocok**" if cocok else "**tidak cocok**"))
               + f". Pembanding: {peta['reference']}. Aturan: {peta['rules']}.")


# ---------------- tampilan konsumen (Beranda, Kurva I-V, Riwayat; docs/CONTRACT.md §19) ----------------
# Teks hanya kata-kata: tanpa emoji atau simbol. Angka memakai koma desimal.
WARNA_KONDISI = {"normal": "#15803D", "object": "#DC2626", "diode": "#1D4ED8", "cable": "#1D4ED8", "nodata": "#94A3B8"}
KATA_KONDISI = {"normal": "Normal", "object": "Cahaya tertutup", "diode": "Masalah listrik", "cable": "Masalah listrik",
                "nodata": "Belum ada data"}


def angka(x, d=2):
    return "-" if x is None else f"{x:.{d}f}".replace(".", ",")


def umur(iso):
    """'12 menit lalu' dari waktu ISO (UTC)."""
    if not iso:
        return "belum ada"
    from datetime import datetime, timezone
    s = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds())
    if s < 60: return "baru saja"
    if s < 3600: return f"{round(s / 60)} menit lalu"
    if s < 86400: return f"{round(s / 3600)} jam lalu"
    return f"{round(s / 86400)} hari lalu"


def jam(iso):
    if not iso:
        return "-"
    from datetime import datetime
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H.%M")


def bingkai(path, device_id, tinggi_awal=1900):
    """Embed a page of the local server (the 3D Beranda, Rekomendasi Rangkaian) with no scrollbar of its own: the page
    reports its height (postMessage 'shadeshift-tinggi') and its frame is set to that height, so the main page scrolls.
    Only messages from the local server's origin, and from that very frame, are used."""
    import json
    from urllib.parse import urlsplit
    import streamlit.components.v1 as components
    url = _settings().api_url
    asal = "{0.scheme}://{0.netloc}".format(urlsplit(url))
    components.iframe(f"{url}{path}?device_id={device_id}", height=tinggi_awal, scrolling=False)
    components.html("""<script>
const P = window.parent, D = P.document, ASAL = %s;
if (!P.__ssTinggi) {
  P.__ssTinggi = true;
  P.addEventListener("message", (e) => {
    if (e.origin !== ASAL || !e.data || e.data.type !== "shadeshift-tinggi" || !(e.data.h > 200)) return;
    const f = [...D.querySelectorAll("iframe")].find((x) => x.contentWindow === e.source);
    if (f) f.style.setProperty("height", Math.ceil(e.data.h) + "px", "important");
  });
}
</script>""" % json.dumps(asal), height=0)


def kepala(judul):
    """Judul halaman, pilihan perangkat dan tombol berhenti. Mengembalikan baris perangkat, atau None (sudah dijelaskan)."""
    try:
        alat = [d for d in get("/devices") if d["kind"] != "virtual"]
    except ServerMati:
        st.title(judul)
        st.error("Server lokal tidak menjawab. Jalankan perintah run.py demo atau run.py live di laptop ini.")
        return None
    alat.sort(key=lambda d: (not d["online"], d["kind"] != "esp32", d["id"]))
    if st.session_state.get("_halaman") != judul:              # a new visit to this page (the analyser 'thinks' again)
        st.session_state["_halaman"] = judul
        st.session_state["_kunjungan"] = st.session_state.get("_kunjungan", 0) + 1
    a, b, c = st.columns([3, 2, 1], vertical_alignment="bottom")
    a.title(judul)
    if not alat:
        st.info("Belum ada perangkat. Jalankan run.py live (ESP32 di USB) atau run.py demo.")
        return None
    ids = [d["id"] for d in alat]
    if st.session_state.get("alat") not in ids:
        st.session_state.alat = ids[0]
    pilih = b.selectbox("Perangkat", ids, key="alat",
                        format_func=lambda i: next(f"{d['id']}, {'mode demo' if d['kind'] == 'emulator' else 'ESP32'}, "
                                                   f"{'terhubung' if d['online'] else 'tidak terhubung'}" for d in alat if d["id"] == i))
    if c.button("Hentikan semua", type="primary", width="stretch",
                help="Membuka semua relai dan menghentikan pemantauan di semua perangkat. Tanpa perangkat lunak: cabut adaptor 12 V."):
        try:
            r = post("/stop_all")
            st.toast(f"Perintah berhenti dikirim ke {len(r['queued'])} perangkat")
        except (RuntimeError, ServerMati) as e:
            st.error(f"Perintah berhenti gagal dikirim: {e}. Cabut adaptor 12 V bila perlu.")
    return next(d for d in alat if d["id"] == pilih)


# ---------------- kotak analisis (Kurva I-V, Riwayat; docs/CONTRACT.md §20) ----------------
_GAYA_AI = """<style>
.ss-ai{position:relative;margin:14px 0 18px 6px;padding:20px 16px 14px;border-radius:18px;background:#e9eef4;border:1px solid #dbe3ec}
.ss-ai .badge{position:absolute;top:-16px;left:-10px;width:42px;height:42px;border-radius:50%;background:#f8fafc;
  border:5px solid #dbe3ec;display:flex;align-items:center;justify-content:center;font:700 13px system-ui,sans-serif;color:#0f172a}
.ss-ai .grid{display:flex;gap:12px;flex-wrap:wrap}
.ss-ai .box{position:relative;background:#fff;border-radius:14px;padding:14px 16px;min-width:0;min-height:120px}
.ss-ai .day{flex:2 1 420px}.ss-ai .now{flex:1 1 260px}.ss-ai .new{flex:1 1 100%;border-left:4px solid #1d4ed8}
.ss-ai h4{margin:0 0 6px;font:600 12px system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#64748b}
.ss-ai .head{font:600 16px/1.4 system-ui,sans-serif;color:#0f172a;margin:0 0 8px}
.ss-ai p{margin:0 0 6px;font:14px/1.55 system-ui,sans-serif;color:#1e293b}
.ss-ai .basis{font:12px/1.4 system-ui,sans-serif;color:#64748b;margin:10px 0 0}
.ss-ai .think{position:absolute;inset:14px 16px;background:#fff;display:none}
.ss-ai.anim .think{display:block;animation:ss-hide .35s ease 1.9s forwards}
.ss-ai .think p{color:#475569;display:flex;align-items:center;gap:10px}
.ss-ai .dots{display:inline-flex;gap:5px}
.ss-ai .dots i{width:7px;height:7px;border-radius:50%;background:#1d4ed8;animation:ss-dot 1s infinite ease-in-out}
.ss-ai .dots i:nth-child(2){animation-delay:.15s}.ss-ai .dots i:nth-child(3){animation-delay:.3s}
.ss-ai .bar{height:10px;border-radius:6px;margin:10px 0;background:linear-gradient(90deg,#e2e8f0 25%,#f1f5f9 50%,#e2e8f0 75%);
  background-size:200% 100%;animation:ss-shim 1.1s infinite linear}
.ss-ai.anim .reveal{opacity:0;animation:ss-in .45s ease forwards;animation-delay:calc(2s + var(--k) * .2s)}
@keyframes ss-hide{to{opacity:0;visibility:hidden}}
@keyframes ss-dot{0%,80%,100%{transform:scale(.5);opacity:.35}40%{transform:scale(1);opacity:1}}
@keyframes ss-shim{to{background-position:-200% 0}}
@keyframes ss-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.ss-ai .think{display:none!important}.ss-ai .reveal{opacity:1!important;animation:none!important}}
</style>"""


def _berpikir(teks):
    return (f"<div class='think'><p><span class='dots'><i></i><i></i><i></i></span>{teks}</p>"
            "<div class='bar' style='width:92%'></div><div class='bar' style='width:76%'></div><div class='bar' style='width:84%'></div></div>")


def sejak(halaman, device_id):
    """The moment 'Yang baru' counts from: the newest measurement seen on the previous visit to this page (none on the
    first visit: the server then compares with the measurement before the newest). Fixed for the whole visit, so new
    data arriving while the page is open adds up in 'Yang baru'."""
    key, visit = f"_baru_{halaman}_{device_id}", st.session_state.get("_kunjungan", 0)
    s = st.session_state.get(key) or {}
    if s.get("visit") != visit:
        s = {"visit": visit, "sejak": s.get("terbaru"), "terbaru": s.get("terbaru")}
        st.session_state[key] = s
    return s["sejak"]


def ingat_terbaru(halaman, device_id, an):
    s = st.session_state.get(f"_baru_{halaman}_{device_id}")
    if s is not None and an.get("terbaru_at"):
        s["terbaru"] = an["terbaru_at"]


def kotak_analisis(an, halaman):
    """The analyser box: what is new since the last visit (full width), the 24-hour analysis (wide) and the current data
    (narrow). It 'thinks' briefly the first time it is shown after the user opens the page, then the sentences appear
    one by one."""
    import html as H
    kunci = (halaman, st.session_state.get("_kunjungan", 0))
    anim = st.session_state.get("_ai_terakhir") != kunci
    st.session_state["_ai_terakhir"] = kunci
    k = 0

    def baris(teks, cls="p"):
        nonlocal k
        k += 1
        tag = "div class='head reveal'" if cls == "head" else "p class='reveal'"
        return f"<{tag} style='--k:{k}'>{H.escape(teks)}</{tag.split()[0]}>"

    b = an.get("baru")
    new = ("".join([baris(b["judul"], "head")] + [baris(t) for t in b["lines"]]) if b else "")
    k = 0
    day = "".join([baris(an["day"]["headline"], "head")] + [baris(t) for t in an["day"]["lines"]])
    k = 0
    now = "".join([baris(an["now"]["headline"], "head")] + [baris(t) for t in an["now"]["lines"]])
    demo = "<p class='basis'>Data demo: kurva lab yang direkam dan model kembaran untuk panel tunggal, bukan pengukuran saat ini.</p>" if an.get("demo") else ""
    st.html(_GAYA_AI + f"<div class='ss-ai{' anim' if anim else ''}'><div class='badge'>AI</div><div class='grid'>"
            + (f"<div class='box new'><h4>Yang baru</h4>{new}{_berpikir('Mencari yang berubah')}</div>" if new else "")
            + f"<div class='box day'><h4>Analisis 24 jam</h4>{day}{_berpikir('Menganalisis data 24 jam terakhir')}</div>"
            f"<div class='box now'><h4>Saat ini</h4>{now}{_berpikir('Membaca pengukuran terakhir')}</div>"
            f"</div><p class='basis'>{H.escape(an['basis'])}</p>{demo}</div>")
