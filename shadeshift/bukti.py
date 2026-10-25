"""Bukti page for the consumer view (docs/CONTRACT.md §24): the proposal's promises and four targets next to their
evidence, in plain Indonesian, plus the trial runs on the real board.

Pure functions; the server passes the facts in (Core.bukti_facts). Only data from a real ESP32 counts as proof: demo data
never does. Lab, simulation and calculation numbers are shown as comparisons, each labelled. The automatic
reconfiguration of the wiring is left out on purpose (it waits for the Indonesian standard question)."""
from shadeshift import kondisi

TERBUKTI, SEBAGIAN, BELUM = "Terbukti", "Sebagian", "Belum"
TERPENUHI, TIDAK, BELUM_DIUKUR = "Terpenuhi", "Belum terpenuhi", "Belum diukur"
TRIAL_TARGET = 3
# The five checks of one full trial run on the board, in the order they happen.
CEK_UJI = (("firmware", "AI di ESP32 aktif"), ("susunan", "Kurva susunan terukur"), ("ai", "Rekomendasi AI dari ESP32"),
           ("panel", "Empat panel diperiksa"), ("stop", "Berhenti aman dikonfirmasi"))


def _ms(us):
    return kondisi.angka(us / 1000.0, 2)


def uji_coba(trials):
    """trials: [{run_id, device_id, started_at, checks: {key: bool}}] -> rows in words and the number of full trials."""
    rows = []
    for t in trials:
        ok = all(t["checks"].get(k) for k, _ in CEK_UJI)
        rows.append({"mulai": t["started_at"], "alat": t["device_id"], "lengkap": ok,
                     "cek": [{"nama": nama, "ok": bool(t["checks"].get(k))} for k, nama in CEK_UJI],
                     "kurang": [nama for k, nama in CEK_UJI if not t["checks"].get(k)]})
    return {"target": TRIAL_TARGET, "lengkap": sum(r["lengkap"] for r in rows), "rows": rows[::-1]}


def janji(f, uji):
    """The proposal's promises (without the automatic reconfiguration) with their status in words."""
    esp = f["esp32"]
    out = [{"janji": "Dasbor web lokal: kurva I-V, kondisi panel, peringatan", "status": TERBUKTI,
            "bukti": "Beranda, Kurva I-V dan Riwayat berjalan di laptop ini tanpa internet."},
           {"janji": "Jejak audit: siapa melakukan apa dan kapan", "status": TERBUKTI,
            "bukti": f"{f['audit_n']} catatan tersimpan. Riwayat, tab Jejak audit, dapat diunduh sebagai CSV."}]
    if esp["web"]:
        out.append({"janji": "Halaman web langsung dari ESP32", "status": TERBUKTI,
                    "bukti": "ESP32 melaporkan halaman webnya aktif. Sambungkan ke Wi-Fi SHADESHIFT, buka 192.168.4.1."})
    else:
        out.append({"janji": "Halaman web langsung dari ESP32", "status": SEBAGIAN,
                    "bukti": "Ada di firmware 3.2 dan diuji di laptop; belum dijalankan di papan."})
    d = f["decisions_esp32"]
    if d["n"]:
        out.append({"janji": "AI pemilih susunan berjalan di ESP32 (TinyML)", "status": TERBUKTI,
                    "bukti": f"{d['n']} rekomendasi dihitung di ESP32, median {_ms(d['median_us'])} milidetik."})
    else:
        out.append({"janji": "AI pemilih susunan berjalan di ESP32 (TinyML)", "status": SEBAGIAN,
                    "bukti": "Ada di firmware 3.2; jawabannya sama dengan model laptop pada 38 dari 38 kurva lab. "
                             "Belum dijalankan di papan."})
    g = f["diagnosis"]
    if g["n"]:
        out.append({"janji": "Diagnosis penyebab oleh AI di ESP32 (enam kelas)", "status": TERBUKTI,
                    "bukti": f"{g['n']} diagnosis dihitung di ESP32. Ketepatannya dinilai pada target di bawah."})
    else:
        out.append({"janji": "Diagnosis penyebab oleh AI di ESP32 (enam kelas)", "status": SEBAGIAN if g["on_board"] else BELUM,
                    "bukti": "Model terpasang di ESP32, belum dijalankan." if g["on_board"] else
                             "Jalur dari ESP32 ke halaman ini siap. Model belum dilatih dengan data lapangan, jadi "
                             "penyebab di halaman ini masih dari aturan di laptop."})
    out.append({"janji": "Lapisan saklar semikonduktor hemat daya", "status": SEBAGIAN,
                "bukti": "Desain dan hitungan (0,13 sampai 0,23 W); belum dibangun. Rinciannya di bagian Daya kendali."})
    n = uji["lengkap"]
    out.append({"janji": f"Minimal {TRIAL_TARGET} uji coba penuh di papan sebelum Demo Day",
                "status": TERBUKTI if n >= TRIAL_TARGET else SEBAGIAN if n else BELUM,
                "bukti": f"{n} dari {TRIAL_TARGET} uji coba penuh tercatat dari ESP32 nyata."})
    return out


