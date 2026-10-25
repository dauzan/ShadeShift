"""Data collection (Stage 4B, CONTRACT §12): sessions, labeled full scans, quality checks and export.

End-to-end tests run the real gateway against the emulator (replayed lab curves) and against a TEST-ONLY fake
firmware v2.1 whose single-panel curves are SYNTHETIC (lab 4P curve with the current divided by 4).
"""
import csv
import io
import time
import zipfile
from datetime import date

import pytest
import requests

from conftest import heartbeat, live_server, server_client
from fake_devices import FakeV21, GatewayV21
from shadeshift import fieldwork, protocol
from shadeshift.gateway.main import Gateway


# ---------------- catalog, names, quality (pure) ----------------
def test_catalog_follows_the_corrected_protocol():
    codes = set(fieldwork.CONDITIONS)
    assert {"A1", "E5", "F1"} <= codes and {f"B{i}" for i in range(1, 8)} <= codes and {f"C{i}" for i in range(1, 6)} <= codes
    assert fieldwork.CONDITIONS["E5"][1] == "bypass_short" and "KONTROL" in fieldwork.CONDITIONS["E1"][4]
    assert "5 Ω" in fieldwork.CONDITIONS["E3"][0] and "10 Ω" in fieldwork.CONDITIONS["E4"][0]
    assert set(fieldwork.DIAGNOSIS) == {"normal", "partial_shading", "uniform_dimming", "bypass_open", "bypass_short",
                                        "series_resistance"}


def test_condition_names():
    d = date(2026, 10, 20)
    assert fieldwork.condition_name("LR", d, "B2", "A") == "LR1020_B2"
    assert fieldwork.condition_name("DR", d, "B2", "C") == "DR1020_B2-C"          # B2 moved to module C
    assert fieldwork.condition_name("LR", d, "A1", "") == "LR1020_A1"
    assert fieldwork.file_name("LR1020_B2-C", "TCT", 3) == "LR1020_B2-C_TCT_u3.csv"
    assert protocol.condition_from_name("LR1020_B2-C_TCT_u3.csv") == ("LR1020_B2-C", "TCT", 3)
    with pytest.raises(fieldwork.LabelError):
        fieldwork.normalize_modules("AE")
    assert fieldwork.normalize_modules("da") == "AD"


def _sw(t, rep, pmax, light=None, light_end=None, complete=True):
    h = {} if light is None else {"light_v": light, "light_end_v": light_end}
    return {"topology": t, "repeat": rep, "pmax": pmax, "complete": complete, "header": h, "label": f"X_{t}_u{rep}"}


def _q(checks):
    return {c["check"]: c for c in checks}


def test_quality_checks():
    scan = {"rounds": 2, "repeat_start": 1, "with_panels": True, "dynamic": False}
    sweeps = [_sw(t, r, 1.0 + 0.001 * r, 1.20, 1.21) for r in (1, 2) for t in protocol.TOPOLOGIES]
    sweeps += [_sw(p, r, 0.26, 1.20, 1.20) for r in (1, 2) for p in protocol.PANELS]
    q = _q(fieldwork.scan_quality(scan, sweeps))
    assert all(q[k]["ok"] is True for k in ("complete", "light_steady", "repeat_spread", "panels_vs_4P")), q

    bad = [s for s in sweeps if not (s["topology"] == "B" and s["repeat"] == 2)]           # one missing
    bad[0] = _sw("4S", 1, 1.0, 1.20, 1.00)                                                   # light dropped mid-sweep
    bad[1] = _sw("2S2P", 1, 1.10)                                                            # 10 % above its repeat
    bad.append({**_sw("C", 9, 0.1), "complete": False, "label": "X_C_u9"})
    q = _q(fieldwork.scan_quality(scan, bad))
    assert q["complete"]["ok"] is False and "B_u2" in q["complete"]["items"] and "X_C_u9" in q["complete"]["items"]
    assert q["light_steady"]["ok"] is False and any("X_4S_u1" in x for x in q["light_steady"]["items"])
    assert q["repeat_spread"]["ok"] is False and q["repeat_spread"]["value"] > 1.8

    p4_high = [s if not (s["topology"] == "4P" and s["repeat"] == 1) else _sw("4P", 1, 1.5, 1.2, 1.2) for s in sweeps]
    assert _q(fieldwork.scan_quality(scan, p4_high))["panels_vs_4P"]["items"] == ["u1"]

    dyn = _q(fieldwork.scan_quality({**scan, "dynamic": True, "with_panels": False}, sweeps[:8]))
    assert dyn["repeat_spread"]["ok"] is None and "panels_vs_4P" not in dyn
    assert _q(fieldwork.scan_quality(scan, [_sw("4S", 1, 1.0)]))["light_steady"]["ok"] is None   # no LDR (firmware v2)


