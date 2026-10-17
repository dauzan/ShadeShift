# ShadeShift system contract (v1)

This file defines the interfaces between the four parts of the system:
- data flow;
- device protocol;
- edge AI model;
- HTTP/WebSocket API with JSON shapes;
- database schema;
- file formats;
- ports and environment variables.

Code must follow this file. If code and contract disagree, fix one of them in the same commit.

Status words used below:
- **v1**: built in Phase 3.
- **Foundation**: real code and interfaces, finished later (usually needs hardware).
- **Reserved**: named here so it can be added later without breaking v1.

---

## 1. Parts and data flow

```
 DEVICE                     EDGE (laptop)                         SERVER (laptop)                 DASHBOARD
 ESP32 + firmware v2/v3     gateway process                       FastAPI + SQLite                Streamlit
 ─────────────────────      ───────────────────────────────       ─────────────────────────       ───────────────────
 sweeps I-V, switches       - owns the serial port                - validates and stores          - polls REST every 1 s
 relays (safe sequence)     - parses sweep blocks (§3)            - derives Pmax/Voc/Isc (§6.3)   - sends commands
                            - stamps time, measures timings       - twin expectation + alerts     - live, replay, CSV upload,
   USB serial 115200 ─────► - EDGE AI: features + ONNX Runtime    - REST + WebSocket (§5)           technical report pages
   ◄──── commands ───────── - control: auto-select, trigger,      - CSV upload / lab import
                              hold, stability rule                - commands queue
                            - outbox: store-and-forward           
                            ── HTTP JSON 127.0.0.1:8000 ────────►  ◄──── HTTP 127.0.0.1:8000 ──── 
                            ◄── long-poll commands ─────────────   ──── WebSocket /api/v1/stream ──► (any live client)
```

- **Device.** The ESP32 never talks to the network in v1. It stays on USB serial (user decision, 18 Oct 2026).
- **Edge gateway.** The *only* program that opens the COM port, so dashboards, tabs and refreshes can never lock it. It runs the selector (edge AI) next to the device and forwards everything to the server.
  - When the server is down it keeps data in a local outbox and sends it later.
  - The same gateway can run an **emulated device** instead of a real one (demo mode, §8). Emulated data travels the exact same path and is labeled `source = "demo"`.
- **Server.** The single source of truth (SQLite). It holds no serial connection.
- **Dashboard.** A pure API client. It holds no serial connection and does no model inference.

### 1.1 Processes and ports

| Process | Command (via `run.py`) | Listens on | Talks to |
|---|---|---|---|
| Server | `python run.py server` | `127.0.0.1:8000` (HTTP + WebSocket) | SQLite file |
| Gateway, real device | `python run.py gateway --source serial` (port auto-detected; `--port COMx` overrides) | nothing | COM port, server |
| Gateway, demo device | `python run.py gateway --source demo` | nothing | lab CSV files, server |
| Dashboard | `python run.py dashboard` | `127.0.0.1:8501` | server |
| All for a demo | `python run.py demo` | 8000 + 8501 | — |
| All with hardware | `python run.py live` (optional `--port COMx`) | 8000 + 8501 | also starts a standby demo gateway |

Everything binds to `127.0.0.1` by default. Nothing needs internet.

### 1.2 Provenance (honesty rules, enforced in data)

Every sweep has a `source` and every decision has a `decided_by`. The dashboard always shows both.

| Field | Values | Meaning |
|---|---|---|
| `sweeps.source` | `device` | Measured now by the real ESP32 |
| | `demo` | Emulated device replaying **real lab curves** (halogen lamp); timing delays are estimates |
| | `upload` | Uploaded by a user as CSV |
| | `lab` | Imported from `SHADESHIFT_ML/data/data_lab/` (halogen-lamp lab dataset) |
| `decisions.decided_by` | `esp32` | Computed on the ESP32 by `pemilih.h` (firmware v3, Foundation) |
| | `gateway_onnx` / `gateway_numpy` | Computed by the edge gateway (ONNX Runtime, or the numpy fallback) |
| | `server_onnx` / `server_numpy` | Computed by the server (uploads, lab imports, replays) |
| `metrics.provenance` | `measured`, `emulated`, `manual`, `calculated` | Timing from a real device, from the emulator, typed in by a person, or computed from a model or design |

Model claims shown in the UI must carry their label, e.g.:
- "lab: loss 0.82 % vs 2.71 % best fixed (30 sets, 6 patterns)";
- "sim: 3.00 vs 6.35 points of ideal MLPE power";
- "twin: ~8 % power error on 7 lab conditions".

Diagnosis accuracy (78–82 %) is **sim only** and is not shown as a live feature.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| sweep (sapuan) | One I-V curve: ~202 (V, I) points from Voc down to near short circuit |
| topology (susunan) | Array wiring: `4S`, `2S2P`, `TCT`, `4P` |
| selector (pemilih) | Logistic regression: 14 shape features from one 4S sweep → `4S`/`2S2P`/`TCT` |
| twin (kembaran) | Digital twin of the lab lamp setup that gives expected power per topology |
| condition (kondisi) | Lab shading pattern, e.g. `V1c`, `V3_paranet65`, `V6_paranet75` |
| run | One gateway session (from start to stop) or one upload/import batch |

---

## 3. Device protocol (USB serial)

### 3.1 v2: current firmware, unchanged

Link: 115200 baud, 8N1, newline-terminated. Commands are case-insensitive. Source: [shadeshift_firmware.ino](docs/before/firmware/shadeshift_firmware/shadeshift_firmware.ino).

