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
    at = AppTest.from_file(str(ROOT / "dasbor" / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert any("STOP" in b.label for b in at.sidebar.button)
