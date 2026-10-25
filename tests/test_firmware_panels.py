"""The firmware (3.2): single-panel sweeps A-D, the LDR light sensor and INFO, and the same measurements as the
original v2, checked on this laptop.

The current sketch and the ORIGINAL v2 (the untouched copy in docs/before/firmware/, compiled read-only) are built with
g++ against tests/firmware_host. The 4 topologies replay REAL lab curves. There are no single-panel lab recordings yet,
so the panel curves here are SYNTHETIC (the lab 4P curve with the current divided by 4, i.e. one average panel); they test
the relay masks, the safe switch and the output format, not the panels.
"""
import re

import pytest

from conftest import ROOT
from firmware_sim import FIRMWARE, compile_sketch, device_lines, final, lab_files, run
from shadeshift import commands, inti, protocol
from shadeshift.gateway.main import RE_INFO, firmware_label

NOW = FIRMWARE / "shadeshift_firmware"
V2 = ROOT / "docs" / "before" / "firmware" / "shadeshift_firmware"


@pytest.fixture(scope="module")
def sims(tmp_path_factory):
    out = tmp_path_factory.mktemp("fwpanel")
    return {"v2": compile_sketch(V2, "shadeshift_firmware.ino", out / "v2.exe"),
            "now": compile_sketch(NOW, "shadeshift_firmware.ino", out / "now.exe", bench=True, web=True)}


def _panel_file(tmp_path, name, scale=0.25, voc=None):
    """SYNTHETIC single-panel curve: the V1c 4P lab curve with I x scale (and optionally a different Voc)."""
    s = inti.baca_berkas(lab_files("V1c")[3])
    v = s.V if voc is None else s.V * voc / s.voc
    path = tmp_path / f"{name}.csv"
    rows = [f"# topologi={name}, Voc={(s.voc if voc is None else voc):.3f} V", "V,I,P"]
    rows += [f"{a:.4f},{b * scale:.5f},{a * b * scale:.4f}" for a, b in zip(v, s.I)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def files8(tmp_path):
    return lab_files("V1c") + [_panel_file(tmp_path, p) for p in protocol.PANELS]


ADDED = ("# cahaya", "# INFO", "# meta ", "# pemilih=", "# WEB ")      # lines the new firmware adds to v2's output


def _as_v2_sees_it(lines):
    """The new firmware's output with its additions removed: v2 tools ignore unknown '#' lines and the STATUS suffix."""
    return [re.sub(r", bench=\w+, fw=[\d.]+$", "", ln) for ln in lines if not ln.startswith(ADDED)]


def test_v2_commands_give_the_same_measurements(sims, files8):
    script = [(1000, "TCT"), (2500, "SWEEP sama"), (10000, "VOC"), (10500, "STATUS"), (10800, "4S"), (12000, "SWEEP sama4"),
              (20000, "PANTAU 1"), (20100, "PANTAU 0"), (20500, "STOP")]
    v2 = run(sims["v2"], files8[:4], script)
    now = run(sims["now"], files8, script)
    after_boot = lambda out: device_lines(out[out.index("##RX "):])              # boot banners differ (version)
    assert _as_v2_sees_it(after_boot(now)) == after_boot(v2)
    assert {k: v for k, v in final(now).items() if k != "t_ms"} == {k: v for k, v in final(v2).items() if k != "t_ms"}


@pytest.mark.parametrize("panel", protocol.PANELS)
def test_single_panel_switch_and_sweep(sims, files8, panel):
    out = run(sims["now"], files8, [(1000, panel), (2500, f"SWEEP uji_{panel}"), (10000, "STATUS")])
    lines = device_lines(out)
    assert f"# siap: {panel}" in lines
    assert any(ln.startswith(f"# topologi={panel}, R0=tutup") for ln in lines)
    f = final(out)
    assert f["topologi"] == panel and f["R0"] == "1"           # the independent relay map sees exactly this panel
    p = protocol.parse_block(protocol.split_blocks("\n".join(lines))[0])
    assert p.topology == panel and p.label == f"uji_{panel}" and p.complete
    d = protocol.derive(p.v, p.i, p.header.get("voc"))
    assert 10 < d["voc"] < 25 and d["pmax"] > 0               # one panel, not the array


def test_panel_with_no_voltage_is_refused(sims, tmp_path):
    files = lab_files("V1c") + [_panel_file(tmp_path, "A"), _panel_file(tmp_path, "B"),
                                _panel_file(tmp_path, "C", voc=0.4), _panel_file(tmp_path, "D")]
    out = run(sims["now"], files, [(1000, "C"), (2500, "SWEEP tidak_boleh")])
    lines = device_lines(out)
    assert any(ln.startswith("# GAGAL: Voc di luar 10-25 V") for ln in lines)
    assert "# siap: C" not in lines and not any(ln.startswith("# MULAI") for ln in lines)
    assert final(out)["R0"] == "0"


def test_light_sensor_lines_and_change_during_sweep(sims, files8):
    out = run(sims["now"], files8, [(0, "##CAHAYA 2.000"), (1000, "4S"), (2500, "SWEEP terang"), (2800, "##CAHAYA 0.500"),
                                    (10000, "CAHAYA")])
    lines = device_lines(out)
    p = protocol.parse_block(protocol.split_blocks("\n".join(lines))[0])
    assert p.header["light_v"] == pytest.approx(2.0, abs=0.002)
    assert p.header["light_end_v"] == pytest.approx(0.5, abs=0.002)    # the light changed during this sweep
    assert lines[-1] == "# cahaya=0.500 V"
    i = next(k for k, ln in enumerate(lines) if ln.startswith("# topologi=4S"))
    assert lines[i + 1] == "# cahaya=2.000 V"


def test_info_and_status_identify_the_firmware(sims, files8):
    out = run(sims["now"], files8, [(1000, "INFO"), (1100, "STATUS")])
    lines = device_lines(out)
    assert "# SHADESHIFT firmware 3.2.0" in lines                # boot banner names the version
    info = [ln for ln in lines if ln.startswith("# INFO")]
    assert len(info) == 2                                      # printed at boot and on request
    m = RE_INFO.match(info[-1])
    assert m and m["fw"] == "3.2.0" and {"panel", "cahaya"} <= set(m["fitur"].split(","))
    assert firmware_label(m["fw"]) == "v3.2 (3.2.0)" and firmware_label("3.0.0") == "v3 (3.0.0)"
    assert re.search(r"^# topologi=-, R0=buka, cekVoc=ON, bench=OFF, fw=3\.2\.0$", out, re.M)


def test_siklus_still_runs_only_the_four_topologies(sims, files8):
    out = run(sims["now"], files8, [(1000, "SIKLUS uji 1"), (1100, "LANJUT")])
    labels = [ln for ln in device_lines(out) if ln.startswith("# MULAI")]
    assert sorted(re.search(r"_(\w+?)_u1$", ln).group(1) for ln in labels) == sorted(protocol.TOPOLOGIES)


def test_api_allows_panels_and_cahaya():
    assert [commands.validate_raw(c) for c in ("a", "B", "cahaya", "info")] == ["A", "B", "CAHAYA", "INFO"]
    assert commands.is_actuating("raw", "A") and not commands.is_actuating("raw", "CAHAYA")
    assert commands.validate_action("cycle", {"topologies": ["A", "B", "C", "D"]})["topologies"] == ["A", "B", "C", "D"]
    with pytest.raises(commands.CommandError):
        commands.validate_action("cycle", {"topologies": ["E"]})
