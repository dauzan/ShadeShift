"""ShadeShift launcher: one entry point for every part of the local system (docs/CONTRACT.md §1.1).

    python run.py demo          everything without hardware: server + emulated ESP32 + dashboard, opens the browser
    python run.py demo --scenario        ... and play the default shading scenario (or --scenario kilat)
    python run.py live          everything with the ESP32 on USB (port auto-detected; --port COM5 overrides),
                                plus a standby demo device to switch to if the hardware fails
    python run.py dashboard     only the dashboard (http://127.0.0.1:8501)
    python run.py server        local API + SQLite on 127.0.0.1:8000 (Ctrl+C to stop)
    python run.py gateway --source serial [--port COM5]   edge gateway for the real ESP32 (port auto-detected)
    python run.py gateway --source demo                   edge gateway with the emulated ESP32 (replays lab curves)
    python run.py import-lab    import the halogen-lamp lab curves into the database (server must be running)
    python run.py check         check this laptop: Python, packages, ports, lab data, model, digital twin
    python run.py ports         list serial ports (to find the ESP32)
    python run.py test          run all tests

Run it with the project's virtual environment, e.g.  .venv\\Scripts\\python run.py demo
Stop with Ctrl+C in the same window: the gateways open all relays first. Closing the window skips that step.
"""
import argparse
import importlib
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from shadeshift import __version__, config  # noqa: E402


def cmd_server(settings, args):
    from shadeshift.server.app import main
    main(settings.with_overrides(host=args.host, api_port=args.port))


def cmd_gateway(settings, args):
    from shadeshift.gateway.main import main
    main(settings.with_overrides(source=args.source, serial_port=args.port, edge_runtime=args.runtime),
         source=args.source, port=args.port, device_id=args.device_id, standby=args.standby)


DASHBOARD_HOST = "127.0.0.1"          # never exposed on the network: the dashboard can switch relays


def dashboard_command(settings):
    return [sys.executable, "-m", "streamlit", "run", str(ROOT / "dasbor" / "app.py"),
            "--server.address", DASHBOARD_HOST, "--server.port", str(settings.dashboard_port),
            "--server.headless", "true", "--server.showEmailPrompt", "false",
            "--browser.gatherUsageStats", "false", "--client.toolbarMode", "minimal",
            "--client.showErrorDetails", "type"]


def cmd_dashboard(settings, args):
    return subprocess.call(dashboard_command(settings), cwd=ROOT)


def _wait_http(url, timeout, procs=()):
    end = time.time() + timeout
    while time.time() < end:
        if any(p.poll() is not None for p in procs):
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


WINDOWS = sys.platform == "win32"
# Server and dashboard get their own process group: Ctrl+C does not reach them, so the launcher can stop them
# AFTER the gateways have opened the relays and sent their last data. Gateways stay in this group and get Ctrl+C.
OWN_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}


def _soft_stop(p):
    """Ask a child in its own process group to shut down cleanly (CTRL_BREAK on Windows, SIGINT elsewhere)."""
    try:
        p.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGINT)
    except (OSError, ValueError):
        pass


