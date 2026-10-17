"""Request bodies of the server API (CONTRACT.md §5). Responses are plain dicts built in app.py."""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from shadeshift import protocol

DEVICE_ID = r"^[A-Za-z0-9_.\-]{1,64}$"
Topology = Literal["4S", "2S2P", "TCT", "4P", "?"]
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
