"""Data-collection sessions (docs/CONTRACT.md §12): condition catalog, file names, quality checks, export.

The catalog follows SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md §2 with the team's corrections (docs/team/progress.md §8):
fault resistors 5 Ω / 10 Ω instead of 1 Ω / 2.2 Ω, E1 is a control (almost invisible), E5 is the shorted-bypass class.
Labels are what the operator says was done to the panels; they never change the raw data.
"""
import csv
import io
import json
import statistics
import zipfile
from datetime import datetime

from shadeshift import protocol

MODULES = "ABCD"            # A top-left, B bottom-left, C top-right, D bottom-right (2x2 photo layout)

# Diagnosis classes (proposal: 6 causes). Ids are stored; the Indonesian names are shown.
DIAGNOSIS = {
    "normal": "normal",
    "partial_shading": "bayangan sebagian (opak)",
    "uniform_dimming": "redup merata / tembus cahaya",
    "bypass_open": "dioda pelewat terbuka",
    "bypass_short": "dioda pelewat hubung singkat",
    "series_resistance": "hambatan seri naik",
}

# code: (description, default diagnosis or None = operator chooses, default modules, dynamic, note)
CONDITIONS = {
    "A1": ("Tanpa bayangan (acuan). Ulangi di awal dan akhir sesi untuk memeriksa hanyut", "normal", "", False, ""),
    "B1": ("Modul A tertutup opak 25 % dari tepi", "partial_shading", "A", False, ""),
    "B2": ("Modul A tertutup opak 50 % dari tepi", "partial_shading", "A", False, ""),
    "B3": ("Modul A tertutup opak 75 % dari tepi", "partial_shading", "A", False, ""),
    "B4": ("Satu sel (strip sempit) modul A tertutup opak", "partial_shading", "A", False, ""),
    "B5": ("Modul A dan B tertutup opak", "partial_shading", "AB", False, ""),
    "B6": ("Modul A dan D tertutup opak (diagonal)", "partial_shading", "AD", False, ""),
    "B7": ("Modul A dan C tertutup opak", "partial_shading", "AC", False, ""),
    "C1": ("Paranet 65 % pada modul A", "uniform_dimming", "A", False, ""),
    "C2": ("Paranet 75 % pada modul A", "uniform_dimming", "A", False, ""),
    "C3": ("Paranet pada modul A dan B", "uniform_dimming", "AB", False, ""),
    "C4": ("Paranet pada modul A dan D", "uniform_dimming", "AD", False, ""),
    "C5": ("Modul A kotor merata (debu / film tipis, opsional)", "uniform_dimming", "A", False, ""),
    "D1": ("Bayangan alami (pohon, tiang, bangunan). Foto wajib; catat jam dan arah", None, "", False,
           "pilih kelas dan modul yang terbayangi"),
    "D2": ("Awan lewat (dinamis): sapuan berulang selama 20 menit", None, "", True,
           "pilih kelas sesuai yang terlihat; tandai dinamis"),
    "E1": ("Dioda pelewat modul C dilepas, tanpa bayangan", "bypass_open", "C", False,
           "KONTROL: kurva hampir sama dengan normal (Isc turun ~2 %)"),
    "E2": ("Dioda pelewat modul C dilepas + opak 50 % pada modul C", "bypass_open", "C", False, ""),
    "E3": ("Resistor seri 5 Ω (5 W) pada satu modul", "series_resistance", "C", False, "ganti modul bila perlu"),
    "E4": ("Resistor seri 10 Ω (10 W) pada satu modul", "series_resistance", "C", False, "ganti modul bila perlu"),
    "E5": ("Modul C dipintas kabel pendek (modul hilang dari susunan)", "bypass_short", "C", False, ""),
    "F1": ("Ranting digerakkan di atas modul A (dinamis), sapuan berulang", "partial_shading", "A", True, ""),
    "X1": ("Lainnya: tulis di catatan", None, "", False, "jelaskan kondisinya di catatan"),
}

