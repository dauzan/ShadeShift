"""Firmware serial protocol (CONTRACT.md §3): sweep blocks, header values, v3 additions, completeness.

Rows are kept exactly as received; only lines that are not three numeric fields are dropped, as in the lab
scripts. Derived values (Pmax, Vmp, Imp, Voc, Isc) use the lab rules of shadeshift.inti.Sapuan (CONTRACT §6.3),
so they always match the reported lab numbers.
"""
import re
from dataclasses import dataclass, field

import numpy as np

from shadeshift import inti

TOPOLOGIES = ("4S", "2S2P", "TCT", "4P")
_BAD_LABEL_CHARS = re.compile(r"[^A-Za-z0-9_.\-]")
_NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_RE_HEADER = re.compile(rf"topologi=(?P<topo>[0-9A-Z?]+).*?Voc=(?P<voc>{_NUM})")
_RE_DAC = re.compile(r"dac=(?P<lo>\d+)\.\.(?P<hi>\d+)")
_RE_N = re.compile(r"\bN=(?P<n>\d+)")
_RE_TRAILER = re.compile(rf"Pmax=(?P<pmax>{_NUM}).*?Vmp=(?P<vmp>{_NUM}).*?Imp=(?P<imp>{_NUM})")
_RE_META = re.compile(r"#\s*meta\b(?P<rest>.*)")
_RE_DECISION = re.compile(rf"pemilih=(?P<choice>4S|2S2P|TCT)(?:.*?skor=(?P<scores>[-+0-9.eE;]+))?(?:.*?t_us=(?P<t_us>{_NUM}))?")
_RE_REPLAY = re.compile(r"#\s*tiruan\s+berkas=(?P<file>\S+)")       # written by the emulator (shadeshift.koneksi.ESPTiruan)


def sanitize_label(label, default="tanpa_label"):
    label = _BAD_LABEL_CHARS.sub("_", (label or "").strip())[:80]
    return label or default


def topology_from_label(label):
    t = inti.topologi_dari_label(label or "")
    return t if t in TOPOLOGIES else "?"