def target(f):
    """The four targets: status, measured evidence, comparisons (labelled), what is still needed."""
    out = []
    m, rel = f["summary"].get("mlpe"), f["summary"].get("relative")
    terukur = []
    if m:
        terukur.append(f"AI memulihkan {kondisi.angka(m['recovery_pts'])} poin dibanding susunan tetap terbaik "
                       f"{m['best_fixed']} ({m['n']} putaran dengan sapuan tiap panel).")
    if rel:
        terukur.append(f"Rugi AI {kondisi.angka(rel['ai_loss_pct'])} persen dibanding {kondisi.angka(rel['best_fixed_loss_pct'])} "
                       f"persen untuk susunan tetap terbaik {rel['best_fixed']} ({rel['n']} putaran).")
    out.append({"target": "Memulihkan minimal 4 poin daya dari MLPE ideal dibanding susunan tetap terbaik",
                "status": (TERPENUHI if m["met"] else TIDAK) if m else BELUM_DIUKUR, "terukur": terukur,
                "pembanding": ["Simulasi: 3,35 poin.",
                               "Lab (lampu halogen, 30 set): rugi AI 0,82 persen dibanding 2,71 persen untuk susunan tetap terbaik."],
                "perlu": None if m else "Pemindaian lengkap di papan dengan sapuan tiap panel (firmware 3.2)."})
    a = f["diagnosis_model"]
    terukur, status, perlu = [], BELUM_DIUKUR, ("Data luar ruangan berlabel dari dua hari, lalu model dilatih dan diuji "
                                                "pada hari yang berbeda.")
    if a and a.get("evidence") == "real":
        luar = a.get("accuracy_outdoor")
        hari_lain = (a.get("test_mode") or "").startswith("held-out day")
        if luar is not None:
            status = TERPENUHI if luar >= 85 and hari_lain else TIDAK
            perlu = None if hari_lain else "Uji pada hari yang berbeda dari data latih."
            terukur.append(f"Ketepatan {kondisi.angka(luar, 1)} persen pada {a.get('n_test_outdoor')} kurva uji luar ruangan.")
        else:
            terukur.append(f"Ketepatan {kondisi.angka(a.get('accuracy') or 0, 1)} persen pada data uji dalam ruangan.")
            perlu = "Kurva luar ruangan di data uji."
    terukur.append(f"Kurva luar ruangan berlabel yang sudah terkumpul: {f['labelled_outdoor']} (sasaran sekitar 360).")
    out.append({"target": "Diagnosis penyebab (enam kelas) minimal 85 persen tepat pada data luar ruangan",
                "status": status, "terukur": terukur,
                "pembanding": ["Simulasi: 78 sampai 82 persen.", "Pada kurva lab, model dari simulasi hanya 3 sampai 13 persen tepat."],
                "perlu": perlu})
    p = f["power"]
    terukur = [f"ESP32 {kondisi.angka(e['device_power_w'], 3)} W ditambah relai {kondisi.angka(e['relay_power_w'], 3)} W "
               f"= {kondisi.angka(e['value'], 3)} W" + (f", susunan {e['topology']}" if e.get("topology") else "") + "."
               for e in p]
    out.append({"target": "Daya kendali paling besar 0,25 W",
                "status": (TERPENUHI if min(e["value"] for e in p) <= 0.25 else TIDAK) if p else BELUM_DIUKUR,
                "terukur": terukur,
                "pembanding": ["Hitungan: relai 1,43 sampai 2,50 W, tergantung susunan.",
                               "Hitungan desain saklar semikonduktor: 0,13 sampai 0,23 W (belum dibangun)."],
                "perlu": None if p else "Ukur arus ESP32 dan relai dengan multimeter, lalu catat di bagian Daya kendali."})
    d = f["decisions_esp32"]
    out.append({"target": "Keputusan susunan di ESP32 dalam hitungan milidetik",
                "status": (TERPENUHI if d["max_us"] < 1e6 else TIDAK) if d["n"] else BELUM_DIUKUR,
                "terukur": [f"Median {_ms(d['median_us'])} milidetik, paling lama {_ms(d['max_us'])} milidetik, "
                            f"dari {d['n']} keputusan di ESP32."] if d["n"] else [],
                "pembanding": [f"Model yang sama di laptop: median {_ms(f['decisions_laptop']['median_us'])} milidetik "
                               f"({f['decisions_laptop']['n']} keputusan)."] if f["decisions_laptop"]["n"] else [],
                "perlu": None if d["n"] else "Firmware 3.2 di papan: ESP32 mencetak waktu hitungnya pada setiap keputusan."})
    return out


def susun(f):
    uji = uji_coba(f["trials"])
    return {"janji": janji(f, uji), "target": target(f), "uji_coba": uji, "demo_only": f["demo_only"],
            "catatan": "Hanya data dari ESP32 nyata yang dihitung sebagai bukti. Angka lab, simulasi dan hitungan "
                       "ditampilkan sebagai pembanding."}
