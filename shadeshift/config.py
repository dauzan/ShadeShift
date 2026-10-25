"""Configuration shared by the server, the gateway and the dashboard (docs/CONTRACT.md §9).

Priority: command-line flags (applied by run.py with Settings.with_overrides) > environment variables >
a .env file in the project root > the defaults below. Relative paths are resolved against the project root.
"""
import os
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EDGE_RUNTIMES = ("auto", "onnx", "numpy")
SOURCES = ("serial", "demo")
DEFAULT_DEVICE_ID = {"serial": "esp32-01", "demo": "demo-01"}


def read_env_file(path):
    """Minimal .env reader: KEY=VALUE lines, '#' comments, optional surrounding quotes, no expansion."""
    values = {}
    path = Path(path)
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    host: str
    api_port: int
    dashboard_port: int
    api_url: str
    api_token: str
    data_dir: Path
    db_path: Path
    ml_dir: Path
    lab_dir: Path
    model_path: Path
    edge_runtime: str
    source: str
    serial_port: str
    serial_baud: int
    device_id: str
    demo_scenario: str
    demo_speed: float
    online_timeout_s: float
    log_level: str
    monitor_auto: bool = True          # the gateway started by run.py begins monitoring by itself (CONTRACT §19)
    gemini_api_key: str = ""           # optional (CONTRACT §27): Gemini rewords the analyser box; empty = local sentences only
    gemini_model: str = "gemini-flash-latest"

    def with_overrides(self, **changes):
        """Copy with command-line overrides applied (None values are ignored)."""
        changes = {k: v for k, v in changes.items() if v is not None}
        if "source" in changes and "device_id" not in changes and self.device_id in DEFAULT_DEVICE_ID.values():
            changes["device_id"] = DEFAULT_DEVICE_ID[changes["source"]]
        new = replace(self, **changes)
        _validate(new)
        return new


def _path(value):
    p = Path(value)
    return p if p.is_absolute() else (ROOT / p).resolve()


def _validate(s):
    if s.edge_runtime not in EDGE_RUNTIMES:
        raise ValueError(f"SHADESHIFT_EDGE_RUNTIME must be one of {EDGE_RUNTIMES}, got {s.edge_runtime!r}")
    if s.source not in SOURCES:
        raise ValueError(f"SHADESHIFT_SOURCE must be one of {SOURCES}, got {s.source!r}")
    for name in ("api_port", "dashboard_port"):
        if not 1 <= getattr(s, name) <= 65535:
            raise ValueError(f"{name} out of range: {getattr(s, name)}")
    if s.demo_speed <= 0:
        raise ValueError("SHADESHIFT_DEMO_SPEED must be > 0")


def load(env=None, env_file=None):
    """Build Settings from the environment (default: os.environ) and the .env file (default: ROOT/.env)."""
    env = os.environ if env is None else env
    file_values = read_env_file(env_file if env_file is not None else ROOT / ".env")

    def get(name, default):
        value = env.get(name)
        if value is None or value == "":
            value = file_values.get(name)
        return default if value is None or value == "" else value

    def number(name, default, cast):
        value = get(name, default)
        try:
            return cast(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number, got {value!r}") from None

    api_port = number("SHADESHIFT_API_PORT", 8000, int)
    data_dir = _path(get("SHADESHIFT_DATA_DIR", "data"))
    ml_dir = _path(get("SHADESHIFT_ML_DIR", "SHADESHIFT_ML"))
    source = get("SHADESHIFT_SOURCE", "demo")
    settings = Settings(
        host=get("SHADESHIFT_HOST", "127.0.0.1"),
        api_port=api_port,
        dashboard_port=number("SHADESHIFT_DASHBOARD_PORT", 8501, int),
        api_url=get("SHADESHIFT_API_URL", f"http://127.0.0.1:{api_port}").rstrip("/"),
        api_token=get("SHADESHIFT_API_TOKEN", ""),
        data_dir=data_dir,
        db_path=_path(get("SHADESHIFT_DB_PATH", data_dir / "shadeshift.db")),
        ml_dir=ml_dir,
        lab_dir=_path(get("SHADESHIFT_LAB_DIR", ml_dir / "data" / "data_lab")),
        model_path=_path(get("SHADESHIFT_MODEL_PATH", "models/pemilih.onnx")),
        edge_runtime=get("SHADESHIFT_EDGE_RUNTIME", "auto"),
        source=source,
        serial_port=get("SHADESHIFT_SERIAL_PORT", "auto"),
        serial_baud=number("SHADESHIFT_SERIAL_BAUD", 115200, int),
        device_id=get("SHADESHIFT_DEVICE_ID", DEFAULT_DEVICE_ID.get(source, "esp32-01")),
        demo_scenario=get("SHADESHIFT_DEMO_SCENARIO", "default"),
        demo_speed=number("SHADESHIFT_DEMO_SPEED", 1.0, float),
        online_timeout_s=number("SHADESHIFT_ONLINE_TIMEOUT_S", 10, float),
        log_level=get("SHADESHIFT_LOG_LEVEL", "INFO").upper(),
        monitor_auto=get("SHADESHIFT_MONITOR_AUTO", "1").strip().lower() not in ("0", "false", "no", "off"),
        gemini_api_key=get("SHADESHIFT_GEMINI_API_KEY", "").strip(),
        gemini_model=get("SHADESHIFT_GEMINI_MODEL", "gemini-flash-latest").strip(),
    )
    _validate(settings)
    return settings