| Command | Effect | Key output lines |
|---|---|---|
| `4S`, `2S2P`, `TCT`, `4P` | Safe switch: DAC 0 → open R0 → open all → close target → 250 ms → Voc check → close R0 | `# topologi <T>, Voc = <v> V`, then `# siap: <T>` or `# GAGAL: Voc di luar …` |
| `SWEEP <label>` | I-V sweep of the active topology | Sweep block (§3.2), or `# GAGAL: pilih topologi dulu …` / `# GAGAL: arus tidak terdeteksi …` |
| `OFF` / `STOP` | All off | `# semua relai terbuka, MOSFET mati` |
| `VOC` | Read the array voltage | `# V_array = <v> V` |
| `STATUS` | State | `# topologi=<T or ->, R0=<tutup/buka>, cekVoc=<ON/OFF>` |
| `SIKLUS <label> <n>` | All 4 topologies, random order, n rounds; pauses for `LANJUT`/`BATAL` | Several sweep blocks, `# SIKLUS SELESAI …` |
| `PANTAU 1/0`, `VPANEL <V>`, `CEKVOC 0/1`, `KAL`, `SCAN`, `DAC <n>`, `UJIRELAI`, `RELAI <i> <0/1>`, `BANTUAN` | Service commands | `# …` lines |

### 3.2 Sweep block (what the gateway parses)

```
# MULAI <label>
# topologi=<T>, Voc=<v> V, dac=<lo>..<hi>, N=201
V,I,P
<v>,<i>,<p>          ← first row is the Voc point with I = 0
... 201 rows ...
# Pmax=<p> W, Vmp=<v> V, Imp=<i> A
# catat suhu punggung panel A-D sesudah sweep (termometer tembak)
# SELESAI
```

Parsing rules (same as `inti.urai_baris`, unchanged from the lab scripts):
- data rows must have exactly 3 comma-separated numeric fields, otherwise they are dropped;
- the header row `V,I,P` is skipped;
- any other `#` line is metadata;
- unknown `#` lines are ignored, which is how v3 additions stay backward compatible.

Gateway checks (new in v1; ANALYSIS B10, B11, F5):

| Check | Rule |
|---|---|
| **Completeness** | A sweep is `complete` when it has `N + 1` valid data rows (the Voc point + `N` from the header) and ends with `# SELESAI`. Incomplete sweeps are stored with `complete = false` and an `error` event. They never feed **live** decisions or audits. Replay and lab views show them with a warning; one archived lab file, `V3_paranet75_TCT_u2.csv`, is incomplete |
| **Response matching** | `# siap: <T>` must name the topology just requested; `# MULAI <label>` must carry the label just sent. A mismatch is an `error` event, and the waiting step fails instead of accepting the wrong line |
| **State sync** | On connect and after any error, the gateway sends `STATUS` and parses `# topologi=<T or ->, R0=<tutup/buka>, …` to learn the real relay state |
| **Failure hints** | Known firmware failures become `error` events with a hint: `GAGAL: Voc di luar …` → "check light and relay wiring; under a dim lamp lower VPANEL (e.g. `VPANEL 17`)"; `GAGAL: arus tidak terdeteksi` → "not enough light (5 mA threshold) or check fuse/R0/MOSFET/shunt"; `GAGAL: pilih topologi dulu` → "select a topology first" |

### 3.3 v3 additions (Foundation: written in Phase 3, verified only when flashed on the board)

All additions are new `#` lines or new commands, so v2 tools (logger, old dashboard) keep working.

| Addition | Format | Notes |
|---|---|---|
| `INFO` command | `# INFO fw=3.0.0, id=<12 hex chip id>, n=201` | Gives a device id and firmware version |
| Sweep metadata | `# meta t_ms=<uptime ms>, seq=<n>` right after `# MULAI` | Sweep counter and uptime (the ESP32 has no real-time clock) |
| On-device selector | `# pemilih=<4S/2S2P/TCT>, skor=<s0>;<s1>;<s2>, t_us=<int>` before `# SELESAI`, only after 4S sweeps | `pemilih.h` running on the ESP32; `t_us` = resample + features + model time |
| Hold-at-MPP monitor | `TAHAN 1/0` command; while on, `# P t_ms=<ms>, V=<v>, I=<i>, P=<p>` every 0.5 s | Lets the trigger rule watch power without sweeping. Thermal behaviour must be checked on hardware first |
| Bench mode | `BENCH 1/0` → `# BENCH ON/OFF` | `RELAI`, `UJIRELAI` and `DAC` work only with `BENCH 1` and no topology active ("only without panels"). `BENCH` is **not** in the API allowlist (§5.3); it is for the Arduino Serial Monitor |
| Safety fixes | — | `OFF`/`STOP`/`BATAL` are honoured inside SIKLUS between steps and at the prompts; a failed sweep ends SIKLUS; `DAC` is refused while R0 is closed; negative `DAC` values are rejected |

---

## 4. Edge AI model (selector)

**Single source of truth:** `SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h`. This is the working copy restored from `docs/before/` in Stage 0; the archived original is [here](docs/before/SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h).
- The ESP32 compiles it.
- The ONNX file is **generated** from it.
- The numpy fallback parses it.

