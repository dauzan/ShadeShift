"""Edge gateway end to end (CONTRACT §1, §5.2, §5.3, §7): emulated ESP32 -> gateway (edge AI) -> server."""
import time
import uuid

import requests

from conftest import free_port, live_server
from shadeshift import config
from shadeshift.gateway.main import Gateway
from shadeshift.gateway.uplink import ServerLink


def _wait(pred, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.1)
    return None


def _command(settings, device_id, body):
    r = requests.post(f"{settings.api_url}/api/v1/devices/{device_id}/commands", json=body, timeout=10)
    assert r.status_code == 202, r.text
    cid = r.json()["id"]

    def done():
        for c in requests.get(f"{settings.api_url}/api/v1/devices/{device_id}/commands", timeout=10).json():
            if c["id"] == cid and c["status"] in ("done", "failed"):
                return c
    return _wait(done)


def test_auto_select_runs_at_the_edge(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            assert _command(settings, "demo-01", {"kind": "action", "command": "demo_condition",
                                                  "params": {"condition": "V6_paranet65"}})["status"] == "done"
            res = _command(settings, "demo-01", {"kind": "action", "command": "auto_select"})
            assert res["status"] == "done" and res["result"] in ("4S", "2S2P", "TCT")
            dec = _wait(lambda: core.db.query("SELECT * FROM decisions WHERE trigger='auto_once'"))[0]
            assert dec["decided_by"] in ("gateway_onnx", "gateway_numpy") and dec["applied"] == 1
            sweeps = _wait(lambda: (lambda r: r if len(r) >= (1 if dec["choice"] == "4S" else 2) else None)(
                core.db.query("SELECT * FROM sweeps WHERE device_id='demo-01' ORDER BY id")))
            assert all(s["source"] == "demo" and s["replay_of"].startswith("V6_paranet65_") for s in sweeps)
            assert sweeps[0]["topology"] == "4S" and sweeps[0]["condition"] == "V6_paranet65"
            metrics = _wait(lambda: {r["name"]: r["provenance"] for r in core.db.query("SELECT name, provenance FROM metrics")}
                            if core.db.query("SELECT 1 FROM metrics WHERE name='decision_us'") else None)
            assert metrics["sweep_ms"] == "emulated" and metrics["decision_us"] == "measured"
            assert _wait(lambda: core.db.query("SELECT 1 FROM events WHERE kind='switch'"))
            log = _wait(lambda: core.db.query("SELECT line FROM device_log WHERE device_id='demo-01'"))
            assert any(r["line"].startswith("# MULAI") for r in log)
        finally:
            gw.stop()
        run = core.db.one("SELECT ended_at FROM runs WHERE uuid=?", (gw.run_uuid,))
        assert run["ended_at"] is not None                        # clean stop ends the run


def test_cycle_and_stop_and_gateway_side_allowlist(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            res = _command(settings, "demo-01", {"kind": "action", "command": "cycle", "params": {"label": "uji", "repeats": 1}})
            assert res["status"] == "done" and res["result"] == "4 sweeps"
            labels = sorted(r["label"] for r in core.db.query("SELECT label FROM sweeps WHERE device_id='demo-01'"))
            assert labels == ["uji_2S2P_u1", "uji_4P_u1", "uji_4S_u1", "uji_TCT_u1"]
            assert _command(settings, "demo-01", {"kind": "action", "command": "stop"})["result"] == "all relays open"
            bad = _command(settings, "demo-01", {"kind": "action", "command": "demo_condition", "params": {"condition": "V9_nope"}})
            assert bad["status"] == "failed"
            gw._execute({"id": 0, "kind": "raw", "command": "RELAI 6 1"})       # bypassing the server is refused too
            assert "RELAI" not in "".join(s for _, s in gw.kon.log if s.startswith(">>>"))
        finally:
            gw.stop()


def test_outbox_keeps_data_while_server_is_down(tmp_path):
    port = free_port()
    settings = config.load(env={"SHADESHIFT_DATA_DIR": str(tmp_path), "SHADESHIFT_API_PORT": str(port)},
                           env_file=tmp_path / "no.env")
    link = ServerLink(settings.api_url, tmp_path / "outbox.db")
    run_uuid = str(uuid.uuid4())
    hb = {"device_id": "esp32-99", "kind": "esp32", "transport": "test", "run_uuid": run_uuid, "state": {"connected": True}}
    assert link.heartbeat(hb) is None and not link.online          # server down
    link.start()
    for k in range(3):
        link.enqueue("sweep", {"uuid": str(uuid.uuid4()), "device_id": "esp32-99", "run_uuid": run_uuid, "source": "device",
                               "label": f"s{k}", "topology": "4S", "captured_at": "2026-10-18T03:15:30.123Z",
                               "points": {"v": [3.0, 2.0, 1.0] * 4, "i": [0.0, 0.01, 0.02] * 4}})
    time.sleep(1.0)
    assert link.pending() == 3
    with live_server(tmp_path / "srv", port=port) as (_, core):
        assert link.heartbeat(hb) is not None
        assert _wait(lambda: link.pending() == 0, 20)
        assert len(core.db.query("SELECT id FROM sweeps WHERE device_id='esp32-99'")) == 3
    link.stop()


def test_stop_via_api_during_auto_select(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = Gateway(settings, source="demo", lambat=0.5)          # slow enough to press Stop mid-flow
        gw.start()
        try:
            r = requests.post(f"{settings.api_url}/api/v1/devices/demo-01/commands",
                              json={"kind": "action", "command": "auto_select"}, timeout=10).json()["id"]
            assert _wait(lambda: any(s.startswith(">>> SWEEP") for _, s in gw.kon.log), 20)
            stop = _command(settings, "demo-01", {"kind": "action", "command": "stop"})
            assert stop["status"] == "done" and stop["result"] == "all relays open"
            sel = _wait(lambda: next((c for c in requests.get(f"{settings.api_url}/api/v1/devices/demo-01/commands",
                                                               timeout=10).json() if c["id"] == r and c["status"] != "sent"), None))
            assert sel["status"] == "failed"
            tx = [s[4:] for _, s in gw.kon.log if s.startswith(">>> ")]
            assert tx[tx.index("OFF") + 1:] == [] and gw.kon.topo is None
            assert not core.db.query("SELECT 1 FROM decisions WHERE applied=1")
        finally:
            gw.stop()
