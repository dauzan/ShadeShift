"""Predictive maintenance for the consumer view (docs/CONTRACT.md §28): what will need attention and roughly when, from
this array's own measurements of the last 14 days, plus the owner's maintenance log. Pure functions; the server passes
the facts in (Core.perawatan_state). Plain Indonesian; every forecast says "perkiraan ... sekitar", never a promise.

Four predictions, each from a robust (Theil-Sen) trend of one health indicator since the last maintenance entry:
  kotor       the array's power, per light-sensor reading when the sweeps carry it (so clouds do not count), else against
              the twin's expectation, dropping slowly: dust or dirt. Forecast: the day it reaches BATAS of its level
              right after the last cleaning (or the start of the data).
  tertinggal  one panel's power against the best panel of each check round, dropping: dirt or a fault on that panel.
  sambungan   the curve getting flatter near its right end (series resistance) rising: a loosening or corroding
              connection. Forecast: the day it reaches RS_BATAS times its starting value.
  bayangan    the same panel covered (kondisi state "object") at about the same hour on at least two different days:
              shade from something nearby that will likely come back tomorrow (no forecast date, a time of day).
A trend is said only over at least MIN_DAYS days and MIN_POINTS points, and only when it is clearly going the wrong way;
with less data the page says how much more it needs. A maintenance entry starts a fresh baseline, and its effect is
measured (median power in the 24 hours before against the 24 hours after)."""
from datetime import datetime, timezone
from statistics import median

MIN_DAYS = 3.0
MIN_POINTS = 8
BATAS = 0.85                 # clean or check when the level falls to 85 % of its starting level
RS_BATAS = 1.5               # check the connections when the series resistance reaches 1.5 times its start
SLOPE_MIN = 0.01             # a drop of at least 1 percent of the starting level per day
SEGERA_HARI = 3              # "soon" when the forecast is at most 3 days away
JENIS_LOG = {"bersih": "Panel dibersihkan", "perbaikan": "Panel diperbaiki teknisi"}


