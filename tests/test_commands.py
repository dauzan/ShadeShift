"""Raw-command allowlist and action validation (CONTRACT §5.3, PLAN Decision 11)."""
import pytest

from shadeshift import commands as C


@pytest.mark.parametrize("raw, normalized", [
    ("4s", "4S"), ("tct", "TCT"), ("off", "OFF"), ("STOP", "STOP"), ("status", "STATUS"), ("cekvoc 1", "CEKVOC 1"),
    ("pantau 0", "PANTAU 0"), ("SWEEP auto 1", "SWEEP auto_1"), ("SWEEP", "SWEEP dasbor"), ("VPANEL 17", "VPANEL 17"),
    ("vpanel 21.5", "VPANEL 21.5"), ("info", "INFO"), ("TAHAN 0", "TAHAN 0"),
])
def test_allowed_raw(raw, normalized):
    assert C.validate_raw(raw) == normalized


def test_stop_and_actuating_classes():
    assert C.is_stop("raw", "OFF") and C.is_stop("raw", "STOP") and C.is_stop("action", "stop")
    assert C.is_stop("action", "auto_mode_stop") and not C.is_stop("raw", "4S")
    assert C.is_actuating("raw", "TCT") and C.is_actuating("raw", "SWEEP x") and C.is_actuating("action", "cycle")
    assert not C.is_actuating("raw", "STATUS") and not C.is_actuating("action", "stop")


@pytest.mark.parametrize("raw", ["RELAI 6 1", "relai 0 1", "UJIRELAI", "DAC 4095", "dac -1", "CEKVOC 0", "cekvoc   0",
                                 "SIKLUS V3_opak 3", "LANJUT", "BATAL", "BENCH 1", "TAHAN 1", "tahan 1"])
def test_blocked_raw_has_reason(raw):
    with pytest.raises(C.CommandError, match="blocked"):
        C.validate_raw(raw)


@pytest.mark.parametrize("raw", ["", "PANTAU", "VPANEL", "VPANEL 3", "VPANEL 50", "HELLO", "4S\nOFF", "X" * 65])
def test_rejected_raw(raw):
    with pytest.raises(C.CommandError):
        C.validate_raw(raw)


def test_actions():
    assert C.validate_action("auto_select", {}) == {}
    assert C.validate_action("auto_mode_start", {"interval_s": 10, "trigger_pct": 20, "hold_s": 30}) == \
        {"interval_s": 10.0, "trigger_pct": 20.0, "hold_s": 30.0}
    assert C.validate_action("cycle", {"label": "uji A", "repeats": 2}) == \
        {"label": "uji_A", "repeats": 2, "topologies": ["4S", "2S2P", "TCT", "4P"]}
    assert C.validate_action("demo_scenario_start", {"name": "kilat"}) == {"name": "kilat", "speed": 1.0}
    for name, params in [("fly", {}), ("auto_mode_start", {"interval_s": 1}), ("cycle", {"repeats": 9}),
                         ("cycle", {"topologies": ["5S"]}), ("demo_condition", {"condition": "../x"})]:
        with pytest.raises(C.CommandError):
            C.validate_action(name, params)
