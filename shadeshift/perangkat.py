"""Perangkat page for the consumer view (docs/CONTRACT.md §25): the status of every part of the system, in words.

Pure functions; the server passes the facts in (Core.perangkat_facts). Each row says the part, its state (Baik, Perlu
dicek, Belum diperiksa, Tidak terhubung, Tidak tersedia, Mati, Mode demo), what was seen and when. A part is only "Baik"
when something measured or reported shows it working; a part nothing has checked yet says so. In demo mode the
hardware rows say "Mode demo": there is no hardware to check."""
from datetime import datetime, timezone

from shadeshift import kondisi

BAIK, CEK, BELUM, PUTUS, TIDAK_ADA, MATI, DEMO = ("Baik", "Perlu dicek", "Belum diperiksa", "Tidak terhubung",
                                                  "Tidak tersedia", "Mati", "Mode demo")
WORD = {"object": "kemungkinan tertutup benda atau kotoran", "diode": "kemungkinan masalah dioda atau sel",
        "cable": "kemungkinan masalah kabel atau sambungan"}
ADS, DAC = "0x48", ("0x60", "0x62")
STALE_FACTOR = 3                      # the last measurement is late after three monitoring intervals


def _age_s(iso, now):
    return (now - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()


def _row(nama, keadaan, rincian, waktu=None):
    return {"nama": nama, "keadaan": keadaan, "rincian": rincian, "waktu": waktu}


def _newer(err, ok):
    """An error that no success has followed since."""
    return err is not None and (ok is None or err["at"] > ok)


def periksa(f, now=None):
    """f: facts (see Core.perangkat_facts). Returns {ringkasan: {level, text}, grup: [{judul, baris}], demo}."""
    now = now or datetime.now(timezone.utc)
    demo, online, esp, st = f["kind"] == "emulator", f["online"], f["esp32"] or {}, f["state"]
    last, err = f["last_sweep"], f["errors"]
    ok_at = last["at"] if last else None
    feats = esp.get("features") or []

    # ---- connections ----
    sambung = [_row("Server lokal dan dasbor", BAIK, "Berjalan di laptop ini, tanpa internet.")]
    if online:
        tunda = st.get("outbox_pending") or 0
        sambung.append(_row("Gateway (laptop ke alat)", BAIK if not tunda else CEK,
                            "Terhubung." + (f" {tunda} data menunggu dikirim ke server." if tunda else ""), f["last_seen"]))
    else:
        sambung.append(_row("Gateway (laptop ke alat)", PUTUS, "Tidak ada kabar dari gateway. Jalankan start_live.bat.",
                            f["last_seen"]))
    if demo:
        sambung.append(_row("ESP32", DEMO, "ESP32 tiruan: kurva lab yang direkam diputar ulang. Tidak ada perangkat keras."))
        sambung.append(_row("AI di ESP32", DEMO, "ESP32 tiruan tidak menjalankan AI; rekomendasi dihitung di laptop."))
        sambung.append(_row("Halaman Wi-Fi ESP32", DEMO, "Hanya ada pada ESP32 nyata."))
    else:
        port = (f.get("transport") or "").removeprefix("serial:")
        if not online:
            sambung.append(_row("ESP32", PUTUS, "Tidak terhubung. Periksa kabel USB."))
        elif _newer(err.get("serial"), ok_at):
            sambung.append(_row("ESP32", CEK, "Sambungan USB sempat terputus. Periksa kabel USB.", err["serial"]["at"]))
        elif esp.get("fw"):
            lama = not esp["fw"].startswith("3.")
            sambung.append(_row("ESP32", CEK if lama else BAIK, f"Terhubung lewat {port or 'USB'}, firmware {esp['fw']}."
                                + (" Firmware lama: unggah firmware 3.2." if lama else "")))
        else:
            sambung.append(_row("ESP32", CEK, f"Terhubung lewat {port or 'USB'}, tetapi firmware tidak menjawab INFO "
                                              "(firmware lama). Unggah firmware 3.2."))
        if esp.get("weights_match") is True:
            sambung.append(_row("AI di ESP32", BAIK, "Model AI terpasang di ESP32 dan sama dengan model di laptop."))
        elif esp.get("weights_match") is False:
            sambung.append(_row("AI di ESP32", CEK, "Model AI di ESP32 berbeda dengan model di laptop. Unggah ulang firmware."))
        else:
            sambung.append(_row("AI di ESP32", TIDAK_ADA if esp.get("fw") else BELUM,
                                "Firmware ini tidak memuat model AI." if esp.get("fw") else "Menunggu ESP32 menjawab."))
        sambung.append(_row("Halaman Wi-Fi ESP32", BAIK if "web" in feats else TIDAK_ADA,
                            "Sambungkan ponsel ke Wi-Fi SHADESHIFT, buka 192.168.4.1." if "web" in feats
                            else "Firmware ini tidak memuat halaman Wi-Fi."))

    # ---- measuring ----
    ukur = []
    i2c = f["i2c"]
    for nama, alamat, guna in (("Pengubah analog ke digital ADS1115", (ADS,), "membaca tegangan, arus dan cahaya"),
                               ("Pengatur beban MCP4725", DAC, "mengatur MOSFET saat menyapu kurva")):
        if demo:
            ukur.append(_row(nama, DEMO, f"Bagian ini {guna}. Tidak ada pada ESP32 tiruan."))
        elif not i2c:
            ukur.append(_row(nama, BELUM, f"Bagian ini {guna}. Tekan Periksa ulang perangkat."))
        elif any(a in i2c["found"] for a in alamat):
            ukur.append(_row(nama, BAIK, f"Ditemukan di jalur I2C (alamat {next(a for a in alamat if a in i2c['found'])}); {guna}.",
                             i2c["at"]))
        else:
            ukur.append(_row(nama, CEK, f"Tidak ditemukan di jalur I2C. Periksa kabel SDA, SCL dan catu 3,3 V.", i2c["at"]))
    if demo:
        ukur.append(_row("Jalur arus (sekring, MOSFET, shunt)", DEMO, "Nilai dari rekaman lab."))
    else:
        if _newer(err.get("arus"), ok_at):
            ukur.append(_row("Jalur arus (sekring, MOSFET, shunt)", CEK, "Arus tidak terdeteksi. Periksa sekring, relai R0, "
                             "MOSFET dan shunt.", err["arus"]["at"]))
        elif last and last.get("isc"):
            ukur.append(_row("Jalur arus (sekring, MOSFET, shunt)", BAIK, f"Arus hubung singkat {kondisi.angka(last['isc'] * 1000, 1)} "
                             f"mA.", last["at"]))
        else:
            ukur.append(_row("Jalur arus (sekring, MOSFET, shunt)", BELUM, "Belum ada pengukuran."))

    # ---- switches and panels ----
    panel = []
    if demo:
        panel.append(_row("Relai dan kabel susunan", DEMO, "Tidak ada relai pada ESP32 tiruan."))
    elif _newer(err.get("voc"), ok_at) or _newer(err.get("pindah"), ok_at):
        e = err.get("voc") if _newer(err.get("voc"), ok_at) else err["pindah"]
        panel.append(_row("Relai dan kabel susunan", CEK, "Pindah susunan gagal. Tekan Hentikan semua, lalu periksa kabel relai.",
                          e["at"]))
    elif last:
        panel.append(_row("Relai dan kabel susunan", BAIK, f"Susunan {last['topology']} terhubung dan terukur.", last["at"]))
    else:
        panel.append(_row("Relai dan kabel susunan", BELUM, "Belum ada pengukuran."))
    for m in kondisi.PANELS:
        p = f["panels"].get(m) or {"state": "nodata"}
        tag = " Data demo." if demo else ""
        if p["state"] == "nodata":
            panel.append(_row(f"Panel {m}", BELUM, "Belum ada pemeriksaan panel." + tag))
        elif p["state"] == "normal":
            panel.append(_row(f"Panel {m}", BAIK, f"Daya {round(p['power_rel'] * 100)} persen dari panel terbaik." + tag, p["at"]))
        else:
            panel.append(_row(f"Panel {m}", CEK, f"{WORD[p['state']].capitalize()}, daya {round(p['power_rel'] * 100)} persen "
                                                 f"dari panel terbaik. Lihat Beranda." + tag, p["at"]))

    # ---- monitoring ----
    mon = st.get("monitor") or {}
    pantau = []
    if mon.get("on"):
        menit = max(1, round(mon.get("array_interval_s", 300) / 60))
        pantau.append(_row("Pemantauan", BAIK, f"Aktif: susunan diukur setiap {menit} menit"
                           + (f", setiap panel diperiksa setiap {round(mon['panel_interval_s'] / 60)} menit." if mon.get("panels")
                              else ".")))
    else:
        pantau.append(_row("Pemantauan", MATI, "Tidak aktif. Tekan Mulai pemantauan di Beranda."))
    if last:
        late = mon.get("on") and _age_s(last["at"], now) > STALE_FACTOR * mon.get("array_interval_s", 300)
        pantau.append(_row("Pengukuran terakhir", CEK if late else BAIK,
                           "Terlambat: pengukuran berikutnya belum masuk." if late else "Data masuk sesuai jadwal.", last["at"]))
    else:
        pantau.append(_row("Pengukuran terakhir", BELUM, "Belum ada pengukuran dalam 24 jam terakhir."))

    grup = [{"judul": "Sambungan", "baris": sambung}, {"judul": "Pengukuran", "baris": ukur},
            {"judul": "Saklar dan panel", "baris": panel}, {"judul": "Pemantauan", "baris": pantau}]
    cek = [r["nama"] for g in grup for r in g["baris"] if r["keadaan"] == CEK]
    if not online:
        ringkas = {"level": "offline", "text": "Alat tidak terhubung."}
    elif cek:
        ringkas = {"level": "problem", "text": f"{len(cek)} bagian perlu dicek: " + ", ".join(cek) + "."}
    elif demo:
        ringkas = {"level": "demo", "text": "Mode demo: tidak ada perangkat keras untuk diperiksa."}
    else:
        ringkas = {"level": "ok", "text": "Semua bagian yang sudah diperiksa bekerja baik."}
    return {"ringkasan": ringkas, "grup": grup, "demo": demo}
