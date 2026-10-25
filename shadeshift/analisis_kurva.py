"""I-V curve shape analysis for the consumer view (docs/CONTRACT.md §20): the six classic deviations of an I-V curve
(as in the usual field guides), each with the voltage range where it shows, so the page can explain every point of the
curve when the user hovers it; plus the 24-hour and current summaries in plain Indonesian.

Rules over measured shape features, compared with a reference curve when there is one (the twin's unshaded curve for the
array, the best panel of the same check for a panel). Not validated on outdoor data yet: every cause says "kemungkinan".
  1 tangga          notches or steps        (P-V has more than one peak)
  2 arus_rendah     current lower than the reference
  3 tegangan_rendah voltage lower than the reference
  4 lutut_landai    rounder knee            (low fill factor without steps or series resistance)
  5 hambatan_seri   shallow slope near Voc  (series resistance)
  6 hambatan_shunt  current falling from near Isc (shunt leakage or uneven light)
"""
import numpy as np

JENIS = {
    1: ("tangga", "Anak tangga pada kurva",
        "Arus turun bertahap: sebagian sel atau panel menerima cahaya lebih sedikit sehingga dioda pelewat bekerja.",
        "bayangan sebagian, kotoran setempat, atau sel retak"),
    2: ("arus_rendah", "Arus lebih rendah dari {acuan}",
        "Seluruh daerah arus lebih rendah: cahaya yang sampai ke sel berkurang.",
        "cahaya redup, debu merata, atau bayangan menyeluruh"),
    3: ("tegangan_rendah", "Tegangan lebih rendah dari {acuan}",
        "Kurva berakhir lebih awal: ada sel atau panel yang terpintas, atau panel sangat panas.",
        "dioda pelewat terhubung singkat, sel rusak, atau suhu tinggi"),
    4: ("lutut_landai", "Lutut kurva membulat",
        "Peralihan dari daerah arus ke daerah tegangan tidak tajam, sehingga daya maksimum lebih kecil.",
        "penuaan panel atau ketidakcocokan antar sel"),
    5: ("hambatan_seri", "Kemiringan dekat tegangan tanpa beban terlalu landai",
        "Tegangan turun saat arus naik: hambatan pada jalur arus terlalu besar.",
        "sambungan kabel, konektor, atau terminal yang longgar atau berkarat"),
    6: ("hambatan_shunt", "Arus menurun sejak dekat hubung singkat",
        "Arus tidak datar di daerah arus: ada arus bocor di dalam panel, atau cahaya antar sel tidak merata.",
        "kebocoran pada sel (hambatan shunt rendah) atau cahaya yang tidak merata"),
}
# The same six signs in a home owner's words: (name, one plain sentence of what it usually means).
MUDAH = {
    1: ("Sebagian panel terhalang", "Sebagian panel mendapat cahaya lebih sedikit, biasanya karena bayangan, kotoran, atau sel yang retak."),
    2: ("Cahaya yang masuk berkurang", "Seluruh panel menerima cahaya lebih sedikit, biasanya karena mendung, debu merata, atau bayangan besar."),
    3: ("Ada bagian panel yang tidak ikut bekerja", "Sebagian sel dilewati, biasanya karena dioda rusak, sel rusak, atau panel terlalu panas."),
    4: ("Panel kurang efisien", "Panel memberi daya lebih kecil dari seharusnya, sering karena usia panel."),
    5: ("Sambungan kabel kurang baik", "Ada sambungan kabel atau konektor yang longgar atau berkarat."),
    6: ("Ada kebocoran listrik di panel", "Sebagian listrik bocor di dalam panel, atau cahaya ke panel tidak merata."),
}
DAERAH = {
    "arus": ("Bagian datar", "Tinggi garis di bagian ini menunjukkan banyaknya cahaya yang diterima panel."),
    "lutut": ("Tikungan", "Peralihan menuju titik terbaik. Makin tajam tikungannya, makin besar daya panel."),
    "mpp": ("Titik daya terbaik", "Di titik ini panel memberi daya paling besar."),
    "tegangan": ("Ujung kanan", "Panel mendekati tegangan tertingginya. Garis yang terlalu landai di sini menandakan sambungan kurang baik."),
}


def _clean(v, i):
    v, i = np.asarray(v, float), np.asarray(i, float)
    m = np.isfinite(v) & np.isfinite(i) & (v >= 0)
    v, i = v[m], np.clip(i[m], 0, None)
    o = np.argsort(v, kind="stable")
    return v[o], i[o]


