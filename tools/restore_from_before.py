"""Copy the original project tree from docs/before/ (the extracted zip) into the working tree.

docs/before/ stays an untouched snapshot of SHADESHIFT_untuk_Dauzan.zip. This script copies the parts the
working project needs (SHADESHIFT_ML/, firmware/, rangkaian/, foto/, and UNTUK_DAUZAN.md into docs/team/).

- The six large simulation CSVs (~75 MB, research only) are skipped unless --research-data is given.
- A file that already exists is skipped when it is byte-identical, and reported (never overwritten) when it differs.

Usage:  python tools/restore_from_before.py [--research-data] [--dry-run]
"""
import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "docs" / "before"
PARTS = ["SHADESHIFT_ML", "firmware", "rangkaian", "foto", "UNTUK_DAUZAN.md"]
DESTINATION = {"UNTUK_DAUZAN.md": "docs/team/UNTUK_DAUZAN.md"}     # moved when the docs were reorganized (18 Oct)
# Removed from the working tree on purpose (still in docs/before/): unused, broken or rejected.
EXCLUDE = {
    "SHADESHIFT_ML/cek_inti.py",                              # reads ../_arsip/..., which was never in the zip
    "firmware/siklus_otomatis.py",                            # unreferenced; sends RELAI with panels connected
    "SHADESHIFT_ML/edge_ai/kembaran_lab/cnn_diagnosis.pt",    # rejected CNN (13 % on lab data); pickle file
    "SHADESHIFT_ML/hasil/pohon_d3_TCT.txt",                   # stale result from before the Voc bug fix
    "firmware/shadeshift_firmware/shadeshift_firmware.ino",   # replaced by firmware 3.2 (one firmware since 20 Oct)
    "firmware/CARA_PAKAI.md",                                 # replaced by the one guide for firmware 3.2
}
RESEARCH_CSVS = {
    "SHADESHIFT_ML/data/sim_acak.csv",
    "SHADESHIFT_ML/data/sim_acak_besar.csv",
    "SHADESHIFT_ML/data/sim_grid625.csv",
    "SHADESHIFT_ML/data/sim_grid625_besar.csv",
    "SHADESHIFT_ML/data/diagnosis_sim.csv",
    "SHADESHIFT_ML/data/kembaran/kembaran_acak.csv",
}


def files_to_copy(research_data):
    for part in PARTS:
        src = BEFORE / part
        items = [src] if src.is_file() else sorted(p for p in src.rglob("*") if p.is_file())
        for p in items:
            rel = p.relative_to(BEFORE).as_posix()
            if "__pycache__" in rel or rel in EXCLUDE:
                continue
            if rel in RESEARCH_CSVS and not research_data:
                continue
            yield p, ROOT / DESTINATION.get(rel, rel), rel


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--research-data", action="store_true", help="also copy the six large simulation CSVs")
    ap.add_argument("--dry-run", action="store_true", help="only report what would be copied")
    args = ap.parse_args()
    if not BEFORE.is_dir():
        sys.exit(f"{BEFORE} not found: extract SHADESHIFT_untuk_Dauzan.zip there first")

    copied = same = 0
    conflicts = []
    for src, dst, rel in files_to_copy(args.research_data):
        if dst.exists():
            if filecmp.cmp(src, dst, shallow=False):
                same += 1
            else:
                conflicts.append(rel)
            continue
        if not args.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        copied += 1
    verb = "would copy" if args.dry_run else "copied"
    print(f"{verb} {copied} files, {same} already identical, {len(conflicts)} differ (left untouched)")
    for rel in conflicts:
        print(f"  differs, not overwritten: {rel}")
    if not args.research_data:
        print(f"skipped {len(RESEARCH_CSVS)} large research CSVs (use --research-data to copy them)")


if __name__ == "__main__":
    main()