| Item | Contract |
|---|---|
| Feature extraction | `port_c.cuplik_ulang` + `port_c.fitur_bentuk` (float32 replica of `pemilih.h`): drop V ≤ 0, clip I ≥ 0, sort by V, average duplicate V, resample to 201 points, 14 features |
| Feature order | `Vmp_Voc, Imp_Isc, FF, n_puncak, P2_Pmax, I@0.1Voc … I@0.9Voc` |
| ONNX file | `models/pemilih.onnx`, opset 17, plus `models/pemilih.onnx.json` metadata (`weights_sha256`, `classes`, `feature_names`, `created_at`, `generator`) |
| ONNX input | `features`: float32 `[N, 14]` |
| ONNX outputs | `scores`: float32 `[N, 3]` = `bias + W · ((x − mean) / scale)`; `label`: int64 `[N]` = argmax (0 = `4S`, 1 = `2S2P`, 2 = `TCT`) |
| `model_id` | `pemilih-logreg-v1@<first 12 hex of sha256(pemilih_bobot.h)>` |
| Runtime choice | `SHADESHIFT_EDGE_RUNTIME=auto` uses ONNX Runtime if importable and the metadata hash matches the header, else numpy (logged and labeled `*_numpy`) |
| Parity (tests must pass) | Same decision as `keputusan_c` on all 38 rows of `referensi_lab_4S.csv`; max \|Δscore\| ≤ 1e-4 vs `port_c.pilih`; lab mean losses 0.82 / 2.71 / 4.30 / 12.0 % reproduced |
| Latency | `latency_us` = wall time for features + inference on the machine named in `decided_by` |
| Input requirement | ≥ 10 valid points and a 4S sweep. Otherwise no decision is made and an `info` event says why |

---

## 5. Server API (HTTP JSON, `/api/v1`)

### 5.1 Conventions

- Base URL: `http://127.0.0.1:8000/api/v1`.
- Times are ISO-8601 UTC with milliseconds, e.g. `2026-10-18T03:15:30.123Z`. The gateway clock stamps device data.
- Topology values are `4S`, `2S2P`, `TCT`, `4P` (plus `?` when unknown, e.g. some uploads).
- **Writes** (POST, PUT, DELETE) need header `X-ShadeShift-Token: <token>` **only if** `SHADESHIFT_API_TOKEN` is set. Reads never need it. Default: no token, bound to 127.0.0.1.
- **Idempotency.** Producers send a UUID for every sweep and decision. Re-sending the same UUID returns `200` with `"duplicate": true` and stores nothing new. This is what makes the outbox retry safe.
- **Errors.** Validation errors return FastAPI's standard `422 {"detail": [...]}`. Other errors return `{"detail": "<message>"}` with 400, 401, 404, 409, 413 or 503.
- **Limits.**
  - Sweep: ≤ 5,000 points.
  - Upload: ≤ 5 MB per file, ≤ 50 files per request.
  - `label`: ≤ 80 chars of `[A-Za-z0-9_.-]`; other characters become `_`.
  - Raw command: ≤ 64 printable ASCII chars, no newline.
- API docs:
  - `GET /openapi.json` is always available.
  - The interactive `/docs` page is served **without CDN assets**: either vendored files or disabled. FastAPI's default page loads its JavaScript from the internet.

### 5.2 Ingestion (gateway → server)

**`POST /ingest/sweeps`**: one sweep.

```json
{
  "uuid": "6f1c2a8e-3b7d-4c55-9a51-2f0f6f3b1c11",
  "device_id": "esp32-01",
  "run_uuid": "0b5e…",
  "source": "device",
  "label": "auto_101530_4S",
  "topology": "4S",
  "captured_at": "2026-10-18T03:15:30.123Z",
  "points": { "v": [73.5526, 73.1637], "i": [0.0, 0.0018] },
  "header": { "voc": 73.553, "dac_lo": 2016, "dac_hi": 2304, "n": 201, "pmax": 1.0211, "vmp": 55.618, "imp": 0.0184 },
  "timing": { "sweep_ms": 1532.0, "switch_ms": null },
  "device_meta": { "uptime_ms": null, "seq": null },
  "device_decision": null,
  "condition": null,
  "repeat": null,
  "replay_of": null,
  "complete": true,
  "raw_text": "# MULAI auto_101530_4S\n…\n# SELESAI"
}
```

`complete` is optional. The server stores `complete = sent value AND (header.n is null OR n_points == header.n + 1)`.

Field notes:
- `points.v` and `points.i` have equal length (2–5,000) and hold the values as received.
- `header`, `timing`, `device_meta`, `device_decision` (v3: `{ "choice": "TCT", "scores": [..3..], "latency_us": 850 }`), `condition`, `repeat`, `replay_of` and `raw_text` are optional.
- In demo mode, `replay_of` names the lab file being replayed, e.g. `"V3_opak_4S_u2.csv"`.

Responses:
- `201`, or `200` when `duplicate` is true:

```json
{ "id": 42, "uuid": "6f1c…", "duplicate": false,
  "derived": { "n_points": 202, "voc": 73.55, "isc": 0.0258, "pmax": 1.0211, "vmp": 55.62, "imp": 0.0184 },
  "alerts": [ { "kind": "alert", "message": "Pmax -23.4 % vs twin expectation (assumed shading: none). Indication only, not a validated diagnosis." } ] }
```

- `404` if `device_id` has never sent a heartbeat. Gateways always heartbeat first.

**`POST /ingest/decisions`**:

```json
{ "uuid": "c7d4…", "sweep_uuid": "6f1c…", "device_id": "esp32-01",
  "decided_by": "gateway_onnx", "model_id": "pemilih-logreg-v1@3fa2c1d09b7e",
  "choice": "TCT", "scores": [0.12, -1.85, 0.97], "features": [0.61, 0.73, "…14 values…"],
  "latency_us": 412.5, "trigger": "auto_once", "applied": true,
  "created_at": "2026-10-18T03:15:31.002Z" }
```

