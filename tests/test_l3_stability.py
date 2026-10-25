"""L3 (semiconductor switch design) and the stability rule (Stage 4G, CONTRACT §17)."""
import re
import threading
import time
import uuid

import pytest

from conftest import ROOT, heartbeat, server_client
from shadeshift import inti, koneksi, l3, protocol, stability


def test_holding_power_matches_the_design_table_and_the_firmware_masks():
    table = {r["topologi"]: r for r in l3._csv("daya_kendali.csv")}
    for t in ("4S", "2S2P", "TCT", "4P"):
        h = l3.holding_power(t)
        assert h["elements"] == int(table[t]["elemen_menyala"])
        assert h["relay_w"] == pytest.approx(float(table[t]["relai_W"]), abs=0.01)
        assert h["semi_w"] == pytest.approx(float(table[t]["semikonduktor_W"]), abs=0.001)
    ino = (ROOT / "firmware" / "shadeshift_firmware" / "shadeshift_firmware.ino").read_text(encoding="utf-8")
    for name, mask in re.findall(r'\{"(\w+)",\s+((?:BIT_R\(\d+\)\s*\|?\s*)+),', ino):
        assert tuple(sorted(int(x) for x in re.findall(r"BIT_R\((\d+)\)", mask))) == l3.CLOSED[name], name
    assert l3.holding_power("A")["elements"] == 2 and l3.holding_power(None) is None
    assert all(r["semi_w"] <= l3.TARGET_W < r["relay_w"] for r in l3.design()["holding_by_wiring"])


def test_unstable_needs_three_readings_in_the_window():
    assert not stability.unstable([(0, 1.0), (10, 0.5)], 10, 30, 10)                   # only two readings
    assert stability.unstable([(0, 1.0), (10, 0.6), (20, 1.0)], 20, 30, 10)
    assert not stability.unstable([(0, 1.0), (10, 1.02), (20, 0.99)], 20, 30, 10)        # steady
    assert not stability.unstable([(0, 0.2), (40, 1.0), (50, 1.0), (60, 1.01)], 60, 30, 10)   # old reading left out


def _round(p4s, p2, ptct, choice):
    return {"pmax": {"4S": p4s, "2S2P": p2, "TCT": ptct}, "choice": choice}


def test_replay_locks_tct_only_when_power_fluctuates():
    steady = [_round(1.0, 0.9, 0.95, "4S")] * 6
    r = stability.replay(steady)
    assert r["policies"]["auto mode + stability rule"]["locks"] == 0
    assert r["policies"]["auto mode (20 % trigger)"]["pct_of_best"] == 100.0
    flicker = [_round(*(x * (1.0 if k % 2 else 0.5) for x in (1.0, 0.8, 0.9)), "4S" if k % 2 else "TCT")
               for k in range(8)]                                          # the light on every wiring jumps each round
    r = stability.replay(flicker)
    assert r["policies"]["auto mode + stability rule"]["locks"] >= 1
    assert stability.replay(steady[:3]) is None                                        # too short to say anything


def test_auto_mode_locks_tct_on_the_emulator_when_shade_flickers():
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V1c", lambat=0)
    stop, locks = threading.Event(), []
    flip = threading.Event()

    def flicker():                                   # alternate between no shade and heavy shade between monitor sweeps
        n = 0
        while not flip.is_set():
            k.ser.kondisi = "V1c" if n % 2 else "V6_paranet75"
            n += 1
            time.sleep(0.01)
    try:
        threading.Thread(target=flicker, daemon=True).start()
        t = threading.Thread(target=k.mode_otomatis, args=(inti.muat_bobot(), stop, 0.02, 0.2, 0.0),
                             kwargs={"stabil": {"enabled": True, "window_s": 30, "cv_pct": 10},
                                     "saat_kunci": lambda locked, why: locks.append(locked)}, daemon=True)
        t.start()
        end = time.time() + 30
        while time.time() < end and not (locks and k.topo == "TCT"):
            time.sleep(0.05)
        assert locks and locks[0] is True and k.topo == "TCT"
    finally:
        flip.set()
        stop.set()
        k.hidup = False
        k.ser.close()


def _scan_round(api, sc, rep, cond):
    for t in ("4S", "2S2P", "TCT", "4P"):
        p = protocol.parse_block(open(f"{inti.DATA_LAB}/{cond}_{t}_u1.csv", encoding="utf8").read().splitlines())
        body = {"uuid": str(uuid.uuid4()), "device_id": "esp32-70", "source": "device",
                "label": f"{sc['condition']}_{t}_u{rep}", "topology": t, "captured_at": f"2026-10-20T03:{10 + rep}:00.000Z",
                "points": {"v": p.v, "i": p.i}, "header": p.header, "complete": p.complete, "raw_text": p.raw_text,
                "scan_uuid": sc["uuid"], "condition": sc["condition"], "repeat": rep}
        assert api.post("/api/v1/ingest/sweeps", json=body).status_code == 201


def test_l3_and_stability_endpoints(tmp_path):
    with server_client(tmp_path) as api:
        heartbeat(api, "esp32-70", active_topology="TCT")
        d = api.get("/api/v1/l3", params={"device_id": "esp32-70"}).json()
        assert d["live"]["wiring"] == "TCT" and d["live"]["holding"]["relay_w"] == pytest.approx(2.145)
        assert d["label"].startswith("calculation") and len(d["net_gain"]) == 3 and d["measured"] == []
        sid = api.post("/api/v1/sessions", json={"device_id": "esp32-70", "place": "outdoor_sun"}).json()["id"]
        sc = api.post(f"/api/v1/sessions/{sid}/scans", json={"code": "F1", "rounds": 6, "pause_s": 0}).json()
        assert sc["dynamic"] is True
        for rep, cond in enumerate(["V1c", "V6_paranet75", "V1c", "V6_paranet75", "V1c", "V6_paranet75"], start=1):
            _scan_round(api, sc, rep, cond)
        s = api.get("/api/v1/stability").json()
        assert s["setting"]["enabled"] is False                                        # off by default
        assert len(s["real"]) == 1 and s["real"][0]["rounds"] == 6
        assert s["real"][0]["policies"]["auto mode + stability rule"]["locks"] >= 1
        assert s["sim"] is None or {"daun", "bergerak", "campuran"} <= set(s["sim"]["mean_pct_mlpe"])