def test_a1_drift():
    assert fieldwork.a1_drift({"4S": 1.0, "TCT": 1.2}, {"4S": 1.02, "TCT": 1.21})["ok"] is True
    c = fieldwork.a1_drift({"4S": 1.0}, {"4S": 0.9})
    assert c["ok"] is False and c["items"] == ["4S"]
    assert fieldwork.a1_drift({}, {})["ok"] is None


# ---------------- API without a gateway ----------------
def test_session_and_scan_api(tmp_path):
    with server_client(tmp_path) as api:
        heartbeat(api, "demo-40", kind="emulator")
        r = api.post("/api/v1/sessions", json={"device_id": "demo-40", "place": "outdoor_sun", "sky": "cerah"})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        assert api.post("/api/v1/sessions", json={"device_id": "demo-40", "place": "outdoor_sun"}).status_code == 409
        assert api.post("/api/v1/sessions", json={"device_id": "upload", "place": "outdoor_sun"}).status_code in (400, 404)

        sc = api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "B2", "rounds": 2, "pause_s": 5}).json()
        assert sc["status"] == "queued" and sc["condition"].startswith("TIRUAN") and sc["condition"].endswith("_B2")
        assert sc["with_panels"] is False and "emulator" in sc["warnings"][0]            # never fakes panel data
        assert (sc["diagnosis"], sc["modules"], sc["repeat_start"], sc["n_expected"]) == ("partial_shading", "A", 1, 8)
        cmd = api.get("/api/v1/devices/demo-40/commands").json()[0]
        assert cmd["command"] == "full_scan" and cmd["params"]["condition"] == sc["condition"]
        assert cmd["params"]["repeat_start"] == 1 and cmd["params"]["panels"] is False
        assert api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "B2"}).status_code == 409    # one at a time
        assert api.post("/api/v1/sessions/{sid}/end".format(sid=sid)).status_code == 409             # scan still queued

        # the gateway reports "stopped": the scan follows; the next B2 scan continues the repeat numbers
        api.post(f"/api/v1/commands/{cmd['id']}/result", json={"status": "failed", "result": "stopped after 3 sweeps"})
        assert api.get(f"/api/v1/scans/{sc['id']}").json()["status"] == "stopped"
        sc2 = api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "B2", "modules": "C", "rounds": 1}).json()
        assert sc2["condition"].endswith("_B2-C") and sc2["repeat_start"] == 1                    # another condition
        api.post(f"/api/v1/commands/{sc2['command_id']}/result", json={"status": "done", "result": "4 sweeps"})
        sc3 = api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "B2", "rounds": 1}).json()
        assert sc3["repeat_start"] == 3
        api.post(f"/api/v1/commands/{sc3['command_id']}/result", json={"status": "done", "result": "4 sweeps"})

        assert api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "Z9"}).status_code == 400
        assert api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "B2", "modules": "AE"}).status_code == 400
        assert api.post("/api/v1/devices/demo-40/commands", json={
            "kind": "action", "command": "full_scan", "params": {"scan_uuid": "12345678", "condition": "X"}}).status_code == 400

        up = api.put(f"/api/v1/scans/{sc['id']}", json={"temps": {"1": {"A": 41.5, "C": 40.0}}, "note": "angin"}).json()
        up = api.put(f"/api/v1/scans/{sc['id']}", json={"temps": {"1": {"B": 39.0}, "2": {"A": 43}}}).json()
        assert up["temps"] == {"1": {"A": 41.5, "C": 40.0, "B": 39.0}, "2": {"A": 43}} and up["note"] == "angin"
        assert api.put(f"/api/v1/scans/{sc['id']}", json={"temps": {"1": {"A": 300}}}).status_code == 422

        assert api.post(f"/api/v1/sessions/{sid}/end").status_code == 200
        assert api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "A1"}).status_code == 409
        cat = api.get("/api/v1/fieldwork/catalog").json()
        assert len(cat["conditions"]) == len(fieldwork.CONDITIONS) and cat["limits"]["repeat_spread_pct"] == 1.8


def test_queued_scan_expires_without_a_gateway(tmp_path):
    with server_client(tmp_path) as api:
        heartbeat(api, "demo-41", kind="emulator")
        sid = api.post("/api/v1/sessions", json={"device_id": "demo-41", "place": "indoor_lamp"}).json()["id"]
        sc = api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "A1"}).json()
        api.core.db.con.execute("UPDATE commands SET created_at='2020-01-01T00:00:00.000Z' WHERE id=?", (sc["command_id"],))
        api.core.maintain()
        got = api.get(f"/api/v1/scans/{sc['id']}").json()
        assert got["status"] == "failed" and "gateway" in got["result"]


# ---------------- end to end with the gateway ----------------
def _wait(pred, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.1)
    return None


def _scan_done(base, scan_id):
    def ready():
        s = requests.get(f"{base}/scans/{scan_id}", timeout=10).json()
        return s if s["status"] in ("done", "failed", "stopped") else None
    return _wait(ready)


