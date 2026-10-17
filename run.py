"""ShadeShift launcher: one entry point for every part of the local system (CONTRACT.md §1.1).

    python run.py server        local API + SQLite on 127.0.0.1:8000 (Ctrl+C to stop)
    python run.py import-lab    import the halogen-lamp lab curves into the database (server must be running)
    python run.py check         check this laptop: Python, packages, ports, lab data, model, digital twin
    python run.py ports         list serial ports (to find the ESP32)
    python run.py test          run all tests

Run it with the project's virtual environment, e.g.  .venv\\Scripts\\python run.py server
Later stages add: gateway, dashboard, demo, live.
"""
import argparse
import importlib
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from shadeshift import __version__, config  # noqa: E402


def cmd_server(settings, args):
    from shadeshift.server.app import main
    main(settings.with_overrides(host=args.host, api_port=args.port))


def cmd_import_lab(settings, args):
    import requests
    headers = {"X-ShadeShift-Token": settings.api_token} if settings.api_token else {}
    try:
        r = requests.post(f"{settings.api_url}/api/v1/import/lab", json={"include_anomalies": args.include_anomalies},
                          headers=headers, timeout=300)
    except requests.RequestException as e:
        sys.exit(f"server not reachable at {settings.api_url} ({e}). Start it first:  python run.py server")
    r.raise_for_status()
    print(r.json())


def _port_free(host, port):
    with socket.socket() as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def cmd_check(settings, args):
    rows, failed = [], False

    def add(name, ok, detail, level="FAIL"):
        nonlocal failed
        rows.append(("OK" if ok else level, name, detail))
        failed |= (not ok and level == "FAIL")

    add("python", sys.version_info >= (3, 11), f"{sys.version.split()[0]} at {sys.executable}")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    add("virtual environment", in_venv, sys.prefix if in_venv else "not in a venv; use .venv\\Scripts\\python", "WARN")
    for mod in ("numpy", "pandas", "scipy", "streamlit", "altair", "fastapi", "uvicorn", "requests", "serial", "pvlib"):
        try:
            m = importlib.import_module(mod)
            add(f"package {mod}", True, getattr(m, "__version__", "installed"))
        except Exception as e:
            add(f"package {mod}", False, f"{type(e).__name__}: {e}")
    try:
        import onnxruntime
        add("package onnxruntime", True, onnxruntime.__version__)
    except Exception as e:
        add("package onnxruntime", False, f"{type(e).__name__}: {e} (edge AI falls back to numpy)", "WARN")
    for name, port in (("API port", settings.api_port), ("dashboard port", settings.dashboard_port)):
        add(name, _port_free(settings.host, port), f"{settings.host}:{port} " +
            ("free" if _port_free(settings.host, port) else "in use (already running, or change it in .env)"), "WARN")
    lab = Path(settings.lab_dir)
    n_lab = len(list(lab.glob("*.csv"))) if lab.is_dir() else 0
    add("lab data", n_lab >= 120, f"{n_lab} CSV files in {lab}")
    weights = Path(settings.ml_dir) / "edge_ai" / "pemilih" / "pemilih_bobot.h"
    add("selector weights", weights.is_file(), str(weights))
    try:
        from shadeshift.server.twin import Twin
        t = Twin()
        add("digital twin", t.available, "available (pvlib)" if t.available else t.reason, "WARN")
    except Exception as e:
        add("digital twin", False, f"{type(e).__name__}: {e}", "WARN")
    width = max(len(r[1]) for r in rows)
    print(f"ShadeShift {__version__} environment check\n")
    for status, name, detail in rows:
        print(f"  [{status:<4}] {name:<{width}}  {detail}")
    print("\nAll required checks passed." if not failed else "\nSome required checks FAILED (see above).")
    return 1 if failed else 0


def cmd_ports(settings, args):
    try:
        from serial.tools import list_ports
    except ImportError:
        sys.exit("pyserial is not installed (pip install -r requirements.txt)")
    ports = list(list_ports.comports())
    if not ports:
        print("no serial ports found (is the ESP32 plugged in, and is its USB driver installed?)")
    for p in ports:
        vid_pid = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "-"
        print(f"  {p.device:<8} {vid_pid:<10} {p.description}")


def cmd_test(settings, args):
    return subprocess.call([sys.executable, "-m", "pytest", *args.pytest_args], cwd=ROOT)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("server", help="run the local API server")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p = sub.add_parser("import-lab", help="import lab curves into the database")
    p.add_argument("--include-anomalies", action="store_true", help="also import the V5 and V1d folders")
    sub.add_parser("check", help="check this laptop")
    sub.add_parser("ports", help="list serial ports")
    p = sub.add_parser("test", help="run the tests")
    p.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    settings = config.load()
    handler = {"server": cmd_server, "import-lab": cmd_import_lab, "check": cmd_check, "ports": cmd_ports,
               "test": cmd_test}[args.cmd]
    sys.exit(handler(settings, args) or 0)


if __name__ == "__main__":
    main()