def _smooth(x, n=5):
    if len(x) < n:
        return x.copy()
    pad = n // 2
    xp = np.pad(x, pad, mode="edge")
    return np.array([np.median(xp[k:k + n]) for k in range(len(x))])


def _shape(v, i):
    """Basic numbers of a curve: Isc, Voc, MPP, fill factor, series and shunt indicators."""
    isc = float(np.median(i[:3])) if len(i) >= 3 else float(i.max())
    pos = v[i > 0.01 * max(isc, 1e-9)]
    voc = float(pos.max()) if len(pos) else float(v.max())
    p = v * i
    k = int(p.argmax())
    vmp, imp, pmax = float(v[k]), float(i[k]), float(p[k])
    ff = pmax / (voc * isc) if voc > 0 and isc > 0 else 0.0
    near_voc = (i < 0.3 * isc) & (v > 0.6 * voc) & (i > 0)
    rs = None
    if near_voc.sum() >= 3 and np.ptp(i[near_voc]) > 0:
        rs = float(-np.polyfit(i[near_voc], v[near_voc], 1)[0]) * isc / voc        # normalised slope dV/dI near Voc
    si = _smooth(i)
    lo, hi = 0.03 * voc, 0.5 * vmp
    m = (v >= lo) & (v <= hi)
    shunt = float((np.interp(lo, v, si) - np.interp(hi, v, si)) / isc) if m.sum() >= 3 and isc > 0 else None
    return {"isc": isc, "voc": voc, "vmp": vmp, "imp": imp, "pmax": pmax, "ff": ff, "rs": rs, "shunt": shunt}


def _peaks(v, i, pmax):
    """Power peaks with their valleys: [(v_peak, p_peak)], [(v_valley)] using a smoothed P-V curve."""
    p = _smooth(v * i, 7)
    idx = [k for k in range(3, len(p) - 3) if p[k] == p[k - 3:k + 4].max() and p[k] > 0.15 * pmax]
    peaks = []
    for k in idx:
        if peaks and v[k] - v[peaks[-1]] < 0.04 * v.max():
            if p[k] > p[peaks[-1]]:
                peaks[-1] = k
            continue
        peaks.append(k)
    keep, valleys = [peaks[0]] if peaks else [], []
    for k in peaks[1:]:
        a = keep[-1]
        vk = a + int(np.argmin(p[a:k + 1]))
        if min(p[a], p[k]) - p[vk] >= 0.04 * pmax:
            keep.append(k)
            valleys.append(vk)
        elif p[k] > p[a]:
            keep[-1] = k
    return keep, valleys


def _plateau_steps(v, i, isc, voc):
    """Steps found as current plateaus: a flat run, a steep drop, then a clearly lower flat run (at least 6 % of Voc
    long). Catches the small second plateau a shaded module leaves after its bypass diode stops (too little power for a
    second P-V peak). Returns [(v_end_of_upper_plateau, v_start_of_lower_plateau)]."""
    g_v = np.linspace(0, voc, 200)
    g_i = np.interp(g_v, v, _smooth(i, 7))
    g_i = np.convolve(np.pad(g_i, 4, mode="edge"), np.ones(9) / 9, mode="valid")    # about 4 % of Voc: noise out
    slope = -np.gradient(g_i, g_v) * voc / max(isc, 1e-12)
    flat = (slope < 0.6) & (g_i > 0.03 * isc)
    runs, k = [], 0
    while k < len(g_v):
        if flat[k]:
            j = k
            while j + 1 < len(g_v) and flat[j + 1]:
                j += 1
            if g_v[j] - g_v[k] >= 0.06 * voc:
                runs.append((k, j, float(np.median(g_i[k:j + 1]))))
            k = j + 1
        else:
            k += 1
    out = []
    for (a0, a1, la), (b0, b1, lb) in zip(runs, runs[1:]):
        if lb < 0.8 * la and slope[a1:b0 + 1].max() > 1.5:
            out.append((float(g_v[a1]), float(g_v[b0])))
    return out


