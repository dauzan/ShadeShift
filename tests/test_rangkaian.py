"""Rekomendasi Rangkaian (CONTRACT §29): the recommendation follows the measurement, 4P is never applied, a change happens
only after a person approves it, monitoring follows the new wiring, the waiting time, going back, the audit trail, and
the 3D page's wiring matches the relay matrix."""
import json
import re
import shutil
import subprocess
import time

import pytest
import requests

from conftest import ROOT, live_server
from shadeshift import commands, rangkaian as RK
from shadeshift.gateway.main import Gateway

STATIC = ROOT / "shadeshift" / "server" / "static"
NOW = "2026-10-22T10:00:00.000Z"


def cmp(**p):
    return {t: {"pmax": v, "at": "2026-10-22T09:55:00.000Z"} for t, v in p.items()}


def test_recommendation_follows_the_measurement():
    s = RK.saran("4S", cmp(**{"4S": 0.49, "2S2P": 0.60, "TCT": 0.61, "4P": 0.66}), {"choice": "TCT", "captured_at": NOW}, NOW)
    assert s["rekomendasi"] == "TCT" and s["sumber"] == "ukur" and s["boleh"]
    assert s["keuntungan"].startswith("Daya terukur naik sekitar 24 persen, dari 0,49 menjadi 0,61 watt")
    assert any("juga memilih silang (TCT)" in x for x in s["alasan"])
    assert any("Tegangan ke alat di rumah turun kira-kira setengah" in x for x in s["kerugian"])
    p4 = next(r for r in s["perbandingan"] if r["rangkaian"] == "4P")
    assert not p4["bisa"] and "24 volt" in p4["catatan"]                     # the highest, but never recommended
    other = RK.saran("4S", cmp(**{"4S": 0.49, "2S2P": 0.60, "TCT": 0.55}), {"choice": "TCT", "captured_at": NOW}, NOW)
    assert other["rekomendasi"] == "2S2P" and any("saran mengikuti pengukuran" in x for x in other["alasan"])


def test_no_change_when_the_current_wiring_is_best_or_the_gain_is_small():
    best = RK.saran("4S", cmp(**{"4S": 0.73, "2S2P": 0.67, "TCT": 0.63}), None, NOW)
    assert best["rekomendasi"] is None and best["judul"].startswith("Rangkaian sekarang, seri (4S), sudah paling baik")
    small = RK.saran("4S", cmp(**{"4S": 0.70, "TCT": 0.71}), None, NOW)       # 1.4 percent: not worth a change
    assert small["rekomendasi"] is None


def test_without_a_fresh_comparison_the_ai_choice_is_said_as_not_measured():
    old = {"4S": {"pmax": 0.5, "at": "2026-10-22T08:00:00.000Z"}, "TCT": {"pmax": 0.9, "at": "2026-10-22T08:00:00.000Z"}}
    s = RK.saran("4S", old, {"choice": "TCT", "captured_at": "2026-10-22T09:59:00.000Z"}, NOW)
    assert s["rekomendasi"] == "TCT" and s["sumber"] == "ai" and s["keuntungan"].startswith("Belum diukur") and not s["segar"]
    none = RK.saran("4S", {}, None, NOW)
    assert none["rekomendasi"] is None and none["judul"].startswith("Belum ada perbandingan")


def test_waiting_time_and_going_back():
    last = {"at": "2026-10-22T09:55:00.000Z", "dari": "4S", "ke": "TCT"}
    s = RK.saran("TCT", cmp(**{"4S": 0.49, "2S2P": 0.65, "TCT": 0.61}), None, NOW, last)
    assert s["rekomendasi"] == "2S2P" and s["jeda_menit"] == 10 and not s["boleh"] and s["kembali"] == "4S"
    later = RK.saran("TCT", cmp(**{"4S": 0.49, "2S2P": 0.65, "TCT": 0.61}), None, "2026-10-22T10:20:00.000Z", last)
    assert later["jeda_menit"] == 0


def test_4p_is_never_applied():
    with pytest.raises(commands.CommandError):
        commands.validate_action("apply_wiring", {"target": "4P"})
    assert commands.validate_action("apply_wiring", {"target": "TCT"}) == {"target": "TCT"}


