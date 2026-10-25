"""Which module is affected, measured from the single-panel sweeps (docs/CONTRACT.md §15).

Each panel is compared with the others IN THE SAME ROUND (so a cloud that dims all four cancels out) and, when the
session has an A1 scan (no shade), with its own A1 value (so a panel that is always a bit weaker is not flagged):
    r(p) = (Pmax(p) / Pmax_A1(p)) / max over panels of the same ratio          (1.0 = as good as the best panel)
The same is done for Isc and Voc. Simple rules, NOT validated yet (thresholds are assumptions, shown with every map):
- r >= 0.90 normal; 0.60-0.90 reduced; < 0.60 strongly reduced;
- Isc down (< 0.90): shaded or dimmed (current follows light);
- else Voc down (< 0.85): cells or a module bypassed/shorted;
- else power down with current and voltage normal: series resistance / low fill factor.
The topology sweeps alone can only give the PATTERN (training.dataset.PATTERNS); this map gives the position.
"""
from shadeshift import fieldwork

OK_MIN, STRONG_MAX = 0.90, 0.60
ISC_DROP, VOC_DROP = 0.90, 0.85


def _rel(values, ref):
    ratio = {m: values[m] / ref[m] if ref and ref.get(m) else values[m] for m in values}
    top = max(ratio.values())
    return {m: (v / top if top > 0 else 0.0) for m, v in ratio.items()}


def panel_map(panels, ref=None):
    """panels / ref: {module: {"pmax", "isc", "voc"}} for A-D. Returns the map, or None without all four panels."""
    mods = list(fieldwork.MODULES)
    if any(not (panels.get(m) or {}).get("pmax") for m in mods):
        return None
    use_ref = ref is not None and all((ref.get(m) or {}).get("pmax") for m in mods)
    rel = {k: _rel({m: float(panels[m].get(k) or 0.0) for m in mods},
                   {m: float(ref[m].get(k) or 0.0) for m in mods} if use_ref else None) for k in ("pmax", "isc", "voc")}
    out = {}
    for m in mods:
        r = rel["pmax"][m]
        status = "normal" if r >= OK_MIN else "reduced" if r >= STRONG_MAX else "strongly_reduced"
        hint = None
        if status != "normal":
            if rel["isc"][m] < ISC_DROP:
                hint = "shaded_or_dimmed"
            elif rel["voc"][m] < VOC_DROP:
                hint = "bypassed_cells"
            else:
                hint = "series_resistance"
        out[m] = {"pmax_w": panels[m]["pmax"], "power_rel": round(r, 3), "isc_rel": round(rel["isc"][m], 3),
                  "voc_rel": round(rel["voc"][m], 3), "status": status, "hint": hint}
    affected = "".join(m for m in mods if out[m]["status"] != "normal")
    from shadeshift.training.dataset import pattern_of
    return {"modules": out, "affected": affected, "pattern": pattern_of(affected),
            "reference": "A1 of this session and the best panel" if use_ref else "the best panel in this round",
            "rules": f"normal >= {OK_MIN:.2f}, strongly reduced < {STRONG_MAX:.2f} of the best panel; Isc < {ISC_DROP:.2f} "
                     f"shade, Voc < {VOC_DROP:.2f} bypassed cells (rules not validated yet)"}
