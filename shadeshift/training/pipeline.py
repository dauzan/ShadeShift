"""Train and test one candidate model (docs/CONTRACT.md §14).

Fair test, never split by repeat (repeats of one shading are near copies; mixing them made the old 87-90 % look good):
- 'day':   real data from at least two days -> train on the other days, test on the held-out day (default: the latest);
- 'group': otherwise leave-one-group-out cross-validation on the evaluation data (a group = one real scan, or one lab
           shading pattern), so every tested round comes from a scan/pattern the model never saw;
- if the evaluation source is not among the training sources (e.g. train on sim, test on real), the whole evaluation
  set is the test set: that measures the sim -> real gap.
Evaluation data = real if any, else lab. Simulation is never the test set (it is not evidence).
"""
import hashlib
import json

import numpy as np

from shadeshift import evaluation
from shadeshift.training import dataset, models as M

TASKS = ("diagnosis", "selector", "pattern")


class TrainingError(ValueError):
    pass


def _xy(task, examples):
    if task == "diagnosis":
        ex = [e for e in examples if e.label is not None and e.x_round is not None]
        return ex, np.array([e.x_round for e in ex]), np.array([e.label for e in ex])
    if task == "pattern":
        ex = [e for e in examples if e.pattern is not None and e.x_round is not None]
        return ex, np.array([e.x_round for e in ex]), np.array([e.pattern for e in ex])
    ex = [e for e in examples if e.best is not None and e.x_4s is not None]
    return ex, np.array([e.x_4s for e in ex]), np.array([e.best for e in ex])


def model_id(task, model):
    blob = json.dumps(model.to_dict(), sort_keys=True).encode()
    if task == "selector":                            # same id as the ESP32 fingerprint of the 73 float32 weights
        from shadeshift.edge.selector import model_id as selector_id
        return selector_id(selector_weights(model))
    prefix = "diag" if task == "diagnosis" else "pola"
    return f"{prefix}-{model.kind}-v1@{hashlib.sha256(blob).hexdigest()[:12]}"


NEVER_BIAS = -1000.0                               # a topology never best in the training data is never chosen


def selector_weights(model):
    """A selector LogReg as the pemilih_bobot.h arrays (float32, rows 4S, 2S2P, TCT). A class missing from the
    training data gets zero weights and a very low bias, so the ESP32 never picks it."""
    if model.kind != "logreg":
        raise TrainingError("the selector must be logistic regression (the ESP32 runs pemilih.h)")
    f = np.float32
    coef = np.zeros((3, len(model.mean)), f)
    bias = np.full(3, NEVER_BIAS, f)
    for row, c in enumerate(model.classes):
        coef[c], bias[c] = model.coef[row], model.bias[row]
    return {"mean": np.asarray(model.mean, f), "scale": np.asarray(model.scale, f), "coef": coef, "bias": bias}


