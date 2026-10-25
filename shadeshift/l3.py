"""L3, the semiconductor switch layer of the proposal (docs/CONTRACT.md §17): the team's design calculations, and the
holding power of whatever wiring is active.

Design and numbers: SHADESHIFT_ML/saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md and its CSVs (CALCULATION, not built, not measured).
Holding power = power needed to keep the switches closed. Per element (main switch R0/S0 + the topology's switches):
- relay coil: 0.3575 W (5 V x 71.4 mA, SRD-05VDC class; an ASSUMPTION until the team measures the 5 V supply current);
- semiconductor cell: 0.033 W (driver LED 10 mA from 3.3 V, VOM1271 datasheet condition).
Closed relays per wiring = the masks in firmware/shadeshift_firmware/shadeshift_firmware.ino (TOPO), plus R0.
"""
import csv
from pathlib import Path

from shadeshift import inti

RELAY_COIL_W = 1.43 / 4            # daya_kendali.csv: 4S closes 4 elements for 1.43 W
SEMI_CELL_W = 0.132 / 4            # daya_kendali.csv: 4 cells for 0.132 W
CLOSED = {"4S": (1, 4, 5), "2S2P": (1, 2, 3, 4), "TCT": (1, 2, 3, 4, 6), "4P": (2, 3, 7, 8, 9, 10),
          "A": (7,), "B": (2, 8), "C": (3, 9), "D": (10,)}
TARGET_W = 0.25                    # proposal: control power <= 0.25 W


def holding_power(target):
    """{elements, relay_w, semi_w} to hold this wiring (R0 included), or None for an unknown / open wiring."""
    if target not in CLOSED:
        return None
    n = len(CLOSED[target]) + 1
    return {"elements": n, "relay_w": round(n * RELAY_COIL_W, 3), "semi_w": round(n * SEMI_CELL_W, 3)}


def _csv(name):
    path = Path(inti.ML) / "saklar" / name
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def design():
    """The design tables as the research code wrote them, with their labels."""
    return {"holding_by_wiring": [{"wiring": t, **holding_power(t)} for t in CLOSED],
            "net_gain": _csv("keuntungan_bersih.csv"), "conduction_loss": _csv("rugi_hantaran.csv"),
            "switches": _csv("tabel_saklar.csv"), "target_w": TARGET_W,
            "assumptions": "relay coil 0.357 W each (5 V x 71.4 mA, not yet measured); semiconductor cell 0.033 W "
                           "(LED 10 mA at 3.3 V); net gain from simulation (10 W modules, G >= 700 W/m2)",
            "label": "calculation (design, not built)"}