PLACES = {"indoor_lamp": ("DR", "dalam ruangan (lampu)"), "outdoor_sun": ("LR", "luar ruangan (matahari)")}
DEMO_PREFIX = "TIRUAN"            # emulator scans: replayed lab curves, never named like real measurements

LIGHT_CHANGE_PCT = 5.0            # protocol §3: discard or mark a cycle when the reference light changes > 5 %
REPEAT_SPREAD_PCT = 1.8           # proposal: spread between repeats <= 1.8 %
A1_DRIFT_PCT = 5.0                # assumption: no limit in the protocol; flag above 5 %
PANEL_SUM_MARGIN = 1.05           # 4P cannot exceed the sum of the four single-panel Pmax (mismatch only lowers it)


class LabelError(ValueError):
    pass


def catalog():
    return [{"code": c, "description": d, "diagnosis": dg, "modules": m, "dynamic": dy, "note": n}
            for c, (d, dg, m, dy, n) in CONDITIONS.items()]


def normalize_modules(modules):
    mods = "".join(sorted(set(str(modules or "").upper())))
    if any(m not in MODULES for m in mods):
        raise LabelError("modules must be letters from A, B, C, D")
    return mods


def condition_name(prefix, local_date, code, modules):
    """'LR', 2026-10-20, 'B2', 'A' -> 'LR1020_B2'; modules other than the catalog default are appended: 'LR1020_B2-C'."""
    if code not in CONDITIONS:
        raise LabelError(f"unknown condition code {code!r}")
    name = f"{prefix}{local_date:%m%d}_{code}"
    return name if modules == CONDITIONS[code][2] else f"{name}-{modules or 'none'}"


def file_name(condition, topology, repeat):
    return f"{condition}_{topology}_u{repeat}.csv"


def local_date(iso_utc):
    return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone()


def scan_targets(with_panels):
    return list(protocol.TOPOLOGIES) + (list(protocol.PANELS) if with_panels else [])


# ---------------- quality checks ----------------
def _pct(a, b):
    return abs(a - b) / max(abs(a), abs(b)) * 100 if max(abs(a), abs(b)) > 0 else 0.0


def _check(name, ok, detail, value=None, limit=None, items=None):
    return {"check": name, "ok": ok, "detail": detail, "value": value, "limit": limit, "items": items or []}


