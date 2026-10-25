"""Training the AI on measured data (Stage 4D, CONTRACT §14): models, fair test, export, activation, registry, import."""
import dataclasses
import io
import shutil
import subprocess
import uuid
import zipfile

import numpy as np
import pytest

from conftest import ROOT, heartbeat, server_client
from shadeshift import inti, protocol
from shadeshift.edge.selector import EdgeSelector, model_id as selector_model_id, weights_sha256
from shadeshift.training import dataset, export, models as TM, pipeline


# ---------------- models ----------------
def test_logreg_reaches_the_optimum_of_the_regularized_objective():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(m, 1.0, (60, 3)) for m in (0, 3, 6)])
    y = np.repeat([0, 1, 2], 60)
    m = TM.LogReg(C=1.0).fit(X, y)
    assert (m.predict(X) == y).mean() > 0.9
    Z = (X - m.mean) / m.scale                         # gradient of C*logloss + 0.5|W|^2 must vanish at the solution
    S = Z @ m.coef.T + m.bias
    P = np.exp(S - S.max(1, keepdims=True))
    P /= P.sum(1, keepdims=True)
    G = P - np.eye(3)[y]
    assert np.abs(G.T @ Z + m.coef).max() < 1e-3 and np.abs(G.sum(0)).max() < 1e-3
    again = TM.from_dict(m.to_dict())
    assert np.array_equal(again.predict(X), m.predict(X))


def test_tree_learns_a_two_level_rule_and_respects_depth():
    rng = np.random.default_rng(1)
    X = rng.uniform(-1, 1, (400, 2))
    y = ((X[:, 0] > 0.3) & (X[:, 1] > -0.2)).astype(int)   # needs two splits
    assert (TM.Tree(max_depth=2).fit(X, y).predict(X) == y).mean() > 0.97
    shallow = TM.Tree(max_depth=1).fit(X, y)
    assert len(shallow.feature) <= 3 and (shallow.predict(X) == y).mean() < 0.92
    assert np.array_equal(TM.from_dict(shallow.to_dict()).predict(X), shallow.predict(X))


# ---------------- evaluation reproduces the research numbers ----------------
@pytest.fixture(scope="module")
def lab():
    return dataset.lab_examples()


def test_lab_rounds_and_labels(lab):
    assert len(lab) == 30 and all(e.x_round is not None and len(e.x_round) == len(dataset.ROUND_FEATURES) for e in lab)
    by = dataset.describe(lab)["lab"]
    assert by["by_class"] == {"normal": 9, "partial_shading": 3, "uniform_dimming": 18} and by["groups"] == 6
    assert not any("V5" in e.ref or "V1d" in e.ref for e in lab)


def test_selector_evaluation_reproduces_the_lab_claim(lab):
    """Through this pipeline the shipped selector loses 0.82 % and the best fixed wiring (2S2P) 2.71 % on the 30 lab
    rounds: the numbers of SHADESHIFT_ML/uji_model/LAPORAN_UJI_FISIK.md."""
    r = pipeline.train("selector", "logreg", {"real": [], "lab": lab}, ["lab"], active_selector=inti.muat_bobot())
    act = r["report"]["selection"]["active"]["relative"]
    assert act["ai_loss_pct"] == pytest.approx(0.82, abs=0.005)
    assert act["best_fixed"] == "2S2P" and act["best_fixed_loss_pct"] == pytest.approx(2.71, abs=0.005)
    assert r["report"]["test_mode"].startswith("leave-one-lab shading pattern-out") and r["report"]["n_test"] == 30
    assert r["model_id"].startswith("pemilih-logreg-v1@")


def _real(day, group, label, x, pmax=1.0):
    return dataset.Example(source="real", group=group, day=day, ref=group, label=label, modules="",
                           pmax={"4S": pmax, "2S2P": pmax * 0.9, "TCT": pmax * 0.95, "4P": pmax},
                           x_round=np.asarray(x, float), x_4s=np.asarray(x[:14], float))


