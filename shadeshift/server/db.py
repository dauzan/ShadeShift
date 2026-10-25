"""SQLite storage for the ShadeShift server (docs/CONTRACT.md §10).

One connection per thread (FastAPI runs sync endpoints in a thread pool), WAL journal, foreign keys on.
Schema changes are numbered migrations applied at start; the version lives in PRAGMA user_version.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE devices (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('esp32','emulator','virtual')),
  transport    TEXT,
  firmware     TEXT,
  first_seen   TEXT NOT NULL,
  last_seen    TEXT NOT NULL,
  state_json   TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE runs (
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  device_id    TEXT NOT NULL REFERENCES devices(id),
  source       TEXT NOT NULL CHECK (source IN ('device','demo','upload','lab')),
  started_at   TEXT NOT NULL,
  ended_at     TEXT,
  meta_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE uploads (
  id           INTEGER PRIMARY KEY,
  filename     TEXT NOT NULL,
  sha256       TEXT NOT NULL UNIQUE,
  size_bytes   INTEGER NOT NULL,
  uploaded_at  TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('ok','rejected')),
  n_sweeps     INTEGER NOT NULL DEFAULT 0,
  error        TEXT
);
CREATE TABLE sweeps (
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  device_id    TEXT NOT NULL REFERENCES devices(id),
  run_id       INTEGER REFERENCES runs(id),
  upload_id    INTEGER REFERENCES uploads(id),
  source       TEXT NOT NULL CHECK (source IN ('device','demo','upload','lab')),
  label        TEXT NOT NULL,
  topology     TEXT NOT NULL CHECK (topology IN ('4S','2S2P','TCT','4P','?')),
  condition    TEXT,
  repeat       INTEGER,
  captured_at  TEXT NOT NULL,
  received_at  TEXT NOT NULL,
  n_points     INTEGER NOT NULL,
  complete     INTEGER NOT NULL DEFAULT 1,
  voc REAL, isc REAL, pmax REAL, vmp REAL, imp REAL,
  header_json  TEXT NOT NULL DEFAULT '{}',
  device_meta_json TEXT NOT NULL DEFAULT '{}',
  sweep_ms REAL, switch_ms REAL,
  points_json  TEXT NOT NULL,
  raw_text     TEXT,
  replay_of    TEXT
);
CREATE INDEX idx_sweeps_device_time ON sweeps(device_id, captured_at);
CREATE INDEX idx_sweeps_source_cond ON sweeps(source, condition, repeat);
CREATE TABLE decisions (
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  sweep_id     INTEGER NOT NULL REFERENCES sweeps(id),
  device_id    TEXT NOT NULL REFERENCES devices(id),
  decided_by   TEXT NOT NULL CHECK (decided_by IN ('esp32','gateway_onnx','gateway_numpy','server_onnx','server_numpy')),
  model_id     TEXT NOT NULL,
  choice       TEXT NOT NULL CHECK (choice IN ('4S','2S2P','TCT')),
  scores_json  TEXT NOT NULL,
  features_json TEXT NOT NULL,
  latency_us   REAL,
  trigger      TEXT NOT NULL CHECK (trigger IN ('observe','auto_once','auto_trigger','stability_lock','upload','replay','manual')),
  applied      INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL
);
CREATE INDEX idx_decisions_device_time ON decisions(device_id, created_at);
CREATE INDEX idx_decisions_sweep ON decisions(sweep_id);
CREATE TABLE evaluations (
  id           INTEGER PRIMARY KEY,
  decision_id  INTEGER REFERENCES decisions(id),
  device_id    TEXT NOT NULL REFERENCES devices(id),
  pmax_4s REAL, pmax_2s2p REAL, pmax_tct REAL,
  sweep_ids_json TEXT NOT NULL DEFAULT '[]',
  best         TEXT NOT NULL,
  chosen       TEXT NOT NULL,
  loss_pct     REAL NOT NULL,
  source       TEXT NOT NULL CHECK (source IN ('device','demo','upload','lab')),
  created_at   TEXT NOT NULL
);
CREATE TABLE events (
  id           INTEGER PRIMARY KEY,
  device_id    TEXT REFERENCES devices(id),
  kind         TEXT NOT NULL CHECK (kind IN ('alert','switch','command','status','error','info')),
  message      TEXT NOT NULL,
  data_json    TEXT NOT NULL DEFAULT '{}',
  created_at   TEXT NOT NULL
);
CREATE INDEX idx_events_device_time ON events(device_id, created_at);
CREATE TABLE commands (
  id           INTEGER PRIMARY KEY,
  device_id    TEXT NOT NULL REFERENCES devices(id),
  kind         TEXT NOT NULL CHECK (kind IN ('raw','action')),
  command      TEXT NOT NULL,
  params_json  TEXT NOT NULL DEFAULT '{}',
  status       TEXT NOT NULL CHECK (status IN ('queued','sent','done','failed','expired')),
  created_at   TEXT NOT NULL,
  sent_at      TEXT,
  done_at      TEXT,
  result       TEXT
);
CREATE INDEX idx_commands_device_status ON commands(device_id, status);
CREATE TABLE device_log (
  id           INTEGER PRIMARY KEY,
  device_id    TEXT NOT NULL REFERENCES devices(id),
  dir          TEXT NOT NULL CHECK (dir IN ('rx','tx')),
  line         TEXT NOT NULL,
  at           TEXT NOT NULL
);
CREATE INDEX idx_log_device ON device_log(device_id, id);
CREATE TABLE metrics (
  id           INTEGER PRIMARY KEY,
  device_id    TEXT REFERENCES devices(id),
  name         TEXT NOT NULL,
  value        REAL NOT NULL,
  unit         TEXT NOT NULL,
  provenance   TEXT NOT NULL CHECK (provenance IN ('measured','emulated','manual','calculated')),
  data_json    TEXT NOT NULL DEFAULT '{}',
  at           TEXT NOT NULL
);
CREATE INDEX idx_metrics_name ON metrics(name, at);
CREATE TABLE settings (
  key          TEXT PRIMARY KEY,
  value_json   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
"""

