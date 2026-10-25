"""Request bodies of the server API (docs/CONTRACT.md §5). Responses are plain dicts built in app.py."""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from shadeshift import protocol

DEVICE_ID = r"^[A-Za-z0-9_.\-]{1,64}$"
Topology = Literal["4S", "2S2P", "TCT", "4P", "A", "B", "C", "D", "?"]     # A-D: single-panel sweeps (firmware 3.2)
Choice = Literal["4S", "2S2P", "TCT"]
LiveSource = Literal["device", "demo"]
Source = Literal["device", "demo", "upload", "lab"]
DecidedBy = Literal["esp32", "gateway_onnx", "gateway_numpy", "server_onnx", "server_numpy"]
Trigger = Literal["observe", "auto_once", "auto_trigger", "stability_lock", "upload", "replay", "manual"]
EventKind = Literal["alert", "switch", "command", "status", "error", "info"]
Provenance = Literal["measured", "emulated", "manual", "calculated"]
Shading = Literal["none", "opak_A", "paranet_A", "paranet_AB", "paranet_AD"]


def valid_device_id(device_id):
    return re.fullmatch(DEVICE_ID, device_id or "") is not None


class Points(BaseModel):
    v: list[float] = Field(min_length=2, max_length=5000)
    i: list[float] = Field(min_length=2, max_length=5000)

    @model_validator(mode="after")
    def same_length(self):
        if len(self.v) != len(self.i):
            raise ValueError("points.v and points.i must have the same length")
        return self


class Header(BaseModel):
    voc: float | None = None
    dac_lo: int | None = None
    dac_hi: int | None = None
    n: int | None = Field(default=None, ge=1, le=5000)
    pmax: float | None = None
    vmp: float | None = None
    imp: float | None = None
    light_v: float | None = Field(default=None, ge=-1, le=6)        # LDR at ADS1115 A2 before / after the sweep (relative)
    light_end_v: float | None = Field(default=None, ge=-1, le=6)


class Timing(BaseModel):
    sweep_ms: float | None = Field(default=None, ge=0)
    switch_ms: float | None = Field(default=None, ge=0)


class DeviceMeta(BaseModel):
    uptime_ms: int | None = Field(default=None, ge=0)
    seq: int | None = Field(default=None, ge=0)


class DeviceDecision(BaseModel):
    choice: Choice
    scores: list[float] | None = Field(default=None, min_length=3, max_length=3)
    latency_us: float | None = Field(default=None, ge=0)


class SweepIn(BaseModel):
    uuid: str = Field(min_length=8, max_length=64)
    device_id: str = Field(pattern=DEVICE_ID)
    run_uuid: str | None = Field(default=None, max_length=64)
    source: LiveSource                       # upload/lab sweeps come only from /uploads and /import/lab
    label: str = "tanpa_label"
    topology: Topology
    captured_at: str = Field(min_length=10, max_length=40)
    points: Points
    header: Header = Header()
    timing: Timing = Timing()
    device_meta: DeviceMeta = DeviceMeta()
    device_decision: DeviceDecision | None = None
    condition: str | None = Field(default=None, max_length=80)
    repeat: int | None = Field(default=None, ge=0, le=1000)
    replay_of: str | None = Field(default=None, max_length=200)
    complete: bool = True
    raw_text: str | None = Field(default=None, max_length=200_000)
    scan_uuid: str | None = Field(default=None, max_length=64)      # sweep of a labeled full scan (CONTRACT §12)

    @field_validator("label")
    @classmethod
    def clean_label(cls, v):
        return protocol.sanitize_label(v)


class DecisionIn(BaseModel):
    uuid: str = Field(min_length=8, max_length=64)
    sweep_uuid: str = Field(min_length=8, max_length=64)
    device_id: str = Field(pattern=DEVICE_ID)
    decided_by: DecidedBy
    model_id: str = Field(min_length=1, max_length=80)
    choice: Choice
    scores: list[float] = Field(min_length=3, max_length=3)
    features: list[float] = Field(min_length=14, max_length=14)
    latency_us: float | None = Field(default=None, ge=0)
    trigger: Trigger
    applied: bool = False
    created_at: str = Field(min_length=10, max_length=40)


class EventIn(BaseModel):
    device_id: str | None = Field(default=None, pattern=DEVICE_ID)
    kind: EventKind
    message: str = Field(min_length=1, max_length=500)
    data: dict = {}
    created_at: str | None = Field(default=None, max_length=40)


class EventsIn(BaseModel):
    items: list[EventIn] = Field(min_length=1, max_length=500)


class MetricIn(BaseModel):
    device_id: str | None = Field(default=None, pattern=DEVICE_ID)
    name: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    value: float
    unit: str = Field(min_length=1, max_length=16)
    provenance: Provenance
    data: dict = {}
    at: str | None = Field(default=None, max_length=40)


class MetricsIn(BaseModel):
    items: list[MetricIn] = Field(min_length=1, max_length=500)


class EvaluationIn(BaseModel):
    decision_uuid: str | None = Field(default=None, max_length=64)
    device_id: str = Field(pattern=DEVICE_ID)
    pmax: dict[Choice, float]
    pmax_4p: float | None = None
    pmax_panels: dict[Literal["A", "B", "C", "D"], float] = {}     # single-panel sweeps of the audit (firmware 3.2)
    mlpe_w: float | None = Field(default=None, gt=0)               # sum of the four single-panel Pmax
    sweep_uuids: list[str] = Field(default=[], max_length=10)
    best: Choice
    chosen: Choice
    loss_pct: float = Field(ge=0)
    source: Source
    created_at: str | None = Field(default=None, max_length=40)