- `trigger` ∈ `observe`, `auto_once`, `auto_trigger`, `stability_lock`, `upload`, `replay`, `manual`.
- Responses: `201` / `200 duplicate` → `{ "id": 9, "duplicate": false }`. `404` if the sweep UUID is unknown. The gateway always sends the sweep first.

**`POST /ingest/events`**:
- Body: `{ "items": [ { "device_id": "esp32-01", "kind": "switch", "message": "4S → TCT (selector)", "data": {}, "created_at": "…" } ] }`.
- `kind` ∈ `alert`, `switch`, `command`, `status`, `error`, `info`.
- Response: `201 { "stored": 1 }`.

**`POST /ingest/metrics`**:
- Body: `{ "items": [ { "device_id": "esp32-01", "name": "switch_ms", "value": 642.0, "unit": "ms", "provenance": "measured", "data": { "to": "TCT" }, "at": "…" } ] }`.
- Standard metric names:
  - `switch_ms`: topology command sent → `# siap:` received.
  - `sweep_ms`: `SWEEP` sent → `# SELESAI` received.
  - `decision_us`: features + inference.
  - `e2e_decision_ms`: end of the 4S sweep → switch command sent.
  - `ingest_ms`: gateway POST round trip.
  - `device_power_w`: manual entry.
  - `relay_power_w`: manual entry.
  - `panel_temp_c`: manual IR-thermometer reading, with `data.module` ∈ `A`–`D`. The firmware has no temperature sensor.
- The dashboard also uses this endpoint for manual entries, always with `provenance = manual`.

**`POST /ingest/evaluations`** (result of the `audit_decision` action):
- Body: `{ "items": [ { "decision_uuid": "c7d4…", "device_id": "esp32-01", "pmax": { "4S": 0.49, "2S2P": 0.56, "TCT": 0.57 }, "sweep_uuids": ["…", "…", "…"], "best": "TCT", "chosen": "TCT", "loss_pct": 0.0, "source": "device", "created_at": "…" } ] }`.
- `source` is `device` for real measurements and `demo` for replayed lab data. The UI never mixes the two.
- Response: `201 { "stored": 1 }`.

**`POST /ingest/log`**:
- Body: `{ "device_id": "esp32-01", "lines": [ { "at": "…", "dir": "rx", "line": "# siap: TCT" } ] }`.
- `dir` ∈ `rx`, `tx`. At most 500 lines per call.
- The server keeps the newest 5,000 lines per device.

**`POST /devices/heartbeat`** (every 2 s; also creates or updates the device):

```json
{ "device_id": "esp32-01", "kind": "esp32", "transport": "serial:COM3", "firmware": "v2",
  "run_uuid": "0b5e…",
  "gateway": { "version": "0.1.0", "edge_runtime": "onnxruntime 1.31.0", "model_id": "pemilih-logreg-v1@3fa2c1d09b7e" },
  "state": { "connected": true, "active_topology": "TCT", "task": null,
             "auto_mode": { "on": false, "interval_s": 10, "trigger_pct": 20, "hold_s": 30, "stability": { "enabled": true, "window_s": 30, "cv_pct": 10 } },
             "demo": null, "last_error": null } }
```

- `kind` ∈ `esp32`, `emulator`. `state.demo` (demo device only): `{ "condition": "V3_paranet65", "scenario": "default", "t_s": 52.0, "available_conditions": ["V1", "V1b", "V1c", "V3_opak", "…"], "standby": false }`.
- Response: `200 { "ok": true, "server_time": "…" }`. The gateway logs its clock offset if it exceeds 2 s.
- **Runs.**
  - The server creates a run the first time it sees a new `run_uuid`. Its `source` is `device` for kind `esp32` and `demo` for kind `emulator`.
  - A run ends when a heartbeat says `"state": { "connected": false, "ending": true }` (clean gateway stop), or when no heartbeat has arrived for 60 s. In that case `ended_at` = last heartbeat.
  - Sweeps whose `run_uuid` is unknown are rejected with `409`. The gateway always heartbeats before sending data.
  - Each upload request and each lab import creates its own run.

### 5.3 Commands (dashboard → server → gateway → device)

**`POST /devices/{device_id}/commands`**. Two body forms:
- raw firmware line: `{ "kind": "raw", "command": "SWEEP demo_1" }`;
- high-level action: `{ "kind": "action", "command": "auto_select", "params": {} }`.

Response: `202 { "id": 7, "status": "queued" }`. Unknown actions → `400`.

**Raw-command allowlist (safety).** The server accepts only these raw firmware commands from the API:
`4S`, `2S2P`, `TCT`, `4P`, `OFF`, `STOP`, `SWEEP <label>`, `STATUS`, `VOC`, `PANTAU 0/1`, `VPANEL <V>`, `CEKVOC 1`, `KAL`, `SCAN`, `BANTUAN`, `INFO`, `TAHAN 0/1`.

These are **rejected with `400`**:
- `RELAI`, `UJIRELAI` — the firmware docs say "only without panels", and the firmware accepts them whenever no topology is active;
- `DAC` — unguarded MOSFET drive, even with R0 closed;
- `CEKVOC 0` — disables the Voc safety check;
- `SIKLUS`, `LANJUT`, `BATAL` — while the firmware runs SIKLUS it ignores `OFF` (ANALYSIS F1). The `cycle` action below does the same job from the gateway, one step at a time, so `stop` always works between steps.

