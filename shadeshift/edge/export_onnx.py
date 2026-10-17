"""Build models/pemilih.onnx from SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h (CONTRACT.md §4).

The ONNX graph is the exact math of pemilih_putuskan() in pemilih.h:
    scores = bias + coef · ((features - mean) / scale)      label = argmax(scores)   (0 = 4S, 1 = 2S2P, 2 = TCT)
The weights header stays the single source of truth; this file is generated from it and committed.
Needs the `onnx` package (development only; the gateway needs only onnxruntime).

Usage:  python -m shadeshift.edge.export_onnx [--out models/pemilih.onnx]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shadeshift import config, inti  # noqa: E402
from shadeshift.edge.selector import CLASSES, FEATURE_NAMES, model_id, weights_path, weights_sha256  # noqa: E402

OPSET = 17
IR_VERSION = 9            # opset 17 needs IR >= 8; 9 keeps the file loadable by older runtimes too


def build(W):
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    f32 = np.float32
    inits = [numpy_helper.from_array(np.asarray(W["mean"], f32), "mean"),
             numpy_helper.from_array(np.asarray(W["scale"], f32), "scale"),
             numpy_helper.from_array(np.ascontiguousarray(np.asarray(W["coef"], f32).T), "coef_t"),
             numpy_helper.from_array(np.asarray(W["bias"], f32), "bias")]
    nodes = [helper.make_node("Sub", ["features", "mean"], ["centered"]),
             helper.make_node("Div", ["centered", "scale"], ["standardized"]),
             helper.make_node("MatMul", ["standardized", "coef_t"], ["linear"]),
             helper.make_node("Add", ["linear", "bias"], ["scores"]),
             helper.make_node("ArgMax", ["scores"], ["label"], axis=1, keepdims=0, select_last_index=0)]
    graph = helper.make_graph(
        nodes, "pemilih_susunan",
        [helper.make_tensor_value_info("features", TensorProto.FLOAT, ["N", len(FEATURE_NAMES)])],
        [helper.make_tensor_value_info("scores", TensorProto.FLOAT, ["N", len(CLASSES)]),
         helper.make_tensor_value_info("label", TensorProto.INT64, ["N"])],
        inits)
    model = helper.make_model(graph, producer_name="shadeshift.edge.export_onnx",
                              opset_imports=[helper.make_opsetid("", OPSET)])
    model.ir_version = IR_VERSION
    model.doc_string = ("ShadeShift topology selector (pemilih): logistic regression on 14 I-V shape features from one 4S "
                        "sweep. Trained on simulation; lab result: loss 0.82 % vs 2.71 % best fixed topology.")
    meta = {"model_id": model_id(W), "weights_sha256": weights_sha256(W), "classes": ",".join(CLASSES),
            "feature_names": ",".join(FEATURE_NAMES), "source": "SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h"}
    helper.set_model_props(model, meta)
    onnx.checker.check_model(model)
    return model, meta


def export(out=None, weights=None):
    out = Path(out or config.load().model_path)
    W = inti.muat_bobot(str(weights or weights_path()))
    model, meta = build(W)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(model.SerializeToString())
    sidecar = {"model_id": meta["model_id"], "weights_sha256": meta["weights_sha256"], "classes": list(CLASSES),
               "feature_names": list(FEATURE_NAMES), "opset": OPSET, "ir_version": IR_VERSION,
               "inputs": {"features": "float32 [N, 14]"},
               "outputs": {"scores": "float32 [N, 3]", "label": "int64 [N] (0 = 4S, 1 = 2S2P, 2 = TCT)"},
               "generator": "python -m shadeshift.edge.export_onnx",
               "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    out.with_suffix(out.suffix + ".json").write_text(json.dumps(sidecar, indent=1) + "\n", encoding="utf-8")
    return out, sidecar


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="output path (default: SHADESHIFT_MODEL_PATH, models/pemilih.onnx)")
    args = ap.parse_args()
    out, meta = export(args.out)
    print(f"wrote {out} ({out.stat().st_size} bytes), model_id {meta['model_id']}")


if __name__ == "__main__":
    main()