def condition_from_name(name):
    """'V3_paranet65_TCT_u2(.csv)' -> ('V3_paranet65', 'TCT', 2); otherwise (None, None, None)."""
    m = re.match(r"(.+)_(4S|2S2P|TCT|4P)_u(\d+)(?:\.csv)?$", name or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m else (None, None, None)


@dataclass
class ParsedSweep:
    label: str
    topology: str
    v: list
    i: list
    header: dict = field(default_factory=dict)
    device_meta: dict = field(default_factory=dict)
    device_decision: dict | None = None
    ended: bool | None = None          # saw '# SELESAI'; None for formats without block markers
    raw_text: str = ""
    replay_of: str | None = None       # lab file named by an emulator's '# tiruan berkas=...' line

    @property
    def complete(self):
        n = self.header.get("n")
        return self.ended is not False and (n is None or len(self.v) == n + 1)


def parse_block(lines, label=None):
    """Lines of one sweep block (or of a whole lab/logger CSV file) -> ParsedSweep."""
    lines = [ln.rstrip("\r\n") for ln in lines]
    v, i, header, meta, decision, replay_of = [], [], {}, {}, None, None
    topo, ended, has_markers = None, False, False
    for ln in lines:
        s = ln.strip()
        if s.startswith("# MULAI"):
            has_markers = True
            label = label or s[len("# MULAI"):].strip()
        elif s.startswith("# SELESAI"):
            has_markers = True
            ended = True
        elif s.startswith("#"):
            m = _RE_HEADER.search(s)
            if m:
                topo = m.group("topo")
                header["voc"] = float(m.group("voc"))
                if (d := _RE_DAC.search(s)):
                    header["dac_lo"], header["dac_hi"] = int(d.group("lo")), int(d.group("hi"))
                if (n := _RE_N.search(s)):
                    header["n"] = int(n.group("n"))
            if (t := _RE_TRAILER.search(s)):
                header.update(pmax=float(t.group("pmax")), vmp=float(t.group("vmp")), imp=float(t.group("imp")))
            if (mm := _RE_META.match(s)):
                for key, val in re.findall(r"(\w+)=([-+0-9.]+)", mm.group("rest")):
                    meta[{"t_ms": "uptime_ms"}.get(key, key)] = int(float(val))
            if (dm := _RE_DECISION.search(s)):
                scores = [float(x) for x in dm.group("scores").split(";")] if dm.group("scores") else None
                decision = {"choice": dm.group("choice"), "scores": scores,
                            "latency_us": float(dm.group("t_us")) if dm.group("t_us") else None}
            if (rm := _RE_REPLAY.match(s)):
                replay_of = rm.group("file")
        else:
            p = s.split(",")
            if len(p) != 3 or p[0] == "V":
                continue
            try:
                vv, ii = float(p[0]), float(p[1])
            except ValueError:
                continue
            v.append(vv)
            i.append(ii)
    label = sanitize_label(label)
    topology = topo if topo in TOPOLOGIES else topology_from_label(label)
    return ParsedSweep(label=label, topology=topology, v=v, i=i, header=header, device_meta=meta,
                       device_decision=decision, ended=ended if has_markers else None, raw_text="\n".join(lines),
                       replay_of=replay_of)


def split_blocks(text):
    """Text that may hold several '# MULAI ... # SELESAI' blocks -> list of line lists.
    Without '# MULAI' the whole text is one block. A block cut off before '# SELESAI' is kept (incomplete)."""
    lines = text.splitlines()
    if not any(ln.strip().startswith("# MULAI") for ln in lines):
        return [lines] if any(ln.strip() for ln in lines) else []
    blocks, current = [], None
    for ln in lines:
        s = ln.strip()
        if s.startswith("# MULAI"):
            if current:
                blocks.append(current)
            current = [ln]
        elif current is not None:
            current.append(ln)
            if s.startswith("# SELESAI"):
                blocks.append(current)
                current = None
    if current:
        blocks.append(current)
    return blocks


def to_sapuan(v, i, label="tanpa_label", topology="?", header_voc=None):
    """Raw points -> inti.Sapuan with exactly the rules of inti.urai_baris: V <= 0 dropped, I clipped >= 0."""
    a = np.array([v, i], dtype=float).T.reshape(-1, 2)
    a = a[a[:, 0] > 0]
    return inti.Sapuan(label=label, topologi=topology, V=a[:, 0], I=np.clip(a[:, 1], 0, None),
                       voc_header=float("nan") if header_voc is None else float(header_voc))


def derive(v, i, header_voc=None):
    """Derived values for storage and display (CONTRACT §6.3)."""
    s = to_sapuan(v, i, header_voc=header_voc)

    def clean(x):
        return None if x is None or not np.isfinite(x) else round(float(x), 6)

    valid = len(s.V) >= 2
    return {"n_points": len(v), "n_valid": int(len(s.V)),
            "voc": clean(s.voc) if len(s.V) else clean(header_voc),
            "isc": clean(s.isc) if len(s.I) else None,
            "pmax": clean(s.pmax) if valid else None,
            "vmp": clean(s.vmp) if valid else None,
            "imp": clean(s.imp) if valid else None}


def to_firmware_csv(label, topology, v, i, header=None):
    """Points -> the firmware/logger file format (CONTRACT §6.1), so exports can be uploaded again."""
    header = header or {}
    voc = header.get("voc", max(v) if v else 0.0)
    head = f"# topologi={topology}, Voc={voc:.3f} V"
    if "dac_lo" in header and "dac_hi" in header:
        head += f", dac={header['dac_lo']}..{header['dac_hi']}"
    head += f", N={header.get('n', max(len(v) - 1, 0))}"
    rows = [f"# MULAI {label}", head, "V,I,P"] + [f"{a:.4f},{b:.5f},{a * b:.4f}" for a, b in zip(v, i)]
    d = derive(v, i, header.get("voc"))
    if d["pmax"] is not None:
        rows.append(f"# Pmax={d['pmax']:.4f} W, Vmp={d['vmp']:.3f} V, Imp={d['imp']:.4f} A")
    rows.append("# SELESAI")
    return "\n".join(rows) + "\n"
