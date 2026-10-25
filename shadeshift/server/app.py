"""ShadeShift local server: FastAPI + SQLite (docs/CONTRACT.md §5). Start with:  python run.py server

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
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from shadeshift import __version__, commands, config as cfg, evaluation, fieldwork, inti, protocol
from shadeshift.edge.selector import CLASSES, FEATURE_NAMES, EdgeSelector, weights_sha256
from shadeshift.server import csv_import, models as M
from shadeshift.server.db import SCHEMA_VERSION, Database, dumps, utc_now
from shadeshift.server.hub import Hub
from shadeshift.server.twin import LABEL as TWIN_LABEL, SHADINGS, Twin

log = logging.getLogger("shadeshift.server")
STATIC = Path(__file__).resolve().parent / "static"          # the Digital Twin page (docs/CONTRACT.md §18)
API = "/api/v1"
UUID_NS = uuidlib.UUID("6a3f1d2e-9b8c-4c1a-8e7f-2d4b5c6a7e80")     # deterministic ids for uploads and lab imports
RESERVED_DEVICES = {"upload": "virtual", "lab": "virtual"}
KIND_SOURCE = {"esp32": "device", "emulator": "demo"}         # provenance follows the device kind (CONTRACT §5.2)
ACTUATING_TTL_S, OTHER_TTL_S, SENT_TTL_S, RUN_IDLE_S, LOG_KEEP = 10, 60, 120, 60, 5000
SELECTOR_MAX_POINTS, UPLOAD_MAX_POINTS = 1000, 250_000
MODEL_CLAIMS = {
    "lab": "lab (halogen lamp, 30 sets, 6 patterns): selector loss 0.82 % vs 2.71 % for the best fixed topology (2S2P), "
           "among 4S/2S2P/TCT; 4P is excluded by the 24 V window (it measured highest in all 30 lab sets)",
    "sim": "sim (12,000 synthetic scenarios): 3.00 vs 6.35 points of ideal-MLPE power for fixed TCT; "
           "accuracy 68.9 %, balanced accuracy 47.5 %",
    "trigger_rule": "sim (36 synthetic moving-shade scenarios, with the ~3 s power cut of each monitor sweep): auto mode "
                    "monitoring every 10 s loses to fixed TCT in all 36; every 5 min it roughly ties fixed TCT (+1.2 / +0.2 / "
                    "-1.0 points for moving / mixed / leaf shade). Without the sweep cost (older research run) the 20 % "
                    "trigger beat fixed TCT on average",
    "edge": "L2: the selector runs on the laptop gateway next to the device (ONNX Runtime); on the ESP32 it is a "
            "Foundation (firmware v3, not yet run on the board)",
}


def source_of_kind(kind):
    return KIND_SOURCE.get(kind, "server")
SWEEP_COLS = ("id, uuid, device_id, run_id, upload_id, source, label, topology, condition, repeat, captured_at, "
              "received_at, n_points, complete, voc, isc, pmax, vmp, imp, sweep_ms, switch_ms, replay_of, scan_id")
SCAN_STATUS = {"done": "done", "failed": "failed", "expired": "failed"}


def _sent_ttl_s(c):
    """How long a sent command may run before 'no result from gateway'. A full scan reports only at its end:
    allow 20 s per sweep (switch + sweep take ~4-5 s) plus its pauses."""
    if c["command"] != "full_scan":
        return SENT_TTL_S
    p = json.loads(c["params_json"] or "{}")
    rounds = int(p.get("rounds", 1))
    n = rounds * len(fieldwork.scan_targets(p.get("panels")))
    return SENT_TTL_S + 20 * n + (rounds - 1) * float(p.get("pause_s", 0))


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
        self.selector = EdgeSelector(role="server", runtime=settings.edge_runtime, model_path=settings.model_path)
        self.hub = Hub()
        self._lab_examples = None                       # training features of the lab files (computed once)
        self._model_cache = {}                          # (task, model_id) -> loaded model, for the live diagnosis
        from shadeshift.training.export import selector_paths
        self.selector_paths = selector_paths()          # files a selector activation rewrites (tests point elsewhere)
        self._cmd_cond = threading.Condition()
        self._stop = threading.Event()
        self._perawatan_cache = {}                      # device -> (key, time, result): predictive maintenance, at most once a minute
        from shadeshift.ai_teks import Penulis
        self.penulis = Penulis(settings.gemini_api_key, settings.gemini_model)    # optional rewording (CONTRACT §27)

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
        d["source"] = source_of_kind(d["kind"])
        return d

    def device_kind(self, con, device_id):
        r = con.execute("SELECT kind FROM devices WHERE id=?", (device_id,)).fetchone()
        if not r:
            raise HTTPException(404, f"unknown device {device_id!r}: send a heartbeat first")
        return r["kind"]

    def expected(self, shading=None):
        """{topology: expected Pmax} from the twin; shading None = the stored setting, "none" = unshaded (consumer view)."""
        if not self.twin.available:
            return None
        s = self.settings_dict()
        try:
            return self.twin.expected(s.get("twin_scale", 1.0), shading or s.get("twin_shading", "none"))
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
        dk = con.execute("SELECT kind FROM devices WHERE id=?", (device_id,)).fetchone() if device_id else None
        return {"device_id": device_id, "kind": kind, "message": message, "data": data or {},
                "created_at": created_at or utc_now(), "source": source_of_kind(dk["kind"] if dk else None)}

    # ---------- storing sweeps (shared by ingest, uploads, lab import) ----------
    def store_sweep(self, con, *, uuid, device_id, run_id, upload_id, source, label, topology, condition, repeat,
                    captured_at, v, i, header, device_meta, complete, timing, replay_of, raw_text, scan_id=None):
        derived = protocol.derive(v, i, header.get("voc"))
        cur = con.execute(
            "INSERT INTO sweeps(uuid, device_id, run_id, upload_id, source, label, topology, condition, repeat, "
            "captured_at, received_at, n_points, complete, voc, isc, pmax, vmp, imp, header_json, device_meta_json, "
            "sweep_ms, switch_ms, points_json, raw_text, replay_of, scan_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid, device_id, run_id, upload_id, source, label, topology, condition, repeat, captured_at, utc_now(),
             derived["n_points"], int(bool(complete)), derived["voc"], derived["isc"], derived["pmax"], derived["vmp"],
             derived["imp"], dumps(header), dumps(device_meta), timing.get("sweep_ms"), timing.get("switch_ms"),
             dumps({"v": list(v), "i": list(i)}), raw_text, replay_of, scan_id))
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

    # ---------- data-collection sessions and scans (CONTRACT §12) ----------
    def sync_scan(self, con, command_id, status, result):
        """A full scan follows its gateway command: done / failed / stopped (stop, or superseded by stop)."""
        new = ("stopped" if status == "failed" and (result or "").startswith(("stopped", "superseded"))
               else SCAN_STATUS.get(status))
        if new:
            con.execute("UPDATE scans SET status=?, result=?, ended_at=? WHERE command_id=? AND status IN ('queued','running')",
                        (new, result or status, utc_now(), command_id))

    @staticmethod
    def scan_row(r):
        d = dict(r)
        d["temps"] = json.loads(d.pop("temps_json") or "{}")
        d["dynamic"], d["with_panels"] = bool(d["dynamic"]), bool(d["with_panels"])
        return d

    def scan_sweeps(self, scan_id, full=False):
        extra = ", points_json, raw_text" if full else ""
        rows = self.db.query(f"SELECT {SWEEP_COLS}, header_json{extra} FROM sweeps WHERE scan_id=? ORDER BY id", (scan_id,))
        for r in rows:
            r["complete"] = bool(r["complete"])
            r["header"] = json.loads(r.pop("header_json"))
            if full:
                r["points"] = json.loads(r.pop("points_json"))
        return rows

    def scan_detail(self, scan_id, full=False):
        r = self.db.one("SELECT * FROM scans WHERE id=?", (scan_id,))
        if not r:
            return None
        sc = self.scan_row(r)
        sweeps = self.scan_sweeps(scan_id, full)
        sc["n_expected"] = sc["rounds"] * len(fieldwork.scan_targets(sc["with_panels"]))
        sc["n_sweeps"] = len(sweeps)
        sc["quality"] = fieldwork.scan_quality(sc, sweeps)
        sc["sweeps"] = sweeps
        return sc

    def session_detail(self, session_id, full=False):
        s = self.db.one("SELECT * FROM sessions WHERE id=?", (session_id,))
        if not s:
            return None
        scans = [self.scan_detail(r["id"], full) for r in self.db.query(
            "SELECT id FROM scans WHERE session_id=? ORDER BY id", (session_id,))]
        a1 = [sc for sc in scans if sc["code"] == "A1" and sc["sweeps"]]

        def mean_pmax(sc):
            out = {}
            for t in protocol.TOPOLOGIES:
                p = [w["pmax"] for w in sc["sweeps"] if w["topology"] == t and w["complete"] and w["pmax"]]
                if p:
                    out[t] = sum(p) / len(p)
            return out
        s["a1_drift"] = (fieldwork.a1_drift(mean_pmax(a1[0]), mean_pmax(a1[-1])) if len(a1) >= 2 else
                         fieldwork.a1_drift({}, {}))
        s["scans"] = scans
        return s

    # ---------- proving the targets (CONTRACT §13) ----------
    def round_decision(self, sweep_id):
        """The AI's choice on a 4S sweep: the ESP32's own '# pemilih=' line when firmware v3 printed one, else the same
        selector on this server. Returns (choice, decided_by) or (None, None)."""
        r = self.db.one("SELECT points_json, raw_text FROM sweeps WHERE id=?", (sweep_id,))
        if not r:
            return None, None
        if r["raw_text"]:
            dd = protocol.parse_block(r["raw_text"].splitlines()).device_decision
            if dd:
                return dd["choice"], "esp32"
        pts = json.loads(r["points_json"])
        d = self.selector.decide(pts["v"], pts["i"])
        return (d.choice, d.decided_by) if d else (None, None)

    def evidence_rounds(self, source="device", session_id=None):
        """Every round of every full scan (and every live decision audit) as one comparison of the AI with the fixed
        topologies. Dynamic conditions and rounds whose light changed > 5 % are kept but not used in the summary."""
        rounds = []
        scans = self.db.query("SELECT sc.*, se.place FROM scans sc JOIN sessions se ON se.id = sc.session_id "
                              "WHERE se.source=? AND (? IS NULL OR sc.session_id=?) ORDER BY sc.id",
                              (source, session_id, session_id))
        for sc in scans:
            by_rep = {}
            for w in self.scan_sweeps(sc["id"]):
                by_rep.setdefault(w["repeat"], {})[w["topology"]] = w
            for rep_no, by_t in sorted(by_rep.items()):
                s4 = by_t.get("4S")
                choice, by = self.round_decision(s4["id"]) if s4 and s4["complete"] else (None, None)
                m = evaluation.round_metrics(by_t, choice, by)
                light = evaluation.light_change_pct(list(by_t.values()))
                if m["usable"] and sc["dynamic"]:
                    m.update(usable=False, reason="dynamic condition (moving shade): sweeps of one round see different shade")
                elif m["usable"] and light is not None and light > fieldwork.LIGHT_CHANGE_PCT:
                    m.update(usable=False, reason=f"light changed {light:.1f} % during the round")
                m.update(kind="scan", scan_id=sc["id"], session_id=sc["session_id"], code=sc["code"],
                         condition=sc["condition"], diagnosis=sc["diagnosis"], modules=sc["modules"], repeat=rep_no,
                         place=sc["place"], light_change_pct=round(light, 2) if light is not None else None,
                         at=(s4 or next(iter(by_t.values())))["captured_at"])
                rounds.append(m)
        if session_id is None:
            for e in self.db.query("SELECT e.*, d.decided_by FROM evaluations e LEFT JOIN decisions d ON d.id = e.decision_id "
                                   "WHERE e.source=? ORDER BY e.id", (source,)):
                by_t = {t: {"pmax": e[c], "complete": True} for t, c in
                        (("4S", "pmax_4s"), ("2S2P", "pmax_2s2p"), ("TCT", "pmax_tct"), ("4P", "pmax_4p")) if e[c]}
                by_t.update({k: {"pmax": v, "complete": True} for k, v in json.loads(e["pmax_panels_json"] or "{}").items()})
                m = evaluation.round_metrics(by_t, e["chosen"], e["decided_by"])
                m.update(kind="audit", evaluation_id=e["id"], code=None, condition=None, diagnosis=None, modules=None,
                         repeat=None, place=None, light_change_pct=None, at=e["created_at"])
                rounds.append(m)
        return rounds

    def power_entries(self):
        """Multimeter entries: control power = ESP32 (device_power_w) + relays (relay_power_w) of one entry (same data.entry)."""
        entries = {}
        for r in self.db.query("SELECT name, value, data_json, at FROM metrics WHERE name IN ('device_power_w', "
                               "'relay_power_w') AND provenance='manual' ORDER BY id"):
            data = json.loads(r["data_json"])
            e = entries.setdefault(data.get("entry") or r["at"], {"at": r["at"], "topology": data.get("topology")})
            e[r["name"]] = r["value"]
        return [{"value": round(e.get("device_power_w", 0) + e.get("relay_power_w", 0), 4), **e} for e in entries.values()
                if "device_power_w" in e and "relay_power_w" in e]

    def evidence(self, source="device"):
        """The four proposal targets next to the evidence for each, every number labeled with where it comes from."""
        rounds = self.evidence_rounds(source)
        summ = evaluation.summarize(rounds)
        mlpe, rel = summ["mlpe"], summ["relative"]
        targets = []

        ev = []
        if mlpe:
            ev.append({"value": mlpe["recovery_pts"], "unit": "points", "source": "measured", "n": mlpe["n"],
                       "detail": f"AI {mlpe['ai_pct']:.1f} % of MLPE vs best fixed {mlpe['best_fixed']} "
                                 f"{mlpe['best_fixed_pct']:.1f} % ({mlpe['n']} rounds with single-panel sweeps)"})
        if rel:
            ev.append({"value": rel["ai_loss_pct"], "unit": "% loss", "source": "measured", "n": rel["n"],
                       "detail": f"AI loss {rel['ai_loss_pct']:.2f} % vs best fixed {rel['best_fixed']} "
                                 f"{rel['best_fixed_loss_pct']:.2f} % of the measured best (no MLPE needed)"})
        ev.append({"value": 0.82, "unit": "% loss", "source": "lab", "n": 30, "detail": MODEL_CLAIMS["lab"]})
        ev.append({"value": 3.35, "unit": "points", "source": "sim", "n": None,
                   "detail": "simulation: selector loses 3.00 points of MLPE power, fixed TCT 6.35, so 3.35 points recovered"})
        targets.append({"id": "recovery", "target": "Recover >= 4 points of ideal-MLPE power vs the best fixed topology",
                        "status": ("met" if mlpe["met"] else "not met") if mlpe else "no measurement yet",
                        "needs": None if mlpe else "full scans with single-panel sweeps (firmware 3.2)",
                        "evidence": ev})

        labeled = self.db.query("SELECT sc.diagnosis, se.place, count(w.id) AS n FROM scans sc JOIN sessions se "
                                "ON se.id = sc.session_id JOIN sweeps w ON w.scan_id = sc.id WHERE se.source=? AND w.complete=1 "
                                "GROUP BY sc.diagnosis, se.place", (source,))
        n_out = sum(r["n"] for r in labeled if r["place"] == "outdoor_sun")
        act = self._active_model("diagnosis")
        measured, status = [], "no measurement yet"
        needs = "labeled outdoor sessions on at least two days, then training and a test on a held-out day (Model AI page)"
        if act and act["evidence"] == "real":
            held_out = (act["test_mode"] or "").startswith("held-out day")
            if act["accuracy_outdoor"] is not None:
                status = "met" if act["accuracy_outdoor"] >= 85 and held_out else "not met"
                needs = None if held_out else "a test on a held-out day (needs real data from a second day)"
            else:
                needs = "outdoor rounds in the test data"
            measured.append({"value": act["accuracy_outdoor"] if act["accuracy_outdoor"] is not None else act["accuracy"],
                             "unit": "% accuracy" + (" (outdoor)" if act["accuracy_outdoor"] is not None else " (indoor)"),
                             "source": "measured", "n": act["n_test_outdoor"] or act["n_test"],
                             "detail": f"active model {act['model_id']}: {act['test_mode']}; all test rounds "
                                       f"{act['accuracy']} %, balanced {act['balanced_accuracy']} %"})
        targets.append({"id": "diagnosis", "target": "Diagnose the cause (6 classes) with >= 85 % accuracy on outdoor test data",
                        "status": status, "needs": needs,
                        "evidence": measured + [{"value": "78-82", "unit": "% accuracy", "source": "sim", "n": 9000,
                                      "detail": "simulation only: 78-82 % with 4 cross-topology sweeps; fails on lab data"},
                                     {"value": n_out, "unit": "labeled outdoor curves", "source": "measured", "n": None,
                                      "detail": "data collected so far: " + (", ".join(
                                          f"{fieldwork.DIAGNOSIS.get(r['diagnosis'], 'unlabeled')} "
                                          f"({'outdoor' if r['place'] == 'outdoor_sun' else 'indoor'}) {r['n']}"
                                          for r in labeled) or "none") + "; protocol goal ~360 curves"}]})

        power = self.power_entries()
        ev = [{"value": e["value"], "unit": "W", "source": "measured", "n": 1,
               "detail": f"ESP32 {e['device_power_w']:.3f} W + relays {e['relay_power_w']:.3f} W"
                         f"{' with ' + e['topology'] + ' active' if e.get('topology') else ''} (multimeter, {e['at'][:10]})"}
              for e in power]
        ev += [{"value": 1.43, "unit": "W", "source": "calc", "n": None,
                "detail": "relay matrix holding power, lowest topology (calculation; 1.43-2.50 W)"},
               {"value": 0.13, "unit": "W", "source": "calc", "n": None,
                "detail": "semiconductor switch design (L3), 0.13-0.23 W (calculation, not built)"}]
        targets.append({"id": "power", "target": "Control power <= 0.25 W",
                        "status": ("met" if min(r["value"] for r in power) <= 0.25 else "not met") if power
                        else "no measurement yet",
                        "needs": None if power else "measure ESP32 + relays with the multimeter and enter it below",
                        "evidence": ev})

        rows = self.db.query("SELECT value, data_json FROM metrics WHERE name='decision_us'")
        by_rt = {}
        for r in rows:
            by_rt.setdefault(json.loads(r["data_json"]).get("runtime", "?"), []).append(r["value"])
        ev = [{"value": round(float(np.percentile(v, 95)) / 1000, 3), "unit": "ms (p95)", "n": len(v),
               "source": "measured" if rt == "esp32" else "measured (laptop)",
               "detail": f"{'on the ESP32 (firmware v3)' if rt == 'esp32' else 'on the laptop gateway (' + rt + ')'}: "
                         f"median {np.median(v) / 1000:.3f} ms"} for rt, v in sorted(by_rt.items())]
        e2e = self.db.query("SELECT value FROM metrics WHERE name='e2e_decision_ms'")
        if e2e:
            v = [r["value"] for r in e2e]
            ev.append({"value": round(float(np.percentile(v, 95)), 1), "unit": "ms (p95)", "n": len(v), "source": "measured (laptop)",
                       "detail": "end of the 4S sweep to the switch command sent (decision + overhead)"})
        esp = by_rt.get("esp32")
        targets.append({"id": "latency", "target": "Topology decision on the ESP32 within milliseconds (< 1 s)",
                        "status": ("met" if np.percentile(esp, 95) < 1e6 else "not met") if esp else "no measurement yet",
                        "needs": None if esp else "firmware v3 on the board (the ESP32 prints t_us with every decision)",
                        "evidence": ev})
        return {"targets": targets, "summary": summ, "source": source,
                "rounds_used": summ["n_rounds"], "rounds_total": len(rounds)}

    # ---------- Bukti page (CONTRACT §24) ----------
    def trial_runs(self):
        """Gateway runs of a real ESP32 with the five checks of a full trial: on-board AI active (firmware 3.x, same
        weights), an array sweep, an ESP32 recommendation, a round of all four panels, a confirmed stop."""
        from datetime import timedelta
        from shadeshift import kondisi
        out = []
        for r in self.db.query("SELECT r.id, r.device_id, r.started_at, r.ended_at, r.meta_json FROM runs r JOIN devices d "
                               "ON d.id = r.device_id WHERE d.kind = 'esp32' AND r.source = 'device' ORDER BY r.id"):
            end = r["ended_at"] or utc_now()
            # the board answers INFO while the gateway connects, a moment before its first heartbeat creates the run
            early = (datetime.fromisoformat(r["started_at"].replace("Z", "+00:00")) - timedelta(seconds=30)).isoformat(
                timespec="milliseconds").replace("+00:00", "Z")
            esp = (json.loads(r["meta_json"] or "{}").get("gateway") or {}).get("esp32") or {}
            sw = self.db.query("SELECT id, topology, captured_at, pmax, isc, voc FROM sweeps WHERE run_id=? AND complete=1",
                               (r["id"],))

            def event(pattern, since=r["started_at"]):
                return self.db.one("SELECT 1 FROM events WHERE device_id=? AND created_at >= ? AND created_at <= ? AND "
                                   "message LIKE ? LIMIT 1", (r["device_id"], since, end, pattern)) is not None
            ids = [s["id"] for s in sw if s["topology"] in protocol.TOPOLOGIES]
            ai = bool(ids) and self.db.one(f"SELECT 1 FROM decisions WHERE decided_by='esp32' AND sweep_id IN "
                                           f"({','.join('?' * len(ids))}) LIMIT 1", ids) is not None
            out.append({"run_id": r["id"], "device_id": r["device_id"], "started_at": r["started_at"], "checks": {
                "firmware": bool(esp.get("weights_match")) or event("ESP32 firmware 3.%on-board AI active%", early),
                "susunan": bool(ids), "ai": ai,
                "panel": bool(kondisi.rounds([s for s in sw if s["topology"] in protocol.PANELS])),
                "stop": event("stop: tasks cancelled, device confirmed all relays open")}})
        return out

    def bukti_facts(self):
        """Facts for the Bukti page, from real ESP32 data only (source 'device')."""
        def lat(where):
            v = sorted(r["latency_us"] for r in self.db.query(
                f"SELECT d.latency_us FROM decisions d JOIN sweeps s ON s.id = d.sweep_id WHERE s.source='device' AND "
                f"d.latency_us IS NOT NULL AND {where}"))
            return {"n": len(v), "median_us": float(np.median(v)) if v else None, "max_us": max(v) if v else None}
        devs = [self.device_row(r["id"]) for r in self.db.query("SELECT id FROM devices WHERE kind='esp32'")]
        feats = [f for d in devs for f in (((d.get("gateway") or {}).get("esp32") or {}).get("features") or [])]
        diag_n = self.db.one("SELECT COUNT(*) AS n FROM events e JOIN devices d ON d.id = e.device_id WHERE d.kind='esp32' "
                             "AND e.message LIKE 'ESP32 diagnosis:%'")["n"]
        labelled = self.db.one("SELECT COUNT(w.id) AS n FROM scans sc JOIN sessions se ON se.id = sc.session_id JOIN sweeps w "
                               "ON w.scan_id = sc.id WHERE se.source='device' AND se.place='outdoor_sun' AND w.complete=1 "
                               "AND sc.diagnosis IS NOT NULL")["n"]
        return {"esp32": {"web": "web" in feats}, "audit_n": self.db.one("SELECT COUNT(*) AS n FROM events")["n"],
                "decisions_esp32": lat("d.decided_by = 'esp32'"),
                "decisions_laptop": lat("d.decided_by IN ('gateway_onnx', 'gateway_numpy')"),
                "diagnosis": {"n": diag_n, "on_board": "diag" in feats}, "diagnosis_model": self._active_model("diagnosis"),
                "labelled_outdoor": labelled, "summary": evaluation.summarize(self.evidence_rounds("device")),
                "power": self.power_entries(), "trials": self.trial_runs(), "demo_only": not devs}

    # ---------- AI models on real data (CONTRACT §14) ----------
    def _training_data(self, sources, sim_n):
        """Real and lab rounds are always loaded (they are the test data); simulation only when it trains."""
        from shadeshift.training import dataset
        if self._lab_examples is None:                 # lab files never change: compute their features once
            self._lab_examples = dataset.lab_examples()
        data = {"real": dataset.real_examples(self.db), "lab": self._lab_examples}
        if "sim" in sources:
            data["sim"] = dataset.sim_examples(sim_n, cache_dir=self.settings.data_dir / "training")
        return data

    def training_summary(self, sim_n=200):
        from shadeshift.training import dataset
        data = self._training_data([], sim_n)
        cached = (self.settings.data_dir / "training" / f"sim_diagnosis_v{dataset.SIM_VERSION}_n{sim_n}_s5.json").is_file()
        out = dataset.describe([e for v in data.values() for e in v])
        out["sim"] = {"rounds": sim_n * len(dataset.CLASSES), "cached": cached,
                      "note": "generated by the research simulator on first use" + ("" if cached else " (about 1-3 minutes)")}
        out["classes"] = list(dataset.CLASSES)
        return out

    def ensure_baseline_selector(self):
        """The shipped selector (trained on simulation by the research code) is the first entry of the registry."""
        if self.db.one("SELECT 1 FROM models WHERE task='selector'"):
            return
        W = self.selector.W
        model = {"kind": "logreg", "C": 1.0, "classes": [0, 1, 2], **{k: np.asarray(W[k], float).tolist()
                                                                     for k in ("mean", "scale", "coef", "bias")}}
        report = {"task": "selector", "kind": "logreg", "sources": ["sim"], "evidence": "sim",
                  "note": "shipped model: trained on 12,000 simulated scenarios by the research code "
                          "(SHADESHIFT_ML/edge_ai/pemilih/latih_ekspor.py); " + MODEL_CLAIMS["lab"]}
        self.db.con.execute("INSERT INTO models(model_id, task, kind, sources_json, params_json, model_json, report_json, "
                            "evidence, active, created_at, activated_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (self.selector.model_id, "selector", "logreg", dumps(["sim"]), "{}", dumps(model), dumps(report),
                             "sim", 1, utc_now(), utc_now(), "shipped with the project"))

    def train_model(self, task, kind, sources, params, test_day, sim_n):
        from shadeshift.training import pipeline
        res = pipeline.train(task, kind, self._training_data(sources, sim_n), sources, params, test_day,
                             active_selector=self.selector.W if task == "selector" else None)
        report = res["report"]
        if "sim" in sources:
            report["sim"] = {"n_per_class": sim_n, "seed": 5}
        with self.db.tx() as con:
            con.execute("INSERT INTO models(model_id, task, kind, sources_json, params_json, model_json, report_json, "
                        "evidence, created_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET "
                        "report_json=excluded.report_json", (res["model_id"], task, kind, dumps(report["sources"]),
                                                             dumps(params or {}), dumps(res["model"].to_dict()),
                                                             dumps(report), report["evidence"], utc_now()))
        return res

    def activate_model(self, row_id):
        from shadeshift.training import export, models as TM, pipeline
        r = self.db.one("SELECT * FROM models WHERE id=?", (row_id,))
        if not r:
            raise LookupError(row_id)
        if r["active"]:
            return {"active": r["model_id"], "done": ["already active"]}
        done = []
        if r["task"] == "selector":
            report = json.loads(r["report_json"])
            shipped = r["note"] == "shipped with the project"
            if not shipped and not (report.get("selection") or {}).get("better_than_active"):
                raise ValueError("this selector did not lose less power than the active one on its test rounds; "
                                 "it is kept in the registry but not activated")
            W = pipeline.selector_weights(TM.from_dict(json.loads(r["model_json"])))
            done = export.activate_selector(W, r["model_id"], ", ".join(json.loads(r["sources_json"])), self.selector_paths)
            self.selector = EdgeSelector(role="server", runtime=self.settings.edge_runtime, model_path=self.settings.model_path)
            done.append("server reloaded the selector; restart run.py live/demo so the gateway does too, then reflash "
                        "firmware v3 (the gateway warns while the board has other weights)")
        elif r["task"] == "diagnosis":
            done = ["diagnosis model active (used by the live diagnosis)"]
            done += export.install_diagnosis(json.loads(r["model_json"]), r["model_id"], self.selector_paths)
        else:
            done.append("pattern model active (used by the live diagnosis)")
        with self.db.tx() as con:
            con.execute("UPDATE models SET active=0 WHERE task=?", (r["task"],))
            con.execute("UPDATE models SET active=1, activated_at=? WHERE id=?", (utc_now(), row_id))
            self.add_event(con, None, "info", f"model activated: {r['model_id']} ({r['task']})", {"done": done})
        return {"active": r["model_id"], "done": done}

    def import_session_zip(self, data):
        """Import a session zip from the Ambil data page of another laptop (CONTRACT §12): same uuids, so importing it
        twice is refused. Raw sweep text is stored exactly as it is in the zip."""
        import zipfile
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            meta = json.loads(z.read("sesi.json"))
            labels = list(csv.DictReader(io.StringIO(z.read("labels.csv").decode("utf-8"))))
        except (zipfile.BadZipFile, KeyError, ValueError) as e:
            raise ValueError(f"not a ShadeShift session zip: {e}") from None
        s, scans = meta["session"], meta["scans"]
        kind = "esp32" if s["source"] == "device" else "emulator"
        n_sweeps = 0
        with self.db.tx() as con:
            if con.execute("SELECT 1 FROM sessions WHERE uuid=?", (s["uuid"],)).fetchone():
                raise FileExistsError(f"session {s['uuid']} was already imported")
            con.execute("INSERT OR IGNORE INTO devices(id, kind, transport, first_seen, last_seen) VALUES (?,?,?,?,?)",
                        (s["device_id"], kind, "import", s["started_at"], s["started_at"]))
            sid = con.execute("INSERT INTO sessions(uuid, device_id, source, place, sky, location, operator, note, started_at, "
                              "ended_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (s["uuid"], s["device_id"], s["source"], s["place"], s.get("sky"), s.get("location"),
                               s.get("operator"), s.get("note"), s["started_at"], s.get("ended_at") or s["started_at"])).lastrowid
            scan_ids = {}
            for sc in scans:
                scan_ids[sc["uuid"]] = con.execute(
                    "INSERT INTO scans(uuid, session_id, device_id, code, condition, diagnosis, modules, dynamic, rounds, "
                    "repeat_start, with_panels, pause_s, temps_json, note, status, result, created_at, ended_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sc["uuid"], sid, s["device_id"], sc["code"], sc["condition"], sc.get("diagnosis"), sc.get("modules") or "",
                     int(bool(sc.get("dynamic"))), sc["rounds"], sc["repeat_start"], int(bool(sc.get("with_panels"))),
                     sc.get("pause_s") or 0, dumps(sc.get("temps") or {}), sc.get("note"),
                     sc["status"] if sc["status"] in ("done", "failed", "stopped") else "failed",
                     sc.get("result"), sc["created_at"], sc.get("ended_at"))).lastrowid
            for row in labels:
                try:
                    text = z.read(f"{row['folder']}/{row['file']}").decode("utf-8")
                except KeyError:
                    raise ValueError(f"labels.csv names {row['folder']}/{row['file']}, which is not in the zip") from None
                p = protocol.parse_block(text.splitlines())
                self.store_sweep(con, uuid=str(uuidlib.uuid5(UUID_NS, f"import:{s['uuid']}:{row['file']}")),
                                 device_id=s["device_id"], run_id=None, upload_id=None, source=s["source"], label=p.label,
                                 topology=p.topology, condition=row["condition"], repeat=int(row["repeat"]),
                                 captured_at=row["captured_at"], v=p.v, i=p.i, header=p.header, device_meta=p.device_meta,
                                 complete=p.complete and row["folder"] == "data", timing={}, replay_of=p.replay_of,
                                 raw_text=text.rstrip("\n"), scan_id=scan_ids.get(row["scan_uuid"]))
                n_sweeps += 1
            self.add_event(con, s["device_id"], "info", f"imported session {s['uuid']}: {len(scans)} scans, {n_sweeps} sweeps")
        return {"session_id": sid, "scans": len(scans), "sweeps": n_sweeps, "source": s["source"]}



    # ---------- live diagnosis (CONTRACT §15) ----------
    def _active_model(self, task):
        r = self.db.one("SELECT model_id, kind, model_json, report_json, evidence FROM models WHERE task=? AND active=1", (task,))
        if not r:
            return None
        key = (task, r["model_id"])
        if key not in self._model_cache:
            from shadeshift.training import models as TM
            self._model_cache[key] = TM.from_dict(json.loads(r["model_json"]))
        rep = json.loads(r["report_json"])
        return {"model": self._model_cache[key], "model_id": r["model_id"], "kind": r["kind"], "evidence": r["evidence"],
                **{k: rep.get(k) for k in ("test_mode", "accuracy", "balanced_accuracy", "accuracy_outdoor",
                                           "n_test", "n_test_outdoor")}}

    def _predict(self, task, x, names):
        a = self._active_model(task)
        if a is None:
            return {"error": "no active model: train and activate one on the Model AI page"}
        if x is None:
            return {"error": "needs complete 4S, 2S2P, TCT and 4P sweeps in this round"}
        p = a["model"].proba([x])[0]
        best = max(p, key=p.get)
        return {"class": names[best], "confidence": round(p[best], 3),
                "probs": {names[k]: round(v, 3) for k, v in sorted(p.items(), key=lambda kv: -kv[1])},
                **{k: a[k] for k in ("model_id", "kind", "evidence", "test_mode", "balanced_accuracy", "accuracy_outdoor")}}

    def round_diagnosis(self, by_t, ref=None):
        """by_t: {target: sweep row with points, pmax, isc, voc, complete} of ONE round. Cause and pattern from the
        active models (topology sweeps), position from the single-panel sweeps."""
        from shadeshift import diagnosis
        from shadeshift.training import dataset
        ok = {t: w for t, w in by_t.items() if w.get("complete") and w.get("pmax")}
        feats = {t: dataset.shape_features(ok[t]["points"]["v"], ok[t]["points"]["i"]) for t in dataset.TOPOS if t in ok}
        x = dataset.round_vector(feats, {t: ok[t]["pmax"] for t in ok})
        pmap = diagnosis.panel_map({m: ok.get(m) for m in fieldwork.MODULES}, ref)
        pat = self._predict("pattern", x, dataset.PATTERNS)
        return {"diagnosis": self._predict("diagnosis", x, dataset.CLASSES), "pattern": pat, "map": pmap,
                "agrees": (pat["class"] == pmap["pattern"]) if pmap and "class" in pat else None}

    def a1_reference(self, session_id):
        """Mean Pmax / Isc / Voc of each panel in the latest A1 scan of the session that has all four panels."""
        for r in self.db.query("SELECT id FROM scans WHERE session_id=? AND code='A1' ORDER BY id DESC", (session_id,)):
            sw = [w for w in self.scan_sweeps(r["id"]) if w["topology"] in fieldwork.MODULES and w["complete"] and w["pmax"]]
            if {w["topology"] for w in sw} == set(fieldwork.MODULES):
                return {m: {k: float(np.mean([w[k] for w in sw if w["topology"] == m])) for k in ("pmax", "isc", "voc")}
                        for m in fieldwork.MODULES}
        return None

    def scan_diagnosis(self, scan_id):
        sc = self.db.one("SELECT * FROM scans WHERE id=?", (scan_id,))
        if not sc:
            return None
        ref = self.a1_reference(sc["session_id"])
        by_rep = {}
        for w in self.scan_sweeps(scan_id, full=True):
            by_rep.setdefault(w["repeat"], {})[w["topology"]] = w
        return {"scan_id": scan_id, "condition": sc["condition"], "label": {"diagnosis": sc["diagnosis"], "modules": sc["modules"]},
                "rounds": [{"repeat": rp, "at": min(w["captured_at"] for w in by_t.values()), **self.round_diagnosis(by_t, ref)}
                           for rp, by_t in sorted(by_rep.items())]}

    def device_diagnosis(self, device_id):
        """The newest round of this device: the last full-scan round or the last decision audit."""
        s = self.db.one("SELECT scan_id, repeat, max(received_at) AS at FROM sweeps WHERE device_id=? AND scan_id IS NOT NULL "
                        "GROUP BY scan_id, repeat ORDER BY at DESC LIMIT 1", (device_id,))
        e = self.db.one("SELECT * FROM evaluations WHERE device_id=? ORDER BY id DESC LIMIT 1", (device_id,))
        if e and (not s or e["created_at"] >= s["at"]):
            by_t = {}
            for sid in json.loads(e["sweep_ids_json"]):
                w = self.sweep_full(sid)
                if w:
                    by_t[w["topology"]] = w
            return {"kind": "audit", "ref": f"audit {e['id']}", "at": e["created_at"], **self.round_diagnosis(by_t)}
        if s:
            sc = self.db.one("SELECT session_id, condition FROM scans WHERE id=?", (s["scan_id"],))
            by_t = {w["topology"]: w for w in self.scan_sweeps(s["scan_id"], full=True) if w["repeat"] == s["repeat"]}
            return {"kind": "scan", "ref": f"{sc['condition']} u{s['repeat']}", "at": s["at"],
                    **self.round_diagnosis(by_t, self.a1_reference(sc["session_id"]))}
        return None

    # ---------- Digital Twin page (CONTRACT §18) ----------
    def twin_state(self, device_id):
        """Everything the twin's live mirror draws, in one call: wiring and relays, latest sweeps, twin expectation,
        diagnosis and module map, markers, temperatures, light."""
        from shadeshift import l3, twinview
        d = self.device_row(device_id)
        if not d:
            return None
        wiring = (d.get("state") or {}).get("active_topology")
        latest = {}
        for t in protocol.SWEEP_TARGETS:
            r = self.db.one("SELECT pmax, voc, isc, captured_at, header_json, source, points_json FROM sweeps "
                            "WHERE device_id=? AND topology=? ORDER BY id DESC LIMIT 1", (device_id, t))
            if r:
                pts = json.loads(r["points_json"])
                latest[t] = {"pmax": r["pmax"], "voc": r["voc"], "isc": r["isc"], "at": r["captured_at"], "source": r["source"],
                             "light_v": json.loads(r["header_json"]).get("light_v"),
                             "points": {"v": pts["v"][::4], "i": pts["i"][::4]}}
        last = self.db.one("SELECT topology, pmax, captured_at, header_json FROM sweeps WHERE device_id=? ORDER BY id DESC "
                           "LIMIT 1", (device_id,))
        expected = self.expected()
        deviation = None
        if last and expected and expected.get(last["topology"]) and last["pmax"]:
            deviation = round((last["pmax"] - expected[last["topology"]]) / expected[last["topology"]] * 100, 1)
        diag = self.device_diagnosis(device_id)
        temps = None
        for sc in self.db.query("SELECT condition, temps_json FROM scans WHERE device_id=? AND temps_json != '{}' "
                                "ORDER BY id DESC LIMIT 1", (device_id,)):
            tj = json.loads(sc["temps_json"])
            rep_no = max(tj, key=int)
            temps = {"condition": sc["condition"], "repeat": int(rep_no), "values": tj[rep_no]}
        s = self.settings_dict()
        return {"device": {k: d.get(k) for k in ("id", "kind", "online", "firmware", "source")},
                "wiring": wiring, "relays": ([0] + list(l3.CLOSED[wiring])) if wiring in l3.CLOSED else [],
                "last_sweep": {"topology": last["topology"], "pmax": last["pmax"], "at": last["captured_at"],
                               "light_v": json.loads(last["header_json"]).get("light_v")} if last else None,
                "latest": latest, "expected": expected, "deviation_pct": deviation, "diagnosis": diag,
                "markers": twinview.markers(diag, deviation, float(s.get("alert_threshold_pct", 15))), "temps": temps,
                "settings": {"twin_scale": s.get("twin_scale", 1.0), "alert_threshold_pct": s.get("alert_threshold_pct", 15)},
                "twin": {"available": self.twin.available, "label": TWIN_LABEL},
                "monitor": (d.get("state") or {}).get("monitor") or {"on": False},
                "demo": {k: ((d.get("state") or {}).get("demo") or {}).get(k) for k in ("condition", "available_conditions")}
                        if d["kind"] == "emulator" else None,
                "kondisi": self.kondisi_state(device_id, d), "ai": self.ai_state(device_id, d),
                "perawatan": self.perawatan_state(device_id, d),
                "diag": self.diag_state(device_id, d)}

    def recent_sweeps(self, device_id, hours=24):
        """Complete sweeps of one device since `hours` ago, oldest first, split into single-panel and array sweeps,
        with light_v from the header (for the consumer view, CONTRACT §19)."""
        from datetime import timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        rows = self.db.query("SELECT topology, captured_at, pmax, voc, isc, vmp, imp, header_json FROM sweeps "
                             "WHERE device_id=? AND complete=1 AND captured_at >= ? ORDER BY captured_at", (device_id, since))
        panels, array = [], []
        for r in rows:
            h = json.loads(r.pop("header_json") or "{}")
            r["light_v"] = h.get("light_v")
            (panels if r["topology"] in protocol.PANELS else array).append(r)
        return panels, array

    def ai_state(self, device_id, d=None, hours=24):
        """The selector's results for the consumer view (CONTRACT §21): the newest 4S sweep's decision, preferring the
        one computed ON the ESP32 (firmware 3.x) over the laptop's cross-check, and the last 24 hours. Recommendations
        only: the consumer view never switches the wiring by itself."""
        from datetime import timedelta, timezone
        d = d or self.device_row(device_id)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        rows = self.db.query("SELECT d.choice, d.decided_by, d.latency_us, d.model_id, d.created_at, d.sweep_id, d.applied, "
                             "s.captured_at FROM decisions d JOIN sweeps s ON s.id = d.sweep_id WHERE d.device_id=? "
                             "AND s.captured_at >= ? ORDER BY s.id DESC, (d.decided_by = 'esp32') DESC", (device_id, since))
        on_board = any(r["decided_by"] == "esp32" for r in rows)
        use = [r for r in rows if (r["decided_by"] == "esp32") == on_board]
        by = {}
        for r in use:
            by[r["choice"]] = by.get(r["choice"], 0) + 1
        esp = (d.get("gateway") or {}).get("esp32") or None
        now = use[0] if use else None
        return {"now": {**now, "on_esp32": now["decided_by"] == "esp32"} if now else None,
                "day": {"n": len(use), "by_choice": by, "on_esp32": on_board},
                "esp32": {k: esp.get(k) for k in ("fw", "weights", "weights_match", "features")} if esp else None,
                "device_kind": d["kind"], "wiring": (d.get("state") or {}).get("active_topology")}

    def diag_state(self, device_id, d=None):
        """The diagnosis AI on the ESP32 (firmware DIAG, CONTRACT §23): whether it can run here, the newest result and the
        newest failure. A firmware that reports its features without 'diag' has no model on board; the emulator never
        runs it. Results come from the '# diagnosis=' line, stored by the gateway as an event."""
        from shadeshift import analisis_kurva as AK
        d = d or self.device_row(device_id)
        esp = (d.get("gateway") or {}).get("esp32") or {}
        feats = esp.get("features")
        on_board = ("diag" in feats) if feats else None
        if d["kind"] == "emulator":
            why = "mode demo, ESP32 tiruan tidak menjalankan diagnosis AI."
        elif on_board is False:
            why = ("model diagnosis belum dipasang di ESP32. Model perlu dilatih dengan data lapangan, lalu firmware "
                   "diunggah ulang.")
        elif not d["online"]:
            why = "ESP32 tidak terhubung."
        else:
            why = None
        ok = self.db.one("SELECT data_json, created_at FROM events WHERE device_id=? AND message LIKE 'ESP32 diagnosis:%' "
                         "ORDER BY id DESC LIMIT 1", (device_id,))
        bad = self.db.one("SELECT message, created_at FROM events WHERE device_id=? AND kind='error' AND "
                          "(message LIKE 'DIAG%' OR message LIKE 'diagnose: %') ORDER BY id DESC LIMIT 1", (device_id,))
        now = None
        if ok:
            x = json.loads(ok["data_json"])
            now = {"class": x.get("class"), "nama": AK.nama_kelas(x.get("class")), "confidence": x.get("confidence"),
                   "model_id": x.get("model_id"), "t_us": x.get("t_us"), "at": ok["created_at"]}
        return {"available": why is None and d["kind"] == "esp32", "on_board": on_board, "why": why, "now": now,
                "failed": {"at": bad["created_at"], "text": AK.alasan_diagnosis(bad["message"])} if bad else None,
                "device_kind": d["kind"]}

    def perangkat_facts(self, device_id, d=None):
        """Facts for the Perangkat page (CONTRACT §25): the device row, the gateway's reports (INFO, I2C scan, monitoring,
        outbox), the newest array sweep of the last 24 h, the newest hardware errors of the last 24 h, the panel states."""
        from datetime import timedelta, timezone
        d = d or self.device_row(device_id)
        panels, array = self.recent_sweeps(device_id)
        arr = [s for s in array if s["topology"] in protocol.TOPOLOGIES and s.get("pmax") is not None]
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        def newest(*patterns):
            rows = [self.db.one("SELECT created_at FROM events WHERE device_id=? AND kind='error' AND message LIKE ? AND "
                                "created_at >= ? ORDER BY id DESC LIMIT 1", (device_id, pat, since)) for pat in patterns]
            ats = [r["created_at"] for r in rows if r]
            return {"at": max(ats)} if ats else None
        last = arr[-1] if arr else None
        gw = d.get("gateway") or {}
        return {"kind": d["kind"], "online": d["online"], "last_seen": d["last_seen"], "transport": d.get("transport"),
                "esp32": gw.get("esp32"), "i2c": gw.get("i2c"), "state": d.get("state") or {},
                "last_sweep": {k: last.get(k) for k in ("topology", "voc", "isc", "light_v")} | {"at": last["captured_at"]}
                if last else None,
                "errors": {"voc": newest("GAGAL: Voc di luar%"), "arus": newest("GAGAL: arus tidak terdeteksi%"),
                           "serial": newest("serial connection lost%"),
                           "pindah": newest("monitoring: switch back%", "panel % check failed")},
                "panels": self.kondisi_state(device_id, d)["panels"]}

    def rangkaian_state(self, device_id, d=None):
        """Rekomendasi Rangkaian (CONTRACT §29): the active wiring, the newest comparison of all wirings, the AI's newest
        choice, the recommendation with its reasons and risks, and the newest approved change with the power before and
        after it (for the split view)."""
        from shadeshift import analisis_kurva as AK, rangkaian
        d = d or self.device_row(device_id)
        st_ = d.get("state") or {}
        mon = st_.get("monitor") or {}
        aktif = mon.get("wiring") if mon.get("on") else st_.get("active_topology")
        sekarang = aktif if aktif in protocol.TOPOLOGIES else None
        banding = {}
        last = self.db.one("SELECT label FROM sweeps WHERE device_id=? AND label LIKE 'banding\\_%' ESCAPE '\\' AND complete=1 "
                           "ORDER BY id DESC LIMIT 1", (device_id,))
        if last:
            prefix = "_".join(last["label"].split("_")[:2]) + "_"
            for r in self.db.query("SELECT id, topology, pmax, captured_at FROM sweeps WHERE device_id=? AND label LIKE ? "
                                   "AND complete=1 ORDER BY id", (device_id, prefix + "%")):
                banding[r["topology"]] = {"pmax": r["pmax"], "at": r["captured_at"], "sweep_id": r["id"]}
        ai = self.ai_state(device_id, d)
        now_ai = ai.get("now")
        ev = self.db.one("SELECT data_json, created_at FROM events WHERE device_id=? AND message LIKE 'wiring change approved%' "
                         "ORDER BY id DESC LIMIT 1", (device_id,))
        terakhir = None
        if ev:
            x = json.loads(ev["data_json"])
            terakhir = {"at": ev["created_at"], "dari": x.get("dari"), "ke": x.get("ke")}
        out = rangkaian.saran(sekarang, banding, {"choice": now_ai["choice"], "captured_at": now_ai["captured_at"]} if now_ai else None,
                              utc_now(), terakhir, demo=d["kind"] == "emulator",
                              tempat_ai=AK.tempat_ai(ai) if now_ai else "di ESP32")
        if terakhir:                                      # power before and after the newest approved change
            def power(topology, before):
                q = ("SELECT pmax, captured_at FROM sweeps WHERE device_id=? AND topology=? AND complete=1 AND captured_at "
                     + ("<= ? ORDER BY captured_at DESC" if before else "> ? ORDER BY captured_at") + " LIMIT 1")
                r = self.db.one(q, (device_id, topology, terakhir["at"]))
                return {"pmax": r["pmax"], "at": r["captured_at"]} if r else None
            a = power(terakhir["dari"], True) if terakhir["dari"] else None
            b = power(terakhir["ke"], False)
            terakhir.update(sebelum=a, sesudah=b,
                            naik_persen=round((b["pmax"] - a["pmax"]) / a["pmax"] * 100) if a and b and a["pmax"] else None)
        out.update(terakhir=terakhir, online=d["online"], device_kind=d["kind"])
        return out

    def perawatan_state(self, device_id, d=None):
        """Predictive maintenance (CONTRACT §28) from the last 14 days of this device and its maintenance log. Cached for
        a minute per device (and recomputed at once after new sweeps or a new log entry): the 3D page polls every 3 s."""
        from datetime import timedelta, timezone
        from shadeshift import analisis_kurva as AK, kondisi, perawatan
        d = d or self.device_row(device_id)
        newest = self.db.one("SELECT max(id) AS n FROM sweeps WHERE device_id=?", (device_id,))["n"]
        logs = self.db.query("SELECT data_json, created_at FROM events WHERE device_id=? AND message LIKE 'maintenance:%' "
                             "ORDER BY id", (device_id,))
        key = (newest, len(logs))
        hit = self._perawatan_cache.get(device_id)
        if hit and hit[0] == key and time.time() - hit[1] < 60:
            return hit[2]
        since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        sweeps = self.db.query("SELECT id, topology, captured_at, pmax, voc, isc, header_json FROM sweeps WHERE device_id=? "
                               "AND complete=1 AND captured_at >= ? AND pmax IS NOT NULL ORDER BY captured_at", (device_id, since))
        exp = self.expected("none") or {}
        arr = [s for s in sweeps if s["topology"] in protocol.TOPOLOGIES]
        step = max(1, len(arr) // 150)                  # the curve's flatness near its end, on at most ~150 sweeps
        sample = {s["id"] for s in arr[::step]}
        rs = {}
        if sample:
            for r in self.db.query(f"SELECT id, points_json FROM sweeps WHERE id IN ({','.join('?' * len(sample))})", list(sample)):
                pts = json.loads(r["points_json"])
                try:
                    rs[r["id"]] = AK._shape(*AK._clean(pts["v"], pts["i"])).get("rs")
                except Exception:
                    rs[r["id"]] = None
        rows = [{"at": s["captured_at"], "topology": s["topology"], "pmax": s["pmax"], "expected": exp.get(s["topology"]),
                 "light_v": json.loads(s["header_json"] or "{}").get("light_v"), "rs": rs.get(s["id"])} for s in arr]
        rounds = [{"at": r["at"], "panels": {m: {"power_rel": e["power_rel"], "state": kondisi.panel_state(e)}
                                             for m, e in r["map"]["modules"].items()}}
                  for r in kondisi.rounds([s for s in sweeps if s["topology"] in protocol.PANELS])]
        log = [{"at": e["created_at"], **{k: json.loads(e["data_json"]).get(k) for k in ("jenis", "panel")}} for e in logs]
        out = perawatan.prediksi(rows, rounds, log, demo=d["kind"] == "emulator")
        self._perawatan_cache[device_id] = (key, time.time(), out)
        return out

    def kondisi_state(self, device_id, d=None):
        from shadeshift import kondisi
        d = d or self.device_row(device_id)
        panels, array = self.recent_sweeps(device_id)
        s = self.settings_dict()
        return kondisi.assess(d["online"], d["kind"], panels, array, self.expected("none"),
                              float(s.get("alert_threshold_pct", 15)))

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
            for c in con.execute("SELECT id, device_id, kind, command, params_json, status, created_at, sent_at FROM commands "
                                 "WHERE status IN ('queued','sent')").fetchall():
                ttl = ACTUATING_TTL_S if commands.is_actuating(c["kind"], c["command"]) else OTHER_TTL_S
                queued_stop = c["status"] == "queued" and commands.is_stop(c["kind"], c["command"])   # never expires
                if c["status"] == "queued" and not queued_stop and _iso_age_s(c["created_at"]) > ttl:
                    con.execute("UPDATE commands SET status='expired', done_at=? WHERE id=?", (now, c["id"]))
                    self.sync_scan(con, c["id"], "expired", "expired: the gateway did not take it within "
                                   f"{ttl} s (is the gateway running?)")
                    self.hub.publish("command", {"id": c["id"], "status": "expired", "result": None}, c["device_id"])
                elif c["status"] == "sent" and _iso_age_s(c["sent_at"]) > _sent_ttl_s(c):
                    con.execute("UPDATE commands SET status='failed', done_at=?, result=? WHERE id=?",
                                (now, "no result from gateway", c["id"]))
                    self.sync_scan(con, c["id"], "failed", "no result from gateway (gateway closed during the scan?)")
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
            "<code>docs/CONTRACT.md</code> §5 and <a href='/openapi.json'>/openapi.json</a>.</p>"
            "<table>" + "".join(rows) + "</table>")


def create_app(settings=None):
    settings = settings or cfg.load()
    core = Core(settings)

    @asynccontextmanager
    async def lifespan(app):
        core.db.migrate()
        core.ensure_baseline_selector()
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
        # The twin can take seconds while it warms up: never inside the write transaction (it would block every writer).
        expected = core.expected() if body.topology in protocol.TOPOLOGIES else None
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
            scan_id = None
            if body.scan_uuid:
                scan = con.execute("SELECT id, device_id, status FROM scans WHERE uuid=?", (body.scan_uuid,)).fetchone()
                if scan and scan["device_id"] == body.device_id:
                    scan_id = scan["id"]
                    if scan["status"] == "queued":
                        con.execute("UPDATE scans SET status='running' WHERE id=?", (scan_id,))
            sweep_id, derived = core.store_sweep(
                con, uuid=body.uuid, device_id=body.device_id, run_id=run_id, upload_id=None, source=body.source,
                label=body.label, topology=body.topology, condition=body.condition, repeat=body.repeat,
                captured_at=body.captured_at, v=body.points.v, i=body.points.i, header=header,
                device_meta=body.device_meta.model_dump(exclude_none=True), complete=complete,
                timing=body.timing.model_dump(exclude_none=True), replay_of=body.replay_of, raw_text=body.raw_text,
                scan_id=scan_id)
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
            if expected and derived["pmax"] is not None and expected.get(body.topology):
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
                            "best, chosen, loss_pct, source, created_at, pmax_4p, pmax_panels_json, mlpe_w) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (decision_id, e.device_id, e.pmax.get("4S"), e.pmax.get("2S2P"), e.pmax.get("TCT"),
                             dumps(sweep_ids), e.best, e.chosen, e.loss_pct, e.source, e.created_at or utc_now(),
                             e.pmax_4p, dumps(e.pmax_panels), e.mlpe_w))
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
        if body.kind == "action" and command in commands.SERVER_MADE_ACTIONS:
            raise HTTPException(400, f"{command} is started with POST /sessions/{{id}}/scans, which records its labels")
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

    @app.post(API + "/stop_all", status_code=202, dependencies=write)
    def stop_all():
        """Queue 'stop' for every live (non-virtual) device: cancels running tasks and opens all relays."""
        queued = []
        with db.tx() as con:
            for d in con.execute("SELECT id FROM devices WHERE kind != 'virtual' ORDER BY id").fetchall():
                cur = con.execute("INSERT INTO commands(device_id, kind, command, params_json, status, created_at) "
                                  "VALUES (?,?,?,?,?,?)", (d["id"], "action", "stop", "{}", "queued", utc_now()))
                core.add_event(con, d["id"], "command", "queued action: stop (stop all)", {"command_id": cur.lastrowid})
                queued.append({"device_id": d["id"], "id": cur.lastrowid})
        core.wake_commands()
        for q in queued:
            core.hub.publish("command", {"id": q["id"], "status": "queued", "result": None, "command": "stop"}, q["device_id"])
        return {"queued": queued}

    @app.get(API + "/devices/{device_id}/commands/next", dependencies=write)
    def next_commands(device_id: str, wait: float = Query(5.0, ge=0, le=25)):
        """Gateway long-poll: returns queued commands (marking them sent) or an empty list after `wait` s."""
        deadline = time.monotonic() + wait
        while True:
            with db.tx() as con:
                rows = con.execute("SELECT id, kind, command, params_json, created_at FROM commands "
                                   "WHERE device_id=? AND status='queued' ORDER BY id", (device_id,)).fetchall()
                superseded = []
                if any(commands.is_stop(r["kind"], r["command"]) for r in rows):
                    # Stop first; relay-moving commands queued with it are cancelled, never run after the stop.
                    superseded = [r for r in rows if commands.is_actuating(r["kind"], r["command"])
                                  and not commands.is_stop(r["kind"], r["command"])]
                    rows = sorted((r for r in rows if r not in superseded),
                                  key=lambda r: (not commands.is_stop(r["kind"], r["command"]), r["id"]))
                now = utc_now()
                con.executemany("UPDATE commands SET status='failed', done_at=?, result='superseded by stop' WHERE id=?",
                                [(now, r["id"]) for r in superseded])
                for r in superseded:
                    core.sync_scan(con, r["id"], "failed", "superseded by stop")
                if rows:
                    con.executemany("UPDATE commands SET status='sent', sent_at=? WHERE id=?", [(now, r["id"]) for r in rows])
            for r in superseded:
                core.hub.publish("command", {"id": r["id"], "status": "failed", "result": "superseded by stop"}, device_id)
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
            core.sync_scan(con, command_id, body.status, body.result)
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
        rows = db.query("SELECT e.*, d.decided_by FROM evaluations e LEFT JOIN decisions d ON d.id = e.decision_id "
                        "WHERE (? IS NULL OR e.device_id=?) ORDER BY e.id DESC LIMIT ?",
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
        for t in protocol.SWEEP_TARGETS:
            r = db.one("SELECT id FROM sweeps WHERE device_id=? AND topology=? ORDER BY id DESC LIMIT 1", (device_id, t))
            if r:
                latest[t] = core.sweep_full(r["id"])
        by_panel = {t: latest.pop(t) for t in protocol.PANELS if t in latest}
        dec = db.one("SELECT * FROM decisions WHERE device_id=? ORDER BY id DESC LIMIT 1", (device_id,))
        return {"device": d, "latest_by_topology": latest, "latest_by_panel": by_panel,
                "recent_sweeps": _summaries("device_id=?", (device_id,), n_recent),
                "latest_decision": core.decision_row(dec) if dec else None,
                "recent_events": _events(device_id, None, None, 20),
                "log_tail": device_log(device_id, 0, 60),
                "settings": core.settings_dict(), "expected": core.expected()}

    # ======================= data-collection sessions (CONTRACT §12) =======================
    @app.get(API + "/fieldwork/catalog")
    def fieldwork_catalog():
        """Condition codes (protocol §2 with the team's corrections), diagnosis classes, places, quality limits."""
        return {"conditions": fieldwork.catalog(), "diagnosis": fieldwork.DIAGNOSIS,
                "places": {k: v[1] for k, v in fieldwork.PLACES.items()},
                "limits": {"light_change_pct": fieldwork.LIGHT_CHANGE_PCT, "repeat_spread_pct": fieldwork.REPEAT_SPREAD_PCT,
                           "a1_drift_pct": fieldwork.A1_DRIFT_PCT}}

    def _session_or_404(session_id):
        s = core.session_detail(session_id)
        if not s:
            raise HTTPException(404, "unknown session")
        return s

    @app.post(API + "/sessions", status_code=201, dependencies=write)
    def start_session(body: M.SessionIn):
        """Start a data-collection session on a live device (one open session per device)."""
        with db.tx() as con:
            kind = core.device_kind(con, body.device_id)
            if kind == "virtual":
                raise HTTPException(400, f"{body.device_id!r} is not a live device")
            open_ = con.execute("SELECT id FROM sessions WHERE device_id=? AND ended_at IS NULL", (body.device_id,)).fetchone()
            if open_:
                raise HTTPException(409, f"session {open_['id']} is still open on {body.device_id}; end it first")
            cur = con.execute("INSERT INTO sessions(uuid, device_id, source, place, sky, location, operator, note, started_at) "
                              "VALUES (?,?,?,?,?,?,?,?,?)",
                              (str(uuidlib.uuid4()), body.device_id, source_of_kind(kind), body.place, body.sky,
                               body.location, body.operator, body.note, utc_now()))
            sid = cur.lastrowid
        return core.session_detail(sid)

    @app.get(API + "/sessions")
    def list_sessions(device_id: str | None = None, open: bool | None = None, limit: int = Query(50, ge=1, le=500)):
        rows = db.query("SELECT s.*, (SELECT count(*) FROM scans WHERE session_id=s.id) AS n_scans, "
                        "(SELECT count(*) FROM sweeps JOIN scans ON scans.id = sweeps.scan_id WHERE scans.session_id=s.id) "
                        "AS n_sweeps FROM sessions s WHERE (? IS NULL OR device_id=?) ORDER BY id DESC LIMIT ?",
                        (device_id, device_id, limit))
        return [r for r in rows if open is None or (r["ended_at"] is None) == open]

    @app.get(API + "/sessions/{session_id}")
    def get_session(session_id: int):
        return _session_or_404(session_id)

    @app.post(API + "/sessions/{session_id}/end", dependencies=write)
    def end_session(session_id: int):
        with db.tx() as con:
            if con.execute("SELECT 1 FROM scans WHERE session_id=? AND status IN ('queued','running')", (session_id,)).fetchone():
                raise HTTPException(409, "a scan is still running: wait for it or press Stop")
            con.execute("UPDATE sessions SET ended_at=? WHERE id=? AND ended_at IS NULL", (utc_now(), session_id))
        return _session_or_404(session_id)

    @app.post(API + "/sessions/{session_id}/scans", status_code=202, dependencies=write)
    def start_scan(session_id: int, body: M.ScanIn):
        """Record the labels of one full scan and queue it on the device (gateway action full_scan)."""
        if body.code not in fieldwork.CONDITIONS:
            raise HTTPException(400, f"unknown condition code {body.code!r}; see /fieldwork/catalog")
        _desc, diag0, mods0, dyn0, _note = fieldwork.CONDITIONS[body.code]
        try:
            mods = fieldwork.normalize_modules(mods0 if body.modules is None else body.modules)
        except fieldwork.LabelError as e:
            raise HTTPException(400, str(e)) from None
        warnings, now = [], utc_now()
        with db.tx() as con:
            s = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not s:
                raise HTTPException(404, "unknown session")
            if s["ended_at"]:
                raise HTTPException(409, "this session has ended; start a new one")
            if con.execute("SELECT 1 FROM scans WHERE session_id=? AND status IN ('queued','running')", (session_id,)).fetchone():
                raise HTTPException(409, "another scan of this session is still queued or running")
            dev = core.device_row(s["device_id"])
            panels = body.panels
            if panels and s["source"] == "demo":
                panels = False
                warnings.append("single panels skipped: the emulator has no single-panel recordings")
            elif panels and "panel" not in ((dev["gateway"].get("esp32") or {}).get("features") or []):
                panels = False
                warnings.append("single panels skipped: the device did not report firmware with single-panel sweeps "
                                "(needs firmware 3.2; check the Status page)")
            prefix = fieldwork.DEMO_PREFIX if s["source"] == "demo" else fieldwork.PLACES[s["place"]][0]
            condition = fieldwork.condition_name(prefix, fieldwork.local_date(now), body.code, mods)
            last = con.execute("SELECT max(repeat_start + rounds - 1) FROM scans WHERE condition=?", (condition,)).fetchone()[0]
            last_sweep = con.execute("SELECT max(repeat) FROM sweeps WHERE condition=?", (condition,)).fetchone()[0]
            repeat_start = max(last or 0, last_sweep or 0) + 1
            scan_uuid = str(uuidlib.uuid4())
            params = commands.validate_action("full_scan", {
                "scan_uuid": scan_uuid, "condition": condition, "rounds": body.rounds, "repeat_start": repeat_start,
                "panels": panels, "pause_s": body.pause_s})
            cur = con.execute(
                "INSERT INTO scans(uuid, session_id, device_id, code, condition, diagnosis, modules, dynamic, rounds, "
                "repeat_start, with_panels, pause_s, note, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (scan_uuid, session_id, s["device_id"], body.code, condition, body.diagnosis or diag0, mods,
                 int(dyn0 if body.dynamic is None else body.dynamic), body.rounds, repeat_start, int(panels),
                 body.pause_s, body.note, "queued", now))
            scan_id = cur.lastrowid
            cid = con.execute("INSERT INTO commands(device_id, kind, command, params_json, status, created_at) "
                              "VALUES (?,?,?,?,?,?)", (s["device_id"], "action", "full_scan", dumps(params), "queued",
                                                       now)).lastrowid
            con.execute("UPDATE scans SET command_id=? WHERE id=?", (cid, scan_id))
            ev = core.add_event(con, s["device_id"], "command", f"queued action: full_scan {condition} "
                                f"u{repeat_start}..u{repeat_start + body.rounds - 1}",
                                {"command_id": cid, "scan_id": scan_id, "params": params, "warnings": warnings})
        core.wake_commands()
        core.hub.publish("command", {"id": cid, "status": "queued", "result": None, "command": "full_scan"}, s["device_id"])
        core.hub.publish("event", ev, s["device_id"])
        return {**core.scan_detail(scan_id), "warnings": warnings}

    @app.get(API + "/scans/{scan_id}")
    def get_scan(scan_id: int):
        sc = core.scan_detail(scan_id)
        if not sc:
            raise HTTPException(404, "unknown scan")
        return sc

    @app.put(API + "/scans/{scan_id}", dependencies=write)
    def update_scan(scan_id: int, body: M.ScanUpdate):
        """Correct labels or add panel temperatures (per repeat). The condition name and the raw sweeps never change."""
        with db.tx() as con:
            r = con.execute("SELECT temps_json FROM scans WHERE id=?", (scan_id,)).fetchone()
            if not r:
                raise HTTPException(404, "unknown scan")
            sets, args = [], []
            if body.diagnosis is not None:
                sets.append("diagnosis=?")
                args.append(body.diagnosis)
            if body.modules is not None:
                try:
                    args.append(fieldwork.normalize_modules(body.modules))
                except fieldwork.LabelError as e:
                    raise HTTPException(400, str(e)) from None
                sets.append("modules=?")
            if body.note is not None:
                sets.append("note=?")
                args.append(body.note)
            if body.temps is not None:
                temps = json.loads(r["temps_json"] or "{}")
                for rep_no, row in body.temps.items():
                    temps.setdefault(rep_no, {}).update(row)
                sets.append("temps_json=?")
                args.append(dumps(temps))
            if sets:
                con.execute(f"UPDATE scans SET {', '.join(sets)} WHERE id=?", (*args, scan_id))
        return core.scan_detail(scan_id)

    @app.get(API + "/sessions/{session_id}/export.zip")
    def export_session(session_id: int):
        """Zip of the session: raw sweep files named like the protocol, labels.csv, sesi.json, BACA_SAYA.txt."""
        s = core.session_detail(session_id, full=True)
        if not s:
            raise HTTPException(404, "unknown session")
        scans = s.pop("scans")
        by_scan = {sc["id"]: sc.pop("sweeps") for sc in scans}
        data = fieldwork.export_zip(s, scans, by_scan)
        prefix = fieldwork.DEMO_PREFIX if s["source"] == "demo" else fieldwork.PLACES[s["place"]][0]
        name = f"{prefix}{fieldwork.local_date(s['started_at']):%m%d}_sesi{session_id}.zip"
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ======================= targets vs evidence (CONTRACT §13) =======================
    @app.get(API + "/evidence/rounds")
    def evidence_rounds(source: M.LiveSource = "device", session_id: int | None = None):
        """Every scan round and live audit: % of ideal-MLPE power per topology, the AI's choice, the measured best."""
        rounds = core.evidence_rounds(source, session_id)
        return {"rounds": rounds, "summary": evaluation.summarize(rounds)}

    @app.get(API + "/evidence")
    def evidence(source: M.LiveSource = "device"):
        """The four proposal targets with their evidence (measured / lab / sim / calc)."""
        return core.evidence(source)

    @app.get(API + "/evidence.csv", response_class=PlainTextResponse)
    def evidence_csv(source: M.LiveSource = "device"):
        """Targets and evidence for the technical report, one row per evidence item."""
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["target", "status", "value", "unit", "source", "n", "detail"])
        for tg in core.evidence(source)["targets"]:
            for e in tg["evidence"]:
                w.writerow([tg["target"], tg["status"], e["value"], e["unit"], e["source"], e["n"] or "", e["detail"]])
        return PlainTextResponse(out.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="shadeshift_target_vs_bukti.csv"'})

    @app.get(API + "/metrics")
    def metrics_list(name: str | None = None, device_id: str | None = None, limit: int = Query(200, ge=1, le=5000)):
        rows = db.query("SELECT * FROM metrics WHERE (? IS NULL OR name=?) AND (? IS NULL OR device_id=?) "
                        "ORDER BY id DESC LIMIT ?", (name, name, device_id, device_id, limit))
        for r in rows:
            r["data"] = json.loads(r.pop("data_json"))
        return rows

    # ======================= AI models on real data (CONTRACT §14) =======================
    def _model_row(r, full=False):
        d = dict(r)
        d["sources"] = json.loads(d.pop("sources_json"))
        d["params"] = json.loads(d.pop("params_json"))
        d["report"] = json.loads(d.pop("report_json"))
        model = json.loads(d.pop("model_json"))
        if full:
            d["model"] = model
        d["active"] = bool(d["active"])
        return d

    @app.get(API + "/training/data")
    def training_data(sim_n: int = Query(200, ge=20, le=1500)):
        """What there is to train and test on, per source, day and class (before training)."""
        return core.training_summary(sim_n)

    @app.post(API + "/models/train", status_code=201, dependencies=write)
    def train_model(body: M.TrainIn):
        """Train one candidate and test it fairly (by day, or leave-one-scan/pattern-out). Stored, not activated."""
        from shadeshift.training import pipeline
        try:
            res = core.train_model(body.task, body.kind, body.sources, body.params, body.test_day, body.sim_n)
        except pipeline.TrainingError as e:
            raise HTTPException(400, str(e)) from None
        return _model_row(db.one("SELECT * FROM models WHERE model_id=?", (res["model_id"],)))

    @app.get(API + "/models")
    def list_models(task: str | None = None):
        return [_model_row(r) for r in db.query("SELECT * FROM models WHERE (? IS NULL OR task=?) ORDER BY id DESC",
                                                 (task, task))]

    @app.get(API + "/models/{model_row_id}")
    def get_model(model_row_id: int):
        r = db.one("SELECT * FROM models WHERE id=?", (model_row_id,))
        if not r:
            raise HTTPException(404, "unknown model")
        return _model_row(r, full=True)

    @app.get(API + "/models/{model_row_id}/header.h", response_class=PlainTextResponse)
    def model_header(model_row_id: int):
        """The model as a C header for the ESP32 (selector: pemilih_bobot.h layout; diagnosis: DIAG_* arrays)."""
        from shadeshift.training import export, models as TM, pipeline
        r = db.one("SELECT * FROM models WHERE id=?", (model_row_id,))
        if not r:
            raise HTTPException(404, "unknown model")
        model = json.loads(r["model_json"])
        if r["task"] == "selector":
            text = export.selector_header(pipeline.selector_weights(TM.from_dict(model)), r["model_id"],
                                          ", ".join(json.loads(r["sources_json"])))
            name = "pemilih_bobot.h"
        else:
            text, name = export.diagnosis_header(model, r["model_id"]), "diagnosis_model.h"
        return PlainTextResponse(text, media_type="text/plain",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post(API + "/models/{model_row_id}/activate", dependencies=write)
    def activate_model(model_row_id: int):
        """Make this model the active one of its task. A selector must have beaten the active one on its test rounds;
        activating it rewrites the weight headers, the on-board self-test and the ONNX file (restart, then reflash v3)."""
        try:
            return core.activate_model(model_row_id)
        except LookupError:
            raise HTTPException(404, "unknown model") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.post(API + "/sessions/import", status_code=201, dependencies=write)
    async def import_session(file: UploadFile = File(...)):
        """A session zip exported on another laptop (Ambil data): sessions, labeled scans and the raw sweeps."""
        data = await file.read(200 * 1024 * 1024 + 1)
        try:
            return await asyncio.to_thread(core.import_session_zip, data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except FileExistsError as e:
            raise HTTPException(409, str(e)) from None

    # ======================= live diagnosis (CONTRACT §15) =======================
    @app.get(API + "/scans/{scan_id}/diagnosis")
    def scan_diagnosis(scan_id: int):
        """Per round of a full scan: cause and pattern (active models) and the measured panel map."""
        d = core.scan_diagnosis(scan_id)
        if d is None:
            raise HTTPException(404, "unknown scan")
        return d

    @app.get(API + "/devices/{device_id}/diagnosis")
    def device_diagnosis(device_id: str):
        """The newest full-scan round or decision audit of the device, diagnosed; null when there is none."""
        return core.device_diagnosis(device_id)

    # ======================= L3 and the stability rule (CONTRACT §17) =======================
    @app.get(API + "/l3")
    def l3_data(device_id: str | None = None):
        """The semiconductor switch design (calculation), the holding power of the active wiring, and multimeter entries."""
        from shadeshift import l3
        live = None
        if device_id:
            d = core.device_row(device_id)
            if not d:
                raise HTTPException(404, f"unknown device {device_id!r}")
            wiring = (d.get("state") or {}).get("active_topology")
            live = {"device_id": device_id, "wiring": wiring, "holding": l3.holding_power(wiring)}
        return {**l3.design(), "live": live, "measured": core.power_entries()}

    @app.get(API + "/stability")
    def stability_evidence(source: M.LiveSource = "device"):
        """The stability rule: its setting (off unless switched on), the simulation result, and a replay on every
        moving-shade full scan (dynamic conditions, e.g. F1 / D2)."""
        from shadeshift import stability
        by_scan = {}
        for r in core.evidence_rounds(source):
            if r["kind"] == "scan" and (r.get("reason") or "").startswith("dynamic"):
                by_scan.setdefault((r["scan_id"], r["condition"]), []).append(r)
        replays = []
        for (scan_id, cond), rounds in sorted(by_scan.items()):
            res = stability.replay(sorted(rounds, key=lambda x: x["repeat"]))
            if res:
                replays.append({"scan_id": scan_id, "condition": cond, **res})
        return {"setting": (core.setting("auto_mode_defaults") or {}).get("stability"), "sim": stability.sim_summary(),
                "real": replays, "source": source}

    # ======================= Digital Twin page (CONTRACT §18) =======================
    @app.get("/twin", include_in_schema=False)
    def twin_page():
        """The Digital Twin page (embedded by the dashboard). Self-contained: nothing is loaded from the internet. Never
        cached, and the script link carries the script's version, so a browser never keeps an old copy after an update."""
        version = int((STATIC / "twin.js").stat().st_mtime)
        page = (STATIC / "twin.html").read_text(encoding="utf-8").replace("/twin/twin.js", f"/twin/twin.js?v={version}")
        return HTMLResponse(page, headers={"Cache-Control": "no-cache"})

    @app.get("/twin/twin.js", include_in_schema=False)
    def twin_script():
        return FileResponse(STATIC / "twin.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    @app.get(API + "/twin/state")
    def twin_state(device_id: str):
        """Live mirror of one device for the Digital Twin page."""
        st_ = core.twin_state(device_id)
        if st_ is None:
            raise HTTPException(404, f"unknown device {device_id!r}")
        return st_

    @app.get("/rangkaian", include_in_schema=False)
    def rangkaian_page():
        """The Rekomendasi Rangkaian page (embedded by the dashboard): the four panels and their wiring in 3D with the
        current flowing, before and after a change. Never cached; nothing loaded from the internet."""
        version = int((STATIC / "rangkaian.js").stat().st_mtime)
        page = (STATIC / "rangkaian.html").read_text(encoding="utf-8").replace("/rangkaian/rangkaian.js",
                                                                              f"/rangkaian/rangkaian.js?v={version}")
        return HTMLResponse(page, headers={"Cache-Control": "no-cache"})

    @app.get("/rangkaian/rangkaian.js", include_in_schema=False)
    def rangkaian_script():
        return FileResponse(STATIC / "rangkaian.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    @app.get(API + "/devices/{device_id}/rangkaian")
    def rangkaian_get(device_id: str):
        """Rekomendasi Rangkaian (CONTRACT §29): the recommendation, its reasons, advantage and risks, the comparison
        of all wirings, and the newest approved change with the power before and after."""
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        return core.rangkaian_state(device_id, d)

    @app.post(API + "/devices/{device_id}/rangkaian/terapkan", status_code=202, dependencies=write)
    def rangkaian_terapkan(device_id: str, body: M.RangkaianIn):
        """A person approved a wiring change: the approval goes into the audit trail and the gateway applies it with the
        firmware's safe order. Refused during the waiting time after the previous change (going back is allowed)."""
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        if d["kind"] == "virtual":
            raise HTTPException(400, f"{device_id!r} is not a live device")
        if not d["online"]:
            raise HTTPException(409, "Alat tidak terhubung.")
        s = core.rangkaian_state(device_id, d)
        if s["sekarang"] == body.target:
            raise HTTPException(409, f"Rangkaian sudah {s['nama_sekarang'].lower()}.")
        if s["jeda_menit"] and body.target != s["kembali"]:
            raise HTTPException(409, f"Tunggu sekitar {s['jeda_menit']} menit sebelum mengubah rangkaian lagi.")
        with db.tx() as con:
            cur = con.execute("INSERT INTO commands(device_id, kind, command, params_json, status, created_at) VALUES (?,?,?,?,?,?)",
                              (device_id, "action", "apply_wiring", dumps({"target": body.target}), "queued", utc_now()))
            ev = core.add_event(con, device_id, "command",
                                f"wiring change approved by the user: {s['sekarang'] or 'open'} -> {body.target}",
                                {"dari": s["sekarang"], "ke": body.target, "command_id": cur.lastrowid})
        core.wake_commands()
        core.hub.publish("command", {"id": cur.lastrowid, "status": "queued", "result": None, "command": "apply_wiring"}, device_id)
        core.hub.publish("event", ev, device_id)
        return {"id": cur.lastrowid, "status": "queued", "target": body.target}

    @app.get(API + "/devices/{device_id}/perawatan")
    def perawatan_get(device_id: str):
        """Predictive maintenance (CONTRACT §28): what will need attention and roughly when, and the maintenance log."""
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        return core.perawatan_state(device_id, d)

    @app.post(API + "/devices/{device_id}/perawatan", status_code=201, dependencies=write)
    def perawatan_log(device_id: str, body: M.PerawatanIn):
        """The owner logs maintenance: a fresh baseline starts here and its effect is measured."""
        with db.tx() as con:
            _require_device(con, device_id)
            word = {"bersih": "cleaned", "perbaikan": "repaired"}[body.jenis]
            ev = core.add_event(con, device_id, "info", f"maintenance: {word}" + (f" panel={body.panel}" if body.panel else ""),
                                {"jenis": body.jenis, "panel": body.panel})
        core.hub.publish("event", ev, device_id)
        core._perawatan_cache.pop(device_id, None)
        return {"ok": True}

    @app.get(API + "/devices/{device_id}/perangkat")
    def perangkat_page(device_id: str):
        """Perangkat page (CONTRACT §25): every part of the system with its state in words, from what was reported or
        measured; nothing is called working before something showed it working."""
        from shadeshift import perangkat
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        return perangkat.periksa(core.perangkat_facts(device_id, d))

    @app.get(API + "/bukti")
    def bukti_page():
        """Bukti page (CONTRACT §24): the proposal's promises and targets next to the evidence, in words, from real ESP32
        data only; the trial runs on the board with their five checks."""
        from shadeshift import bukti, l3
        out = bukti.susun(core.bukti_facts())
        out["daya"] = {**l3.design(), "measured": core.power_entries()}
        return out

    @app.get(API + "/devices/{device_id}/diag")
    def device_diag(device_id: str):
        """The diagnosis AI on the ESP32 (CONTRACT §23): available or why not, the newest result and the newest failure."""
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        return core.diag_state(device_id, d)

    @app.get(API + "/riwayat")
    def riwayat(device_id: str, hours: float = Query(24, gt=0, le=24 * 7)):
        """24-hour history for the consumer view (CONTRACT §19): per-panel state timeline from the panel checks, array
        power against the twin's expectation, state changes as events, and a summary in sentences. Measured data only."""
        from shadeshift import kondisi
        if not core.device_row(device_id):
            raise HTTPException(404, f"unknown device {device_id!r}")
        panels, array = core.recent_sweeps(device_id, hours)
        return kondisi.history(panels, array, core.expected("none"), utc_now(), hours)

    @app.get(API + "/analisis")
    def analisis(device_id: str, hours: float = Query(24, gt=0, le=24 * 7), sejak: str | None = None):
        """Curve-shape analysis for the consumer view (CONTRACT §20, §26): the latest array curve explained point by point
        (part of the curve, deviation, meaning), the last panel check's curves against the best panel, the 24-hour and
        current summaries in plain sentences, the light model's verdict on the newest measurement and its trend, and what
        is new since `sejak` (ISO; none = since the measurement before the newest). Rules and the light model, not
        validated on outdoor data; every cause says "kemungkinan"."""
        from datetime import timedelta, timezone
        from shadeshift import analisis_kurva as AK, kebiasaan as KB, kondisi
        sejak = _utc(sejak, "sejak")
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        rows = db.query("SELECT id, topology, captured_at, pmax, points_json, source FROM sweeps WHERE device_id=? AND complete=1 "
                        "AND captured_at >= ? ORDER BY captured_at", (device_id, since))
        s = core.settings_dict()
        exp = core.expected("none") or {}
        array, panels = [], []
        for r in rows:
            pts = json.loads(r["points_json"])
            if r["topology"] in protocol.TOPOLOGIES:
                ref = None
                if core.twin.available:
                    try:
                        V, I = core.twin.curve(r["topology"], max(pts["v"]), s.get("twin_scale", 1.0), "none")
                        ref = {"v": V, "i": I}
                    except Exception:
                        ref = None
                array.append({"id": r["id"], "at": r["captured_at"], "topology": r["topology"], "pmax": r["pmax"],
                              "source": r["source"], "expected": exp.get(r["topology"]), "analysis": AK.analyze(pts["v"], pts["i"], ref, 0.85)})
            else:
                panels.append({**r, "points": pts})
        panel_now = {}
        if panels:
            latest = {}
            for p in panels:                                   # newest sweep of each panel; the best one is the reference
                latest[p["topology"]] = p
            best = max(latest.values(), key=lambda p: p["pmax"] or 0)
            for m, p in latest.items():
                panel_now[m] = AK.analyze(p["points"]["v"], p["points"]["i"],
                                          None if p is best else {"v": best["points"]["v"], "i": best["points"]["i"]}, 0.9,
                                          acuan="panel terbaik")
        pan_rows, arr_rows = core.recent_sweeps(device_id, hours)
        k_now = kondisi.assess(d["online"], d["kind"], pan_rows, arr_rows, exp, float(s.get("alert_threshold_pct", 15)))
        hist = kondisi.history(pan_rows, arr_rows, exp, utc_now(), hours)
        ai = core.ai_state(device_id, d, hours)
        diag = core.diag_state(device_id, d)
        # the light model: learns this array's normal from up to 14 days, judges the newest against the ones before it
        since_m = (datetime.now(timezone.utc) - timedelta(days=KB.WINDOW_DAYS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        hist_rows = []
        for r in db.query("SELECT topology, captured_at, pmax, header_json FROM sweeps WHERE device_id=? AND complete=1 "
                          "AND captured_at >= ? AND pmax IS NOT NULL ORDER BY captured_at", (device_id, since_m)):
            if r["topology"] in protocol.TOPOLOGIES:
                hist_rows.append({"at": r["captured_at"], "topology": r["topology"], "pmax": r["pmax"],
                                  "expected": exp.get(r["topology"]), "light_v": json.loads(r["header_json"] or "{}").get("light_v")})
        model = KB.latih(hist_rows[:-1])
        newest = hist_rows[-1] if hist_rows else None
        verdict = KB.nilai(model, newest) if newest else None
        n_learn = sum(m["n"] for m in model.values())
        days = KB.tren([r for r in hist_rows if newest and r["topology"] == newest["topology"]])
        mtext = {"nilai": KB.kalimat_nilai(verdict) if verdict else None, "tren": KB.kalimat_tren(days),
                 "basis": f"Model AI kebiasaan (di laptop) belajar dari {n_learn} pengukuran panel ini dalam "
                          f"{KB.WINDOW_DAYS} hari terakhir." if hist_rows else None}
        text = AK.ringkasan(array, panel_now, k_now, hist, round(hours), ai=ai, diag=diag, model=mtext)
        pw = core.perawatan_state(device_id, d)                    # predictive maintenance (CONTRACT §28), when it is due
        if pw["ringkas"]["level"] in ("segera", "nanti"):
            text["now"]["lines"].append("Perawatan: " + pw["ringkas"]["text"])
        shapes = {a["at"]: AK.codes(a["analysis"]) for a in array}
        baru = KB.yang_baru(hist_rows, sejak, model, hist["events"][::-1], shapes, {c: v[0] for c, v in AK.MUDAH.items()})
        # optional: Gemini rewords the three boxes in the background; the local sentences stay until it passes the guard
        fakta = {"baru": {"judul": baru["judul"], "lines": baru["lines"]}, "day": text["day"], "now": text["now"]}
        ulang = core.penulis.tulis(fakta)
        penulis = "lokal"
        if ulang:
            baru = {**baru, "judul": ulang["baru"]["judul"], "lines": ulang["baru"]["lines"]}
            text = {**text, "day": ulang["day"], "now": ulang["now"],
                    "basis": text["basis"] + " Kalimat di kotak ini ditulis ulang oleh Gemini (Google) dari hasil model di "
                                             "laptop; angka dan kesimpulan tidak diubah."}
            penulis = "gemini"
        latest_curve = array[-1] if array else None
        return {**text, "demo": d["kind"] == "emulator", "ai": ai, "diag": diag, "baru": baru, "penulis": penulis,
                "model": {"status": verdict["status"] if verdict else None, "persen": verdict["persen"] if verdict else None,
                          "n": n_learn, "min_n": KB.MIN_N},
                "terbaru_at": newest["at"] if newest else None,
                "curve": {"sweep_id": latest_curve["id"], "at": latest_curve["at"], "topology": latest_curve["topology"],
                          "source": latest_curve["source"], **latest_curve["analysis"]} if latest_curve else None,
                "panels": {m: {k: a[k] for k in ("headline", "anomalies") if k in a} for m, a in panel_now.items()}}

    def _utc(iso, name):
        if not iso:
            return None
        from datetime import timezone
        try:
            t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"{name} is not an ISO time: {iso!r}") from None
        t = t if t.tzinfo else t.astimezone()                  # a time without a zone is the laptop's local time
        return t.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _jejak(device_id, since, until, semua, kategori):
        from shadeshift import jejak, kondisi
        d = core.device_row(device_id)
        if not d:
            raise HTTPException(404, f"unknown device {device_id!r}")
        if kategori not in jejak.KATEGORI:
            raise HTTPException(400, f"kategori must be one of {sorted(jejak.KATEGORI)}")
        since, until = _utc(since, "since"), _utc(until, "until")
        rng = "(? IS NULL OR {c} >= ?) AND (? IS NULL OR {c} <= ?)"
        args = (since, since, until, until)
        events = db.query("SELECT kind, message, data_json, created_at FROM events WHERE (device_id=? OR device_id IS NULL) "
                          "AND " + rng.format(c="created_at") + " ORDER BY id", (device_id, *args))
        for e in events:
            e["data"] = json.loads(e.pop("data_json"))
        decisions = db.query("SELECT d.sweep_id, d.choice, d.decided_by, d.latency_us, d.applied, s.captured_at, s.source "
                             "FROM decisions d JOIN sweeps s ON s.id = d.sweep_id WHERE d.device_id=? AND "
                             + rng.format(c="s.captured_at"), (device_id, *args))
        sebelum = None
        if since:
            last = db.query("SELECT d.choice, d.decided_by FROM decisions d JOIN sweeps s ON s.id = d.sweep_id "
                            "WHERE d.device_id=? AND s.captured_at < ? ORDER BY s.captured_at DESC, s.id DESC, "
                            "(d.decided_by = 'esp32') DESC LIMIT 1", (device_id, since))
            sebelum = last[0]["choice"] if last else None
        sebelum_diag = None
        if since:
            last = db.query("SELECT data_json FROM events WHERE device_id=? AND message LIKE 'ESP32 diagnosis:%' "
                            "AND created_at < ? ORDER BY id DESC LIMIT 1", (device_id, since))
            sebelum_diag = json.loads(last[0]["data_json"]).get("class") if last else None
        sweeps = db.query("SELECT id, topology, captured_at, pmax, voc, isc, source FROM sweeps WHERE device_id=? AND complete=1 "
                          "AND " + rng.format(c="captured_at") + " ORDER BY captured_at", (device_id, *args))
        panels = [s for s in sweeps if s["topology"] in protocol.PANELS]
        changes = kondisi.history(panels, [], None, until or utc_now())["events"] if panels else []
        demo = d["kind"] == "emulator"
        return (jejak.susun(events, decisions, sweeps, changes, sebelum, semua, kategori, demo, sebelum_diag),
                demo, since, until)

    @app.get(API + "/jejak")
    def jejak_audit(device_id: str, since: str | None = None, until: str | None = None, semua: bool = False,
                    kategori: str = "semua", page: int = Query(1, ge=1), per_page: int = Query(100, ge=10, le=1000)):
        """Audit trail for the consumer view (CONTRACT §22): who did what and when, in words, newest first. Default: the
        important entries plus one summary line per day; `semua`: every measurement and AI result. Paged."""
        entries, demo, since, until = _jejak(device_id, since, until, semua, kategori)
        pages = max(1, -(-len(entries) // per_page))
        page = min(page, pages)
        return {"device_id": device_id, "since": since, "until": until, "semua": semua, "kategori": kategori, "demo": demo,
                "total": len(entries), "page": page, "pages": pages, "per_page": per_page,
                "entries": entries[(page - 1) * per_page: page * per_page]}

    @app.get(API + "/jejak.csv", response_class=PlainTextResponse)
    def jejak_csv(device_id: str, since: str | None = None, until: str | None = None, semua: bool = True,
                  kategori: str = "semua"):
        """The whole audit trail of the period as CSV (UTF-8 with BOM so spreadsheet programs read it), every entry by
        default. Column `data` says "Mode demo" or "Nyata"; `pesan_asli` keeps the original system message."""
        from shadeshift import jejak
        entries, demo, since, until = _jejak(device_id, since, until, semua, kategori)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(jejak.KOLOM_CSV)
        for e in reversed(entries):                            # oldest first, like a log book
            w.writerow(jejak.baris_csv(e))
        name = f"jejak_audit_{device_id}.csv"
        return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post(API + "/twin/whatif", dependencies=write)
    def twin_whatif(body: M.WhatIfIn):
        """What-if shading (SIMULATION): per-cell coverage from the Shade brush -> Pmax of each wiring, the AI's pick on
        the simulated 4S curve, and the ideal-MLPE reference. Uses the lab-lamp twin (~8 % error, lab only)."""
        _twin_or_503()
        tw = core.twin
        t0 = time.perf_counter()
        scale = body.scale if body.scale is not None else float(core.setting("twin_scale") or 1.0)
        tp, mod_p = tw.whatif(scale, {"ABCD".index(m): v for m, v in body.coverage.items()}, body.kind)
        pmax = {t: round(float(v), 6) for t, v in inti.daya_harapan(tp).items()}
        c4 = tp["4S"]
        voc = float(c4.V_of_I(0.0))
        V = np.linspace(0.0, voc, 201)
        dec = core.selector.decide(V.tolist(), np.clip(c4.I_of_V(V), 0, None).tolist())
        mlpe = float(sum(mod_p))
        best = max(evaluation.CANDIDATES, key=lambda t: pmax[t])
        return {"label": "simulation: " + TWIN_LABEL, "scale": scale, "kind": body.kind, "pmax": pmax,
                "modules": {m: round(p, 6) for m, p in zip("ABCD", mod_p)}, "mlpe_w": round(mlpe, 6), "best": best,
                "ai": {"choice": dec.choice, "decided_by": dec.decided_by, "model_id": dec.model_id} if dec else None,
                "pct_of_mlpe": {t: round(v / mlpe * 100, 2) for t, v in pmax.items()} if mlpe > 0 else {},
                "covered_cells": {m: int(sum(c >= 0.5 for c in v)) for m, v in body.coverage.items()},
                "ms": round((time.perf_counter() - t0) * 1000, 1)}

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
        if topology is not None and topology not in protocol.SWEEP_TARGETS:
            raise HTTPException(400, f"topology must be one of {list(protocol.SWEEP_TARGETS)}")
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
    # A gateway's command long-poll can keep a request open for up to 25 s after the gateway is gone; without a limit
    # Ctrl+C waits for it and the launcher has to terminate the server. Unfinished writes roll back; the gateway's
    # outbox resends anything that did not get a 2xx (ingestion is idempotent by uuid).
    uvicorn.run(create_app(settings), host=settings.host, port=settings.api_port, log_level=settings.log_level.lower(),
                timeout_graceful_shutdown=5)
