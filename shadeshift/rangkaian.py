"""Rekomendasi Rangkaian (docs/CONTRACT.md §29): which way of wiring the four panels gives the most power now, why, what
changes, and what can go wrong, in plain Indonesian. Pure functions; the server passes the facts in.

The recommendation follows the measurement when a fresh comparison of all wirings exists (each measured once, the relays
moving only to measure), and the AI's choice otherwise (said as "belum diukur"). The AI on the ESP32 (or the laptop in
demo mode) is credited, and a disagreement between the AI and the measurement is said plainly. Paralel (4P) is measured
and shown but never recommended: it gives about 20 volt and the system needs 24 volt. A change is applied only after a
person approves it, never by itself."""
from datetime import datetime, timezone

NAMA = {"4S": "Seri (4S)", "2S2P": "Seri-paralel (2S2P)", "TCT": "Silang (TCT)", "4P": "Paralel (4P)"}
BISA = ("4S", "2S2P", "TCT")
SEGAR_MENIT = 30                 # a comparison older than this is not used for the recommendation
MIN_UNTUNG = 3.0                 # a gain below 3 percent is not worth a change
JEDA_MENIT = 15                  # between two approved changes (going back to the previous wiring is always allowed)
ALASAN = {
    "TCT": "Rangkaian silang menghubungkan titik tengah kedua deret. Bila satu panel terhalang, arus bisa memutar lewat "
           "panel lain, sehingga panel yang terhalang tidak menahan seluruh rangkaian.",
    "2S2P": "Rangkaian seri-paralel membagi panel menjadi dua deret. Panel yang terhalang hanya menahan deretnya sendiri; "
            "deret yang lain tetap bekerja penuh.",
    "4S": "Rangkaian seri menyambung keempat panel dalam satu deret. Saat semua panel mendapat cahaya yang sama, rangkaian ini "
          "memberi tegangan tertinggi dengan arus terkecil, sehingga rugi di kabel paling kecil.",
}
UMUM = ["Listrik terputus beberapa detik saat relai berpindah.",
        "Keuntungan ini hanya berlaku untuk keadaan cahaya sekarang. Bila bayangan bergeser atau hilang, rangkaian lain bisa "
        "lebih baik.",
        "Bila pemeriksaan tegangan sesudah pindah gagal, semua relai dibuka otomatis dan panel berhenti mengalirkan listrik "
        "sampai diatur ulang.",
        "Jangan menyentuh kabel selama perpindahan: tegangan bisa mencapai sekitar 88 volt."]


def kecil(t):
    """'seri (4S)': the name in a sentence, the code kept in capitals."""
    n = NAMA.get(t, t or "")
    return n[:1].lower() + n[1:]


