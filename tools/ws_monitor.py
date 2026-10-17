"""Print the server's live WebSocket stream (CONTRACT.md §5.7), one line per message. Ctrl+C to stop.

Usage:  python tools/ws_monitor.py [--device demo-01] [--raw]
"""
import argparse
import json
import sys
from pathlib import Path

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shadeshift import config  # noqa: E402


def describe(msg):
    t, d = msg.get("type"), msg.get("data") or {}
    if t == "sweep":
        return (f"sweep    #{d['id']} {d['device_id']} {d['source']:<6} {d['topology']:<5} Pmax={d['pmax']} W "
                f"complete={d['complete']}" + (f" replay_of={d['replay_of']}" if d.get("replay_of") else ""))
    if t == "decision":
        return (f"decision {d['device_id']} {d['choice']} by {d['decided_by']} ({d['trigger']}, "
                f"{d.get('latency_us')} us, applied={d['applied']})")
    if t == "event":
        return f"event    {d.get('device_id')} [{d['kind']}] {d['message']}"
    if t == "device":
        return f"device   {d['id']} online={d['online']} state={json.dumps(d.get('state'))[:120]}"
    if t == "command":
        return f"command  #{d['id']} {d.get('command', '')} -> {d['status']} {d.get('result') or ''}"
    return json.dumps(msg)


def main():
    s = config.load()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default=s.api_url)
    ap.add_argument("--device", default=None, help="only messages for this device id")
    ap.add_argument("--raw", action="store_true", help="print the raw JSON")
    args = ap.parse_args()
    url = args.api.replace("http://", "ws://", 1).replace("https://", "wss://", 1).rstrip("/") + "/api/v1/stream"
    if args.device:
        url += f"?device_id={args.device}"
    try:
        with connect(url, open_timeout=5) as ws:
            print(f"connected to {url}")
            for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    continue
                print(raw if args.raw else describe(msg), flush=True)
    except KeyboardInterrupt:
        pass
    except OSError as e:
        sys.exit(f"cannot connect to {url} ({e}). Start the server with:  python run.py server")


if __name__ == "__main__":
    main()
