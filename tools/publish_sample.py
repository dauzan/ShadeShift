"""Test publisher: acts like a gateway and posts real lab sweeps to the server's ingestion API.

It proves the ingestion path (CONTRACT.md §5.2) without any hardware. Everything it sends is labeled honestly:
device kind 'emulator', source 'demo', and replay_of = the lab file that was replayed.

Usage (with the server running:  python run.py server):
    python tools/publish_sample.py
    python tools/publish_sample.py --conditions V1c V3_opak V6_paranet65 --count 12 --interval 1
"""
import argparse
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shadeshift import config, protocol  # noqa: E402


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main():
    s = config.load()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=s.api_url, help=f"server URL (default {s.api_url})")
    ap.add_argument("--device-id", default="publisher-01")
    ap.add_argument("--conditions", nargs="+", default=["V1c", "V3_opak", "V4_paranet65", "V6_paranet65"])
    ap.add_argument("--count", type=int, default=8, help="number of sweeps to send")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between sweeps")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    files = [p for c in args.conditions for p in sorted(Path(s.lab_dir).glob(f"{c}_*_u*.csv"))]
    if not files:
        sys.exit(f"no lab files for {args.conditions} in {s.lab_dir}")
    rng = random.Random(args.seed)
    api = args.api.rstrip("/") + "/api/v1"
    headers = {"X-ShadeShift-Token": s.api_token} if s.api_token else {}
    run_uuid = str(uuid.uuid4())

    def heartbeat(connected=True, ending=False):
        r = requests.post(f"{api}/devices/heartbeat", headers=headers, timeout=10, json={
            "device_id": args.device_id, "kind": "emulator", "transport": "test-publisher", "run_uuid": run_uuid,
            "gateway": {"version": "tools/publish_sample.py"}, "state": {"connected": connected, "ending": ending}})
        r.raise_for_status()

    try:
        heartbeat()
    except requests.RequestException as e:
        sys.exit(f"server not reachable at {args.api} ({e}). Start it with:  python run.py server")
    print(f"publishing {args.count} sweeps as {args.device_id} (source=demo, replayed lab data) to {args.api}")
    for k in range(args.count):
        path = rng.choice(files)
        p = protocol.parse_block(path.read_text(encoding="utf-8").splitlines())
        cond, _, rep = protocol.condition_from_name(path.stem)
        body = {"uuid": str(uuid.uuid4()), "device_id": args.device_id, "run_uuid": run_uuid, "source": "demo",
                "label": f"pub_{k + 1:03d}_{p.topology}", "topology": p.topology, "captured_at": now(),
                "points": {"v": p.v, "i": p.i}, "header": p.header, "condition": cond, "repeat": rep,
                "replay_of": path.name, "complete": p.complete}
        r = requests.post(f"{api}/ingest/sweeps", json=body, headers=headers, timeout=30)
        r.raise_for_status()
        out = r.json()
        d = out["derived"]
        alert = f"  ALERT: {out['alerts'][0]['message']}" if out["alerts"] else ""
        print(f"  #{out['id']:<4} {path.name:<26} {p.topology:<5} Pmax {d['pmax']:.4f} W  Voc {d['voc']:.2f} V{alert}")
        heartbeat()
        time.sleep(args.interval)
    heartbeat(connected=False, ending=True)
    print("done; see them with:  python tools/ws_monitor.py  or  GET /api/v1/sweeps?device_id=" + args.device_id)


if __name__ == "__main__":
    main()
