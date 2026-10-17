"""Topology selector (pemilih) for the edge gateway and the server (CONTRACT.md §4).

Feature extraction is port_c.py, the float32 replica of pemilih.h (verified equal to the C code on 38/38 lab
curves). The model weights are parsed from pemilih_bobot.h, the single source of truth also compiled into
the ESP32 firmware. Backends: "numpy" (port_c.pilih, identical math to pemilih_putuskan); ONNX Runtime is
added in Stage 2.
"""
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from shadeshift import inti, protocol

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
    latency_us: float
    decided_by: str
    model_id: str


class EdgeSelector:
    """decide(v, i) -> Decision for a 4S sweep, or None when there are fewer than 10 valid points."""

    def __init__(self, role="gateway", runtime="numpy"):
        if role not in ("gateway", "server"):
            raise ValueError("role must be 'gateway' or 'server'")
        self.role = role
        self.W = inti.muat_bobot(str(weights_path()))
        self.model_id = model_id(self.W)
        self.runtime = "numpy"
        self.runtime_label = f"numpy {np.__version__} (port of pemilih.h)"

    @property
    def decided_by(self):
        return f"{self.role}_{self.runtime}"

    def decide(self, v, i):
        import port_c                                   # on sys.path via shadeshift.inti (SHADESHIFT_ML/edge_ai/pemilih)
        s = protocol.to_sapuan(v, i)
        if len(s.V) < MIN_POINTS:
            return None
        t0 = time.perf_counter()
        V, I = port_c.cuplik_ulang(s.V, s.I)
        x = port_c.fitur_bentuk(V, I)
        k, scores = port_c.pilih(x, self.W)
        dt_us = (time.perf_counter() - t0) * 1e6
        return Decision(choice=CLASSES[k], scores=[float(v) for v in scores], features=[float(v) for v in x],
                        latency_us=round(dt_us, 1), decided_by=self.decided_by, model_id=self.model_id)
