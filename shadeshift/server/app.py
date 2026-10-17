"""ShadeShift local server: FastAPI + SQLite (CONTRACT.md §5). Start with:  python run.py server

Everything binds to 127.0.0.1 by default and nothing here needs the internet. FastAPI's built-in /docs page loads
its JavaScript from a CDN, so it is replaced by a small server-rendered page; /openapi.json is always available.
"""
import asyncio
import csv
import hashlib
import html
import io
import json
import logging
import threading
import time
import uuid as uuidlib
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse

from shadeshift import __version__, commands, config as cfg, protocol
from shadeshift.edge.selector import CLASSES, FEATURE_NAMES, EdgeSelector, weights_sha256
from shadeshift.server import csv_import, models as M
from shadeshift.server.db import SCHEMA_VERSION, Database, dumps, utc_now
from shadeshift.server.hub import Hub
from shadeshift.server.twin import LABEL as TWIN_LABEL, SHADINGS, Twin

log = logging.getLogger("shadeshift.server")
API = "/api/v1"
UUID_NS = uuidlib.UUID("6a3f1d2e-9b8c-4c1a-8e7f-2d4b5c6a7e80")     # deterministic ids for uploads and lab imports
RESERVED_DEVICES = {"upload": "virtual", "lab": "virtual"}
QUEUED_TTL_S, SENT_TTL_S, RUN_IDLE_S, LOG_KEEP = 60, 120, 60, 5000
MODEL_CLAIMS = {
    "lab": "loss 0.82 % vs 2.71 % for the best fixed topology (2S2P), among 4S/2S2P/TCT; 30 halogen-lamp sets, 6 patterns",
    "sim": "3.00 vs 6.35 points of ideal-MLPE power (fixed TCT); accuracy 68.9 %, balanced 47.5 % (simulation)",
}
SWEEP_COLS = ("id, uuid, device_id, run_id, upload_id, source, label, topology, condition, repeat, captured_at, "
              "received_at, n_points, complete, voc, isc, pmax, vmp, imp, sweep_ms, switch_ms, replay_of")


def _iso_age_s(iso):
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return float("inf")
    return time.time() - t.timestamp()


class Core:
    """Everything the routes share: settings, database, twin, selector, live hub, command wake-ups."""

    def __init__(self, settings):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.twin = Twin()
        self.selector = EdgeSelector(role="server")
        self.hub = Hub()
        self._cmd_cond = threading.Condition()
        self._stop = threading.Event()

    # ---------- small helpers ----------
    def setting(self, key):
        row = self.db.one("SELECT value_json FROM settings WHERE key=?", (key,))
        return json.loads(row["value_json"]) if row else None

    def settings_dict(self):
        return {r["key"]: json.loads(r["value_json"]) for r in self.db.query("SELECT key, value_json FROM settings")}

    def ensure_virtual_device(self, con, device_id):
        now = utc_now()
        con.execute("INSERT OR IGNORE INTO devices(id, kind, transport, first_seen, last_seen) VALUES (?,?,?,?,?)",
                    (device_id, "virtual", "http", now, now))

    def device_row(self, device_id):
        d = self.db.one("SELECT * FROM devices WHERE id=?", (device_id,))
        if not d:
            return None
        state = json.loads(d.pop("state_json") or "{}")
        d["state"] = state.get("state", {})
        d["gateway"] = state.get("gateway", {})
        d["online"] = d["kind"] != "virtual" and _iso_age_s(d["last_seen"]) <= self.settings.online_timeout_s
        return d

    def expected(self):
        if not self.twin.available:
            return None
        s = self.settings_dict()
        try:
            return self.twin.expected(s.get("twin_scale", 1.0), s.get("twin_shading", "none"))
        except Exception as e:                      # twin failure must never break ingestion
            log.warning("twin failed: %s", e)
            return None

    def sweep_summary(self, row):
        d = dict(row)
        d["complete"] = bool(d["complete"])
        choice, by = d.pop("d_choice", None), d.pop("d_by", None)
        d["decision"] = {"choice": choice, "decided_by": by} if choice else None
        return d

    def sweep_full(self, sweep_id):
        r = self.db.one(f"SELECT {SWEEP_COLS}, header_json, device_meta_json, points_json, raw_text, "
                        "(SELECT choice FROM decisions WHERE sweep_id=sweeps.id ORDER BY id DESC LIMIT 1) AS d_choice, "
                        "(SELECT decided_by FROM decisions WHERE sweep_id=sweeps.id ORDER BY id DESC LIMIT 1) AS d_by "
                        "FROM sweeps WHERE id=?", (sweep_id,))
        if not r:
            return None
        header, meta, points = (json.loads(r.pop(k)) for k in ("header_json", "device_meta_json", "points_json"))
        d = self.sweep_summary(r)
        d.update(header=header, device_meta=meta, points=points)
        return d

    def decision_row(self, r):
        d = dict(r)
        d["scores"] = json.loads(d.pop("scores_json"))
        d["features"] = json.loads(d.pop("features_json"))
        d["applied"] = bool(d["applied"])
        return d

    def add_event(self, con, device_id, kind, message, data=None, created_at=None):
        con.execute("INSERT INTO events(device_id, kind, message, data_json, created_at) VALUES (?,?,?,?,?)",
                    (device_id, kind, message, dumps(data or {}), created_at or utc_now()))
        return {"device_id": device_id, "kind": kind, "message": message, "data": data or {},
                "created_at": created_at or utc_now()}

    # ---------- storing sweeps (shared by ingest, uploads, lab import) ----------
    def store_sweep(self, con, *, uuid, device_id, run_id, upload_id, source, label, topology, condition, repeat,
                    captured_at, v, i, header, device_meta, complete, timing, replay_of, raw_text):
        derived = protocol.derive(v, i, header.get("voc"))
        cur = con.execute(
            "INSERT INTO sweeps(uuid, device_id, run_id, upload_id, source, label, topology, condition, repeat, "
            "captured_at, received_at, n_points, complete, voc, isc, pmax, vmp, imp, header_json, device_meta_json, "
            "sweep_ms, switch_ms, points_json, raw_text, replay_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid, device_id, run_id, upload_id, source, label, topology, condition, repeat, captured_at, utc_now(),
             derived["n_points"], int(bool(complete)), derived["voc"], derived["isc"], derived["pmax"], derived["vmp"],
             derived["imp"], dumps(header), dumps(device_meta), timing.get("sweep_ms"), timing.get("switch_ms"),
             dumps({"v": list(v), "i": list(i)}), raw_text, replay_of))
        return cur.lastrowid, derived

    def server_decision(self, con, sweep_id, device_id, v, i, trigger):
        dec = self.selector.decide(v, i)
        if dec is None:
            return None
        con.execute(
            "INSERT INTO decisions(uuid, sweep_id, device_id, decided_by, model_id, choice, scores_json, features_json, "
            "latency_us, trigger, applied, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuidlib.uuid4()), sweep_id, device_id, dec.decided_by, dec.model_id, dec.choice, dumps(dec.scores),
             dumps(dec.features), dec.latency_us, trigger, 0, utc_now()))
        return {"choice": dec.choice, "decided_by": dec.decided_by}

    # ---------- background maintenance ----------
    def maintenance_loop(self):
        while not self._stop.wait(5.0):
            try:
                self.maintain()
            except Exception:
                log.exception("maintenance failed")

    def maintain(self):
        now = utc_now()
        with self.db.tx() as con:
            for c in con.execute("SELECT id, device_id, status, created_at, sent_at FROM commands "
                                 "WHERE status IN ('queued','sent')").fetchall():
                if c["status"] == "queued" and _iso_age_s(c["created_at"]) > QUEUED_TTL_S:
                    con.execute("UPDATE commands SET status='expired', done_at=? WHERE id=?", (now, c["id"]))
                    self.hub.publish("command", {"id": c["id"], "status": "expired", "result": None}, c["device_id"])
                elif c["status"] == "sent" and _iso_age_s(c["sent_at"]) > SENT_TTL_S:
                    con.execute("UPDATE commands SET status='failed', done_at=?, result=? WHERE id=?",
                                (now, "no result from gateway", c["id"]))
                    self.hub.publish("command", {"id": c["id"], "status": "failed", "result": "no result from gateway"},
                                     c["device_id"])
            for r in con.execute("SELECT runs.id, devices.last_seen FROM runs JOIN devices ON devices.id = runs.device_id "
                                 "WHERE runs.ended_at IS NULL AND runs.source IN ('device','demo')").fetchall():
                if _iso_age_s(r["last_seen"]) > RUN_IDLE_S:
                    con.execute("UPDATE runs SET ended_at=? WHERE id=?", (r["last_seen"], r["id"]))
            for d in con.execute("SELECT device_id, count(*) AS n FROM device_log GROUP BY device_id").fetchall():
                if d["n"] > LOG_KEEP:
                    con.execute("DELETE FROM device_log WHERE device_id=? AND id <= (SELECT id FROM device_log "
                                "WHERE device_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)", (d["device_id"], d["device_id"], LOG_KEEP))

    def wake_commands(self):
        with self._cmd_cond:
            self._cmd_cond.notify_all()


