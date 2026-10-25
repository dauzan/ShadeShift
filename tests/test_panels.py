"""Single-panel sweeps A-D and the light sensor (firmware v2.1 / v3.1, CONTRACT §3.4) through the laptop side:
emulator, gateway INFO handling, server storage, snapshot and upload.

The panel curves are SYNTHETIC (lab 4P curve with the current divided by 4) or come from the lab twin (emulator):
no single-panel recordings exist yet.
"""
import uuid

from conftest import heartbeat, server_client
from shadeshift import config, inti, koneksi, protocol
from shadeshift.gateway.main import Gateway

LAB_4P = f"{inti.DATA_LAB}/V1c_4P_u1.csv"


def _panel_block(panel, light=(1.234, 1.229)):
    s = inti.baca_berkas(LAB_4P)
    rows = [f"# MULAI uji_{panel}", f"# topologi={panel}, Voc={s.voc:.3f} V, dac=2016..2304, N={len(s.V) - 1}",
            f"# cahaya={light[0]:.3f} V", "V,I,P"]
    rows += [f"{a:.4f},{b / 4:.5f},{a * b / 4:.4f}" for a, b in zip(s.V, s.I)]
    rows += ["# Pmax=0.1 W, Vmp=14.000 V, Imp=0.0070 A", f"# cahaya_akhir={light[1]:.3f} V", "# SELESAI"]
    return rows


def test_parse_panel_block_with_light():
    p = protocol.parse_block(_panel_block("C"))
    assert p.topology == "C" and p.complete
    assert p.header["light_v"] == 1.234 and p.header["light_end_v"] == 1.229
    assert protocol.condition_from_name("LR20261020_B3_A_u2.csv") == ("LR20261020_B3", "A", 2)


def test_emulator_answers_panels_from_the_twin(monkeypatch):
    """The lab recordings have no single panels: the emulator computes them with the lab twin for its condition and says
    so in every block ('# tiruan model=kembaran'); without the twin it refuses, as before."""
    from shadeshift.server.twin import Twin
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V3_paranet65", lambat=0)
    try:
        if Twin().available:
            pmax = {}
            for p in "ABCD":
                assert k.pindah(p, batas=60)
                pmax[p] = k.sapu(f"uji_{p}").pmax
            assert pmax["A"] < 0.3 * min(pmax[p] for p in "BCD")          # shade cloth on A in V3
            assert any("# tiruan model=kembaran" in s for _, s in k.log)
        monkeypatch.setattr(k.ser, "_kurva_panel", lambda panel: None)
        assert k.pindah("B") is False
        assert any("tiruan tidak punya data panel tunggal (B)" in s for _, s in k.log)
        assert k.pindah("TCT") is True                   # topologies still replay lab curves
    finally:
        k.hidup = False
        k.ser.close()


def _gateway(tmp_path):
    settings = config.load(env={"SHADESHIFT_DATA_DIR": str(tmp_path)}, env_file=tmp_path / "no.env")
    return Gateway(settings, source="serial", port="SIM")


def test_gateway_reads_v2_1_info(tmp_path):
    gw = _gateway(tmp_path)
    gw._on_line(0.0, "rx", "# INFO fw=2.1.0, id=a1b2c3d4e5f6, n=201, fitur=panel,cahaya")
    assert gw.esp32 == {"fw": "2.1.0", "id": "a1b2c3d4e5f6", "weights": None, "weights_match": None,
                        "features": ["panel", "cahaya"]}
    assert gw.firmware == "v2.1 (2.1.0)"
    assert gw._events[-1]["kind"] == "status" and "runs on this laptop" in gw._events[-1]["message"]


def test_gateway_reads_v3_1_info(tmp_path):
    gw = _gateway(tmp_path)
    ours = gw.selector.model_id.split("@")[1]
    gw._on_line(0.0, "rx", f"# INFO fw=3.1.0, id=a1b2c3d4e5f6, n=201, w={ours}, fitur=panel,cahaya,pemilih")
    assert gw.esp32["weights_match"] is True and gw.esp32["features"] == ["panel", "cahaya", "pemilih"]
    assert gw.firmware == "v3.1 (3.1.0)"


def test_server_stores_panel_sweeps_without_decisions(tmp_path):
    with server_client(tmp_path) as api:
        run = heartbeat(api, "esp32-30")
        ids = {}
        for panel in protocol.PANELS:
            p = protocol.parse_block(_panel_block(panel))
            body = {"uuid": str(uuid.uuid4()), "device_id": "esp32-30", "run_uuid": run, "source": "device",
                    "label": p.label, "topology": p.topology, "captured_at": "2026-10-20T03:15:30.123Z",
                    "points": {"v": p.v, "i": p.i}, "header": p.header, "complete": p.complete}
            r = api.post("/api/v1/ingest/sweeps", json=body)
            assert r.status_code == 201, r.text
            assert not r.json().get("alerts")                     # no twin comparison for one panel
            ids[panel] = r.json()["id"]
        full = api.get(f"/api/v1/sweeps/{ids['B']}").json()
        assert full["topology"] == "B" and full["header"]["light_v"] == 1.234 and full["header"]["light_end_v"] == 1.229
        snap = api.get("/api/v1/devices/esp32-30/snapshot").json()
        assert set(snap["latest_by_panel"]) == set(protocol.PANELS) and snap["latest_by_topology"] == {}
        assert api.get("/api/v1/decisions", params={"device_id": "esp32-30"}).json() == []


def test_upload_with_panel_override(tmp_path):
    text = "\n".join(_panel_block("D")).replace("topologi=D", "topologi=?").encode()
    with server_client(tmp_path) as api:
        r = api.post("/api/v1/uploads", files=[("files", ("panel.csv", text, "text/csv"))], data={"topology": "D"})
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["status"] == "ok" and res["sweeps"][0]["topology"] == "D" and not res["sweeps"][0].get("decision")
        assert api.post("/api/v1/uploads", files=[("files", ("x.csv", text, "text/csv"))],
                        data={"topology": "E"}).status_code == 400
