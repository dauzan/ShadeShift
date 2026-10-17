"""Server API (CONTRACT §5): ingestion, idempotency, runs, commands, reads, WebSocket, token, limits."""
import uuid
from pathlib import Path

import pytest

from conftest import heartbeat, server_client
from shadeshift import inti, protocol

LAB = Path(inti.DATA_LAB)


def lab_sweep(name):
    return protocol.parse_block((LAB / name).read_text(encoding="utf-8").splitlines())


def sweep_body(device_id, run_uuid, name="V3_opak_4S_u1.csv", source="device", **extra):
    p = lab_sweep(name)
    body = {"uuid": str(uuid.uuid4()), "device_id": device_id, "run_uuid": run_uuid, "source": source,
            "label": p.label, "topology": p.topology, "captured_at": "2026-10-18T03:15:30.123Z",
            "points": {"v": p.v, "i": p.i}, "header": p.header, "timing": {"sweep_ms": 1520.0},
            "replay_of": name if source == "demo" else None, "complete": p.complete}
    body.update(extra)
    return body


def test_health_and_model(api):
    h = api.get("/api/v1/health").json()
    assert h["status"] == "ok" and h["db"] == "ok" and h["schema_version"] == 1
    m = api.get("/api/v1/model").json()
    assert m["model_id"].startswith("pemilih-logreg-v1@") and m["classes"] == ["4S", "2S2P", "TCT"]
    assert len(m["feature_names"]) == 14 and "lab" in m["claims"] and "sim" in m["claims"]
    assert "<table>" in api.get("/docs").text and "cdn" not in api.get("/docs").text.lower()


