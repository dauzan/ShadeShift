"""Topology selector (pemilih) for the edge gateway and the server (CONTRACT.md §4).

Feature extraction is port_c.py, the float32 replica of pemilih.h (verified equal to the C code on 38/38 lab
curves). The weights come from pemilih_bobot.h, the single source of truth that is also compiled into the ESP32
firmware. Two backends compute the same scores:
- "onnx":  models/pemilih.onnx (generated from the header) on ONNX Runtime, CPU provider only;
- "numpy": port_c.pilih, the line-by-line port of pemilih_putuskan().
runtime="auto" uses ONNX when onnxruntime is installed and the model's weights hash matches the header,
otherwise numpy, and records why (fallback_reason).
"""
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from shadeshift import inti, protocol

log = logging.getLogger("shadeshift.edge")
CLASSES = ("4S", "2S2P", "TCT")
FEATURE_NAMES = ("Vmp_Voc", "Imp_Isc", "FF", "n_puncak", "P2_Pmax") + tuple(f"I@0.{k}Voc" for k in range(1, 10))
MIN_POINTS = 10


def weights_path():
    return Path(inti.PEMILIH) / "pemilih_bobot.h"


def weights_sha256(W):
    """Hash of the 73 float32 weights (mean, scale, coef row-major, bias), independent of file line endings."""
    blob = b"".join(np.ascontiguousarray(W[k], dtype="<f4").tobytes() for k in ("mean", "scale", "coef", "bias"))
    return hashlib.sha256(blob).hexdigest()


def model_id(W):
    return f"pemilih-logreg-v1@{weights_sha256(W)[:12]}"


@dataclass
class Decision:
    choice: str
    scores: list
    features: list
    latency_us: float          # features + model, on this machine
    model_us: float            # model only
    decided_by: str
    model_id: str


class EdgeSelector:
    """decide(v, i) -> Decision for a 4S sweep, or None when there are fewer than 10 valid points."""

    def __init__(self, role="gateway", runtime="auto", model_path=None):
        if role not in ("gateway", "server"):
            raise ValueError("role must be 'gateway' or 'server'")
        if runtime not in ("auto", "onnx", "numpy"):
            raise ValueError("runtime must be auto, onnx or numpy")
        self.role = role
        self.W = inti.muat_bobot(str(weights_path()))
        self.model_id = model_id(self.W)
        self.model_path = Path(model_path) if model_path else None
        self.session = None
        self.fallback_reason = None
        if runtime in ("auto", "onnx"):
            try:
                self.session = self._load_onnx()
            except Exception as e:
                if runtime == "onnx":
                    raise
                self.fallback_reason = f"{type(e).__name__}: {e}"
                log.warning("edge selector falls back to numpy: %s", self.fallback_reason)
        if self.session is not None:
            import onnxruntime
            self.runtime = "onnx"
            self.runtime_label = f"onnxruntime {onnxruntime.__version__} (CPUExecutionProvider)"
        else:
            self.runtime = "numpy"
            self.runtime_label = f"numpy {np.__version__} (port of pemilih.h)"
            if runtime == "numpy":
                self.fallback_reason = None

    def _load_onnx(self):
        import onnxruntime as ort
        if hasattr(ort, "disable_telemetry_events"):     # Windows builds can send usage data to Microsoft: keep it off
            ort.disable_telemetry_events()
        if self.model_path is None or not self.model_path.is_file():
            raise FileNotFoundError(f"ONNX model not found: {self.model_path} (python -m shadeshift.edge.export_onnx)")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        sess = ort.InferenceSession(str(self.model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        meta = sess.get_modelmeta().custom_metadata_map
        if meta.get("weights_sha256") != weights_sha256(self.W):
            raise ValueError("ONNX model was built from different weights than pemilih_bobot.h; "
                             "regenerate it with: python -m shadeshift.edge.export_onnx")
        return sess

    @property
    def decided_by(self):
        return f"{self.role}_{self.runtime}"

    def features(self, v, i):
        """14 shape features exactly as pemilih.h computes them (float32), or None if too few points."""
        import port_c                                   # on sys.path via shadeshift.inti (SHADESHIFT_ML/edge_ai/pemilih)
        s = protocol.to_sapuan(v, i)
        if len(s.V) < MIN_POINTS:
            return None
        V, I = port_c.cuplik_ulang(s.V, s.I)
        return port_c.fitur_bentuk(V, I)

    def scores(self, x):
        """Scores and class index for one feature vector."""
        if self.session is not None:
            scores, label = self.session.run(["scores", "label"], {"features": np.asarray(x, np.float32)[None, :]})
            return [float(v) for v in scores[0]], int(label[0])
        import port_c
        k, scores = port_c.pilih(x, self.W)
        return [float(v) for v in scores], int(k)

    def decide(self, v, i):
        t0 = time.perf_counter()
        x = self.features(v, i)
        if x is None:
            return None
        t1 = time.perf_counter()
        scores, k = self.scores(x)
        t2 = time.perf_counter()
        return Decision(choice=CLASSES[k], scores=scores, features=[float(f) for f in x],
                        latency_us=round((t2 - t0) * 1e6, 1), model_us=round((t2 - t1) * 1e6, 1),
                        decided_by=self.decided_by, model_id=self.model_id)

    def info(self):
        return {"model_id": self.model_id, "runtime": self.runtime_label, "decided_by": self.decided_by,
                "fallback_reason": self.fallback_reason}
