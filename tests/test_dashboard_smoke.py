"""Stage 0: the existing Streamlit dashboard runs with the pinned Streamlit version and the offline config."""
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_offline_streamlit_config():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["browser"]["gatherUsageStats"] is False
    assert cfg["client"]["toolbarMode"] == "minimal"           # no framework menu or branding on the page
    assert cfg["client"]["showErrorDetails"] == "type"
    assert cfg["server"]["headless"] is True


def test_app_without_server_explains_how_to_start(monkeypatch):
    # The dashboard is an API client: with no server it must say how to start one, not crash.
    monkeypatch.setenv("SHADESHIFT_API_URL", f"http://127.0.0.1:{_free_port()}")
    at = AppTest.from_file(str(ROOT / "dasbor" / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert any("run.py demo" in e.value for e in at.error)


def test_streamlit_server_starts_and_serves(tmp_path):
    port = _free_port()
    log = (tmp_path / "streamlit.log").open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "dasbor/app.py", "--server.port", str(port)],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 90
        health = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
                    health = r.read().decode()
                    break
            except OSError:
                time.sleep(0.5)
        assert health == "ok"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        log.close()
