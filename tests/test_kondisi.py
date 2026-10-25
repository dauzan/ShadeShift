"""Consumer view (CONTRACT §19): condition rules, 24-hour history, monitoring and the one-off panel check."""
import time

import pytest
import requests

from conftest import live_server
from shadeshift import commands, kondisi
from shadeshift.gateway.main import Gateway


def _panels(at, pmax, isc=None, voc=None):
    """One check round: single-panel sweeps A-D at `at` (seconds apart)."""
    isc = isc or {}
    voc = voc or {}
    return [{"topology": m, "captured_at": at.replace("00.000Z", f"{k:02d}.000Z"), "pmax": pmax.get(m, 0.25),
             "isc": isc.get(m, 0.028), "voc": voc.get(m, 18.0)} for k, m in enumerate("ABCD")]


def _array(at, pmax, light=None):
    return {"topology": "4S", "captured_at": at, "pmax": pmax, "voc": 70.0, "isc": 0.026, "vmp": 42.0, "imp": 0.018,
            "light_v": light}


def test_object_on_one_panel_is_located_and_worded():
    ps = _panels("2026-10-22T10:00:00.000Z", {"A": 0.03}, isc={"A": 0.004})
    k = kondisi.assess(True, "esp32", ps, [_array("2026-10-22T10:00:30.000Z", 0.74)], {"4S": 1.04})
    assert k["status"]["level"] == "problem"
    assert k["panels"]["A"]["state"] == "object" and k["panels"]["B"]["state"] == "normal"
    p = k["problems"][0]
    assert p["panel"] == "A" and p["place"] == "surface" and p["title"].startswith("Kemungkinan")
    assert "tidak terukur" in p["where"]                      # the position on the surface is never claimed
    assert "0,220 W" in p["how_much"]                         # Indonesian decimal comma
    assert not k["demo"]


def test_voltage_and_resistance_point_behind_the_panel():
    ps = _panels("2026-10-22T10:00:00.000Z", {"B": 0.18, "D": 0.18}, voc={"B": 12.0})
    k = kondisi.assess(True, "esp32", ps, [], None)
    places = {p["panel"]: p["place"] for p in k["problems"]}
    assert places == {"B": "diode", "D": "cable"}
    assert "1N5822" in next(p for p in k["problems"] if p["panel"] == "B")["where"]


def test_uniform_drop_is_light_not_a_panel():
    old = [_array(f"2026-10-22T0{h}:00:00.000Z", 1.0, light=1.2) for h in range(3)]
    ps = _panels("2026-10-22T10:00:00.000Z", {m: 0.15 for m in "ABCD"})
    now = _array("2026-10-22T10:00:30.000Z", 0.6, light=0.7)
    cloud = kondisi.assess(True, "esp32", ps, old + [now], {"4S": 1.04})
    assert [p["place"] for p in cloud["problems"]] == ["sky"] and all(v["state"] == "normal" for v in cloud["panels"].values())
    dim = kondisi.assess(True, "esp32", ps, [now], {"4S": 1.04})          # no light history: no cloud claimed
    assert [p["place"] for p in dim["problems"]] == ["array"]


def test_no_data_offline_and_demo_are_said_plainly():
    k = kondisi.assess(True, "emulator", [], [], None)
    assert k["status"] == {"level": "nodata", "text": "Belum ada data. Mulai pemantauan untuk mengukur panel."}
    assert all(v["state"] == "nodata" for v in k["panels"].values()) and k["demo"]
    assert kondisi.assess(False, "esp32", [], [], None)["status"]["level"] == "offline"


def test_history_timeline_events_and_summary():
    ps = (_panels("2026-10-22T08:00:00.000Z", {}) + _panels("2026-10-22T08:30:00.000Z", {"A": 0.03}, isc={"A": 0.004})
          + _panels("2026-10-22T09:30:00.000Z", {}))
    h = kondisi.history(ps, [_array("2026-10-22T09:30:30.000Z", 0.9)], {"4S": 1.0}, "2026-10-22T10:00:00.000Z")
    assert h["rounds"] == 3 and [x["state"] for x in h["timeline"]["A"]] == ["normal", "object", "normal"]
    assert [e["text"] for e in h["events"]] == ["Panel A kembali normal",
                                                "Panel A: kemungkinan tertutup benda atau kotoran, daya 12 persen dari panel terbaik"]
    assert "Panel A kemungkinan tertutup benda atau kotoran selama sekitar 1 jam." in h["summary"]
    assert any("90 persen dari perkiraan normal" in s for s in h["summary"])


def test_monitor_actions_are_validated():
    assert commands.validate_action("monitor_start", {}) == {"array_interval_s": 300, "panel_interval_s": 1800, "wiring": None}
    assert commands.validate_action("monitor_start", {"panel_interval_s": 0})["panel_interval_s"] == 0
    with pytest.raises(commands.CommandError):
        commands.validate_action("monitor_start", {"panel_interval_s": 60})           # panel checks at most every 5 min
    assert commands.is_stop("action", "monitor_stop") and commands.validate_action("panel_check", {}) == {}


