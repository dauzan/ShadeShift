"""The stability rule (docs/CONTRACT.md §17): while the power of the active wiring keeps changing, lock TCT and do not
run the selector; when it is steady again, normal auto mode resumes.

Rule (team notes, 16 Oct; NOT validated): coefficient of variation (std / mean) of the Pmax of the monitor sweeps of the
last window_s seconds on the same wiring, at least 3 sweeps; above cv_pct % = unstable. Off by default.
Evidence: simulation (SHADESHIFT_ML/uji_stabilitas.py -> hasil/stabilitas_ringkasan.csv) and a replay on the team's
moving-shade full scans (protocol F1 / D2), both shown on the L3 page.
"""
import csv
import statistics
from pathlib import Path

from shadeshift import inti
from shadeshift.evaluation import CANDIDATES

TCT = "TCT"


def unstable(readings, now, window_s, cv_pct):
    """readings: [(time_s, pmax)] of the active wiring. True when the recent ones vary more than cv_pct %."""
    vals = [p for t, p in readings if now - t <= window_s]
    if len(vals) < 3:
        return False
    m = statistics.fmean(vals)
    return m > 0 and statistics.pstdev(vals) / m * 100 > cv_pct


def replay(rounds, threshold=0.20, window=3, cv_pct=10.0):
    """Replay auto mode on measured rounds of a moving-shade scan. rounds: [{"pmax": {4S, 2S2P, TCT}, "choice"}] in time
    order (one round = one monitor step). Returns the energy (sum of Pmax of the active wiring) of each policy as % of
    picking the best wiring in every round. As in the gateway (hold 30 s, a monitor sweep every 10 s), the trigger may
    switch again only `window` rounds after a switch, so the rule can see `window` readings of one wiring first.
    Sweep and switch costs are NOT modelled here."""
    rounds = [r for r in rounds if all(r["pmax"].get(t) for t in CANDIDATES) and r.get("choice") in CANDIDATES]
    if len(rounds) < 4:
        return None
    best = sum(max(r["pmax"][t] for t in CANDIDATES) for r in rounds)

    def run(stabil):
        cur = rounds[0]["choice"]
        ref, hist, energy, locks, switches = rounds[0]["pmax"][cur], [], 0.0, 0, 0
        locked, last_switch = False, 0
        for k, r in enumerate(rounds):
            p = r["pmax"][cur]
            hist = (hist + [p])[-window:]
            if stabil and len(hist) >= 3 and statistics.fmean(hist) > 0 and \
                    statistics.pstdev(hist) / statistics.fmean(hist) * 100 > cv_pct:
                if not locked:
                    locks += 1
                locked = True
                if cur != TCT:
                    cur, hist, switches, last_switch = TCT, [], switches + 1, k
                ref = r["pmax"][cur]
            else:
                if locked:
                    locked, ref = False, p
                if k - last_switch >= window and ref > 0 and abs(p - ref) / ref > threshold:
                    new = r["choice"]
                    if new != cur:
                        cur, hist, switches, last_switch = new, [], switches + 1, k
                    ref = r["pmax"][cur]
            energy += r["pmax"][cur]
        return energy, switches, locks

    out = {"rounds": len(rounds), "policies": {}}
    for name, (e, sw, lk) in {"fixed TCT": (sum(r["pmax"][TCT] for r in rounds), 0, 0),
                              "AI every round": (sum(r["pmax"][r["choice"]] for r in rounds), None, 0),
                              "auto mode (20 % trigger)": run(False),
                              "auto mode + stability rule": run(True)}.items():
        out["policies"][name] = {"pct_of_best": round(e / best * 100, 2), "switches": sw, "locks": lk}
    return out


def sim_summary(path=None):
    """Mean % of ideal-MLPE energy per shade type and policy from the simulation run, or None if it has not been run."""
    path = Path(path or Path(inti.ML) / "hasil" / "stabilitas_ringkasan.csv")
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out, intervals = {}, set()
    for r in rows:
        jeda = r.get("jeda_s") or ""
        key = r["kebijakan"] + (f" @{int(float(jeda))}s" if jeda else "")
        if jeda:
            intervals.add(int(float(jeda)))
        out.setdefault(r["jenis"], {}).setdefault(key, []).append(float(r["pct_mlpe"]))
    summary = {j: {k: round(statistics.fmean(v), 2) for k, v in pol.items()} for j, pol in out.items()}
    paired = {}
    for j in out:
        for s in sorted(intervals):
            a = out[j].get(f"mode otomatis (pemicu 20 %) @{s}s") or []
            b = out[j].get(f"mode otomatis + aturan stabilitas @{s}s") or []
            tct = out[j].get("tetap TCT") or []
            d = [y - x for x, y in zip(a, b)]
            paired.setdefault(j, {})[s] = {"rule_better": sum(x > 0.05 for x in d), "rule_worse": sum(x < -0.05 for x in d),
                                          "auto_worse_than_tct": sum(x < y - 0.05 for x, y in zip(a, tct)), "of": len(d)}
    return {"mean_pct_mlpe": summary, "by_interval": paired, "intervals_s": sorted(intervals),
            "label": "simulation (36 synthetic 20-minute scenarios, same as SHADESHIFT_ML/dinamis.py)"}
