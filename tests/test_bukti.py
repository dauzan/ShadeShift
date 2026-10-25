"""Bukti page (CONTRACT §24): promises and targets from real ESP32 data only, trial runs counted from their five checks."""
import time

import requests

from conftest import live_server, server_client
from fake_devices import Fake32, Gateway32
from shadeshift import bukti


def _facts(**kw):
    f = {"esp32": {"web": False}, "audit_n": 0, "decisions_esp32": {"n": 0, "median_us": None, "max_us": None},
         "decisions_laptop": {"n": 0, "median_us": None, "max_us": None}, "diagnosis": {"n": 0, "on_board": False},
         "diagnosis_model": None, "labelled_outdoor": 0, "summary": {"mlpe": None, "relative": None}, "power": [],
         "trials": [], "demo_only": True}
    f.update(kw)
    return f


def test_nothing_measured_says_so_in_words():
    b = bukti.susun(_facts())
    assert {t["status"] for t in b["target"]} == {"Belum diukur"}
    j = {x["janji"]: x["status"] for x in b["janji"]}
    assert j["Minimal 3 uji coba penuh di papan sebelum Demo Day"] == "Belum"
    assert j["AI pemilih susunan berjalan di ESP32 (TinyML)"] == "Sebagian"
    assert not any("otomatis" in x["janji"].lower() for x in b["janji"])     # automatic reconfiguration left out


def test_trials_count_only_when_all_five_checks_pass():
    full = {k: True for k, _ in bukti.CEK_UJI}
    trials = [{"run_id": 1, "device_id": "esp32-01", "started_at": "2026-10-22T01:00:00.000Z", "checks": full},
              {"run_id": 2, "device_id": "esp32-01", "started_at": "2026-10-22T02:00:00.000Z", "checks": {**full, "stop": False}}]
    u = bukti.uji_coba(trials)
    assert u["lengkap"] == 1 and u["rows"][0]["kurang"] == ["Berhenti aman dikonfirmasi"]


def test_power_and_latency_targets_from_measurements():
    b = bukti.susun(_facts(power=[{"value": 1.6, "device_power_w": 0.4, "relay_power_w": 1.2, "topology": "4S", "at": "x"}],
                           decisions_esp32={"n": 12, "median_us": 850.0, "max_us": 900.0}))
    t = {x["target"]: x for x in b["target"]}
    assert t["Daya kendali paling besar 0,25 W"]["status"] == "Belum terpenuhi"
    assert "= 1,600 W, susunan 4S." in t["Daya kendali paling besar 0,25 W"]["terukur"][0]
    lat = t["Keputusan susunan di ESP32 dalam hitungan milidetik"]
    assert lat["status"] == "Terpenuhi" and lat["terukur"][0].startswith("Median 0,85 milidetik")


def test_demo_data_never_counts(tmp_path):
    with server_client(tmp_path) as api:
        from conftest import heartbeat
        heartbeat(api, "demo-01", kind="emulator")
        b = api.get("/api/v1/bukti").json()
        assert b["demo_only"] and b["uji_coba"]["lengkap"] == 0


def _wait(cond, s=60):
    end = time.time() + s
    while time.time() < end and not cond():
        time.sleep(0.2)
    return cond()


def test_a_full_trial_on_a_board_is_counted(tmp_path):
    """Firmware 3.2 board (test fake): connect, monitoring with a panel check, the ESP32's AI line, then Hentikan semua."""
    with live_server(tmp_path) as (settings, core):
        if not core.twin.available:
            import pytest
            pytest.skip("pvlib not installed")
        from shadeshift.edge.selector import EdgeSelector
        base = settings.api_url + "/api/v1"
        gw = Gateway32(settings, Fake32("V1c", tmp_path, EdgeSelector().model_id.split("@")[1]))
        gw.start()
        try:
            dev = gw.device_id
            assert _wait(lambda: core.device_row(dev))
            requests.post(f"{base}/devices/{dev}/commands", json={"kind": "action", "command": "monitor_start",
                                                                   "params": {"panel_interval_s": 300}}, timeout=10)
            assert _wait(lambda: core.db.one("SELECT COUNT(*) n FROM decisions WHERE decided_by='esp32'")["n"] > 0, 120)
            requests.post(f"{base}/stop_all", timeout=10)
            assert _wait(lambda: core.db.one("SELECT 1 FROM events WHERE message LIKE 'stop: tasks cancelled%'"))
            gw._flush()
        finally:
            gw.stop()
        b = requests.get(f"{base}/bukti", timeout=60).json()
    assert not b["demo_only"]
    assert b["uji_coba"]["lengkap"] == 1, b["uji_coba"]["rows"][0]["kurang"]
    j = {x["janji"]: x for x in b["janji"]}
    assert j["AI pemilih susunan berjalan di ESP32 (TinyML)"]["status"] == "Terbukti"
    assert "median 0,85 milidetik" in j["AI pemilih susunan berjalan di ESP32 (TinyML)"]["bukti"]
    assert j["Halaman web langsung dari ESP32"]["status"] == "Terbukti"
    assert j["Minimal 3 uji coba penuh di papan sebelum Demo Day"]["bukti"].startswith("1 dari 3")