def _menit(a, b):
    return (datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() / 60


def _jam(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H.%M")


def _w(x):
    return f"{x:.2f}".replace(".", ",")


def kerugian(dari, ke):
    """What can go wrong or change when going from `dari` to `ke`."""
    out = list(UMUM)
    if dari == "4S" and ke in ("2S2P", "TCT"):
        out.insert(1, "Tegangan ke alat di rumah turun kira-kira setengah dan arusnya dua kali lipat; kabel sedikit lebih hangat.")
    elif dari in ("2S2P", "TCT") and ke == "4S":
        out.insert(1, "Tegangan naik kira-kira dua kali lipat dan arusnya setengah; bila bayangan muncul lagi, daya bisa turun banyak.")
    elif {dari, ke} == {"2S2P", "TCT"}:
        out.insert(1, "Tegangan dan arus hampir sama; bedanya hanya sambungan silang di tengah.")
    return out


def saran(sekarang, banding, ai, now_iso, terakhir=None, demo=False, tempat_ai="di ESP32"):
    """sekarang: the active wiring or None (all relays open); banding: {topology: {pmax, at}} of the newest comparison
    or {}; ai: {choice, captured_at} of the newest AI result or None; terakhir: the newest approved change {at, dari, ke}
    or None. Returns the page's analysis: {sekarang, rekomendasi, sumber, judul, alasan, keuntungan, kerugian, ai,
    perbandingan, segar, boleh, jeda_menit, kembali}."""
    t_banding = max((v["at"] for v in banding.values()), default=None)
    segar = bool(t_banding) and _menit(t_banding, now_iso) <= SEGAR_MENIT
    rows = []
    for t in ("4S", "2S2P", "TCT", "4P"):
        v = banding.get(t)
        rows.append({"rangkaian": t, "nama": NAMA[t], "pmax": v["pmax"] if v else None, "bisa": t in BISA,
                     "catatan": None if t in BISA else "Tidak bisa dipakai: tegangannya sekitar 20 volt, sedangkan sistem ini "
                                                       "membutuhkan 24 volt."})
    rek, sumber, alasan, untung, judul = None, None, [], None, None
    ukur = {t: banding[t]["pmax"] for t in BISA if banding.get(t) and banding[t].get("pmax")}
    if segar and ukur:
        terbaik = max(ukur, key=ukur.get)
        kini = ukur.get(sekarang) if sekarang else None
        gain = (ukur[terbaik] - kini) / kini * 100 if kini else None
        if sekarang == terbaik or (gain is not None and gain < MIN_UNTUNG):
            judul = f"Rangkaian sekarang, {kecil(sekarang)}, sudah paling baik untuk cahaya saat ini."
        else:
            rek, sumber = terbaik, "ukur"
            judul = f"Saran: ubah ke {kecil(terbaik)}."
            untung = (f"Daya terukur naik sekitar {round(gain)} persen, dari {_w(kini)} menjadi {_w(ukur[terbaik])} watt "
                      f"(diukur pukul {_jam(t_banding)})." if gain is not None else
                      f"Daya terukur paling besar: {_w(ukur[terbaik])} watt (diukur pukul {_jam(t_banding)}).")
        if ai and ai.get("choice"):
            pilih = ai["choice"]
            alasan.append(f"AI {tempat_ai} juga memilih {kecil(pilih)}." if pilih == terbaik else
                          f"AI {tempat_ai} memilih {kecil(pilih)}, tetapi pengukuran menunjukkan "
                          f"{kecil(terbaik)} lebih besar; saran mengikuti pengukuran.")
    elif ai and ai.get("choice") and ai["choice"] != sekarang:
        rek, sumber = ai["choice"], "ai"
        judul = f"Saran AI: ubah ke {kecil(rek)}."
        untung = "Belum diukur. Tekan Bandingkan semua rangkaian untuk melihat angka sebenarnya sebelum mengubah."
        alasan.append(f"Dihitung oleh AI {tempat_ai} dari pengukuran pukul {_jam(ai['captured_at'])}.")
    else:
        judul = ("Belum ada perbandingan. Tekan Bandingkan semua rangkaian agar AI dan pengukuran bisa memberi saran."
                 if not (ai and ai.get("choice")) else
                 f"AI {tempat_ai} menilai rangkaian sekarang sudah paling cocok. Bandingkan semua rangkaian untuk memastikannya.")
    if rek:
        if sekarang == "4S":
            alasan.insert(0, "Pada rangkaian seri, panel yang paling gelap menahan arus semua panel.")
        alasan.insert(0, ALASAN[rek])
    jeda, kembali = 0, None
    if terakhir:
        sisa = JEDA_MENIT - _menit(terakhir["at"], now_iso)
        jeda = max(0, round(sisa)) if sisa > 0 else 0
        kembali = terakhir.get("dari") if terakhir.get("dari") in BISA and terakhir.get("ke") == sekarang else None
    return {"sekarang": sekarang, "nama_sekarang": NAMA.get(sekarang, "Semua relai terbuka"), "rekomendasi": rek,
            "nama_rekomendasi": NAMA.get(rek), "sumber": sumber, "judul": judul, "alasan": alasan, "keuntungan": untung,
            "kerugian": kerugian(sekarang, rek) if rek else [], "perbandingan": rows, "waktu_banding": t_banding,
            "segar": segar, "jeda_menit": jeda, "boleh": bool(rek) and jeda == 0, "kembali": kembali, "demo": demo}
