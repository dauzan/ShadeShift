"""Condition of the array for the consumer view (docs/CONTRACT.md §19): status sentence, problems in plain Indonesian,
the place each problem points to on the 3D model, and the 24-hour history.

Pure functions; the server passes the rows in. Rules (not validated yet; every cause is worded "kemungkinan"):
- single-panel sweeps taken within GROUP_S of each other form one check round; each round goes through
  diagnosis.panel_map (each panel against the best panel of the same round, so a cloud that dims all four cancels out);
- a panel with current down -> an object or dirt on its surface (place "surface": the whole panel, the position on the
  surface is not measurable: 36 cells in series with one bypass diode, the darkest cell sets the current);
- voltage down -> bypass diode or bypassed cells (place "diode": the terminal box on the back);
- power down with current and voltage normal -> cable or connector (place "cable");
- all panels alike but the array below the twin's expectation -> less light everywhere (place "sky" when the LDR also
  dropped against its own 24-hour median, else "array").
Nothing here invents a value: no data gives "Belum ada data", and an old check says how old it is."""
from statistics import median

from shadeshift import diagnosis

PANELS = ("A", "B", "C", "D")
ARRAY = ("4S", "2S2P", "TCT", "4P")
GROUP_S = 180
LIGHT_DROP = 0.85                     # LDR below 85 % of its 24-hour median = the light dropped
POS = {"A": "kiri atas", "B": "kiri bawah", "C": "kanan atas", "D": "kanan bawah"}
HINT_KIND = {"shaded_or_dimmed": "object", "bypassed_cells": "diode", "series_resistance": "cable"}


def angka(x, d=2):
    """Indonesian number: comma as the decimal mark."""
    return f"{x:.{d}f}".replace(".", ",")


