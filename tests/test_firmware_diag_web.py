"""Firmware 3.2 (Stage 4F): diagnosis on the ESP32 (DIAG) and the ESP32 web page, checked on this laptop.

The unchanged sketch is compiled against tests/firmware_host (WiFi and WebServer stand-ins: page requests come from the
script, and are served only when the firmware calls handleClient(), as on the board). The topology curves replay REAL
lab data. The diagnosis models here are trained on lab data only: the test checks that the ESP32 computes exactly what
the laptop computes, not that the diagnosis is right.
"""
import json
import re

import pytest

from firmware_sim import FIRMWARE, compile_sketch, device_lines, final, http_responses, lab_files, run
from shadeshift import protocol
from shadeshift.gateway.main import RE_DIAG, RE_INFO, firmware_label
from shadeshift.training import dataset, export, pipeline

SKETCH = FIRMWARE / "shadeshift_firmware"


@pytest.fixture(scope="module")
def lab():
    return dataset.lab_examples()


@pytest.fixture(scope="module")
def sims(tmp_path_factory, lab):
    """Firmware 3.2 without a diagnosis model, and with a lab-trained logistic regression and a lab-trained tree."""
    out = tmp_path_factory.mktemp("fw32")
    sims = {"none": compile_sketch(SKETCH, "shadeshift_firmware.ino", out / "none.exe", bench=True, web=True)}
    models = {}
    for kind in ("logreg", "tree"):
        r = pipeline.train("diagnosis", kind, {"real": [], "lab": lab}, ["lab"])
        inc = out / kind
        inc.mkdir()
        (inc / "diagnosis_model.h").write_text(export.diagnosis_header(r["model"].to_dict(), r["model_id"]), encoding="utf-8")
        sims[kind] = compile_sketch(SKETCH, "shadeshift_firmware.ino", out / f"{kind}.exe", bench=True, web=True, include=inc)
        models[kind] = r
    return sims, models


def test_sketch_folder_ships_without_a_diagnosis_model():
    assert not (SKETCH / "diagnosis_model.h").exists()        # written only when the team activates a model


def test_info_lists_web_and_diag_only_with_a_model(sims):
    s, _ = sims
    for name, diag in (("none", False), ("logreg", True)):
        info = [ln for ln in device_lines(run(s[name], lab_files("V1c"), [(0, "INFO")])) if ln.startswith("# INFO")][-1]
        m = RE_INFO.match(info)
        assert m["fw"] == "3.2.0" and firmware_label(m["fw"]) == "v3.2 (3.2.0)"
        assert m["fitur"].split(",") == ["panel", "cahaya", "pemilih", "web"] + (["diag"] if diag else [])


def test_diag_without_a_model_refuses_plainly(sims):
    s, _ = sims
    out = run(s["none"], lab_files("V1c"), [(0, "DIAG")])
    assert any(ln.startswith("# DIAG GAGAL: belum ada model diagnosis") for ln in device_lines(out))
    assert final(out)["R0"] == "0" and "# MULAI" not in out                   # nothing was switched or swept


def _laptop_diagnosis(out, model):
    """The laptop's answer on exactly the sweeps the ESP32 printed (same features as the live diagnosis)."""
    blocks = [protocol.parse_block(b) for b in protocol.split_blocks("\n".join(device_lines(out)))]
    by_t = {p.topology: p for p in blocks if p.label.startswith("diag_")}
    assert set(by_t) == set(dataset.TOPOS)
    feats = {t: dataset.shape_features(p.v, p.i) for t, p in by_t.items()}
    pmax = {t: protocol.derive(p.v, p.i, p.header.get("voc"))["pmax"] for t, p in by_t.items()}
    x = dataset.round_vector(feats, pmax)
    proba = model.proba([x])[0]
    best = max(proba, key=proba.get)
    return dataset.CLASSES[best], proba[best]


