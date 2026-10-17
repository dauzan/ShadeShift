"""Stage 0 baseline: the dashboard's own self-test (dasbor/uji_dasbor.py) as pytest tests, plus raw-data integrity."""
import zipfile
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import inti
import koneksi

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "docs" / "before"
ZIP = ROOT / "SHADESHIFT_untuk_Dauzan.zip"
LAB_WORK = ROOT / "SHADESHIFT_ML" / "data" / "data_lab"
LAB_SNAPSHOT = BEFORE / "SHADESHIFT_ML" / "data" / "data_lab"


@pytest.fixture(scope="module")
def W():
    return inti.muat_bobot()


def _files(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def test_selector_matches_c_on_all_lab_4s_curves(W):
    ref = pd.read_csv(Path(inti.PEMILIH) / "referensi_lab_4S.csv")
    matches = 0
    for _, row in ref.iterrows():
        path = LAB_WORK / row.berkas
        if not path.exists():
            path = LAB_WORK / "_V5_anomali_dioda" / row.berkas
        matches += inti.pilih_susunan(inti.baca_berkas(str(path)), W)[0] == row.keputusan_c
    assert len(ref) == 38
    assert matches == 38


def test_lab_losses_match_report(W):
    # LAPORAN_UJI_FISIK.md (lab): selector / fixed 2S2P / fixed TCT / fixed 4S = 0.82 / 2.71 / 4.30 / 12.0 %
    rows = []
    for kond, repeats in inti.daftar_kondisi().items():
        for files in repeats.values():
            pmax = {t: inti.baca_berkas(files[t]).pmax for t in inti.KELAS}
            best = max(pmax.values())
            choice = inti.pilih_susunan(inti.baca_berkas(files["4S"]), W)[0]
            rows.append([(best - pmax[t]) / best * 100 for t in (choice, "2S2P", "TCT", "4S")])
    assert len(rows) == 30
    assert np.allclose(np.array(rows).mean(0).round(2), [0.82, 2.71, 4.30, 12.0], atol=0.01)


def test_emulated_esp32_auto_select_flow(W):
    k = koneksi.Koneksi("TIRUAN", tiruan_kondisi="V6_paranet65", lambat=0)
    try:
        h = k.pilih_sekali(W)
    finally:
        k.tutup()
    assert not h.get("galat")
    assert k.topo == h["pilihan"]
    assert len(k.sapuan) == (1 if h["pilihan"] == "4S" else 2)


def test_raw_lab_data_is_byte_identical_to_snapshot():
    snapshot = _files(LAB_SNAPSHOT)
    assert len(snapshot) >= 150
    assert _files(LAB_WORK) == snapshot, "files were added to or removed from data_lab/"
    for rel in snapshot:
        assert (LAB_WORK / rel).read_bytes() == (LAB_SNAPSHOT / rel).read_bytes(), rel


@pytest.mark.skipif(not ZIP.exists(), reason="original zip not present")
def test_snapshot_matches_original_zip():
    expected = {}
    with zipfile.ZipFile(ZIP) as z:
        for info in z.infolist():
            parts = [p for p in info.filename.replace("\\", "/").split("/") if p][1:]
            if parts and not info.filename.endswith("/"):
                expected["/".join(parts)] = info.CRC
    assert _files(BEFORE) == sorted(expected), "docs/before/ has extra or missing files"
    for rel, crc in expected.items():
        assert zlib.crc32((BEFORE / rel).read_bytes()) & 0xFFFFFFFF == crc, rel


def test_board_test_sketch_uses_current_weights():
    # ANALYSIS D2: the uji_pemilih sketch had a stale copy of the weights.
    current = inti.muat_bobot(str(Path(inti.PEMILIH) / "pemilih_bobot.h"))
    sketch = inti.muat_bobot(str(Path(inti.PEMILIH) / "uji_pemilih" / "pemilih_bobot.h"))
    for key in current:
        assert np.array_equal(current[key], sketch[key]), key