def scan_quality(scan, sweeps):
    """scan: dict with rounds, repeat_start, with_panels, dynamic. sweeps: dicts with topology, repeat, complete, pmax,
    header (light_v, light_end_v), label. Returns a list of checks; ok is True, False or None (cannot be checked)."""
    checks = []
    targets = scan_targets(scan["with_panels"])
    repeats = list(range(scan["repeat_start"], scan["repeat_start"] + scan["rounds"]))
    got = {(s["topology"], s["repeat"]): s for s in sweeps}
    missing = [f"{t}_u{r}" for r in repeats for t in targets if (t, r) not in got]
    incomplete = [s["label"] for s in sweeps if not s["complete"]]
    n_expected = len(targets) * len(repeats)
    checks.append(_check("complete", not missing and not incomplete,
                         f"{len(sweeps) - len(incomplete)} of {n_expected} sweeps complete"
                         + (f"; missing {', '.join(missing)}" if missing else "")
                         + (f"; incomplete {', '.join(incomplete)}" if incomplete else ""),
                         value=len(sweeps) - len(incomplete), limit=n_expected, items=missing + incomplete))

    # light: change inside each sweep, and spread over each round (one cycle), from the LDR lines
    lit = [s for s in sweeps if (s.get("header") or {}).get("light_v") is not None]
    if not lit:
        checks.append(_check("light_steady", None, "no light readings (needs firmware 3.2 and the LDR on A2)"))
    else:
        bad = []
        for s in lit:
            h = s["header"]
            if h.get("light_end_v") is not None and _pct(h["light_v"], h["light_end_v"]) > LIGHT_CHANGE_PCT:
                bad.append(f"{s['label']} ({_pct(h['light_v'], h['light_end_v']):.1f} % during the sweep)")
        for r in repeats:
            vals = [x for s in lit if s["repeat"] == r
                    for x in (s["header"]["light_v"], s["header"].get("light_end_v")) if x is not None]
            if len(vals) >= 2 and _pct(max(vals), min(vals)) > LIGHT_CHANGE_PCT:
                bad.append(f"round u{r} ({_pct(max(vals), min(vals)):.1f} % between its sweeps)")
        checks.append(_check("light_steady", not bad,
                             "light steady within 5 % (LDR volts; the LDR is not linear, so this is approximate)"
                             if not bad else "light changed: " + "; ".join(bad), limit=LIGHT_CHANGE_PCT, items=bad))

    # repeat spread per topology (not meaningful for dynamic conditions)
    if scan["dynamic"]:
        checks.append(_check("repeat_spread", None, "dynamic condition: repeats are expected to differ"))
    elif len(repeats) < 2:
        checks.append(_check("repeat_spread", None, "one round only: no spread between repeats"))
    else:
        spreads, bad = {}, []
        for t in targets:
            p = [got[(t, r)]["pmax"] for r in repeats if (t, r) in got and got[(t, r)]["complete"] and got[(t, r)]["pmax"]]
            if len(p) >= 2:
                spreads[t] = round(statistics.stdev(p) / statistics.mean(p) * 100, 2)
                if spreads[t] > REPEAT_SPREAD_PCT:
                    bad.append(f"{t} {spreads[t]:.2f} %")
        checks.append(_check("repeat_spread", (not bad) if spreads else None,
                             ("Pmax spread between repeats (std/mean): "
                              + ", ".join(f"{t} {v:.2f} %" for t, v in spreads.items())) if spreads else "not enough repeats",
                             value=max(spreads.values()) if spreads else None, limit=REPEAT_SPREAD_PCT, items=bad))

    # relay sanity: 4P must not exceed the sum of the four single panels in the same round
    if scan["with_panels"]:
        bad, rows = [], []
        for r in repeats:
            parts = [got.get((p, r)) for p in protocol.PANELS]
            p4 = got.get(("4P", r))
            if p4 and p4["pmax"] and all(x and x["pmax"] for x in parts):
                total = sum(x["pmax"] for x in parts)
                rows.append(f"u{r}: 4P {p4['pmax']:.3f} W, A+B+C+D {total:.3f} W")
                if p4["pmax"] > PANEL_SUM_MARGIN * total:
                    bad.append(f"u{r}")
        checks.append(_check("panels_vs_4P", (not bad) if rows else None,
                             ("; ".join(rows) + (". 4P above the panel sum: check relays/wiring or changing light" if bad else ""))
                             if rows else "no complete round with 4P and all four panels", items=bad))
    return checks


def a1_drift(first, last):
    """first, last: {topology: pmax} of the first and the last A1 scan of a session (mean over repeats)."""
    common = [t for t in protocol.TOPOLOGIES if first.get(t) and last.get(t)]
    if not common:
        return _check("a1_drift", None, "needs an A1 scan at the start and another at the end of the session")
    d = {t: round((last[t] - first[t]) / first[t] * 100, 2) for t in common}
    worst = max(abs(v) for v in d.values())
    return _check("a1_drift", worst <= A1_DRIFT_PCT,
                  "A1 end vs start: " + ", ".join(f"{t} {v:+.2f} %" for t, v in d.items()),
                  value=worst, limit=A1_DRIFT_PCT, items=[t for t, v in d.items() if abs(v) > A1_DRIFT_PCT])


# ---------------- export ----------------
LABEL_COLUMNS = ["file", "folder", "reason_excluded", "source", "session_uuid", "place", "sky", "location", "operator",
                 "scan_uuid", "code", "condition", "diagnosis", "modules", "dynamic", "topology", "repeat",
                 "captured_at", "voc", "isc", "pmax", "vmp", "imp", "light_v", "light_end_v",
                 "temp_A", "temp_B", "temp_C", "temp_D", "quality_flags", "scan_note", "session_note"]