Use the blocked commands only from the Arduino Serial Monitor during bench work, with the gateway stopped. Topology changes always go through the firmware's safe sequence.

| Action | Params | Executed by gateway |
|---|---|---|
| `auto_select` | — | 4S → SWEEP → selector → switch → SWEEP (§7) |
| `auto_mode_start` | `interval_s`, `trigger_pct`, `hold_s`, `stability` | Edge control loop (§7) |
| `auto_mode_stop` | — | Stop the loop |
| `audit_decision` | — | Sweep 4S, 2S2P and TCT, then store an evaluation (measured loss of the decision) |
| `cycle` | `label`, `repeats` (1–5), `topologies` (default all 4) | Replaces firmware SIKLUS. For each repeat it shuffles the topologies, then per topology: switch → SWEEP named `<label>_<T>_u<n>`. `stop` takes effect between steps |
| `stop` | — | Immediately cancels any running gateway task (auto mode, cycle, audit), then sends `OFF`. The dashboard shows it on every page |
| `demo_condition` | `condition` | Demo device only: change the replayed condition |
| `demo_scenario_start` | `name`, `speed` | Demo device only: play `scenarios/<name>.json` |
| `demo_scenario_stop` | — | Demo device only |

**`GET /devices/{device_id}/commands/next?wait=5`** (gateway long-poll):
- returns `200 { "commands": [ { "id": 7, "kind": "action", "command": "auto_select", "params": {}, "created_at": "…" } ] }`;
- marks them `sent`;
- answers with an empty list after `wait` seconds;
- queued commands older than 60 s become `expired`;
- `sent` commands with no result after 120 s become `failed` with result `"no result from gateway"`, so a crashed gateway never leaves a command hanging. Commands are never re-delivered automatically, because re-sending a relay switch is not safe to repeat blindly.

**`POST /commands/{id}/result`**: body `{ "status": "done", "result": "TCT" }`, where `status` is `done` or `failed`. Response: `200`.

**`GET /devices/{device_id}/commands?limit=20`**: recent commands with status.

### 5.4 Reads (dashboard, tools)

| Endpoint | Returns |
|---|---|
| `GET /health` | `{ "status": "ok", "version": "0.1.0", "schema_version": 1, "db": "ok", "time": "…", "twin": "available" or "unavailable: <reason>", "model": { "model_id": "…", "runtime": "…" } }` |
| `GET /devices` | `[ { "id", "kind", "transport", "firmware", "online", "last_seen", "state" } ]`; `online` = heartbeat within `SHADESHIFT_ONLINE_TIMEOUT_S` |
| `GET /devices/{id}/snapshot?n_recent=30` | One call per dashboard refresh: `{ "device", "latest_by_topology": { "<T>": SweepFull }, "recent_sweeps": [SweepSummary], "latest_decision": Decision or null, "recent_events": [Event], "log_tail": [LogLine], "settings": Settings, "expected": { "<T>": pmax } or null }` |
| `GET /sweeps?device_id=&source=&topology=&condition=&run_id=&upload_id=&since=&limit=100&offset=0` | `[SweepSummary]`, newest first |
| `GET /sweeps/{id}` | `SweepFull` |
| `GET /sweeps/{id}/csv` | `text/csv` in the firmware/logger format (§6.1), so it can be uploaded again |
| `GET /conditions?source=lab` | `[ { "condition", "repeats": { "1": { "4S": id, "2S2P": id, "TCT": id, "4P": id } } } ]` for replay |
| `GET /decisions?device_id=&decided_by=&limit=` | `[Decision]` |
| `GET /evaluations?device_id=&limit=` | `[Evaluation]` |
| `GET /events?device_id=&kind=&since=&limit=` | `[Event]` |
| `GET /events.csv?device_id=&since=` | Audit trail as CSV. Columns: `created_at, device_id, kind, message, data`. Includes commands (`kind=command`), switches, alerts and errors. The organizers' L1 definition asks for an audit trail |
| `GET /devices/{id}/log?after_id=&limit=200` | `[LogLine]` |
| `GET /metrics/summary?device_id=&since=` | `{ "<name>": { "n", "mean", "p50", "p95", "max", "unit", "provenance": [..] } }` |
| `GET /runs?device_id=&source=` / `GET /runs/{id}` | `[Run]` / `Run`. Run = `{ "id", "uuid", "device_id", "source", "started_at", "ended_at", "meta", "n_sweeps" }` |
| `GET /uploads?limit=` | `[ { "id", "filename", "sha256", "size_bytes", "uploaded_at", "status", "n_sweeps", "error" } ]` |
| `GET /scenarios` | `[ { "name", "description", "label", "duration_s", "conditions": [...] } ]`, read from `scenarios/*.json` |
| `GET /model` | `{ "model_id", "classes", "feature_names", "weights_sha256", "onnx_sha256", "runtime", "claims": { "lab": "…", "sim": "…" } }` |

Shared shapes:
- **SweepSummary**: `{ "id", "uuid", "device_id", "run_id", "source", "label", "topology", "condition", "repeat", "captured_at", "n_points", "complete", "voc", "isc", "pmax", "vmp", "imp", "sweep_ms", "switch_ms", "replay_of", "decision": { "choice", "decided_by" } or null }`. `decision` is the newest decision made from this sweep.
- **SweepFull**: SweepSummary plus `"points": { "v": [...], "i": [...] }, "header": {...}, "device_meta": {...}, "raw_text": "…"`.
- **Decision**: `{ "id", "uuid", "sweep_id", "device_id", "decided_by", "model_id", "choice", "scores", "features", "latency_us", "trigger", "applied", "created_at" }`.
- **Evaluation**: `{ "id", "decision_id", "device_id", "pmax": { "4S", "2S2P", "TCT" }, "best", "chosen", "loss_pct", "source", "created_at" }`.
- **Event**: `{ "id", "device_id", "kind", "message", "data", "created_at" }`.
- **LogLine**: `{ "id", "at", "dir", "line" }`.