def test_the_3d_wiring_matches_the_relay_matrix():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js not installed")
    script = r"""
const t = require(process.argv[1]);
const out = {};
for (const [topo, ws] of Object.entries(t.WIRING)) {
  // follow the current: wires in their listed direction, and inside each panel from its negative to its positive
  const edges = {};
  const add = (a, b) => (edges[a] = edges[a] || []).push(b);
  for (const [a, b, kind] of ws) if (kind !== "tie") add(a, b);
  for (const m of "ABCD") add(m + "-", m + "+");
  const seen = new Set(["N"]), todo = ["N"];
  while (todo.length) for (const n of edges[todo.pop()] || []) if (!seen.has(n)) { seen.add(n); todo.push(n); }
  const used = new Set(ws.flatMap(([a, b]) => [a, b]));
  const routes = t.wires(topo).every((w) => w.pts.length >= 4 && w.pts.every((p) => p.every(Number.isFinite)));
  out[topo] = {reachesP: seen.has("P"), allPanels: "ABCD".split("").every((m) => seen.has(m + "+")),
               fixed: used.has("A+") && used.has("D-"), routes, wires: ws.length};
}
console.log(JSON.stringify(out));
"""
    r = subprocess.run([node, "-e", script, str(STATIC / "rangkaian.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert set(out) == {"4S", "2S2P", "TCT", "4P"}
    for topo, v in out.items():
        assert v["reachesP"] and v["allPanels"] and v["fixed"] and v["routes"], (topo, v)
    assert out["4S"]["wires"] == 5 and out["TCT"]["wires"] == 7 and out["4P"]["wires"] == 8
    assert subprocess.run([node, "--check", str(STATIC / "rangkaian.js")]).returncode == 0


def test_page_has_words_only_and_nothing_from_the_internet():
    for f in ("rangkaian.html", "rangkaian.js"):
        text = (STATIC / f).read_text(encoding="utf-8")
        assert not re.search("[\U0001f300-\U0001faff☀-➿]", text), f
        assert "simulasi" not in text.lower() and "https://" not in text
        assert "http://" not in text.replace("http://www.w3.org/2000/svg", ""), f


def _wait(f, s=90):
    end = time.time() + s
    while time.time() < end:
        v = f()
        if v:
            return v
        time.sleep(0.3)
    return f()


def test_compare_approve_and_monitoring_follows(tmp_path):
    with live_server(tmp_path) as (settings, core):
        base = settings.api_url + "/api/v1"
        get = lambda: requests.get(f"{base}/devices/demo-01/rangkaian", timeout=10).json()     # noqa: E731
        gw = Gateway(settings, source="demo", lambat=0, monitor_auto=True)
        gw.start()
        try:
            assert _wait(lambda: gw.monitor.get("on"))
            requests.post(f"{base}/devices/demo-01/commands", timeout=10,
                          json={"kind": "action", "command": "demo_condition", "params": {"condition": "V6_paranet75"}})
            requests.post(f"{base}/devices/demo-01/commands", json={"kind": "action", "command": "compare_wirings"}, timeout=10)
            assert _wait(lambda: core.db.one("SELECT COUNT(*) n FROM sweeps WHERE label LIKE 'banding%'")["n"] >= 4)
            assert _wait(lambda: get()["rekomendasi"], 30)
            s = get()
            assert s["sekarang"] == "4S" and s["rekomendasi"] in ("2S2P", "TCT") and s["sumber"] == "ukur" and s["demo"]
            assert requests.post(f"{base}/devices/demo-01/rangkaian/terapkan", json={"target": "4P"}, timeout=10).status_code == 422
            r = requests.post(f"{base}/devices/demo-01/rangkaian/terapkan", json={"target": s["rekomendasi"]}, timeout=10)
            assert r.status_code == 202
            assert _wait(lambda: get()["sekarang"] == s["rekomendasi"], 60)
            assert _wait(lambda: (get()["terakhir"] or {}).get("sesudah"), 30)
            t = get()["terakhir"]
            assert t["dari"] == "4S" and t["ke"] == s["rekomendasi"] and t["naik_persen"] > 10
            time.sleep(4)                                            # a monitoring sweep later: still on the new wiring
            assert gw.monitor["wiring"] == s["rekomendasi"] and gw.kon.topo == s["rekomendasi"]
            other = "TCT" if s["rekomendasi"] == "2S2P" else "2S2P"
            busy = requests.post(f"{base}/devices/demo-01/rangkaian/terapkan", json={"target": other}, timeout=10)
            assert busy.status_code == 409 and "Tunggu" in busy.json()["detail"]
            back = requests.post(f"{base}/devices/demo-01/rangkaian/terapkan", json={"target": "4S"}, timeout=10)
            assert back.status_code == 202                           # going back is always allowed
            trail = [e["teks"] for e in requests.get(f"{base}/jejak", params={"device_id": "demo-01"}, timeout=30).json()["entries"]]
            assert any(x.startswith("Pengguna menyetujui perubahan rangkaian dari seri (4S)") for x in trail)
            assert any(x.startswith("Relai memindah rangkaian dari seri (4S)") for x in trail)
        finally:
            gw.stop()
