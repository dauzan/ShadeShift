"""Command validation (docs/CONTRACT.md §5.3): the raw-command allowlist and the gateway actions.

Raw firmware commands that could bypass safety are refused here, so neither the dashboard nor any other
API client can send them (docs/ANALYSIS.md §7.1 F1, F2). Bench work uses the Arduino Serial Monitor instead.
"""
import re

from shadeshift import protocol

RAW_EXACT = {"4S", "2S2P", "TCT", "4P", "A", "B", "C", "D", "OFF", "STOP", "STATUS", "VOC", "CAHAYA", "KAL", "SCAN",
             "BANTUAN", "INFO", "DIAG",
             "CEKVOC 1", "PANTAU 0", "PANTAU 1", "TAHAN 0"}
BLOCKED = {
    "TAHAN 1": "TAHAN 1 holds the MOSFET at the MPP (same heat hazard as DAC); only the gateway's auto mode may use it "
               "after the team's heat check on hardware",
    "RELAI": "RELAI is for bench tests without panels; the firmware accepts it whenever no topology is active",
    "UJIRELAI": "UJIRELAI is for bench tests without panels; the firmware accepts it whenever no topology is active",
    "DAC": "DAC drives the MOSFET directly, even with R0 closed (no thermal protection)",
    "CEKVOC 0": "CEKVOC 0 disables the Voc safety check",
    "SIKLUS": "the firmware ignores OFF while SIKLUS runs; use the 'cycle' action, which stops cleanly",
    "LANJUT": "only used by firmware SIKLUS, which is not allowed from the API",
    "BATAL": "only used by firmware SIKLUS, which is not allowed from the API",
    "BENCH": "bench mode is for the Arduino Serial Monitor only",
}
BLOCKED_HINT = "Use the Arduino Serial Monitor for bench work, with the gateway stopped."

ACTIONS = ("auto_select", "auto_mode_start", "auto_mode_stop", "audit_decision", "cycle", "full_scan", "stop",
           "demo_condition", "demo_scenario_start", "demo_scenario_stop", "monitor_start", "monitor_stop",
           "panel_check", "measure_now", "diagnose", "compare_wirings", "apply_wiring")
APPLICABLE_WIRINGS = ("4S", "2S2P", "TCT")     # 4P gives about 20 V, below the 24 V the controller needs (CONTRACT §29)
SERVER_MADE_ACTIONS = {"full_scan"}            # queued only by POST /sessions/{id}/scans, which records the labels


TOPOLOGY_WORDS = set(protocol.SWEEP_TARGETS)          # 4 topologies + single panels A-D
ACTUATING_RAW_WORDS = TOPOLOGY_WORDS | {"SWEEP", "VPANEL", "CEKVOC", "TAHAN", "DIAG"}   # DIAG: firmware 3.2, honours OFF
STOP_ACTIONS = {"stop", "auto_mode_stop", "monitor_stop"}


class CommandError(ValueError):
    pass


def is_stop(kind, command):
    """Stop-type commands: handed out first, never expire (CONTRACT §5.3)."""
    if kind == "raw":
        return command.split()[0].upper() in ("OFF", "STOP")
    return command in STOP_ACTIONS


def is_actuating(kind, command):
    """Commands that move relays or start work: refused while a task runs, expire after 10 s in the queue."""
    if kind == "raw":
        return command.split()[0].upper() in ACTUATING_RAW_WORDS
    return command not in STOP_ACTIONS


def validate_raw(command):
    """Return the normalized firmware line, or raise CommandError with the reason."""
    if not command.isprintable() or len(command) > 64:
        raise CommandError("command must be at most 64 printable characters on one line")
    parts = command.strip().split()
    if not parts:
        raise CommandError("empty command")
    word = parts[0].upper()
    line = " ".join([word] + parts[1:])
    for blocked, reason in BLOCKED.items():
        if line.upper() == blocked or word == blocked:
            raise CommandError(f"{blocked} is blocked: {reason}. {BLOCKED_HINT}")
    if line.upper() in RAW_EXACT:
        return line.upper()
    if word == "SWEEP":
        label = protocol.sanitize_label(" ".join(parts[1:]), default="dasbor")
        return f"SWEEP {label}"
    if word == "VPANEL":
        try:
            value = float(parts[1])
        except (IndexError, ValueError):
            raise CommandError("VPANEL needs a number, e.g. VPANEL 17") from None
        if not 5 < value < 40:
            raise CommandError("VPANEL must be between 5 and 40 V (firmware limit)")
        return f"VPANEL {value:g}"
    raise CommandError(f"{word} is not an allowed command. Allowed: {', '.join(sorted(RAW_EXACT))}, SWEEP <label>, VPANEL <V>")


