"""Shared helpers for the firmware host tests: compile an unchanged sketch with g++ against tests/firmware_host and run it.

TEST ONLY. The simulated hardware replays REAL lab curves (see tests/firmware_host/arduino_stub.h); this checks the
firmware's logic and output format on the laptop, not the board itself.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT
from shadeshift import inti

HOST = ROOT / "tests" / "firmware_host"
FIRMWARE = ROOT / "firmware"
LAB = Path(inti.DATA_LAB)
MSYS = Path(r"C:\msys64\ucrt64\bin")
ENV = {**os.environ, "PATH": f"{MSYS}{os.pathsep}{os.environ.get('PATH', '')}"}
TOPOLOGIES = ("4S", "2S2P", "TCT", "4P")


def compiler(name):
    found = shutil.which(name, path=ENV["PATH"])
    if not found:
        pytest.skip(f"{name} not found (MSYS2 ucrt64); firmware host tests skipped")
    return found


def compile_sketch(sketch_dir, ino, out, bench=False, web=False, include=None):
    """g++ build of <sketch_dir>/<ino> with the host stand-ins; the sketch must compile without warnings.
    include: an extra folder searched first (e.g. one holding a diagnosis_model.h for the test)."""
    cmd = [compiler("g++"), "-std=c++17", "-O1", "-Wall", "-Wextra", "-Wno-unused-parameter",
           *([f"-I{include}"] if include else []), f"-I{sketch_dir}", f"-I{HOST}", f'-DSKETCH="{ino}"',
           *(["-DSIM_ADA_BENCH"] if bench else []), *(["-DSIM_ADA_WEB"] if web else []),
           str(HOST / "sim_main.cpp"), "-o", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr, r.stderr
    return out


def lab_files(condition, repeat=1):
    return [str(LAB / f"{condition}_{t}_u{repeat}.csv") for t in TOPOLOGIES]


def run(sim, files, script):
    """script: [(t_ms, line)], where line is a firmware command or a '##CAHAYA <V>' simulation directive."""
    r = subprocess.run([str(sim), *files], input="".join(f"{t} {c}\n" for t, c in script),
                       capture_output=True, text=True, env=ENV, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def final(out):
    return dict(kv.split("=") for kv in re.search(r"^##SIM \S+ (.*)$", out, re.M).group(1).split())


def device_lines(out):
    """Firmware output only (simulation '##' lines removed)."""
    return [ln for ln in out.splitlines() if not ln.startswith("##")]


def http_responses(out):
    """[(code, method, path, type, body)] from the '##HTTP' blocks of a simulation run."""
    pat = r"^##HTTP (\d+) (\S+) (\S+) (\S+)\n(.*?)\n##HTTP-END$"
    return [(int(m[1]), m[2], m[3], m[4], m[5]) for m in re.finditer(pat, out, re.M | re.S)]
