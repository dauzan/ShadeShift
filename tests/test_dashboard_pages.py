"""Dashboard pages (Stage 3) rendered against a live server with the demo gateway: no exceptions, honest labels."""
import time

import pytest
import requests
from streamlit.testing.v1 import AppTest

from conftest import ROOT, live_server
from shadeshift.gateway.main import Gateway

PAGES = ROOT / "dasbor" / "halaman"


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dash")
    with live_server(tmp) as (settings, core):
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        api = settings.api_url + "/api/v1"
        requests.post(f"{api}/import/lab", json={}, timeout=120)
        cid = requests.post(f"{api}/devices/demo-01/commands", json={"kind": "action", "command": "auto_select"},
                            timeout=10).json()["id"]
        end = time.time() + 60
        while time.time() < end and not core.db.query("SELECT 1 FROM commands WHERE id=? AND status='done'", (cid,)):
            time.sleep(0.2)
        files = [("files", (n, (ROOT / "samples" / n).read_bytes(), "text/csv")) for n in ("V3_opak_4S_u1.csv", "bad_non_numeric.csv")]
        requests.post(f"{api}/uploads", files=files, timeout=60)
        time.sleep(1.5)                                    # let the gateway's outbox deliver the decision and events
        try:
            yield settings, core
        finally:
            gw.stop()


@pytest.fixture(autouse=True)
def point_dashboard_at_server(stack, monkeypatch):
    monkeypatch.setenv("SHADESHIFT_API_URL", stack[0].api_url)


