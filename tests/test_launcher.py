"""run.py demo end to end: one command starts everything; stopping it opens the relays before the server goes away."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request

import pytest

from conftest import ROOT, free_port

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows console signals")


def _get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _wait(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = pred()
            if v:
                return v
        except OSError:
            pass
        time.sleep(0.5)
    return None


def test_demo_starts_everything_and_stops_in_safe_order(tmp_path):
    api_port, dash_port = free_port(), free_port()
    api = f"http://127.0.0.1:{api_port}/api/v1"
    env = {**os.environ, "SHADESHIFT_DATA_DIR": str(tmp_path), "SHADESHIFT_API_PORT": str(api_port),
           "SHADESHIFT_API_URL": f"http://127.0.0.1:{api_port}", "SHADESHIFT_DASHBOARD_PORT": str(dash_port),
           "SHADESHIFT_DEMO_SPEED": "5", "PYTHONIOENCODING": "utf-8"}
    log = (tmp_path / "launcher.log").open("w", encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(ROOT / "run.py"), "demo", "--no-browser"], cwd=ROOT, env=env,
                         stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        assert _wait(lambda: any(d["id"] == "demo-01" and d["online"] for d in _get(f"{api}/devices")), 120), "demo not up"
        assert _wait(lambda: urllib.request.urlopen(f"http://127.0.0.1:{dash_port}/_stcore/health", timeout=2).status == 200, 90)
        assert len(_get(f"{api}/sweeps?source=lab&limit=1000")) == 120          # lab data imported once
        # monitoring started by itself (consumer view, CONTRACT §19); a measurement on request is served by it
        assert _wait(lambda: (next(d for d in _get(f"{api}/devices") if d["id"] == "demo-01")["state"].get("monitor") or {}).get("on"), 60)
        cid = _post(f"{api}/devices/demo-01/commands", {"kind": "action", "command": "measure_now"})["id"]
        done = _wait(lambda: next((c for c in _get(f"{api}/devices/demo-01/commands") if c["id"] == cid
                                   and c["status"] in ("done", "failed")), None), 60)
        assert done["status"] == "done"
        p.send_signal(signal.CTRL_BREAK_EVENT)                                  # what Ctrl+C does in the window
        p.wait(timeout=90)
    finally:
        if p.poll() is None:
            subprocess.call(["taskkill", "/PID", str(p.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.close()
    out = (tmp_path / "launcher.log").read_text(encoding="utf-8", errors="replace")
    assert "Stopped." in out and "did not stop in time" not in out, out[-2000:]
    for port in (api_port, dash_port):                                         # nothing left listening
        with pytest.raises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
    con = sqlite3.connect(tmp_path / "shadeshift.db")
    run_ended = con.execute("SELECT ended_at FROM runs WHERE device_id='demo-01' ORDER BY id DESC LIMIT 1").fetchone()[0]
    tx = [r[0] for r in con.execute("SELECT line FROM device_log WHERE device_id='demo-01' AND dir='tx' ORDER BY id")]
    con.close()
    assert run_ended is not None                      # the gateway's final heartbeat reached the server
    assert tx[-1] == "OFF"                            # relays opened last, and the log got through before shutdown