# 2: single-panel sweeps (firmware 3.2) may have topology A, B, C or D. SQLite cannot change a CHECK
# constraint, so the table is rebuilt (sqlite.org/lang_altertable.html, "other kinds of table schema changes").
MIGRATION_2 = """
CREATE TABLE sweeps_new (
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  device_id    TEXT NOT NULL REFERENCES devices(id),
  run_id       INTEGER REFERENCES runs(id),
  upload_id    INTEGER REFERENCES uploads(id),
  source       TEXT NOT NULL CHECK (source IN ('device','demo','upload','lab')),
  label        TEXT NOT NULL,
  topology     TEXT NOT NULL CHECK (topology IN ('4S','2S2P','TCT','4P','A','B','C','D','?')),
  condition    TEXT,
  repeat       INTEGER,
  captured_at  TEXT NOT NULL,
  received_at  TEXT NOT NULL,
  n_points     INTEGER NOT NULL,
  complete     INTEGER NOT NULL DEFAULT 1,
  voc REAL, isc REAL, pmax REAL, vmp REAL, imp REAL,
  header_json  TEXT NOT NULL DEFAULT '{}',
  device_meta_json TEXT NOT NULL DEFAULT '{}',
  sweep_ms REAL, switch_ms REAL,
  points_json  TEXT NOT NULL,
  raw_text     TEXT,
  replay_of    TEXT
);
INSERT INTO sweeps_new SELECT * FROM sweeps;
DROP TABLE sweeps;
ALTER TABLE sweeps_new RENAME TO sweeps;
CREATE INDEX idx_sweeps_device_time ON sweeps(device_id, captured_at);
CREATE INDEX idx_sweeps_source_cond ON sweeps(source, condition, repeat);
"""

# 3: data-collection sessions and labeled full scans (docs/CONTRACT.md §12). Each sweep of a scan points to it.
MIGRATION_3 = """
CREATE TABLE sessions (
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  device_id    TEXT NOT NULL REFERENCES devices(id),
  source       TEXT NOT NULL CHECK (source IN ('device','demo')),
  place        TEXT NOT NULL CHECK (place IN ('indoor_lamp','outdoor_sun')),
  sky          TEXT,
  location     TEXT,
  operator     TEXT,
  note         TEXT,
  started_at   TEXT NOT NULL,
  ended_at     TEXT
);
CREATE INDEX idx_sessions_device ON sessions(device_id, started_at);
CREATE TABLE scans (
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  session_id   INTEGER NOT NULL REFERENCES sessions(id),
  device_id    TEXT NOT NULL REFERENCES devices(id),
  code         TEXT NOT NULL,
  condition    TEXT NOT NULL,
  diagnosis    TEXT CHECK (diagnosis IN ('normal','partial_shading','uniform_dimming','bypass_open','bypass_short','series_resistance')),
  modules      TEXT NOT NULL DEFAULT '',
  dynamic      INTEGER NOT NULL DEFAULT 0,
  rounds       INTEGER NOT NULL,
  repeat_start INTEGER NOT NULL,
  with_panels  INTEGER NOT NULL DEFAULT 0,
  pause_s      REAL NOT NULL DEFAULT 0,
  temps_json   TEXT NOT NULL DEFAULT '{}',
  note         TEXT,
  status       TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','stopped')),
  result       TEXT,
  command_id   INTEGER REFERENCES commands(id),
  created_at   TEXT NOT NULL,
  ended_at     TEXT
);
CREATE INDEX idx_scans_session ON scans(session_id);
CREATE INDEX idx_scans_condition ON scans(condition);
ALTER TABLE sweeps ADD COLUMN scan_id INTEGER REFERENCES scans(id);
CREATE INDEX idx_sweeps_scan ON sweeps(scan_id);
"""

