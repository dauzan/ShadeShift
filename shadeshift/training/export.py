"""Model export: C headers for the ESP32 and activation of a retrained selector (docs/CONTRACT.md §14).

A selector is the same 73 float32 numbers as pemilih_bobot.h, so the ESP32 code (pemilih.h), its fingerprint and the
gateway's ONNX model all stay valid. Activating one rewrites every copy together, so they never disagree:
- SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h        (the source of truth the laptop reads)
- SHADESHIFT_ML/edge_ai/pemilih/uji_pemilih/pemilih_bobot.h and the expected decisions in uji_pemilih/data_uji.h
  (the on-board self-test must still print LULUS 12/12)
- firmware/shadeshift_firmware/pemilih_bobot.h          (reflash the board afterwards)
- models/pemilih.onnx (+ .json)                          (needs the 'onnx' package; without it the gateway uses numpy)
Each file keeps its line endings. The previous weights stay in the model registry, so activation can be undone.
"""
import re
from pathlib import Path

import numpy as np

from shadeshift import inti
from shadeshift.edge.selector import FEATURE_NAMES
from shadeshift.training import dataset

ROOT = Path(__file__).resolve().parents[2]


def _lit(v):
    t = "%.9g" % v
    return (t if any(c in t for c in ".eEn") else t + ".0") + "f"


def _f32(a):
    return ", ".join(_lit(v) for v in np.asarray(a, dtype=np.float32).ravel())


def selector_header(W, model_id, trained_on):
    """pemilih_bobot.h text (LF), same layout as the original from latih_ekspor.py."""
    lines = [f"// Bobot model pemilih susunan SHADESHIFT (regresi logistik, sapuan 4S), {model_id}. Dilatih pada: {trained_on}.",
             "// Dibuat otomatis oleh shadeshift.training (halaman Model AI). Bobot sebelumnya tersimpan di registri model.",
             "// Urutan fitur: " + ", ".join(n.replace("0.", "0.") for n in FEATURE_NAMES),
             "// Urutan kelas: 0 = 4S, 1 = 2S2P, 2 = TCT", "#pragma once",
             "#define PEMILIH_N_FITUR %d" % len(FEATURE_NAMES), "#define PEMILIH_N_KELAS 3",
             "static const float PEMILIH_RERATA[PEMILIH_N_FITUR] = {%s};" % _f32(W["mean"]),
             "static const float PEMILIH_SKALA[PEMILIH_N_FITUR] = {%s};" % _f32(W["scale"]),
             "static const float PEMILIH_BOBOT[PEMILIH_N_KELAS][PEMILIH_N_FITUR] = {"]
    lines += ["  {%s}," % _f32(row) for row in W["coef"]]
    lines += ["};", "static const float PEMILIH_BIAS[PEMILIH_N_KELAS] = {%s};" % _f32(W["bias"])]
    return "\n".join(lines) + "\n"