def analyze(v, i, ref=None, tol_i=0.9, acuan="harapan"):
    """Shape analysis of one curve. ref: {"v": [...], "i": [...]} or None; tol_i: current ratio below which the curve
    is "low current" (0.9 against the best panel, 0.85 against the twin, whose error is about 8 percent). Returns the
    numbers, the deviations found (code, key, title, meaning, cause, v0, v1) and, for every point, the part of the curve
    and what it means."""
    v, i = _clean(v, i)
    if len(v) < 10 or i.max() <= 0:
        return {"ok": False, "anomalies": [], "points": [], "headline": "Data kurva belum cukup untuk dibaca."}
    s = _shape(v, i)
    r = _shape(*_clean(ref["v"], ref["i"])) if ref is not None and len(ref.get("v", [])) >= 10 else None
    found = []

    def add(code, v0, v1, detail=""):
        key, title, meaning, cause = JENIS[code]
        title = title.format(acuan=acuan)
        found.append({"code": code, "key": key, "title": title, "meaning": meaning + (f" {detail}" if detail else ""),
                      "cause": f"Kemungkinan penyebab: {cause}.", "mudah": MUDAH[code][0], "mudah_arti": MUDAH[code][1],
                      "v0": round(float(v0), 3), "v1": round(float(v1), 3)})

    peaks, valleys = _peaks(v, i, s["pmax"])
    steps = [(float(v[a]), float(v[vk])) for a, vk in zip(peaks, valleys)]
    for p0, p1 in _plateau_steps(v, i, s["isc"], s["voc"]):
        if not any(a - 0.05 * s["voc"] <= p0 <= b + 0.05 * s["voc"] for a, b in steps):
            steps.append((p0, p1))
    merged = []
    for v0, v1 in sorted(steps):
        if merged and v0 <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], v1))
        else:
            merged.append((v0, v1))
    steps = merged
    for v0, v1 in steps:
        add(1, v0, v1, f"Kurva ini memiliki {len(steps)} anak tangga." if len(steps) > 1 else "")
    # current AND power below the reference (the twin's power is good to ~8 %, its current near Isc much less so)
    if r and s["isc"] < tol_i * r["isc"] and s["pmax"] < tol_i * r["pmax"]:
        add(2, 0, 0.6 * s["vmp"], f"Arus hubung singkat {round(s['isc'] / r['isc'] * 100)} persen dari acuan.")
    if r and s["voc"] < 0.93 * r["voc"]:
        add(3, 0.85 * s["voc"], s["voc"], f"Tegangan tanpa beban {round(s['voc'] / r['voc'] * 100)} persen dari acuan.")
    # with steps the low tail near Voc is the step's lower plateau, not a series resistance
    series = not steps and s["rs"] is not None and (s["rs"] > 1.8 * r["rs"] + 0.05 if r and r["rs"] is not None else s["rs"] > 0.3)
    if series:
        add(5, max(s["vmp"], 0.8 * s["voc"]), s["voc"])
    shunt = s["shunt"] is not None and (s["shunt"] > r["shunt"] + 0.06 if r and r["shunt"] is not None else s["shunt"] > 0.15)
    if shunt and not steps:
        add(6, 0, 0.5 * s["vmp"], f"Arus turun {round(s['shunt'] * 100)} persen sebelum lutut kurva.")
    rounded = s["ff"] < (r["ff"] - 0.08 if r else 0.6)
    if rounded and not steps and not series:
        add(4, 0.6 * s["vmp"], min(1.12 * s["vmp"], 0.97 * s["voc"]), f"Faktor isi {s['ff']:.2f}".replace(".", ",") + ".")

    k_mpp = int(np.argmax(v * i))
    pts = []
    for k, (vv, ii) in enumerate(zip(v, i)):
        part = "mpp" if k == k_mpp else "arus" if vv < 0.6 * s["vmp"] else "lutut" if vv <= min(1.12 * s["vmp"], 0.95 * s["voc"]) else "tegangan"
        name, text = DAERAH[part]
        hit = next((a for a in found if a["v0"] <= vv <= a["v1"]), None)
        if hit and part != "mpp":
            name, text = hit["mudah"], hit["mudah_arti"]
        pts.append({"v": round(float(vv), 4), "i": round(float(ii), 6), "bagian": name, "arti": text,
                    "kode": hit["code"] if hit and part != "mpp" else 0})
    head = (found[0]["title"] if found else "Bentuk kurva normal")
    return {"ok": True, **{k: round(x, 6) if isinstance(x, float) else x for k, x in s.items()},
            "reference": bool(r), "anomalies": found, "points": pts, "headline": head}


def codes(analysis):
    return {a["code"] for a in analysis.get("anomalies", [])}


