"""Training examples from three sources, never mixed silently (docs/CONTRACT.md §14):

- real: labeled full-scan rounds from the data-collection sessions (source = device);
- lab:  the halogen-lamp lab rounds (SHADESHIFT_ML/data/data_lab; V5 and V1d excluded, as its README says);
- sim:  scenarios from the research simulator (SHADESHIFT_ML/buat_data_diagnosis.py), generated once and cached.

One example = one ROUND: the same shading seen through 4S, 2S2P, TCT and 4P. Features use port_c.py, the float32 replica
of pemilih.h, so the ESP32 can compute exactly the same numbers later:
- diagnosis: 14 shape features of each of the 4 sweeps + Pmax of 2S2P, TCT, 4P relative to 4S  (59 numbers);
- selector:  the 14 shape features of the 4S sweep (as the current selector), label = the best of 4S / 2S2P / TCT.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from shadeshift import fieldwork, inti, protocol
from shadeshift.evaluation import CANDIDATES, light_change_pct

TOPOS = ("4S", "2S2P", "TCT", "4P")
SHAPE = ("Vmp_Voc", "Imp_Isc", "FF", "n_puncak", "P2_Pmax") + tuple(f"I@0.{k}Voc" for k in range(1, 10))
ROUND_FEATURES = tuple(f"{t}:{n}" for t in TOPOS for n in SHAPE) + ("P_2S2P/P_4S", "P_TCT/P_4S", "P_4P/P_4S")
CLASSES = tuple(fieldwork.DIAGNOSIS)          # normal, partial_shading, uniform_dimming, bypass_open, bypass_short, series_resistance
# Where the affected modules are, as far as the TOPOLOGY sweeps can tell. 2S2P strings are A+B and C+D, TCT ties the rows
# A|C and B|D (rangkaian/daftar_kabel.md). Swapping the strings or the rows leaves all four topology curves unchanged, so
# they cannot say WHICH single module is affected, only the pattern. The single-panel sweeps give the exact position.
PATTERNS = ("none", "one", "string_pair", "row_pair", "diagonal", "three", "all")
PAIRS = {"AB": "string_pair", "CD": "string_pair", "AC": "row_pair", "BD": "row_pair", "AD": "diagonal", "BC": "diagonal"}


def pattern_of(modules):
    mods = "".join(sorted(set(modules or "")))
    return {0: "none", 1: "one", 3: "three", 4: "all"}.get(len(mods)) or PAIRS[mods]
SIM_VERSION = 1

# lab condition -> (diagnosis, modules, pattern). Pattern = the group for a fair test: V1 and V1b are the same setting,
# shade cloth 65 % and 75 % shade almost the same (data_lab/README.md).
LAB = {"V1": ("normal", "", "V1"), "V1b": ("normal", "", "V1"), "V1c": ("normal", "", "V1c"),
       "V3_opak": ("partial_shading", "A", "V3_opak"),
       "V3_paranet65": ("uniform_dimming", "A", "V3_paranet"), "V3_paranet75": ("uniform_dimming", "A", "V3_paranet"),
       "V4_paranet65": ("uniform_dimming", "AB", "V4_paranet"), "V4_paranet75": ("uniform_dimming", "AB", "V4_paranet"),
       "V6_paranet65": ("uniform_dimming", "AD", "V6_paranet"), "V6_paranet75": ("uniform_dimming", "AD", "V6_paranet")}


@dataclass
class Example:
    source: str                  # real / lab / sim
    group: str                   # fair-test group: real scan, lab pattern, sim
    day: str                     # local date of the session (real), 'lab', 'sim'
    ref: str                     # human-readable: 'LR1020_B2 u1', 'V3_opak u2'
    label: int | None            # diagnosis class index or None (not labeled)
    modules: str
    place: str = ""              # real: indoor_lamp / outdoor_sun
    pmax: dict = field(default_factory=dict)
    mlpe: float | None = None
    x_round: np.ndarray | None = None
    x_4s: np.ndarray | None = None

    @property
    def pattern(self):
        """Pattern label index, or None when the modules were not recorded (a non-normal round without modules)."""
        if self.label is None or (not self.modules and CLASSES[self.label] != "normal"):
            return None
        return PATTERNS.index(pattern_of(self.modules))

    @property
    def best(self):
        """Selector label: index of the best of 4S / 2S2P / TCT, or None."""
        if all(self.pmax.get(t) for t in CANDIDATES):
            return int(np.argmax([self.pmax[t] for t in CANDIDATES]))
        return None


def shape_features(v, i):
    """14 shape features exactly as pemilih.h computes them (float32), or None with fewer than 10 valid points."""
    import port_c                                   # on sys.path via shadeshift.inti
    s = protocol.to_sapuan(v, i)
    if len(s.V) < 10:
        return None
    V, I = port_c.cuplik_ulang(s.V, s.I)
    return np.asarray(port_c.fitur_bentuk(V, I), float)


def round_vector(feats, pmax):
    """feats: {topology: 14 features}; pmax: {topology: W}. 59 numbers, or None if a sweep is missing."""
    if any(feats.get(t) is None for t in TOPOS) or not pmax.get("4S"):
        return None
    ratios = [pmax[t] / pmax["4S"] for t in ("2S2P", "TCT", "4P")]
    return np.concatenate([feats[t] for t in TOPOS] + [np.asarray(ratios, float)])


def _example(source, group, day, ref, label, modules, curves, pmax, mlpe=None, place=""):
    feats = {t: shape_features(*curves[t]) for t in TOPOS if t in curves}
    return Example(source=source, group=group, day=day, ref=ref, place=place,
                   label=CLASSES.index(label) if label in CLASSES else None, modules=modules or "",
                   pmax={t: float(p) for t, p in pmax.items() if p}, mlpe=mlpe,
                   x_round=round_vector(feats, pmax), x_4s=feats.get("4S"))


# ---------------- real sessions ----------------
def real_examples(db):
    """Complete rounds of full scans on a real device. Dynamic conditions and rounds whose light changed > 5 % are left
    out (one round must see one shading)."""
    out = []
    for sc in db.query("SELECT sc.*, se.started_at, se.place FROM scans sc JOIN sessions se ON se.id = sc.session_id "
                       "WHERE se.source='device' AND sc.dynamic=0 ORDER BY sc.id"):
        rows = db.query("SELECT topology, repeat, complete, pmax, header_json, points_json FROM sweeps "
                        "WHERE scan_id=? ORDER BY id", (sc["id"],))
        by_rep = {}
        for r in rows:
            if r["complete"] and r["pmax"]:
                by_rep.setdefault(r["repeat"], {})[r["topology"]] = r
        day = fieldwork.local_date(sc["started_at"]).strftime("%Y-%m-%d")
        for rep, by_t in sorted(by_rep.items()):
            if not all(t in by_t for t in TOPOS):
                continue
            heads = [{"header": json.loads(r["header_json"])} for r in by_t.values()]
            light = light_change_pct(heads)
            if light is not None and light > fieldwork.LIGHT_CHANGE_PCT:
                continue
            curves = {t: (json.loads(r["points_json"])["v"], json.loads(r["points_json"])["i"]) for t, r in by_t.items()}
            pmax = {t: r["pmax"] for t, r in by_t.items()}
            panels = [pmax.get(p) for p in protocol.PANELS]
            out.append(_example("real", f"scan{sc['id']}", day, f"{sc['condition']} u{rep}", sc["diagnosis"],
                                sc["modules"], curves, pmax, sum(panels) if all(panels) else None, sc["place"]))
    return out


# ---------------- lab files ----------------
def lab_examples(lab_dir=None):
    lab_dir = Path(lab_dir or inti.DATA_LAB)
    out = []
    for cond, (label, mods, pattern) in LAB.items():
        for rep in (1, 2, 3):
            files = {t: lab_dir / f"{cond}_{t}_u{rep}.csv" for t in TOPOS}
            if not all(f.is_file() for f in files.values()):
                continue
            curves, pmax = {}, {}
            for t, f in files.items():
                s = inti.baca_berkas(str(f))
                curves[t] = (s.V, s.I)
                pmax[t] = s.pmax
            out.append(_example("lab", pattern, "lab", f"{cond} u{rep}", label, mods, curves, pmax))
    return out


# ---------------- simulation ----------------
def sim_examples(n_per_class=200, seed=5, cache_dir=None):
    """Research simulator scenarios (6 classes, measurement noise), cached as JSON per (n, seed, version)."""
    cache = Path(cache_dir) / f"sim_diagnosis_v{SIM_VERSION}_n{n_per_class}_s{seed}.json" if cache_dir else None
    if cache and cache.is_file():
        rows = json.loads(cache.read_text(encoding="utf-8"))
    else:
        rows = _simulate(n_per_class, seed)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(rows), encoding="utf-8")
    return [Example(source="sim", group="sim", day="sim", ref=f"sim {r['k']}", label=r["label"], modules=r["modules"],
                    pmax=r["pmax"], mlpe=r["mlpe"],
                    x_round=np.asarray(r["x_round"]) if r["x_round"] else None,
                    x_4s=np.asarray(r["x_4s"]) if r["x_4s"] else None) for r in rows]


def _simulate(n_per_class, seed):
    if inti.ML not in sys.path:
        sys.path.insert(0, inti.ML)
    from buat_data_diagnosis import KELAS, skenario   # research code, unchanged
    from fitur import sapuan
    from sim_core import PARAMS, simulasi
    assert len(KELAS) == len(CLASSES)                 # same order: normal ... series resistance
    rng = np.random.default_rng(seed)
    rows, k = [], 0
    for c in range(len(KELAS)):
        for _ in range(n_per_class):
            S, mode, nc, G, T, f, ubah = skenario(c, rng)
            for i in range(4):
                if "k" in ubah[i]:
                    ubah[i] = {"R_s": PARAMS[i]["R_s"] * ubah[i]["k"]}
            tp, pw, ml = simulasi(S, mode, nc, G, T, f, ubah)
            curves = {t: sapuan(tp[t], rng) for t in TOPOS}
            pmax = {t: float(np.max(V * I)) for t, (V, I) in curves.items()}
            mods = "".join(m for m, s, u in zip(fieldwork.MODULES, S, ubah) if s > 0 or u)
            e = _example("sim", "sim", "sim", "", CLASSES[c], mods, curves, pmax, ml)
            rows.append({"k": k, "label": c, "modules": mods, "pmax": e.pmax, "mlpe": float(ml),
                         "x_round": e.x_round.tolist() if e.x_round is not None else None,
                         "x_4s": e.x_4s.tolist() if e.x_4s is not None else None})
            k += 1
    return rows


def describe(examples):
    """Counts per source and class, for reports."""
    out = {}
    for e in examples:
        d = out.setdefault(e.source, {"rounds": 0, "by_class": {}, "days": set(), "groups": set(), "places": {}})
        if e.place:
            d["places"][e.place] = d["places"].get(e.place, 0) + 1
        d["rounds"] += 1
        name = CLASSES[e.label] if e.label is not None else "unlabeled"
        d["by_class"][name] = d["by_class"].get(name, 0) + 1
        d["days"].add(e.day)
        d["groups"].add(e.group)
    return {s: {**d, "days": sorted(d["days"]), "groups": len(d["groups"])} for s, d in out.items()}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")
