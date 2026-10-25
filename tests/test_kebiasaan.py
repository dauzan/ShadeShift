"""The light AI model of the analyser box (CONTRACT §26): learns this array's normal, judges the newest measurement,
uses the light sensor to tell less light from a panel problem, and says what is new since a moment."""
from datetime import datetime, timedelta, timezone

from shadeshift import kebiasaan as KB


def _rows(n, ratio=1.0, light=1.2, start=None, step_min=10, topology="4S"):
    start = start or datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    return [{"at": (start + timedelta(minutes=step_min * k)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
             "topology": topology, "pmax": 1.0 * ratio * (1 + 0.01 * ((k % 3) - 1)), "expected": 1.0, "light_v": light}
            for k in range(n)]


def test_still_learning_until_enough_measurements():
    rows = _rows(5)
    v = KB.nilai(KB.latih(rows[:-1]), rows[-1])
    assert v["status"] == "belajar"
    assert KB.kalimat_nilai(v) == "Model AI masih mempelajari kebiasaan panel ini (4 dari 8 pengukuran)."


def test_normal_low_and_the_reason():
    rows = _rows(20)
    model = KB.latih(rows)
    assert KB.nilai(model, {**rows[-1], "pmax": 1.0})["status"] == "normal"
    cloud = KB.nilai(model, {**rows[-1], "pmax": 0.6, "light_v": 0.72})          # power and light dropped together
    assert cloud["status"] == "sangat_rendah" and cloud["sebab"] == "cahaya"
    assert "kemungkinan karena mendung" in KB.kalimat_nilai(cloud)
    shade = KB.nilai(model, {**rows[-1], "pmax": 0.6, "light_v": 1.2})          # light normal, power low
    assert shade["sebab"] == "bukan_cahaya" and "ada yang menutupi panel" in KB.kalimat_nilai(shade)
    assert KB.nilai(model, {**rows[-1], "pmax": 0.6, "light_v": None})["sebab"] is None


def test_trend_over_days():
    start = datetime(2026, 10, 15, tzinfo=timezone.utc)
    rows = [{"at": (start + timedelta(hours=6 * k)).isoformat().replace("+00:00", "Z"), "topology": "4S",
             "pmax": 1.0 - 0.02 * k, "expected": 1.0, "light_v": None} for k in range(20)]          # about 8 % less per day
    t = KB.tren(rows)
    assert t["hari"] >= 4 and t["persen_per_hari"] < -5
    assert "cenderung turun" in KB.kalimat_tren(t) and "bersihkan" in KB.kalimat_tren(t)
    assert KB.tren(_rows(20)) is None                                            # less than a day: no trend said


def test_what_is_new_since_a_moment():
    rows = _rows(12)
    rows[-1] = {**rows[-1], "pmax": 0.6, "light_v": 1.2}
    model = KB.latih(rows[:-1])
    b = KB.yang_baru(rows, rows[-3]["at"], model, [{"at": rows[-1]["at"], "text": "Panel A: kemungkinan tertutup benda atau kotoran"}],
                     {rows[-3]["at"]: set(), rows[-1]["at"]: {1}}, {1: "Sebagian panel terhalang"})
    assert b["judul"].startswith("Yang baru sejak pukul")
    assert b["lines"][0].startswith("2 pengukuran baru, dari pukul")
    assert any(x.startswith("Daya turun") for x in b["lines"])
    assert any("ada yang menutupi panel" in x for x in b["lines"])
    assert any("Panel A: kemungkinan tertutup" in x for x in b["lines"])
    assert "Muncul tanda baru: sebagian panel terhalang." in b["lines"]
    none_new = KB.yang_baru(rows, rows[-1]["at"], model)
    assert none_new["judul"].startswith("Belum ada data baru sejak") and none_new["lines"] == []
    first = KB.yang_baru(rows, None, model)                                      # first visit: since the measurement before
    assert first["judul"].startswith("Yang baru sejak pengukuran sebelumnya")


def test_endpoint_returns_what_is_new(tmp_path):
    import json, uuid
    from conftest import heartbeat, server_client
    with server_client(tmp_path) as api:
        heartbeat(api, "esp32-01")
        start = datetime.now(timezone.utc) - timedelta(hours=3)
        with api.core.db.tx() as con:
            for k in range(12):
                at = (start + timedelta(minutes=10 * k)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                v = [x * 0.7 for x in range(101)]
                i = [0.03 * (1 - (x / 70.7) ** 12) for x in v]
                con.execute("INSERT INTO sweeps(uuid, device_id, source, label, topology, captured_at, received_at, n_points, "
                            "pmax, voc, isc, points_json, header_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()), "esp32-01", "device", "t", "4S", at, at, len(v),
                             max(a * b for a, b in zip(v, i)), 70.7, 0.03, json.dumps({"v": v, "i": i}), json.dumps({"light_v": 1.2})))
        r = api.get("/api/v1/analisis", params={"device_id": "esp32-01"}).json()
        assert r["baru"]["judul"].startswith("Yang baru sejak pengukuran sebelumnya")
        assert r["model"]["n"] == 11 and r["terbaru_at"]
        assert api.get("/api/v1/analisis", params={"device_id": "esp32-01", "sejak": r["terbaru_at"]}).json()["baru"]["lines"] == []