def export_zip(session, scans, sweeps_by_scan):
    """Zip bytes: data/<file>.csv (raw text exactly as received from the device), _dibuang/<file>.csv (incomplete),
    labels.csv, sesi.json and BACA_SAYA.txt."""
    demo = session["source"] == "demo"
    buf, rows = io.BytesIO(), []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for sc in scans:
            flags = [q["check"] for q in sc["quality"] if q["ok"] is False]
            temps = sc.get("temps") or {}
            for s in sweeps_by_scan.get(sc["id"], []):
                name = file_name(sc["condition"], s["topology"], s["repeat"])
                folder = "data" if s["complete"] else "_dibuang"
                text = s.get("raw_text")
                if not text:     # never expected for gateway sweeps; rebuilt from the stored points and marked
                    text = protocol.to_firmware_csv(s["label"], s["topology"], s["points"]["v"], s["points"]["i"], s["header"])
                    text = "# (dibuat ulang dari titik tersimpan: teks mentah tidak ada)\n" + text
                z.writestr(f"{folder}/{name}", text if text.endswith("\n") else text + "\n")
                t = temps.get(str(s["repeat"])) or {}
                h = s.get("header") or {}
                rows.append({
                    "file": name, "folder": folder, "reason_excluded": "" if s["complete"] else "incomplete sweep",
                    "source": s["source"], "session_uuid": session["uuid"], "place": session["place"],
                    "sky": session.get("sky") or "", "location": session.get("location") or "",
                    "operator": session.get("operator") or "", "scan_uuid": sc["uuid"], "code": sc["code"],
                    "condition": sc["condition"], "diagnosis": sc.get("diagnosis") or "", "modules": sc["modules"],
                    "dynamic": int(bool(sc["dynamic"])), "topology": s["topology"], "repeat": s["repeat"],
                    "captured_at": s["captured_at"], **{k: s.get(k) for k in ("voc", "isc", "pmax", "vmp", "imp")},
                    "light_v": h.get("light_v"), "light_end_v": h.get("light_end_v"),
                    **{f"temp_{m}": t.get(m) for m in MODULES}, "quality_flags": " ".join(flags),
                    "scan_note": sc.get("note") or "", "session_note": session.get("note") or ""})
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=LABEL_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        z.writestr("labels.csv", out.getvalue())
        z.writestr("sesi.json", json.dumps({"session": session, "scans": scans}, ensure_ascii=False, indent=1))
        z.writestr("BACA_SAYA.txt", _readme(session, demo, len(rows)))
    return buf.getvalue()


def _readme(session, demo, n):
    head = ("DATA TIRUAN: sesi ini direkam dari ESP32 tiruan yang memutar ulang kurva lab lama (lampu halogen).\n"
            "BUKAN pengukuran baru. Jangan dipakai sebagai data lapangan.\n\n") if demo else ""
    return head + (
        f"Sesi SHADESHIFT {session['uuid']} ({PLACES[session['place']][1]}), mulai {session['started_at']} UTC, {n} sapuan.\n"
        "data/      : sapuan lengkap, teks persis seperti diterima dari alat (format logger/lab, bisa diunggah lagi).\n"
        "_dibuang/  : sapuan tidak lengkap (protokol §4); alasannya di labels.csv.\n"
        "labels.csv : satu baris per berkas: kode kondisi, kelas diagnosis, modul, ulangan, cahaya (LDR, relatif),\n"
        "             suhu punggung A-D per ulangan, dan pemeriksaan mutu yang gagal (quality_flags).\n"
        "sesi.json  : data sesi, label tiap scan, dan hasil pemeriksaan mutu lengkap.\n"
        "Label adalah keterangan operator tentang kondisi panel; data mentah tidak pernah diubah.\n")
