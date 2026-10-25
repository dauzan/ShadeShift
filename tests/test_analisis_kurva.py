"""I-V curve shape analysis (CONTRACT §20): the six deviations on real lab curves and constructed faults, per-point
explanations for the hover, and the 24-hour / current summaries."""
import os

import numpy as np
import pytest

from shadeshift import analisis_kurva as A, inti, kondisi


def lab(name):
    s = inti.baca_berkas(os.path.join(inti.DATA_LAB, name + ".csv"))
    return np.array(s.V), np.array(s.I)


@pytest.fixture(scope="module")
def twin():
    from shadeshift.server.twin import Twin
    tw = Twin()
    if not tw.available:
        pytest.skip("pvlib not installed: no twin reference")
    return tw


def ref_of(tw, name):
    v, _ = lab(name)
    V, I = tw.curve(name.split("_")[-2], max(v), 1.0, "none")
    return {"v": V, "i": I}


def test_unshaded_lab_curves_read_normal(twin):
    for name in ("V1c_4S_u1", "V1c_TCT_u1"):
        v, i = lab(name)
        r = A.analyze(v, i, ref_of(twin, name), tol_i=0.85)
        assert r["anomalies"] == [], (name, r["anomalies"])
        assert r["headline"] == "Bentuk kurva normal"


def test_shaded_4s_shows_its_step_where_the_current_drops(twin):
    for name in ("V3_opak_4S_u1", "V3_paranet65_4S_u1", "V4_paranet65_4S_u1", "V6_paranet65_4S_u1"):
        v, i = lab(name)
        r = A.analyze(v, i, ref_of(twin, name), tol_i=0.85)
        steps = [a for a in r["anomalies"] if a["code"] == 1]
        assert steps, (name, r["anomalies"])
        assert all(0 < a["v0"] < a["v1"] < r["voc"] for a in steps)
        assert not any(a["code"] == 5 for a in r["anomalies"])        # the low tail after a step is not series resistance


def test_constructed_faults_are_named():
    v, i = lab("V1c_4S_u1")
    ref = {"v": v, "i": i}
    k = int(np.argmax(v * i))
    rs = 0.25 * v[k] / i[k]
    vs = v - i * rs
    m = vs >= 0
    assert A.codes(A.analyze(vs[m], i[m], ref, 0.85)) == {5}                      # series resistance
    assert A.codes(A.analyze(v * 0.75, i, ref, 0.85)) == {3}                       # low voltage
    assert A.codes(A.analyze(v, i * 0.6, ref, 0.85)) == {2}                        # low current
    assert A.codes(A.analyze(v, i, ref)) == set()                                  # itself: nothing
    assert "panel terbaik" in A.analyze(v, i * 0.6, ref, 0.9, acuan="panel terbaik")["anomalies"][0]["title"]


def test_every_point_is_explained_for_the_hover():
    v, i = lab("V3_paranet65_4S_u1")
    r = A.analyze(v, i)
    parts = {p["bagian"] for p in r["points"]}
    assert {"Titik daya terbaik", "Ujung kanan"} <= parts                       # plain words for a home owner
    assert "Sebagian panel terhalang" in parts
    mpp = [p for p in r["points"] if p["bagian"] == "Titik daya terbaik"]
    assert len(mpp) == 1 and mpp[0]["kode"] == 0
    assert all(p["arti"] for p in r["points"])
    assert A.analyze([1, 2], [0.1, 0.0])["ok"] is False                        # too few points: said plainly


def test_summaries_in_sentences():
    v, i = lab("V3_paranet65_4S_u1")
    an = A.analyze(v, i)
    array = [{"at": "2026-10-22T09:00:00.000Z", "topology": "4S", "pmax": float(max(v * i)), "expected": 1.04, "analysis": an}]
    k = kondisi.assess(True, "emulator", [], [], None)
    h = kondisi.history([], [], None, "2026-10-22T10:00:00.000Z")
    s = A.ringkasan(array, {}, k, h)
    assert s["day"]["headline"] == "Ada tanda gangguan dalam 24 jam terakhir"
    assert any(line.startswith("Tanda sebagian panel terhalang terlihat pada 1 dari 1 pengukuran") for line in s["day"]["lines"])
    assert any("biasanya karena bayangan" in line for line in s["now"]["lines"])
    assert "belum divalidasi" in s["basis"]
    words = " ".join(s["day"]["lines"] + s["now"]["lines"])
    for term in ("Voc", "Isc", "MPP", "anak tangga", "susunan 4S", "kurva susunan"):            # no jargon for a home owner
        assert term not in words, term
    empty = A.ringkasan([], {}, k, h)
    assert empty["day"]["lines"][0].startswith("Belum ada pengukuran")
