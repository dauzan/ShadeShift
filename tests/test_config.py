from pathlib import Path

import pytest

from shadeshift import config


def test_defaults_match_contract(tmp_path):
    s = config.load(env={}, env_file=tmp_path / "missing.env")
    assert (s.host, s.api_port, s.dashboard_port) == ("127.0.0.1", 8000, 8501)
    assert s.api_url == "http://127.0.0.1:8000"
    assert s.api_token == ""
    assert s.db_path == config.ROOT / "data" / "shadeshift.db"
    assert s.lab_dir == config.ROOT / "SHADESHIFT_ML" / "data" / "data_lab"
    assert s.model_path == config.ROOT / "models" / "pemilih.onnx"
    assert (s.edge_runtime, s.source, s.serial_port, s.serial_baud) == ("auto", "demo", "auto", 115200)
    assert s.device_id == "demo-01"
    assert (s.demo_scenario, s.demo_speed, s.online_timeout_s, s.log_level) == ("default", 1.0, 10.0, "INFO")


def test_priority_env_over_file_over_default(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nSHADESHIFT_API_PORT=9000\nSHADESHIFT_SERIAL_PORT='COM7'\nSHADESHIFT_SOURCE=serial\n", encoding="utf-8")
    s = config.load(env={"SHADESHIFT_API_PORT": "9100"}, env_file=env_file)
    assert s.api_port == 9100                      # environment beats .env
    assert s.api_url == "http://127.0.0.1:9100"    # derived from the effective port
    assert s.serial_port == "COM7"                 # quotes stripped
    assert s.device_id == "esp32-01"               # default id follows the source


def test_relative_paths_resolve_against_project_root(tmp_path):
    s = config.load(env={"SHADESHIFT_DATA_DIR": "var/x"}, env_file=tmp_path / "none")
    assert s.data_dir == (config.ROOT / "var" / "x").resolve()
    assert s.db_path == s.data_dir / "shadeshift.db"


def test_overrides_and_validation(tmp_path):
    s = config.load(env={}, env_file=tmp_path / "none")
    live = s.with_overrides(source="serial", serial_port="COM5", api_port=None)
    assert (live.source, live.serial_port, live.device_id, live.api_port) == ("serial", "COM5", "esp32-01", 8000)
    with pytest.raises(ValueError):
        s.with_overrides(edge_runtime="tflite")
    with pytest.raises(ValueError):
        config.load(env={"SHADESHIFT_API_PORT": "eighty"}, env_file=tmp_path / "none")
