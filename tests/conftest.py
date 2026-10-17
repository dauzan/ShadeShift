import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The dashboard modules (inti, koneksi) are imported the same way Streamlit imports them: from dasbor/.
for p in (ROOT, ROOT / "dasbor"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@contextmanager
def server_client(tmp_path, **env):
    """FastAPI TestClient on a fresh database in tmp_path. Extra env entries override settings."""
    from fastapi.testclient import TestClient
    from shadeshift import config
    from shadeshift.server.app import create_app
    settings = config.load(env={"SHADESHIFT_DATA_DIR": str(tmp_path), **env}, env_file=tmp_path / "no.env")
    app = create_app(settings)
    with TestClient(app) as client:
        client.core = app.state.core
        yield client


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    with server_client(tmp_path_factory.mktemp("server")) as client:
        yield client


def heartbeat(client, device_id="esp32-01", kind="esp32", run_uuid=None, **state):
    run_uuid = run_uuid or str(uuid.uuid4())
    r = client.post("/api/v1/devices/heartbeat", json={"device_id": device_id, "kind": kind, "transport": "test",
                                                       "run_uuid": run_uuid, "state": {"connected": True, **state}})
    assert r.status_code == 200, r.text
    return run_uuid
