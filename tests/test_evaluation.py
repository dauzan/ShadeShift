"""Proving the targets (Stage 4C, CONTRACT §13): MLPE reference, recovery points, live decision audit, evidence page.

The end-to-end tests use the TEST-ONLY FakeV21 device, whose single-panel curves are SYNTHETIC; they check the
arithmetic and the data flow, not ShadeShift's real performance.
"""
import csv
import io
import time

import pytest
import requests

from conftest import heartbeat, live_server, server_client
from fake_devices import FakeV21, GatewayV21
from shadeshift import evaluation, protocol
from shadeshift.gateway.main import Gateway


def _round(p, choice, panels=(0.30, 0.30, 0.30, 0.30)):
    by_t = {t: {"pmax": v, "complete": True} for t, v in p.items()}
    if panels:
        by_t.update({k: {"pmax": v, "complete": True} for k, v in zip(protocol.PANELS, panels)})
    return evaluation.round_metrics(by_t, choice, "server_numpy")


def test_round_metrics_follow_the_research_definitions():
    r = _round({"4S": 0.84, "2S2P": 0.96, "TCT": 1.02, "4P": 1.10}, "2S2P")
    assert r["usable"] and r["mlpe_w"] == pytest.approx(1.20) and r["best"] == "TCT"
    assert r["pct_mlpe"]["TCT"] == pytest.approx(85.0) and r["pct_mlpe"]["4P"] == pytest.approx(1.10 / 1.2 * 100)
    assert r["ai_loss_pts"] == pytest.approx(5.0)                      # (1.02 - 0.96) / 1.20
    assert r["ai_loss_pct"] == pytest.approx(0.06 / 1.02 * 100)        # without MLPE: % of the measured best
    assert _round({"4S": 1.0, "2S2P": 1.0}, "4S")["reason"].startswith("missing complete sweep: TCT")
    assert _round({"4S": 1.0, "2S2P": 1.0, "TCT": 1.0}, None)["usable"] is False
    assert _round({"4S": 1.0, "2S2P": 1.0, "TCT": 1.0}, "4S", panels=None)["mlpe_w"] is None


def test_summary_recovery_vs_best_fixed():
    rounds = [_round({"4S": 1.08, "2S2P": 0.90, "TCT": 0.96}, "4S"),      # unshaded-like: 4S best
              _round({"4S": 0.60, "2S2P": 0.84, "TCT": 0.90}, "TCT"),     # shaded: TCT best
              _round({"4S": 0.60, "2S2P": 0.90, "TCT": 0.84}, "TCT")]     # AI wrong here: 2S2P was best
    s = evaluation.summarize(rounds)["mlpe"]
    pct = {t: sum(r["pmax"][t] for r in rounds) / 3 / 1.2 * 100 for t in evaluation.CANDIDATES}
    fixed = max(pct, key=pct.get)
    ai = (1.08 + 0.90 + 0.84) / 3 / 1.2 * 100
    assert s["best_fixed"] == fixed and s["ai_pct"] == pytest.approx(ai, abs=0.01)
    assert s["recovery_pts"] == pytest.approx(ai - pct[fixed], abs=0.01) and s["n"] == 3
    assert s["met"] == (s["recovery_pts"] >= 4)
    rel = evaluation.summarize(rounds)["relative"]
    assert rel["ai_matches_best_pct"] == pytest.approx(66.7) and rel["best_fixed"] in evaluation.CANDIDATES
    assert evaluation.summarize([]) == {"n_rounds": 0, "mlpe": None, "relative": None}


def _wait(pred, timeout=90.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.1)
    return None