def _start_all(settings, serial_port=None, live=False, open_browser=True, scenario=None):
    """Start server, gateway(s) and dashboard as child processes in this console; supervise until Ctrl+C."""
    for name, port in (("API", settings.api_port), ("dashboard", settings.dashboard_port)):
        if not _port_free("127.0.0.1", port):
            sys.exit(f"Port {port} ({name}) is in use: ShadeShift may already be running in another window. "
                     "Close it, or change the port in .env.")
    me = [sys.executable, str(ROOT / "run.py")]
    procs = {}
    try:
        print("Starting the local server ...")
        procs["server"] = subprocess.Popen(me + ["server"], cwd=ROOT, **OWN_GROUP)
        if not _wait_http(f"{settings.api_url}/api/v1/health", 60, [procs["server"]]):
            raise RuntimeError("the server did not start; see the messages above")
        import requests
        headers = {"X-ShadeShift-Token": settings.api_token} if settings.api_token else {}
        if not requests.get(f"{settings.api_url}/api/v1/conditions", params={"source": "lab"}, timeout=10).json():
            print("Importing the 120 lab curves into the database (read-only, once) ...")
            requests.post(f"{settings.api_url}/api/v1/import/lab", json={}, headers=headers, timeout=300)
        if live:
            cmd = me + ["gateway", "--source", "serial"] + (["--port", serial_port] if serial_port else [])
            procs["gateway-esp32"] = subprocess.Popen(cmd, cwd=ROOT)
            procs["gateway-demo"] = subprocess.Popen(me + ["gateway", "--source", "demo", "--standby"], cwd=ROOT)
        else:
            procs["gateway-demo"] = subprocess.Popen(me + ["gateway", "--source", "demo"], cwd=ROOT)
        procs["dashboard"] = subprocess.Popen(dashboard_command(settings), cwd=ROOT, **OWN_GROUP)
        if scenario:
            end = time.time() + 60
            while time.time() < end and not any(d["id"] == "demo-01" and d["online"] for d in
                                                requests.get(f"{settings.api_url}/api/v1/devices", timeout=5).json()):
                time.sleep(0.5)
            r = requests.post(f"{settings.api_url}/api/v1/devices/demo-01/commands", headers=headers, timeout=10,
                              json={"kind": "action", "command": "demo_scenario_start", "params": {"name": scenario}})
            print(f"Demo scenario '{scenario}': {'queued' if r.status_code == 202 else r.text}")
        url = f"http://{DASHBOARD_HOST}:{settings.dashboard_port}"
        if _wait_http(url + "/_stcore/health", 90, [procs["dashboard"]]) and open_browser:
            webbrowser.open(url)
        print(f"\nShadeShift is running. Dashboard: {url}   API: {settings.api_url}/docs")
        print("Press Ctrl+C in this window to stop everything (relays are opened first).\n")
        warned = set()
        while True:
            time.sleep(0.5)
            for name, p in procs.items():
                if p.poll() is not None and name not in warned:
                    warned.add(name)
                    if name == "gateway-esp32":
                        print("\n!! The ESP32 gateway stopped (see the message above). The demo device keeps running: "
                              "pick 'demo-01' on the dashboard, or fix the USB connection and run "
                              "'run.py gateway --source serial' in another window.\n")
                    elif name in ("server", "dashboard"):
                        raise RuntimeError(f"the {name} stopped unexpectedly")
    except KeyboardInterrupt:
        print("\nStopping ShadeShift ... (gateways open all relays first)")
    except RuntimeError as e:
        print(f"\nShadeShift cannot continue: {e}")
    finally:
        # 1) Gateways got the same Ctrl+C: they open the relays, flush their data to the still-running server, end the run.
        # 2) Then the dashboard and the server are asked to stop. 3) Anything still alive after 20 s is terminated.
        for group, ask in ((["gateway-esp32", "gateway-demo"], False), (["dashboard", "server"], True)):
            if ask:
                for name in group:
                    if procs.get(name) is not None and procs[name].poll() is None:
                        _soft_stop(procs[name])
            end = time.time() + 20
            for name in group:
                p = procs.get(name)
                while p is not None and p.poll() is None and time.time() < end:
                    try:
                        time.sleep(0.25)
                    except KeyboardInterrupt:
                        pass
                if p is not None and p.poll() is None:
                    print(f"  {name} did not stop in time; terminating it")
                    p.terminate()
        print("Stopped.")


def cmd_demo(settings, args):
    _start_all(settings, live=False, open_browser=not args.no_browser, scenario=args.scenario)


def cmd_live(settings, args):
    _start_all(settings, serial_port=args.port, live=True, open_browser=not args.no_browser)


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
    p = sub.add_parser("demo", help="server + emulated ESP32 + dashboard (no hardware)")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--scenario", nargs="?", const="default", default=None,
                   help="also start a demo scenario (default: 'default'; see scenarios/)")
    p = sub.add_parser("live", help="server + real ESP32 gateway + standby demo + dashboard")
    p.add_argument("--port", default=None, help="serial port, e.g. COM5 (default: auto-detect the ESP32)")
    p.add_argument("--no-browser", action="store_true")
    sub.add_parser("dashboard", help="run only the dashboard")
    p = sub.add_parser("server", help="run the local API server")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p = sub.add_parser("gateway", help="run the edge gateway (serial ESP32 or emulated demo device)")
    p.add_argument("--source", choices=["serial", "demo"], default=None)
    p.add_argument("--port", default=None, help="serial port, e.g. COM5 (default: auto-detect the ESP32)")
    p.add_argument("--device-id", default=None)
    p.add_argument("--runtime", choices=["auto", "onnx", "numpy"], default=None, help="edge AI runtime")
    p.add_argument("--standby", action="store_true", help="demo device waiting as a backup (used by run.py live)")
    p = sub.add_parser("import-lab", help="import lab curves into the database")
    p.add_argument("--include-anomalies", action="store_true", help="also import the V5 and V1d folders")
    sub.add_parser("check", help="check this laptop")
    sub.add_parser("ports", help="list serial ports")
    p = sub.add_parser("test", help="run the tests")
    p.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)          # status lines appear immediately, also when redirected
    if WINDOWS:
        # CTRL_BREAK (launcher shutdown) and closing the console window arrive as SIGBREAK: treat them like Ctrl+C,
        # so a gateway still opens the relays first.
        def _as_ctrl_c(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, _as_ctrl_c)
    settings = config.load()
    handler = {"demo": cmd_demo, "live": cmd_live, "dashboard": cmd_dashboard, "server": cmd_server,
               "gateway": cmd_gateway, "import-lab": cmd_import_lab, "check": cmd_check, "ports": cmd_ports,
               "test": cmd_test}[args.cmd]
    sys.exit(handler(settings, args) or 0)


if __name__ == "__main__":
    main()