def test_fair_test_modes(lab):
    rng = np.random.default_rng(2)
    two_days = [_real(d, f"scan{d}{k}", k % 2, rng.normal(k % 2 * 3, 1, 59)) for d in ("2026-10-20", "2026-10-21")
                for k in range(6)]
    r = pipeline.train("diagnosis", "logreg", {"real": two_days, "lab": lab}, ["real"])
    assert r["report"]["test_mode"].startswith("held-out day 2026-10-21") and r["report"]["n_test"] == 6
    r = pipeline.train("diagnosis", "logreg", {"real": two_days, "lab": lab}, ["real"], test_day="2026-10-20")
    assert r["report"]["test_mode"].startswith("held-out day 2026-10-20")
    one_day = [e for e in two_days if e.day == "2026-10-20"]
    r = pipeline.train("diagnosis", "logreg", {"real": one_day, "lab": lab}, ["real"])
    assert "leave-one-scan-out" in r["report"]["test_mode"] and "weaker evidence" in r["report"]["test_mode"]
    r = pipeline.train("diagnosis", "logreg", {"real": one_day, "lab": lab}, ["lab"])
    assert r["report"]["test_mode"].startswith("trained without real data")      # lab -> real gap
    with pytest.raises(pipeline.TrainingError):
        pipeline.train("selector", "tree", {"real": [], "lab": lab}, ["lab"])     # the ESP32 runs logistic regression


# ---------------- export ----------------
def test_selector_header_round_trip_and_fingerprint(tmp_path):
    W = inti.muat_bobot()
    h = tmp_path / "pemilih_bobot.h"
    h.write_text(export.selector_header(W, selector_model_id(W), "sim"), encoding="utf-8")
    back = inti.muat_bobot(str(h))
    assert weights_sha256(back) == weights_sha256(W)                 # the same 73 float32 numbers, bit for bit


def test_missing_selector_class_is_never_chosen(lab):
    only_two = [e for e in lab if e.best != 1]                        # no round where 2S2P was best
    r = pipeline.train("selector", "logreg", {"real": [], "lab": only_two}, ["lab"])
    W = pipeline.selector_weights(r["model"])
    assert W["bias"][1] == pipeline.NEVER_BIAS and not W["coef"][1].any()


def test_diagnosis_headers_compile(tmp_path, lab):
    from firmware_sim import ENV, compiler
    for kind in ("logreg", "tree"):
        r = pipeline.train("diagnosis", kind, {"real": [], "lab": lab}, ["lab"])
        (tmp_path / "diagnosis_model.h").write_text(export.diagnosis_header(r["model"].to_dict(), r["model_id"]), encoding="utf-8")
        (tmp_path / "t.c").write_text('#include "diagnosis_model.h"\nint main(void){return DIAG_N_FITUR == 59 ? 0 : 1;}\n')
        out = subprocess.run([compiler("gcc"), "-Wall", "-Wno-unused-variable", "-Wno-unused-const-variable",
                              str(tmp_path / "t.c"), "-o", str(tmp_path / "t.exe")], capture_output=True, text=True, env=ENV)
        assert out.returncode == 0, out.stderr
        assert subprocess.run([str(tmp_path / "t.exe")], env=ENV).returncode == 0


def test_activate_selector_rewrites_every_copy(tmp_path, lab):
    paths = export.selector_paths(tmp_path)
    src = export.selector_paths(ROOT)
    for a, b in zip(src["headers"] + [src["self_test"]], paths["headers"] + [paths["self_test"]]):
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a, b)
    r = pipeline.train("selector", "logreg", {"real": [], "lab": lab}, ["lab"])
    W = pipeline.selector_weights(r["model"])
    done = export.activate_selector(W, r["model_id"], "lab", paths)
    assert any("self-test" in d for d in done)
    for h in paths["headers"]:
        assert b"\r\n" in h.read_bytes()                              # line endings of the originals kept
        assert weights_sha256(inti.muat_bobot(str(h))) == weights_sha256(W)
    import port_c
    t = paths["self_test"].read_text(encoding="utf-8")
    feats = np.asarray(inti._larik(t, "UJI_FITUR"), np.float32).reshape(-1, 14)
    assert inti._larik(t, "UJI_KEPUTUSAN") == [float(port_c.pilih(x, W)[0]) for x in feats]
    if any("regenerated" in d for d in done):                         # onnx installed: same weights, same decisions
        import onnxruntime as ort
        sess = ort.InferenceSession(str(paths["onnx"]), providers=["CPUExecutionProvider"])
        assert sess.get_modelmeta().custom_metadata_map["weights_sha256"] == weights_sha256(W)
        labels = sess.run(["label"], {"features": feats})[0]
        assert labels.tolist() == [int(port_c.pilih(x, W)[0]) for x in feats]
    assert weights_sha256(inti.muat_bobot(str(src["headers"][0]))) == weights_sha256(EdgeSelector(runtime="numpy").W)