def test_scan_rounds_audit_and_evidence_end_to_end(tmp_path):
    with live_server(tmp_path) as (settings, core):
        base = f"{settings.api_url}/api/v1"
        gw = GatewayV21(settings, FakeV21("V6_paranet65", tmp_path))
        gw.start()
        try:
            assert _wait(lambda: (core.device_row("esp32-01") or {}).get("gateway", {}).get("esp32"))
            sid = requests.post(f"{base}/sessions", json={"device_id": "esp32-01", "place": "outdoor_sun"}, timeout=10).json()["id"]
            sc = requests.post(f"{base}/sessions/{sid}/scans", json={"code": "C4", "rounds": 2, "pause_s": 0}, timeout=10).json()
            assert _wait(lambda: requests.get(f"{base}/scans/{sc['id']}", timeout=10).json()["status"] == "done")

            ev = requests.get(f"{base}/evidence/rounds", params={"session_id": sid}, timeout=30).json()
            rounds = ev["rounds"]
            assert len(rounds) == 2 and all(r["usable"] and r["kind"] == "scan" and r["mlpe_w"] for r in rounds), rounds
            r = rounds[0]
            assert r["mlpe_w"] == pytest.approx(sum(r["pmax"][p] for p in protocol.PANELS))
            assert r["pct_mlpe"]["TCT"] == pytest.approx(r["pmax"]["TCT"] / r["mlpe_w"] * 100)
            assert r["decided_by"] in ("server_onnx", "server_numpy") and r["choice"] in evaluation.CANDIDATES
            assert ev["summary"]["mlpe"]["n"] == 2

            cid = requests.post(f"{base}/devices/esp32-01/commands", json={"kind": "action", "command": "audit_decision"},
                                timeout=10).json()["id"]
            res = _wait(lambda: core.db.one("SELECT status, result FROM commands WHERE id=? AND status IN ('done','failed')", (cid,)))
            assert res["status"] == "done" and "points of MLPE" in res["result"], res
            e = _wait(lambda: core.db.one("SELECT * FROM evaluations"))
            assert e["mlpe_w"] > 0 and len(eval(e["pmax_panels_json"])) == 4 and e["source"] == "device"
            dec = core.db.one("SELECT trigger, applied, choice FROM decisions WHERE id=?", (e["decision_id"],))
            assert dec["trigger"] == "manual" and dec["applied"] == 1 and dec["choice"] == e["chosen"]
            assert gw.kon.topo == e["chosen"]                                  # the array is left on the AI's choice

            # a multimeter entry: ESP32 + relays
            requests.post(f"{base}/ingest/metrics", json={"items": [
                {"device_id": "esp32-01", "name": "device_power_w", "value": 0.45, "unit": "W", "provenance": "manual",
                 "data": {"entry": "e1", "topology": "TCT"}},
                {"device_id": "esp32-01", "name": "relay_power_w", "value": 1.60, "unit": "W", "provenance": "manual",
                 "data": {"entry": "e1", "topology": "TCT"}}]}, timeout=10)
            evid = _wait(lambda: (lambda x: x if x["rounds_total"] == 3 and x["targets"][3]["evidence"] else None)(
                requests.get(f"{base}/evidence", timeout=30).json()))         # metrics arrive in the next batch
            t = {x["id"]: x for x in evid["targets"]}
            assert t["recovery"]["status"] in ("met", "not met")
            assert t["recovery"]["evidence"][0]["source"] == "measured" and t["recovery"]["evidence"][0]["n"] == 3
            assert t["power"]["status"] == "not met" and t["power"]["evidence"][0]["value"] == pytest.approx(2.05)
            assert t["diagnosis"]["status"] == "no measurement yet"
            assert t["latency"]["status"] == "no measurement yet"                 # no firmware v3 on this fake board
            assert any(x["source"] == "measured (laptop)" for x in t["latency"]["evidence"])
            rows = list(csv.DictReader(io.StringIO(requests.get(f"{base}/evidence.csv", timeout=30).text)))
            assert {r["source"] for r in rows} >= {"measured", "lab", "sim", "calc"}
        finally:
            gw.stop()


def test_audit_on_the_emulator_has_no_mlpe(tmp_path):
    with live_server(tmp_path) as (settings, core):
        base = f"{settings.api_url}/api/v1"
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            assert _wait(lambda: core.db.one("SELECT 1 FROM devices WHERE id='demo-01'"))
            cid = requests.post(f"{base}/devices/demo-01/commands", json={"kind": "action", "command": "audit_decision"},
                                timeout=10).json()["id"]
            res = _wait(lambda: core.db.one("SELECT status, result FROM commands WHERE id=? AND status IN ('done','failed')", (cid,)))
            assert res["status"] == "done" and "MLPE" not in res["result"], res
            e = _wait(lambda: core.db.one("SELECT * FROM evaluations"))
            assert e["source"] == "demo" and e["mlpe_w"] is None and e["pmax_tct"] > 0
            assert requests.get(f"{base}/evidence", timeout=30).json()["rounds_total"] == 0     # demo is never evidence
            demo = requests.get(f"{base}/evidence/rounds", params={"source": "demo"}, timeout=30).json()
            assert demo["summary"]["relative"]["n"] == 1 and demo["summary"]["mlpe"] is None
        finally:
            gw.stop()


def test_evidence_without_data(tmp_path):
    with server_client(tmp_path) as api:
        heartbeat(api, "esp32-50")
        t = {x["id"]: x for x in api.get("/api/v1/evidence").json()["targets"]}
        assert all(x["status"] == "no measurement yet" for x in t.values())
        assert all(x["needs"] for x in t.values())
        assert [e["source"] for e in t["recovery"]["evidence"]] == ["lab", "sim"]
