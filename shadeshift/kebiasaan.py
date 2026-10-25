"""Light AI model for the analyser box (docs/CONTRACT.md §26): it learns what is normal for THIS array from its own
measurements, judges each new measurement against that, and says in plain words what is new since a moment in time.
Runs on the laptop in milliseconds; nothing to install, no internet.

Learning (unsupervised, per wiring): the robust centre (median) and spread (median absolute deviation) of
  r = measured power / the twin's expected power     (the twin knows the wiring; r near 1 is a clear lamp)
  q = measured power / light sensor reading           (only when the sweeps carry the LDR value)
over the measurements before the newest one, at most WINDOW_DAYS back. It needs MIN_N measurements of a wiring before it
judges anything; until then it says it is still learning.
Judging: how many spreads the newest measurement lies from that normal (a robust z-score). With the light sensor, low
power with normal power-per-light means less light (a cloud), not a panel problem.
Trend: the Theil-Sen slope of r over the window, in percent of normal per day, said only over at least one day.

What is new since `sejak`: how many measurements arrived and when, the power change against the last measurement before
`sejak`, the model's verdict on the newest, panel changes and curve-shape changes in that time. Plain Indonesian, for a
home owner: no symbols, no Voc or Isc."""
from datetime import datetime
from statistics import median

MIN_N = 8
WINDOW_DAYS = 14
Z_LOW, Z_VERY_LOW, Z_HIGH = -2.0, -4.0, 2.0
MIN_SPREAD = 0.03                      # a spread below 3 % of normal is treated as 3 % (lab lamps are very steady)
SUSUNAN = {"4S": "seri (4S)", "2S2P": "seri-paralel (2S2P)", "TCT": "silang (TCT)", "4P": "paralel (4P)"}