def _docs_page(app):
    rows = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or ["WS"])
        if not route.path.startswith(API):
            continue
        summary = (getattr(route, "summary", None) or (route.endpoint.__doc__ or "").strip().split("\n")[0]
                   if hasattr(route, "endpoint") else "")
        rows.append(f"<tr><td>{', '.join(m for m in methods if m != 'HEAD')}</td><td><code>{html.escape(route.path)}</code></td>"
                    f"<td>{html.escape(summary)}</td></tr>")
    return ("<!doctype html><meta charset='utf-8'><title>ShadeShift API</title>"
            "<style>body{font-family:system-ui,sans-serif;margin:2rem;max-width:70rem}td{padding:.2rem .6rem;"
            "border-bottom:1px solid #ddd;vertical-align:top}code{font-size:.95em}</style>"
            f"<h1>ShadeShift API v1</h1><p>Offline endpoint list (server {__version__}). Full shapes: "
            "<code>CONTRACT.md</code> §5 and <a href='/openapi.json'>/openapi.json</a>.</p>"
            "<table>" + "".join(rows) + "</table>")


def create_app(settings=None):
    settings = settings or cfg.load()
    core = Core(settings)

    @asynccontextmanager
    async def lifespan(app):
        core.db.migrate()
        core.hub.attach(asyncio.get_running_loop())
        threading.Thread(target=core.maintenance_loop, name="maintenance", daemon=True).start()
        threading.Thread(target=core.twin.warm_up, name="twin-warm-up", daemon=True).start()
        log.info("server ready: db=%s twin=%s", settings.db_path, "available" if core.twin.available else core.twin.reason)
        yield
        core._stop.set()
        core.wake_commands()
        core.db.close()

    app = FastAPI(title="ShadeShift local API", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.core = core
    db = core.db

    def require_token(x_shadeshift_token: str | None = Header(default=None)):
        if settings.api_token and x_shadeshift_token != settings.api_token:
            raise HTTPException(401, "missing or wrong X-ShadeShift-Token header")

    write = [Depends(require_token)]

    @app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
    def docs():
        return _docs_page(app)

    # ======================= health, model, settings =======================
    @app.get(API + "/health")
    def health():
        """Server, database, twin and model status."""
        try:
            db.one("SELECT 1 AS ok")
            db_state = "ok"
        except Exception as e:
            db_state = f"error: {e}"
        return {"status": "ok" if db_state == "ok" else "degraded", "version": __version__,
                "schema_version": SCHEMA_VERSION, "db": db_state, "time": utc_now(),
                "twin": "available" if core.twin.available else f"unavailable: {core.twin.reason}",
                "model": {"model_id": core.selector.model_id, "runtime": core.selector.runtime_label}}

    @app.get(API + "/model")
    def model():
        """Selector model metadata and its labeled evidence."""
        onnx_path = settings.model_path
        return {"model_id": core.selector.model_id, "classes": list(CLASSES), "feature_names": list(FEATURE_NAMES),
                "weights_sha256": weights_sha256(core.selector.W),
                "onnx_sha256": hashlib.sha256(onnx_path.read_bytes()).hexdigest() if onnx_path.is_file() else None,
                "runtime": core.selector.runtime_label, "claims": MODEL_CLAIMS}

    @app.get(API + "/settings")
    def get_settings():
        return core.settings_dict()

    @app.put(API + "/settings", dependencies=write)
    def put_settings(body: M.SettingsIn):
        """Shared dashboard settings: twin light scale, assumed shading, alert threshold, auto-mode defaults."""
        now = utc_now()
        with db.tx() as con:
            for key, value in body.model_dump(exclude_none=True).items():
                con.execute("INSERT INTO settings(key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) "
                            "DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                            (key, dumps(value), now))
            core.add_event(con, None, "info", "settings changed", body.model_dump(exclude_none=True))
        return core.settings_dict()

    # ======================= devices, heartbeat, runs =======================
    @app.post(API + "/devices/heartbeat", dependencies=write)
    def heartbeat(body: M.HeartbeatIn):
        """Gateway heartbeat (every 2 s); creates or updates the device and its run."""
        if body.device_id in RESERVED_DEVICES:
            raise HTTPException(400, f"device id {body.device_id!r} is reserved")
        now = utc_now()
        state = {"state": body.state, "gateway": body.gateway}
        with db.tx() as con:
            con.execute("INSERT INTO devices(id, kind, transport, firmware, first_seen, last_seen, state_json) "
                        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, "
                        "transport=excluded.transport, firmware=excluded.firmware, last_seen=excluded.last_seen, "
                        "state_json=excluded.state_json",
                        (body.device_id, body.kind, body.transport, body.firmware, now, now, dumps(state)))
            run = con.execute("SELECT id, ended_at FROM runs WHERE uuid=?", (body.run_uuid,)).fetchone()
            ending = body.state.get("connected") is False and body.state.get("ending") is True
            if run is None:
                source = "device" if body.kind == "esp32" else "demo"
                con.execute("INSERT INTO runs(uuid, device_id, source, started_at, meta_json) VALUES (?,?,?,?,?)",
                            (body.run_uuid, body.device_id, source, now,
                             dumps({"transport": body.transport, "gateway": body.gateway})))
                core.add_event(con, body.device_id, "status", f"run started ({source}, {body.transport})")
            elif run["ended_at"] and not ending:
                con.execute("UPDATE runs SET ended_at=NULL WHERE id=?", (run["id"],))
            if ending:
                con.execute("UPDATE runs SET ended_at=? WHERE uuid=? AND ended_at IS NULL", (now, body.run_uuid))
                core.add_event(con, body.device_id, "status", "gateway stopped")
        core.hub.publish("device", {"id": body.device_id, "online": not ending, "state": body.state}, body.device_id)
        return {"ok": True, "server_time": now}

    @app.get(API + "/devices")
    def devices():
        return [core.device_row(r["id"]) for r in db.query("SELECT id FROM devices ORDER BY id")]

    @app.get(API + "/devices/{device_id}")
    def device(device_id: str):
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        return d

    @app.get(API + "/runs")
    def runs(device_id: str | None = None, source: str | None = None, limit: int = Query(100, ge=1, le=1000)):
        rows = db.query("SELECT r.*, (SELECT count(*) FROM sweeps WHERE run_id=r.id) AS n_sweeps FROM runs r "
                        "WHERE (? IS NULL OR device_id=?) AND (? IS NULL OR source=?) ORDER BY id DESC LIMIT ?",
                        (device_id, device_id, source, source, limit))
        for r in rows:
            r["meta"] = json.loads(r.pop("meta_json"))
        return rows

    @app.get(API + "/runs/{run_id}")
    def run(run_id: int):
        r = db.one("SELECT r.*, (SELECT count(*) FROM sweeps WHERE run_id=r.id) AS n_sweeps FROM runs r WHERE id=?", (run_id,))
        if not r:
            raise HTTPException(404, "unknown run")
        r["meta"] = json.loads(r.pop("meta_json"))
        return r

    # ======================= ingestion =======================
    def _require_device(con, device_id):
        if not con.execute("SELECT 1 FROM devices WHERE id=?", (device_id,)).fetchone():
            raise HTTPException(404, f"unknown device {device_id!r}: send a heartbeat first")

    @app.post(API + "/ingest/sweeps", status_code=201, dependencies=write)
    def ingest_sweep(body: M.SweepIn, response: Response):
        """One sweep from a gateway (source device or demo). Idempotent by uuid."""
        alerts, events = [], []
        with db.tx() as con:
            _require_device(con, body.device_id)
            dup = con.execute("SELECT id, n_points, voc, isc, pmax, vmp, imp FROM sweeps WHERE uuid=?", (body.uuid,)).fetchone()
            if dup:
                response.status_code = 200
                d = dict(dup)
                return {"id": d.pop("id"), "uuid": body.uuid, "duplicate": True, "derived": d, "alerts": []}
            run_id = None
            if body.run_uuid:
                run = con.execute("SELECT id FROM runs WHERE uuid=?", (body.run_uuid,)).fetchone()
                if not run:
                    raise HTTPException(409, f"unknown run {body.run_uuid!r}: send a heartbeat with this run_uuid first")
                run_id = run["id"]
            header = body.header.model_dump(exclude_none=True)
            complete = body.complete and (body.header.n is None or len(body.points.v) == body.header.n + 1)
            sweep_id, derived = core.store_sweep(
                con, uuid=body.uuid, device_id=body.device_id, run_id=run_id, upload_id=None, source=body.source,
                label=body.label, topology=body.topology, condition=body.condition, repeat=body.repeat,
                captured_at=body.captured_at, v=body.points.v, i=body.points.i, header=header,
                device_meta=body.device_meta.model_dump(exclude_none=True), complete=complete,
                timing=body.timing.model_dump(exclude_none=True), replay_of=body.replay_of, raw_text=body.raw_text)
            if not complete:
                events.append(core.add_event(con, body.device_id, "error",
                                             f"incomplete sweep {body.label}: {len(body.points.v)} rows"
                                             + (f", expected {body.header.n + 1}" if body.header.n else ""),
                                             {"sweep_id": sweep_id}))
            if body.device_decision:
                dd = body.device_decision
                con.execute("INSERT INTO decisions(uuid, sweep_id, device_id, decided_by, model_id, choice, scores_json, "
                            "features_json, latency_us, trigger, applied, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (str(uuidlib.uuid5(UUID_NS, "esp32:" + body.uuid)), sweep_id, body.device_id, "esp32",
                             "pemilih.h@firmware", dd.choice, dumps(dd.scores or []), dumps([]), dd.latency_us,
                             "observe", 0, body.captured_at))
            expected = core.expected() if derived["pmax"] is not None and body.topology in protocol.TOPOLOGIES else None
            if expected and expected.get(body.topology):
                s = core.settings_dict()
                ph = expected[body.topology]
                dev = (derived["pmax"] - ph) / ph
                if abs(dev) * 100 > float(s.get("alert_threshold_pct", 15)):
                    msg = (f"Pmax {dev * 100:+.1f} % vs twin expectation for {body.topology} (assumed shading: "
                           f"{s.get('twin_shading', 'none')}). Indication only, not a validated diagnosis.")
                    ev = core.add_event(con, body.device_id, "alert", msg,
                                        {"sweep_id": sweep_id, "deviation_pct": round(dev * 100, 2), "expected_w": ph,
                                         "measured_w": derived["pmax"], "source": body.source, "label": TWIN_LABEL})
                    alerts.append({"kind": "alert", "message": msg})
                    events.append(ev)
        summary = core.sweep_summary(db.one(f"SELECT {SWEEP_COLS} FROM sweeps WHERE id=?", (sweep_id,)))
        core.hub.publish("sweep", summary, body.device_id)
        for ev in events:
            core.hub.publish("event", ev, body.device_id)
        return {"id": sweep_id, "uuid": body.uuid, "duplicate": False,
                "derived": {k: derived[k] for k in ("n_points", "voc", "isc", "pmax", "vmp", "imp")}, "alerts": alerts}

    @app.post(API + "/ingest/decisions", status_code=201, dependencies=write)
    def ingest_decision(body: M.DecisionIn, response: Response):
        """A selector decision made at the edge (gateway or ESP32). Idempotent by uuid."""
        with db.tx() as con:
            _require_device(con, body.device_id)
            dup = con.execute("SELECT id FROM decisions WHERE uuid=?", (body.uuid,)).fetchone()
            if dup:
                response.status_code = 200
                return {"id": dup["id"], "duplicate": True}
            sweep = con.execute("SELECT id FROM sweeps WHERE uuid=?", (body.sweep_uuid,)).fetchone()
            if not sweep:
                raise HTTPException(404, f"unknown sweep {body.sweep_uuid!r}: send the sweep first")
            cur = con.execute(
                "INSERT INTO decisions(uuid, sweep_id, device_id, decided_by, model_id, choice, scores_json, features_json, "
                "latency_us, trigger, applied, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (body.uuid, sweep["id"], body.device_id, body.decided_by, body.model_id, body.choice, dumps(body.scores),
                 dumps(body.features), body.latency_us, body.trigger, int(body.applied), body.created_at))
            row = con.execute("SELECT * FROM decisions WHERE id=?", (cur.lastrowid,)).fetchone()
        decision = core.decision_row(row)
        core.hub.publish("decision", decision, body.device_id)
        return {"id": decision["id"], "duplicate": False}

    @app.post(API + "/ingest/events", status_code=201, dependencies=write)
    def ingest_events(body: M.EventsIn):
        stored = []
        with db.tx() as con:
            for e in body.items:
                if e.device_id:
                    _require_device(con, e.device_id)
                stored.append(core.add_event(con, e.device_id, e.kind, e.message, e.data, e.created_at))
        for ev in stored:
            core.hub.publish("event", ev, ev["device_id"])
        return {"stored": len(stored)}

    @app.post(API + "/ingest/metrics", status_code=201, dependencies=write)
    def ingest_metrics(body: M.MetricsIn):
        """Timing metrics from gateways and manual entries from the dashboard (provenance is mandatory)."""
        with db.tx() as con:
            for m in body.items:
                if m.device_id:
                    _require_device(con, m.device_id)
                con.execute("INSERT INTO metrics(device_id, name, value, unit, provenance, data_json, at) VALUES (?,?,?,?,?,?,?)",
                            (m.device_id, m.name, m.value, m.unit, m.provenance, dumps(m.data), m.at or utc_now()))
        return {"stored": len(body.items)}

    @app.post(API + "/ingest/evaluations", status_code=201, dependencies=write)
    def ingest_evaluations(body: M.EvaluationsIn):
        """Decision audits: the three topologies swept after a decision, with the measured loss."""
        with db.tx() as con:
            for e in body.items:
                _require_device(con, e.device_id)
                decision_id = None
                if e.decision_uuid:
                    d = con.execute("SELECT id FROM decisions WHERE uuid=?", (e.decision_uuid,)).fetchone()
                    if not d:
                        raise HTTPException(404, f"unknown decision {e.decision_uuid!r}")
                    decision_id = d["id"]
                sweep_ids = []
                for su in e.sweep_uuids:
                    s = con.execute("SELECT id FROM sweeps WHERE uuid=?", (su,)).fetchone()
                    if not s:
                        raise HTTPException(404, f"unknown sweep {su!r}")
                    sweep_ids.append(s["id"])
                con.execute("INSERT INTO evaluations(decision_id, device_id, pmax_4s, pmax_2s2p, pmax_tct, sweep_ids_json, "
                            "best, chosen, loss_pct, source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (decision_id, e.device_id, e.pmax.get("4S"), e.pmax.get("2S2P"), e.pmax.get("TCT"),
                             dumps(sweep_ids), e.best, e.chosen, e.loss_pct, e.source, e.created_at or utc_now()))
        return {"stored": len(body.items)}

    @app.post(API + "/ingest/log", status_code=201, dependencies=write)
    def ingest_log(body: M.LogIn):
        """Serial log lines (rx = from the device, tx = sent to it)."""
        now = utc_now()
        with db.tx() as con:
            _require_device(con, body.device_id)
            con.executemany("INSERT INTO device_log(device_id, dir, line, at) VALUES (?,?,?,?)",
                            [(body.device_id, ln.dir, ln.line, ln.at or now) for ln in body.lines])
        return {"stored": len(body.lines)}

    # ======================= commands =======================
    @app.post(API + "/devices/{device_id}/commands", status_code=202, dependencies=write)
    def queue_command(device_id: str, body: M.CommandIn):
        """Queue a raw firmware command (allowlist) or a gateway action for this device."""
        try:
            if body.kind == "raw":
                command, params = commands.validate_raw(body.command), {}
            else:
                command, params = body.command, commands.validate_action(body.command, body.params)
        except commands.CommandError as e:
            raise HTTPException(400, str(e)) from None
        with db.tx() as con:
            _require_device(con, device_id)
            if con.execute("SELECT kind FROM devices WHERE id=?", (device_id,)).fetchone()["kind"] == "virtual":
                raise HTTPException(400, f"{device_id!r} is not a live device")
            cur = con.execute("INSERT INTO commands(device_id, kind, command, params_json, status, created_at) "
                              "VALUES (?,?,?,?,?,?)", (device_id, body.kind, command, dumps(params), "queued", utc_now()))
            cid = cur.lastrowid
            ev = core.add_event(con, device_id, "command", f"queued {body.kind}: {command}", {"command_id": cid, "params": params})
        core.wake_commands()
        core.hub.publish("command", {"id": cid, "status": "queued", "result": None, "command": command}, device_id)
        core.hub.publish("event", ev, device_id)
        return {"id": cid, "status": "queued", "command": command}

    @app.get(API + "/devices/{device_id}/commands/next", dependencies=write)
    def next_commands(device_id: str, wait: float = Query(5.0, ge=0, le=25)):
        """Gateway long-poll: returns queued commands (marking them sent) or an empty list after `wait` s."""
        deadline = time.monotonic() + wait
        while True:
            with db.tx() as con:
                rows = con.execute("SELECT id, kind, command, params_json, created_at FROM commands "
                                   "WHERE device_id=? AND status='queued' ORDER BY id", (device_id,)).fetchall()
                if rows:
                    now = utc_now()
                    con.executemany("UPDATE commands SET status='sent', sent_at=? WHERE id=?", [(now, r["id"]) for r in rows])
            if rows:
                out = [{"id": r["id"], "kind": r["kind"], "command": r["command"], "params": json.loads(r["params_json"]),
                        "created_at": r["created_at"]} for r in rows]
                for c in out:
                    core.hub.publish("command", {"id": c["id"], "status": "sent", "result": None}, device_id)
                return {"commands": out}
            remaining = deadline - time.monotonic()
            if remaining <= 0 or core._stop.is_set():
                return {"commands": []}
            with core._cmd_cond:
                core._cmd_cond.wait(min(remaining, 1.0))

    @app.post(API + "/commands/{command_id}/result", dependencies=write)
    def command_result(command_id: int, body: M.CommandResultIn):
        with db.tx() as con:
            c = con.execute("SELECT device_id, command FROM commands WHERE id=?", (command_id,)).fetchone()
            if not c:
                raise HTTPException(404, "unknown command")
            con.execute("UPDATE commands SET status=?, result=?, done_at=? WHERE id=?",
                        (body.status, body.result, utc_now(), command_id))
            ev = core.add_event(con, c["device_id"], "command" if body.status == "done" else "error",
                                f"{c['command']}: {body.status}" + (f" ({body.result})" if body.result else ""),
                                {"command_id": command_id})
        core.hub.publish("command", {"id": command_id, "status": body.status, "result": body.result}, c["device_id"])
        core.hub.publish("event", ev, c["device_id"])
        return {"id": command_id, "status": body.status}

    @app.get(API + "/devices/{device_id}/commands")
    def list_commands(device_id: str, limit: int = Query(20, ge=1, le=500)):
        rows = db.query("SELECT * FROM commands WHERE device_id=? ORDER BY id DESC LIMIT ?", (device_id, limit))
        for r in rows:
            r["params"] = json.loads(r.pop("params_json"))
        return rows

    # ======================= reads =======================
    def _summaries(where, args, limit, offset=0):
        rows = db.query(f"SELECT {SWEEP_COLS}, "
                        "(SELECT choice FROM decisions WHERE sweep_id=sweeps.id ORDER BY id DESC LIMIT 1) AS d_choice, "
                        "(SELECT decided_by FROM decisions WHERE sweep_id=sweeps.id ORDER BY id DESC LIMIT 1) AS d_by "
                        f"FROM sweeps WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
        return [core.sweep_summary(r) for r in rows]

    @app.get(API + "/sweeps")
    def sweeps(device_id: str | None = None, source: str | None = None, topology: str | None = None,
               condition: str | None = None, run_id: int | None = None, upload_id: int | None = None,
               since: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        clauses, args = [], []
        for col, val in (("device_id", device_id), ("source", source), ("topology", topology), ("condition", condition),
                         ("run_id", run_id), ("upload_id", upload_id)):
            if val is not None:
                clauses.append(f"{col}=?")
                args.append(val)
        if since:
            clauses.append("captured_at >= ?")
            args.append(since)
        return _summaries(" AND ".join(clauses) or "1=1", args, limit, offset)

    @app.get(API + "/sweeps/{sweep_id}")
    def sweep(sweep_id: int):
        d = core.sweep_full(sweep_id)
        if not d:
            raise HTTPException(404, "unknown sweep")
        return d

    @app.get(API + "/sweeps/{sweep_id}/csv", response_class=PlainTextResponse)
    def sweep_csv(sweep_id: int):
        """The sweep in the firmware/logger file format, ready to be uploaded again."""
        d = core.sweep_full(sweep_id)
        if not d:
            raise HTTPException(404, "unknown sweep")
        text = protocol.to_firmware_csv(d["label"], d["topology"], d["points"]["v"], d["points"]["i"], d["header"])
        return PlainTextResponse(text, media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{d["label"]}.csv"'})

    @app.get(API + "/conditions")
    def conditions(source: str = "lab"):
        """Replay index: {condition, repeats: {n: {topology: sweep id}}} for complete-or-not stored sweeps."""
        out = {}
        for r in db.query("SELECT id, condition, repeat, topology FROM sweeps WHERE source=? AND condition IS NOT NULL "
                          "ORDER BY id", (source,)):
            out.setdefault(r["condition"], {}).setdefault(str(r["repeat"] or 0), {})[r["topology"]] = r["id"]
        return [{"condition": c, "repeats": reps} for c, reps in sorted(out.items())]

    @app.get(API + "/decisions")
    def decisions(device_id: str | None = None, decided_by: str | None = None, limit: int = Query(50, ge=1, le=1000)):
        rows = db.query("SELECT * FROM decisions WHERE (? IS NULL OR device_id=?) AND (? IS NULL OR decided_by=?) "
                        "ORDER BY id DESC LIMIT ?", (device_id, device_id, decided_by, decided_by, limit))
        return [core.decision_row(r) for r in rows]

    @app.get(API + "/evaluations")
    def evaluations(device_id: str | None = None, limit: int = Query(50, ge=1, le=1000)):
        rows = db.query("SELECT * FROM evaluations WHERE (? IS NULL OR device_id=?) ORDER BY id DESC LIMIT ?",
                        (device_id, device_id, limit))
        return [{"id": r["id"], "decision_id": r["decision_id"], "device_id": r["device_id"],
                 "pmax": {"4S": r["pmax_4s"], "2S2P": r["pmax_2s2p"], "TCT": r["pmax_tct"]},
                 "sweep_ids": json.loads(r["sweep_ids_json"]), "best": r["best"], "chosen": r["chosen"],
                 "loss_pct": r["loss_pct"], "source": r["source"], "created_at": r["created_at"]} for r in rows]

    def _events(device_id, kind, since, limit):
        rows = db.query("SELECT * FROM events WHERE (? IS NULL OR device_id=?) AND (? IS NULL OR kind=?) "
                        "AND (? IS NULL OR created_at >= ?) ORDER BY id DESC LIMIT ?",
                        (device_id, device_id, kind, kind, since, since, limit))
        for r in rows:
            r["data"] = json.loads(r.pop("data_json"))
        return rows

    @app.get(API + "/events")
    def events(device_id: str | None = None, kind: str | None = None, since: str | None = None,
               limit: int = Query(100, ge=1, le=5000)):
        return _events(device_id, kind, since, limit)

    @app.get(API + "/events.csv", response_class=PlainTextResponse)
    def events_csv(device_id: str | None = None, since: str | None = None):
        """Audit trail as CSV (commands, switches, decisions' alerts, errors, status changes)."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["created_at", "device_id", "kind", "message", "data"])
        for r in reversed(_events(device_id, None, since, 100_000)):
            w.writerow([r["created_at"], r["device_id"] or "", r["kind"], r["message"], dumps(r["data"])])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="shadeshift_events.csv"'})

    @app.get(API + "/devices/{device_id}/log")
    def device_log(device_id: str, after_id: int = 0, limit: int = Query(200, ge=1, le=5000)):
        return db.query("SELECT id, at, dir, line FROM device_log WHERE device_id=? AND id > ? ORDER BY id DESC LIMIT ?",
                        (device_id, after_id, limit))[::-1]

    @app.get(API + "/metrics/summary")
    def metrics_summary(device_id: str | None = None, since: str | None = None):
        rows = db.query("SELECT name, value, unit, provenance FROM metrics WHERE (? IS NULL OR device_id=?) "
                        "AND (? IS NULL OR at >= ?)", (device_id, device_id, since, since))
        out = {}
        for name in sorted({r["name"] for r in rows}):
            vals = np.array([r["value"] for r in rows if r["name"] == name], dtype=float)
            out[name] = {"n": int(len(vals)), "mean": round(float(vals.mean()), 3),
                         "p50": round(float(np.percentile(vals, 50)), 3), "p95": round(float(np.percentile(vals, 95)), 3),
                         "max": round(float(vals.max()), 3),
                         "unit": next(r["unit"] for r in rows if r["name"] == name),
                         "provenance": sorted({r["provenance"] for r in rows if r["name"] == name})}
        return out

    @app.get(API + "/uploads")
    def uploads(limit: int = Query(100, ge=1, le=1000)):
        return db.query("SELECT * FROM uploads ORDER BY id DESC LIMIT ?", (limit,))

    @app.get(API + "/scenarios")
    def scenarios():
        """Demo scenarios available in scenarios/*.json (Stage 4)."""
        folder = cfg.ROOT / "scenarios"
        out = []
        for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            timeline = s.get("timeline", [])
            out.append({"name": s.get("name", p.stem), "description": s.get("description", ""), "label": s.get("label", ""),
                        "duration_s": max((t.get("at_s", 0) for t in timeline), default=0),
                        "conditions": [t.get("condition") for t in timeline]})
        return out

    @app.get(API + "/devices/{device_id}/snapshot")
    def snapshot(device_id: str, n_recent: int = Query(30, ge=1, le=200)):
        """Everything the live dashboard page needs, in one call."""
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        latest = {}
        for t in protocol.TOPOLOGIES:
            r = db.one("SELECT id FROM sweeps WHERE device_id=? AND topology=? ORDER BY id DESC LIMIT 1", (device_id, t))
            if r:
                latest[t] = core.sweep_full(r["id"])
        dec = db.one("SELECT * FROM decisions WHERE device_id=? ORDER BY id DESC LIMIT 1", (device_id,))
        return {"device": d, "latest_by_topology": latest,
                "recent_sweeps": _summaries("device_id=?", (device_id,), n_recent),
                "latest_decision": core.decision_row(dec) if dec else None,
                "recent_events": _events(device_id, None, None, 20),
                "log_tail": device_log(device_id, 0, 60),
                "settings": core.settings_dict(), "expected": core.expected()}

    # ======================= uploads and lab import =======================
    def _new_run(con, device_id, source, meta):
        cur = con.execute("INSERT INTO runs(uuid, device_id, source, started_at, ended_at, meta_json) VALUES (?,?,?,?,?,?)",
                          (str(uuidlib.uuid4()), device_id, source, utc_now(), utc_now(), dumps(meta)))
        return cur.lastrowid

    @app.post(API + "/uploads", dependencies=write)
    async def upload(files: list[UploadFile] = File(...), device_id: str = Form("upload"),
                     topology: str | None = Form(None), condition: str | None = Form(None)):
        """Upload sweep CSV files (firmware/logger format or plain V,I). Each file is accepted or rejected."""
        if len(files) > csv_import.MAX_FILES:
            raise HTTPException(413, f"at most {csv_import.MAX_FILES} files per request")
        if topology is not None and topology not in protocol.TOPOLOGIES:
            raise HTTPException(400, f"topology must be one of {list(protocol.TOPOLOGIES)}")
        if not M.valid_device_id(device_id) or device_id == "lab":
            raise HTTPException(400, "invalid device_id for uploads")
        payloads = []
        for f in files:
            data = await f.read(csv_import.MAX_FILE_BYTES + 1)
            payloads.append((f.filename or "upload.csv", data))
        return await asyncio.to_thread(_store_uploads, payloads, device_id, topology, condition)

    def _store_uploads(payloads, device_id, topology, condition):
        results = []
        with db.tx() as con:
            if device_id in RESERVED_DEVICES or not con.execute("SELECT 1 FROM devices WHERE id=?", (device_id,)).fetchone():
                core.ensure_virtual_device(con, device_id)
            run_id = _new_run(con, device_id, "upload", {"files": [p[0] for p in payloads]})
            for filename, data in payloads:
                sha = hashlib.sha256(data).hexdigest()
                prior = con.execute("SELECT id, status, error FROM uploads WHERE sha256=?", (sha,)).fetchone()
                if prior:
                    ids = [r["id"] for r in con.execute("SELECT id FROM sweeps WHERE upload_id=?", (prior["id"],))]
                    results.append({"filename": filename, "status": "duplicate" if prior["status"] == "ok" else "rejected",
                                    "upload_id": prior["id"], "sweep_ids": ids, "error": prior["error"]})
                    continue
                try:
                    parsed = csv_import.parse_file(filename, data, topology=topology, condition=condition)
                except csv_import.Rejected as e:
                    cur = con.execute("INSERT INTO uploads(filename, sha256, size_bytes, uploaded_at, status, n_sweeps, error) "
                                      "VALUES (?,?,?,?,?,?,?)", (filename, sha, len(data), utc_now(), "rejected", 0, str(e)))
                    results.append({"filename": filename, "status": "rejected", "upload_id": cur.lastrowid, "error": str(e)})
                    continue
                cur = con.execute("INSERT INTO uploads(filename, sha256, size_bytes, uploaded_at, status, n_sweeps) "
                                  "VALUES (?,?,?,?,?,?)", (filename, sha, len(data), utc_now(), "ok", len(parsed)))
                upload_id = cur.lastrowid
                sweeps_out = []
                for k, fs in enumerate(parsed):
                    p = fs.parsed
                    sid, derived = core.store_sweep(
                        con, uuid=str(uuidlib.uuid5(UUID_NS, f"upload:{sha}:{k}")), device_id=device_id, run_id=run_id,
                        upload_id=upload_id, source="upload", label=p.label, topology=fs.topology, condition=fs.condition,
                        repeat=fs.repeat, captured_at=utc_now(), v=p.v, i=p.i, header=p.header, device_meta=p.device_meta,
                        complete=p.complete, timing={}, replay_of=None, raw_text=p.raw_text)
                    decision = core.server_decision(con, sid, device_id, p.v, p.i, "upload") if fs.topology == "4S" else None
                    sweeps_out.append({"id": sid, "label": p.label, "topology": fs.topology, "pmax": derived["pmax"],
                                       "complete": p.complete, "decision": decision})
                results.append({"filename": filename, "status": "ok", "upload_id": upload_id, "sweeps": sweeps_out})
            core.add_event(con, device_id, "info", f"upload: {sum(r['status'] == 'ok' for r in results)} accepted, "
                                                   f"{sum(r['status'] == 'rejected' for r in results)} rejected, "
                                                   f"{sum(r['status'] == 'duplicate' for r in results)} duplicate")
        return {"results": results}

    @app.post(API + "/import/lab", dependencies=write)
    def import_lab(body: M.LabImportIn | None = None):
        """Import the halogen-lamp lab curves (read-only) as source=lab. Idempotent by file content."""
        body = body or M.LabImportIn()
        lab = Path(settings.lab_dir)
        if not lab.is_dir():
            raise HTTPException(503, f"lab data folder not found: {lab}")
        files = sorted(lab.glob("*.csv"))
        if body.include_anomalies:
            files += sorted(p for sub in ("_V5_anomali_dioda", "_V1d_gagal_R1") for p in (lab / sub).glob("*.csv"))
        imported = skipped = 0
        with db.tx() as con:
            core.ensure_virtual_device(con, "lab")
            run_id = _new_run(con, "lab", "lab", {"folder": str(lab), "include_anomalies": body.include_anomalies})
            for path in files:
                data = path.read_bytes()
                uid = str(uuidlib.uuid5(UUID_NS, "lab:" + hashlib.sha256(data).hexdigest()))
                if con.execute("SELECT 1 FROM sweeps WHERE uuid=?", (uid,)).fetchone():
                    skipped += 1
                    continue
                fs = csv_import.parse_file(path.name, data)[0]
                p = fs.parsed
                sid, _ = core.store_sweep(
                    con, uuid=uid, device_id="lab", run_id=run_id, upload_id=None, source="lab", label=path.stem,
                    topology=fs.topology, condition=fs.condition, repeat=fs.repeat, captured_at=utc_now(), v=p.v, i=p.i,
                    header=p.header, device_meta={}, complete=p.complete, timing={}, replay_of=path.name, raw_text=None)
                if fs.topology == "4S":
                    core.server_decision(con, sid, "lab", p.v, p.i, "replay")
                imported += 1
            core.add_event(con, "lab", "info", f"lab import: {imported} imported, {skipped} already present")
        return {"imported": imported, "skipped_duplicates": skipped}

    # ======================= digital twin =======================
    def _twin_or_503():
        if not core.twin.available:
            raise HTTPException(503, f"twin unavailable: {core.twin.reason}")

    @app.get(API + "/twin/expected")
    def twin_expected(scale: float = Query(1.0, ge=0.05, le=4.0), shading: M.Shading = "none"):
        _twin_or_503()
        return {"available": True, "scale": scale, "shading": shading,
                "pmax": core.twin.expected(scale, shading), "label": TWIN_LABEL}

    @app.get(API + "/twin/curve")
    def twin_curve(topology: str, voc_max: float = Query(..., gt=0, le=200), scale: float = Query(1.0, ge=0.05, le=4.0),
                   shading: M.Shading = "none"):
        _twin_or_503()
        if topology not in protocol.TOPOLOGIES:
            raise HTTPException(400, "unknown topology")
        V, I = core.twin.curve(topology, voc_max, scale, shading)
        return {"v": [round(float(x), 5) for x in V], "i": [round(float(x), 7) for x in I], "label": TWIN_LABEL}

    @app.post(API + "/twin/calibrate", dependencies=write)
    def twin_calibrate(body: M.CalibrateIn):
        """Set the light scale from an UNSHADED sweep so the twin's Pmax equals the measured Pmax."""
        _twin_or_503()
        d = core.sweep_full(body.sweep_id)
        if not d:
            raise HTTPException(404, "unknown sweep")
        if d["topology"] not in protocol.TOPOLOGIES:
            raise HTTPException(400, "sweep topology unknown")
        scale = round(core.twin.calibrate(d["points"]["v"], d["points"]["i"], d["topology"], d["header"].get("voc")), 4)
        scale = min(4.0, max(0.05, scale))
        put_settings(M.SettingsIn(twin_scale=scale))
        return {"scale": scale}

    # ======================= live stream =======================
    @app.websocket(API + "/stream")
    async def stream(ws: WebSocket, device_id: str | None = None):
        await ws.accept()
        client = core.hub.subscribe(device_id)
        try:
            await ws.send_json({"type": "hello", "server_time": utc_now(), "schema_version": SCHEMA_VERSION})
            queue = client[0]
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    msg = {"type": "ping"}
                await ws.send_json(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            core.hub.unsubscribe(client)

    return app


def main(settings=None):
    """Entry point used by run.py."""
    import uvicorn
    settings = settings or cfg.load()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.host not in ("127.0.0.1", "localhost") and not settings.api_token:
        raise SystemExit("Refusing to listen on a non-local address without SHADESHIFT_API_TOKEN (CONTRACT §5.1).")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.api_port, log_level=settings.log_level.lower())