def test_monitoring_and_panel_check_on_the_demo_device(tmp_path):
    with live_server(tmp_path) as (settings, core):
        if not core.twin.available:
            pytest.skip("pvlib not installed: the demo device has no single-panel curves")
        base = settings.api_url + "/api/v1"
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            end = time.time() + 30
            while time.time() < end and not core.db.one("SELECT 1 FROM devices WHERE id='demo-01'"):
                time.sleep(0.1)
            cmd = lambda c, p=None: requests.post(f"{base}/devices/demo-01/commands",
                                                  json={"kind": "action", "command": c, "params": p or {}}, timeout=10).json()
            cmd("demo_condition", {"condition": "V3_paranet65"})
            cmd("monitor_start", {"array_interval_s": 30})
            end = time.time() + 120
            while time.time() < end and core.db.one("SELECT COUNT(*) n FROM sweeps")["n"] < 5:
                time.sleep(0.3)
            rows = core.db.query("SELECT topology, label FROM sweeps ORDER BY id")
            assert [r["topology"] for r in rows[:5]] == ["A", "B", "C", "D", "4S"]
            assert all(r["label"].startswith("pantau_") for r in rows[:5])
            assert core.db.one("SELECT COUNT(*) n FROM decisions WHERE applied=1")["n"] == 0   # recommendations only, never applied
            assert core.db.one("SELECT COUNT(*) n FROM events WHERE kind='switch'")["n"] == 0
            time.sleep(1)
            st = requests.get(f"{base}/twin/state", params={"device_id": "demo-01"}, timeout=30).json()
            assert st["monitor"]["on"] and st["kondisi"]["panels"]["A"]["state"] == "object"
            raw = core.db.one("SELECT raw_text FROM sweeps WHERE topology='A'")["raw_text"]
            assert "# tiruan model=kembaran" in raw                                   # demo panel curves say where they come from
            hist = requests.get(f"{base}/riwayat", params={"device_id": "demo-01"}, timeout=30).json()
            assert hist["rounds"] == 1 and hist["events"][0]["panel"] == "A"
            an = requests.get(f"{base}/analisis", params={"device_id": "demo-01"}, timeout=30).json()
            assert an["demo"] and an["curve"]["topology"] == "4S" and len(an["curve"]["points"]) > 100
            assert 1 in {a["code"] for a in an["curve"]["anomalies"]}                  # shade cloth on A: a step
            assert an["now"]["headline"].startswith("Kemungkinan ada benda") and an["day"]["lines"]
            assert set(an["panels"]) == set("ABCD")
            cmd("monitor_stop")
            end = time.time() + 20
            while time.time() < end and (core.device_row("demo-01")["state"].get("monitor") or {}).get("on"):
                time.sleep(0.3)
            assert not core.device_row("demo-01")["state"]["monitor"]["on"]
            c = cmd("panel_check")
            end = time.time() + 60
            while time.time() < end and core.db.one("SELECT status FROM commands WHERE id=?", (c["id"],))["status"] not in ("done", "failed"):
                time.sleep(0.3)
            done = core.db.one("SELECT status, result FROM commands WHERE id=?", (c["id"],))
            assert done["status"] == "done" and "4 of 4" in done["result"]
            assert core.db.one("SELECT COUNT(*) n FROM sweeps WHERE label LIKE 'periksa_%'")["n"] == 4
        finally:
            gw.stop()


def test_monitoring_starts_by_itself_and_takes_requests(tmp_path):
    """Monitoring is always on for the consumer view (run.py gateway); requests are served by the monitoring loop."""
    from shadeshift import config
    assert config.load(env={}).monitor_auto and not config.load(env={"SHADESHIFT_MONITOR_AUTO": "0"}).monitor_auto
    with live_server(tmp_path) as (settings, core):
        if not core.twin.available:
            pytest.skip("pvlib not installed: the demo device has no single-panel curves")
        base = settings.api_url + "/api/v1"
        gw = Gateway(settings, source="demo", lambat=0, monitor_auto=True)
        gw.start()
        try:
            end = time.time() + 90
            while time.time() < end and core.db.one("SELECT COUNT(*) n FROM sweeps")["n"] < 5:
                time.sleep(0.3)
            end = time.time() + 20                                                         # the next heartbeat reports it
            while time.time() < end and not (core.device_row("demo-01")["state"].get("monitor") or {}).get("on"):
                time.sleep(0.3)
            assert (core.device_row("demo-01")["state"].get("monitor") or {}).get("on")      # nobody pressed a button
            n = core.db.one("SELECT COUNT(*) n FROM sweeps")["n"]
            r = requests.post(f"{base}/devices/demo-01/commands", json={"kind": "action", "command": "measure_now"}, timeout=10).json()
            end = time.time() + 60
            while time.time() < end and core.db.one("SELECT status FROM commands WHERE id=?", (r["id"],))["status"] != "done":
                time.sleep(0.3)
            assert "monitoring" in core.db.one("SELECT result FROM commands WHERE id=?", (r["id"],))["result"]
            end = time.time() + 60
            while time.time() < end and core.db.one("SELECT COUNT(*) n FROM sweeps")["n"] <= n:
                time.sleep(0.3)
            assert core.db.one("SELECT COUNT(*) n FROM sweeps")["n"] > n                     # measured now, not refused
        finally:
            gw.stop()
