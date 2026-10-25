"""Edge gateway (docs/CONTRACT.md §1, §3, §7, §8). Start with:  python run.py gateway --source serial|demo

The gateway is the only program that opens the ESP32's COM port. It parses sweeps, measures switch and sweep times,
runs the topology selector at the edge (ONNX Runtime, numpy fallback), executes commands from the server, and
forwards everything to the server through an outbox. With --source demo it drives the emulated ESP32 instead, which
replays real lab curves; that data is labeled source=demo all the way to the dashboard.
"""
import logging
import random
import re
import threading
import time
import uuid
from datetime import datetime, timezone

from shadeshift import __version__, commands, config as cfg, evaluation, inti, koneksi, protocol
from shadeshift.edge.selector import Decision, EdgeSelector
from shadeshift.gateway import demo as demo_mode
from shadeshift.gateway.uplink import ServerLink, utc_now

log = logging.getLogger("shadeshift.gateway")

KNOWN_USB_IDS = {(0x10C4, 0xEA60): "Silicon Labs CP210x", (0x1A86, 0x7523): "WCH CH340",
                 (0x1A86, 0x55D4): "WCH CH9102", (0x0403, 0x6001): "FTDI FT232"}
FAILURE_HINTS = [
    ("GAGAL: Voc di luar", "check the light and the relay wiring; under a dim lamp lower VPANEL (e.g. VPANEL 17)"),
    ("GAGAL: arus tidak terdeteksi", "not enough light (5 mA threshold) or check fuse, R0, MOSFET and shunt"),
    ("GAGAL: pilih topologi dulu", "select a topology first"),
]
RE_INFO = re.compile(r"# INFO fw=(?P<fw>[\w.]+), id=(?P<id>\w+), n=(?P<n>\d+)(?:, w=(?P<w>[0-9a-f]{12}))?"
                     r"(?:, fitur=(?P<fitur>[\w,]+))?")      # w= from 3.0, fitur= from 3.1 (CONTRACT §3)
RE_I2C = re.compile(r"#\s+ditemukan 0x(?P<a>[0-9A-Fa-f]{2})")             # SCAN: one line per I2C device found
RE_DIAG = re.compile(r"# diagnosis=(?P<cls>\w+), yakin=(?P<conf>[0-9.]+), model=(?P<model>\S+), t_us=(?P<t_us>\d+)")


def firmware_label(fw):
    """'3.2.0' -> 'v3.2 (3.2.0)', '3.0.0' -> 'v3 (3.0.0)'."""
    major, _, rest = fw.partition(".")
    minor = rest.partition(".")[0]
    return f"v{major}{'.' + minor if minor not in ('', '0') else ''} ({fw})"


def find_esp32_port():
    """The single serial port with a known ESP32 USB bridge id, else a clear error listing what was found."""
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    matches = [p for p in ports if (p.vid, p.pid) in KNOWN_USB_IDS]
    if len(matches) == 1:
        return matches[0].device
    listing = "; ".join(f"{p.device} ({p.description})" for p in ports) or "none"
    if not matches:
        raise RuntimeError(f"no ESP32 USB-serial port found (ports: {listing}). Plug in the ESP32, install its "
                           "CP210x/CH340 driver, or pass --port COMx")
    raise RuntimeError(f"several ESP32-like ports found ({listing}); pass --port COMx")


