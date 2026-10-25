"""Jejak audit (audit trail) for the consumer view (docs/CONTRACT.md §22): who did what and when, in plain Indonesian.

Pure functions; the server passes the rows in. Sources: the events table (commands, relay switches, warnings, errors,
monitoring, device status), the AI decisions (one per sweep, the ESP32's preferred over the laptop's cross-check), the
sweeps (measurements) and the panel condition changes (kondisi.history). Each entry says who acted:
"Pengguna" (a person pressed a button), "AI di ESP32" / "AI di laptop", "Sistem" (gateway or server) or "Perangkat"
(the ESP32 itself). By default only the important entries are listed and routine work is summed up in one line per day;
`semua=True` lists every measurement and every AI result. The original message is kept in `asli` (CSV column).
Demo data (the emulated ESP32) is marked `demo` and shown as "Mode demo"; nothing here turns demo data into measured."""
import re
from datetime import datetime

from shadeshift import kondisi
from shadeshift.analisis_kurva import alasan_diagnosis, nama_kelas

ULANG_S = 1800                   # a power warning for the same wiring within 30 min is a repeat (counted per day)
_DIAG = re.compile(r"ESP32 diagnosis: (\S+) \(confidence ([\d.]+)")
_PMAX = re.compile(r"Pmax [+-][\d.]+ % vs twin expectation for (\S+)")
BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
NAMA_AKSI = {"stop": "Hentikan semua", "monitor_start": "Mulai pemantauan", "monitor_stop": "Hentikan pemantauan",
             "panel_check": "Periksa setiap panel", "measure_now": "Ukur sekarang", "auto_select": "Pilih susunan dengan AI",
             "auto_mode_start": "Mulai mode otomatis", "auto_mode_stop": "Hentikan mode otomatis",
             "audit_decision": "Periksa keputusan AI", "cycle": "Ukur semua susunan", "full_scan": "Pemindaian lengkap",
             "demo_condition": "Ganti kondisi demo", "demo_scenario_start": "Mulai skenario demo",
             "demo_scenario_stop": "Hentikan skenario demo", "diagnose": "Diagnosis dengan AI",
             "compare_wirings": "Bandingkan semua rangkaian", "apply_wiring": "Ubah rangkaian"}
NAMA_RANGKAIAN = {"4S": "seri (4S)", "2S2P": "seri-paralel (2S2P)", "TCT": "silang (TCT)", "4P": "paralel (4P)",
                  "open": "semua relai terbuka"}
# category filter -> kinds of entry (`jenis`)
KATEGORI = {"semua": None,
            "perintah": {"Perintah"},
            "relai": {"Perpindahan relai"},
            "ai": {"Keputusan AI"},
            "peringatan": {"Peringatan", "Galat"},
            "sistem": {"Pemantauan", "Perangkat", "Pengukuran", "Catatan", "Ringkasan harian"}}