@pytest.mark.parametrize("kind", ["logreg", "tree"])
@pytest.mark.parametrize("condition", ["V1c", "V3_opak", "V6_paranet65"])
def test_diag_on_the_esp32_equals_the_laptop(sims, kind, condition):
    s, models = sims
    out = run(s[kind], lab_files(condition), [(0, "DIAG")])
    lines = [ln for ln in device_lines(out) if ln.startswith("# diagnosis=")]
    assert len(lines) == 1, device_lines(out)[-5:]
    m = RE_DIAG.match(lines[0])
    assert m["model"] == models[kind]["model_id"]
    cls, conf = _laptop_diagnosis(out, models[kind]["model"])
    assert m["cls"] == cls and float(m["conf"]) == pytest.approx(conf, abs=2e-3)
    assert final(out)["R0"] == "0" and final(out)["topologi"] == "-"          # all relays open afterwards


def test_off_stops_diag(sims):
    s, _ = sims
    out = run(s["logreg"], lab_files("V1c"), [(0, "DIAG"), (3000, "OFF")])
    lines = device_lines(out)
    assert "# DIAG dihentikan" in lines and not any(ln.startswith("# diagnosis=") for ln in lines)
    assert final(out)["R0"] == "0"


def _json(out, path):
    return [json.loads(b) for c, m, p, t, b in http_responses(out) if p == path and c == 200]


def test_web_page_is_self_contained_and_shows_the_last_sweep(sims):
    s, _ = sims
    out = run(s["logreg"], lab_files("V6_paranet65"),
              [(1000, "##HTTP GET /"), (1100, "##HTTP GET /data"), (1200, "PILIH"), (14000, "##HTTP GET /data"),
               (15000, "DIAG"), (45000, "##HTTP GET /data")])          # boot takes ~0.5 s; PILIH ~9 s; DIAG ~18 s
    page = [b for c, m, p, t, b in http_responses(out) if p == "/"][0]
    assert "<svg" in page and "fetch('/data')" in page
    assert not re.search(r"(src|href)\s*=\s*[\"']?https?://", page) and "http://" not in page   # nothing from the internet
    first, after_pilih, after_diag = _json(out, "/data")
    assert first["titik"] == [] and first["fw"] == "3.2.0"
    assert after_pilih["pemilih"] in ("4S", "2S2P", "TCT") and after_pilih["topologi"] == after_pilih["pemilih"]
    assert len(after_pilih["titik"]) >= 90 and after_pilih["label"].startswith("pilih_")
    assert after_diag["diagnosis"] in dataset.CLASSES and 0 < after_diag["yakin"] <= 1
    assert after_diag["topologi"] == "" and after_diag["label"].endswith("_4P")     # DIAG ends with the array off


def test_web_stop_ends_a_running_task(sims):
    s, _ = sims
    out = run(s["logreg"], lab_files("V1c"), [(0, "DIAG"), (2500, "##HTTP POST /off")])
    lines = device_lines(out)
    assert "# DIAG dihentikan" in lines and final(out)["R0"] == "0"
    assert any(p == "/off" and c == 200 for c, m, p, t, b in http_responses(out))


def test_wifi_can_be_switched_off(sims):
    s, _ = sims
    out = run(s["none"], lab_files("V1c"), [(1000, "WEB 0"), (1500, "##HTTP GET /data"), (2000, "STATUS"), (2500, "WEB 1"),
                                            (3000, "STATUS")])
    lines = device_lines(out)
    assert "# WEB OFF: WiFi mati" in lines and any(ln.startswith("# WEB ON") for ln in lines)
    assert "##WIFI OFF" in out
    served = http_responses(out)
    assert len(served) == 1 and out.index("# WEB ON", out.index("# WEB OFF")) < out.index("##HTTP 200")  # only after WEB 1


def test_api_accepts_diag_as_a_relay_moving_command():
    from shadeshift import commands
    assert commands.validate_raw("diag") == "DIAG" and commands.is_actuating("raw", "DIAG")
    with pytest.raises(commands.CommandError):
        commands.validate_raw("PILIH")                    # the dashboard uses the auto_select action instead