### 5.5 CSV upload and lab import

**`POST /uploads`** (multipart/form-data):
- Form fields: `files` (1–50), `device_id` (default `upload`), `topology` (optional override), `condition` (optional).
- Each file is parsed (§6), validated, and stored as sweeps with `source = "upload"`.
- 4S sweeps also get a `server_*` decision with `trigger = "upload"`.
- Response `200`:

```json
{ "results": [
  { "filename": "V3_opak_4S_u1.csv", "status": "ok", "upload_id": 3,
    "sweeps": [ { "id": 51, "topology": "4S", "pmax": 0.912, "decision": { "choice": "TCT", "decided_by": "server_onnx" } } ] },
  { "filename": "bad.csv", "status": "rejected", "error": "only 4 valid points (need >= 10)" } ] }
```

- A file whose bytes are already stored (same sha256) returns `"status": "duplicate"` with the existing sweep ids.

**`POST /import/lab`**:
- Body: `{ "include_anomalies": false }`.
- Imports `SHADESHIFT_ML/data/data_lab/*.csv` as `source = "lab"`, parsing `condition` and `repeat` from the file name. The `_V5_anomali_dioda` and `_V1d_gagal_R1` subfolders are skipped unless `include_anomalies` is true.
- Raw files are only read, never written.
- Idempotent by file sha256.
- Response: `200 { "imported": 120, "skipped_duplicates": 0 }`.

### 5.6 Digital twin and settings

| Endpoint | Contract |
|---|---|
| `GET /twin/expected?scale=1.0&shading=none` | `{ "available": true, "scale": 1.0, "shading": "none", "pmax": { "4S": 1.043, "2S2P": 1.050, "TCT": 1.051, "4P": 1.053 }, "label": "simulation: lab-lamp twin, ~8 % power error on 7 lab conditions" }`. `503` with a reason if pvlib or the twin files are missing |
| `GET /twin/curve?topology=TCT&voc_max=36.6&scale=1.0&shading=none` | `{ "v": [...250], "i": [...250] }` |
| `POST /twin/calibrate` | Body `{ "sweep_id": 42 }`. Response `{ "scale": 1.02 }`, also saved to settings. Only valid on an **unshaded** sweep; the UI says so |
| `GET /settings`, `PUT /settings` | `{ "twin_scale": 1.0, "twin_shading": "none", "alert_threshold_pct": 15, "auto_mode_defaults": { "interval_s": 10, "trigger_pct": 20, "hold_s": 30, "stability": { "enabled": true, "window_s": 30, "cv_pct": 10 } } }` |

`shading` values:

| Value | Shading |
|---|---|
| `none` | no shading |
| `opak_A` | one opaque cell on module A |
| `paranet_A` | shade net on A |
| `paranet_AB` | shade net on A+B |
| `paranet_AD` | shade net on A+D |

These are the presets in `inti.BAYANGAN`.

### 5.7 WebSocket live stream

`GET /stream?device_id=<optional>` (WebSocket). The server pushes JSON messages:

```json
{ "type": "hello", "server_time": "…", "schema_version": 1 }
{ "type": "sweep", "data": SweepSummary }
{ "type": "decision", "data": Decision }
{ "type": "device", "data": { "id", "online", "state" } }
{ "type": "event", "data": Event }
{ "type": "command", "data": { "id", "status", "result" } }
{ "type": "ping" }
```

- `ping` is sent every 15 s.
- Clients only listen. Anything they send is ignored in v1.
- `tools/ws_monitor.py` prints the stream.

### 5.8 Reserved (not in v1)

These names are reserved so they can be added later without breaking v1:
- `POST /ingest/sweeps` via MQTT: the topic `shadeshift/<device_id>/sweep` would carry the same JSON. A bridge would be needed, and Mosquitto is optional.
- `GET /runs/{id}/export` (ZIP of CSVs + decisions + metrics).
- `POST /localize`.

---

## 6. Files and formats

### 6.1 Sweep CSV: firmware/logger format (import, upload, export)

Exactly the block from §3.2:
- `#` lines for metadata;
- the header row `V,I,P`;
- data rows `v,i,p` with 3 numeric fields;
- topology from `# topologi=<T>`.

If that line is missing, the topology comes from the file name pattern `<condition>_<T>_u<n>.csv`, or from the upload form. Raw lab files keep this format and are never rewritten.

### 6.2 Plain CSV (upload only)

- A header row containing `V` and `I` (case-insensitive; also `V (V)`, `I (A)`, `voltage`, `current`). `P` and extra columns are ignored.
- Separator `,` or `;`. Decimal point `.`.
- Current in **amperes**. If the header says `mA` (e.g. `I_mA`), values are divided by 1000.

### 6.3 Validation and derived values

- Reject when:
  - there are fewer than 10 rows with V > 0;
  - any value is not numeric;
  - V is outside [-1, 200] V;
  - I is outside [-0.5, 10] A;
  - the file is larger than 5 MB.
- Accepted data is stored **as received**. Derived values use the lab rules (`inti.Sapuan.kurva_bersih`): drop V ≤ 0, clip I ≥ 0, average duplicate V, resample to 201 points.
  - `pmax`, `vmp`, `imp` come from the resampled curve;
  - `voc` = the header Voc if present, else max V;
  - `isc` = max I.
