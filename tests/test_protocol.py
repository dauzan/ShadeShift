"""Firmware protocol parser (shadeshift/protocol.py) against the existing lab rules (shadeshift/inti.py)."""
from pathlib import Path

import numpy as np
import pytest

from shadeshift import inti, protocol

LAB = Path(inti.DATA_LAB)
ALL_LAB_FILES = sorted(LAB.rglob("*.csv"))


def test_lab_dataset_is_present():
    assert len(ALL_LAB_FILES) == 154                 # 120 main + 34 in the V5/V1d subfolders


@pytest.mark.parametrize("path", ALL_LAB_FILES, ids=lambda p: p.name)
def test_derived_values_equal_lab_rules(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    p = protocol.parse_block(lines)
    d = protocol.derive(p.v, p.i, p.header.get("voc"))
    ref = inti.baca_berkas(str(path))
    assert p.topology == ref.topologi
    assert d["pmax"] == pytest.approx(ref.pmax, abs=1e-6)
    assert d["vmp"] == pytest.approx(ref.vmp, abs=1e-5)
    assert d["voc"] == pytest.approx(ref.voc, abs=1e-6)
    assert d["isc"] == pytest.approx(ref.isc, abs=1e-6)
    assert d["n_valid"] == len(ref.V)


def test_completeness_flags_the_damaged_lab_file():
    bad = protocol.parse_block((LAB / "V3_paranet75_TCT_u2.csv").read_text(encoding="utf-8").splitlines())
    good = protocol.parse_block((LAB / "V1c_4S_u1.csv").read_text(encoding="utf-8").splitlines())
    assert good.complete and good.header["n"] == 201 and len(good.v) == 202
    assert not bad.complete and len(bad.v) < 202
    complete = [protocol.parse_block(p.read_text(encoding="utf-8").splitlines()).complete for p in ALL_LAB_FILES]
    assert complete.count(False) == 1


def test_block_without_selesai_is_incomplete():
    lines = (LAB / "V1c_4S_u1.csv").read_text(encoding="utf-8").splitlines()
    assert not protocol.parse_block([ln for ln in lines if not ln.startswith("# SELESAI")]).complete


def test_header_and_trailer_values():
    p = protocol.parse_block((LAB / "V1c_4S_u1.csv").read_text(encoding="utf-8").splitlines())
    assert p.label == "V1c_4S_u1" and p.topology == "4S"
    assert p.header == {"voc": 73.553, "dac_lo": 2016, "dac_hi": 2304, "n": 201, "pmax": 1.0211, "vmp": 55.618, "imp": 0.0184}


def test_v3_lines_are_parsed():
    # SYNTHETIC firmware v3 output (CONTRACT §3.3); no real v3 firmware has run yet.
    lines = ["# MULAI auto_1_4S", "# meta t_ms=123456, seq=17", "# topologi=4S, Voc=70.000 V, dac=10..20, N=3", "V,I,P",
             "70.0,0.0,0.0", "60.0,0.01,0.6", "30.0,0.02,0.6", "1.0,0.021,0.021",
             "# pemilih=TCT, skor=0.12;-1.85;0.97, t_us=850", "# SELESAI"]
    p = protocol.parse_block(lines)
    assert p.device_meta == {"uptime_ms": 123456, "seq": 17}
    assert p.device_decision == {"choice": "TCT", "scores": [0.12, -1.85, 0.97], "latency_us": 850.0}
    assert p.complete


def test_split_blocks_and_round_trip():
    a = (LAB / "V1c_4S_u1.csv").read_text(encoding="utf-8")
    b = (LAB / "V6_paranet65_TCT_u2.csv").read_text(encoding="utf-8")
    blocks = protocol.split_blocks("# boot banner\n" + a + "noise line\n" + b)
    assert [protocol.parse_block(x).label for x in blocks] == ["V1c_4S_u1", "V6_paranet65_TCT_u2"]
    p = protocol.parse_block(a.splitlines())
    again = protocol.parse_block(protocol.to_firmware_csv(p.label, p.topology, p.v, p.i, p.header).splitlines())
    assert np.allclose(again.v, p.v) and np.allclose(again.i, p.i)
    assert protocol.derive(again.v, again.i, again.header["voc"])["pmax"] == pytest.approx(
        protocol.derive(p.v, p.i, p.header["voc"])["pmax"], abs=1e-6)


def test_labels_and_names():
    assert protocol.sanitize_label("auto 10:15/4S") == "auto_10_15_4S"
    assert protocol.sanitize_label("") == "tanpa_label"
    assert protocol.condition_from_name("V3_paranet65_TCT_u2.csv") == ("V3_paranet65", "TCT", 2)
    assert protocol.condition_from_name("auto_101530_4S") == (None, None, None)
    assert protocol.topology_from_label("auto_101530_4S") == "4S"
    assert protocol.topology_from_label("whatever") == "?"