class EvaluationsIn(BaseModel):
    items: list[EvaluationIn] = Field(min_length=1, max_length=100)


class LogLine(BaseModel):
    at: str | None = Field(default=None, max_length=40)
    dir: Literal["rx", "tx"]
    line: str = Field(max_length=500)


class LogIn(BaseModel):
    device_id: str = Field(pattern=DEVICE_ID)
    lines: list[LogLine] = Field(min_length=1, max_length=500)


class HeartbeatIn(BaseModel):
    device_id: str = Field(pattern=DEVICE_ID)
    kind: Literal["esp32", "emulator"]
    transport: str | None = Field(default=None, max_length=80)
    firmware: str | None = Field(default=None, max_length=40)
    run_uuid: str = Field(min_length=8, max_length=64)
    gateway: dict = {}
    state: dict = {}


class RangkaianIn(BaseModel):
    """A wiring change a person approved on the Rekomendasi Rangkaian page (CONTRACT §29). 4P is never applied."""
    target: Literal["4S", "2S2P", "TCT"]


class PerawatanIn(BaseModel):
    """A maintenance log entry from the owner (CONTRACT §28): the panels were cleaned, or a technician repaired them."""
    jenis: Literal["bersih", "perbaikan"]
    panel: Literal["A", "B", "C", "D"] | None = None


class CommandIn(BaseModel):
    kind: Literal["raw", "action"]
    command: str = Field(min_length=1, max_length=64)
    params: dict = {}


class CommandResultIn(BaseModel):
    status: Literal["done", "failed"]
    result: str | None = Field(default=None, max_length=500)


class SettingsIn(BaseModel):
    twin_scale: float | None = Field(default=None, ge=0.05, le=4.0)
    twin_shading: Shading | None = None
    alert_threshold_pct: float | None = Field(default=None, ge=1, le=100)
    auto_mode_defaults: dict | None = None


class LabImportIn(BaseModel):
    include_anomalies: bool = False


class CalibrateIn(BaseModel):
    sweep_id: int


# ---------------- data-collection sessions (CONTRACT §12) ----------------
Place = Literal["indoor_lamp", "outdoor_sun"]
Diagnosis = Literal["normal", "partial_shading", "uniform_dimming", "bypass_open", "bypass_short", "series_resistance"]
Module = Literal["A", "B", "C", "D"]


class SessionIn(BaseModel):
    device_id: str = Field(pattern=DEVICE_ID)
    place: Place
    sky: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=200)
    operator: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)


class ScanIn(BaseModel):
    code: str = Field(min_length=2, max_length=4)
    modules: str | None = Field(default=None, max_length=4)      # None = the catalog default for the code
    diagnosis: Diagnosis | None = None                            # None = the catalog default (may stay empty)
    dynamic: bool | None = None
    rounds: int = Field(default=3, ge=1, le=60)
    panels: bool = True
    pause_s: float = Field(default=30, ge=0, le=600)
    note: str | None = Field(default=None, max_length=2000)


class ScanUpdate(BaseModel):
    """Labels can be corrected after the scan; the raw sweeps never change."""
    diagnosis: Diagnosis | None = None
    modules: str | None = Field(default=None, max_length=4)
    note: str | None = Field(default=None, max_length=2000)
    temps: dict[str, dict[Module, float | None]] | None = None   # {"<repeat>": {"A": 41.5, ...}} panel back, deg C

    @field_validator("temps")
    @classmethod
    def plausible(cls, v):
        for rep, row in (v or {}).items():
            if not rep.isdigit():
                raise ValueError("temps keys are repeat numbers, e.g. '1'")
            if any(x is not None and not -20 <= x <= 120 for x in row.values()):
                raise ValueError("temperatures must be between -20 and 120 deg C")
        return v


# ---------------- AI models on real data (CONTRACT §14) ----------------
class TrainIn(BaseModel):
    task: Literal["diagnosis", "selector", "pattern"]
    kind: Literal["logreg", "tree"] = "logreg"
    sources: list[Literal["real", "lab", "sim"]] = Field(default=["real", "lab"], min_length=1)
    params: dict = {}                                  # logreg: {"C"}; tree: {"max_depth", "min_leaf"}
    test_day: str | None = Field(default=None, max_length=10)
    sim_n: int = Field(default=200, ge=20, le=1500)    # simulated rounds per class when "sim" is a source

    @field_validator("params")
    @classmethod
    def known_params(cls, v):
        allowed = {"C": (1e-3, 1e3), "max_depth": (1, 8), "min_leaf": (1, 50)}
        for k, x in v.items():
            if k not in allowed or not isinstance(x, (int, float)) or not allowed[k][0] <= x <= allowed[k][1]:
                raise ValueError(f"params: {k} must be one of {sorted(allowed)} within {allowed.get(k)}")
        return v


# ---------------- Digital Twin what-if (CONTRACT §18) ----------------
class WhatIfIn(BaseModel):
    coverage: dict[Literal["A", "B", "C", "D"], list[float]] = {}   # per module: 36 cell shares 0-1, twin cell order
    kind: Literal["solid", "cloth"] = "solid"                       # solid object (2 % light left) or shade cloth
    scale: float | None = Field(default=None, ge=0.05, le=4.0)      # light scale; None = the calibrated setting

    @field_validator("coverage")
    @classmethod
    def thirty_six_cells(cls, v):
        for m, cells in v.items():
            if len(cells) != 36 or any(not 0.0 <= c <= 1.0 for c in cells):
                raise ValueError(f"coverage[{m}] must be 36 numbers between 0 and 1")
        return v