def run_page(name):
    at = AppTest.from_file(str(PAGES / name), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def test_live_page_shows_edge_decision_and_demo_label():
    at = run_page("langsung.py")
    assert any("DEMO" in w.value for w in at.warning)
    labels = [m.label for m in at.metric]
    assert "Keputusan pemilih (AI)" in labels and "Susunan aktif" in labels
    assert any("gateway laptop" in c.value for c in at.caption)               # where the AI decision ran
    assert len(at.dataframe) >= 1                                                 # sweep history from the database


def test_live_page_button_queues_command(stack):
    settings, core = stack
    n = len(core.db.query("SELECT id FROM commands"))
    at = run_page("langsung.py")
    next(b for b in at.button if b.label == "STATUS").click().run()
    assert not at.exception
    assert len(core.db.query("SELECT id FROM commands")) == n + 1


def test_replay_page_lab_set_and_summary():
    at = run_page("putar_ulang.py")
    labels = [m.label for m in at.metric]
    assert "Pemilih (dari sapuan 4S)" in labels and "Rugi bila tetap 2S2P" in labels


def test_other_pages_render():
    up = run_page("unggah.py")
    assert any("Format yang diterima" in m.value for m in up.markdown)
    ev = run_page("peristiwa.py")
    assert len(ev.dataframe) == 1
    st_ = run_page("status.py")
    assert any("onnxruntime" in str(m.delta) or "numpy" in str(m.delta) for m in st_.metric)


def test_app_navigation_and_stop_button():
    """Consumer view (CONTRACT §19): Beranda opens first, with the stop button; no sidebar, words only."""
    at = AppTest.from_file(str(ROOT / "dasbor" / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert any(b.label == "Hentikan semua" for b in at.button)
    assert not at.sidebar.button
    src = (ROOT / "dasbor" / "app.py").read_text(encoding="utf-8")
    assert 'position="top"' in src and "icon=" not in src


def test_consumer_pages_render():
    import re
    emoji = re.compile("[🌀-🫿☀-➿]")
    k = run_page("kurva_iv.py")
    assert [m.label for m in k.metric][:3] == ["Daya sekarang", "Dibanding normal", "Tanda gangguan"]   # plain words first
    assert any(e.label == "Lihat kurva lengkap" for e in k.expander)                                    # the curve on request
    assert any("Mode demo" in w.value for w in k.warning)                     # demo data always says so
    html = " ".join(str(h.proto.body) for h in k.get("html"))
    assert "Analisis 24 jam" in html and "Saat ini" in html and ">AI<" in html     # the analyser box
    assert "belum divalidasi" in html
    d = next(x for x in k.button if x.label == "Diagnosis dengan AI")            # CONTRACT §23: never pretends in demo
    assert d.disabled and "mode demo" in d.help
    assert "Diagnosis penyebab oleh AI di ESP32: mode demo" in html
    r = run_page("riwayat.py")
    assert {"24 jam terakhir", "Saat ini"} <= {s.value for s in r.subheader}
    assert any("Analisis 24 jam" in str(h.proto.body) for h in r.get("html"))
    assert any("Mode demo" in w.value for w in r.warning)
    b = run_page("beranda.py")
    assert any(x.label == "Perangkat" for x in b.selectbox)
    for name in ("beranda.py", "kurva_iv.py", "riwayat.py", "janji.py", "perangkat.py", "rangkaian.py"):
        assert not emoji.search((PAGES / name).read_text(encoding="utf-8")), name


def test_rangkaian_page(stack):
    """Rekomendasi Rangkaian (CONTRACT §29): the fifth page, the 3D wiring page embedded without its own scrollbar."""
    r = run_page("rangkaian.py")
    assert any(t.value == "Rekomendasi Rangkaian" for t in r.title)
    src = (ROOT / "dasbor" / "app.py").read_text(encoding="utf-8")
    nav = src.split("st.navigation")[1]
    assert [x for x in ("beranda.py", "kurva_iv.py", "riwayat.py", "perangkat.py", "rangkaian.py") if x in nav] ==         ["beranda.py", "kurva_iv.py", "riwayat.py", "perangkat.py", "rangkaian.py"]
    assert 'title="Rekomendasi Rangkaian"' in nav


def test_perangkat_page(stack):
    """Perangkat (CONTRACT §25): the status of every part, in words; the demo device has no hardware to check."""
    r = run_page("perangkat.py")
    assert [s.value for s in r.subheader] == ["Sambungan", "Pengukuran", "Saklar dan panel", "Pemantauan"]
    assert any("Mode demo" in w.value for w in r.warning)
    b = next(x for x in r.button if x.label == "Periksa ulang perangkat")
    assert b.disabled                                                           # nothing to ask an emulated ESP32
    body = " ".join(str(h.proto.body) for h in r.get("html"))
    assert "<th>Bagian</th>" in body and "Pengubah analog ke digital ADS1115" in body and "Mode demo" in body
    src = (ROOT / "dasbor" / "app.py").read_text(encoding="utf-8")
    assert '"perangkat.py"), title="Perangkat"' in src and "janji.py" not in src.split("st.navigation")[1]   # Bukti hidden


def test_bukti_page(stack):
    """Bukti (team page, out of the navigation; CONTRACT §24): promises and targets; demo data never counts as proof."""
    r = run_page("janji.py")
    assert [s.value for s in r.subheader] == ["Janji proposal", "Empat target", "Uji coba di papan", "Daya kendali"]
    assert any("Belum ada ESP32 nyata" in i.value for i in r.info)
    body = " ".join(str(h.proto.body) for h in r.get("html"))
    assert "Minimal 3 uji coba penuh" in body and "Belum diukur" in body and "Pembanding, bukan bukti" in body
    assert "otomatis" not in body.lower()                                       # automatic reconfiguration left out
    assert any(m.value.startswith("**0 dari 3 uji coba penuh.**") for m in r.markdown)


def test_audit_trail_tab_in_riwayat(stack):
    """Jejak audit (CONTRACT §22): a tab in Riwayat with periods, who acted, the demo label and the CSV download."""
    r = run_page("riwayat.py")
    assert [t.label for t in r.tabs] == ["Ringkasan", "Jejak audit"]
    assert any(x.label == "Jenis" for x in r.selectbox) and any(x.label == "Tampilkan semua" for x in r.toggle)
    tabel = " ".join(str(h.proto.body) for h in r.get("html") if "class='jejak'" in str(h.proto.body))
    assert "<th>Siapa</th>" in tabel and "Pengguna meminta Pilih susunan dengan AI" in tabel and "Mode demo" in tabel
    assert any("Mode demo: catatan ini berasal dari ESP32 tiruan" in c.value for c in r.caption)
    assert any(b.proto.label == "Unduh jejak audit (CSV)" for b in r.get("download_button"))
    next(x for x in r.toggle if x.label == "Tampilkan semua").set_value(True).run()
    assert not r.exception, r.exception
    assert any(c.value.startswith("Menampilkan 1 sampai") and "Semua catatan" in c.value for c in r.caption)


def test_data_collection_page_session_scan_and_export(stack):
    settings, core = stack
    at = run_page("ambil_data.py")
    assert any("TIRUAN" in w.value for w in at.warning)                         # the demo device is never "real" data
    next(b for b in at.button if b.label == "Mulai sesi").click().run()
    assert not at.exception, at.exception
    sess = core.db.one("SELECT id, ended_at FROM sessions WHERE device_id='demo-01'")
    assert sess and sess["ended_at"] is None
    assert any("TIRUAN" in c.value and "_A1_<susunan>" in c.value for c in at.caption)   # file-name preview
    next(b for b in at.button if b.label == "▶ Mulai scan penuh").click().run()
    assert not at.exception, at.exception
    end = time.time() + 180                                                     # slow when the laptop is busy
    while time.time() < end and not core.db.one("SELECT 1 FROM scans WHERE status='done'"):
        time.sleep(0.2)
    sc = core.db.one("SELECT condition, rounds, with_panels, status FROM scans")
    assert sc["status"] == "done" and sc["rounds"] == 3 and sc["with_panels"] == 0
    at = run_page("ambil_data.py")
    assert len(at.dataframe) >= 2                                                # scan table + Pmax table
    assert any("complete" in m.value for m in at.markdown)                       # quality checks are shown
    assert any("Penyebab" in m.value and "no active model" in m.value for m in at.markdown)   # diagnosis card, said plainly
    live = run_page("langsung.py")
    assert any("Diagnosis AI terakhir" in e.label for e in live.expander)
    next(b for b in at.button if b.label == "Siapkan zip").click().run()
    assert not at.exception, at.exception
    next(b for b in at.button if b.label == "Akhiri sesi").click().run()
    assert core.db.one("SELECT ended_at FROM sessions WHERE id=?", (sess["id"],))["ended_at"]


def test_target_vs_evidence_page(stack):
    settings, core = stack
    at = run_page("bukti.py")
    assert any("belum diukur" in m.value for m in at.markdown)               # no measured evidence in this stack
    assert len(at.dataframe) >= 4                                             # one evidence table per target
    n = len(core.db.query("SELECT id FROM metrics WHERE provenance='manual'"))
    at.number_input[0].set_value(0.40)
    at.number_input[1].set_value(1.50)
    next(b for b in at.button if b.label == "Simpan pengukuran").click().run()
    assert not at.exception, at.exception
    assert len(core.db.query("SELECT id FROM metrics WHERE provenance='manual'")) == n + 2
    at = run_page("bukti.py")
    power = [df.value for df in at.dataframe if "satuan" in df.value.columns and (df.value["satuan"] == "W").any()]
    assert power and any(r["sumber"] == "terukur" and r["nilai"] == "1.9" for _, r in power[0].iterrows()), power
    at.radio[0].set_value("demo").run()
    assert not at.exception, at.exception
    assert any("DEMO bukan bukti" in w.value for w in at.warning)


def test_model_page_trains_and_shows_a_candidate(stack):
    settings, core = stack
    at = run_page("model_ai.py")
    reg = [df.value for df in at.dataframe if "model" in df.value.columns]
    assert reg and reg[0]["model"].str.startswith("pemilih-logreg-v1@").any()  # the shipped selector is registered
    n = len(core.db.query("SELECT id FROM models"))
    next(b for b in at.button if b.label == "Latih dan uji").click().run(timeout=300)
    assert not at.exception, at.exception
    assert len(core.db.query("SELECT id FROM models")) == n + 1
    assert any(m.label == "Akurasi seimbang" for m in at.metric)                # the new candidate's fair-test result
    assert any("lab" in c.value and "Cara uji" in c.value for c in at.caption)


def test_l3_page_renders():
    at = run_page("l3.py")
    assert any("Hitungan desain" in c.value for c in at.caption)
    assert len(at.dataframe) >= 2                                              # holding power + net gain tables
    assert any("Belum divalidasi" in m.value for m in at.markdown)


def test_twin_page_embeds_the_server_page(stack):
    at = run_page("kembaran.py")
    assert any("Kembaran = simulasi" in c.value for c in at.caption)
    assert len(at.selectbox) == 1                                             # device choice; the twin itself is the iframe