def _epoch(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _jam(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H.%M")


def _angka(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def _robust(values):
    m = median(values)
    mad = median(abs(v - m) for v in values) * 1.4826
    return m, max(mad, MIN_SPREAD * abs(m))


def _ratio(row):
    return row["pmax"] / row["expected"] if row.get("expected") else None


def _per_light(row):
    return row["pmax"] / row["light_v"] if row.get("light_v") else None


def latih(rows):
    """rows: array measurements oldest first ({at, topology, pmax, expected, light_v}). Returns the learned normal per
    wiring: {topology: {n, r: (centre, spread), q: (centre, spread) or None}}."""
    model = {}
    for t in {r["topology"] for r in rows}:
        mine = [r for r in rows if r["topology"] == t and r.get("pmax")]
        rs = [x for x in map(_ratio, mine) if x is not None]
        qs = [x for x in map(_per_light, mine) if x is not None]
        model[t] = {"n": len(mine), "r": _robust(rs) if len(rs) >= MIN_N else None,
                    "q": _robust(qs) if len(qs) >= MIN_N else None}
    return model


def nilai(model, row):
    """The newest measurement against the learned normal: {status: belajar | normal | rendah | sangat_rendah | tinggi,
    persen (of normal), z, sebab: cahaya (the light dropped too) | bukan_cahaya | None, n}."""
    m = model.get(row["topology"]) or {"n": 0, "r": None, "q": None}
    r = _ratio(row)
    if not m["r"] or r is None:
        return {"status": "belajar", "n": m["n"], "persen": None, "z": None, "sebab": None}
    centre, spread = m["r"]
    z = (r - centre) / spread
    status = "sangat_rendah" if z <= Z_VERY_LOW else "rendah" if z <= Z_LOW else "tinggi" if z >= Z_HIGH else "normal"
    sebab = None
    q = _per_light(row)
    if m["q"] and q is not None and status in ("rendah", "sangat_rendah"):
        qc, qs = m["q"]
        sebab = "cahaya" if (q - qc) / qs > Z_LOW else "bukan_cahaya"     # normal power per light: the light itself dropped
    return {"status": status, "n": m["n"], "persen": round(r / centre * 100), "z": round(z, 2), "sebab": sebab}


def tren(rows):
    """Theil-Sen slope of r over the rows, in percent of normal per day, and the span in days."""
    pts = [(_epoch(r["at"]) / 86400.0, _ratio(r)) for r in rows if _ratio(r) is not None]
    if len(pts) < MIN_N:
        return None
    span = pts[-1][0] - pts[0][0]
    if span < 1.0:
        return None
    if len(pts) > 400:                                   # keep the pairwise slopes cheap
        step = len(pts) / 400
        pts = [pts[int(k * step)] for k in range(400)]
    slopes = [(b[1] - a[1]) / (b[0] - a[0]) for k, a in enumerate(pts) for b in pts[k + 1:] if b[0] - a[0] > 1e-3]
    centre = median(p[1] for p in pts)
    return {"persen_per_hari": round(median(slopes) / centre * 100, 1) if slopes and centre else 0.0, "hari": round(span, 1)}


def kalimat_nilai(v):
    """The verdict in a sentence."""
    if v["status"] == "belajar":
        return f"Model AI masih mempelajari kebiasaan panel ini ({v['n']} dari {MIN_N} pengukuran)."
    if v["status"] == "normal":
        return f"Menurut model AI, daya ini normal untuk panel Anda ({v['persen']} persen dari biasanya)."
    if v["status"] == "tinggi":
        return f"Menurut model AI, daya ini lebih tinggi dari biasanya ({v['persen']} persen), biasanya karena cahaya lebih terang."
    teks = ("jauh lebih rendah" if v["status"] == "sangat_rendah" else "lebih rendah") + f" dari biasanya ({v['persen']} persen)"
    if v["sebab"] == "cahaya":
        return f"Menurut model AI, daya ini {teks}. Sensor cahaya juga turun, jadi kemungkinan karena mendung, bukan masalah panel."
    if v["sebab"] == "bukan_cahaya":
        return (f"Menurut model AI, daya ini {teks}, padahal cahaya tidak berkurang. Kemungkinan ada yang menutupi panel atau "
                "ada masalah pada panel.")
    return f"Menurut model AI, daya ini {teks}."


def kalimat_tren(t):
    if not t:
        return None
    if abs(t["persen_per_hari"]) < 2:
        return f"Dalam {_angka(t['hari'], 0)} hari terakhir daya panel stabil."
    arah = "turun" if t["persen_per_hari"] < 0 else "naik"
    saran = " Bila langit cerah, coba bersihkan permukaan panel." if arah == "turun" else ""
    return f"Dalam {_angka(t['hari'], 0)} hari terakhir daya cenderung {arah} sekitar {_angka(abs(t['persen_per_hari']), 0)} persen per hari.{saran}"


def yang_baru(rows, sejak, model, panel_events=(), shapes=None, judul_shape=None):
    """What is new since `sejak` (ISO; None = since the measurement before the newest). rows: array measurements oldest
    first; panel_events: kondisi.history events; shapes: {at: set of curve-shape codes} for recent measurements;
    judul_shape: {code: plain title}. Returns {judul, lines, dari, sampai}."""
    if not rows:
        return {"judul": "Belum ada pengukuran", "lines": [], "dari": None, "sampai": None}
    if sejak is None:
        sejak = rows[-2]["at"] if len(rows) > 1 else None
        asal = f"pengukuran sebelumnya (pukul {_jam(sejak)})" if sejak else None
    else:
        asal = f"pukul {_jam(sejak)}"
    baru = [r for r in rows if sejak is None or _epoch(r["at"]) > _epoch(sejak)]
    if not baru:
        return {"judul": f"Belum ada data baru sejak {asal}", "lines": [], "dari": sejak, "sampai": None}
    judul = f"Yang baru sejak {asal}" if asal else "Pengukuran pertama"
    lines = [f"1 pengukuran baru, pukul {_jam(baru[0]['at'])}." if len(baru) == 1 else
             f"{len(baru)} pengukuran baru, dari pukul {_jam(baru[0]['at'])} sampai {_jam(baru[-1]['at'])}."]
    akhir = baru[-1]
    sebelum = [r for r in rows if sejak and _epoch(r["at"]) <= _epoch(sejak) and r["topology"] == akhir["topology"]]
    if sebelum and sebelum[-1].get("pmax") and akhir.get("pmax"):
        a, b = sebelum[-1]["pmax"], akhir["pmax"]
        d = (b - a) / a * 100
        if abs(d) < 5:
            lines.append(f"Daya hampir sama dengan pukul {_jam(sebelum[-1]['at'])} ({_angka(b, 2)} watt).")
        else:
            lines.append(f"Daya {'naik' if d > 0 else 'turun'} {round(abs(d))} persen dibanding pukul {_jam(sebelum[-1]['at'])}, "
                         f"dari {_angka(a, 2)} menjadi {_angka(b, 2)} watt.")
    lines.append(kalimat_nilai(nilai(model, akhir)))
    for e in [e for e in panel_events if sejak is None or _epoch(e["at"]) > _epoch(sejak)][-3:]:
        lines.append(f"Pukul {_jam(e['at'])}: {e['text']}.")
    if shapes and sebelum and judul_shape:
        lama, kini = shapes.get(sebelum[-1]["at"]), shapes.get(akhir["at"])
        if lama is not None and kini is not None:
            for c in sorted(kini - lama):
                lines.append(f"Muncul tanda baru: {judul_shape[c].lower()}.")
            for c in sorted(lama - kini):
                lines.append(f"Tanda {judul_shape[c].lower()} sudah hilang.")
    return {"judul": judul, "lines": lines, "dari": sejak, "sampai": akhir["at"]}
