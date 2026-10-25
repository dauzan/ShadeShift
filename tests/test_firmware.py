"""The firmware (3.2): on-board selector (TinyML, Stage 6) and safety, checked on this laptop.

The unchanged sketch is compiled with g++ against small Arduino stand-ins (tests/firmware_host) whose simulated hardware
replays REAL lab curves. This proves the firmware's logic, output format and the C model; it does NOT replace running
on the board (see firmware/CARA_PAKAI.md).
"""
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from conftest import ROOT
from firmware_sim import ENV, FIRMWARE, HOST, LAB, compile_sketch, compiler, final, lab_files, run
from shadeshift import inti, protocol
from shadeshift.edge.selector import EdgeSelector

SKETCH = FIRMWARE / "shadeshift_firmware"


@pytest.fixture(scope="module")
def build(tmp_path_factory):
    out = tmp_path_factory.mktemp("fw")
    sim = compile_sketch(SKETCH, "shadeshift_firmware.ino", out / "sim.exe", bench=True, web=True)
    cli = out / "pemilih_cli.exe"
    r = subprocess.run([compiler("gcc"), "-std=c11", "-O1", "-Wall", "-Wno-unused-function", f"-I{SKETCH}",
                        str(HOST / "pemilih_cli.c"), "-o", str(cli)], capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr, r.stderr                        # the firmware compiles cleanly
    return sim, cli


def run_sim(build, condition, script, repeat=1, files=None):
    return run(build[0], files or lab_files(condition, repeat), script)


def test_sketch_uses_the_current_model_files():
    for name in ("pemilih.h", "pemilih_bobot.h"):
        assert (SKETCH / name).read_bytes() == (Path(inti.PEMILIH) / name).read_bytes(), name


def test_info_fingerprint_equals_laptop_model_id(build):
    out = run_sim(build, "V1c", [(0, "INFO")])
    w = re.search(r"# INFO fw=3\.2\.0, id=\w+, n=201, w=([0-9a-f]{12}), fitur=panel,cahaya,pemilih,web$", out, re.M).group(1)
    assert w == EdgeSelector(runtime="numpy").model_id.split("@")[1]


def test_c_model_equals_onnx_on_all_38_lab_curves(build):
    sel = EdgeSelector(runtime="auto", model_path=ROOT / "models" / "pemilih.onnx")
    curves = sorted(LAB.glob("*_4S_u*.csv")) + sorted((LAB / "_V5_anomali_dioda").glob("*_4S_u*.csv"))
    assert len(curves) == 38
    parsed = [protocol.parse_block(p.read_text(encoding="utf-8").splitlines()) for p in curves]
    stdin = "".join(f"{len(p.v)}\n" + "".join(f"{v!r} {i!r}\n" for v, i in zip(p.v, p.i)) for p in parsed)
    r = subprocess.run([str(build[1])], input=stdin, capture_output=True, text=True, env=ENV, timeout=60)
    assert r.returncode == 0, r.stderr
    rows = [list(map(float, ln.split())) for ln in r.stdout.splitlines()]
    for path, p, row in zip(curves, parsed, rows):
        d = sel.decide(p.v, p.i)
        assert ["4S", "2S2P", "TCT"][int(row[0])] == d.choice, path.name
        assert np.max(np.abs(np.array(row[1:4]) - d.scores)) <= 1e-4, path.name
        assert np.max(np.abs(np.array(row[4:]) - d.features)) <= 1e-4, path.name


@pytest.mark.parametrize("condition, repeat, expected", [("V6_paranet65", 1, "TCT"), ("V3_paranet65", 1, "4S"),
                                                         ("V4_paranet65", 3, "TCT"), ("V1c", 1, "TCT")])
def test_pilih_decides_on_board_and_switches(build, condition, repeat, expected):
    out = run_sim(build, condition, [(0, "PILIH")], repeat)
    blocks = [protocol.parse_block(b) for b in protocol.split_blocks(out)]
    assert blocks[0].topology == "4S" and blocks[0].complete
    dd = blocks[0].device_decision
    assert dd["choice"] == expected and len(dd["scores"]) == 3 and dd["latency_us"] is not None
    # The ESP32 decides on exactly the numbers it prints, so the laptop recomputes the same decision from the log
    # (scores are printed with 4 decimals).
    lap = EdgeSelector(runtime="numpy").decide(blocks[0].v, blocks[0].i)
    assert lap.choice == expected and np.max(np.abs(np.array(lap.scores) - dd["scores"])) <= 6e-5
    assert blocks[0].device_meta["seq"] == 1
    assert f"# PILIH SELESAI: {expected}" in out
    assert len(blocks) == (1 if expected == "4S" else 2)
    assert final(out)["topologi"] == expected and final(out)["R0"] == "1"


def test_off_stops_siklus_between_steps(build):
    out = run_sim(build, "V1c", [(0, "SIKLUS uji 2"), (100, "LANJUT"), (6000, "OFF")])
    assert "# siklus dihentikan (OFF)" in out
    assert 1 <= len(protocol.split_blocks(out)) < 4
    f = final(out)
    assert f["R0"] == "0" and f["topologi"] == "-" and f["dac"] == "0"


def test_off_at_the_lanjut_prompt_cancels(build):
    out = run_sim(build, "V1c", [(0, "SIKLUS uji 1"), (100, "OFF")])
    assert "# siklus dibatalkan" in out and "# MULAI" not in out
    assert final(out)["R0"] == "0"


def test_off_stops_pilih(build):
    out = run_sim(build, "V6_paranet65", [(0, "PILIH"), (1000, "OFF")])
    assert "# PILIH dihentikan" in out and "PILIH SELESAI" not in out
    assert len(protocol.split_blocks(out)) == 1                    # the 4S sweep finishes, then everything opens
    assert final(out)["R0"] == "0" and final(out)["topologi"] == "-"


def test_failed_sweep_stops_siklus(build, tmp_path):
    dim = tmp_path / "redup.csv"                                   # SYNTHETIC: a curve below the 5 mA detection threshold
    dim.write_text("V,I,P\n" + "".join(f"{v:.3f},{0.003 * (1 - (v / 70) ** 8):.5f},0\n" for v in np.linspace(0.5, 70, 50)))
    out = run_sim(build, None, [(0, "CEKVOC 0"), (50, "SIKLUS redup 1"), (150, "LANJUT")], files=[str(dim)] * 4)
    assert "# GAGAL: arus tidak terdeteksi" in out and "# siklus dihentikan (sweep gagal)" in out
    assert final(out)["R0"] == "0"


def test_bench_mode_guards_relai_and_dac(build):
    out = run_sim(build, "V1c", [(0, "RELAI 6 1"), (100, "DAC 4095"), (200, "UJIRELAI"), (300, "4S"),
                                 (1500, "BENCH 1"), (1600, "OFF"), (1700, "BENCH 1"), (1800, "DAC -1"),
                                 (1900, "DAC 4096"), (2000, "RELAI 6 1"), (2100, "OFF")])
    assert out.count("hanya dalam mode uji bangku TANPA PANEL") == 3   # RELAI, DAC, UJIRELAI refused without BENCH
    assert "# GAGAL: ketik OFF dulu" in out                             # BENCH refused while a topology is active
    assert out.count("# format: DAC <0-4095>") == 2                     # -1 and 4096 rejected
    assert "# R6 NYALA" in out
    f = final(out)
    assert f["bench"] == "0" and f["R0"] == "0"                         # OFF ends bench mode and opens everything


def test_v2_commands_and_output_format_unchanged(build):
    out = run_sim(build, "V1c", [(0, "TCT"), (1500, "SWEEP v3_cek"), (8000, "VOC"), (8500, "STATUS"), (9000, "STOP")])
    assert "# siap: TCT" in out and "# SELESAI" in out
    p = protocol.parse_block(protocol.split_blocks(out)[0])
    assert p.label == "v3_cek" and p.topology == "TCT" and p.complete and p.header["n"] == 201
    assert p.device_decision is None                                    # the selector only runs on 4S sweeps
    assert re.search(r"# V_array = \d+\.\d+ V", out)
    assert "# topologi=TCT, R0=tutup" in out                           # the gateway's STATUS regex still matches
    s = inti.urai_baris(protocol.split_blocks(out)[0])                 # the old dashboard parser still reads v3 blocks
    assert s.topologi == "TCT" and len(p.v) == 202 and len(s.V) == sum(v > 0 for v in p.v)
