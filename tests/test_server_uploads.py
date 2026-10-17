"""CSV upload page backend and lab import (CONTRACT §5.5, §6)."""
import hashlib
from pathlib import Path

import numpy as np
import pytest

from conftest import ROOT, server_client
from shadeshift import inti

SAMPLES = ROOT / "samples"
LAB = Path(inti.DATA_LAB)


def _upload(client, *names, **form):
    files = [("files", (n, (SAMPLES / n).read_bytes(), "text/csv")) for n in names]
    r = client.post("/api/v1/uploads", files=files, data=form)
    assert r.status_code == 200, r.text
    return {x["filename"]: x for x in r.json()["results"]}


def test_samples_accepted_and_rejected(tmp_path):
    with server_client(tmp_path) as c:
        res = _upload(c, "V3_opak_4S_u1.csv", "V1c_TCT_u1_plain.csv", "V1c_TCT_u1_plain_mA.csv",
                      "bad_too_few_points.csv", "bad_non_numeric.csv")
        assert res["V3_opak_4S_u1.csv"]["status"] == "ok"
        s = res["V3_opak_4S_u1.csv"]["sweeps"][0]
        assert s["topology"] == "4S" and s["decision"]["decided_by"] in ("server_onnx", "server_numpy")
        assert s["decision"]["choice"] == inti.pilih_susunan(inti.baca_berkas(str(LAB / "V3_opak_4S_u1.csv")), inti.muat_bobot())[0]
        amps, milli = res["V1c_TCT_u1_plain.csv"]["sweeps"][0], res["V1c_TCT_u1_plain_mA.csv"]["sweeps"][0]
        assert amps["topology"] == milli["topology"] == "TCT"
        assert milli["pmax"] == pytest.approx(amps["pmax"], rel=1e-3)
        assert res["bad_too_few_points.csv"]["status"] == "rejected" and "valid points" in res["bad_too_few_points.csv"]["error"]
        assert res["bad_non_numeric.csv"]["status"] == "rejected" and "numbers" in res["bad_non_numeric.csv"]["error"]
        full = c.get(f"/api/v1/sweeps/{s['id']}").json()
        assert full["source"] == "upload" and full["condition"] == "V3_opak" and full["repeat"] == 1
        again = _upload(c, "V3_opak_4S_u1.csv")["V3_opak_4S_u1.csv"]
        assert again["status"] == "duplicate" and again["sweep_ids"] == [s["id"]]
        uploads = c.get("/api/v1/uploads").json()
        assert sorted(u["status"] for u in uploads) == ["ok", "ok", "ok", "rejected", "rejected"]
        csv_back = c.get(f"/api/v1/sweeps/{s['id']}/csv").text
        reup = c.post("/api/v1/uploads", files=[("files", ("roundtrip_4S.csv", csv_back.encode(), "text/csv"))]).json()
        assert reup["results"][0]["sweeps"][0]["pmax"] == pytest.approx(s["pmax"], abs=1e-6)


def test_upload_limits(tmp_path):
    with server_client(tmp_path) as c:
        files = [("files", (f"f{k}.csv", b"V,I\n1,0\n", "text/csv")) for k in range(51)]
        assert c.post("/api/v1/uploads", files=files).status_code == 413
        big = b"V,I\n" + b"1.0,0.1\n" * 700_000
        r = c.post("/api/v1/uploads", files=[("files", ("big.csv", big, "text/csv"))]).json()["results"][0]
        assert r["status"] == "rejected" and "larger than" in r["error"]
        assert c.post("/api/v1/uploads", files=[("files", ("x.csv", b"V,I\n", "text/csv"))],
                      data={"topology": "5S"}).status_code == 400


def _lab_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in LAB.rglob("*.csv")}


def test_lab_import_is_read_only_idempotent_and_reproduces_report(tmp_path):
    before = _lab_hashes()
    with server_client(tmp_path) as c:
        assert c.post("/api/v1/import/lab").json() == {"imported": 120, "skipped_duplicates": 0}
        assert c.post("/api/v1/import/lab").json() == {"imported": 0, "skipped_duplicates": 120}
        conds = c.get("/api/v1/conditions", params={"source": "lab"}).json()
        assert len(conds) == 10
        losses = []
        for cond in conds:
            for rep in cond["repeats"].values():
                pm = {t: c.get(f"/api/v1/sweeps/{rep[t]}").json()["pmax"] for t in ("4S", "2S2P", "TCT")}
                choice = c.get(f"/api/v1/sweeps/{rep['4S']}").json()["decision"]["choice"]
                best = max(pm.values())
                losses.append([(best - pm[t]) / best * 100 for t in (choice, "2S2P", "TCT", "4S")])
        assert len(losses) == 30
        # LAPORAN_UJI_FISIK.md (lab): selector / fixed 2S2P / fixed TCT / fixed 4S
        assert np.allclose(np.array(losses).mean(0).round(2), [0.82, 2.71, 4.30, 12.0], atol=0.01)
        incomplete = [s for s in c.get("/api/v1/sweeps", params={"source": "lab", "limit": 1000}).json() if not s["complete"]]
        assert [s["label"] for s in incomplete] == ["V3_paranet75_TCT_u2"]
        assert c.post("/api/v1/import/lab", json={"include_anomalies": True}).json()["imported"] == 34
    assert _lab_hashes() == before