def _iso_to_epoch(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


class Gateway:
    OBSERVING_TASKS = (None, "pemantauan", "ukur sekarang", "periksa panel", "diagnosis AI", "bandingkan rangkaian",
                       "terapkan rangkaian")   # never decide by themselves: a person approved the only switch
    def __init__(self, settings, source=None, port=None, device_id=None, lambat=None, standby=False, monitor_auto=False):
        self.s = settings
        self.source = source or settings.source
        if self.source not in ("serial", "demo"):
            raise ValueError("source must be serial or demo")
        self.serial = self.source == "serial"
        self.device_id = device_id or (settings.device_id if source in (None, settings.source)
                                       else cfg.DEFAULT_DEVICE_ID[self.source])
        self.kind = "esp32" if self.serial else "emulator"
        self.port = port if port not in (None, "", "auto") else (None if settings.serial_port == "auto" else settings.serial_port)
        self.lambat = lambat if lambat is not None else 1.0 / settings.demo_speed
        self.standby = standby
        self.run_uuid = str(uuid.uuid4())
        self.selector = EdgeSelector(role="gateway", runtime=settings.edge_runtime, model_path=settings.model_path)
        self.link = ServerLink(settings.api_url, settings.data_dir / f"outbox-{self.device_id}.db", settings.api_token)
        self.kon = None
        self.firmware = None if self.serial else "emulator (lab replay)"
        self.last_error = None
        self.auto_mode = {"on": False}
        self.monitor = {"on": False}               # monitoring mode (CONTRACT §19)
        self.monitor_auto = monitor_auto           # start monitoring by itself once connected (run.py; not the standby)
        self._monitor_wake = threading.Event()     # a person asked for a measurement now
        self._monitor_req = set()                  # {"panel"}: also check each panel now
        self.scenario = None                       # demo_mode.ScenarioPlayer while a demo scenario runs
        self._auto_stop = threading.Event()
        self._task_stop = threading.Event()
        self._decisions = {}                       # sweep uuid -> Decision made inside a selection flow
        self._crosscheck = {}                      # sweep uuid -> gateway Decision when the ESP32 decided (firmware v3)
        self.esp32 = None                          # INFO (firmware 3.x): {"fw", "id", "weights", "weights_match", "features"}
        self.i2c = None                            # SCAN: {"at", "found": ["0x48", ...]} for the Perangkat page
        self._monitor_apply = None                 # a wiring a person approved, applied by the monitoring loop
        self._scan = None                          # running full scan: {"uuid", "condition"}; its sweeps carry the scan
        self._buf_lock = threading.Lock()
        self._log, self._events, self._metrics = [], [], []
        self._stop = threading.Event()
        self._threads = []

    # ---------- connection ----------
    def connect(self):
        if self.serial:
            port = self.port or find_esp32_port()
            self.kon = koneksi.Koneksi(port, simpan=False, baud=self.s.serial_baud)
            self.port = port
            self.firmware = "v2"
        else:
            self.kon = koneksi.Koneksi("TIRUAN", simpan=False, tiruan_kondisi="V1c", lambat=self.lambat)
        self.kon.pengamat_baris.append(self._on_line)
        self.kon.pengamat_sapuan.append(self._on_sweep)
        self.kon.pengamat_pilih.append(self._on_selection)
        if self.serial:
            self.kon.kirim("INFO")                 # firmware 3.x answers with version, chip id, weights fingerprint, features
            self.kon.kirim("SCAN")                 # the I2C devices (ADS1115, MCP4725); reads only, no relay moves
        self.event("status", f"connected to {'serial ' + self.port if self.serial else 'emulated ESP32 (lab replay)'}")

    @property
    def transport(self):
        return f"serial:{self.port}" if self.serial else "emulator"

    @property
    def provenance(self):
        return "measured" if self.serial else "emulated"

    # ---------- buffers flushed to the outbox ----------
    def event(self, kind, message, data=None):
        with self._buf_lock:
            self._events.append({"device_id": self.device_id, "kind": kind, "message": message[:500],
                                 "data": data or {}, "created_at": utc_now()})

    def metric(self, name, value, unit, provenance, data=None):
        if value is None:
            return
        with self._buf_lock:
            self._metrics.append({"device_id": self.device_id, "name": name, "value": round(float(value), 3),
                                  "unit": unit, "provenance": provenance, "data": data or {}, "at": utc_now()})

    def _flush(self):
        with self._buf_lock:
            logs, events, metrics = self._log, self._events, self._metrics
            self._log, self._events, self._metrics = [], [], []
        for k in range(0, len(logs), 500):
            self.link.enqueue("log", {"device_id": self.device_id, "lines": logs[k:k + 500]})
        for k in range(0, len(events), 500):
            self.link.enqueue("events", {"items": events[k:k + 500]})
        for k in range(0, len(metrics), 500):
            self.link.enqueue("metrics", {"items": metrics[k:k + 500]})

    # ---------- observers (reader thread of koneksi) ----------
    def _on_line(self, t, direction, line):
        at = datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._buf_lock:
            self._log.append({"at": at, "dir": direction, "line": line[:500]})
        if direction == "rx" and (m := RE_INFO.match(line)):
            ours = self.selector.model_id.split("@")[1]
            features = m["fitur"].split(",") if m["fitur"] else []
            self.esp32 = {"fw": m["fw"], "id": m["id"], "weights": m["w"],
                          "weights_match": m["w"] == ours if m["w"] else None, "features": features}
            self.firmware = firmware_label(m["fw"])
            if m["w"] is None:
                self.event("status", f"ESP32 firmware {m['fw']}"
                                     + (f" (features: {', '.join(features)})" if features else "")
                                     + "; the selector runs on this laptop")
            elif m["w"] != ours:
                self.event("error", f"ESP32 selector weights w={m['w']} differ from the laptop model ({ours}). "
                                    "Reflash firmware/shadeshift_firmware with the current pemilih_bobot.h",
                           {"esp32_weights": m["w"], "laptop_weights": ours})
            else:
                self.event("status", f"ESP32 firmware {m['fw']} with the same selector weights ({ours}): on-board AI active")
        if direction == "rx" and line.startswith("# scan I2C"):
            self.i2c = {"at": at, "found": []}
        elif direction == "rx" and self.i2c is not None and (m := RE_I2C.match(line)):
            self.i2c["found"].append("0x" + m["a"].upper())
        if direction == "rx" and (m := RE_DIAG.match(line)):          # firmware 3.2 DIAG: diagnosis ON the ESP32
            data = {"class": m["cls"], "confidence": float(m["conf"]), "model_id": m["model"], "t_us": int(m["t_us"]),
                    "decided_by": "esp32"}
            self.event("info", f"ESP32 diagnosis: {m['cls']} (confidence {float(m['conf']):.2f}, model {m['model']})", data)
            self.metric("diagnosis_us", int(m["t_us"]), "us", "measured", {"runtime": "esp32", "model_id": m["model"]})
        if direction == "rx" and "GAGAL" in line:
            hint = next((h for key, h in FAILURE_HINTS if key in line), None)
            self.event("error", line.lstrip("# ").strip(), {"hint": hint} if hint else {})

    def _on_sweep(self, sp, lines):
        p = protocol.parse_block(lines)
        sweep_uuid = str(uuid.uuid4())
        sp.meta["uuid"] = sweep_uuid
        sp.meta["complete"] = p.complete
        sp.meta["device_decision"] = p.device_decision if self.serial else None   # never trusted from an emulator
        sweep_ms, switch_ms = sp.meta.get("sweep_ms"), sp.meta.get("switch_ms")
        body = {"uuid": sweep_uuid, "device_id": self.device_id, "run_uuid": self.run_uuid,
                "source": "device" if self.serial else "demo", "label": p.label, "topology": p.topology,
                "captured_at": datetime.fromtimestamp(sp.waktu, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "points": {"v": p.v, "i": p.i}, "header": p.header,
                "timing": {"sweep_ms": round(sweep_ms, 1) if sweep_ms else None, "switch_ms": round(switch_ms, 1) if switch_ms else None},
                "device_meta": p.device_meta, "complete": p.complete, "raw_text": "\n".join(lines)}
        # The ESP32's own AI result (firmware 3.x, '# pemilih=' after a 4S sweep) is stored as an observation whenever
        # no flow posts its own (applied) decision: idle, monitoring, a measurement on request, a panel check.
        observing = self.kon.kerja in self.OBSERVING_TASKS
        if self.serial and p.device_decision and observing:
            body["device_decision"] = p.device_decision
        if not self.serial:
            body["replay_of"] = p.replay_of
            cond, _, rep = protocol.condition_from_name((p.replay_of or "").removesuffix(".csv"))
            body["condition"], body["repeat"] = cond, rep
        scan = self._scan
        if scan and p.label.startswith(scan["condition"] + "_"):
            cond, _, rep = protocol.condition_from_name(p.label)
            body.update(scan_uuid=scan["uuid"], condition=cond, repeat=rep)
        self.link.enqueue("sweep", body)
        self.metric("sweep_ms", sweep_ms, "ms", self.provenance, {"topology": p.topology})
        self.metric("switch_ms", switch_ms, "ms", self.provenance, {"topology": p.topology})
        if p.topology == "4S" and p.complete and observing:              # the laptop's cross-check (or the demo's AI)
            d = self.selector.decide(p.v, p.i)
            if d:
                self._post_decision(d, sweep_uuid, "observe", applied=False)

    def _putuskan(self, sp):
        """Selector used inside koneksi.pilih_sekali (auto-select, auto mode)."""
        if not sp.meta.get("complete"):
            return {"pilihan": None, "galat": "4S sweep incomplete (rows missing); no decision from partial data"}
        d = self.selector.decide(sp.V, sp.I)
        if d is None:
            return None
        dd = sp.meta.get("device_decision")
        if dd and dd.get("scores"):
            # Firmware v3 decided on the ESP32 (TinyML): apply ITS decision; keep the laptop result as a cross-check.
            w = (self.esp32 or {}).get("weights")
            esp = Decision(choice=dd["choice"], scores=dd["scores"], features=d.features,
                           latency_us=dd.get("latency_us"), model_us=dd.get("latency_us"), decided_by="esp32",
                           model_id=f"pemilih-logreg-v1@{w}" if w else "pemilih.h@firmware")
            self._crosscheck[sp.meta["uuid"]] = d
            if esp.choice != d.choice:
                self.event("info", f"ESP32 chose {esp.choice}, laptop cross-check ({d.decided_by}) chose {d.choice}",
                           {"esp32": esp.choice, "laptop": d.choice})
            d = esp
        self._decisions[sp.meta["uuid"]] = d
        return {"pilihan": d.choice, "skor": d.scores, "decided_by": d.decided_by, "latency_us": d.latency_us}

    def _on_selection(self, hasil, s4, sk):
        if s4 is None or "uuid" not in s4.meta:
            self.event("error", f"selection failed: {hasil.get('galat')}")
            return
        d = self._decisions.pop(s4.meta["uuid"], None)
        if d is None:
            self.event("error", f"selection failed: {hasil.get('galat', 'no decision')}")
            return
        applied = not hasil.get("galat")
        self._post_decision(d, s4.meta["uuid"], hasil.get("pemicu", "auto_once"), applied=applied)
        cross = self._crosscheck.pop(s4.meta["uuid"], None)
        if cross is not None:
            self._post_decision(cross, s4.meta["uuid"], "observe", applied=False)
        sent = self.kon.terakhir_dikirim.get(d.choice) if d.choice != "4S" else None
        if applied and sent and sent >= s4.waktu:
            self.metric("e2e_decision_ms", (sent - s4.waktu) * 1000, "ms", "measured",
                        {"note": "end of 4S sweep to switch command sent (decision + overhead on this laptop)"})
        if applied:
            gain = (hasil.get("pmax_pilihan", 0) / hasil["pmax_4S"] - 1) * 100 if hasil.get("pmax_4S") else None
            self.event("switch", f"4S -> {d.choice} (selector, {d.decided_by})" if d.choice != "4S" else "selector kept 4S",
                       {"choice": d.choice, "gain_vs_4S_pct": round(gain, 2) if gain is not None else None,
                        "trigger": hasil.get("pemicu")})
        else:
            self.event("error", f"selection {d.choice} not applied: {hasil.get('galat')}")

    def _post_decision(self, d, sweep_uuid, trigger, applied):
        decision_uuid = str(uuid.uuid4())
        self.link.enqueue("decision", {
            "uuid": decision_uuid, "sweep_uuid": sweep_uuid, "device_id": self.device_id, "decided_by": d.decided_by,
            "model_id": d.model_id, "choice": d.choice, "scores": d.scores, "features": d.features,
            "latency_us": d.latency_us, "trigger": trigger, "applied": applied, "created_at": utc_now()})
        # Inference time is real compute time (laptop, or the ESP32 itself for firmware v3) even in demo mode: 'measured'.
        if d.latency_us is not None:
            where = "esp32" if d.decided_by == "esp32" else self.selector.runtime
            self.metric("decision_us", d.latency_us, "us", "measured", {"model_us": d.model_us, "runtime": where,
                                                                        "decided_by": d.decided_by})
        return decision_uuid

    # ---------- commands ----------
    def _execute(self, c):
        cid, kind, name, params = c["id"], c["kind"], c["command"], c.get("params") or {}
        try:
            if commands.is_stop(kind, name):
                return self._stop_now(cid)
            if kind == "raw":
                line = commands.validate_raw(name)                # checked again here, even if the server did
                if self.kon.kerja and commands.is_actuating("raw", line):
                    return self.link.command_result(cid, "failed", f"busy: {self.kon.kerja} (press Stop first)")
                self.kon.kirim(line)
                return self.link.command_result(cid, "done", "sent")
            if name == "demo_condition":
                return self._demo_condition(cid, params["condition"])
            if name == "demo_scenario_stop":
                return self._stop_now(cid)
            if name == "demo_scenario_start":
                return self._start_scenario(cid, params)
            if name == "diagnose" and (why := self.diagnosis_unavailable()):
                return self.link.command_result(cid, "failed", why)
            if name in ("panel_check", "measure_now", "diagnose", "compare_wirings", "apply_wiring") and self.monitor.get("on"):
                if name == "panel_check":
                    self._monitor_req.add("panel")
                if name == "diagnose":
                    self._monitor_req.add("diag")
                if name == "compare_wirings":
                    self._monitor_req.add("compare")
                if name == "apply_wiring":
                    self._monitor_apply = params["target"]
                self._monitor_wake.set()
                return self.link.command_result(cid, "done", "measuring now (monitoring)")
            if self.kon.kerja:
                return self.link.command_result(cid, "failed", f"busy: {self.kon.kerja}")
            if name == "measure_now":
                self._start_task("ukur sekarang", cid, self._measure_now_task)
            elif name == "auto_select":
                self._start_task("pilih otomatis", cid, lambda: self._result_of_selection(
                    self.kon.pilih_sekali(self.selector.W, putuskan=self._putuskan)))
            elif name == "auto_mode_start":
                self._start_auto_mode(cid, params)
            elif name == "cycle":
                self._start_task("siklus", cid, lambda: self._cycle(params))
            elif name == "audit_decision":
                self._start_task("audit keputusan", cid, self._audit)
            elif name == "full_scan":
                self._start_task("scan penuh", cid, lambda: self._full_scan(params))
            elif name == "monitor_start":
                self._start_monitor(cid, params)
            elif name == "panel_check":
                self._start_task("periksa panel", cid, self._panel_check_task)
            elif name == "diagnose":
                self._start_task("diagnosis AI", cid, self._diagnose_task)
            elif name == "compare_wirings":
                self._start_task("bandingkan rangkaian", cid, self._compare_task)
            elif name == "apply_wiring":
                self._start_task("terapkan rangkaian", cid, lambda: self._apply_wiring(params["target"]))
            else:
                self.link.command_result(cid, "failed", f"unknown action {name}")
        except Exception as e:
            log.exception("command %s failed", name)
            self.link.command_result(cid, "failed", f"{type(e).__name__}: {e}")

    def _stop_now(self, cid):
        """The one stop path (stop, auto_mode_stop, raw OFF/STOP): latch so no task writes again, send OFF, and report
        'done' only when the device confirms all relays open. The firmware finishes the step it is in first
        (a sweep can take ~3-4 s)."""
        if self.scenario is not None:
            self.scenario.stop()
        self._auto_stop.set()
        self._task_stop.set()
        self.auto_mode = {"on": False}
        self.monitor = {"on": False}
        confirmed = self.kon.hentikan(batas=10)
        if confirmed:
            self.event("command", "stop: tasks cancelled, device confirmed all relays open")
            return self.link.command_result(cid, "done", "all relays open")
        self.event("error", "stop: OFF sent but the device did not confirm within 10 s",
                   {"hint": "check the USB cable; to cut power without software, unplug the 12 V adaptor"})
        return self.link.command_result(cid, "failed", "OFF not confirmed by device")

    def _start_task(self, nama, cid, fn):
        self._task_stop.clear()

        def run():
            try:
                status, result = fn()
            except koneksi.Dibatalkan:
                status, result = "failed", "stopped"
            except Exception as e:
                status, result = "failed", f"{type(e).__name__}: {e}"
            self.link.command_result(cid, status, result)
        if not self.kon.mulai_tugas(nama, run):
            self.link.command_result(cid, "failed", f"busy: {self.kon.kerja}")

    @staticmethod
    def _result_of_selection(hasil):
        return ("failed", hasil["galat"]) if hasil.get("galat") else ("done", hasil.get("pilihan"))

    def _start_auto_mode(self, cid, params):
        defaults = (self.link.get("/settings") or {}).get("auto_mode_defaults") or {}
        conf = {**{"interval_s": 10, "trigger_pct": 20, "hold_s": 30}, **defaults, **params}
        self._auto_stop = threading.Event()
        ev = self._auto_stop
        self.auto_mode = {"on": True, **conf}
        self.event("command", "auto mode started", conf)

        def run():
            try:
                st = dict(conf.get("stability") or {})
                if st.get("enabled") and not st.get("window_s"):
                    st["window_s"] = 3 * conf["interval_s"] + 1         # the last 3 monitor sweeps (CONTRACT §17)
                self.kon.mode_otomatis(self.selector.W, ev, conf["interval_s"], conf["trigger_pct"] / 100,
                                       conf["hold_s"], putuskan=self._putuskan, stabil=st if st.get("enabled") else None,
                                       saat_kunci=self._stability_lock)
            finally:
                self.auto_mode = {"on": False}
                self.event("command", "auto mode stopped")
        if self.kon.mulai_tugas("mode otomatis", run):
            self.link.command_result(cid, "done", "auto mode started")
        else:
            self.auto_mode = {"on": False}
            self.link.command_result(cid, "failed", f"busy: {self.kon.kerja}")

    def _start_monitor(self, cid, params):
        """Monitoring (CONTRACT §19): measure, never decide or reconfigure. Every array_interval_s one sweep of the
        wiring (the active one, or 4S when all relays are open); every panel_interval_s each panel alone (A-D), then back
        to that wiring. Stop ends it between steps."""
        conf = {"array_interval_s": 300, "panel_interval_s": 1800, **{k: v for k, v in params.items() if v is not None}}
        wiring = conf.get("wiring") or (self.kon.topo if self.kon.topo in protocol.TOPOLOGIES else "4S")
        panels = bool(conf["panel_interval_s"]) and self.panels_available()
        self._auto_stop = threading.Event()
        self._task_stop.clear()
        ev = self._auto_stop
        self.monitor = {"on": True, **conf, "wiring": wiring, "panels": panels}
        self.event("command", f"monitoring started: {wiring} every {conf['array_interval_s']:g} s"
                              + (f", panel check every {conf['panel_interval_s']:g} s" if panels else ", no panel checks"), conf)

        def run():
            nonlocal wiring
            last_panel = None
            self._monitor_wake.clear()
            try:
                while not ev.is_set() and not self._task_stop.is_set():
                    t0 = time.monotonic()
                    stamp = time.strftime("%H%M%S")
                    asked, self._monitor_req = self._monitor_req, set()
                    if panels and (last_panel is None or t0 - last_panel >= conf["panel_interval_s"] or "panel" in asked):
                        if self._panel_check(f"pantau_{stamp}", ev) is None:
                            return
                        last_panel = t0
                        self.monitor = {**self.monitor, "last_panel_check": utc_now()}
                    if "diag" in asked:
                        self._diagnose()
                    if "compare" in asked:
                        self._compare_wirings()
                    target, self._monitor_apply = self._monitor_apply, None
                    if target and self._apply_wiring(target)[0] == "done":
                        wiring = target                            # monitoring follows the wiring the person chose
                        self.monitor = {**self.monitor, "wiring": wiring}
                    if self.kon.topo != wiring and not self.kon.pindah(wiring):
                        self.event("error", f"monitoring: switch back to {wiring} failed")
                    elif self.kon.sapu(f"pantau_{stamp}_{wiring}") is None:
                        self.event("error", f"monitoring: {wiring} sweep failed")
                    self.monitor = {**self.monitor, "last_sweep": utc_now()}
                    end = t0 + conf["array_interval_s"]
                    while time.monotonic() < end:                  # wait for the next sweep, or a person asking now
                        if ev.wait(0.5):
                            return
                        if self._monitor_wake.is_set():
                            self._monitor_wake.clear()
                            break
            except koneksi.Dibatalkan:
                pass
            finally:
                self.monitor = {"on": False}
                self.event("command", "monitoring stopped")
        if self.kon.mulai_tugas("pemantauan", run):
            if cid is not None:
                self.link.command_result(cid, "done", "monitoring started")
        else:
            self.monitor = {"on": False}
            if cid is not None:
                self.link.command_result(cid, "failed", f"busy: {self.kon.kerja}")

    def _auto_monitor(self):
        """Monitoring is always on for the consumer view: start it once the device answers (not again after a stop,
        which is the safety action before touching the wiring)."""
        if self._stop.wait(3.0) or self.kon is None:
            return
        if not self.kon.kerja and not self.monitor.get("on"):
            log.info("monitoring starts by itself (SHADESHIFT_MONITOR_AUTO)")
            self._start_monitor(None, {})

    def _panel_check(self, prefix, ev=None):
        """Each panel alone (A-D), one sweep each; returns how many succeeded, or None when stopped. Leaves the relays on
        the last panel: the caller switches back to its wiring."""
        ok = 0
        for p in protocol.PANELS:
            if (ev is not None and ev.is_set()) or self._task_stop.is_set():
                return None
            # 60 s: the emulator's first panel loads the lab twin (~13 s); the board itself answers in under a second
            if self.kon.pindah(p, batas=60) and self.kon.sapu(f"{prefix}_{p}") is not None:
                ok += 1
            else:
                self.event("error", f"panel {p} check failed")
        return ok

    def diagnosis_unavailable(self):
        """Why the diagnosis AI cannot run on this device, or None (CONTRACT §23). It runs ON the ESP32 only: the
        emulator never pretends to, and a firmware that reports its features without 'diag' has no model on board."""
        if not self.serial:
            return "the emulated ESP32 (demo mode) does not run the diagnosis AI"
        features = (self.esp32 or {}).get("features")
        if features and "diag" not in features:
            return "no diagnosis model on the ESP32 (firmware built without diagnosis_model.h)"
        return None

    def _diagnose(self):
        """DIAG on the board: it sweeps 4S, 2S2P, TCT and 4P through its safe sequence, runs the model on the 59 numbers,
        prints '# diagnosis=...' (stored by _on_line) and opens all relays. Returns (status, result)."""
        if why := self.diagnosis_unavailable():
            return "failed", why
        s = self.kon._tunggu(lambda s: s.startswith(("# diagnosis=", "# DIAG GAGAL", "# DIAG dihentikan")), 120, kirim="DIAG")
        if s is None:
            self.event("error", "DIAG: no answer from the ESP32 within 120 s")
            return "failed", "no answer within 120 s"
        if s.startswith("# diagnosis="):
            return "done", s.lstrip("# ")
        return "failed", s.lstrip("# ")

    def _diagnose_task(self):
        """Diagnosis with AI started by a person, then back to the wiring that was active (the board opens all relays)."""
        back = self.kon.topo if self.kon.topo in protocol.TOPOLOGIES else None
        status, result = self._diagnose()
        if back and self.kon.topo != back and not self.kon.pindah(back):
            return "failed", f"{result}; switching back to {back} failed"
        return status, result

    COMPARED = ("4S", "2S2P", "TCT", "4P")

    def _compare_wirings(self):
        """Measure every wiring once (labels 'banding_<time>_<wiring>'), then back to the wiring that was active: the
        relays move only to measure. 4P is measured for information (below the 24 V window, never applied)."""
        back = self.kon.topo if self.kon.topo in protocol.TOPOLOGIES else None
        stamp, ok = time.strftime("%H%M%S"), 0
        for t in self.COMPARED:
            if self._task_stop.is_set():
                return "failed", "stopped"
            if self.kon.pindah(t) and self.kon.sapu(f"banding_{stamp}_{t}") is not None:
                ok += 1
            else:
                self.event("error", f"compare: {t} sweep failed")
        if back and self.kon.topo != back and not self.kon.pindah(back):
            return "failed", f"{ok} of {len(self.COMPARED)} wirings measured; switching back to {back} failed"
        if not back:
            self.kon.buka_semua()
        self.event("info", f"wirings compared: {ok} of {len(self.COMPARED)} measured")
        return ("done" if ok == len(self.COMPARED) else "failed"), f"{ok} of {len(self.COMPARED)} wirings measured"

    def _compare_task(self):
        return self._compare_wirings()

    def _apply_wiring(self, target):
        """A wiring a person approved on the page (CONTRACT §29): the firmware's safe order (current off, R0 open, all
        relays open, the new ones closed, open-circuit voltage checked; on a failed check every relay opens), then one
        sweep to measure the result."""
        before = self.kon.topo
        if not self.kon.pindah(target):
            self.event("error", f"wiring change to {target} failed; relays opened for safety", {"from": before, "to": target})
            return "failed", f"switch to {target} failed"
        self.event("switch", f"wiring {before or 'open'} -> {target} (approved by the user)",
                   {"from": before, "to": target, "approved": True})
        sp = self.kon.sapu(f"terapkan_{time.strftime('%H%M%S')}_{target}")
        return ("done", f"wiring {target}, measured") if sp else ("done", f"wiring {target}; the check sweep failed")

    def _measure_now_task(self):
        """One sweep of the active wiring (4S when all relays are open), started by a person."""
        t = self.kon.topo if self.kon.topo in protocol.TOPOLOGIES else "4S"
        if self.kon.topo != t and not self.kon.pindah(t):
            return "failed", f"switch to {t} failed"
        return ("done", f"{t} measured") if self.kon.sapu(f"ukur_{time.strftime('%H%M%S')}_{t}") else ("failed", "sweep failed")

    def _panel_check_task(self):
        """One-off panel check started by a person (CONTRACT §19): A-D, then back to the wiring that was active."""
        if not self.panels_available():
            return "failed", "this firmware has no single-panel sweeps (needs firmware 3.2)"
        back = self.kon.topo if self.kon.topo in protocol.TOPOLOGIES else None
        ok = self._panel_check(f"periksa_{time.strftime('%H%M%S')}")
        if ok is None:
            return "failed", "stopped"
        if back and not self.kon.pindah(back):
            return "failed", f"{ok} of 4 panels checked; switching back to {back} failed"
        if not back:
            self.kon.buka_semua()
        return ("done" if ok == 4 else "failed"), f"{ok} of 4 panels checked" + (f", back on {back}" if back else "")

    def _cycle(self, params):
        """Gateway-run replacement for firmware SIKLUS: one step at a time, so 'stop' works between steps."""
        done = 0
        for rep in range(1, params["repeats"] + 1):
            order = list(params["topologies"])
            random.shuffle(order)
            for t in order:
                if self._task_stop.is_set():
                    return "failed", f"stopped after {done} sweeps"
                if not self.kon.pindah(t):
                    return "failed", f"switch to {t} failed after {done} sweeps"
                if self.kon.sapu(f"{params['label']}_{t}_u{rep}") is None:
                    return "failed", f"sweep {t} failed after {done} sweeps"
                done += 1
        self.kon.hentikan(batas=10)                # leave the array off after the cycle
        return "done", f"{done} sweeps"

    def _audit(self):
        """Live decision audit (CONTRACT §13): 4S sweep -> the AI decides (on the ESP32 with firmware v3) -> sweep the
        other two candidates and, when available, the four single panels (ideal-MLPE reference) -> switch to the AI's
        choice. The measured loss of the decision is stored as an evaluation."""
        self._audit_n = getattr(self, "_audit_n", 0) + 1
        tag = f"audit{int(time.time()) % 100000}_{self._audit_n}"
        if not self.kon.pindah("4S"):
            return "failed", "switch to 4S failed"
        s4 = self.kon.sapu(f"{tag}_4S")
        if s4 is None:
            return "failed", "4S sweep failed"
        res = self._putuskan(s4)
        d = self._decisions.pop(s4.meta["uuid"], None)
        if not res or d is None:
            return "failed", (res or {}).get("galat") or "no decision on the 4S sweep"
        cross = self._crosscheck.pop(s4.meta["uuid"], None)
        others = ["2S2P", "TCT", "4P"] + (list(protocol.PANELS) if self.panels_measured() else [])    # 4P: diagnosis input
        sweeps = {"4S": s4}
        for t in random.sample(others, len(others)):
            if self._task_stop.is_set():
                return "failed", "stopped"
            if not self.kon.pindah(t):
                return "failed", f"switch to {t} failed"
            sp = self.kon.sapu(f"{tag}_{t}")
            if sp is None:
                return "failed", f"sweep {t} failed"
            sweeps[t] = sp
        applied = self.kon.pindah(d.choice)
        decision_uuid = self._post_decision(d, s4.meta["uuid"], "manual", applied=applied)
        if cross is not None:
            self._post_decision(cross, s4.meta["uuid"], "observe", applied=False)
        if not all(sp.meta.get("complete") for sp in sweeps.values()):
            return "failed", "an audit sweep was incomplete; no evaluation stored"
        pmax = {t: float(sp.pmax) for t, sp in sweeps.items()}
        best = max(evaluation.CANDIDATES, key=lambda t: pmax[t])
        loss = (pmax[best] - pmax[d.choice]) / pmax[best] * 100
        panels = {p: pmax[p] for p in protocol.PANELS if p in pmax}
        mlpe = sum(panels.values()) if len(panels) == 4 else None
        self.link.enqueue("evaluations", {"items": [{
            "decision_uuid": decision_uuid, "device_id": self.device_id,
            "pmax": {t: pmax[t] for t in evaluation.CANDIDATES}, "pmax_4p": pmax.get("4P"), "pmax_panels": panels,
            "mlpe_w": mlpe,
            "sweep_uuids": [sp.meta["uuid"] for sp in sweeps.values()], "best": best, "chosen": d.choice,
            "loss_pct": round(loss, 4), "source": "device" if self.serial else "demo", "created_at": utc_now()}]})
        text = (f"audit: AI ({d.decided_by}) chose {d.choice}, measured best {best}, loss {loss:.2f} % of the best"
                + (f", {(pmax[best] - pmax[d.choice]) / mlpe * 100:.2f} points of MLPE ({mlpe:.3f} W)" if mlpe else ""))
        self.event("info", text, {"choice": d.choice, "best": best, "loss_pct": round(loss, 3)})
        if not applied:
            return "failed", text + f"; switching to {d.choice} failed"
        return "done", text

    def _stability_lock(self, locked, why):
        """Auto mode with the stability rule (not validated) locked or released TCT."""
        self.auto_mode = {**self.auto_mode, "stability_locked": locked}
        self.event("switch" if locked else "info",
                   f"stability rule: {'TCT locked' if locked else 'lock released'} ({why})",
                   {"trigger": "stability_lock", "locked": locked, "note": "rule not validated yet (CONTRACT §17)"})

    def panels_measured(self):
        """Single panels that are MEASURED (firmware 3.2). Evidence (audits, full scans, the MLPE reference) uses only
        these: the emulator's twin panels never enter an evaluation or a training session."""
        return self.serial and "panel" in ((self.esp32 or {}).get("features") or [])

    def panels_available(self):
        """Single-panel sweeps need firmware 3.2 (INFO fitur=panel). The emulator answers them from the lab twin (its
        lab recordings have no single panels); those sweeps say so in a '# tiruan model=kembaran' line."""
        if not self.serial:
            return True
        return "panel" in ((self.esp32 or {}).get("features") or [])

    def _full_scan(self, params):
        """Labeled data collection (CONTRACT §12). Each round sweeps the 4 topologies and, when available, the 4 single
        panels, in random order, named <condition>_<target>_u<n>. Between rounds all relays open for the pause
        (panel temperatures, MOSFET cooling). Stop ends it between steps; the firmware finishes the step it is in."""
        targets, note = list(protocol.TOPOLOGIES), ""
        if params["panels"]:
            if self.panels_measured():
                targets += list(protocol.PANELS)
            else:
                note = "; panels skipped: " + ("the emulator has no single-panel recordings" if not self.serial
                                               else "this firmware has no single-panel sweeps (needs firmware 3.2)")
        cond, done = params["condition"], 0
        self._scan = {"uuid": params["scan_uuid"], "condition": cond}
        try:
            for k in range(params["rounds"]):
                rep = params["repeat_start"] + k
                for t in random.sample(targets, len(targets)):
                    if self._task_stop.is_set():
                        return "failed", f"stopped after {done} sweeps{note}"
                    if not self.kon.pindah(t):
                        return "failed", f"switch to {t} failed after {done} sweeps{note}"
                    if self.kon.sapu(f"{cond}_{t}_u{rep}") is None:
                        return "failed", f"sweep {t} u{rep} failed after {done} sweeps{note}"
                    done += 1
                if k < params["rounds"] - 1 and params["pause_s"] > 0:
                    self.kon.buka_semua()
                    self.event("info", f"full scan {cond}: round u{rep} done, pause {params['pause_s']:g} s "
                                       "(record the panel temperatures)", {"scan_uuid": params["scan_uuid"], "repeat": rep})
                    if self._task_stop.wait(params["pause_s"]):
                        return "failed", f"stopped after {done} sweeps{note}"
        finally:
            self._scan = None
        self.kon.hentikan(batas=10)                # leave the array off after the scan
        return "done", f"{done} sweeps{note}"

    def _start_scenario(self, cid, params):
        if self.serial:
            return self.link.command_result(cid, "failed", "demo scenarios only run on an emulated device")
        if self.kon.kerja or (self.scenario and self.scenario.thread and self.scenario.thread.is_alive()):
            return self.link.command_result(cid, "failed", f"busy: {self.kon.kerja or 'scenario'} (press Stop first)")
        try:
            sc = demo_mode.load(params["name"], self.kon.ser.semua)
        except demo_mode.ScenarioError as e:
            return self.link.command_result(cid, "failed", str(e))
        self.kon.lanjutkan()                       # a new task chosen by the user releases the stop latch
        self.scenario = demo_mode.ScenarioPlayer(self, sc, params.get("speed"))
        self.scenario.start()
        return self.link.command_result(cid, "done", f"started {sc['name']} at {self.scenario.speed:g}x")

    def _demo_condition(self, cid, condition):
        if self.serial:
            return self.link.command_result(cid, "failed", "demo_condition only applies to an emulated device")
        if condition not in self.kon.ser.semua:
            return self.link.command_result(cid, "failed", f"unknown condition {condition}")
        self.kon.ser.kondisi = condition
        self.event("info", f"emulated condition -> {condition} (replayed lab curves)")
        self.link.command_result(cid, "done", condition)

    # ---------- loops ----------
    def heartbeat_payload(self, ending=False):
        connected = bool(self.kon and self.kon.hidup) and not ending
        demo = None
        if self.kon is not None and not self.serial:
            demo = {"condition": self.kon.ser.kondisi, "repeat": self.kon.ser.ulangan,
                    "available_conditions": sorted(self.kon.ser.semua),
                    "scenario": self.scenario.state() if self.scenario else None,
                    "scenarios": demo_mode.available(), "standby": self.standby}
        return {"device_id": self.device_id, "kind": self.kind, "transport": self.transport, "firmware": self.firmware,
                "run_uuid": self.run_uuid,
                "gateway": {"version": __version__, **self.selector.info(), "esp32": self.esp32, "i2c": self.i2c},
                "state": {"connected": connected, "ending": ending,
                          "active_topology": self.kon.topo if self.kon else None,
                          "task": self.kon.kerja if self.kon else None, "auto_mode": self.auto_mode, "monitor": self.monitor,
                          "demo": demo,
                          "last_error": self.last_error or (self.kon.galat if self.kon else None),
                          "outbox_pending": self.link.pending(), "uplink_error": self.link.last_error}}

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            server_time = self.link.heartbeat(self.heartbeat_payload())
            if server_time and (t := _iso_to_epoch(server_time)) and abs(t - time.time()) > 2:
                log.warning("clock offset vs server: %.1f s", t - time.time())
            if self.kon is not None and not self.kon.hidup and self.serial:
                self._reconnect()
            self._stop.wait(2.0)

    def _reconnect(self):
        self.last_error = f"serial connection lost: {self.kon.galat}"
        self.event("error", self.last_error)
        try:
            self.connect()
            self.last_error = None
            self.event("status", "serial reconnected")
        except Exception as e:
            self.last_error = f"reconnect failed: {e}"

    def _commands_loop(self):
        while not self._stop.is_set():
            for c in self.link.next_commands(self.device_id, wait=5):
                self._execute(c)

    def _flush_loop(self):
        while not self._stop.wait(1.0):
            self._flush()
        self._flush()

    def start(self):
        """Connect and start the background threads (used by run() and by tests)."""
        self.connect()
        self.link.heartbeat(self.heartbeat_payload())
        self.link.start()
        for target in (self._heartbeat_loop, self._commands_loop, self._flush_loop):
            t = threading.Thread(target=target, name=target.__name__, daemon=True)
            t.start()
            self._threads.append(t)
        log.info("gateway %s (%s) running; edge AI: %s", self.device_id, self.transport, self.selector.runtime_label)
        if self.monitor_auto:
            threading.Thread(target=self._auto_monitor, name="auto-monitor", daemon=True).start()

    def stop(self):
        if self.scenario is not None:
            self.scenario.stop()
        self._auto_stop.set()
        self._task_stop.set()
        if self.kon is not None and self.kon.hidup:
            self.kon.hentikan(batas=3)             # leave the array safe (all relays open) when the gateway stops
        self._stop.set()
        for t in self._threads:
            t.join(timeout=12)
        self._flush()
        self.link.heartbeat(self.heartbeat_payload(ending=True))
        self.link.stop()
        if self.kon is not None:
            self.kon.tutup()

    def run(self):
        self.start()
        try:
            while not self._stop.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def main(settings=None, source=None, port=None, device_id=None, standby=False):
    settings = settings or cfg.load()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        Gateway(settings, source=source, port=port, device_id=device_id, standby=standby,
                monitor_auto=settings.monitor_auto and not standby).run()
    except (RuntimeError, OSError) as e:          # no ESP32 found, port busy or denied
        log.error("gateway cannot start: %s", e)
        raise SystemExit(2) from None
