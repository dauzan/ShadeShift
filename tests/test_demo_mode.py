"""Demo mode (Stage 4): scenario files, the player, and the edge AI reacting to shading changes."""
import json
import time

import pytest
import requests

from conftest import live_server
from shadeshift import inti
from shadeshift.gateway import demo as D
from shadeshift.gateway.main import Gateway

CONDITIONS = inti.daftar_kondisi()


@pytest.mark.parametrize("name", D.available())
def test_shipped_scenarios_are_valid_and_labeled(name):
    sc = D.load(name, CONDITIONS)
    assert "DEMO" in sc["label"] and sc["timeline"][0]["at_s"] == 0
    assert sc["auto_mode"]["trigger_pct"] == 20


def test_loader_rejects_bad_scenarios(tmp_path):
    def write(obj):
        (tmp_path / "x.json").write_text(json.dumps(obj), encoding="utf-8")
    write({"timeline": [{"at_s": 0, "condition": "V9_nope"}]})
    with pytest.raises(D.ScenarioError, match="unknown lab condition"):
        D.load("x", CONDITIONS, folder=tmp_path)
    write({"timeline": [{"at_s": 0, "condition": "V1c"}, {"at_s": 0, "condition": "V1c"}]})
    with pytest.raises(D.ScenarioError, match="must increase"):
        D.load("x", CONDITIONS, folder=tmp_path)
    write({"timeline": [{"at_s": 0, "condition": "V1c", "repeat": 7}]})
    with pytest.raises(D.ScenarioError, match="no repeat 7"):
        D.load("x", CONDITIONS, folder=tmp_path)
    with pytest.raises(D.ScenarioError, match="not found"):
        D.load("missing", CONDITIONS, folder=tmp_path)
    with pytest.raises(D.ScenarioError):
        D.load("../x", CONDITIONS, folder=tmp_path)


def _command(settings, body):
    r = requests.post(f"{settings.api_url}/api/v1/devices/demo-01/commands", json=body, timeout=10)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_default_scenario_ai_follows_the_shading(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            _command(settings, {"kind": "action", "command": "demo_scenario_start", "params": {"name": "default", "speed": 20}})
            time.sleep(9.5)                      # one cycle at 20x: 180 s / 20
            assert gw.scenario.state() is not None
            _command(settings, {"kind": "action", "command": "stop"})
            end = time.time() + 20
            while time.time() < end and (gw.scenario.thread.is_alive() or gw.kon.kerja):
                time.sleep(0.2)
            assert not gw.scenario.thread.is_alive() and gw.auto_mode == {"on": False}
            time.sleep(2.5)                      # let the outbox deliver
        finally:
            gw.stop()
        applied = core.db.query("SELECT d.choice, d.trigger, s.replay_of FROM decisions d JOIN sweeps s ON s.id = d.sweep_id "
                                "WHERE d.applied = 1 ORDER BY d.id")
        steps = [(a["choice"], a["replay_of"].split("_4S_")[0]) for a in applied]
        # V1c u1 -> TCT, V3_paranet65 u1 -> 4S, V4_paranet65 u3 -> TCT (all correct in the lab data)
        assert steps[:3] == [("TCT", "V1c"), ("4S", "V3_paranet65"), ("TCT", "V4_paranet65")], steps
        assert applied[0]["trigger"] == "auto_once" and applied[1]["trigger"] == "auto_trigger"
        sweeps = core.db.query("SELECT source, replay_of FROM sweeps WHERE device_id='demo-01'")
        assert all(s["source"] == "demo" and s["replay_of"] for s in sweeps)
        assert {s["replay_of"] for s in sweeps if s["replay_of"].startswith("V4_")} <= {f"V4_paranet65_{t}_u3.csv" for t in inti.TOPO}
        events = [e["message"] for e in core.db.query("SELECT message FROM events WHERE device_id='demo-01' ORDER BY id")]
        assert any(m.startswith("DEMO scenario 'default' started") for m in events)
        assert any("DEMO scenario 'default' ended" in m for m in events)


def test_scenario_refused_on_a_real_device_and_when_busy(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            gw.serial = True                     # pretend: a real ESP32 never plays scenarios
            gw._execute({"id": 0, "kind": "action", "command": "demo_scenario_start", "params": {"name": "default"}})
            assert gw.scenario is None
            gw.serial = False
            gw._execute({"id": 0, "kind": "action", "command": "demo_scenario_start", "params": {"name": "kilat"}})
            first = gw.scenario
            gw._execute({"id": 0, "kind": "action", "command": "demo_scenario_start", "params": {"name": "default"}})
            assert gw.scenario is first          # second start refused while the first runs
        finally:
            gw.stop()