def diagnosis_header(model, model_id):
    """C header for the 6-class diagnosis (stage 4F runs it on the ESP32). Feature order = dataset.ROUND_FEATURES."""
    names = ", ".join(f"{i} = {c}" for i, c in enumerate(dataset.CLASSES))
    out = [f"// Model diagnosis SHADESHIFT {model_id} ({model['kind']}). Dibuat otomatis oleh shadeshift.training.",
           f"// Masukan: {len(dataset.ROUND_FEATURES)} angka = 14 fitur bentuk sapuan 4S, 2S2P, TCT, 4P (urutan pemilih.h) + "
           "Pmax 2S2P/4S, TCT/4S, 4P/4S.", f"// Kelas: {names}", "#pragma once",
           f'#define DIAG_MODEL_ID "{model_id}"',
           "#define DIAG_N_FITUR %d" % len(dataset.ROUND_FEATURES)]
    cls = model["classes"]
    if model["kind"] == "logreg":
        out += ["#define DIAG_N_KELAS %d" % len(cls),
                "static const unsigned char DIAG_KELAS[DIAG_N_KELAS] = {%s};" % ", ".join(map(str, cls)),
                "static const float DIAG_RERATA[DIAG_N_FITUR] = {%s};" % _f32(model["mean"]),
                "static const float DIAG_SKALA[DIAG_N_FITUR] = {%s};" % _f32(model["scale"]),
                "static const float DIAG_BOBOT[DIAG_N_KELAS][DIAG_N_FITUR] = {"]
        out += ["  {%s}," % _f32(r) for r in model["coef"]]
        out += ["};", "static const float DIAG_BIAS[DIAG_N_KELAS] = {%s};" % _f32(model["bias"])]
    else:
        leaf_cls = [cls[int(np.argmax(v))] for v in model["value"]]
        leaf_conf = [float(max(v)) / float(sum(v)) for v in model["value"]]
        out += ["#define DIAG_N_SIMPUL %d" % len(model["feature"]),
                "// Pohon: simpul n -> bila DIAG_FITUR[n] < 0 daun dengan kelas DIAG_DAUN[n]; bila tidak,",
                "// x[DIAG_FITUR[n]] <= DIAG_AMBANG[n] ? DIAG_KIRI[n] : DIAG_KANAN[n].",
                "static const short DIAG_FITUR[DIAG_N_SIMPUL] = {%s};" % ", ".join(map(str, model["feature"])),
                "static const float DIAG_AMBANG[DIAG_N_SIMPUL] = {%s};" % _f32(model["threshold"]),
                "static const short DIAG_KIRI[DIAG_N_SIMPUL] = {%s};" % ", ".join(map(str, model["left"])),
                "static const short DIAG_KANAN[DIAG_N_SIMPUL] = {%s};" % ", ".join(map(str, model["right"])),
                "static const unsigned char DIAG_DAUN[DIAG_N_SIMPUL] = {%s};" % ", ".join(map(str, leaf_cls)),
                "static const float DIAG_YAKIN[DIAG_N_SIMPUL] = {%s};" % _f32(leaf_conf)]
    return "\n".join(out) + "\n"


def selector_paths(root=ROOT):
    root = Path(root)
    pem = root / "SHADESHIFT_ML" / "edge_ai" / "pemilih"
    return {"headers": [pem / "pemilih_bobot.h", pem / "uji_pemilih" / "pemilih_bobot.h",
                        root / "firmware" / "shadeshift_firmware" / "pemilih_bobot.h"],
            "self_test": pem / "uji_pemilih" / "data_uji.h", "onnx": root / "models" / "pemilih.onnx",
            "diagnosis_header": root / "firmware" / "shadeshift_firmware" / "diagnosis_model.h"}


def install_diagnosis(model, model_id, paths):
    """Write the active diagnosis model into the firmware folder (DIAG uses it after a reflash)."""
    h = Path(paths["diagnosis_header"])
    h.parent.mkdir(parents=True, exist_ok=True)
    _write_like(h, diagnosis_header(model, model_id))
    return [f"wrote {h.name} into {h.parent.name}: reflash the firmware to run DIAG on the board"]


def _write_like(path, text):
    """Write text with the line endings the existing file uses (CRLF for the zip originals)."""
    path = Path(path)
    crlf = path.is_file() and b"\r\n" in path.read_bytes()
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def activate_selector(W, model_id, trained_on, paths):
    """Write the selector everywhere (see module docstring). Returns a list of what was done."""
    import port_c
    done = []
    text = selector_header(W, model_id, trained_on)
    for h in paths["headers"]:
        _write_like(h, text)
        done.append(f"wrote {h.name} ({h.parent.name})")
    st = Path(paths["self_test"])
    if st.is_file():
        t = st.read_bytes().decode("utf-8")
        feats = np.asarray(inti._larik(t, "UJI_FITUR"), np.float32).reshape(-1, len(FEATURE_NAMES))
        dec = [int(port_c.pilih(x, W)[0]) for x in feats]
        t2, n = re.subn(r"(UJI_KEPUTUSAN\[N_UJI\] = \{)[^}]*(\})", lambda m: m.group(1) + ", ".join(map(str, dec)) + m.group(2), t)
        if n != 1:
            raise RuntimeError("could not update UJI_KEPUTUSAN in data_uji.h")
        st.write_bytes(t2.encode("utf-8"))
        done.append(f"updated the on-board self-test's expected decisions ({len(dec)} curves)")
    try:
        from shadeshift.edge.export_onnx import export
        out, _ = export(paths["onnx"], weights=paths["headers"][0])
        sidecar = out.with_suffix(out.suffix + ".json")
        _write_like(sidecar, sidecar.read_bytes().decode("utf-8").replace("\r\n", "\n"))
        done.append(f"regenerated {out.name}")
    except ImportError:
        done.append("ONNX not regenerated (package 'onnx' missing): the gateway uses the numpy port until it is")
    return done
