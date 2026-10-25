"""Jejak audit (CONTRACT §22): every system message in words with who acted, AI changes only, daily summaries, paging,
CSV for the whole period, demo data marked."""
import csv
import io
import json
import uuid

import pytest

from conftest import heartbeat, server_client
from shadeshift import jejak

# Messages exactly as the gateway and the server write them.
NYATA = [
    ("command", "queued action: measure_now", "Pengguna", "Perintah", "Pengguna meminta Ukur sekarang"),
    ("command", "queued action: stop (stop all)", "Pengguna", "Perintah", "Pengguna menekan Hentikan semua"),
    ("command", "queued raw: STATUS", "Pengguna", "Perintah", "Pengguna mengirim perintah langsung ke ESP32: STATUS"),
    ("command", "monitoring started: 4S every 10 s, panels every 30 min", "Sistem", "Pemantauan",
     "Pemantauan dimulai: susunan 4S diukur setiap 10 detik"),
    ("command", "monitoring stopped", "Sistem", "Pemantauan", "Pemantauan dihentikan"),
    ("command", "stop: tasks cancelled, device confirmed all relays open", "Perangkat", "Perintah",
     "ESP32 memastikan semua relai terbuka setelah perintah berhenti"),
    ("error", "panel_check: failed (timeout)", "Sistem", "Galat", "Perintah Periksa setiap panel gagal"),
    ("error", "panel C check failed", "Sistem", "Galat", "Pemeriksaan panel C gagal"),
    ("error", "monitoring: 4S sweep failed", "Sistem", "Galat", "Pemantauan: pengukuran susunan 4S gagal"),
    ("switch", "4S -> TCT (selector, esp32)", "AI di ESP32", "Perpindahan relai",
     "Relai dipindah dari susunan 4S ke TCT atas pilihan AI"),
    ("switch", "4S -> 2S2P (selector, gateway_onnx)", "AI di laptop", "Perpindahan relai",
     "Relai dipindah dari susunan 4S ke 2S2P atas pilihan AI"),
    ("info", "ESP32 chose TCT, laptop cross-check (gateway_onnx) chose 4S", "AI di ESP32", "Keputusan AI",
     "AI di ESP32 memilih TCT, pemeriksaan silang di laptop memilih 4S"),
    ("alert", "Pmax -21.4 % vs twin expectation for 4S (assumed shading: none). Indication only, not a validated diagnosis.",
     "Sistem", "Peringatan", "Daya semua panel 21,4 persen di bawah perkiraan normal (rangkaian 4S)"),
    ("status", "connected to serial COM5", "Sistem", "Perangkat", "Sistem terhubung ke ESP32 melalui COM5"),
    ("status", "ESP32 firmware 3.2 with the same selector weights (ab12cd34): on-board AI active", "Perangkat", "Perangkat",
     "ESP32 melaporkan firmware 3.2 dengan bobot AI yang sama: AI di ESP32 aktif"),
    ("info", "settings changed", "Pengguna", "Perintah", "Pengguna mengubah pengaturan"),
]


@pytest.mark.parametrize("kind, msg, siapa, jenis, teks", NYATA)
def test_system_messages_become_indonesian_sentences_with_who(kind, msg, siapa, jenis, teks):
    e = jejak.dari_kejadian({"kind": kind, "message": msg, "data": {}, "created_at": "2026-10-22T07:05:00.000Z"})
    assert (e["siapa"], e["jenis"]) == (siapa, jenis)
    assert e["teks"].startswith(teks)
    assert e["asli"] == msg and not e["demo"]


def test_unknown_message_keeps_the_original_and_says_nothing_invented():
    e = jejak.dari_kejadian({"kind": "error", "message": "something odd", "data": {}, "created_at": "2026-10-22T07:05:00.000Z"})
    assert (e["siapa"], e["jenis"], e["teks"], e["asli"]) == ("Sistem", "Galat", "Galat sistem", "something odd")


def _keputusan(n, pilihan, by="esp32", mulai=0):
    return [{"sweep_id": mulai + k, "choice": c, "decided_by": by, "latency_us": 850.0, "applied": 0,
             "captured_at": f"2026-10-22T08:{(mulai + k) % 60:02d}:00.000Z", "source": "device"}
            for k, c in zip(range(n), pilihan)]


def test_ai_listed_only_when_the_recommendation_changes():
    ds = _keputusan(5, ["4S", "4S", "TCT", "TCT", "4S"])
    ds += [{**ds[2], "decided_by": "gateway_onnx", "choice": "4S"}]    # the laptop's cross-check on the same sweep
    teks = [e["teks"] for e in jejak.dari_keputusan(ds, sebelum="4S")]
    assert teks == ["AI di ESP32 mengubah rekomendasi dari 4S ke TCT", "AI di ESP32 mengubah rekomendasi dari TCT ke 4S"]
    semua = jejak.dari_keputusan(ds, sebelum=None, semua=True)
    assert len(semua) == 5 and semua[0]["teks"].startswith("AI di ESP32 merekomendasikan susunan 4S, dihitung dalam 0,85")