# ---------------- server: registry, activation, import ----------------
def _ingest_scan(api, sid, code, lab_cond, reps=(1, 2)):
    sc = api.post(f"/api/v1/sessions/{sid}/scans", json={"code": code, "rounds": len(reps), "pause_s": 0}).json()
    for k, rep in enumerate(reps):
        for t in dataset.TOPOS:
            p = protocol.parse_block(open(f"{inti.DATA_LAB}/{lab_cond}_{t}_u{rep}.csv", encoding="utf8").read().splitlines())
            body = {"uuid": str(uuid.uuid4()), "device_id": "esp32-60", "source": "device",
                    "label": f"{sc['condition']}_{t}_u{sc['repeat_start'] + k}", "topology": t,
                    "captured_at": "2026-10-20T03:15:30.123Z", "points": {"v": p.v, "i": p.i}, "header": p.header,
                    "complete": p.complete, "raw_text": p.raw_text, "scan_uuid": sc["uuid"],
                    "condition": sc["condition"], "repeat": sc["repeat_start"] + k}
            assert api.post("/api/v1/ingest/sweeps", json=body).status_code == 201
    api.post(f"/api/v1/commands/{sc['command_id']}/result", json={"status": "done", "result": "ok"})
    return sc


def test_registry_training_activation_and_session_import(tmp_path, monkeypatch):
    with server_client(tmp_path / "a") as api:
        rows = api.get("/api/v1/models", params={"task": "selector"}).json()
        assert len(rows) == 1 and rows[0]["active"] and rows[0]["note"] == "shipped with the project"
        heartbeat(api, "esp32-60")
        sid = api.post("/api/v1/sessions", json={"device_id": "esp32-60", "place": "outdoor_sun"}).json()["id"]
        _ingest_scan(api, sid, "A1", "V1c")
        _ingest_scan(api, sid, "C1", "V3_paranet65")
        _ingest_scan(api, sid, "B4", "V3_opak")
        api.post(f"/api/v1/sessions/{sid}/end")
        summary = api.get("/api/v1/training/data").json()
        assert summary["real"]["rounds"] == 6 and summary["lab"]["rounds"] == 30
        zip_bytes = api.get(f"/api/v1/sessions/{sid}/export.zip").content

    with server_client(tmp_path / "b") as api:
        paths = export.selector_paths(tmp_path / "files")        # activations must never touch the project files
        for a, b in zip(export.selector_paths(ROOT)["headers"] + [export.selector_paths(ROOT)["self_test"]],
                        paths["headers"] + [paths["self_test"]]):
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a, b)
        monkeypatch.setattr(api.core, "selector_paths", paths)
        monkeypatch.setattr(api.core, "settings", dataclasses.replace(api.core.settings, model_path=paths["onnx"]))
        r = api.post("/api/v1/sessions/import", files={"file": ("s.zip", zip_bytes, "application/zip")})
        assert r.status_code == 201 and r.json()["sweeps"] == 24, r.text
        assert api.post("/api/v1/sessions/import", files={"file": ("s.zip", zip_bytes, "application/zip")}).status_code == 409
        bad = io.BytesIO()
        zipfile.ZipFile(bad, "w").writestr("x.txt", "x")
        assert api.post("/api/v1/sessions/import", files={"file": ("x.zip", bad.getvalue(), "application/zip")}).status_code == 400

        m = api.post("/api/v1/models/train", json={"task": "diagnosis", "kind": "tree", "sources": ["real", "lab"],
                                                     "params": {"max_depth": 3}})
        assert m.status_code == 201, m.text
        m = m.json()
        assert m["evidence"] == "real" and "leave-one-scan-out" in m["report"]["test_mode"]
        assert m["report"]["tested_on"]["real"]["rounds"] == 6 and not m["active"]
        assert "DIAG_N_FITUR 59" in api.get(f"/api/v1/models/{m['id']}/header.h").text
        assert api.post(f"/api/v1/models/{m['id']}/activate").json()["active"] == m["model_id"]
        assert api.post("/api/v1/models/train", json={"task": "selector", "kind": "tree"}).status_code == 400
        assert api.post("/api/v1/models/train", json={"task": "diagnosis", "params": {"gamma": 1}}).status_code == 422

        sel = api.post("/api/v1/models/train", json={"task": "selector", "sources": ["lab"]}).json()
        if sel["report"]["selection"]["better_than_active"]:
            assert api.post(f"/api/v1/models/{sel['id']}/activate").status_code == 200
        else:
            assert api.post(f"/api/v1/models/{sel['id']}/activate").status_code == 409     # never activates a worse one
        shipped = api.get("/api/v1/models", params={"task": "selector"}).json()[-1]
        assert shipped["note"] == "shipped with the project"
        assert api.post(f"/api/v1/models/{shipped['id']}/activate").status_code == 200
