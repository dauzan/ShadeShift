"""Proving the proposal's targets with measured data (docs/CONTRACT.md §13).

Metric definitions are the ones of the research code (SHADESHIFT_ML/latih.py, the source of the proposal's numbers):
- ideal-MLPE power = the sum of the four single-panel Pmax (every panel at its own maximum, as with one optimizer per
  panel); measured with the single-panel sweeps of firmware 3.2 (A, B, C, D);
- "% MLPE" of a topology = its Pmax / MLPE power x 100;
- the selector chooses among 4S, 2S2P and TCT (4P is outside the 24 V controller window, as in the lab and sim claims);
- AI loss = points of MLPE power lost vs the measured best of the three in the same round;
- best FIXED topology = the one wiring with the highest mean % MLPE over all rounds (a normal installation is wired once);
- recovery = mean % MLPE of the AI's choices - mean % MLPE of the best fixed topology (proposal target: >= 4 points).
Without single-panel sweeps (original firmware v2, emulator, lab files) MLPE is unknown: losses are then % of the measured best,
like the lab claim (0.82 % vs 2.71 %).
"""
import statistics

from shadeshift import protocol

CANDIDATES = ("4S", "2S2P", "TCT")
RECOVERY_TARGET_PTS = 4.0


def light_change_pct(sweeps):
    """Largest relative spread of the LDR readings (start and end of each sweep) over these sweeps, or None."""
    vals = [x for s in sweeps for x in ((s.get("header") or {}).get("light_v"), (s.get("header") or {}).get("light_end_v"))
            if x is not None]
    if len(vals) < 2 or max(vals) <= 0:
        return None
    return (max(vals) - min(vals)) / max(vals) * 100


def round_metrics(by_target, choice, decided_by):
    """by_target: {target: sweep dict with pmax, complete}. choice: the AI's choice for this round (or None).
    Returns the round's numbers; 'usable' is False with a reason when the three candidates are not all measured."""
    ok = {t: s["pmax"] for t, s in by_target.items() if s.get("complete") and s.get("pmax")}
    out = {"pmax": ok, "choice": choice, "decided_by": decided_by, "mlpe_w": None, "pct_mlpe": {}, "best": None,
           "ai_loss_pct": None, "ai_loss_pts": None, "usable": False, "reason": None}
    missing = [t for t in CANDIDATES if t not in ok]
    if missing:
        out["reason"] = "missing complete sweep: " + ", ".join(missing)
        return out
    if choice not in CANDIDATES:
        out["reason"] = "no AI decision (4S sweep unusable for the selector)"
        return out
    best = max(CANDIDATES, key=lambda t: ok[t])
    out.update(best=best, usable=True, ai_loss_pct=(ok[best] - ok[choice]) / ok[best] * 100)
    if all(p in ok for p in protocol.PANELS):
        mlpe = sum(ok[p] for p in protocol.PANELS)
        out["mlpe_w"] = mlpe
        out["pct_mlpe"] = {t: ok[t] / mlpe * 100 for t in (*CANDIDATES, "4P") if t in ok}
        out["ai_loss_pts"] = (ok[best] - ok[choice]) / mlpe * 100
    return out


def summarize(rounds):
    """rounds: usable round_metrics results. Two summaries: vs MLPE (rounds with panels) and vs measured best (all)."""
    rounds = [r for r in rounds if r["usable"]]
    out = {"n_rounds": len(rounds), "mlpe": None, "relative": None}
    if rounds:
        rel = {t: statistics.mean((r["pmax"][max(CANDIDATES, key=lambda x: r["pmax"][x])] - r["pmax"][t])
                                  / r["pmax"][max(CANDIDATES, key=lambda x: r["pmax"][x])] * 100 for r in rounds)
               for t in CANDIDATES}
        fixed = min(CANDIDATES, key=lambda t: rel[t])
        out["relative"] = {"n": len(rounds), "loss_pct_by_fixed": {t: round(v, 3) for t, v in rel.items()},
                           "best_fixed": fixed, "best_fixed_loss_pct": round(rel[fixed], 3),
                           "ai_loss_pct": round(statistics.mean(r["ai_loss_pct"] for r in rounds), 3),
                           "ai_matches_best_pct": round(sum(r["choice"] == r["best"] for r in rounds) / len(rounds) * 100, 1)}
    with_mlpe = [r for r in rounds if r["mlpe_w"]]
    if with_mlpe:
        pct = {t: statistics.mean(r["pct_mlpe"][t] for r in with_mlpe) for t in CANDIDATES}
        fixed = max(CANDIDATES, key=lambda t: pct[t])
        ai = statistics.mean(r["pct_mlpe"][r["choice"]] for r in with_mlpe)
        oracle = statistics.mean(r["pct_mlpe"][r["best"]] for r in with_mlpe)
        p4 = [r["pct_mlpe"]["4P"] for r in with_mlpe if "4P" in r["pct_mlpe"]]
        recovery = ai - pct[fixed]
        out["mlpe"] = {"n": len(with_mlpe), "pct_mlpe_by_fixed": {t: round(v, 2) for t, v in pct.items()},
                       "pct_mlpe_4p": round(statistics.mean(p4), 2) if p4 else None,
                       "best_fixed": fixed, "best_fixed_pct": round(pct[fixed], 2), "ai_pct": round(ai, 2),
                       "sweep_all_pct": round(oracle, 2), "recovery_pts": round(recovery, 2),
                       "ai_loss_pts": round(oracle - ai, 2), "fixed_loss_pts": round(oracle - pct[fixed], 2),
                       "target_pts": RECOVERY_TARGET_PTS, "met": recovery >= RECOVERY_TARGET_PTS}
    return out
