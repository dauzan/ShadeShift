"""Perangkat page (CONTRACT §25): every part of the system with its state in words; a part is Baik only when a report or
a measurement shows it working."""
import time

import requests

from conftest import heartbeat, live_server, server_client
from fake_devices import Fake32, Gateway32
from shadeshift import perangkat


def _facts(**kw):
    f = {"kind": "esp32", "online": True, "last_seen": "2026-10-22T08:00:00.000Z", "transport": "serial:COM5",
         "esp32": {"fw": "3.2.0", "weights_match": True, "features": ["panel", "cahaya", "pemilih", "web"]},
         "i2c": {"at": "2026-10-22T07:00:00.000Z", "found": ["0x48", "0x60"]},
         "state": {"monitor": {"on": True, "array_interval_s": 300, "panel_interval_s": 1800, "panels": True}},
         "last_sweep": {"at": "2026-10-22T07:58:00.000Z", "topology": "4S", "voc": 70.2, "isc": 0.026, "light_v": 1.2},
         "errors": {}, "panels": {m: {"state": "normal", "power_rel": 1.0, "at": "2026-10-22T07:30:00.000Z"} for m in "ABCD"}}
    f.update(kw)
    return f


def _rows(out):
    return {r["nama"]: r for g in out["grup"] for r in g["baris"]}


NOW = __import__("datetime").datetime(2026, 10, 22, 8, 0, tzinfo=__import__("datetime").timezone.utc)


def test_everything_reported_working_is_baik():
    out = perangkat.periksa(_facts(), NOW)
    assert out["ringkasan"]["level"] == "ok"
    assert {r["keadaan"] for r in _rows(out).values()} == {"Baik"}
    assert "COM5, firmware 3.2.0" in _rows(out)["ESP32"]["rincian"]


def test_an_error_after_the_last_good_sweep_needs_a_check():
    out = perangkat.periksa(_facts(errors={"arus": {"at": "2026-10-22T07:59:00.000Z"}}), NOW)
    r = _rows(out)["Jalur arus (sekring, MOSFET, shunt)"]
    assert r["keadaan"] == "Perlu dicek" and "sekring" in r["rincian"]
    assert out["ringkasan"]["text"] == "1 bagian perlu dicek: Jalur arus (sekring, MOSFET, shunt)."
    healed = perangkat.periksa(_facts(errors={"arus": {"at": "2026-10-22T07:00:00.000Z"}}), NOW)   # a good sweep since
    assert _rows(healed)["Jalur arus (sekring, MOSFET, shunt)"]["keadaan"] == "Baik"


def test_missing_i2c_part_and_late_measurement():
    out = perangkat.periksa(_facts(i2c={"at": "2026-10-22T07:00:00.000Z", "found": ["0x48"]},
                                   last_sweep={"at": "2026-10-22T06:00:00.000Z", "topology": "4S", "voc": 70.0, "isc": 0.02,
                                               "light_v": None}), NOW)
    r = _rows(out)
    assert r["Pengatur beban MCP4725"]["keadaan"] == "Perlu dicek" and "SDA" in r["Pengatur beban MCP4725"]["rincian"]
    assert r["Pengukuran terakhir"]["keadaan"] == "Perlu dicek"
    assert r["Pengubah analog ke digital ADS1115"]["keadaan"] == "Baik"


def test_nothing_checked_is_never_called_baik():
    out = perangkat.periksa(_facts(i2c=None, last_sweep=None, panels={}, esp32=None), NOW)
    r = _rows(out)
    for nama in ("Pengubah analog ke digital ADS1115", "Jalur arus (sekring, MOSFET, shunt)", "Relai dan kabel susunan", "Panel A"):
        assert r[nama]["keadaan"] == "Belum diperiksa", nama


def test_demo_device_has_no_hardware_to_check(tmp_path):
    with server_client(tmp_path) as api:
        heartbeat(api, "demo-01", kind="emulator")
        out = api.get("/api/v1/devices/demo-01/perangkat").json()
    r = _rows(out)
    assert out["demo"] and out["ringkasan"]["level"] == "demo"
    assert r["ESP32"]["keadaan"] == r["Pengatur beban MCP4725"]["keadaan"] == "Mode demo"
    assert not any(x["keadaan"] == "Baik" for k, x in r.items() if k not in ("Server lokal dan dasbor", "Gateway (laptop ke alat)"))


def test_a_board_reports_its_parts(tmp_path):
    """Firmware 3.2 board (test fake): INFO and SCAN at connect, one measurement -> the parts it showed are Baik."""
    with live_server(tmp_path) as (settings, core):
        from shadeshift.edge.selector import EdgeSelector
        base = settings.api_url + "/api/v1"
        gw = Gateway32(settings, Fake32("V1c", tmp_path, EdgeSelector().model_id.split("@")[1]))
        gw.start()
        try:
            dev = gw.device_id
            end = time.time() + 30
            while time.time() < end and not ((core.device_row(dev) or {}).get("gateway") or {}).get("i2c"):
                time.sleep(0.2)
            assert core.device_row(dev)["gateway"]["i2c"]["found"] == ["0x48", "0x60"]
            requests.post(f"{base}/devices/{dev}/commands", json={"kind": "action", "command": "measure_now"}, timeout=10)
            end = time.time() + 60
            while time.time() < end and not core.db.one("SELECT 1 FROM sweeps WHERE device_id=?", (dev,)):
                time.sleep(0.2)
            out = requests.get(f"{base}/devices/{dev}/perangkat", timeout=30).json()
        finally:
            gw.stop()
    r = _rows(out)
    for nama in ("ESP32", "AI di ESP32", "Halaman Wi-Fi ESP32", "Pengubah analog ke digital ADS1115", "Pengatur beban MCP4725",
                 "Jalur arus (sekring, MOSFET, shunt)", "Relai dan kabel susunan"):
        assert r[nama]["keadaan"] == "Baik", (nama, r[nama])
    assert "alamat 0x60" in r["Pengatur beban MCP4725"]["rincian"]