# ---------------- summaries in sentences (the analyser boxes on Kurva I-V and Riwayat) ----------------
def _jam(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H.%M")


def _pct(x):
    return f"{round(x)} persen"


def tempat_ai(ai):
    """Where the selector ran, in words."""
    if ai["device_kind"] == "emulator":
        return "di laptop (mode demo: ESP32 tiruan tidak menjalankan AI)"
    if ai["day"]["on_esp32"] or (ai["now"] or {}).get("on_esp32"):
        return "di ESP32"
    esp = ai.get("esp32") or {}
    return "di laptop (firmware ESP32 belum memuat model AI)" if not esp.get("weights") else "di laptop"


def susunan(t):
    """A wiring in words: 'seri (4S)'."""
    from shadeshift.kebiasaan import SUSUNAN
    return SUSUNAN.get(t, t)


def kalimat_ai(ai):
    """The selector's advice in plain words for the analyser box: (now, day). Recommendations only."""
    if not ai or not ai.get("now"):
        return [], []
    n = ai["now"]
    if ai.get("wiring") == n["choice"]:
        now = [f"Saran AI: rangkaian {susunan(n['choice'])} sudah paling cocok untuk kondisi sekarang."]
    else:
        now = [f"Saran AI: rangkaian {susunan(n['choice'])} bisa memberi daya lebih besar untuk kondisi sekarang. "
               "Rangkaian tidak diubah otomatis."]
    by = sorted(ai["day"]["by_choice"].items(), key=lambda x: -x[1])
    day = []
    if ai["day"]["n"] and by:
        top, k = by[0]
        day = [f"Saran AI dalam 24 jam: rangkaian {susunan(top)} paling cocok pada {k} dari {ai['day']['n']} pengukuran."]
    return now, day


# The six causes of the diagnosis AI (firmware DIAG, CONTRACT §23) in words.
KELAS_DIAGNOSIS = {"normal": "Normal", "partial_shading": "Bayangan sebagian", "uniform_dimming": "Cahaya redup merata",
                   "bypass_open": "Dioda pelewat terbuka", "bypass_short": "Dioda pelewat terhubung singkat",
                   "series_resistance": "Hambatan kabel atau sambungan tinggi"}
_ALASAN = [("belum ada model", "model diagnosis belum dipasang di ESP32"),
           ("no diagnosis model", "model diagnosis belum dipasang di ESP32"),
           ("demo mode", "ESP32 tiruan (mode demo) tidak menjalankan diagnosis AI"),
           ("no answer", "ESP32 tidak menjawab dalam 120 detik"),
           ("pindah ke", "perpindahan relai gagal"), ("titik valid", "titik pengukuran terlalu sedikit"),
           ("sapuan", "pengukuran kurva gagal"), ("Pmax 4S nol", "daya susunan 4S nol, kemungkinan tidak ada cahaya"),
           ("dihentikan", "dihentikan"), ("stopped", "dihentikan"), ("busy", "alat sedang menjalankan tugas lain")]


def nama_kelas(cls):
    return KELAS_DIAGNOSIS.get(cls, cls)


def alasan_diagnosis(msg):
    """Why a diagnosis failed, in words, from the firmware or gateway message."""
    return next((kata for kunci, kata in _ALASAN if kunci in (msg or "")), "galat sistem")


def kalimat_diagnosis(diag, kondisi_now=None):
    """Sentences about the diagnosis AI for the analyser box: (now lines, basis sentence). The model judges the whole
    array; the panel comes from the per-panel check, so both are said side by side."""
    if not diag:
        return [], ""
    now, n, f = [], diag.get("now"), diag.get("failed")
    if n:
        yakin = f", keyakinan {round(n['confidence'] * 100)} persen" if n.get("confidence") is not None else ""
        now.append(f"AI di ESP32 menilai penyebabnya: {n['nama'].lower()}{yakin}, dari pengukuran pukul {_jam(n['at'])} dengan "
                   "empat cara merangkai panel."
                   if n["class"] != "normal" else f"AI di ESP32 menilai susunan normal{yakin}, diukur pukul {_jam(n['at'])}.")
        panels = sorted({p["panel"] for p in (kondisi_now or {}).get("problems", []) if p.get("panel")})
        if n["class"] != "normal" and panels:
            now.append(f"Panel yang terdampak menurut pemeriksaan tiap panel: {', '.join(panels)}.")
    if f and (not n or f["at"] > n["at"]):
        now.append(f"Diagnosis AI di ESP32 terakhir gagal pukul {_jam(f['at'])}: {f['text']}.")
    if n:
        basis = " Diagnosis penyebab: model AI di ESP32, menilai seluruh susunan dari empat kurva, bukan per panel."
    else:
        basis = " Diagnosis penyebab oleh AI di ESP32: " + (diag.get("why") or "belum dijalankan.")
    return now, basis


def ringkasan(array, panel_now, kondisi_now, history, hours=24, ai=None, diag=None, model=None):
    """The analyser boxes in a home owner's words. array: [{"at", "topology", "pmax", "expected", "analysis"}] oldest
    first (24 h); panel_now: {A: analysis} of the last panel check or {}; kondisi_now: kondisi.assess(); history:
    kondisi.history(); model: {"nilai": sentence on the newest, "tren": sentence or None, "basis": sentence} from the light
    model (kebiasaan). Returns {"day": {"headline", "lines"}, "now": {"headline", "lines"}, "basis"}."""
    n = len(array)
    day = []
    if not n and not history["rounds"]:
        day.append(f"Belum ada pengukuran dalam {hours} jam terakhir. Nyalakan pemantauan di Beranda agar panel diperiksa otomatis.")
    else:
        day.append(f"Dalam {hours} jam terakhir panel diukur {n} kali dan diperiksa satu per satu {history['rounds']} kali.")
    seen = {}
    for a in array:
        for c in codes(a["analysis"]):
            seen.setdefault(c, []).append(a["at"])
    for c, times in sorted(seen.items(), key=lambda x: -len(x[1]))[:3]:
        name, plain = MUDAH[c]
        when = f"pukul {_jam(times[0])}" if len(times) == 1 else f"pukul {_jam(times[0])} sampai {_jam(times[-1])}"
        day.append(f"Tanda {name.lower()} terlihat pada {len(times)} dari {n} pengukuran ({when}). {plain}")
    for s in history["summary"]:
        if "persen dari perkiraan normal" not in s:
            day.append(s)
    pcts = [(a["pmax"] / a["expected"] * 100, a["at"]) for a in array if a.get("expected")]
    if pcts:
        avg = sum(p for p, _ in pcts) / len(pcts)
        low = min(pcts)
        day.append(f"Rata-rata daya {_pct(avg)} dari perkiraan normal; paling rendah {_pct(low[0])} pukul {_jam(low[1])}.")
    bad_states = {e["state"] for e in history["events"]}
    if n and not (seen.keys() & {3, 5}) and not (bad_states & {"diode", "cable"}):
        day.append("Tidak ada tanda kerusakan kabel atau komponen di dalam panel.")
    if model and model.get("tren"):
        day.append(model["tren"])
    if seen or (bad_states - {"normal"}):
        day_head = "Ada tanda gangguan dalam 24 jam terakhir" if seen else "Ada panel yang sempat bermasalah"
    else:
        day_head = "Panel bekerja normal dalam 24 jam terakhir" if n else "Belum ada data 24 jam"

    now = [kondisi_now["status"]["text"] + "."]
    last = array[-1] if array else None
    if last:
        found = last["analysis"].get("anomalies") or []
        now.append(f"Pengukuran terakhir pukul {_jam(last['at'])}: " + (f"{found[0]['mudah'].lower()}. {found[0]['mudah_arti']}"
                   if found else "tidak ada tanda gangguan."))
        if last.get("expected"):
            now.append(f"Daya {str(round(last['pmax'], 2)).replace('.', ',')} watt, {_pct(last['pmax'] / last['expected'] * 100)} "
                       "dari perkiraan normal.")
    if model and model.get("nilai"):
        now.append(model["nilai"])
    for m, an in sorted(panel_now.items()):
        found = an.get("anomalies") or []
        if found:
            now.append(f"Panel {m}: {found[0]['mudah'].lower()}.")
    ai_now, ai_day = kalimat_ai(ai)
    now.extend(ai_now)
    day.extend(ai_day)
    diag_now, diag_basis = kalimat_diagnosis(diag, kondisi_now)
    now.extend(diag_now)
    where = tempat_ai(ai) if ai and ai.get("now") else None
    return {"day": {"headline": day_head, "lines": day}, "now": {"headline": kondisi_now["status"]["text"], "lines": now[1:]},
            "basis": "Cara kerja: tanda gangguan dibaca dari bentuk kurva dan pemeriksaan tiap panel, dihitung di laptop; "
                     "belum divalidasi dengan data lapangan, jadi setiap penyebab adalah kemungkinan."
                     + (" " + model["basis"] if model and model.get("basis") else "")
                     + (f" Saran rangkaian: model AI kecil yang berjalan {where}." if where else "")
                     + diag_basis}