def test_default_view_sums_up_routine_work_per_day():
    sweeps = [{"id": k, "topology": "4S", "captured_at": f"2026-10-22T08:{k:02d}:00.000Z", "pmax": 1.0, "source": "device"}
              for k in range(5)]
    ds = _keputusan(5, ["4S", "4S", "TCT", "4S", "4S"])
    ev = [{"kind": "command", "message": "queued action: measure_now", "data": {}, "created_at": "2026-10-22T08:30:00.000Z"}]
    out = jejak.susun(ev, ds, sweeps, sebelum="4S")
    assert out[0]["jenis"] == "Ringkasan harian"                        # above the day's entries
    assert "5 pengukuran susunan" in out[0]["teks"] and "AI merekomendasikan 4S 4 kali dan TCT 1 kali" in out[0]["teks"]
    assert [e["jenis"] for e in out[1:]] == ["Perintah", "Keputusan AI", "Keputusan AI"]
    full = jejak.susun(ev, ds, sweeps, sebelum="4S", semua=True)
    assert sum(e["jenis"] == "Pengukuran" for e in full) == 5 and len(full) == 1 + 1 + 5 + 5
    only_ai = jejak.susun(ev, ds, sweeps, sebelum="4S", kategori="ai")
    assert {e["jenis"] for e in only_ai} == {"Keputusan AI"}


def test_repeated_power_warnings_are_counted_not_listed():
    msg = "Pmax -30.2 % vs twin expectation for 4S (assumed shading: none). Indication only, not a validated diagnosis."
    ev = [{"kind": "alert", "message": msg, "data": {}, "created_at": f"2026-10-22T{h:02d}:{m:02d}:00.000Z"}
          for h, m in [(1, 0), (1, 10), (1, 20), (1, 30), (3, 0)]]                # a gap of 90 min before the last one
    sweeps = [{"id": 1, "topology": "4S", "captured_at": "2026-10-22T03:00:00.000Z", "pmax": 0.7, "source": "device"}]
    out = jejak.susun(ev, [], sweeps)
    assert sum(e["jenis"] == "Peringatan" for e in out) == 2
    assert "5 peringatan daya di luar harapan" in out[0]["teks"]
    assert sum(e["jenis"] == "Peringatan" for e in jejak.susun(ev, [], sweeps, semua=True)) == 5


def test_demo_entries_are_marked():
    sweeps = [{"id": 1, "topology": "4S", "captured_at": "2026-10-22T08:00:00.000Z", "pmax": 1.0, "source": "demo"}]
    out = jejak.susun([], [], sweeps, semua=True, demo=True)
    assert all(e["demo"] for e in out)
    assert any("ESP32 tiruan mengukur" in e["teks"] for e in out)
    assert jejak.baris_csv(out[0])[5] == "Mode demo"


def _isi(core, device_id, n=150):
    """n array sweeps one minute apart with ESP32 decisions (changing every 50) and a command event."""
    with core.db.tx() as con:
        for k in range(n):
            at = f"2026-10-2{1 + k // 1440}T{(k // 60) % 24:02d}:{k % 60:02d}:00.000Z"
            sid = con.execute("INSERT INTO sweeps(uuid, device_id, source, label, topology, captured_at, received_at, n_points, "
                              "pmax, points_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (str(uuid.uuid4()), device_id, "device", "t", "4S", at, at, 2, 1.0,
                               json.dumps({"v": [0, 1], "i": [1, 0]}))).lastrowid
            con.execute("INSERT INTO decisions(uuid, sweep_id, device_id, decided_by, model_id, choice, scores_json, "
                        "features_json, trigger, applied, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), sid, device_id, "esp32", "pemilih.h@firmware", ["4S", "TCT"][(k // 50) % 2],
                         "[]", "[]", "observe", 0, at))
        core.add_event(con, device_id, "command", "queued action: panel_check", created_at="2026-10-21T01:00:30.000Z")


def test_endpoint_pages_filters_period_and_csv(tmp_path):
    with server_client(tmp_path) as api:
        heartbeat(api, "esp32-01")
        _isi(api.core, "esp32-01")
        url = "/api/v1/jejak?device_id=esp32-01"
        d = api.get(url).json()
        assert not d["demo"] and d["pages"] == 1
        jenis = [e["jenis"] for e in d["entries"]]
        assert jenis[0] == "Perangkat" and d["entries"][0]["teks"] == "Gateway mulai berjalan"     # the heartbeat, today
        assert jenis.index("Ringkasan harian") < jenis.index("Keputusan AI")
        assert sum(e["jenis"] == "Keputusan AI" for e in d["entries"]) == 3     # first one and two changes
        assert any(e["teks"] == "Pengguna meminta Periksa setiap panel" for e in d["entries"])
        full = api.get(url + "&semua=true").json()
        assert full["total"] > 300 and full["pages"] == -(-full["total"] // 100) and len(full["entries"]) == 100
        last = api.get(url + f"&semua=true&page={full['pages']}").json()
        assert last["page"] == full["pages"] and 0 < len(last["entries"]) <= 100
        part = api.get(url + "&semua=true&since=2026-10-21T02:00:00Z&until=2026-10-21T02:09:59Z").json()
        assert sum(e["jenis"] == "Pengukuran" for e in part["entries"]) == 10
        assert api.get(url + "&kategori=apa").status_code == 400
        assert api.get(url + "&since=kemarin").status_code == 400
        r = api.get("/api/v1/jejak.csv?device_id=esp32-01")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        assert tuple(rows[0]) == jejak.KOLOM_CSV and len(rows) - 1 == full["total"]
        assert rows[1][1] <= rows[-1][1] or rows[-1][3] == "Ringkasan harian"    # oldest first
        assert {r_[5] for r_ in rows[1:]} == {"Nyata"}