# 4: decision audits also record the single panels (ideal-MLPE reference) and 4P (docs/CONTRACT.md §13).
MIGRATION_4 = """
ALTER TABLE evaluations ADD COLUMN pmax_4p REAL;
ALTER TABLE evaluations ADD COLUMN pmax_panels_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE evaluations ADD COLUMN mlpe_w REAL;
"""

# 5: model registry (docs/CONTRACT.md §14): every trained candidate with what it was trained and tested on.
MIGRATION_5 = """
CREATE TABLE models (
  id           INTEGER PRIMARY KEY,
  model_id     TEXT NOT NULL UNIQUE,
  task         TEXT NOT NULL CHECK (task IN ('diagnosis','selector','pattern')),
  kind         TEXT NOT NULL CHECK (kind IN ('logreg','tree')),
  sources_json TEXT NOT NULL,
  params_json  TEXT NOT NULL DEFAULT '{}',
  model_json   TEXT NOT NULL,
  report_json  TEXT NOT NULL,
  evidence     TEXT NOT NULL CHECK (evidence IN ('real','lab','sim')),
  active       INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL,
  activated_at TEXT,
  note         TEXT
);
CREATE INDEX idx_models_task ON models(task, active);
"""

MIGRATIONS = {1: SCHEMA_V1, 2: MIGRATION_2, 3: MIGRATION_3, 4: MIGRATION_4, 5: MIGRATION_5}
SCHEMA_VERSION = max(MIGRATIONS)

DEFAULT_SETTINGS = {
    "twin_scale": 1.0,
    "twin_shading": "none",
    "alert_threshold_pct": 15,
    # Monitor every 5 min: each monitor sweep cuts the power ~3 s; every 10 s lost to fixed TCT in all 36 simulated
    # moving-shade scenarios (SHADESHIFT_ML/uji_stabilitas.py, CONTRACT §17). Stability window None = last 3 sweeps.
    "auto_mode_defaults": {"interval_s": 300, "trigger_pct": 20, "hold_s": 30,
                           "stability": {"enabled": False, "window_s": None, "cv_pct": 10}},   # rule not validated yet
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _connect(path):
    con = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    return con


class Database:
    """Thin wrapper: one connection per thread, explicit transactions via tx()."""

    def __init__(self, path):
        self.path = Path(path)
        self._local = threading.local()
        self._all = []
        self._lock = threading.Lock()

    @property
    def con(self):
        con = getattr(self._local, "con", None)
        if con is None:
            con = _connect(self.path)
            self._local.con = con
            with self._lock:
                self._all.append(con)
        return con

    def migrate(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = self.con
        con.execute("PRAGMA journal_mode=WAL")
        current = con.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"database schema {current} is newer than this code ({SCHEMA_VERSION})")
        for version in sorted(MIGRATIONS):
            if version > current:
                self._apply(con, version)
        now = utc_now()
        for key, value in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key, value_json, updated_at) VALUES (?,?,?)",
                        (key, dumps(value), now))
        return con.execute("PRAGMA user_version").fetchone()[0]

    @staticmethod
    def _apply(con, version):
        """One migration in one transaction. Foreign keys are off during it (a table rebuild drops a referenced
        table; the pragma has no effect inside a transaction) and are checked before COMMIT."""
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.executescript(f"BEGIN;\n{MIGRATIONS[version]}")
            bad = con.execute("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise RuntimeError(f"migration {version} would break {len(bad)} foreign key(s); database left unchanged")
            con.execute(f"PRAGMA user_version={version}")
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.execute("PRAGMA foreign_keys=ON")

    def tx(self):
        return _Transaction(self.con)

    def query(self, sql, args=()):
        return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.con.execute(sql, args).fetchone()
        return dict(r) if r else None

    def close(self):
        with self._lock:
            for con in self._all:
                try:
                    con.close()
                except sqlite3.Error:
                    pass
            self._all.clear()
        self._local = threading.local()


class _Transaction:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, exc_type, exc, tb):
        self.con.execute("ROLLBACK" if exc_type else "COMMIT")
        return False