def _epoch(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def durasi(s):
    s = int(round(s / 60.0))
    if s < 60:
        return f"{s} menit"
    return f"{s // 60} jam" + (f" {s % 60} menit" if s % 60 else "")


def rounds(panel_sweeps):
    """Group single-panel sweeps (dicts with topology A-D, captured_at, pmax, isc, voc), oldest first, into check
    rounds: {"at": time of the last sweep of the round, "panels": {A: {...}}, "map": panel_map or None}."""
    out, cur = [], None
    for s in sorted(panel_sweeps, key=lambda s: s["captured_at"]):
        t = _epoch(s["captured_at"])
        if cur is None or t - cur["t0"] > GROUP_S or s["topology"] in cur["panels"]:
            cur = {"t0": t, "panels": {}}
            out.append(cur)
        cur["panels"][s["topology"]] = s
        cur["at"] = s["captured_at"]
    for r in out:
        r["map"] = diagnosis.panel_map({m: {k: r["panels"][m].get(k) for k in ("pmax", "isc", "voc")}
                                        for m in r["panels"]}) if len(r["panels"]) == 4 else None
        r.pop("t0", None)
    return [r for r in out if r["map"]]


def panel_state(entry):
    """'normal' or the kind of problem of one panel in one round."""
    if entry["status"] == "normal":
        return "normal"
    return HINT_KIND.get(entry["hint"], "object")


def _since(rs, m, kind):
    """Time of the first round of the current unbroken run of `kind` for panel m (rounds oldest first)."""
    since = None
    for r in reversed(rs):
        if panel_state(r["map"]["modules"][m]) != kind:
            break
        since = r["at"]
    return since


def _problem(kind, m, e, best_w, since):
    lost = max(0.0, best_w - e["pmax_w"])
    how = (f"Daya panel {m} {round(e['power_rel'] * 100)} persen dari panel terbaik, sekitar {angka(lost, 3)} W "
           "lebih rendah.")
    if kind == "object":
        return {"kind": kind, "panel": m, "place": "surface",
                "title": f"Kemungkinan ada benda atau kotoran menutupi panel {m}",
                "where": f"Permukaan panel {m} ({POS[m]}). Posisi benda di permukaan panel tidak terukur.",
                "how_much": how, "since": since,
                "advice": f"Periksa permukaan panel {m} dan singkirkan benda atau kotoran yang menutupinya. "
                          "Bayangan kecil pada satu sel pun dapat menurunkan daya seluruh panel."}
    if kind == "diode":
        return {"kind": kind, "panel": m, "place": "diode",
                "title": f"Kemungkinan dioda pelewat atau sel panel {m} bermasalah",
                "where": f"Kotak terminal di bagian belakang panel {m}, tepi bawah, tempat dioda pelewat 1N5822.",
                "how_much": how, "since": since,
                "advice": f"Periksa dioda pelewat di kotak terminal panel {m}. Bila dioda baik, kemungkinan ada sel "
                          "yang rusak atau terpintas."}
    return {"kind": "cable", "panel": m, "place": "cable",
            "title": f"Kemungkinan sambungan kabel panel {m} bermasalah",
            "where": f"Terminal panel {m}, kabelnya, dan konektor Wago di samping susunan panel.",
            "how_much": how, "since": since,
            "advice": f"Periksa kabel dan sambungan dari terminal panel {m} ke konektor Wago. Kencangkan atau ganti "
                      "yang longgar atau berkarat."}


def assess(online, kind, panel_sweeps, array_sweeps, expected, threshold_pct=15.0, now_iso=None):
    """Current condition. panel_sweeps / array_sweeps: complete sweeps of the last 24 h (dicts with captured_at,
    topology, pmax, isc, voc and, for array sweeps, light_v). expected: {topology: W} from the twin, or None."""
    rs = rounds(panel_sweeps)
    arr = sorted((s for s in array_sweeps if s["topology"] in ARRAY and s.get("pmax") is not None),
                 key=lambda s: s["captured_at"])
    last = arr[-1] if arr else None
    panels, problems = {}, []
    if rs:
        r = rs[-1]
        best_w = max(e["pmax_w"] for e in r["map"]["modules"].values())
        for m in PANELS:
            e = r["map"]["modules"][m]
            st = panel_state(e)
            panels[m] = {"state": st, "power_rel": e["power_rel"], "pmax_w": e["pmax_w"], "isc_rel": e["isc_rel"],
                         "voc_rel": e["voc_rel"], "at": r["at"], "since": _since(rs, m, st) if st != "normal" else None}
            if st != "normal":
                problems.append(_problem(st, m, e, best_w, panels[m]["since"]))
    else:
        for m in PANELS:
            panels[m] = {"state": "nodata", "power_rel": None, "pmax_w": None, "at": None, "since": None}

    array = None
    if last:
        exp = (expected or {}).get(last["topology"])
        lights = [s["light_v"] for s in arr if s.get("light_v") is not None]
        ref = median(lights) if len(lights) >= 3 else None
        array = {"topology": last["topology"], "pmax_w": last["pmax"], "voc": last.get("voc"), "isc": last.get("isc"),
                 "vmp": last.get("vmp"), "imp": last.get("imp"), "at": last["captured_at"], "expected_w": exp,
                 "pct_of_expected": round(last["pmax"] / exp * 100, 1) if exp else None,
                 "light_v": last.get("light_v"), "light_ref_v": ref}
        uniform = not problems
        if uniform and array["pct_of_expected"] is not None and array["pct_of_expected"] < 100 - threshold_pct:
            light_low = ref is not None and last.get("light_v") is not None and last["light_v"] < LIGHT_DROP * ref
            pct = round(array["pct_of_expected"])
            problems.append({
                "kind": "cloud" if light_low else "dim", "panel": None, "place": "sky" if light_low else "array",
                "title": "Cahaya berkurang merata, kemungkinan awan atau mendung" if light_low
                         else "Daya seluruh panel turun merata",
                "where": "Seluruh susunan panel. Keempat panel turun bersama.",
                "how_much": f"Daya seluruh panel {pct} persen dari perkiraan normal.",
                "since": None,
                "advice": "Tidak perlu tindakan. Daya kembali saat cahaya kembali terang." if light_low
                          else "Bila langit cerah, bersihkan seluruh permukaan panel dari debu atau kotoran."})

    if not online:
        level, text = "offline", ("Alat tidak terhubung. Data terakhir tetap ditampilkan." if (rs or arr)
                                  else "Alat tidak terhubung.")
    elif not rs and not arr:
        level, text = "nodata", "Belum ada data. Mulai pemantauan untuk mengukur panel."
    elif problems:
        p = problems[0]
        level = "problem"
        text = p["title"] if len(problems) == 1 else f"{p['title']}, dan {len(problems) - 1} masalah lain"
    else:
        level, text = "ok", "Semua panel dalam kondisi normal"
    return {"status": {"level": level, "text": text}, "panels": panels, "problems": problems, "array": array,
            "last_check": rs[-1]["at"] if rs else None, "demo": kind == "emulator",
            "rules": "Aturan belum divalidasi dengan data terukur; setiap penyebab adalah kemungkinan."}


def history(panel_sweeps, array_sweeps, expected, now_iso, hours=24):
    """24-hour history: per-panel state timeline, array power against the expectation, events (state changes) and a
    summary in sentences. Durations are approximate: a state is assumed to last until the next check."""
    rs = rounds(panel_sweeps)
    now = _epoch(now_iso)
    timeline = {m: [] for m in PANELS}
    events, spent = [], {m: {} for m in PANELS}
    prev = {m: None for m in PANELS}
    for k, r in enumerate(rs):
        t0 = _epoch(r["at"])
        t1 = _epoch(rs[k + 1]["at"]) if k + 1 < len(rs) else now
        for m in PANELS:
            e = r["map"]["modules"][m]
            st = panel_state(e)
            timeline[m].append({"at": r["at"], "state": st, "power_rel": e["power_rel"]})
            spent[m][st] = spent[m].get(st, 0.0) + max(0.0, t1 - t0)
            if st != prev[m]:
                if st != "normal":
                    events.append({"at": r["at"], "panel": m, "state": st,
                                   "text": f"Panel {m}: {_word(st)}, daya {round(e['power_rel'] * 100)} persen dari panel terbaik"})
                elif prev[m] not in (None, "normal"):
                    events.append({"at": r["at"], "panel": m, "state": st, "text": f"Panel {m} kembali normal"})
            prev[m] = st
    arr = [{"at": s["captured_at"], "topology": s["topology"], "pmax_w": s["pmax"],
            "expected_w": (expected or {}).get(s["topology"]), "light_v": s.get("light_v")}
           for s in sorted(array_sweeps, key=lambda s: s["captured_at"]) if s["topology"] in ARRAY and s.get("pmax") is not None]
    summary = []
    for m in PANELS:
        bad = {k: v for k, v in spent[m].items() if k != "normal" and v >= 60}
        for st, secs in sorted(bad.items(), key=lambda x: -x[1]):
            summary.append(f"Panel {m} {_word(st)} selama sekitar {durasi(secs)}.")
    pcts = [a["pmax_w"] / a["expected_w"] * 100 for a in arr if a["expected_w"]]
    if pcts:
        summary.append(f"Rata-rata daya {round(sum(pcts) / len(pcts))} persen dari perkiraan normal "
                       f"({len(pcts)} pengukuran).")
    if rs and not any(spent[m].get(k) for m in PANELS for k in spent[m] if k != "normal"):
        summary.insert(0, "Semua panel normal pada setiap pemeriksaan.")
    if not rs and not arr:
        summary.append(f"Belum ada pengukuran dalam {hours} jam terakhir.")
    return {"hours": hours, "rounds": len(rs), "timeline": timeline, "array": arr, "events": events[::-1],
            "summary": summary}


def _word(state):
    return {"object": "kemungkinan tertutup benda atau kotoran", "diode": "kemungkinan masalah dioda atau sel",
            "cable": "kemungkinan masalah kabel atau sambungan", "normal": "normal"}.get(state, state)
