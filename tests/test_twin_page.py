"""The Digital Twin page (CONTRACT §18): geometry (in Node), what-if, live state, markers, and that it is self-contained."""
import json
import re
import shutil
import subprocess
import time

import pytest
import requests

from conftest import ROOT, live_server, server_client
from shadeshift import twinview
from shadeshift.gateway.main import Gateway

STATIC = ROOT / "shadeshift" / "server" / "static"


def test_geometry_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js not installed: page geometry not tested")
    script = r"""
const t = require(process.argv[1]);
const c = (m) => t.project(t.W(t.panelCenter(m)), t.HOME);
const out = {};
out.leftRight = c('A')[0] < c('C')[0] && c('B')[0] < c('D')[0];          // A and B on the left, as built
out.frontLower = c('B')[1] > c('A')[1] && c('D')[1] > c('C')[1];          // front row (B, D) lower on screen
out.topVisible = t.dot(t.boxFaces({x: 0, y: 0, w: 1, h: 1, z0: 0, z1: 1})[0].n, t.viewer(t.HOME)) > 0;
out.bottomHidden = t.dot(t.boxFaces({x: 0, y: 0, w: 1, h: 1, z0: 0, z1: 1})[1].n, t.viewer(t.HOME)) < 0;
out.topView = t.project([10, 20, 3], {yaw: 0, pitch: 90}).slice(0, 2).map((v) => Math.round(v * 1e6) / 1e6);
out.ref = t.project([0, 0, 0], {yaw: 0, pitch: 90}).slice(0, 2).map((v) => Math.round(v * 1e6) / 1e6);
const parts = 'ABCD'.split('').map((m) => t.backParts(m));
out.cablesToWago = parts.every((p) => p.cable[p.cable.length - 1][0] === t.WAGO.x);
out.terminalUnderPanel = 'ABCD'.split('').every((m, k) => {
  const [ox, oy] = t.ORIGIN[m], tb = parts[k].tb;
  return tb.x > ox && tb.x + tb.w < ox + t.PANEL_W && tb.y > oy + t.PANEL_H / 2 && tb.y + tb.h < oy + t.PANEL_H && tb.z1 <= t.RAIL;
});
out.slots = new Set(parts.map((p) => p.slot[1])).size;
out.colors = t.COLOR.object !== t.COLOR.normal && t.COLOR.diode === t.COLOR.cable;
out.roofs = {};
for (const type of Object.keys(t.ROOF_TYPES)) {             // every roof type carries the array on its sun-facing slope
  t.setRoof(type);
  const g = t.ROOFGEO, H = t.HOUSE;
  const above = 'ABCD'.split('').every((m) => { const c = t.W(t.panelCenter(m, t.RAIL)); return c[2] >= g.zRoof(c[1]) - 1e-6; });
  const track = t.flashTrack(), first = track[0], last = track[track.length - 1];
  const atBox = (q) => Math.abs(q[2] - t.BOX.z1) < 1e-6 && q[0] > t.BOX.x && q[0] < t.BOX.x + t.BOX.w;
  const half = t.along(track, t.trackLength(track) / 2);
  const roofPts = track.slice(4, -4).concat(t.panelLeads().map((l) => l[0]));          // the cable lies on the roof
  const onRoof = roofPts.every((q) => q[2] >= g.zRoof(q[1]) - 1e-6 && q[2] <= g.zRoof(q[1]) + 1);
  const leads = t.panelLeads().every((l) => l[1][2] >= l[0][2] - 1e-6);              // leads climb to the panel frame
  const flat = g.faces.every((f) => f.p.every((q) => Math.abs(t.dot(f.n, [q[0] - f.p[0][0], q[1] - f.p[0][1], q[2] - f.p[0][2]])) < 1e-6));
  const gablets = g.faces.filter((f) => f.wall).every((f) => f.p.every((q) => q[2] > 44 && q[2] <= g.Zr + 1e-6));
  const porch = !g.porch || (g.porch.x1 < t.BOX.x && g.porch.zTop < H.zf && g.porch.y0 >= H.yf - 1e-6);
  out.roofs[type] = {above, faces: g.faces.length, frontSlope: g.rt.flat || g.faces.some((f) => f.slope), flat, gablets, porch,
                     walls: H.zf > 0 && H.zb > 0 && H.x0 > t.ROOF.x0 && H.x1 < t.ROOF.x1,
                     loop: atBox(first) && atBox(last) && half[2] > t.BOX.z1, cable: onRoof && leads};
}
t.setRoof('pelana');
out.roofFacesFront = t.R([0, 0, 1])[1] > 0;                                   // tilted towards the sun (front)
console.log(JSON.stringify(out));
"""
    r = subprocess.run([node, "-e", script, str(STATIC / "twin.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["leftRight"] and out["frontLower"]                  # the raised three-quarter view keeps the layout readable
    assert out["topVisible"] and out["bottomHidden"]
    assert [a - b for a, b in zip(out["topView"], out["ref"])] == pytest.approx([10, 20])   # straight down: plain top view
    assert out["cablesToWago"] and out["terminalUnderPanel"] and out["slots"] == 4
    assert out["colors"]
    assert out["roofFacesFront"]
    assert set(out["roofs"]) == {"pelana", "perisai", "gablet", "gambrel", "kampung", "saltbox", "sandar", "datar"}
    for name, r in out["roofs"].items():                                        # flashes leave and return to the box
        assert r["above"] and r["frontSlope"] and r["walls"] and r["loop"] and r["cable"] and r["faces"] >= 4, (name, r)
        assert r["flat"] and r["gablets"] and r["porch"], (name, r)       # planar faces; the porch stays clear of the box
    assert subprocess.run([node, "--check", str(STATIC / "twin.js")]).returncode == 0


def test_page_has_words_only():
    """Consumer page: Indonesian words, no emoji or pictogram symbols (decision 22 Oct)."""
    text = (STATIC / "twin.html").read_text(encoding="utf-8") + (STATIC / "twin.js").read_text(encoding="utf-8")
    assert not re.search(r"[🌀-🫿☀-➿←-⇿■-◿]", text)
    assert "simulasi" not in text.lower()                                      # demo data is labelled "Mode demo"
    assert "Mode demo" in text and "Data demo" in text


def test_page_loads_nothing_from_the_internet():
    html = (STATIC / "twin.html").read_text(encoding="utf-8")
    js = (STATIC / "twin.js").read_text(encoding="utf-8")
    assert '<script src="/twin/twin.js">' in html
    assert not re.search(r"(src|href)\s*=\s*[\"']?https?://", html + js)
    assert not re.search(r"fetch\(\s*[\"'`]https?://", js) and "@import" not in html
    assert set(re.findall(r"https?://[^\s\"'`]+", html + js)) <= {"http://www.w3.org/2000/svg"}   # SVG namespace only


def test_markers_draw_only_what_the_data_knows():
    pmap = {"modules": {"A": {"status": "strongly_reduced", "hint": "shaded_or_dimmed", "power_rel": 0.5, "isc_rel": 0.5, "voc_rel": 1.0},
                        "B": {"status": "reduced", "hint": "bypassed_cells", "power_rel": 0.7, "isc_rel": 1.0, "voc_rel": 0.7},
                        "C": {"status": "normal", "hint": None, "power_rel": 1.0, "isc_rel": 1.0, "voc_rel": 1.0},
                        "D": {"status": "reduced", "hint": "series_resistance", "power_rel": 0.8, "isc_rel": 1.0, "voc_rel": 1.0}},
            "reference": "the best panel in this round"}
    m = twinview.markers({"map": pmap})
    assert {k: v["kind"] for k, v in m.items()} == {"A": "light", "B": "electrical", "C": "healthy", "D": "electrical"}
    assert not any(v["dashed"] for v in m.values())
    p = twinview.markers({"map": None, "pattern": {"class": "string_pair"}})
    assert set(p) == set("ABCD") and all(v["dashed"] and v["kind"] == "unknown" for v in p.values())
    low = twinview.markers(None, deviation_pct=-30, threshold_pct=15)
    assert all(v["dashed"] and v["basis"] == "twin" for v in low.values())
    assert all(v["kind"] == "healthy" for v in twinview.markers(None, deviation_pct=-5).values())
    assert twinview.markers(None) == {}


def test_whatif(tmp_path):
    with server_client(tmp_path) as api:
        if not api.core.twin.available:
            pytest.skip("pvlib not installed: twin unavailable")
        exp = api.get("/api/v1/twin/expected").json()["pmax"]
        none = api.post("/api/v1/twin/whatif", json={}).json()
        assert all(none["pmax"][t] == pytest.approx(exp[t], abs=1e-6) for t in exp)        # no shade = the expectation
        assert none["mlpe_w"] >= max(none["pmax"][t] for t in ("4S", "2S2P", "TCT"))
        a = api.post("/api/v1/twin/whatif", json={"coverage": {"A": [1.0] * 36}}).json()
        assert a["modules"]["A"] < 0.05 * none["modules"]["A"] and a["modules"]["B"] == pytest.approx(none["modules"]["B"], rel=1e-6)
        assert a["mlpe_w"] < none["mlpe_w"] and a["covered_cells"] == {"A": 36}
        assert a["ai"]["choice"] in ("4S", "2S2P", "TCT") and a["label"].startswith("simulation")
        cloth = api.post("/api/v1/twin/whatif", json={"coverage": {"A": [1.0] * 36}, "kind": "cloth"}).json()
        assert a["modules"]["A"] < cloth["modules"]["A"] < none["modules"]["A"]           # shade cloth lets some light through
        half = api.post("/api/v1/twin/whatif", json={"scale": 0.5}).json()
        assert half["mlpe_w"] < none["mlpe_w"]
        assert api.post("/api/v1/twin/whatif", json={"coverage": {"A": [1.0] * 35}}).status_code == 422
        assert api.post("/api/v1/twin/whatif", json={"coverage": {"E": [0.0] * 36}}).status_code == 422
        assert api.get("/api/v1/twin/state", params={"device_id": "nobody"}).status_code == 404
        assert "<svg" in api.get("/twin").text and api.get("/twin/twin.js").headers["content-type"].startswith("application/javascript")


def test_live_state_of_the_demo_device(tmp_path):
    with live_server(tmp_path) as (settings, core):
        base = settings.api_url + "/api/v1"
        gw = Gateway(settings, source="demo", lambat=0)
        gw.start()
        try:
            end = time.time() + 30
            while time.time() < end and not core.db.one("SELECT 1 FROM devices WHERE id='demo-01'"):
                time.sleep(0.1)
            requests.post(f"{base}/devices/demo-01/commands", json={"kind": "action", "command": "auto_select"}, timeout=10)
            end = time.time() + 60
            st = None
            while time.time() < end:
                st = requests.get(f"{base}/twin/state", params={"device_id": "demo-01"}, timeout=30).json()
                if st["wiring"] and st["last_sweep"]:
                    break
                time.sleep(0.5)
            assert st["device"]["kind"] == "emulator" and st["wiring"] in ("4S", "2S2P", "TCT")
            from shadeshift import l3
            assert st["relays"] == [0] + list(l3.CLOSED[st["wiring"]])
            assert st["last_sweep"]["pmax"] > 0 and set(st["latest"]) >= {"4S"}
            if core.twin.available:
                assert st["expected"] and st["deviation_pct"] is not None and set(st["markers"]) == set("ABCD")
            assert st["monitor"] == {"on": False} and st["kondisi"]["status"]["level"] in ("ok", "problem", "nodata")
            assert st["kondisi"]["demo"] is True
        finally:
            gw.stop()