def _epoch(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _lokal(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()


def _tanggal(iso):
    t = _lokal(iso)
    return f"{t.day} {('Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des')[t.month - 1]}"


def _theil(pts):
    """Median of the pairwise slopes of (day, value) points (at most 300 points, evenly kept)."""
    if len(pts) > 300:
        step = len(pts) / 300
        pts = [pts[int(k * step)] for k in range(300)]
    s = [(b[1] - a[1]) / (b[0] - a[0]) for k, a in enumerate(pts) for b in pts[k + 1:] if b[0] - a[0] > 1e-3]
    return median(s) if s else 0.0


def _seri(pts):
    """(start level, current level, slope per day relative to the start, span in days) or None when too little data."""
    if len(pts) < MIN_POINTS:
        return None
    span = pts[-1][0] - pts[0][0]
    if span < MIN_DAYS:
        return None
    awal = median(v for d, v in pts if d - pts[0][0] <= 1.0)
    kini = median(v for d, v in pts if pts[-1][0] - d <= 1.0)
    if not awal:
        return None
    return awal, kini, _theil(pts) / awal, span


def _hari(n):
    n = max(1, round(n))
    return f"sekitar {n} hari"


def _array_series(rows, since):
    """The array's power per light reading (when most sweeps carry it) or against the expectation, for the most used
    wiring, after `since`. Returns (points, uses_light)."""
    rows = [r for r in rows if r.get("pmax") and (since is None or _epoch(r["at"]) > since)]
    if not rows:
        return [], False
    common = max({r["topology"] for r in rows}, key=lambda t: sum(r["topology"] == t for r in rows))
    rows = [r for r in rows if r["topology"] == common]
    light = sum(1 for r in rows if r.get("light_v")) >= 0.8 * len(rows)
    pts = [(_epoch(r["at"]) / 86400.0, r["pmax"] / (r["light_v"] if light else r["expected"]))
           for r in rows if (r.get("light_v") if light else r.get("expected"))]
    return pts, light


def _shade_pattern(rounds, m):
    """(hour, days with the panel covered near that hour, days with any check near it) or None."""
    hits, exact, checks = {}, {}, {}
    for r in rounds:
        p = r["panels"].get(m)
        if not p:
            continue
        t = _lokal(r["at"])
        h, day = t.hour + t.minute / 60.0, t.date()
        if p["state"] == "object":
            exact.setdefault(round(h) % 24, set()).add(day)
        for c in range(24):
            if abs(h - c) <= 1.0:
                checks.setdefault(c, set()).add(day)
                if p["state"] == "object":
                    hits.setdefault(c, set()).add(day)
    # the hour with the most days covered nearby; on a tie, the hour the shade was seen at itself
    best = max(hits, key=lambda c: (len(hits[c]), len(exact.get(c, ())), -c), default=None)
    if best is None or len(hits[best]) < 2:
        return None
    return best, len(hits[best]), len(checks[best])


def prediksi(rows, rounds, log, now=None, demo=False):
    """rows: array measurements oldest first {at, topology, pmax, expected, light_v, rs}; rounds: panel check rounds oldest
    first {at, panels: {A: {power_rel, state}}}; log: maintenance entries oldest first {at, jenis, panel}. Returns
    {ringkas: {level, text}, prediksi: [{jenis, panel, tingkat, judul, kalimat, hari}], log: [...], data_hari, demo}."""
    now = now or datetime.now(timezone.utc)
    out = []
    reset_all = max((_epoch(e["at"]) for e in log if not e.get("panel")), default=None)
    reset_any = max((_epoch(e["at"]) for e in log), default=None)

    # dirt on the whole array
    pts, light = _array_series(rows, reset_any)
    s = _seri(pts)
    if s:
        awal, kini, slope, span = s
        lvl = kini / awal
        if slope <= -SLOPE_MIN:
            if lvl <= BATAS:
                out.append({"jenis": "kotor", "panel": None, "tingkat": "segera", "judul": "Bersihkan panel", "hari": 0,
                            "kalimat": f"Daya sudah {round(lvl * 100)} persen dari daya setelah panel bersih dan terus turun "
                                       f"sekitar {round(-slope * 100)} persen per hari, kemungkinan karena debu atau kotoran. "
                                       "Sudah waktunya membersihkan panel."})
            else:
                d = (lvl - BATAS) / -slope
                out.append({"jenis": "kotor", "panel": None, "tingkat": "segera" if d <= SEGERA_HARI else "nanti",
                            "judul": "Bersihkan panel", "hari": round(d, 1),
                            "kalimat": f"Daya turun pelan sekitar {round(-slope * 100)} persen per hari"
                                       + (" walau cahaya sama" if light else "") + ", kemungkinan karena debu atau kotoran. "
                                       f"Perkiraan perlu dibersihkan dalam {_hari(d)}."})

    # one panel falling behind the others
    for m in ("A", "B", "C", "D"):
        since = max([x for x in (reset_all, max((_epoch(e["at"]) for e in log if e.get("panel") == m), default=None))
                     if x is not None], default=None)
        pp = [(_epoch(r["at"]) / 86400.0, r["panels"][m]["power_rel"]) for r in rounds
              if m in r["panels"] and (since is None or _epoch(r["at"]) > since)]
        s = _seri(pp)
        if not s:
            continue
        awal, kini, slope, span = s
        if slope > -SLOPE_MIN:
            continue
        lvl = kini / awal
        if lvl <= BATAS:
            out.append({"jenis": "tertinggal", "panel": m, "tingkat": "segera", "judul": f"Periksa panel {m}", "hari": 0,
                        "kalimat": f"Panel {m} makin tertinggal dari panel lain: sekarang {round(kini * 100)} persen dari panel "
                                   "terbaik. Bersihkan permukaannya; bila tidak membaik, minta teknisi memeriksa."})
        else:
            d = (lvl - BATAS) / -slope
            out.append({"jenis": "tertinggal", "panel": m, "tingkat": "segera" if d <= SEGERA_HARI else "nanti",
                        "judul": f"Periksa panel {m}", "hari": round(d, 1),
                        "kalimat": f"Panel {m} pelan-pelan tertinggal dari panel lain, sekitar {round(-slope * 100)} persen per "
                                   f"hari. Perkiraan perlu dibersihkan atau diperiksa dalam {_hari(d)}."})

    # a connection getting worse
    rp = [(_epoch(r["at"]) / 86400.0, r["rs"]) for r in rows
          if r.get("rs") and (reset_all is None or _epoch(r["at"]) > reset_all)]
    s = _seri(rp)
    if s:
        awal, kini, slope, span = s
        lvl = kini / awal
        if slope >= 0.05 and lvl >= 1.2:
            d = (RS_BATAS - lvl) / slope if lvl < RS_BATAS else 0
            out.append({"jenis": "sambungan", "panel": None, "tingkat": "segera" if d <= SEGERA_HARI else "nanti",
                        "judul": "Periksa sambungan kabel", "hari": round(d, 1),
                        "kalimat": "Sambungan kabel atau konektor kemungkinan makin longgar atau berkarat. "
                                   + ("Minta teknisi memeriksanya sekarang." if d <= 0 else
                                      f"Perkiraan perlu diperiksa teknisi dalam {_hari(d)}.")})

    # shade that comes back at the same hour
    for m in ("A", "B", "C", "D"):
        pat = _shade_pattern(rounds, m)
        if pat:
            jam, k, n = pat
            out.append({"jenis": "bayangan", "panel": m, "tingkat": "info", "judul": f"Bayangan berulang di panel {m}",
                        "hari": None,
                        "kalimat": f"Panel {m} terhalang sekitar pukul {jam:02d}.00 pada {k} dari {n} hari. Kemungkinan "
                                   "bayangan benda di sekitar, seperti pohon, tiang, atau bangunan. Besok kemungkinan terulang "
                                   "pada jam yang sama."})

    # the maintenance log and its effect
    catatan, semua = [], _array_series(rows, None)[0]
    for e in log[-5:]:
        t = _epoch(e["at"]) / 86400.0
        sebelum = [v for d, v in semua if t - 1.0 <= d < t]
        sesudah = [v for d, v in semua if t < d <= t + 1.0]
        efek = None
        if len(sebelum) >= 3 and len(sesudah) >= 3:
            g = (median(sesudah) - median(sebelum)) / median(sebelum) * 100
            efek = (f"Daya naik {round(g)} persen sesudahnya." if g >= 3 else
                    f"Daya turun {round(-g)} persen sesudahnya." if g <= -3 else "Daya hampir sama sesudahnya.")
        catatan.append({"at": e["at"], "teks": f"{_tanggal(e['at'])}: {JENIS_LOG.get(e['jenis'], e['jenis'])}"
                        + (f" (panel {e['panel']})" if e.get("panel") else "") + ".", "efek": efek})

    data_hari = round((_epoch(rows[-1]["at"]) - _epoch(rows[0]["at"])) / 86400.0, 1) if rows else 0.0
    out.sort(key=lambda p: ({"segera": 0, "nanti": 1, "info": 2}[p["tingkat"]], p["hari"] if p["hari"] is not None else 99))
    segera = [p for p in out if p["tingkat"] == "segera"]
    nanti = [p for p in out if p["tingkat"] == "nanti"]
    if segera:
        ringkas = {"level": "segera", "text": segera[0]["judul"] + (" sekarang" if not segera[0]["hari"] else
                                                                     f" dalam {_hari(segera[0]['hari'])}") + "."}
    elif nanti:
        ringkas = {"level": "nanti", "text": f"Perawatan berikutnya: {nanti[0]['judul'].lower()} dalam {_hari(nanti[0]['hari'])}."}
    elif data_hari < MIN_DAYS:
        ringkas = {"level": "belajar", "text": f"Belum cukup data untuk perkiraan: butuh {round(MIN_DAYS)} hari pengukuran, "
                                               f"baru {str(data_hari).replace('.', ',')} hari."}
    else:
        ringkas = {"level": "ok", "text": "Tidak ada perawatan yang perlu dilakukan saat ini."}
    return {"ringkas": ringkas, "prediksi": out, "log": catatan[::-1], "data_hari": data_hari, "demo": demo}
