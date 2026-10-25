"""Live diagnosis and module map (Stage 4E, CONTRACT §15).

The fake board's panel curves are SYNTHETIC (lab 4P curve / 4, one panel scaled down to imitate shade): these tests check
the arithmetic and the data flow, not the diagnosis quality on real panels.
"""
import time

import requests

from conftest import live_server
from fake_devices import FakeV21, GatewayV21
from shadeshift import diagnosis
from shadeshift.training import dataset, pipeline


def _p(pmax, isc=1.0, voc=20.0):
    return {"pmax": pmax, "isc": isc, "voc": voc}


def test_panel_map_rules():
    shaded = diagnosis.panel_map({"A": _p(0.5, isc=0.5), "B": _p(1.0), "C": _p(0.98), "D": _p(1.0)})
    assert shaded["affected"] == "A" and shaded["pattern"] == "one"
    assert shaded["modules"]["A"]["status"] == "strongly_reduced" and shaded["modules"]["A"]["hint"] == "shaded_or_dimmed"
    assert shaded["modules"]["C"]["status"] == "normal"
    short = diagnosis.panel_map({"A": _p(1.0), "B": _p(1.0), "C": _p(0.7, voc=14.0), "D": _p(1.0)})
    assert short["modules"]["C"]["hint"] == "bypassed_cells"
    series = diagnosis.panel_map({"A": _p(1.0), "B": _p(0.8), "C": _p(1.0), "D": _p(1.0)})
    assert series["modules"]["B"]["hint"] == "series_resistance"
    cloud = diagnosis.panel_map({m: _p(0.4, isc=0.4) for m in "ABCD"})          # all dimmed alike: nothing flagged
    assert cloud["affected"] == "" and cloud["pattern"] == "none"
    weak = {"A": _p(0.8, isc=0.8), "B": _p(1.0), "C": _p(1.0), "D": _p(1.0)}    # panel A is always a bit weaker
    assert diagnosis.panel_map(weak)["affected"] == "A"
    ref = diagnosis.panel_map(weak, ref=weak)
    assert ref["affected"] == "" and "A1" in ref["reference"]                     # its own A1 baseline removes it
    assert diagnosis.panel_map({"A": _p(1.0), "B": _p(1.0), "C": _p(1.0)}) is None


def test_patterns_follow_the_wiring_symmetry():
    assert [dataset.pattern_of(m) for m in ("", "C", "AB", "CD", "AC", "BD", "AD", "BC", "ABD", "ABCD")] == [
        "none", "one", "string_pair", "string_pair", "row_pair", "row_pair", "diagonal", "diagonal", "three", "all"]
    lab = dataset.lab_examples()
    assert {dataset.PATTERNS[e.pattern] for e in lab} == {"none", "one", "string_pair", "diagonal"}
    r = pipeline.train("pattern", "logreg", {"real": [], "lab": lab}, ["lab"])
    assert r["model_id"].startswith("pola-logreg-v1@") and r["report"]["classes"] == list(dataset.PATTERNS)


def _wait(pred, timeout=90.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.1)
    return None


def test_live_diagnosis_of_scans_and_audits(tmp_path):
    with live_server(tmp_path) as (settings, core):
        base = f"{settings.api_url}/api/v1"
        from shadeshift.training import export
        core.selector_paths = export.selector_paths(tmp_path / "files")   # activation must not write into the project
        for task in ("diagnosis", "pattern"):                       # active models: trained on lab (no real data here)
            m = requests.post(f"{base}/models/train", json={"task": task, "sources": ["lab"]}, timeout=120).json()
            assert requests.post(f"{base}/models/{m['id']}/activate", timeout=30).status_code == 200
        gw = GatewayV21(settings, FakeV21("V3_opak", tmp_path, panel_scale={"A": 0.5}))
        gw.start()
        try:
            assert _wait(lambda: (core.device_row("esp32-01") or {}).get("gateway", {}).get("esp32"))
            sid = requests.post(f"{base}/sessions", json={"device_id": "esp32-01", "place": "outdoor_sun"}, timeout=10).json()["id"]
            sc = requests.post(f"{base}/sessions/{sid}/scans", json={"code": "B4", "rounds": 1, "pause_s": 0}, timeout=10).json()
            assert _wait(lambda: requests.get(f"{base}/scans/{sc['id']}", timeout=10).json()["status"] == "done")

            d = requests.get(f"{base}/scans/{sc['id']}/diagnosis", timeout=30).json()
            r = d["rounds"][0]
            assert r["diagnosis"]["class"] in dataset.CLASSES and 0 < r["diagnosis"]["confidence"] <= 1
            assert r["diagnosis"]["evidence"] == "lab" and "leave-one" in r["diagnosis"]["test_mode"]   # status shown
            assert r["pattern"]["class"] in dataset.PATTERNS
            assert r["map"]["affected"] == "A" and r["map"]["modules"]["A"]["hint"] == "shaded_or_dimmed"
            assert r["map"]["reference"] == "the best panel in this round"                          # no A1 scan yet
            assert r["agrees"] == (r["pattern"]["class"] == "one")
            dev = requests.get(f"{base}/devices/esp32-01/diagnosis", timeout=30).json()
            assert dev["kind"] == "scan" and dev["map"]["affected"] == "A"

            cid = requests.post(f"{base}/devices/esp32-01/commands", json={"kind": "action", "command": "audit_decision"},
                                timeout=10).json()["id"]
            assert _wait(lambda: core.db.one("SELECT 1 FROM commands WHERE id=? AND status='done'", (cid,)))
            dev = _wait(lambda: (lambda x: x if x and x["kind"] == "audit" else None)(
                requests.get(f"{base}/devices/esp32-01/diagnosis", timeout=30).json()))
            assert dev["diagnosis"]["class"] in dataset.CLASSES and dev["map"]["affected"] == "A"   # audit has 4P now
            assert core.db.one("SELECT pmax_4p FROM evaluations")["pmax_4p"] > 0

            t = {x["id"]: x for x in requests.get(f"{base}/evidence", timeout=30).json()["targets"]}
            assert t["diagnosis"]["status"] == "no measurement yet"                 # the active model was tested on lab
        finally:
            gw.stop()


def test_no_active_model_is_said_plainly(tmp_path):
    from conftest import server_client
    with server_client(tmp_path) as api:
        r = api.core.round_diagnosis({})
        assert "no active model" in r["diagnosis"]["error"] and r["map"] is None and r["agrees"] is None
