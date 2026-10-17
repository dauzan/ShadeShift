"""Uplink from the edge gateway to the local server (CONTRACT.md §5.2, §5.3).

Data (sweeps, decisions, evaluations, events, metrics, log lines) goes through an outbox: a small SQLite file in the
data folder, sent in order by one thread. A network error or a 5xx keeps the item and retries with backoff, so nothing
is lost while the server is down. Re-sending is safe: the server de-duplicates sweeps and decisions by uuid.
A 404/409 (device or run unknown, e.g. the server database was reset) waits for the next heartbeat, then retries.
"""
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger("shadeshift.gateway")
PATHS = {"sweep": "/ingest/sweeps", "decision": "/ingest/decisions", "evaluations": "/ingest/evaluations",
         "events": "/ingest/events", "metrics": "/ingest/metrics", "log": "/ingest/log"}
MAX_REGISTRATION_RETRIES = 30


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ServerLink:
    def __init__(self, api_url, outbox_path, token=""):
        self.base = api_url.rstrip("/") + "/api/v1"
        self.http = requests.Session()
        if token:
            self.http.headers["X-ShadeShift-Token"] = token
        Path(outbox_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(outbox_path), check_same_thread=False, isolation_level=None, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, "
                        "attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.registered = threading.Event()      # a heartbeat was accepted since the last 404/409
        self.online = False                      # last request reached the server
        self.sent = self.dropped = 0
        self.last_error = None
        self._thread = None

    # ---------- outbox ----------
    def enqueue(self, kind, body):
        if kind not in PATHS:
            raise ValueError(f"unknown outbox kind {kind}")
        with self._lock:
            self.db.execute("INSERT INTO outbox(kind, body, created_at) VALUES (?,?,?)",
                            (kind, json.dumps(body, separators=(",", ":")), utc_now()))
        self._wake.set()

    def pending(self):
        with self._lock:
            return self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._sender, name="uplink", daemon=True)
            self._thread.start()

    def stop(self, flush_timeout=5.0):
        deadline = time.time() + flush_timeout
        while self.pending() and self.online and time.time() < deadline:
            time.sleep(0.1)
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.db.close()

    def _sender(self):
        backoff = 0.5
        while not self._stop.is_set():
            if not self.registered.wait(0.5):
                continue
            with self._lock:
                row = self.db.execute("SELECT id, kind, body, attempts FROM outbox ORDER BY id LIMIT 1").fetchone()
            if row is None:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            oid, kind, body, attempts = row
            try:
                r = self.http.post(self.base + PATHS[kind], data=body, timeout=15,
                                   headers={"Content-Type": "application/json"})
            except requests.RequestException as e:
                self._offline(e)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 10.0)
                continue
            self.online = True
            if r.status_code < 300:
                with self._lock:
                    self.db.execute("DELETE FROM outbox WHERE id=?", (oid,))
                self.sent += 1
                backoff = 0.5
            elif r.status_code in (404, 409) and attempts < MAX_REGISTRATION_RETRIES:
                with self._lock:
                    self.db.execute("UPDATE outbox SET attempts=attempts+1 WHERE id=?", (oid,))
                self.registered.clear()          # wait for the next heartbeat to re-create device and run
            elif r.status_code >= 500 or r.status_code == 401:
                self.last_error = f"{kind}: HTTP {r.status_code} {r.text[:200]}"
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 10.0)
            else:                                # 4xx that can never succeed: drop it, but say so
                with self._lock:
                    self.db.execute("DELETE FROM outbox WHERE id=?", (oid,))
                self.dropped += 1
                self.last_error = f"dropped {kind}: HTTP {r.status_code} {r.text[:200]}"
                log.error(self.last_error)

    def _offline(self, e):
        if self.online or self.last_error is None:
            log.warning("server unreachable (%s); data is kept in the outbox", e)
        self.online = False
        self.last_error = f"server unreachable: {e}"

    # ---------- direct calls ----------
    def heartbeat(self, payload):
        """POST the heartbeat; returns the server time string or None when unreachable."""
        try:
            r = self.http.post(self.base + "/devices/heartbeat", json=payload, timeout=5)
        except requests.RequestException as e:
            self._offline(e)
            return None
        self.online = True
        if r.status_code != 200:
            self.last_error = f"heartbeat: HTTP {r.status_code} {r.text[:200]}"
            return None
        self.registered.set()
        return r.json().get("server_time")

    def next_commands(self, device_id, wait=10.0):
        try:
            r = self.http.get(f"{self.base}/devices/{device_id}/commands/next", params={"wait": wait}, timeout=wait + 10)
        except requests.RequestException as e:
            self._offline(e)
            self._stop.wait(2.0)
            return []
        if r.status_code != 200:
            self._stop.wait(2.0)
            return []
        return r.json().get("commands", [])

    def command_result(self, command_id, status, result=None):
        try:
            self.http.post(f"{self.base}/commands/{command_id}/result", json={"status": status, "result": result}, timeout=10)
        except requests.RequestException as e:
            self._offline(e)

    def get(self, path, **params):
        try:
            r = self.http.get(self.base + path, params=params, timeout=10)
            return r.json() if r.status_code == 200 else None
        except (requests.RequestException, ValueError):
            return None