def _lokal(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()


def waktu(iso):
    """'22 Okt 2026, 14.05' in the laptop's local time."""
    t = _lokal(iso)
    return f"{t.day} {BULAN[t.month - 1]} {t.year}, {t:%H.%M}"


def tanggal(iso):
    t = _lokal(iso)
    return f"{t.day} {BULAN[t.month - 1]} {t.year}"


def aksi(command):
    return NAMA_AKSI.get(command, command)


def _ai(decided_by):
    return "AI di ESP32" if decided_by == "esp32" else "AI di laptop"


def _detik(s):
    return kondisi.angka(float(s), 0 if float(s) == int(float(s)) else 1)


def _mode(m):
    return {"stopped": "dihentikan", "started": "dimulai"}.get(m, m)


# (pattern, who, kind, important, text) for event messages; text may use the match groups and `d` (the event data).
_POLA = [
    # ---- commands queued by a person (dashboard buttons, API) ----
    (r"queued action: stop \(stop all\)", "Pengguna", "Perintah", True, lambda g, d: "Pengguna menekan Hentikan semua"),
    (r"queued action: full_scan (\S+)", "Pengguna", "Perintah", True,
     lambda g, d: f"Pengguna memulai pemindaian lengkap, kondisi {g[0]}"),
    (r"queued action: (\S+)", "Pengguna", "Perintah", True, lambda g, d: f"Pengguna meminta {aksi(g[0])}"),
    (r"queued raw: (.+)", "Pengguna", "Perintah", True, lambda g, d: f"Pengguna mengirim perintah langsung ke ESP32: {g[0]}"),
    # ---- results of commands ----
    (r"stop: tasks cancelled, device confirmed all relays open", "Perangkat", "Perintah", True,
     lambda g, d: "ESP32 memastikan semua relai terbuka setelah perintah berhenti"),
    (r"stop: OFF sent but the device did not confirm", "Perangkat", "Galat", True,
     lambda g, d: "Perintah berhenti dikirim, tetapi ESP32 tidak mengonfirmasi dalam 10 detik"),
    (r"diagnose: failed \((.*)\)", "Sistem", "Galat", True,
     lambda g, d: f"Diagnosis dengan AI tidak berjalan: {alasan_diagnosis(g[0])}"),
    (r"(\S+): done", "Sistem", "Perintah", False, lambda g, d: f"Perintah {aksi(g[0])} selesai"),
    (r"(\S+): (failed|expired)", "Sistem", "Galat", True,
     lambda g, d: f"Perintah {aksi(g[0])} {'gagal' if g[1] == 'failed' else 'kedaluwarsa sebelum dijalankan'}"),
    # ---- monitoring and the hidden automatic mode ----
    (r"monitoring started: (\S+) every ([\d.]+) s", "Sistem", "Pemantauan", True,
     lambda g, d: f"Pemantauan dimulai: susunan {g[0]} diukur setiap {_detik(g[1])} detik"),
    (r"monitoring stopped", "Sistem", "Pemantauan", True, lambda g, d: "Pemantauan dihentikan"),
    (r"monitoring: switch back to (\S+) failed", "Sistem", "Galat", True,
     lambda g, d: f"Pemantauan: gagal kembali ke susunan {g[0]}"),
    (r"monitoring: (\S+) sweep failed", "Sistem", "Galat", True,
     lambda g, d: f"Pemantauan: pengukuran susunan {g[0]} gagal"),
    (r"auto mode (started|stopped)", "Sistem", "Pemantauan", True, lambda g, d: f"Mode otomatis {_mode(g[0])}"),
    (r"panel (\S) check failed", "Sistem", "Galat", True, lambda g, d: f"Pemeriksaan panel {g[0]} gagal"),
    # ---- relays and the AI ----
    (r"4S -> (\S+) \(selector, (\S+)\)", None, "Perpindahan relai", True,
     lambda g, d: f"Relai dipindah dari susunan 4S ke {g[0]} atas pilihan AI"),
    (r"selector kept (\S+)", None, "Keputusan AI", True, lambda g, d: f"AI mempertahankan susunan {g[0]}"),
    (r"stability rule: TCT locked", "Sistem", "Perpindahan relai", True,
     lambda g, d: "Aturan stabilitas mengunci susunan TCT"),
    (r"stability rule: lock released", "Sistem", "Perpindahan relai", True,
     lambda g, d: "Aturan stabilitas melepas kunci susunan TCT"),
    (r"ESP32 chose (\S+), laptop cross-check \((\S+)\) chose (\S+)", "AI di ESP32", "Keputusan AI", True,
     lambda g, d: f"AI di ESP32 memilih {g[0]}, pemeriksaan silang di laptop memilih {g[2]}"),
    (r"audit: AI \((\S+)\) chose (\S+), measured best (\S+), loss ([\d.]+) %", "Sistem", "Keputusan AI", True,
     lambda g, d: f"Pemeriksaan keputusan AI: AI memilih {g[1]}, yang terbaik terukur {g[2]}, "
                  f"selisih {kondisi.angka(float(g[3]))} persen"),
    (r"ESP32 diagnosis: (\S+) \(confidence ([\d.]+)", "AI di ESP32", "Keputusan AI", True,
     lambda g, d: f"Diagnosis AI di ESP32: {nama_kelas(g[0])}, keyakinan {round(float(g[1]) * 100)} persen"),
    (r"DIAG GAGAL: (.*)|DIAG: (no answer)", "Perangkat", "Galat", True,
     lambda g, d: f"Diagnosis AI di ESP32 gagal: {alasan_diagnosis(g[0] or g[1])}"),
    (r"selection failed", "Sistem", "Galat", True, lambda g, d: "Pemilihan susunan oleh AI gagal"),
    (r"selection (\S+) not applied", "Sistem", "Galat", True,
     lambda g, d: f"Rekomendasi AI {g[0]} tidak dapat diterapkan"),
    (r"ESP32 selector weights .* differ", "Perangkat", "Galat", True,
     lambda g, d: "Bobot AI di ESP32 berbeda dengan model di laptop: perbarui firmware"),
    # ---- warnings ----
    (r"Pmax ([+-][\d.]+) % vs twin expectation for (\S+)", "Sistem", "Peringatan", True,
     lambda g, d: f"Daya semua panel {kondisi.angka(abs(float(g[0])), 1)} persen "
                  f"{'di bawah' if float(g[0]) < 0 else 'di atas'} perkiraan normal (rangkaian {g[1]})"),
    # ---- connection and device status ----
    (r"connected to serial (\S+)", "Sistem", "Perangkat", True, lambda g, d: f"Sistem terhubung ke ESP32 melalui {g[0]}"),
    (r"connected to emulated ESP32", "Sistem", "Perangkat", True, lambda g, d: "Sistem terhubung ke ESP32 tiruan (mode demo)"),
    (r"ESP32 firmware (\S+) with the same selector weights", "Perangkat", "Perangkat", True,
     lambda g, d: f"ESP32 melaporkan firmware {g[0]} dengan bobot AI yang sama: AI di ESP32 aktif"),
    (r"ESP32 firmware (\S+)", "Perangkat", "Perangkat", True, lambda g, d: f"ESP32 melaporkan firmware {g[0]}"),
    (r"serial connection lost", "Perangkat", "Galat", True, lambda g, d: "Sambungan ke ESP32 terputus"),
    (r"serial reconnected", "Sistem", "Perangkat", True, lambda g, d: "Sambungan ke ESP32 pulih"),
    (r"run started", "Sistem", "Perangkat", True, lambda g, d: "Gateway mulai berjalan"),
    (r"gateway stopped", "Sistem", "Perangkat", True, lambda g, d: "Gateway berhenti"),
    # ---- demo mode ----
    (r"DEMO scenario '([^']+)' started", "Sistem", "Catatan", False, lambda g, d: f"Skenario demo {g[0]} dimulai"),
    (r"DEMO scenario '([^']+)' ended", "Sistem", "Catatan", False, lambda g, d: f"Skenario demo {g[0]} selesai"),
    (r"DEMO scenario '([^']+)' repeats", "Sistem", "Catatan", False, lambda g, d: f"Skenario demo {g[0]} diulang"),
    (r"DEMO step (\d+)/(\d+): (\S+)", "Sistem", "Catatan", False,
     lambda g, d: f"Skenario demo langkah {g[0]} dari {g[1]}: kondisi {g[2]}"),
    (r"emulated condition -> (\S+)", "Sistem", "Catatan", False, lambda g, d: f"Kondisi demo diganti ke {g[0]}"),
    # ---- settings, models, files ----
    (r"settings changed", "Pengguna", "Perintah", True, lambda g, d: "Pengguna mengubah pengaturan"),
    (r"wiring change approved by the user: (\S+) -> (\S+)", "Pengguna", "Perintah", True,
     lambda g, d: f"Pengguna menyetujui perubahan rangkaian dari {NAMA_RANGKAIAN.get(g[0], g[0])} ke {NAMA_RANGKAIAN.get(g[1], g[1])}"),
    (r"wiring (\S+) -> (\S+) \(approved by the user\)", "Perangkat", "Perpindahan relai", True,
     lambda g, d: f"Relai memindah rangkaian dari {NAMA_RANGKAIAN.get(g[0], g[0])} ke {NAMA_RANGKAIAN.get(g[1], g[1])}"),
    (r"wiring change to (\S+) failed", "Perangkat", "Galat", True,
     lambda g, d: f"Perubahan rangkaian ke {NAMA_RANGKAIAN.get(g[0], g[0])} gagal; semua relai dibuka demi keamanan"),
    (r"wirings compared: (\d+) of (\d+)", "Sistem", "Pengukuran", False,
     lambda g, d: f"Semua rangkaian dibandingkan: {g[0]} dari {g[1]} terukur"),
    (r"compare: (\S+) sweep failed", "Sistem", "Galat", True,
     lambda g, d: f"Perbandingan: pengukuran rangkaian {NAMA_RANGKAIAN.get(g[0], g[0])} gagal"),
    (r"maintenance: (cleaned|repaired)(?: panel=(\S))?", "Pengguna", "Perintah", True,
     lambda g, d: f"Pengguna mencatat: panel {'dibersihkan' if g[0] == 'cleaned' else 'diperbaiki teknisi'}"
                  + (f" (panel {g[1]})" if g[1] else "")),
    (r"model activated: (\S+)", "Pengguna", "Perintah", True, lambda g, d: f"Pengguna mengaktifkan model {g[0]}"),
    (r"upload: (\d+) accepted", "Pengguna", "Perintah", True,
     lambda g, d: f"Pengguna mengunggah berkas CSV: {g[0]} kurva diterima"),
    (r"imported session \S+: (\d+) scans, (\d+) sweeps", "Pengguna", "Perintah", True,
     lambda g, d: f"Pengguna mengimpor sesi: {g[0]} pemindaian, {g[1]} kurva"),
    (r"lab import: (\d+) imported", "Sistem", "Catatan", False, lambda g, d: f"Data lab dimuat: {g[0]} kurva"),
    (r"full scan (\S+): round u(\d+) done", "Sistem", "Pengukuran", False,
     lambda g, d: f"Pemindaian lengkap {g[0]}: putaran {g[1]} selesai"),
]
_POLA = [(re.compile(p), *rest) for p, *rest in _POLA]
_SISA = {"error": ("Sistem", "Galat", True, "Galat sistem"), "alert": ("Sistem", "Peringatan", True, "Peringatan sistem"),
         "switch": ("Sistem", "Perpindahan relai", True, "Relai dipindah"), "command": ("Sistem", "Perintah", True, "Perintah"),
         "status": ("Sistem", "Perangkat", True, "Status perangkat berubah"), "info": ("Sistem", "Catatan", False, "Catatan sistem")}


def dari_kejadian(ev, demo=False):
    """One events-table row -> an entry. Unknown messages get a generic sentence; the original stays in `asli`."""
    msg, data = ev["message"], ev.get("data") or {}
    for pola, siapa, jenis, penting, teks in _POLA:
        m = pola.match(msg)
        if m:
            if siapa is None:                                  # who decided a switch: the ESP32 or the laptop
                siapa = _ai(m.groups()[-1]) if jenis == "Perpindahan relai" else "AI"
            return _entri(ev["created_at"], siapa, jenis, teks(m.groups(), data), penting,
                          demo or msg.startswith("DEMO"), msg)
    siapa, jenis, penting, teks = _SISA.get(ev["kind"], _SISA["info"])
    return _entri(ev["created_at"], siapa, jenis, teks, penting, demo or msg.startswith("DEMO"), msg)


def _entri(at, siapa, jenis, teks, penting, demo, asli="", urut=0, kunci=None):
    return {"at": at, "waktu": waktu(at), "siapa": siapa, "jenis": jenis, "teks": teks, "penting": bool(penting),
            "demo": bool(demo), "asli": asli, "_urut": urut, "_kunci": kondisi._epoch(at) if kunci is None else kunci}


def _akhir_hari(iso):
    """Epoch of the end of the local day of `iso` (the day's summary sorts above that day's entries)."""
    from datetime import timedelta
    t = _lokal(iso).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return t.timestamp() - 0.001


def pilih_keputusan(decisions):
    """One decision per sweep (dicts with sweep_id, captured_at, choice, decided_by, latency_us), the ESP32's preferred,
    oldest first."""
    per = {}
    for d in decisions:
        cur = per.get(d["sweep_id"])
        if cur is None or (d["decided_by"] == "esp32" and cur["decided_by"] != "esp32"):
            per[d["sweep_id"]] = d
    return sorted(per.values(), key=lambda d: (d["captured_at"], d["sweep_id"]))


def dari_keputusan(decisions, sebelum=None, semua=False, demo=False):
    """AI results -> entries. Default: only when the recommendation changes (against `sebelum`, the last choice before
    the period); `semua`: every result, with the time it took."""
    out, prev = [], sebelum
    for d in pilih_keputusan(decisions):
        siapa, berubah = _ai(d["decided_by"]), d["choice"] != prev
        if berubah and prev:
            teks = f"{siapa} mengubah rekomendasi dari {prev} ke {d['choice']}"
        elif berubah:
            teks = f"{siapa} merekomendasikan susunan {d['choice']}"
        else:
            teks = f"{siapa} tetap merekomendasikan susunan {d['choice']}"
        if d.get("latency_us") is not None and semua:
            teks += f", dihitung dalam {kondisi.angka(d['latency_us'] / 1000.0, 2)} milidetik"
        if d.get("applied"):
            teks += ", dan diterapkan"
        if berubah or semua:
            out.append(_entri(d["captured_at"], siapa, "Keputusan AI", teks, berubah, demo or d.get("source") == "demo",
                              f"decision sweep={d['sweep_id']} by={d['decided_by']} choice={d['choice']}", 1))
        prev = d["choice"]
    return out


def dari_pengukuran(sweeps, demo=False):
    """Every complete sweep -> an entry (only with `semua`)."""
    out = []
    for s in sweeps:
        bagian = f"panel {s['topology']}" if s["topology"] in kondisi.PANELS else f"susunan {s['topology']}"
        daya = f", daya maksimum {kondisi.angka(s['pmax'], 3)} W" if s.get("pmax") is not None else ""
        oleh = "ESP32 tiruan" if s.get("source") == "demo" else "ESP32"
        out.append(_entri(s["captured_at"], "Perangkat", "Pengukuran", f"{oleh} mengukur kurva I-V {bagian}{daya}", False,
                          demo or s.get("source") == "demo", f"sweep {s['id']} {s['topology']}", 2))
    return out


def dari_kondisi(events, demo=False):
    """Panel condition changes from kondisi.history -> warnings (a panel back to normal is important too)."""
    return [_entri(e["at"], "Sistem", "Peringatan" if e["state"] != "normal" else "Pemantauan", e["text"], True, demo,
                   f"kondisi panel {e['panel']} {e['state']}") for e in events]


def tandai_diagnosis(entries, sebelum=None):
    """Diagnosis results: important only when the cause changes (against `sebelum`, the last class before the period),
    worded as the change."""
    prev = sebelum
    for e in sorted((e for e in entries if _DIAG.match(e["asli"] or "")), key=lambda e: e["_kunci"]):
        cls, conf = _DIAG.match(e["asli"]).groups()
        e["penting"] = cls != prev
        if prev and cls != prev:
            e["teks"] = (f"AI di ESP32 mengubah diagnosis dari {nama_kelas(prev)} ke {nama_kelas(cls)}, "
                         f"keyakinan {round(float(conf) * 100)} persen")
        prev = cls


def tandai_ulangan(entries):
    """Power warnings come with every measurement while the power stays low: only the first one (no warning for the
    same wiring in the previous ULANG_S) is important; the repeats become routine. Returns {day: number of warnings}."""
    akhir, per_hari = {}, {}
    for e in sorted((e for e in entries if _PMAX.match(e["asli"] or "")), key=lambda e: e["_kunci"]):
        topo = _PMAX.match(e["asli"]).group(1)
        e["penting"] = e["_kunci"] - akhir.get(topo, float("-inf")) > ULANG_S
        akhir[topo] = e["_kunci"]
        per_hari[tanggal(e["at"])] = per_hari.get(tanggal(e["at"]), 0) + 1
    return per_hari


def ringkasan_harian(sweeps, decisions, demo=False, peringatan=None):
    """One line per local day with the routine work: measurements, panel checks, the AI's recommendations and the
    number of power warnings."""
    hari = {}
    for s in sweeps:
        h = hari.setdefault(tanggal(s["captured_at"]), {"at": s["captured_at"], "susunan": 0, "panel": [], "ai": {}})
        h["at"] = max(h["at"], s["captured_at"])
        if s["topology"] in kondisi.PANELS:
            h["panel"].append(s)
        else:
            h["susunan"] += 1
    for d in pilih_keputusan(decisions):
        h = hari.get(tanggal(d["captured_at"]))
        if h:
            h["ai"][d["choice"]] = h["ai"].get(d["choice"], 0) + 1
    out = []
    for nama, h in hari.items():
        bagian = [f"{h['susunan']} pengukuran susunan"]
        n_cek = len(kondisi.rounds(h["panel"]))
        if n_cek or h["panel"]:
            bagian.append(f"{n_cek} pemeriksaan panel")
        if h["ai"]:
            urut = sorted(h["ai"].items(), key=lambda x: (-x[1], x[0]))
            daftar = [f"{c} {n} kali" for c, n in urut]
            bagian.append("AI merekomendasikan " + (daftar[0] if len(daftar) == 1 else ", ".join(daftar[:-1]) + " dan " + daftar[-1]))
        if (peringatan or {}).get(nama):
            bagian.append(f"{peringatan[nama]} peringatan daya di luar harapan")
        out.append(_entri(h["at"], "Sistem", "Ringkasan harian", f"{nama}: " + ", ".join(bagian) + ".", True, demo,
                          "daily summary", -1, _akhir_hari(h["at"])))
        out[-1]["waktu"] = nama
    return out


def susun(events, decisions, sweeps, kondisi_events=(), sebelum=None, semua=False, kategori="semua", demo=False,
          sebelum_diag=None):
    """All entries of a period, newest first (the day's summary above that day's entries). `demo`: the device is the
    emulated ESP32, so every entry is demo data."""
    out = [dari_kejadian(e, demo) for e in events]
    per_hari = tandai_ulangan(out)
    tandai_diagnosis(out, sebelum_diag)
    out += dari_keputusan(decisions, sebelum, semua, demo)
    out += dari_kondisi(kondisi_events, demo)
    out += ringkasan_harian(sweeps, decisions, demo, per_hari)
    if semua:
        out += dari_pengukuran(sweeps, demo)
    else:
        out = [e for e in out if e["penting"]]
    ingin = KATEGORI.get(kategori)
    if ingin is not None:
        out = [e for e in out if e["jenis"] in ingin]
    out.sort(key=lambda e: (e["_kunci"], -e["_urut"]), reverse=True)
    for e in out:
        e.pop("_urut", None)
        e.pop("_kunci", None)
    return out


KOLOM_CSV = ("waktu", "waktu_utc", "siapa", "jenis", "keterangan", "data", "pesan_asli")


def baris_csv(e):
    return [e["waktu"], e["at"], e["siapa"], e["jenis"], e["teks"], "Mode demo" if e["demo"] else "Nyata", e["asli"]]
