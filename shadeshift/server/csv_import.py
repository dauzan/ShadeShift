"""Parsing and validation of uploaded sweep files and of the lab dataset (docs/CONTRACT.md §5.5, §6).

Two formats are accepted:
- the firmware/logger format (lines starting with '#', header row 'V,I,P'), possibly with several sweep blocks;
- a plain CSV with a header row naming the V and I columns (I in A, or in mA when the header says so).
"""
import math
import re
from dataclasses import dataclass
from pathlib import PurePath

from shadeshift import protocol

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 50
MIN_VALID_POINTS = 10
V_RANGE = (-1.0, 200.0)
I_RANGE = (-0.5, 10.0)


class Rejected(ValueError):
    """The file cannot be stored; the message is shown to the user."""


@dataclass
class FileSweep:
    parsed: protocol.ParsedSweep
    topology: str
    condition: str | None
    repeat: int | None


def decode(data):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _is_firmware_format(text):
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            return True
        return s.replace(" ", "").upper() == "V,I,P"
    return False


def _unit_is_milliamp(header_cell):
    return re.search(r"(^|[^a-z])ma([^a-z]|$)", header_cell) is not None


def _find_columns(cells):
    v_col = i_col = None
    milli = False
    for k, raw in enumerate(cells):
        h = raw.strip().lower()
        if v_col is None and (h in ("v", "voltage", "tegangan") or re.match(r"^(v[\s(\[_]|voltage|tegangan)", h)):
            v_col = k
        elif i_col is None and (h in ("i", "current", "arus") or re.match(r"^(i[\s(\[_]|current|arus)", h)):
            i_col, milli = k, _unit_is_milliamp(h)
    return v_col, i_col, milli


def _parse_plain(text, label):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise Rejected("empty file")
    head = lines[0]
    sep = ";" if head.count(";") > head.count(",") else ","
    v_col, i_col, milli = _find_columns(head.split(sep))
    if v_col is None or i_col is None:
        raise Rejected(f"need a header row with V and I columns (e.g. 'V,I' or 'V,I_mA'); found: {head[:80]!r}")
    v, i = [], []
    for row_no, ln in enumerate(lines[1:], start=2):
        cells = ln.split(sep)
        try:
            vv, ii = float(cells[v_col]), float(cells[i_col])
        except (IndexError, ValueError):
            raise Rejected(f"row {row_no}: V and I must be numbers with a decimal point, got {ln[:60]!r}") from None
        v.append(vv)
        i.append(ii / 1000.0 if milli else ii)
    return protocol.ParsedSweep(label=label, topology=protocol.topology_from_label(label), v=v, i=i,
                                ended=None, raw_text=text)


def _validate(p):
    if any(not math.isfinite(x) for x in p.v + p.i):
        raise Rejected("contains NaN or infinite values")
    valid = sum(1 for x in p.v if x > 0)
    if valid < MIN_VALID_POINTS:
        raise Rejected(f"only {valid} valid points (need >= {MIN_VALID_POINTS} with V > 0)")
    if min(p.v) < V_RANGE[0] or max(p.v) > V_RANGE[1]:
        raise Rejected(f"voltage outside {V_RANGE[0]}..{V_RANGE[1]} V (min {min(p.v):.2f}, max {max(p.v):.2f})")
    if min(p.i) < I_RANGE[0] or max(p.i) > I_RANGE[1]:
        raise Rejected(f"current outside {I_RANGE[0]}..{I_RANGE[1]} A (min {min(p.i):.4f}, max {max(p.i):.4f}); "
                       "if the file is in mA, name the column I_mA")


def parse_file(filename, data, topology=None, condition=None):
    """Bytes of one file -> list[FileSweep]. Raises Rejected with a user-facing reason."""
    if len(data) > MAX_FILE_BYTES:
        raise Rejected(f"file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    text = decode(data)
    stem = PurePath(filename or "upload.csv").stem
    name_cond, name_topo, name_repeat = protocol.condition_from_name(stem)
    if _is_firmware_format(text):
        blocks = protocol.split_blocks(text)
        sweeps = [protocol.parse_block(b, label=None if any(x.strip().startswith("# MULAI") for x in b) else stem)
                  for b in blocks]
    else:
        sweeps = [_parse_plain(text, protocol.sanitize_label(stem))]
    if not sweeps:
        raise Rejected("no sweep data found")
    out = []
    for p in sweeps:
        _validate(p)
        topo = topology or (p.topology if p.topology != "?" else None) or name_topo or "?"
        cond, rep = protocol.condition_from_name(p.label)[0::2]
        out.append(FileSweep(parsed=p, topology=topo, condition=condition or cond or name_cond,
                             repeat=rep if rep is not None else name_repeat))
    return out