- These are the rules that reproduce the reported lab numbers.

### 6.4 Demo scenario (`scenarios/<name>.json`)

```json
{
  "name": "default",
  "description": "Clear, then shade net on A, diagonal A+D, A+B, clear again; auto mode on",
  "label": "DEMO: replays real lab curves (halogen lamp); timing delays are estimates",
  "timing": { "switch_s": 0.6, "sweep_s": 1.5 },
  "auto_mode": { "interval_s": 10, "trigger_pct": 20, "hold_s": 30, "stability": { "enabled": true, "window_s": 30, "cv_pct": 10 } },
  "timeline": [
    { "at_s": 0,   "condition": "V1c",          "note": "no shading" },
    { "at_s": 40,  "condition": "V3_paranet65", "note": "shade net on module A" },
    { "at_s": 90,  "condition": "V6_paranet65", "note": "diagonal A+D, the selector's known weak case" },
    { "at_s": 140, "condition": "V4_paranet75", "note": "A+B" },
    { "at_s": 190, "condition": "V1c",          "note": "clear again" }
  ],
  "loop": true
}
```

Conditions must exist in the lab dataset. The scenario loader rejects unknown ones.

### 6.5 Runtime files (all under `SHADESHIFT_DATA_DIR`, never committed)

| File | Purpose |
|---|---|
| `shadeshift.db` | Server database |
| `outbox-<device_id>.db` | Gateway store-and-forward queue |
| `twin_cache.json` | Cached twin results |
| `exports/` | Generated exports |

---

## 7. Edge control logic (gateway)

| Function | Rule (v1) |
|---|---|
| Observe | Every 4S sweep gets a selector decision (`trigger = observe`, `applied = false`) |
| `auto_select` | 4S → SWEEP → selector → if the choice ≠ 4S: switch → SWEEP. Stores the decision with `trigger = auto_once`, `applied = true` |
| Auto mode (trigger + hold) | Re-sweep the active topology every `interval_s`. Run `auto_select` again only if Pmax changed by more than `trigger_pct` % from the Pmax right after the last decision **and** at least `hold_s` passed since the last switch (anti-flapping). This is the existing laptop rule, moved to the edge |
| Stability rule | Over the last `window_s`, if the coefficient of variation of Pmax exceeds `cv_pct` %, switch to and hold **TCT** (`trigger = stability_lock`); release when stable. Basis: TCT was the robust default for leaf shading in **sim** (`dinamis.py`). The rule itself is **not yet validated in sim**, and the UI says so |
| Honesty | Today power is only measured by sweeping, and each sweep briefly interrupts output. The sim assumed continuous monitoring. Firmware v3 `TAHAN` (§3.3) will close that gap |
| Decision audit | `audit_decision`: sweep 4S, 2S2P and TCT, compute `loss_pct = (best − chosen) / best · 100`, store an evaluation. Source is `device` (measured) or `demo` (replayed lab data) |

---

## 8. Demo mode

- The demo device (`device_id = demo-01`, `kind = emulator`) runs inside a gateway process. It reuses the existing emulator (`ESPTiruan`), which answers the v2 protocol with **real lab curves**:
  - for a given condition it picks one of the 3 repeats at random;
  - switch and sweep delays come from the scenario `timing` (estimates, labeled `emulated`).
- Scenario playback changes the condition along the timeline and turns on auto mode. Everything flows through the normal parse → edge AI → server → dashboard path.
- With `run.py live`, a demo device is also started in standby. If the hardware fails on stage, picking `demo-01` in the dashboard takes over instantly without a restart.
- The dashboard shows a persistent DEMO banner whenever the selected device is an emulator.

---

## 9. Ports and environment variables

Configuration comes from, in priority order:
1. command-line flags of `run.py`;
2. environment variables;
3. a `.env` file in the project root (copy `.env.example`);
4. the defaults below.

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `SHADESHIFT_HOST` | `127.0.0.1` | server, dashboard | Bind address. Use `0.0.0.0` only together with a token |
| `SHADESHIFT_API_PORT` | `8000` | server | HTTP + WebSocket port |
| `SHADESHIFT_DASHBOARD_PORT` | `8501` | dashboard | Streamlit port |
| `SHADESHIFT_API_URL` | `http://127.0.0.1:8000` | gateway, dashboard, tools | Where the server is |
| `SHADESHIFT_API_TOKEN` | *(empty)* | all | If set, required as `X-ShadeShift-Token` on writes |
| `SHADESHIFT_DATA_DIR` | `./data` | server, gateway | Runtime data (§6.5) |
| `SHADESHIFT_DB_PATH` | `<DATA_DIR>/shadeshift.db` | server | SQLite file |
| `SHADESHIFT_ML_DIR` | `./SHADESHIFT_ML` | all | Research tree (weights, twin, lab data) |
| `SHADESHIFT_LAB_DIR` | `<ML_DIR>/data/data_lab` | gateway, server | Lab curves (read-only) |
| `SHADESHIFT_MODEL_PATH` | `./models/pemilih.onnx` | gateway, server | ONNX selector |
| `SHADESHIFT_EDGE_RUNTIME` | `auto` | gateway, server | `auto`, `onnx` or `numpy` |
| `SHADESHIFT_SOURCE` | `demo` | gateway | `serial` or `demo` |
| `SHADESHIFT_SERIAL_PORT` | `auto` | gateway | `auto` picks the single USB-serial port with a known ESP32 bridge id (CP210x `10C4:EA60`, CH340 `1A86:7523`/`1A86:55D4`, FTDI `0403:6001`). It fails with a port list if there are zero or several. Never defaults to `COM3`, which is a Bluetooth link on this laptop. `run.py ports` lists ports with descriptions |
| `SHADESHIFT_SERIAL_BAUD` | `115200` | gateway | |
| `SHADESHIFT_DEVICE_ID` | `esp32-01` (serial) / `demo-01` (demo) | gateway | Device id. Firmware v3 `INFO` can supply one |
| `SHADESHIFT_DEMO_SCENARIO` | `default` | gateway (demo) | Scenario file name |
| `SHADESHIFT_DEMO_SPEED` | `1.0` | gateway (demo) | Multiplier for emulated delays and the timeline |
| `SHADESHIFT_ONLINE_TIMEOUT_S` | `10` | server | Device counts as online if a heartbeat arrived within this many seconds |
| `SHADESHIFT_LOG_LEVEL` | `INFO` | all | Python logging level |