def train(task, kind, data, sources, params=None, test_day=None, active_selector=None):
    """data: {source: [Example]}. Returns {"model", "model_id", "report"}; raises TrainingError when impossible."""
    if task not in TASKS:
        raise TrainingError(f"task must be one of {TASKS}")
    if task == "selector" and kind != "logreg":
        raise TrainingError("the selector must be logistic regression (the ESP32 runs pemilih.h)")
    sources = [s for s in ("real", "lab", "sim") if s in sources]
    if not sources:
        raise TrainingError("choose at least one training source")
    params = params or {}
    pool = [e for s in sources for e in data.get(s, [])]
    eval_src = "real" if _xy(task, data.get("real", []))[0] else "lab"
    eval_all = _xy(task, data.get(eval_src, []))[0]
    if not eval_all:
        raise TrainingError("no labeled real or lab rounds to test on")
    days = sorted({e.day for e in eval_all}) if eval_src == "real" else []

    folds = []                                        # (train examples, test examples)
    if eval_src not in sources:
        mode = f"trained without {eval_src} data, tested on all {eval_src} rounds (gap between sources)"
        folds.append((pool, eval_all))
    elif len(days) >= 2:
        test_day = test_day if test_day in days else days[-1]
        mode = f"held-out day {test_day} (trained on {', '.join(d for d in days if d != test_day)})"
        folds.append(([e for e in pool if not (e.source == "real" and e.day == test_day)],
                      [e for e in eval_all if e.day == test_day]))
    else:
        groups = sorted({e.group for e in eval_all})
        if len(groups) < 2:
            raise TrainingError(f"only one {eval_src} scan/pattern: a fair test needs at least two (or two days)")
        what = "scan" if eval_src == "real" else "lab shading pattern"
        mode = f"leave-one-{what}-out on {eval_src} ({len(groups)} groups" + (", one day: weaker evidence)" if eval_src == "real" else ")")
        for g in groups:
            folds.append(([e for e in pool if not (e.source == eval_src and e.group == g)],
                          [e for e in eval_all if e.group == g]))

    y_true, y_pred, tested = [], [], []
    for tr, te in folds:
        ex_tr, X, y = _xy(task, tr)
        if len(ex_tr) < 4 or len(set(y.tolist())) < 2:
            continue                                   # this fold cannot train (e.g. one class only)
        m = M.make(kind, **params).fit(X, y)
        ex_te, Xt, yt = _xy(task, te)
        if len(ex_te):
            y_true += yt.tolist()
            y_pred += m.predict(Xt).tolist()
            tested += ex_te
    if not tested:
        raise TrainingError("no fold could be trained (too few rounds or a single class)")

    # the stored model: what was tested in 'day' / gap mode; trained on everything in group mode (CV estimates it)
    final_pool = folds[0][0] if len(folds) == 1 else pool
    ex_f, X, y = _xy(task, final_pool)
    model = M.make(kind, **params).fit(X, y)

    report = {"task": task, "kind": kind, "params": params, "sources": sources, "test_mode": mode,
              "evidence": eval_src, "trained_on": dataset.describe(ex_f), "tested_on": dataset.describe(tested),
              "n_test": len(tested)}
    if task in ("diagnosis", "pattern"):
        names = dataset.CLASSES if task == "diagnosis" else dataset.PATTERNS
        report.update(_classification(y_true, y_pred, names))
        outdoor = [k for k, e in enumerate(tested) if e.place == "outdoor_sun"]
        if outdoor:                                   # the proposal's target is on OUTDOOR test data
            report["accuracy_outdoor"] = round(float(np.mean([y_true[k] == y_pred[k] for k in outdoor]) * 100), 1)
            report["n_test_outdoor"] = len(outdoor)
    else:
        report.update(_classification(y_true, y_pred, evaluation.CANDIDATES))
        report["selection"] = _selector_losses(tested, y_pred, active_selector)
    return {"model": model, "model_id": model_id(task, model), "report": report}


def _classification(y_true, y_pred, names):
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    k = len(names)
    cm = np.zeros((k, k), int)
    for a, b in zip(y_true, y_pred):
        cm[a, b] += 1
    present = [c for c in range(k) if cm[c].sum()]
    recall = {names[c]: round(float(cm[c, c] / cm[c].sum() * 100), 1) for c in present}
    return {"classes": list(names), "accuracy": round(float((y_true == y_pred).mean() * 100), 1),
            "balanced_accuracy": round(float(np.mean([cm[c, c] / cm[c].sum() for c in present]) * 100), 1),
            "recall": recall, "confusion": cm.tolist(),
            "classes_not_tested": [names[c] for c in range(k) if c not in present]}


def _selector_losses(tested, y_pred, active):
    """Candidate vs the active selector vs fixed wirings on the same test rounds (evaluation.py definitions)."""
    rounds_c, rounds_a = [], []
    for e, p in zip(tested, y_pred):
        by_t = {t: {"pmax": v, "complete": True} for t, v in e.pmax.items()}
        rounds_c.append(evaluation.round_metrics(by_t, evaluation.CANDIDATES[int(p)], "candidate"))
        if active is not None:
            import port_c
            k, _ = port_c.pilih(np.asarray(e.x_4s, np.float32), active)
            rounds_a.append(evaluation.round_metrics(by_t, evaluation.CANDIDATES[int(k)], "active"))
    out = {"candidate": evaluation.summarize(rounds_c)}
    if active is not None:
        out["active"] = evaluation.summarize(rounds_a)
        c, a = out["candidate"]["relative"], out["active"]["relative"]
        out["better_than_active"] = bool(c and a and c["ai_loss_pct"] < a["ai_loss_pct"])
    return out