def _number(params, key, lo, hi, default, cast=float):
    value = params.get(key, default)
    if value is None:
        return None
    try:
        value = cast(value)
    except (TypeError, ValueError):
        raise CommandError(f"{key} must be a number") from None
    if not lo <= value <= hi:
        raise CommandError(f"{key} must be between {lo} and {hi}")
    return value


def validate_action(name, params):
    """Return normalized params for an action, or raise CommandError."""
    params = dict(params or {})
    if name not in ACTIONS:
        raise CommandError(f"unknown action {name!r}; known: {', '.join(ACTIONS)}")
    if name == "auto_mode_start":
        out = {"interval_s": _number(params, "interval_s", 3, 3600, None),
               "trigger_pct": _number(params, "trigger_pct", 5, 80, None),
               "hold_s": _number(params, "hold_s", 0, 3600, None)}
        st = params.get("stability")
        if st is not None:
            if not isinstance(st, dict):
                raise CommandError("stability must be an object")
            out["stability"] = {"enabled": bool(st.get("enabled", True)),
                                "window_s": _number(st, "window_s", 5, 10800, None),    # None = the last 3 monitor sweeps
                                "cv_pct": _number(st, "cv_pct", 1, 100, 10)}
        return {k: v for k, v in out.items() if v is not None}
    if name == "monitor_start":
        # Monitoring (CONTRACT §19): sweep the active wiring every array_interval_s (no switching) and check each panel
        # alone every panel_interval_s (switches A-D, then back to the wiring); 0 = no panel checks.
        panel = _number(params, "panel_interval_s", 0, 7200, 1800)
        if panel and panel < 300:
            raise CommandError("panel_interval_s must be 0 (off) or at least 300")
        return {"array_interval_s": _number(params, "array_interval_s", 30, 3600, 300), "panel_interval_s": panel,
                "wiring": params.get("wiring") if params.get("wiring") in protocol.TOPOLOGIES else None}
    if name == "cycle":
        topologies = params.get("topologies") or list(protocol.TOPOLOGIES)
        if not isinstance(topologies, list) or not topologies or any(t not in protocol.SWEEP_TARGETS for t in topologies):
            raise CommandError(f"topologies must be a non-empty subset of {list(protocol.SWEEP_TARGETS)}")
        return {"label": protocol.sanitize_label(params.get("label"), default="siklus"),
                "repeats": _number(params, "repeats", 1, 5, 1, int), "topologies": topologies}
    if name == "full_scan":
        scan_uuid, condition = str(params.get("scan_uuid", "")), str(params.get("condition", ""))
        if not re.fullmatch(r"[0-9a-f\-]{8,64}", scan_uuid):
            raise CommandError("scan_uuid must be the uuid of a scan")
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", condition):
            raise CommandError("condition must look like LR1020_B2")
        return {"scan_uuid": scan_uuid, "condition": condition, "rounds": _number(params, "rounds", 1, 60, 3, int),
                "repeat_start": _number(params, "repeat_start", 1, 999, 1, int), "panels": bool(params.get("panels", False)),
                "pause_s": _number(params, "pause_s", 0, 600, 0)}
    if name == "apply_wiring":
        target = params.get("target")
        if target not in APPLICABLE_WIRINGS:
            raise CommandError(f"target must be one of {', '.join(APPLICABLE_WIRINGS)} (4P is below the 24 V window)")
        return {"target": target}
    if name == "demo_condition":
        cond = str(params.get("condition", ""))
        if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", cond):
            raise CommandError("condition must look like V3_paranet65")
        return {"condition": cond}
    if name == "demo_scenario_start":
        scenario = str(params.get("name", "default"))
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", scenario):
            raise CommandError("scenario name must be letters, digits, '_' or '-'")
        return {"name": scenario, "speed": _number(params, "speed", 0.1, 50, None)}   # None = scenario's own speed
    return {}
