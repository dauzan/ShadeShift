"""Write the sample upload files in samples/ from real lab curves (data_lab is only read).

Usage:  python tools/make_samples.py
The files exercise both accepted formats and the two most common rejections (docs/CONTRACT.md §6).
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shadeshift import protocol  # noqa: E402

LAB = ROOT / "SHADESHIFT_ML" / "data" / "data_lab"
OUT = ROOT / "samples"

README = """# Sample upload files

Use them on the dashboard's **Unggah CSV** page or with `POST /api/v1/uploads` (docs/CONTRACT.md §5.5). Regenerate with
`python tools/make_samples.py`. All curves are real halogen-lamp lab measurements from `SHADESHIFT_ML/data/data_lab/`
(that folder is only read, never written).

| File | Format | Expected result |
|---|---|---|
| `V3_opak_4S_u1.csv` | Firmware/logger format, exact copy of the lab file | Accepted; topology 4S from the header; condition `V3_opak`, repeat 1; selector decision |
| `V1c_TCT_u1_plain.csv` | Plain CSV `V,I` (amperes), converted from `V1c_TCT_u1.csv` | Accepted; topology TCT from the file name |
| `V1c_TCT_u1_plain_mA.csv` | Plain CSV `V,I_mA` (milliamperes), same curve | Accepted; current divided by 1000; same Pmax as the file above |
| `bad_too_few_points.csv` | Plain CSV with 5 rows | Rejected: fewer than 10 valid points |
| `bad_non_numeric.csv` | Plain CSV with text in a value | Rejected: values must be numbers |
"""


def main():
    OUT.mkdir(exist_ok=True)
    shutil.copyfile(LAB / "V3_opak_4S_u1.csv", OUT / "V3_opak_4S_u1.csv")
    p = protocol.parse_block((LAB / "V1c_TCT_u1.csv").read_text(encoding="utf-8").splitlines())
    rows = list(zip(p.v, p.i))
    (OUT / "V1c_TCT_u1_plain.csv").write_text("V,I\n" + "".join(f"{v:.4f},{i:.5f}\n" for v, i in rows), encoding="utf-8")
    (OUT / "V1c_TCT_u1_plain_mA.csv").write_text("V,I_mA\n" + "".join(f"{v:.4f},{i * 1000:.2f}\n" for v, i in rows),
                                                 encoding="utf-8")
    (OUT / "bad_too_few_points.csv").write_text("V,I\n" + "".join(f"{v:.4f},{i:.5f}\n" for v, i in rows[:5]),
                                                encoding="utf-8")
    (OUT / "bad_non_numeric.csv").write_text("V,I\n" + "".join(f"{v:.4f},{i:.5f}\n" for v, i in rows[:20])
                                             + "12.5,abc\n", encoding="utf-8")
    (OUT / "README.md").write_text(README, encoding="utf-8")
    print(f"wrote {len(list(OUT.glob('*')))} files to {OUT}")


if __name__ == "__main__":
    main()