def test_ingest_round_trip_and_idempotency(api):
    run = heartbeat(api)
    body = sweep_body("esp32-01", run)
    r = api.post("/api/v1/ingest/sweeps", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    ref = inti.baca_berkas(str(LAB / "V3_opak_4S_u1.csv"))
    assert out["derived"]["pmax"] == pytest.approx(ref.pmax, abs=1e-6)
    full = api.get(f"/api/v1/sweeps/{out['id']}").json()
    assert full["points"] == body["points"] and full["source"] == "device" and full["complete"] is True
    assert full["sweep_ms"] == 1520.0 and full["header"]["n"] == 201
    again = api.post("/api/v1/ingest/sweeps", json=body)
    assert again.status_code == 200 and again.json()["duplicate"] is True and again.json()["id"] == out["id"]


def test_unknown_device_and_run(api):
    run = heartbeat(api, "esp32-02")
    assert api.post("/api/v1/ingest/sweeps", json=sweep_body("nobody", run)).status_code == 404
    assert api.post("/api/v1/ingest/sweeps", json=sweep_body("esp32-02", str(uuid.uuid4()))).status_code == 409
    bad_source = sweep_body("esp32-02", run, source="lab")
    assert api.post("/api/v1/ingest/sweeps", json=bad_source).status_code == 422


def test_limits_and_label_sanitizing(api):
    run = heartbeat(api, "esp32-03")
    too_long = sweep_body("esp32-03", run)
    too_long["points"] = {"v": [1.0] * 5001, "i": [0.0] * 5001}
    assert api.post("/api/v1/ingest/sweeps", json=too_long).status_code == 422
    uneven = sweep_body("esp32-03", run)
    uneven["points"]["i"] = uneven["points"]["i"][:-1]
    assert api.post("/api/v1/ingest/sweeps", json=uneven).status_code == 422
    weird = sweep_body("esp32-03", run, label="a b/c:d")
    sid = api.post("/api/v1/ingest/sweeps", json=weird).json()["id"]
    assert api.get(f"/api/v1/sweeps/{sid}").json()["label"] == "a_b_c_d"


def test_incomplete_sweep_flagged_with_error_event(api):
    run = heartbeat(api, "esp32-04")
    body = sweep_body("esp32-04", run, name="V3_paranet75_TCT_u2.csv")
    sid = api.post("/api/v1/ingest/sweeps", json=body).json()["id"]
    assert api.get(f"/api/v1/sweeps/{sid}").json()["complete"] is False
    kinds = [e["kind"] for e in api.get("/api/v1/events", params={"device_id": "esp32-04"}).json()]
    assert "error" in kinds


def test_decisions_and_device_decision(api):
    run = heartbeat(api, "esp32-05")
    body = sweep_body("esp32-05", run, device_decision={"choice": "TCT", "scores": [0.1, -1.0, 0.9], "latency_us": 900})
    api.post("/api/v1/ingest/sweeps", json=body)
    dec = {"uuid": str(uuid.uuid4()), "sweep_uuid": body["uuid"], "device_id": "esp32-05", "decided_by": "gateway_numpy",
           "model_id": "pemilih-logreg-v1@test", "choice": "TCT", "scores": [0.1, -1.0, 0.9], "features": [0.5] * 14,
           "latency_us": 400.0, "trigger": "auto_once", "applied": True, "created_at": "2026-10-18T03:15:31.000Z"}
    assert api.post("/api/v1/ingest/decisions", json=dec).status_code == 201
    assert api.post("/api/v1/ingest/decisions", json=dec).json()["duplicate"] is True
    bad = dict(dec, uuid=str(uuid.uuid4()), sweep_uuid=str(uuid.uuid4()))
    assert api.post("/api/v1/ingest/decisions", json=bad).status_code == 404
    by = sorted(d["decided_by"] for d in api.get("/api/v1/decisions", params={"device_id": "esp32-05"}).json())
    assert by == ["esp32", "gateway_numpy"]


def test_events_metrics_log_evaluations(api):
    run = heartbeat(api, "esp32-06")
    body = sweep_body("esp32-06", run)
    api.post("/api/v1/ingest/sweeps", json=body)
    assert api.post("/api/v1/ingest/events", json={"items": [{"device_id": "esp32-06", "kind": "switch",
                                                              "message": "4S -> TCT (selector)"}]}).status_code == 201
    metrics = {"items": [{"device_id": "esp32-06", "name": "switch_ms", "value": v, "unit": "ms", "provenance": "measured"}
                         for v in (600, 640, 700)]}
    assert api.post("/api/v1/ingest/metrics", json=metrics).status_code == 201
    summary = api.get("/api/v1/metrics/summary", params={"device_id": "esp32-06"}).json()["switch_ms"]
    assert summary["n"] == 3 and summary["mean"] == pytest.approx(646.667, abs=1e-3) and summary["provenance"] == ["measured"]
    assert api.post("/api/v1/ingest/metrics", json={"items": [{"name": "x", "value": 1, "unit": "W",
                                                               "provenance": "guessed"}]}).status_code == 422
    log = {"device_id": "esp32-06", "lines": [{"dir": "tx", "line": "4S"}, {"dir": "rx", "line": "# siap: 4S"}]}
    assert api.post("/api/v1/ingest/log", json=log).status_code == 201
    assert [x["line"] for x in api.get("/api/v1/devices/esp32-06/log").json()] == ["4S", "# siap: 4S"]
    ev = {"items": [{"device_id": "esp32-06", "pmax": {"4S": 0.49, "2S2P": 0.56, "TCT": 0.57},
                     "sweep_uuids": [body["uuid"]], "best": "TCT", "chosen": "TCT", "loss_pct": 0.0, "source": "device"}]}
    assert api.post("/api/v1/ingest/evaluations", json=ev).status_code == 201
    e = api.get("/api/v1/evaluations", params={"device_id": "esp32-06"}).json()[0]
    assert e["pmax"]["TCT"] == 0.57 and e["loss_pct"] == 0.0 and len(e["sweep_ids"]) == 1
    csv_text = api.get("/api/v1/events.csv", params={"device_id": "esp32-06"}).text
    assert csv_text.splitlines()[0] == "created_at,device_id,kind,message,data" and "4S -> TCT" in csv_text


def test_command_lifecycle(api):
    heartbeat(api, "esp32-07")
    assert api.post("/api/v1/devices/esp32-07/commands", json={"kind": "raw", "command": "RELAI 6 1"}).status_code == 400
    assert api.post("/api/v1/devices/nobody/commands", json={"kind": "raw", "command": "4S"}).status_code == 404
    c = api.post("/api/v1/devices/esp32-07/commands", json={"kind": "action", "command": "auto_select"}).json()
    assert c["status"] == "queued"
    nxt = api.get("/api/v1/devices/esp32-07/commands/next", params={"wait": 0}).json()["commands"]
    assert [x["id"] for x in nxt] == [c["id"]]
    assert api.get("/api/v1/devices/esp32-07/commands/next", params={"wait": 0}).json()["commands"] == []
    assert api.post(f"/api/v1/commands/{c['id']}/result", json={"status": "done", "result": "TCT"}).status_code == 200
    listed = api.get("/api/v1/devices/esp32-07/commands").json()[0]
    assert listed["status"] == "done" and listed["result"] == "TCT"


def test_commands_expire_and_fail(api):
    heartbeat(api, "esp32-08")
    q = api.post("/api/v1/devices/esp32-08/commands", json={"kind": "raw", "command": "STATUS"}).json()["id"]
    s = api.post("/api/v1/devices/esp32-08/commands", json={"kind": "raw", "command": "VOC"}).json()["id"]
    db = api.core.db
    db.con.execute("UPDATE commands SET status='sent', sent_at='2020-01-01T00:00:00.000Z' WHERE id=?", (s,))
    db.con.execute("UPDATE commands SET created_at='2020-01-01T00:00:00.000Z' WHERE id=?", (q,))
    api.core.maintain()
    status = {c["id"]: (c["status"], c["result"]) for c in api.get("/api/v1/devices/esp32-08/commands").json()}
    assert status[q] == ("expired", None) and status[s] == ("failed", "no result from gateway")


def test_runs_start_and_end(api):
    run = heartbeat(api, "demo-09", kind="emulator")
    r = [x for x in api.get("/api/v1/runs", params={"device_id": "demo-09"}).json()][0]
    assert r["uuid"] == run and r["source"] == "demo" and r["ended_at"] is None
    api.post("/api/v1/devices/heartbeat", json={"device_id": "demo-09", "kind": "emulator", "run_uuid": run,
                                                "state": {"connected": False, "ending": True}})
    assert api.get(f"/api/v1/runs/{r['id']}").json()["ended_at"] is not None
    devices = {d["id"]: d for d in api.get("/api/v1/devices").json()}
    assert devices["esp32-01"]["online"] is True
    assert api.post("/api/v1/devices/heartbeat", json={"device_id": "lab", "kind": "esp32",
                                                       "run_uuid": str(uuid.uuid4())}).status_code == 400


def test_snapshot(api):
    run = heartbeat(api, "esp32-10")
    for name in ("V1c_4S_u1.csv", "V1c_TCT_u1.csv"):
        api.post("/api/v1/ingest/sweeps", json=sweep_body("esp32-10", run, name=name))
    snap = api.get("/api/v1/devices/esp32-10/snapshot").json()
    assert set(snap["latest_by_topology"]) == {"4S", "TCT"}
    assert len(snap["latest_by_topology"]["4S"]["points"]["v"]) == 202
    assert len(snap["recent_sweeps"]) == 2 and snap["device"]["online"] is True
    assert snap["settings"]["alert_threshold_pct"] == 15


def test_settings_and_twin(api):
    s = api.put("/api/v1/settings", json={"alert_threshold_pct": 20, "twin_shading": "paranet_AD"}).json()
    assert s["alert_threshold_pct"] == 20 and s["twin_shading"] == "paranet_AD"
    assert api.put("/api/v1/settings", json={"twin_shading": "fog"}).status_code == 422
    api.put("/api/v1/settings", json={"alert_threshold_pct": 15, "twin_shading": "none"})
    if not api.core.twin.available:
        pytest.skip("pvlib not installed: twin unavailable")
    exp = api.get("/api/v1/twin/expected").json()
    assert set(exp["pmax"]) == {"4S", "2S2P", "TCT", "4P"} and "simulation" in exp["label"]
    curve = api.get("/api/v1/twin/curve", params={"topology": "TCT", "voc_max": 36.6}).json()
    assert len(curve["v"]) == 250
    run = heartbeat(api, "esp32-11")
    sid = api.post("/api/v1/ingest/sweeps", json=sweep_body("esp32-11", run, name="V1c_4S_u1.csv")).json()["id"]
    scale = api.post("/api/v1/twin/calibrate", json={"sweep_id": sid}).json()["scale"]
    assert 0.8 < scale < 1.2                        # the twin was fitted on V1c
    assert api.get("/api/v1/settings").json()["twin_scale"] == scale
    api.put("/api/v1/settings", json={"twin_scale": 1.0})


def test_alert_when_measured_power_is_far_below_expected(api):
    if not api.core.twin.available:
        pytest.skip("pvlib not installed: twin unavailable")
    run = heartbeat(api, "demo-12", kind="emulator")
    out = api.post("/api/v1/ingest/sweeps", json=sweep_body("demo-12", run, name="V4_paranet65_4S_u1.csv",
                                                            source="demo")).json()
    assert out["alerts"] and "not a validated diagnosis" in out["alerts"][0]["message"]


def test_websocket_stream(api):
    run = heartbeat(api, "esp32-13")
    with api.websocket_connect("/api/v1/stream?device_id=esp32-13") as ws:
        assert ws.receive_json()["type"] == "hello"
        api.post("/api/v1/ingest/sweeps", json=sweep_body("esp32-13", run))
        types = []
        while "sweep" not in types:
            types.append(ws.receive_json()["type"])
        assert "sweep" in types


def test_token_required_for_writes_only(tmp_path):
    with server_client(tmp_path, SHADESHIFT_API_TOKEN="s3cret") as c:
        hb = {"device_id": "esp32-01", "kind": "esp32", "run_uuid": str(uuid.uuid4())}
        assert c.post("/api/v1/devices/heartbeat", json=hb).status_code == 401
        assert c.post("/api/v1/devices/heartbeat", json=hb, headers={"X-ShadeShift-Token": "s3cret"}).status_code == 200
        assert c.get("/api/v1/devices").status_code == 200


def test_stop_is_delivered_first_and_supersedes_relay_commands(api):
    heartbeat(api, "esp32-20")
    a = api.post("/api/v1/devices/esp32-20/commands", json={"kind": "raw", "command": "TCT"}).json()["id"]
    b = api.post("/api/v1/devices/esp32-20/commands", json={"kind": "raw", "command": "STATUS"}).json()["id"]
    s = api.post("/api/v1/devices/esp32-20/commands", json={"kind": "action", "command": "stop"}).json()["id"]
    got = [c["id"] for c in api.get("/api/v1/devices/esp32-20/commands/next", params={"wait": 0}).json()["commands"]]
    assert got == [s, b]                                   # stop first; the relay move is never handed out
    status = {c["id"]: (c["status"], c["result"]) for c in api.get("/api/v1/devices/esp32-20/commands").json()}
    assert status[a] == ("failed", "superseded by stop")


def test_queued_stop_never_expires_but_relay_commands_do(api):
    heartbeat(api, "esp32-21")
    s = api.post("/api/v1/devices/esp32-21/commands", json={"kind": "action", "command": "stop"}).json()["id"]
    t = api.post("/api/v1/devices/esp32-21/commands", json={"kind": "raw", "command": "4S"}).json()["id"]
    api.core.db.con.execute("UPDATE commands SET created_at='2020-01-01T00:00:00.000Z' WHERE id IN (?,?)", (s, t))
    api.core.maintain()
    status = {c["id"]: c["status"] for c in api.get("/api/v1/devices/esp32-21/commands").json()}
    assert status[s] == "queued" and status[t] == "expired"


def test_stop_all_targets_every_live_device(api):
    heartbeat(api, "esp32-22")
    heartbeat(api, "demo-22", kind="emulator")
    targets = {q["device_id"] for q in api.post("/api/v1/stop_all").json()["queued"]}
    assert {"esp32-22", "demo-22"} <= targets and "lab" not in targets and "upload" not in targets
