"""Demo mode (docs/CONTRACT.md §6.4, §8): play a shading scenario on the emulated ESP32.

A scenario is a timeline of lab conditions. The player changes the emulated condition at each step and runs the normal
auto mode (trigger + hold rule), so the edge AI reacts to the new shading exactly as it would with the real device.
All data are REAL lab curves replayed (labeled source=demo); the emulated switch and sweep times are estimates.
speed > 1 makes everything faster: timeline, emulated delays, and the auto-mode interval and hold times.
"""
import json
import logging
import re
import threading
import time

from shadeshift import commands, config as cfg

log = logging.getLogger("shadeshift.gateway.demo")
FOLDER = cfg.ROOT / "scenarios"
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


class ScenarioError(ValueError):
    pass


def available():
    return sorted(p.stem for p in FOLDER.glob("*.json")) if FOLDER.is_dir() else []


def load(name, conditions, folder=None):
    """Read and validate scenarios/<name>.json against the lab conditions the emulator has."""
    if not NAME_RE.match(name or ""):
        raise ScenarioError("scenario name must be letters, digits, '_' or '-'")
    path = (folder or FOLDER) / f"{name}.json"
    if not path.is_file():
        raise ScenarioError(f"scenario {name!r} not found; available: {', '.join(available()) or 'none'}")
    try:
        sc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ScenarioError(f"{path.name}: invalid JSON ({e})") from None
    timeline = sc.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        raise ScenarioError(f"{path.name}: timeline must be a non-empty list")
    last = -1
    for k, step in enumerate(timeline):
        at, cond, rep = step.get("at_s"), step.get("condition"), step.get("repeat")
        if not isinstance(at, (int, float)) or at < 0 or at <= last:
            raise ScenarioError(f"{path.name}: step {k + 1}: at_s must increase (got {at})")
        if cond not in conditions:
            raise ScenarioError(f"{path.name}: step {k + 1}: unknown lab condition {cond!r}")
        if rep is not None and rep not in conditions[cond]:
            raise ScenarioError(f"{path.name}: step {k + 1}: {cond} has no repeat {rep}")
        last = at
    duration = sc.get("duration_s", last + 45)
    if duration <= last:
        raise ScenarioError(f"{path.name}: duration_s must be after the last step")
    try:
        auto = commands.validate_action("auto_mode_start", sc.get("auto_mode") or {})
    except commands.CommandError as e:
        raise ScenarioError(f"{path.name}: auto_mode: {e}") from None
    speed = sc.get("speed", 1.0)
    if not isinstance(speed, (int, float)) or not 0.1 <= speed <= 50:
        raise ScenarioError(f"{path.name}: speed must be between 0.1 and 50")
    return {"name": name, "description": sc.get("description", ""), "label": sc.get("label", ""),
            "timeline": timeline, "duration_s": float(duration), "loop": bool(sc.get("loop", False)),
            "speed": float(speed), "seed": sc.get("seed"),
            "auto_mode": {"interval_s": 10.0, "trigger_pct": 20.0, "hold_s": 30.0, **auto}}


class ScenarioPlayer:
    """Runs one scenario on a demo Gateway; stop() (or the gateway's Stop) ends it."""

    def __init__(self, gateway, scenario, speed=None):
        self.gw, self.sc = gateway, scenario
        self.speed = float(speed or scenario["speed"])
        self.stop_event = threading.Event()
        self.step = 0
        self.t0 = None
        self.thread = None

    def state(self):
        if self.thread is None or not self.thread.is_alive():
            return None
        st = self.sc["timeline"][self.step]
        return {"name": self.sc["name"], "step": self.step + 1, "steps": len(self.sc["timeline"]),
                "note": st.get("note", ""), "condition": st["condition"], "speed": self.speed,
                "t_s": round((time.monotonic() - self.t0) * self.speed, 1) if self.t0 else 0.0}

    def start(self):
        self.thread = threading.Thread(target=self._run, name="demo-scenario", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _apply(self, k):
        step = self.sc["timeline"][k]
        ser = self.gw.kon.ser
        ser.kondisi = step["condition"]
        if step.get("repeat") is not None:
            ser.ulangan = step["repeat"]
        self.step = k
        rep = f" u{step['repeat']}" if step.get("repeat") is not None else ""
        self.gw.event("info", f"DEMO step {k + 1}/{len(self.sc['timeline'])}: {step['condition']}{rep}"
                              + (f" ({step['note']})" if step.get("note") else "") + " - replayed lab curves",
                      {"scenario": self.sc["name"], "condition": step["condition"], "repeat": step.get("repeat")})

    def _run(self):
        kon, sc, speed = self.gw.kon, self.sc, self.speed
        old_lambat = kon.ser.lambat
        kon.ser.lambat = 1.0 / speed
        if sc["seed"] is not None:
            kon.ser.acak.seed(sc["seed"])
        auto = sc["auto_mode"]
        henti = threading.Event()
        self.gw._auto_stop = henti
        self.gw.auto_mode = {"on": True, **auto, "scenario": sc["name"], "speed": speed}
        self.gw.event("info", f"DEMO scenario '{sc['name']}' started at {speed:g}x: {sc['description']}",
                      {"scenario": sc["name"], "speed": speed, "label": sc["label"]})
        try:
            while not self.stop_event.is_set():
                self.t0 = time.monotonic()
                self._apply(0)
                if not kon.kerja:
                    kon.mulai_tugas("skenario demo", lambda: kon.mode_otomatis(
                        self.gw.selector.W, henti, auto["interval_s"] / speed, auto["trigger_pct"] / 100,
                        auto["hold_s"] / speed, putuskan=self.gw._putuskan))
                for k in range(1, len(sc["timeline"])):
                    if self._wait_until(sc["timeline"][k]["at_s"] / speed):
                        return
                    self._apply(k)
                if self._wait_until(sc["duration_s"] / speed) or not sc["loop"]:
                    return
                self.gw.event("info", f"DEMO scenario '{sc['name']}' repeats")
        finally:
            henti.set()
            self.gw.auto_mode = {"on": False}
            end = time.time() + 30                     # let the running step finish before restoring the timing
            while kon.kerja and time.time() < end:
                time.sleep(0.1)
            kon.ser.lambat = old_lambat
            self.gw.event("info", f"DEMO scenario '{sc['name']}' ended")

    def _wait_until(self, t_rel):
        """Wait until t_rel seconds after the cycle start; True when stopped (or the auto mode died)."""
        while True:
            remaining = self.t0 + t_rel - time.monotonic()
            if remaining <= 0:
                return False
            if self.stop_event.wait(min(remaining, 0.5)) or self.gw.kon.henti.is_set():
                return True