Serial: `COMx` (Windows) or `/dev/ttyUSB0` (Linux), 115200 8N1. MQTT port 1883 is **not used** in v1 (reserved, §5.8).

---

## 10. Database (SQLite, schema version 1)

Settings:
- file `<DATA_DIR>/shadeshift.db`, opened with `journal_mode=WAL` and `foreign_keys=ON`;
- version stored in `PRAGMA user_version`; migrations are numbered SQL steps applied at server start;
- times are ISO-8601 UTC text;
- JSON columns are compact JSON text.

```sql
CREATE TABLE devices (
  id           TEXT PRIMARY KEY,                       -- 'esp32-01', 'demo-01', 'upload', 'lab'
  kind         TEXT NOT NULL CHECK (kind IN ('esp32','emulator','virtual')),
  transport    TEXT,                                   -- 'serial:COM3', 'emulator', 'http'
  firmware     TEXT,                                   -- 'v2', '3.0.0', NULL
  first_seen   TEXT NOT NULL,
  last_seen    TEXT NOT NULL,
  state_json   TEXT NOT NULL DEFAULT '{}'              -- last heartbeat 'state' + 'gateway'
);

CREATE TABLE runs (
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  device_id    TEXT NOT NULL REFERENCES devices(id),
  source       TEXT NOT NULL CHECK (source IN ('device','demo','upload','lab')),
  started_at   TEXT NOT NULL,
  ended_at     TEXT,
  meta_json    TEXT NOT NULL DEFAULT '{}'              -- port, scenario, gateway version
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
  uuid         TEXT NOT NULL UNIQUE,                   -- idempotency key from the producer
  device_id    TEXT NOT NULL REFERENCES devices(id),
  run_id       INTEGER REFERENCES runs(id),
  upload_id    INTEGER REFERENCES uploads(id),
  source       TEXT NOT NULL CHECK (source IN ('device','demo','upload','lab')),
  label        TEXT NOT NULL,
  topology     TEXT NOT NULL CHECK (topology IN ('4S','2S2P','TCT','4P','?')),
  condition    TEXT,                                   -- e.g. 'V3_paranet65' (lab, upload, demo replay)
  repeat       INTEGER,
  captured_at  TEXT NOT NULL,                          -- gateway clock; uploads/lab: ingest time
  received_at  TEXT NOT NULL,                          -- server clock
  n_points     INTEGER NOT NULL,
  complete     INTEGER NOT NULL DEFAULT 1,             -- 0 = fewer rows than header N+1 or no '# SELESAI' (§3.2)
  voc REAL, isc REAL, pmax REAL, vmp REAL, imp REAL,   -- derived (§6.3)
  header_json  TEXT NOT NULL DEFAULT '{}',             -- firmware header values
  device_meta_json TEXT NOT NULL DEFAULT '{}',         -- v3: uptime_ms, seq
  sweep_ms REAL, switch_ms REAL,                       -- gateway-measured timings
  points_json  TEXT NOT NULL,                          -- {"v":[...],"i":[...]} as received
  raw_text     TEXT,                                   -- original block (audit)
  replay_of    TEXT                                    -- demo: lab file replayed
);
CREATE INDEX idx_sweeps_device_time ON sweeps(device_id, captured_at);
CREATE INDEX idx_sweeps_source_cond ON sweeps(source, condition, repeat);

CREATE TABLE decisions (
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  sweep_id     INTEGER NOT NULL REFERENCES sweeps(id), -- the 4S sweep used
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

CREATE TABLE evaluations (
  id           INTEGER PRIMARY KEY,
  decision_id  INTEGER REFERENCES decisions(id),
  device_id    TEXT NOT NULL REFERENCES devices(id),
  pmax_4s REAL, pmax_2s2p REAL, pmax_tct REAL,
  sweep_ids_json TEXT NOT NULL DEFAULT '[]',          -- the 3 audit sweeps
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
```

The virtual devices `upload` and `lab` (kind `virtual`) are created by the server on first use.

---

## 11. Versioning

| Item | Version | How it changes |
|---|---|---|
| HTTP API | `/api/v1` | Breaking changes get `/api/v2`. Optional new fields may be added to v1 |
| Database | `PRAGMA user_version = 1` | New numbered migration |
| Device protocol | v2 (as-is), v3 additions (§3.3) | Only new `#` lines or new commands |
| Selector model | `pemilih-logreg-v1@<hash>` | New weights produce a new hash. The ONNX file is regenerated and the parity tests re-run |
