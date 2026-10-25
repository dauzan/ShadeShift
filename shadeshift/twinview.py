"""What the Digital Twin page draws on each panel (docs/CONTRACT.md §18). Pure functions, no I/O.

Legend (basic colors, each with an icon and a word, never color alone):
- green  = healthy (single-panel sweep normal, or the array matches the twin's expectation);
- red    = power lost to light: shade or dimming (current dropped);
- blue   = electrical: bypassed cells / diode, or series resistance (voltage or fill factor dropped);
- grey dashed outline = lower than expected or a pattern without a position: cause or place unknown.
Only the precision the data has is drawn: a position needs the single-panel sweeps (A-D); the topology sweeps alone give a
PATTERN, so its candidates are all drawn dashed (training.dataset.PATTERNS: string and row swaps look identical).
"""
MODULES = "ABCD"
HINT_KIND = {"shaded_or_dimmed": "light", "bypassed_cells": "electrical", "series_resistance": "electrical"}
GROUPS = {"string_pair": "A+B or C+D", "row_pair": "A+C or B+D", "diagonal": "A+D or B+C", "one": "one of A, B, C, D",
          "three": "three of the four", "all": "all four"}


def markers(diagnosis=None, deviation_pct=None, threshold_pct=15.0):
    """{module: {"kind", "text", "source", "dashed"}}. diagnosis: Core.device_diagnosis() result (or None);
    deviation_pct: measured vs twin expectation of the latest sweep on the active wiring (or None)."""
    pmap = (diagnosis or {}).get("map")
    if pmap:
        out = {}
        for m in MODULES:
            x = pmap["modules"][m]
            kind = "healthy" if x["status"] == "normal" else HINT_KIND.get(x["hint"], "unknown")
            out[m] = {"kind": kind, "dashed": False, "power_rel": x["power_rel"], "hint": x["hint"],
                      "isc_rel": x["isc_rel"], "voc_rel": x["voc_rel"], "basis": "panel",
                      "text": f"{x['power_rel'] * 100:.0f} % of the best panel" + (f", {x['hint']}" if x["hint"] else ""),
                      "source": f"single-panel sweep, compared with {pmap['reference']} (rules not validated)"}
        return out
    pattern = ((diagnosis or {}).get("pattern") or {}).get("class")
    if pattern and pattern != "none":
        return {m: {"kind": "unknown", "dashed": True, "power_rel": None, "basis": "pattern", "pattern": pattern,
                    "text": f"pattern: {GROUPS[pattern]}; the topology sweeps cannot tell which",
                    "source": "pattern model on the topology sweeps (single-panel sweeps give the position)"}
                for m in MODULES}                     # every panel is a candidate: the pattern has no position
    if deviation_pct is not None and deviation_pct < -threshold_pct:
        return {m: {"kind": "unknown", "dashed": True, "power_rel": None, "basis": "twin", "deviation_pct": deviation_pct,
                    "text": f"array {deviation_pct:+.0f} % vs the twin: lower than expected, cause unknown",
                    "source": "digital twin (lab-lamp fit, ~8 % error)"} for m in MODULES}
    if deviation_pct is not None:
        return {m: {"kind": "healthy", "dashed": False, "power_rel": None, "basis": "twin", "deviation_pct": deviation_pct,
                    "text": f"array {deviation_pct:+.0f} % vs the twin", "source": "digital twin (lab-lamp fit, ~8 % error)"}
                for m in MODULES}
    return {}
