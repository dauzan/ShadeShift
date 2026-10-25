"""Predictive maintenance (CONTRACT §28): dirt, a panel falling behind, recurring shade, the maintenance log and its
effect; nothing forecast from too little data."""
from datetime import datetime, timedelta, timezone

from shadeshift import perawatan as PW

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def iso(t):
    return t.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def arr(days, per_day=8, drop=0.0, start=None, light=1.2):
    start = start or NOW - timedelta(days=days)
    out = []
    for k in range(int(days * per_day)):
        t = start + timedelta(hours=24 / per_day * k)
        d = (t - start).total_seconds() / 86400
        out.append({"at": iso(t), "topology": "4S", "pmax": 1.0 * (1 - drop * d), "expected": 1.0, "light_v": light, "rs": None})
    return out


def rounds(days, power=lambda m, d: 1.0, state=lambda m, t: "normal", start=None, per_day=4):
    start = start or NOW - timedelta(days=days)
    out = []
    for k in range(int(days * per_day)):
        t = start + timedelta(hours=24 / per_day * k)
        d = (t - start).total_seconds() / 86400
        out.append({"at": iso(t), "panels": {m: {"power_rel": power(m, d), "state": state(m, t)} for m in "ABCD"}})
    return out


def test_too_little_data_says_how_much_more_is_needed():
    out = PW.prediksi(arr(1), rounds(1), [], NOW)
    assert out["ringkas"]["level"] == "belajar" and out["prediksi"] == []
    assert out["ringkas"]["text"].startswith("Belum cukup data untuk perkiraan: butuh 3 hari")


def test_slow_dirt_is_forecast():
    out = PW.prediksi(arr(6, drop=0.01), rounds(6), [], NOW)                 # 1 % less per day, same light
    p = next(x for x in out["prediksi"] if x["jenis"] == "kotor")
    assert p["tingkat"] == "nanti" and 5 < p["hari"] < 15 and "walau cahaya sama" in p["kalimat"]
    assert out["ringkas"]["text"].startswith("Perawatan berikutnya: bersihkan panel dalam sekitar")
    soon = PW.prediksi(arr(6, drop=0.02), rounds(6), [], NOW)                # 2 % a day: due within 3 days
    assert soon["ringkas"]["level"] == "segera" and soon["ringkas"]["text"].startswith("Bersihkan panel dalam sekitar")
    clean = PW.prediksi(arr(6), rounds(6), [], NOW)
    assert clean["ringkas"] == {"level": "ok", "text": "Tidak ada perawatan yang perlu dilakukan saat ini."}


def test_a_panel_falling_behind():
    out = PW.prediksi(arr(6), rounds(6, power=lambda m, d: 1.0 - 0.03 * d if m == "B" else 1.0), [], NOW)
    p = next(x for x in out["prediksi"] if x["jenis"] == "tertinggal")
    assert p["panel"] == "B" and p["judul"] == "Periksa panel B"


def test_recurring_shade_at_the_same_hour():
    def state(m, t):
        return "object" if m == "A" and t.astimezone().hour == 15 else "normal"
    start = (NOW - timedelta(days=4)).astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    out = PW.prediksi(arr(4), rounds(4, state=state, start=start, per_day=24), [], NOW)
    p = next(x for x in out["prediksi"] if x["jenis"] == "bayangan")
    assert p["panel"] == "A" and "sekitar pukul 15.00" in p["kalimat"] and p["tingkat"] == "info"


def test_cleaning_starts_a_fresh_baseline_and_its_effect_is_measured():
    before = arr(5, drop=0.03)
    cleaned = NOW - timedelta(hours=20)
    after = [r for r in arr(1, start=cleaned + timedelta(minutes=30), per_day=12)]
    rows = [r for r in before if r["at"] < iso(cleaned)] + after
    out = PW.prediksi(rows, rounds(5), [{"at": iso(cleaned), "jenis": "bersih", "panel": None}], NOW)
    assert not any(x["jenis"] == "kotor" for x in out["prediksi"])           # less than 3 days since cleaning
    assert out["log"][0]["teks"].endswith("Panel dibersihkan.") and out["log"][0]["efek"].startswith("Daya naik")


def test_endpoint_log_and_audit_line(tmp_path):
    from conftest import heartbeat, server_client
    with server_client(tmp_path) as api:
        heartbeat(api, "esp32-01")
        assert api.post("/api/v1/devices/esp32-01/perawatan", json={"jenis": "bersih", "panel": "B"}).status_code == 201
        assert api.post("/api/v1/devices/esp32-01/perawatan", json={"jenis": "cuci"}).status_code == 422
        pw = api.get("/api/v1/devices/esp32-01/perawatan").json()
        assert pw["log"][0]["teks"].endswith("Panel dibersihkan (panel B).") and pw["ringkas"]["level"] == "belajar"
        assert api.get("/api/v1/twin/state", params={"device_id": "esp32-01"}).json()["perawatan"]["log"]
        trail = api.get("/api/v1/jejak", params={"device_id": "esp32-01"}).json()
        assert any(e["teks"] == "Pengguna mencatat: panel dibersihkan (panel B)" for e in trail["entries"])
