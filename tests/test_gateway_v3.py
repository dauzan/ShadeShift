"""Gateway with firmware v3 (on-board AI): the ESP32's decision is applied, the laptop cross-checks it.

Uses a TEST-ONLY fake serial device that answers like firmware v3 (INFO + '# pemilih=' line). The real firmware's
output format and C model are verified separately in test_firmware_v3.py.
"""
import time

import requests

from conftest import live_server
from shadeshift import koneksi, protocol
from shadeshift.edge.selector import EdgeSelector
from shadeshift.gateway.main import Gateway

OURS = EdgeSelector(runtime="numpy").model_id.split("@")[1]


class FakeV3(koneksi.ESPTiruan):
    """SYNTHETIC: replays lab curves and adds the v3 lines, computed with the Python port of pemilih.h."""

    def __init__(self, condition, w, override=None):
        super().__init__(condition, lambat=0, seed=1)
        self.w, self.override = w, override

    def _jalankan(self, baris):
        cmd = baris.split()[0].upper() if baris.strip() else ""
        if cmd == "INFO":
            return self._cetak(f"# INFO fw=3.0.0, id=a1b2c3d4e5f6, n=201, w={self.w}")
        if cmd == "SWEEP" and self.topo == "4S":
            blok, asli = [], self._cetak
            self._cetak = lambda *b: blok.extend(b)
            try:
                super()._jalankan(baris)
            finally:
                self._cetak = asli
            p = protocol.parse_block(blok)
            d = EdgeSelector(runtime="numpy").decide(p.v, p.i)
            pilih = self.override or d.choice
            k = next(n for n, ln in enumerate(blok) if ln.startswith("# SELESAI"))
            blok.insert(k, f"# pemilih={pilih}, skor={d.scores[0]:.4f};{d.scores[1]:.4f};{d.scores[2]:.4f}, t_us=850")
            return asli(*blok)
        return super()._jalankan(baris)


class GatewayV3(Gateway):
    def __init__(self, settings, fake):
        super().__init__(settings, source="serial", port="SIM", lambat=0)
        self.fake = fake

    def connect(self):
        self.kon = koneksi.Koneksi("TIRUAN", simpan=False, lambat=0)
        self.kon.ser = self.fake                     # the reader thread now talks to the fake v3 device
        self.firmware = "v2"
        self.kon.pengamat_baris.append(self._on_line)
        self.kon.pengamat_sapuan.append(self._on_sweep)
        self.kon.pengamat_pilih.append(self._on_selection)
        self.kon.kirim("INFO")


def _wait(pred, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.1)


def _auto_select(settings, core):
    cid = requests.post(f"{settings.api_url}/api/v1/devices/esp32-01/commands",
                        json={"kind": "action", "command": "auto_select"}, timeout=10).json()["id"]
    return _wait(lambda: core.db.one("SELECT status, result FROM commands WHERE id=? AND status IN ('done','failed')", (cid,)))


def test_esp32_decision_is_applied_and_cross_checked(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = GatewayV3(settings, FakeV3("V6_paranet65", OURS))
        gw.start()
        try:
            assert _wait(lambda: gw.esp32) == {"fw": "3.0.0", "id": "a1b2c3d4e5f6", "weights": OURS, "weights_match": True}
            assert _auto_select(settings, core)["result"] == "TCT"
            rows = _wait(lambda: (lambda r: r if len(r) >= 2 else None)(
                core.db.query("SELECT decided_by, trigger, applied, choice, model_id, latency_us FROM decisions ORDER BY id")))
        finally:
            gw.stop()
        applied = [r for r in rows if r["applied"]]
        assert len(applied) == 1 and applied[0]["decided_by"] == "esp32" and applied[0]["trigger"] == "auto_once"
        assert applied[0]["model_id"] == f"pemilih-logreg-v1@{OURS}" and applied[0]["latency_us"] == 850
        cross = [r for r in rows if not r["applied"]]
        assert [r["decided_by"] for r in cross] in (["gateway_onnx"], ["gateway_numpy"])   # cross-check, not duplicated
        dev = core.db.one("SELECT firmware, state_json FROM devices WHERE id='esp32-01'")
        assert dev["firmware"] == "v3 (3.0.0)"
        assert any(e["message"].endswith("on-board AI active") for e in core.db.query("SELECT message FROM events"))


def test_disagreement_is_reported_and_esp32_wins(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = GatewayV3(settings, FakeV3("V6_paranet65", OURS, override="2S2P"))
        gw.start()
        try:
            assert _auto_select(settings, core)["result"] == "2S2P"           # the device's decision is applied
            assert _wait(lambda: core.db.query("SELECT 1 FROM events WHERE message LIKE 'ESP32 chose 2S2P%'"))
        finally:
            gw.stop()


def test_stale_weights_on_the_board_raise_an_error(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = GatewayV3(settings, FakeV3("V1c", "0dd195b615ea"))      # the old weights from the stale test sketch
        gw.start()
        try:
            assert _wait(lambda: gw.esp32) and gw.esp32["weights_match"] is False
            assert _wait(lambda: core.db.query("SELECT 1 FROM events WHERE kind='error' AND message LIKE '%differ%'"))
        finally:
            gw.stop()


def test_emulator_never_produces_esp32_decisions(tmp_path):
    with live_server(tmp_path) as (settings, core):
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            _wait(lambda: core.db.one("SELECT 1 FROM devices WHERE id='demo-01'"))
            cid = requests.post(f"{settings.api_url}/api/v1/devices/demo-01/commands",
                                json={"kind": "action", "command": "auto_select"}, timeout=10).json()["id"]
            _wait(lambda: core.db.one("SELECT 1 FROM commands WHERE id=? AND status='done'", (cid,)))
            time.sleep(1.5)
        finally:
            gw.stop()
        assert not core.db.query("SELECT 1 FROM decisions WHERE decided_by='esp32'")
