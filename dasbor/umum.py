"""Bagian bersama dasbor: klien API server lokal, grafik, dan label sumber data (CONTRACT.md §1.2, §5).
Dasbor tidak membuka port serial dan tidak menjalankan model; semuanya lewat server (http://127.0.0.1:8000)."""
import os, sys

import altair as alt
import pandas as pd
import requests
import streamlit as st

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)
from shadeshift import config  # noqa: E402

WARNA = {"4S": "#1F77B4", "2S2P": "#FF7F0E", "TCT": "#2CA02C", "4P": "#9467BD", "?": "#7F7F7F"}
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


def kirim_perintah(device_id, kind, command, params=None):
    try:
        r = post(f"/devices/{device_id}/commands", {"kind": kind, "command": command, "params": params or {}})
        st.toast(f"Perintah {r['command']} dikirim ke {device_id}")
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
