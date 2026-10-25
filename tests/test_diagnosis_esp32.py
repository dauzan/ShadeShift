"""Diagnosis AI on the ESP32 shown on the web page (CONTRACT §23): the gateway action `diagnose` sends DIAG, the board's
'# diagnosis=' line becomes the Beranda row, the analyser sentence and an audit line; without a model, or in demo mode,
the page says why instead of showing a cause."""
import time

import requests

from conftest import heartbeat, live_server, server_client
from fake_devices import Fake32, Gateway32
from shadeshift import analisis_kurva as AK, jejak


def _wait(cond, s=30):
    end = time.time() + s
    while time.time() < end and not cond():
        time.sleep(0.2)
    return cond()


def _run(tmp_path, with_model, monitoring=False):
    with live_server(tmp_path) as (settings, core):
        base = settings.api_url + "/api/v1"
        from shadeshift.edge.selector import EdgeSelector
        fake = Fake32("V1c", tmp_path, EdgeSelector().model_id.split("@")[1], with_model)
        gw = Gateway32(settings, fake)
        gw.start()
        try:
            dev = gw.device_id
            assert _wait(lambda: (core.device_row(dev) or {}).get("gateway", {}).get("esp32"))
            st = requests.get(f"{base}/devices/{dev}/diag", timeout=10).json()
            assert st["on_board"] is with_model and st["available"] is with_model
            if monitoring:
                requests.post(f"{base}/devices/{dev}/commands", timeout=10,
                              json={"kind": "action", "command": "monitor_start", "params": {"panel_interval_s": 0}})
                assert _wait(lambda: gw.monitor.get("on"))
            cid = requests.post(f"{base}/devices/{dev}/commands", json={"kind": "action", "command": "diagnose"},
                                timeout=10).json()["id"]
            assert _wait(lambda: core.db.one("SELECT status FROM commands WHERE id=?", (cid,))["status"] in ("done", "failed"))
            assert _wait(lambda: requests.get(f"{base}/devices/{dev}/diag", timeout=10).json()["now" if with_model else "failed"])
            st = requests.get(f"{base}/devices/{dev}/diag", timeout=10).json()
            twin = requests.get(f"{base}/twin/state", params={"device_id": dev}, timeout=30).json()
            an = requests.get(f"{base}/analisis", params={"device_id": dev}, timeout=30).json()
            trail = requests.get(f"{base}/jejak", params={"device_id": dev}, timeout=30).json()
            return core.db.one("SELECT status, result FROM commands WHERE id=?", (cid,)), st, twin, an, trail
        finally:
            gw.stop()


def test_diagnosis_from_the_esp32_reaches_the_page(tmp_path):
    cmd, st, twin, an, trail = _run(tmp_path, with_model=True)
    assert cmd["status"] == "done" and cmd["result"].startswith("diagnosis=partial_shading")
    assert st["now"]["class"] == "partial_shading" and st["now"]["nama"] == "Bayangan sebagian"
    assert st["now"]["confidence"] == 0.84 and st["now"]["t_us"] == 3200 and st["why"] is None
    assert twin["diag"]["now"]["nama"] == "Bayangan sebagian"
    assert any(s.startswith("AI di ESP32 menilai penyebabnya: bayangan sebagian, keyakinan 84 persen") for s in an["now"]["lines"])
    assert "menilai seluruh susunan dari empat kurva, bukan per panel" in an["basis"]
    teks = [e["teks"] for e in trail["entries"]]
    assert "Pengguna meminta Diagnosis dengan AI" in teks
    assert "Diagnosis AI di ESP32: Bayangan sebagian, keyakinan 84 persen" in teks


def test_diagnosis_requested_while_monitoring(tmp_path):
    cmd, st, twin, an, trail = _run(tmp_path, with_model=True, monitoring=True)
    assert cmd["status"] == "done" and "monitoring" in cmd["result"]           # the monitoring loop runs it
    assert st["now"]["class"] == "partial_shading"


def test_without_a_model_the_page_says_so(tmp_path):
    cmd, st, twin, an, trail = _run(tmp_path, with_model=False)
    assert cmd["status"] == "failed" and "no diagnosis model" in cmd["result"]        # refused before DIAG is sent
    assert st["now"] is None and st["why"].startswith("model diagnosis belum dipasang di ESP32")
    assert st["failed"]["text"] == "model diagnosis belum dipasang di ESP32"
    assert "Diagnosis penyebab oleh AI di ESP32: model diagnosis belum dipasang" in an["basis"]
    assert any(e["teks"] == "Diagnosis dengan AI tidak berjalan: model diagnosis belum dipasang di ESP32"
               for e in trail["entries"])


def test_demo_device_never_pretends(tmp_path):
    with server_client(tmp_path) as api:
        heartbeat(api, "demo-01", kind="emulator")
        st = api.get("/api/v1/devices/demo-01/diag").json()
        assert not st["available"] and st["why"].startswith("mode demo") and st["now"] is None


def test_diagnosis_changes_are_the_important_lines():
    def ev(cls, conf, minute):
        return {"kind": "info", "message": f"ESP32 diagnosis: {cls} (confidence {conf:.2f}, model m)", "data": {},
                "created_at": f"2026-10-22T08:{minute:02d}:00.000Z"}
    events = [ev("normal", 0.9, 0), ev("normal", 0.91, 5), ev("partial_shading", 0.84, 10), ev("partial_shading", 0.8, 15)]
    out = [e for e in jejak.susun(events, [], []) if e["jenis"] == "Keputusan AI"]
    assert [e["teks"] for e in out] == ["AI di ESP32 mengubah diagnosis dari Normal ke Bayangan sebagian, keyakinan 84 persen",
                                        "Diagnosis AI di ESP32: Normal, keyakinan 90 persen"]
    assert len([e for e in jejak.susun(events, [], [], semua=True) if e["jenis"] == "Keputusan AI"]) == 4


def test_failure_reasons_in_words():
    assert AK.alasan_diagnosis("DIAG GAGAL: pindah ke TCT") == "perpindahan relai gagal"
    assert AK.alasan_diagnosis("DIAG GAGAL: Pmax 4S nol") == "daya susunan 4S nol, kemungkinan tidak ada cahaya"
    assert AK.alasan_diagnosis("something new") == "galat sistem"
    assert set(AK.KELAS_DIAGNOSIS) == {"normal", "partial_shading", "uniform_dimming", "bypass_open", "bypass_short",
                                       "series_resistance"}
