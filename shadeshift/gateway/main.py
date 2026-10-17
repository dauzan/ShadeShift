"""Edge gateway (CONTRACT.md §1, §3, §7, §8). Start with:  python run.py gateway --source serial|demo

The gateway is the only program that opens the ESP32's COM port. It parses sweeps, measures switch and sweep times,
runs the topology selector at the edge (ONNX Runtime, numpy fallback), executes commands from the server, and
forwards everything to the server through an outbox. With --source demo it drives the emulated ESP32 instead, which
replays real lab curves; that data is labeled source=demo all the way to the dashboard.
"""
import logging
import random
import threading
import time
import uuid
from datetime import datetime, timezone

from shadeshift import __version__, commands, config as cfg, inti, koneksi, protocol
from shadeshift.edge.selector import EdgeSelector
from shadeshift.gateway.uplink import ServerLink, utc_now

log = logging.getLogger("shadeshift.gateway")

KNOWN_USB_IDS = {(0x10C4, 0xEA60): "Silicon Labs CP210x", (0x1A86, 0x7523): "WCH CH340",
                 (0x1A86, 0x55D4): "WCH CH9102", (0x0403, 0x6001): "FTDI FT232"}
FAILURE_HINTS = [
    ("GAGAL: Voc di luar", "check the light and the relay wiring; under a dim lamp lower VPANEL (e.g. VPANEL 17)"),
    ("GAGAL: arus tidak terdeteksi", "not enough light (5 mA threshold) or check fuse, R0, MOSFET and shunt"),
    ("GAGAL: pilih topologi dulu", "select a topology first"),
]


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
    def __init__(self, settings, source=None, port=None, device_id=None, lambat=None, standby=False):
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
        self._auto_stop = threading.Event()
        self._task_stop = threading.Event()
        self._decisions = {}                       # sweep uuid -> Decision made inside a selection flow
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
        if direction == "rx" and "GAGAL" in line:
            hint = next((h for key, h in FAILURE_HINTS if key in line), None)
            self.event("error", line.lstrip("# ").strip(), {"hint": hint} if hint else {})

    def _on_sweep(self, sp, lines):
        p = protocol.parse_block(lines)
        sweep_uuid = str(uuid.uuid4())
        sp.meta["uuid"] = sweep_uuid
        sp.meta["complete"] = p.complete
        sweep_ms, switch_ms = sp.meta.get("sweep_ms"), sp.meta.get("switch_ms")
        body = {"uuid": sweep_uuid, "device_id": self.device_id, "run_uuid": self.run_uuid,
                "source": "device" if self.serial else "demo", "label": p.label, "topology": p.topology,
                "captured_at": datetime.fromtimestamp(sp.waktu, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "points": {"v": p.v, "i": p.i}, "header": p.header,
                "timing": {"sweep_ms": round(sweep_ms, 1) if sweep_ms else None, "switch_ms": round(switch_ms, 1) if switch_ms else None},
                "device_meta": p.device_meta, "complete": p.complete, "raw_text": "\n".join(lines)}
        if self.serial and p.device_decision:
            body["device_decision"] = p.device_decision
        if not self.serial:
            body["replay_of"] = p.replay_of
            cond, _, rep = protocol.condition_from_name((p.replay_of or "").removesuffix(".csv"))
            body["condition"], body["repeat"] = cond, rep
        self.link.enqueue("sweep", body)
        self.metric("sweep_ms", sweep_ms, "ms", self.provenance, {"topology": p.topology})
        self.metric("switch_ms", switch_ms, "ms", self.provenance, {"topology": p.topology})
        if p.topology == "4S" and p.complete and not self.kon.kerja:      # flows post their own decision
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
        self.link.enqueue("decision", {
            "uuid": str(uuid.uuid4()), "sweep_uuid": sweep_uuid, "device_id": self.device_id, "decided_by": d.decided_by,
            "model_id": d.model_id, "choice": d.choice, "scores": d.scores, "features": d.features,
            "latency_us": d.latency_us, "trigger": trigger, "applied": applied, "created_at": utc_now()})
        # Inference time is real compute time on this laptop even in demo mode, so it is 'measured'.
        self.metric("decision_us", d.latency_us, "us", "measured", {"model_us": d.model_us, "runtime": self.selector.runtime})

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
            if name in ("demo_scenario_start", "demo_scenario_stop", "audit_decision"):
                return self.link.command_result(cid, "failed", f"{name} is not available yet in this build")
            if self.kon.kerja:
                return self.link.command_result(cid, "failed", f"busy: {self.kon.kerja}")
            if name == "auto_select":
                self._start_task("pilih otomatis", cid, lambda: self._result_of_selection(
                    self.kon.pilih_sekali(self.selector.W, putuskan=self._putuskan)))
            elif name == "auto_mode_start":
                self._start_auto_mode(cid, params)
            elif name == "cycle":
                self._start_task("siklus", cid, lambda: self._cycle(params))
            else:
                self.link.command_result(cid, "failed", f"unknown action {name}")
        except Exception as e:
            log.exception("command %s failed", name)
            self.link.command_result(cid, "failed", f"{type(e).__name__}: {e}")

    def _stop_now(self, cid):
        """The one stop path (stop, auto_mode_stop, raw OFF/STOP): latch so no task writes again, send OFF, and report
        'done' only when the device confirms all relays open. The firmware finishes the step it is in first
        (a sweep can take ~3-4 s)."""
        self._auto_stop.set()
        self._task_stop.set()
        self.auto_mode = {"on": False}
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
                self.kon.mode_otomatis(self.selector.W, ev, conf["interval_s"], conf["trigger_pct"] / 100,
                                       conf["hold_s"], putuskan=self._putuskan)
            finally:
                self.auto_mode = {"on": False}
                self.event("command", "auto mode stopped")
        if self.kon.mulai_tugas("mode otomatis", run):
            self.link.command_result(cid, "done", "auto mode started")
        else:
            self.auto_mode = {"on": False}
            self.link.command_result(cid, "failed", f"busy: {self.kon.kerja}")

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
            demo = {"condition": self.kon.ser.kondisi, "available_conditions": sorted(self.kon.ser.semua),
                    "scenario": None, "standby": self.standby}
        return {"device_id": self.device_id, "kind": self.kind, "transport": self.transport, "firmware": self.firmware,
                "run_uuid": self.run_uuid,
                "gateway": {"version": __version__, **self.selector.info()},
                "state": {"connected": connected, "ending": ending,
                          "active_topology": self.kon.topo if self.kon else None,
                          "task": self.kon.kerja if self.kon else None, "auto_mode": self.auto_mode, "demo": demo,
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

    def stop(self):
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
    Gateway(settings, source=source, port=port, device_id=device_id, standby=standby).run()