def test_full_scan_on_the_emulator_and_export(tmp_path):
    with live_server(tmp_path) as (settings, core):
        base = f"{settings.api_url}/api/v1"
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            assert _wait(lambda: core.db.one("SELECT 1 FROM devices WHERE id='demo-01'"))
            sid = requests.post(f"{base}/sessions", json={"device_id": "demo-01", "place": "indoor_lamp",
                                                         "operator": "uji"}, timeout=10).json()["id"]
            for code in ("A1", "C1", "A1"):
                sc = requests.post(f"{base}/sessions/{sid}/scans", json={"code": code, "rounds": 2, "pause_s": 0.3},
                                   timeout=10).json()
                done = _scan_done(base, sc["id"])
                assert done["status"] == "done", done
                assert done["n_sweeps"] == 8 and done["result"] == "8 sweeps"
            q = {c["check"]: c for c in done["quality"]}
            assert q["complete"]["ok"] is True and q["light_steady"]["ok"] is None     # the emulator has no LDR
            assert {(w["topology"], w["repeat"]) for w in done["sweeps"]} == {(t, r) for t in protocol.TOPOLOGIES for r in (3, 4)}
            assert all(w["label"] == f"{done['condition']}_{w['topology']}_u{w['repeat']}" for w in done["sweeps"])
            assert _wait(lambda: any(e["message"].startswith(f"full scan {done['condition']}: round u3 done")
                                     for e in core.db.query("SELECT message FROM events")))   # events are sent in batches
            session = requests.get(f"{base}/sessions/{sid}", timeout=10).json()
            assert session["a1_drift"]["ok"] is not None                                # two A1 scans: drift computed
            assert not core.db.query("SELECT 1 FROM decisions")                          # data collection, no decisions
            z = zipfile.ZipFile(io.BytesIO(requests.get(f"{base}/sessions/{sid}/export.zip", timeout=30).content))
        finally:
            gw.stop()
    names = z.namelist()
    assert len([n for n in names if n.startswith("data/")]) == 24 and "labels.csv" in names
    assert z.read("BACA_SAYA.txt").decode().startswith("DATA TIRUAN")
    rows = list(csv.DictReader(io.StringIO(z.read("labels.csv").decode())))
    assert len(rows) == 24 and {r["code"] for r in rows} == {"A1", "C1"} and rows[0]["source"] == "demo"
    c1 = [r for r in rows if r["code"] == "C1"][0]
    assert c1["diagnosis"] == "uniform_dimming" and c1["modules"] == "A"
    first = sorted(n for n in names if n.startswith("data/"))[0]
    text = z.read(first).decode()
    assert text.startswith("# MULAI ") and "# tiruan berkas=" in text and "# SELESAI" in text   # raw, as received
    p = protocol.parse_block(text.splitlines())
    assert p.complete and len(p.v) == 202


def test_full_scan_with_single_panels_and_stop(tmp_path):
    with live_server(tmp_path) as (settings, core):
        base = f"{settings.api_url}/api/v1"
        gw = GatewayV21(settings, FakeV21("V1c", tmp_path))
        gw.start()
        try:
            assert _wait(lambda: (core.device_row("esp32-01") or {}).get("gateway", {}).get("esp32"))
            sid = requests.post(f"{base}/sessions", json={"device_id": "esp32-01", "place": "outdoor_sun"},
                                timeout=10).json()["id"]
            sc = requests.post(f"{base}/sessions/{sid}/scans", json={"code": "A1", "rounds": 1, "pause_s": 0},
                               timeout=10).json()
            assert sc["with_panels"] is True and sc["warnings"] == [] and sc["condition"].startswith("LR")
            done = _scan_done(base, sc["id"])
            assert done["status"] == "done" and done["n_sweeps"] == 8, done
            assert {w["topology"] for w in done["sweeps"]} == set(protocol.SWEEP_TARGETS)
            q = {c["check"]: c for c in done["quality"]}
            assert q["complete"]["ok"] and q["light_steady"]["ok"] and q["panels_vs_4P"]["ok"] is True, q
            assert all(w["header"]["light_v"] == 1.2 for w in done["sweeps"])

            gw.fake.lambat = 1.0                                     # real-time switching/sweeps, so Stop lands mid-scan
            sc = requests.post(f"{base}/sessions/{sid}/scans", json={"code": "B2", "rounds": 3, "pause_s": 0},
                               timeout=10).json()
            assert _wait(lambda: requests.get(f"{base}/scans/{sc['id']}", timeout=10).json()["n_sweeps"] >= 1)
            stop_id = requests.post(f"{base}/stop_all", timeout=10).json()["queued"][0]["id"]
            stopped = _scan_done(base, sc["id"])
            assert stopped["status"] == "stopped" and stopped["n_sweeps"] < 24, stopped
            stop = _wait(lambda: core.db.one("SELECT status, result FROM commands WHERE id=? AND status != 'sent' "
                                             "AND status != 'queued'", (stop_id,)))
            assert stop == {"status": "done", "result": "all relays open"}   # the device confirmed
            assert not gw.kon.topo
        finally:
            gw.stop()
