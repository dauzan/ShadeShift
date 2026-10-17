"""Edge AI (CONTRACT §4): ONNX model generated from the C weights, parity with C/numpy, honest fallback."""
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shadeshift import config, inti
from shadeshift.edge import export_onnx
from shadeshift.edge.selector import CLASSES, EdgeSelector, model_id

MODEL = config.load(env={}).model_path
REF = Path(inti.PEMILIH) / "referensi_lab_4S.csv"
ort = pytest.importorskip("onnxruntime")


def _lab_4s_curves():
    ref = pd.read_csv(REF)
    for _, row in ref.iterrows():
        path = Path(inti.DATA_LAB) / row.berkas
        if not path.exists():
            path = Path(inti.DATA_LAB) / "_V5_anomali_dioda" / row.berkas
        s = inti.baca_berkas(str(path))
        yield row.berkas, row.keputusan_c, s


def test_committed_model_matches_current_weights():
    sel = EdgeSelector(role="gateway", runtime="onnx", model_path=MODEL)
    assert sel.runtime == "onnx" and sel.decided_by == "gateway_onnx"
    assert sel.model_id == model_id(inti.muat_bobot())
    assert sel.session.get_providers() == ["CPUExecutionProvider"]        # never a cloud provider


def test_onnx_equals_c_and_numpy_on_all_38_lab_curves():
    onnx_sel = EdgeSelector(runtime="onnx", model_path=MODEL)
    np_sel = EdgeSelector(runtime="numpy")
    n = 0
    for name, c_choice, s in _lab_4s_curves():
        a, b = onnx_sel.decide(s.V, s.I), np_sel.decide(s.V, s.I)
        assert a.choice == b.choice == c_choice, name
        assert np.max(np.abs(np.array(a.scores) - np.array(b.scores))) <= 1e-4, name
        assert a.features == b.features
        n += 1
    assert n == 38


def test_too_few_points_gives_no_decision():
    assert EdgeSelector(runtime="numpy").decide([1, 2, 3], [0.1, 0.1, 0.0]) is None


def test_stale_model_falls_back_to_numpy_or_fails_when_strict(tmp_path):
    W = inti.muat_bobot()
    W_other = {k: v.copy() for k, v in W.items()}
    W_other["bias"][0] += 1.0
    stale = tmp_path / "stale.onnx"
    model, _ = export_onnx.build(W_other)
    stale.write_bytes(model.SerializeToString())
    auto = EdgeSelector(runtime="auto", model_path=stale)
    assert auto.runtime == "numpy" and auto.decided_by == "gateway_numpy" and "different weights" in auto.fallback_reason
    with pytest.raises(ValueError):
        EdgeSelector(runtime="onnx", model_path=stale)
    missing = EdgeSelector(runtime="auto", model_path=tmp_path / "missing.onnx")
    assert missing.runtime == "numpy" and "not found" in missing.fallback_reason


def test_export_is_reproducible(tmp_path):
    out, meta = export_onnx.export(tmp_path / "pemilih.onnx")
    assert meta["model_id"] == model_id(inti.muat_bobot())
    assert meta["classes"] == list(CLASSES) and len(meta["feature_names"]) == 14
    sel = EdgeSelector(runtime="onnx", model_path=out)
    _, c_choice, s = next(iter(_lab_4s_curves()))
    assert sel.decide(s.V, s.I).choice == c_choice
