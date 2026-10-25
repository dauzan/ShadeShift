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
| `decisions.decided_by` | `esp32` | Computed on the ESP32 by `pemilih.h` (firmware 3.x, Foundation) |
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

Link: 115200 baud, 8N1, newline-terminated. Commands are case-insensitive. Source: [shadeshift_firmware.ino](before/firmware/shadeshift_firmware/shadeshift_firmware.ino).

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

### 3.3 Firmware 3.0 additions (in `firmware/shadeshift_firmware/`, the project's only firmware since 20 Oct; tested on the laptop with simulated hardware, not yet on the board)

All additions are new `#` lines or new commands, so v2 tools (logger, old dashboard) keep working. Team guide and hardware checklist: `firmware/CARA_PAKAI.md`. The original v2 stays untouched in `docs/before/firmware/` as the emergency fallback.

| Addition | Format | Notes |
|---|---|---|
| `INFO` command | `# INFO fw=3.0.0, id=<12 hex chip id>, n=201, w=<12 hex>` (also printed at boot; 3.1.0 appends `, fitur=…`, §3.4) | `w` = first 12 hex of `weights_sha256` (§4), computed on the ESP32. The gateway sends `INFO` on connect; a different `w` raises an `error` event ("reflash with the current weights") |
| Sweep metadata | `# meta t_ms=<uptime ms>, seq=<n>` right after `# MULAI` | Sweep counter and uptime (the ESP32 has no real-time clock) |
| On-device selector | `# pemilih=<4S/2S2P/TCT>, skor=<s0>;<s1>;<s2>, t_us=<int>` after the `# Pmax=` line, only after 4S sweeps | `pemilih.h` running on the ESP32 on exactly the numbers it printed, so the decision can be recomputed from the log. `t_us` = resample + features + model time on the ESP32 |
| `PILIH` command | 4S → SWEEP → selector → safe switch → SWEEP, ends with `# PILIH SELESAI: <T>` or `# PILIH GAGAL: …` / `# PILIH dihentikan` | Autonomous on-board selection (Serial Monitor use). Not in the API allowlist: the dashboard uses the `auto_select` action, which applies the ESP32's decision when firmware v3 is present |
| Bench mode | `BENCH 1/0` → `# BENCH ON…` / `# BENCH OFF` | `RELAI`, `UJIRELAI` and `DAC` work only with `BENCH 1` and no topology active ("only without panels"). `OFF` ends bench mode. Not in the API allowlist (§5.3) |
| `STATUS` | `# topologi=<T or ->, R0=<tutup/buka>, cekVoc=<ON/OFF>, bench=<ON/OFF>, fw=3.0.0` | Starts like v2, so the gateway's parser is unchanged |
| Safety fixes | — | `OFF`/`STOP`/`BATAL` are honoured inside `SIKLUS` and `PILIH` between steps and at the `LANJUT` prompt; a failed sweep ends `SIKLUS` with all relays open; `DAC` accepts only 0–4095 |
| Hold-at-MPP monitor (`TAHAN`) | — | **Not implemented** (heat risk on the small MOSFET heatsink). Reserved until a heat check on the board |

### 3.4 Firmware 3.1 additions: single panels, light sensor

Every v2 command keeps its output; for the shared commands the measurements equal the original v2's (test: `tests/test_firmware_panels.py`). Wiring: `firmware/CARA_PAKAI.md`.

| Addition | Format | Notes |
|---|---|---|
| Single-panel commands `A`, `B`, `C`, `D` | Same safe switch and outputs as a topology: `# topologi A, Voc = <v> V`, `# siap: A` or `# GAGAL: Voc di luar …` | One panel alone between P and N (wiring list `rangkaian/daftar_kabel.md`): A = R7, B = R2+R8, C = R3+R9, D = R10. Voc window = one panel. `SWEEP` then gives a block with `topologi=A` etc. These are the per-panel (MLPE-style) reference sweeps. `SIKLUS` still runs only the 4 topologies |
| Light sensor (LDR) | In every sweep block: `# cahaya=<v> V` right after the `# topologi=` line, `# cahaya_akhir=<v> V` right after the `# Pmax=` line. Command `CAHAYA` prints `# cahaya=<v> V` | LDR from 3.3 V to ADS1115 A2, 10 kΩ from A2 to GND. Relative light only (not W/m²); a large start/end difference means the light changed during the sweep |
| `INFO` command | `# INFO fw=3.1.0, id=<12 hex>, n=201, w=<12 hex>, fitur=panel,cahaya,pemilih` (3.2 adds `web` and `diag`, §16; also printed at boot) | The gateway sends `INFO` on connect and shows `firmware = "v3.2 (3.2.0)"`. An `INFO` without `w` (no on-board selector) is also accepted; the laptop then decides |
| `STATUS` | v2 line plus `, fw=<version>` | Prefix unchanged |

Parsed into the sweep `header` (§5.2): `light_v` (from `# cahaya=`) and `light_end_v` (from `# cahaya_akhir=`). Sweep `topology` may be `A`–`D`. Single-panel sweeps never produce selector decisions, twin comparisons or audits; they are stored and shown as the per-panel reference.

**Emulator.** The lab recordings have no single-panel curves, so the emulated ESP32 answers `A`–`D` with `# GAGAL: tiruan tidak punya data panel tunggal (<P>); …` and opens all relays. It does not invent curves.

**Gateway behaviour with v3.** In `auto_select` and auto mode, the ESP32's decision is applied and stored with `decided_by = "esp32"`, `model_id = "pemilih-logreg-v1@<w>"` and the ESP32's `t_us`. The gateway's own decision on the same sweep is stored next to it as `observe` (cross-check). If the two differ, an `info` event says so. An emulated device never produces `esp32` decisions.

## 4. Edge AI model (selector)

**Single source of truth:** `SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h`. This is the working copy restored from `docs/before/` in Stage 0; the archived original is [here](before/SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h).
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
| `model_id` | `pemilih-logreg-v1@<first 12 hex of weights_sha256>`. `weights_sha256` = sha256 of the 73 weights as little-endian float32, in the order mean (14), scale (14), coef (3×14, row-major), bias (3). Hashing the numbers, not the file, keeps the id stable across line-ending changes |
| Runtime choice | `SHADESHIFT_EDGE_RUNTIME=auto` uses ONNX Runtime if importable and the metadata hash matches the header, else numpy (logged and labeled `*_numpy`) |
| Parity (tests must pass) | Same decision as `keputusan_c` on all 38 rows of `referensi_lab_4S.csv`; max \|Δscore\| ≤ 1e-4 vs `port_c.pilih`; lab mean losses 0.82 / 2.71 / 4.30 / 12.0 % reproduced |
| Latency | `latency_us` = wall time for features + inference on the machine named in `decided_by` |
| Input requirement | ≥ 10 valid points and a 4S sweep. Otherwise no decision is made and an `info` event says why |

---

## 5. Server API (HTTP JSON, `/api/v1`)

### 5.1 Conventions

- Base URL: `http://127.0.0.1:8000/api/v1`.
- Times are ISO-8601 UTC with milliseconds, e.g. `2026-10-18T03:15:30.123Z`. The gateway clock stamps device data.
- Topology values are `4S`, `2S2P`, `TCT`, `4P`, the single panels `A`, `B`, `C`, `D` (firmware 3.1+, §3.4), and `?` when unknown (e.g. some uploads).
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
  - `GET /docs` is a small server-rendered list of endpoints with no JavaScript and no CDN. FastAPI's default page loads its JavaScript from the internet, so it is disabled.

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
  "header": { "voc": 73.553, "dac_lo": 2016, "dac_hi": 2304, "n": 201, "pmax": 1.0211, "vmp": 55.618, "imp": 0.0184,
              "light_v": 1.234, "light_end_v": 1.229 },
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

More rules:
- `source` must be `device` or `demo`. Sweeps with `upload` or `lab` are created only by `/uploads` and `/import/lab`, so a client cannot label its data as lab measurements.
- A `device_decision` (firmware 3.x) is stored as a decision with `decided_by = "esp32"`, `model_id = "pemilih.h@firmware"` (the ESP32 does not report its weights hash yet), `features = []` and `trigger = "observe"`.

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
- Body: `{ "items": [ { "decision_uuid": "c7d4…", "device_id": "esp32-01", "pmax": { "4S": 0.49, "2S2P": 0.56, "TCT": 0.57 }, "pmax_panels": { "A": 0.16, "B": 0.16, "C": 0.15, "D": 0.16 }, "mlpe_w": 0.63, "sweep_uuids": ["…", "…", "…"], "best": "TCT", "chosen": "TCT", "loss_pct": 0.0, "source": "device", "created_at": "…" } ] }`.
- `pmax_4p`, `pmax_panels` and `mlpe_w` are optional (single panels need firmware 3.1+; §13).
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
             "auto_mode": { "on": false, "interval_s": 10, "trigger_pct": 20, "hold_s": 30, "stability": { "enabled": false, "window_s": 30, "cv_pct": 10 } },
             "demo": null, "last_error": null } }
```

- `kind` ∈ `esp32`, `emulator`. `state.demo` (demo device only): `{ "condition": "V3_paranet65", "repeat": 1, "available_conditions": ["V1", "V1b", "V1c", "V3_opak", "…"], "scenarios": ["default", "kilat", "v6_kelemahan"], "scenario": null or §6.4 progress object, "standby": false }`.
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
`4S`, `2S2P`, `TCT`, `4P`, `A`, `B`, `C`, `D`, `OFF`, `STOP`, `SWEEP <label>`, `STATUS`, `VOC`, `CAHAYA`, `PANTAU 0/1`, `VPANEL <V>`, `CEKVOC 1`, `KAL`, `SCAN`, `BANTUAN`, `INFO`, `DIAG`, `TAHAN 0`. `DIAG` (firmware v3.2) is a multi-step task on the board, accepted because the firmware honours `OFF` between its steps; like the topology commands it is refused while a gateway task runs.

These are **rejected with `400`**:
- `TAHAN 1` — holds the MOSFET at the MPP, the same heat hazard as `DAC`; only gateway logic may use it, after a heat check on hardware;
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
| `audit_decision` | — | 4S sweep → AI decision → sweep 2S2P, TCT (and A–D when available) → switch to the choice; store the decision and an evaluation (§13) |
| `cycle` | `label`, `repeats` (1–5), `topologies` (default all 4) | Replaces firmware SIKLUS. For each repeat it shuffles the topologies, then per topology: switch → SWEEP named `<label>_<T>_u<n>`. `stop` takes effect between steps |
| `stop` | — | Immediately cancels any running gateway task (auto mode, cycle, audit), then sends `OFF`. The dashboard shows it on every page |
| `demo_condition` | `condition` | Demo device only: change the replayed condition |
| `demo_scenario_start` | `name`, `speed` | Demo device only: play `scenarios/<name>.json` |
| `demo_scenario_stop` | — | Demo device only |

**Stop semantics (safety).**
- `stop`, `auto_mode_stop`, raw `OFF` and raw `STOP` all take one path in the gateway. It sets a stop latch so a running task can send nothing more, writes `OFF`, and waits up to 10 s for `# semua relai terbuka`.
- The result is `done` ("all relays open") only after that confirmation, otherwise `failed` ("OFF not confirmed by device").
- The firmware finishes the step it is in first; a sweep can take ~3–4 s. A sweep that completes after a stop is never used for a decision.
- The latch is released only when the user starts a new task.
- While a task runs, raw relay-moving commands (topologies, `SWEEP`, `VPANEL`, `CEKVOC`, `TAHAN`) and other actions fail with `busy: <task>`.
- `POST /stop_all` queues `stop` for every live device; the dashboard's Stop button uses it. Response `202 { "queued": [ { "device_id", "id" } ] }`.
- Stop needs the server and the gateway running. To cut power without software, unplug the 12 V adaptor (all relay coils).

**`GET /devices/{device_id}/commands/next?wait=5`** (gateway long-poll):
- returns `200 { "commands": [ { "id": 7, "kind": "action", "command": "auto_select", "params": {}, "created_at": "…" } ] }`;
- marks them `sent`;
- answers with an empty list after `wait` seconds;
- if a stop is queued, it is returned first, and relay-moving commands queued with it become `failed` ("superseded by stop");
- a queued stop never expires; queued relay-moving commands expire after 10 s; other queued commands after 60 s;
- `sent` commands with no result after 120 s become `failed` with result `"no result from gateway"`, so a crashed gateway never leaves a command hanging. Commands are never re-delivered automatically, because re-sending a relay switch is not safe to repeat blindly.

**`POST /commands/{id}/result`**: body `{ "status": "done", "result": "TCT" }`, where `status` is `done` or `failed`. Response: `200`.

**`GET /devices/{device_id}/commands?limit=20`**: recent commands with status.

### 5.4 Reads (dashboard, tools)

| Endpoint | Returns |
|---|---|
| `GET /health` | `{ "status": "ok", "version": "0.1.0", "schema_version": 1, "db": "ok", "time": "…", "twin": "available" or "unavailable: <reason>", "model": { "model_id": "…", "runtime": "…" } }` |
| `GET /devices` | `[ { "id", "kind", "transport", "firmware", "online", "last_seen", "state" } ]`; `online` = heartbeat within `SHADESHIFT_ONLINE_TIMEOUT_S` |
| `GET /devices/{id}/snapshot?n_recent=30` | One call per dashboard refresh: `{ "device", "latest_by_topology": { "<T>": SweepFull }, "latest_by_panel": { "<A-D>": SweepFull }, "recent_sweeps": [SweepSummary], "latest_decision": Decision or null, "recent_events": [Event], "log_tail": [LogLine], "settings": Settings, "expected": { "<T>": pmax } or null }` |
| `GET /sweeps?device_id=&source=&topology=&condition=&run_id=&upload_id=&since=&limit=100&offset=0` | `[SweepSummary]`, newest first |
| `GET /sweeps/{id}` | `SweepFull` |
| `GET /sweeps/{id}/csv` | `text/csv` in the firmware/logger format (§6.1), so it can be uploaded again |
| `GET /conditions?source=lab` | `[ { "condition", "repeats": { "1": { "4S": id, "2S2P": id, "TCT": id, "4P": id } } } ]` for replay |
| `GET /decisions?device_id=&decided_by=&limit=` | `[Decision]` |
| `GET /evaluations?device_id=&limit=` | `[Evaluation]` |
| `GET /events?device_id=&kind=&since=&limit=` | `[Event]` |
| `GET /jejak?device_id=&since=&until=&semua=&kategori=&page=&per_page=` | Audit trail in words for the consumer view (section 22), paged |
| `GET /jejak.csv?device_id=&since=&until=` | The whole audit trail of the period as CSV, every entry (section 22) |
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

- A file whose bytes are already stored (same sha256) returns `"status": "duplicate"` with the existing `sweep_ids`. If that earlier upload was rejected, it returns `"status": "rejected"` with the stored error.
- The device ids `upload` and `lab` are reserved (kind `virtual`): heartbeats for them get `400`, and so do commands to any virtual device.

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
| `GET /settings`, `PUT /settings` | `{ "twin_scale": 1.0, "twin_shading": "none", "alert_threshold_pct": 15, "auto_mode_defaults": { "interval_s": 10, "trigger_pct": 20, "hold_s": 30, "stability": { "enabled": false, "window_s": 30, "cv_pct": 10 } } }`. The stability rule is off by default because it is not validated (§7) |

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

### 5.8 Data collection (sessions and labeled full scans, details in §12)

| Endpoint | Purpose |
|---|---|
| `GET /fieldwork/catalog` | Condition codes, diagnosis classes, places, quality limits |
| `POST /sessions` | `{ "device_id", "place": "indoor_lamp" or "outdoor_sun", "sky", "location", "operator", "note" }` → 201 Session. 409 if the device already has an open session |
| `GET /sessions?device_id=&open=` | Sessions, newest first, with `n_scans`, `n_sweeps` |
| `GET /sessions/{id}` | Session with its scans (each with `quality`, `sweeps`, `n_expected`) and `a1_drift` |
| `POST /sessions/{id}/end` | Close the session (409 while a scan is queued or running) |
| `POST /sessions/{id}/scans` | `{ "code", "modules", "diagnosis", "dynamic", "rounds": 1-60, "panels", "pause_s": 0-600, "note" }` → 202 Scan + `warnings`; queues the gateway action `full_scan` |
| `GET /scans/{id}` | Scan with sweeps and quality checks |
| `PUT /scans/{id}` | `{ "diagnosis", "modules", "note", "temps": { "<repeat>": { "A": 41.5, … } } }`: label corrections and panel temperatures |
| `GET /sessions/{id}/export.zip` | The session as files for training (§12) |

### 5.9 Reserved (not in v1)

These names are reserved so they can be added later without breaking v1:
- `POST /ingest/sweeps` via MQTT: the topic `shadeshift/<device_id>/sweep` would carry the same JSON. A bridge would be needed, and Mosquitto is optional.
- `GET /runs/{id}/export` (ZIP of CSVs + decisions + metrics).
- `POST /localize`.


### 5.10 Targets vs evidence (details in §13)

| Endpoint | Purpose |
|---|---|
| `GET /evidence?source=device` | The four proposal targets, each with `status` (met / not met / no measurement yet), `needs`, and `evidence` items `{ value, unit, source: measured / lab / sim / calc, n, detail }` |
| `GET /evidence/rounds?source=device&session_id=` | Every scan round and live audit: `pmax`, `mlpe_w`, `pct_mlpe`, `choice`, `decided_by`, `best`, `ai_loss_pct`, `ai_loss_pts`, `usable`, `reason`; plus `summary` |
| `GET /evidence.csv?source=device` | One row per evidence item, for the technical report |
| `GET /metrics?name=&device_id=&limit=` | Raw metric rows (e.g. the manual `device_power_w` / `relay_power_w` entries) |

The action `audit_decision` (§5.3) runs a live audit; one multimeter entry on the page posts `device_power_w` (ESP32) and `relay_power_w` (relay coils) with `provenance = "manual"` and the same `data = { "entry": "<id>", "topology": "<active>" }`; control power = their sum.

### 5.11 AI models (details in §14)

| Endpoint | Purpose |
|---|---|
| `GET /training/data?sim_n=200` | What there is to train and test on: rounds per source, day and class |
| `POST /models/train` | `{ "task": "diagnosis", "pattern" or "selector", "kind": "logreg" or "tree", "sources": ["real","lab","sim"], "params": {"C"} or {"max_depth","min_leaf"}, "test_day": "YYYY-MM-DD" or null, "sim_n": 20-1500 }` → 201 Model (stored, not active). 400 when no fair test is possible |
| `GET /models?task=` | The registry, newest first; `report` holds the fair-test results |
| `GET /models/{id}` | One model including its weights or tree |
| `GET /models/{id}/header.h` | The model as a C header (selector: `pemilih_bobot.h` layout; diagnosis: `DIAG_*` arrays) |
| `POST /models/{id}/activate` | Make it the active model of its task. A selector must have lost less power than the active one on its test rounds (409 otherwise) |
| `POST /sessions/import` | Multipart `file`: a session zip from §12, e.g. from another laptop. 409 if already imported |

### 5.12 Live diagnosis (details in §15)

| Endpoint | Purpose |
|---|---|
| `GET /scans/{id}/diagnosis` | Per round of a full scan: cause and pattern from the active models, the measured module map |
| `GET /devices/{id}/diagnosis` | The newest full-scan round or decision audit of the device, diagnosed (or `null`) |
| `GET /devices/{id}/rangkaian` | Rekomendasi Rangkaian (section 29): the recommendation, reasons, advantage, risks, the comparison of all wirings, the newest approved change with power before and after |
| `POST /devices/{id}/rangkaian/terapkan` | `{ "target": "4S" or "2S2P" or "TCT" }` -> 202: a person approved a wiring change (audit line, then the gateway action `apply_wiring`); 409 during the waiting time (going back allowed), when offline, or when already on that wiring; 422 for 4P |
| `GET /devices/{id}/perawatan` | Predictive maintenance (section 28): `{ringkas, prediksi, log, data_hari, demo}` |
| `POST /devices/{id}/perawatan` | `{ "jenis": "bersih" or "perbaikan", "panel": "A"-"D" or null }` -> 201: the owner logs cleaning or a repair (an audit line; a fresh baseline) |
| `GET /devices/{id}/perangkat` | The Perangkat page (section 25): every part of the system with its state in words |
| `GET /bukti` | The Bukti page (section 24): promises, targets, trial runs and control power, in words, from real ESP32 data only |
| `GET /devices/{id}/diag` | The diagnosis AI on the ESP32 (section 23): `available`, `on_board`, `why`, `now`, `failed` |

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

Shipped: `default` (three shading changes, the selector is right at every step), `kilat` (the same at 3x, for rehearsals), `v6_kelemahan` (the selector's known weak case, shown honestly).

```json
{
  "name": "default",
  "description": "No shading, then three shading changes; auto mode re-selects whenever power changes by more than 20 %",
  "label": "DEMO: replays real lab curves (halogen lamp); switch and sweep times are estimates",
  "timeline": [
    { "at_s": 0,   "condition": "V1c",          "repeat": 1, "note": "no shading: TCT best, selector picks TCT" },
    { "at_s": 45,  "condition": "V3_paranet65", "repeat": 1, "note": "shade net on A: 4S best, selector picks 4S" },
    { "at_s": 90,  "condition": "V4_paranet65", "repeat": 3, "note": "shade net on A+B: TCT best, selector picks TCT" },
    { "at_s": 135, "condition": "V1c",          "repeat": 1, "note": "shading gone again" }
  ],
  "duration_s": 180,
  "loop": true,
  "speed": 1.0,
  "auto_mode": { "interval_s": 10, "trigger_pct": 20, "hold_s": 30 }
}
```

Rules:
- `condition` must exist in the lab dataset and `repeat` (optional) must exist for it; the loader rejects anything else. A pinned repeat makes the show reproducible; without it the emulator picks one repeat per condition.
- `at_s` must increase. `duration_s` (default last step + 45 s) is the cycle length; with `loop` the timeline starts again.
- `speed` > 1 makes everything faster: timeline, emulated switch/sweep delays (~0.65 s / ~3 s at 1x, estimated from firmware delays, not measured) and the auto-mode `interval_s` and `hold_s`. The `demo_scenario_start` action's `speed` overrides it.
- The player starts the normal auto mode (trigger + hold, §7), so the edge AI reacts exactly as with the real device. The stability rule is not used.
- Progress is sent as `info` events ("DEMO step 2/4: ...") and in the heartbeat as `state.demo.scenario = { "name", "step", "steps", "note", "condition", "speed", "t_s" }`.
- `stop` (any stop path) ends the scenario. A scenario never runs on an `esp32` device.

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
| Decision audit | `audit_decision`: 4S sweep and decision, then 2S2P, TCT, 4P and (firmware 3.1+) A–D in random order, then switch to the choice. `loss_pct = (best − chosen) / best · 100`; with the panels also the MLPE sum (§13). Source is `device` (measured) or `demo` (replayed lab data) |

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
| `SHADESHIFT_MONITOR_AUTO` | `1` | gateway | Start monitoring by itself once connected (not the standby demo device); `0` = wait for **Mulai pemantauan** (section 19) |
| `SHADESHIFT_GEMINI_API_KEY` | (empty) | server | Optional: Gemini rewords the analyser box (section 27); empty = local sentences only. Set it yourself; never commit it |
| `SHADESHIFT_GEMINI_MODEL` | `gemini-flash-latest` | server | The Gemini model id used for the rewording (section 27) |

Serial: `COMx` (Windows) or `/dev/ttyUSB0` (Linux), 115200 8N1. MQTT port 1883 is **not used** in v1 (reserved, §5.9).

---

## 10. Database (SQLite, schema version 5)

Settings:
- file `<DATA_DIR>/shadeshift.db`, opened with `journal_mode=WAL` and `foreign_keys=ON`;
- version stored in `PRAGMA user_version`; migrations are numbered SQL steps applied at server start, each in one transaction with foreign keys off during the step and `PRAGMA foreign_key_check` before commit;
- migration 1 = the schema as first built; migration 2 rebuilds `sweeps` so `topology` also accepts `A`–`D` (§3.4); migration 3 adds `sessions`, `scans` and `sweeps.scan_id` (§12); migration 4 adds the panels, 4P and MLPE to `evaluations` (§13); migration 5 adds the model registry `models` (§14). The DDL below is the current schema after all migrations;
- times are ISO-8601 UTC text;
- JSON columns are compact JSON text.

```sql
CREATE TABLE devices (
  id           TEXT PRIMARY KEY,                       -- 'esp32-01', 'demo-01', 'upload', 'lab'
  kind         TEXT NOT NULL CHECK (kind IN ('esp32','emulator','virtual')),
  transport    TEXT,                                   -- 'serial:COM3', 'emulator', 'http'
  firmware     TEXT,                                   -- 'v2', 'v3.2 (3.2.0)', NULL
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
  topology     TEXT NOT NULL CHECK (topology IN ('4S','2S2P','TCT','4P','A','B','C','D','?')),
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
  replay_of    TEXT,                                   -- demo: lab file replayed
  scan_id      INTEGER REFERENCES scans(id)            -- migration 3: sweep of a labeled full scan (§12)
);
CREATE INDEX idx_sweeps_device_time ON sweeps(device_id, captured_at);
CREATE INDEX idx_sweeps_source_cond ON sweeps(source, condition, repeat);
CREATE INDEX idx_sweeps_scan ON sweeps(scan_id);

CREATE TABLE sessions (                                 -- migration 3: data-collection sessions (§12)
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
  ended_at     TEXT                                     -- NULL while open (one open session per device)
);
CREATE INDEX idx_sessions_device ON sessions(device_id, started_at);

CREATE TABLE scans (                                    -- migration 3: one labeled full scan (§12)
  id           INTEGER PRIMARY KEY,
  uuid         TEXT NOT NULL UNIQUE,
  session_id   INTEGER NOT NULL REFERENCES sessions(id),
  device_id    TEXT NOT NULL REFERENCES devices(id),
  code         TEXT NOT NULL,                           -- protocol condition code: A1, B1-B7, C1-C5, D1-D2, E1-E5, F1, X1
  condition    TEXT NOT NULL,                           -- file-name stem: LR1020_B2, DR1020_B2-C, TIRUAN1020_A1
  diagnosis    TEXT CHECK (diagnosis IN ('normal','partial_shading','uniform_dimming','bypass_open','bypass_short','series_resistance')),
  modules      TEXT NOT NULL DEFAULT '',                -- affected modules, e.g. 'AB'
  dynamic      INTEGER NOT NULL DEFAULT 0,
  rounds       INTEGER NOT NULL,
  repeat_start INTEGER NOT NULL,                        -- the rounds are repeats u<repeat_start> .. u<repeat_start+rounds-1>
  with_panels  INTEGER NOT NULL DEFAULT 0,
  pause_s      REAL NOT NULL DEFAULT 0,
  temps_json   TEXT NOT NULL DEFAULT '{}',              -- {"<repeat>": {"A": 41.5, ...}} panel back, deg C
  note         TEXT,
  status       TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','stopped')),
  result       TEXT,
  command_id   INTEGER REFERENCES commands(id),
  created_at   TEXT NOT NULL,
  ended_at     TEXT
);
CREATE INDEX idx_scans_session ON scans(session_id);
CREATE INDEX idx_scans_condition ON scans(condition);

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
CREATE INDEX idx_decisions_sweep ON decisions(sweep_id);

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
  created_at   TEXT NOT NULL,
  pmax_4p      REAL,                                    -- migration 4 (§13)
  pmax_panels_json TEXT NOT NULL DEFAULT '{}',          -- single panels A-D of the audit
  mlpe_w       REAL                                     -- sum of the four single-panel Pmax
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

CREATE TABLE models (                                   -- migration 5: model registry (§14)
  id           INTEGER PRIMARY KEY,
  model_id     TEXT NOT NULL UNIQUE,                    -- pemilih-logreg-v1@<weights fingerprint> / diag-<kind>-v1@<hash>
  task         TEXT NOT NULL CHECK (task IN ('diagnosis','selector','pattern')),
  kind         TEXT NOT NULL CHECK (kind IN ('logreg','tree')),
  sources_json TEXT NOT NULL,                           -- training sources: real / lab / sim
  params_json  TEXT NOT NULL DEFAULT '{}',
  model_json   TEXT NOT NULL,                           -- the model itself (weights or tree)
  report_json  TEXT NOT NULL,                           -- fair test: mode, data used, accuracy, confusion, losses
  evidence     TEXT NOT NULL CHECK (evidence IN ('real','lab','sim')),   -- what the test data was
  active       INTEGER NOT NULL DEFAULT 0,              -- one active model per task
  created_at   TEXT NOT NULL,
  activated_at TEXT,
  note         TEXT
);
CREATE INDEX idx_models_task ON models(task, active);

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
| Database | `PRAGMA user_version = 5` | New numbered migration |
| Device protocol | v2 (as-is), firmware 3.0 additions (§3.3), 3.1 (§3.4), 3.2 (§16) | Only new `#` lines or new commands |
| Selector model | `pemilih-logreg-v1@<hash>` | New weights produce a new hash. The ONNX file is regenerated and the parity tests re-run |

---

## 12. Data collection: sessions and labeled full scans

Built for the measurement days (protocol `SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md`, corrected in `docs/team/progress.md` §8). Dashboard page **Ambil data**; code in `shadeshift/fieldwork.py`.

**Flow.**
1. `POST /sessions` starts a session on a live device: place (`indoor_lamp` / `outdoor_sun`), sky, location, operator, note. One open session per device.
2. For each condition the operator sets up the panels, then `POST /sessions/{id}/scans` records the labels and queues the gateway action `full_scan`. `full_scan` cannot be queued through `/devices/{id}/commands`.
3. The gateway runs `rounds` rounds. Each round sweeps the 4 topologies and, with firmware 3.1+, the 4 single panels, in random order, through the usual safe switch. Between rounds all relays open for `pause_s` seconds (panel temperatures with the IR thermometer, MOSFET cooling). Stop ends it between steps, as for every task.
4. Every sweep is named `<condition>_<target>_u<repeat>` and carries `scan_uuid`, `condition` and `repeat`; the server links it to the scan (`sweeps.scan_id`).
5. Temperatures and label corrections: `PUT /scans/{id}`. Raw sweeps never change.
6. `GET /sessions/{id}/export.zip` gives the files for training.

**Names.** `condition` = `<prefix><MMDD>_<code>`, local date of the scan. Prefix `LR` = outdoor (protocol §4), `DR` = indoor lamp, `TIRUAN` = emulator (replayed lab curves, never named like a real measurement). If the affected modules differ from the catalog default, they are appended: `LR1020_B2-C` (B2 on module C). Repeats continue across scans of the same condition, so file names never collide.

**Catalog** (`GET /fieldwork/catalog`): A1 (reference, start and end of each session), B1–B7 opaque, C1–C5 shade cloth / dirt, D1–D2 natural shade (operator picks the class), E1 (open bypass diode without shade, a control), E2 (open diode + 50 % shade), E3/E4 series resistor **5 Ω / 10 Ω**, E5 (module bypassed = shorted-bypass class), F1 moving leaves (dynamic), X1 other. Diagnosis classes: `normal`, `partial_shading`, `uniform_dimming`, `bypass_open`, `bypass_short`, `series_resistance`.

**Panels.** The server asks for single panels only when the device's `INFO` reported `fitur=…panel…`; otherwise the scan runs the 4 topologies and the response has a warning. The emulator never does single panels.

**Quality checks** (in every scan response, `quality`: `ok` = true / false / null when it cannot be checked):

| Check | Rule |
|---|---|
| `complete` | Every target of every round has a complete sweep |
| `light_steady` | LDR start vs end of each sweep, and spread over each round, ≤ 5 % (protocol §3). LDR volts are not linear in irradiance: approximate. Null without LDR lines |
| `repeat_spread` | Pmax std/mean between repeats per target ≤ 1.8 % (proposal). Null for dynamic conditions or one round |
| `panels_vs_4P` | 4P Pmax ≤ 1.05 × sum of the four single-panel Pmax in the same round (relay/wiring sanity) |
| `a1_drift` (session) | First vs last A1 scan of the session, mean Pmax per topology; flagged above 5 % (assumption: the protocol gives no limit) |

**Export zip.** `data/<condition>_<target>_u<n>.csv`: the block text exactly as received from the device. `_dibuang/…`: incomplete sweeps. `labels.csv`: one row per file (code, condition, diagnosis, modules, dynamic, topology, repeat, derived values, light, temperatures A–D of that repeat, failed checks, notes). Plus `sesi.json` and `BACA_SAYA.txt`. An emulator session's readme starts with "DATA TIRUAN".

**Scan status** follows its command: `queued` → `running` (first sweep) → `done` / `failed` / `stopped` (Stop, or superseded by Stop). A queued scan expires after 10 s like every actuating command (gateway not running). A running scan may report for `120 s + 20 s per sweep + pauses`.

---

## 13. Proving the targets: MLPE reference, recovery, decision audit

Code: `shadeshift/evaluation.py`; dashboard page **Target vs Bukti**. The definitions are those of the research code (`SHADESHIFT_ML/latih.py`), which produced the proposal's numbers.

| Quantity | Definition |
|---|---|
| Ideal-MLPE power | Sum of the four single-panel Pmax in the same round (each panel at its own maximum, as with one optimizer per panel). Needs firmware 3.1+ |
| % MLPE of a topology | Its Pmax / ideal-MLPE power × 100 |
| Candidates | 4S, 2S2P, TCT. 4P is shown but not a candidate (outside the 24 V controller window, as in the lab and sim claims) |
| AI choice of a scan round | The ESP32's own `# pemilih=` line in that round's 4S sweep (firmware 3.x), otherwise the same selector on the server (`server_onnx` / `server_numpy`) on that sweep |
| Measured best | The candidate with the highest Pmax in that round |
| AI loss | (best − AI choice) / MLPE × 100, in points; without single panels, / best × 100 in % (like the lab claim) |
| Best fixed topology | The candidate with the highest **mean** % MLPE over all usable rounds (an installation is wired once). Chosen in hindsight on the same data, so it is the strongest fixed competitor |
| Recovery | Mean % MLPE of the AI's choices − mean % MLPE of the best fixed topology. Proposal target: ≥ 4 points |

**Usable rounds.** A round needs complete 4S, 2S2P and TCT sweeps and an AI decision. Rounds of dynamic conditions (D2, F1) and rounds whose LDR readings spread more than 5 % are listed with the reason and left out of the summary. Only `source = device` counts as evidence; the emulator has no single panels.

**Live decision audit** (action `audit_decision`, Langsung page): 4S → SWEEP → the AI decides (on the ESP32 with firmware 3.x, laptop cross-check stored as `observe`) → sweep 2S2P, TCT, 4P and, when available, A–D in random order → switch to the AI's choice. The decision is stored with `trigger = "manual"`, `applied = true`; the evaluation stores every Pmax, the MLPE sum, best, chosen and the loss. Audits count as rounds in the evidence.

**Targets** (`GET /evidence`), each with its evidence labeled `measured`, `lab`, `sim` or `calc`:

| Target | Measured evidence | Other evidence shown |
|---|---|---|
| Recover ≥ 4 points of ideal-MLPE power vs the best fixed topology | Recovery from usable rounds with single panels; AI loss vs best fixed in % without them | Lab: 0.82 % vs 2.71 % (no MLPE). Sim: 3.35 points |
| Diagnosis ≥ 85 % on outdoor test data | None until stage 4D; the number of labeled curves per class and place is shown | Sim: 78–82 % |
| Control power ≤ 0.25 W | Multimeter entries on the page: `device_power_w` + `relay_power_w` of the same entry | Calc: relays 1.43–2.50 W, semiconductor design 0.13–0.23 W |
| Decision on the ESP32 within milliseconds | `decision_us` with runtime `esp32` (firmware 3.x `t_us`); laptop times shown separately; end-to-end decision time | — |

"Within milliseconds" is read as p95 below 1 s. A target is "met" only from measured evidence.

---

## 14. Training the AI on measured data

Code: `shadeshift/training/` (dataset, models, pipeline, export); dashboard page **Model AI**. Only numpy and scipy are used (no new dependency).

**Examples.** One example is one round: the same shading seen through 4S, 2S2P, TCT and 4P. Features come from `port_c.py`, the float32 replica of `pemilih.h`, so the ESP32 can compute the same numbers.

| Task | Input | Label | Classes |
|---|---|---|---|
| Diagnosis | 14 shape features of each of the 4 sweeps + Pmax of 2S2P, TCT, 4P relative to 4S (59 numbers) | The scan's diagnosis label (§12) | normal, partial_shading, uniform_dimming, bypass_open, bypass_short, series_resistance |
| Selector | 14 shape features of the 4S sweep (as `pemilih.h`) | The best measured of 4S, 2S2P, TCT in that round | 4S, 2S2P, TCT |

**Sources** (never mixed silently; every report lists rounds per source and class):

| Source | What | Group for the fair test |
|---|---|---|
| `real` | Complete rounds of labeled full scans on a real device; dynamic conditions and rounds whose light changed > 5 % are left out | The scan |
| `lab` | The 30 halogen-lamp rounds (V5 and V1d excluded): V1/V1b/V1c normal, V3_opak partial shading, V3/V4/V6 shade cloth uniform dimming | The shading pattern (V1+V1b one pattern; shade cloth 65/75 % one pattern) |
| `sim` | The research simulator's six-class scenarios (`SHADESHIFT_ML/buat_data_diagnosis.py`, unchanged), `sim_n` per class, seed 5, cached in `<DATA_DIR>/training/` | Never a test set |

**Models.** `logreg`: multinomial logistic regression on standardized features, L2 (the objective of scikit-learn's `LogisticRegression(C=1)`), L-BFGS. `tree`: CART decision tree (Gini), depth-limited. A selector must be `logreg` (the ESP32 runs `pemilih.h`); a topology never best in its training data gets zero weights and bias −1000, so it is never chosen.

**Fair test** (never by repeat: repeats of one shading are near copies, which inflated the old 87–90 %). Evaluation data = real if any, else lab.
- Real data from ≥ 2 days: train on the other days, test on the held-out day (default: the latest). The stored model is the tested one.
- Otherwise leave-one-group-out cross-validation (group = real scan, or lab pattern); with one real day the report says "weaker evidence". The stored model is then trained on all of it.
- If the evaluation source is not a training source (e.g. sim only), the whole evaluation set is the test: the gap between sources.

**Report** (`report_json`): mode, rounds trained and tested per source and class, accuracy, balanced accuracy, recall per class, confusion matrix, classes not tested. Selector: losses of the candidate and of the active selector on the same rounds, and the best fixed wiring (§13 definitions); `better_than_active`.

**Registry and activation.** The shipped selector is registered at server start as active ("shipped with the project"). A diagnosis model is activated by a flag (used by the live diagnosis, stage 4E). Activating a selector requires `better_than_active` (the shipped one can always be re-activated) and rewrites, keeping line endings: `SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h`, `…/uji_pemilih/pemilih_bobot.h`, the expected decisions in `…/uji_pemilih/data_uji.h` (the on-board self-test stays LULUS 12/12), `firmware/shadeshift_firmware/pemilih_bobot.h`, and `models/pemilih.onnx` (+ `.json`, needs the `onnx` package; otherwise the gateway falls back to numpy). The server reloads its selector; the gateway needs a restart and the board a reflash, and the gateway warns while the board's fingerprint differs. Tests that encode the shipped selector's decisions describe the shipped model.

**Shipped baseline numbers through this pipeline** (lab, 30 rounds, leave-one-pattern-out): the shipped selector loses 0.82 % and the best fixed wiring (2S2P) 2.71 %, the published lab claim. Diagnosis on lab data is weak (sim-trained 10 %; lab-trained 37 %, 3 of 6 classes present), which is why real sessions are needed.

---

## 15. Live diagnosis and the module map

Code: `shadeshift/diagnosis.py` (map), `Core.round_diagnosis` (server); shown on Langsung (newest round) and Ambil data (per scan).

**What the topology sweeps can and cannot say.** In this array the 2S2P strings are A+B and C+D (R1, R4) and TCT ties the rows A∥C and B∥D (R6) (`rangkaian/daftar_kabel.md`). Swapping the two strings, or the two rows, leaves all four topology curves unchanged. So the topology sweeps cannot tell WHICH single module is affected, only the **pattern**: `none`, `one`, `string_pair` (A+B or C+D), `row_pair` (A+C or B+D), `diagonal` (A+D or B+C), `three`, `all`. The exact position needs the single-panel sweeps (firmware v2.1 / v3.1). The pattern model is a third task in the registry (§14), labeled from the scan's recorded modules; a non-normal round without recorded modules has no pattern label.

**Per round** (`GET /scans/{id}/diagnosis` → `{ scan_id, condition, label, rounds: [ … ] }`; `GET /devices/{id}/diagnosis` → the newest full-scan round or decision audit, or `null`):

| Field | Content |
|---|---|
| `diagnosis` | Active diagnosis model on the round's 59 features: `class`, `confidence` (logistic regression: probability; tree: share of training rounds in the leaf), `probs`, and the model's `model_id`, `evidence` (what it was tested on), `test_mode`, `balanced_accuracy`. `{ "error": … }` without an active model or without complete 4S/2S2P/TCT/4P |
| `pattern` | Same, from the active pattern model |
| `map` | From the single panels: per module `pmax_w`, `power_rel`, `isc_rel`, `voc_rel` (each relative to the best panel of the round, after dividing by the panel's own A1 value when the session has an A1 scan with all four panels), `status` (`normal` ≥ 0.90, `reduced`, `strongly_reduced` < 0.60), `hint` (Isc < 0.90 → `shaded_or_dimmed`; else Voc < 0.85 → `bypassed_cells`; else `series_resistance`); `affected`, `pattern`, `reference`, `rules`. These rules are not validated yet and say so. `null` without all four panels |
| `agrees` | Whether the pattern model's answer equals the measured map's pattern (null when either is missing) |

The decision audit (§13) also sweeps 4P, so an audit round can be diagnosed. The Target vs Bukti diagnosis target uses the active diagnosis model: "met" only when it was tested on real data on a held-out day with outdoor accuracy ≥ 85 %.

---

## 16. ESP32 web page and on-board diagnosis (firmware 3.2)

Built in `firmware/shadeshift_firmware/` 3.2.0 (`diagnosis.h`, `halaman_web.h`); tested on the laptop with the host simulator (WiFi and WebServer stand-ins), **not yet on the board**. Team guide: `firmware/CARA_PAKAI.md`.

| Addition | Format | Notes |
|---|---|---|
| `DIAG` | Sweeps 4S, 2S2P, TCT, 4P through `pindah()`, then `# diagnosis=<class>, yakin=<0-1>, model=<model_id>, t_us=<µs>`; all relays open afterwards; `# DIAG dihentikan` on OFF/STOP/BATAL or the web STOP; `# DIAG GAGAL: …` otherwise | The 59 features of §14, computed with `pemilih.h` on the printed numbers; Pmax = max V·I of the 201-point curve. For 4S the selector's resampled curve is reused. `t_us` = features + model on the ESP32. Verified equal to the laptop (class and confidence) on lab curves for both model kinds. In the API allowlist (§5.3), so the dashboard's command box can start it; the server also diagnoses full scans and audits itself (§15) |
| Model file | `diagnosis_model.h` (§14 `DIAG_*` arrays + `DIAG_MODEL_ID`; trees also `DIAG_YAKIN`) | Written into the sketch folder when a diagnosis model is activated on the Model AI page. Not shipped: without it `DIAG_ADA = 0` and DIAG refuses |
| `WEB 1` / `WEB 0` | `# WEB ON: WiFi SHADESHIFT, buka http://192.168.4.1 (hanya baca + STOP)` / `# WEB OFF: WiFi mati` | Access point SSID `SHADESHIFT`, WPA2 password `WEB_SANDI` in the sketch (must be changed, ≥ 8 characters). On at boot when `WEB_SAAT_NYALA` is 1. No router, no internet |
| `GET /` | One HTML page, inline CSS/JS, the last I-V curve as inline SVG, dark-mode aware | Nothing loaded from the internet |
| `GET /data` | `{ "fw", "topologi", "r0", "label", "voc", "isc", "pmax", "pemilih", "diagnosis", "yakin", "peringatan", "titik": [[v, i], …] }` (every second point) | Polled every 2 s by the page |
| `POST /off` | `{ "ok": true }` | Sets a stop request: `loop()` opens all relays; inside PILIH, DIAG and SIKLUS it is checked between steps like a serial OFF |
| `INFO` | `…, fitur=panel,cahaya,pemilih,web[,diag]` | `diag` only with a model; the gateway shows `v3.2 (3.2.0)` |

The web server is served from `loop()` and between task steps; it does not answer during a sweep (~3–4 s). The gateway turns a `# diagnosis=` line into an `info` event ("ESP32 diagnosis: …", `decided_by = esp32`) and a measured `diagnosis_us` metric.

---

## 17. L3 (semiconductor switch layer) and the stability rule

Code: `shadeshift/l3.py`, `shadeshift/stability.py`; dashboard page **L3 dan stabilitas**; simulation `SHADESHIFT_ML/uji_stabilitas.py` (new script; `dinamis.py` unchanged).

**L3** is a design with calculations, not built (`SHADESHIFT_ML/saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md`). Holding power = elements kept closed (R0/S0 + the wiring's switches, from the firmware masks) × 0.3575 W per relay coil (assumption: 5 V × 71.4 mA, to be measured) or × 0.033 W per semiconductor cell (LED 10 mA at 3.3 V). Relays: 1.43–2.50 W for 4S…4P (0.72 W for panel A or D alone); semiconductor: 0.13–0.23 W. Only the semiconductor design meets ≤ 0.25 W. Net gain of choosing the wiring (simulation): relays −0.73 W, MOSFET 100 V +0.62 W, 150 V +0.82 W.

| Endpoint | Purpose |
|---|---|
| `GET /l3?device_id=` | Design tables (holding power per wiring, net gain, conduction loss, switch ratings) labeled "calculation", the device's active wiring with its holding power, and the multimeter entries (§13) |
| `GET /stability?source=device` | The rule's default setting, the simulation summary (`hasil/stabilitas_ringkasan.csv`, if run), and a replay on every measured dynamic full scan |

**Stability rule** (team notes 16 Oct; not validated; **off by default**, switch on the Langsung page or with `auto_mode_start` `stability: { enabled, window_s: 30, cv_pct: 10 }`): in auto mode, the Pmax of the monitor sweeps of the active wiring over the last `window_s` seconds (at least 3; default `window_s` = 3 × interval + 1, i.e. the last 3 sweeps) is checked; coefficient of variation > `cv_pct` % → switch to TCT and do not run the selector until it is steady again. Readings restart after every switch. The gateway reports lock and release as events (`trigger = "stability_lock"`, kind `switch` / `info`).

**Evidence.**
- Simulation: the 36 moving-shade scenarios of `dinamis.py` (same seed; fixed TCT reproduces the published 89.6 / 89.2 / 80.9 %), with the gateway's timing: a monitor sweep cuts power for 3 s, a switch 0.6 s, hold 30 s, trigger 20 %, selector assumed perfect; monitor intervals 10 s to 10 min.
- Result (20 Oct): Simulation, 36 moving-shade scenarios with the ~3 s power cut of each monitor sweep: auto mode monitoring every 10 s loses to fixed TCT in all 36; every 5 min it roughly ties fixed TCT (+1.2 / +0.2 / −1.0 points for moving / mixed / leaf shade), so the default interval is now 300 s. The stability rule (window = last 3 monitor sweeps) helps a little on leaf shade (+0.5 at 1–2 min) and hurts on moving and mixed shade (−0.8 to −1.4); it stays off.
- Measured: each dynamic full scan (e.g. F1) replayed round by round: fixed TCT, AI every round, auto mode, auto mode + rule, as % of the best wiring per round (sweep and switch costs not modelled; a switch at most every `window` rounds, like the hold time).

---

## 18. Digital Twin page

Files: `shadeshift/server/static/twin.html` + `twin.js` (plain JavaScript, no library, nothing from the internet), served by the local server at `/twin?device_id=<id>[&mode=whatif]` and embedded by the dashboard page **Kembaran Digital**; markers in `shadeshift/twinview.py`; what-if in `Twin.whatif` (`shadeshift/server/twin.py`). The twin controls left the sidebar (light-scale slider, assumed-shading list, calibrate): calibration and the alert threshold are on this page, and the Shade brush replaces the assumed-shading list.

**Model.** A wireframe of the array as built (`foto/susunan_modul_lampu.jpg`): four landscape panels of 9 × 4 cells (A top-left, B bottom-left, C top-right, D bottom-right) and the control box with relays R0–R10 beside them, drawn by a small orthographic camera. On the back of each panel: its terminal box with the external 1N5822 bypass diode, and a cable under the array to the control box (positions are schematic, not measured).

**Camera.** The user cannot move it (no drag, no tilt). The page turns it, animated in about 0.75 s, only to where a problem lives:

| View | Camera (yaw, pitch) | When |
|---|---|---|
| `top` | 0°, 90° | Default; light problems; What-if always uses it |
| `back` | 180°, −90°: the array turned over like a page, so left and right swap and the rows stay | Click a blue marker whose hint is `bypassed_cells` (voltage down: bypassed cells or diode); or **Lihat punggung panel** on the overview when the AI diagnosis is `bypass_open` / `bypass_short` |
| `cable` | −20°, 30°: low side view | Click a blue marker whose hint is `series_resistance`; or **Lihat kabel dan konektor** when the diagnosis is `series_resistance` |

With a panel in focus the camera zooms to it and highlights its diode (`back`) or cable and connector (`cable`) in the marker's color; the other panels are dimmed. Every view keeps the top view's aspect ratio. **Kembali ke tampak atas** (or **← Ringkasan**) turns it back. Only a panel-level marker (from a single-panel sweep) turns the camera; a pattern or a twin deviation does not, because the place is unknown. URL options for a direct link: `view=top|back|cable` and `focus=A|B|C|D`.

**Two modes, never mixed.**

| Mode | Shows | Data |
|---|---|---|
| Cermin langsung (live mirror) | Active wiring (series links, TCT ties, buses to the box), closed relays, per-panel markers, panel temperatures, last sweep vs the twin's expectation, AI diagnosis and pattern with their validation status; click a panel or marker for its card (single-panel sweep, mini I-V curve, temperature, source) | `GET /api/v1/twin/state?device_id=` every 3 s |
| What-if (SIMULATION) | Shade brush: a circle outline (transparent inside) centred on the pointer, size up to the whole array, solid object or shade cloth; painting covers cells; on release the twin predicts every wiring's Pmax, % of ideal MLPE, the best wiring and the AI's pick on the simulated 4S curve; a log of every try; **Ukur sekarang** runs a live decision audit on the device and shows predicted vs measured per wiring | `POST /api/v1/twin/whatif` |

**Legend** (basic colors, each with an icon and a word): green ✓ healthy, red ☀ power lost to light (current down: shade or dimming), blue ⚡ electrical (voltage or fill factor down: bypassed cells / diode, series resistance), grey dashed ? place or cause unknown. A position is drawn only from single-panel sweeps; a pattern from the topology sweeps marks every panel dashed with the pattern named (§15: string and row swaps look identical); without either, the twin deviation (below `alert_threshold_pct`) marks all panels dashed grey.

| Endpoint | Purpose |
|---|---|
| `GET /twin/state?device_id=` | `{ device, wiring, relays, last_sweep, latest: {target: {pmax, voc, isc, at, source, light_v, points (every 4th)}}, expected, deviation_pct, diagnosis (§15), markers, temps, settings, twin }` |
| `POST /twin/whatif` | `{ "coverage": { "A": [36 shares 0-1], … }, "kind": "solid" or "cloth", "scale": null }` → `{ pmax, modules, mlpe_w, pct_of_mlpe, best, ai, covered_cells, label, ms }`. Cell order = the twin's (index = row × 4 + column of its 4 × 9 grid); the page maps each drawn cell to the twin cell at the same distance from the array centre. A covered cell keeps 2 % of its light (solid, as the twin's opaque case) or the shade-cloth transmission fitted to the lab data. With no coverage the result equals `GET /twin/expected` |

Accuracy: the lab-lamp twin, ~8 % power error on 7 lab conditions; unknown under the sun, even after calibration. Every what-if result says SIMULASI.

---

## 19. Consumer view: Beranda, Kurva I-V, Riwayat (22 Oct)

The dashboard shows three pages in a top navigation bar, white theme, words only (no emoji or pictograms), Indonesian:
**Beranda** (`dasbor/halaman/beranda.py`, embeds the server page `/twin`), **Kurva I-V** and **Riwayat**. The earlier pages
stay in `dasbor/halaman/` but are not in the navigation; add them back to the list in `dasbor/app.py` when needed.
Automatic switching (auto select, auto mode, audit, demo scenarios) is not shown. Demo data is labelled **Mode demo** on
every page; the panel curves of the demo device come from the lab twin and every such sweep carries the line
`# tiruan model=kembaran` in its raw text.

**Measuring.** The gateway action `monitor_start` (`array_interval_s` 30-3600, default 300; `panel_interval_s` 0 or
300-7200, default 1800) measures and never decides or reconfigures: one sweep of the wiring (the active one, or 4S) every
`array_interval_s`, and every `panel_interval_s` a panel check (A, B, C, D alone, then back to the wiring). `monitor_stop`
is a stop action (all relays open). `panel_check` runs one panel check on request. The heartbeat reports `state.monitor`.
The demo device answers A-D with the twin's single-module curve for its lab condition.

**Condition** (`shadeshift/kondisi.py`, in `GET /twin/state` as `kondisi`). Single-panel sweeps within 180 s form a check
round; each round goes through `diagnosis.panel_map` (each panel against the best panel of the round). Rules, not
validated (every cause says "kemungkinan"):

| Measured | Problem | Where the 3D model points |
|---|---|---|
| One panel's current down | Object or dirt on the panel | `surface`: the whole panel darkens (opacity 0.18 plus 0.62 times the light lost against the best panel, at most 0.8) under a red radial glow. The whole panel, because the position on the surface is not measurable (36 cells in series, one bypass diode, the darkest cell sets the current); a small blockage gives a light shade, a large one a deep shade. No illustrations (22 Oct) |
| Its voltage down | Bypass diode or bypassed cells | `diode`: the panel turns see-through, glow at its terminal box and 1N5822 |
| Power down, current and voltage normal | Cable or connector | `cable`: see-through, glow along its cable to the Wago connector |
| All panels alike, array below the twin's expectation by more than `alert_threshold_pct` | Less light everywhere | `sky` when the LDR is below 85 % of its 24-hour median, else `array`; all four panels darken evenly by the array's loss (opacity 0.12 plus 0.6 times the loss, at most 0.7) |

`kondisi` = `{status: {level: ok|problem|offline|nodata, text}, panels: {A: {state, power_rel, pmax_w, at, since}},
problems: [{kind, panel, place, title, where, how_much, since, advice}], array: {topology, pmax_w, vmp, imp, at,
expected_w, pct_of_expected, light_v}, last_check, demo, rules}`.

| Endpoint | Purpose |
|---|---|
| `GET /riwayat?device_id=&hours=24` | `{rounds, timeline: {A: [{at, state, power_rel}]}, array: [{at, topology, pmax_w, expected_w, light_v}], events: [{at, panel, state, text}], summary: [sentences]}`. Durations assume a state lasts until the next check. No energy figure: the rig delivers power only during a sweep |

**The 3D page** (`/twin?device_id=`, `shadeshift/server/static/twin.html` + `twin.js`, plain SVG): a solid model of the
array as built (panels A-D, terminal boxes and diodes at the bottom edge on the back, cables to the Wago strip, control
box), raised three-quarter view; drag to rotate, **Atur ulang tampilan**, click a panel to zoom in, **Lihat bagian
belakang**; callouts with leader lines (power, percent of the best panel, condition); problem cards (what, where, how
much, since, advice); rows for array power, the twin's expectation and the monitoring control. `?panel=A` opens zoomed.
The SVG twin with What-if (section 18) is replaced; `POST /twin/whatif` stays in the API.

---

## 20. Curve analysis, the analyser box, and the house in the 3D view (22 Oct)

**Curve shape analysis** (`shadeshift/analisis_kurva.py`). Rules over measured shape features (the same kind of
features the TinyML models use), compared with a reference when there is one: the twin's **unshaded** curve for the
array (current tolerance 0.85: the twin's power is good to about 8 %, its current near Isc much less; "low current" needs
both current and power below the reference), the best panel of the same check for a panel (tolerance 0.9). Not
validated on outdoor data; every cause says "kemungkinan". The six deviations of the usual field guides:

| Code | Deviation | Rule | Likely causes (as worded) |
|---|---|---|---|
| 1 | Steps (anak tangga) | More than one P-V peak, or a current plateau, a steep drop, then a lower plateau at least 6 % of Voc long | partial shade, local dirt, cracked cell |
| 2 | Low current | Isc and Pmax below the reference | dim light, uniform dust, shade over everything |
| 3 | Low voltage | Voc below 93 % of the reference | shorted bypass diode, damaged cells, heat |
| 4 | Rounder knee | Fill factor 0.08 below the reference (0.6 without one), no steps, no series resistance | ageing, cell mismatch |
| 5 | Shallow slope near Voc | Normalised dV/dI near Voc above 1.8 times the reference (0.3 without one), no steps | loose or corroded cables, connectors, terminals |
| 6 | Current falling from near Isc | Relative drop of current from 3 % of Voc to half of Vmp 0.06 above the reference (0.15 without one), no steps | shunt leakage, uneven light |

Every point of the analysed curve gets the part of the curve it lies in (current region, knee, maximum power point,
voltage region) or, inside a deviation's voltage range, that deviation with its meaning and likely causes: the Kurva I-V
chart shows it when the pointer is near the point. Measured on the 40 lab curves: the unshaded 4S and TCT curves read
normal, every shaded 4S curve shows its step; the unshaded 2S2P and 4P curves under the lamp show small steps (the
lamp's light is uneven between modules).

| Endpoint | Purpose |
|---|---|
| `GET /analisis?device_id=&hours=24` | `{day: {headline, lines}, now: {headline, lines}, basis, demo, curve: {sweep_id, at, topology, source, isc, voc, vmp, imp, pmax, ff, anomalies: [{code, key, title, meaning, cause, v0, v1}], points: [{v, i, bagian, arti, kode}]}, panels: {A: {headline, anomalies}}}` |

**The analyser box** (`umum.kotak_analisis`, on Kurva I-V and Riwayat): an "AI" badge, the 24-hour analysis (wide) and
the current data (narrow), sentences from `/analisis`, and the line saying what the analysis is based on. When the user
opens the page, the box shows a short thinking animation (about 2 s, CSS only) before the sentences appear one by one;
refreshes while the page stays open do not repeat it. No language model runs: everything is local and rule-based, plus
the trained diagnosis model when one is active (section 15).

**The 3D view** now shows the array on a brown roof tilted 24 degrees towards the sun, over half of a house with white
walls (windows, door), the control box on the front wall under the Wago strip. The array and its parts are drawn in roof
coordinates and tilted by `W()`; the tested positions on the roof plane are unchanged. A moving, transparent yellow line
shows the power path (panels, Wago strip, down the wall, control box) while monitoring is on, the device is online and
the newest array measurement is recent; the legend says "Jalur daya, saat pemantauan aktif" (the rig carries current
only during a sweep).

The consumer view always compares with the twin's unshaded array (`Core.expected("none")`), whatever the old stored
"assumed shading" setting says.

**Update (22 Oct, later).** Monitoring is always on: the gateway started by `run.py` begins monitoring about 3 s after it
connects (`SHADESHIFT_MONITOR_AUTO`, default on; the standby demo device and gateways created by tests do not). After a
stop it stays off until someone presses **Mulai pemantauan** (a stop is the safety action before touching the wiring).
While monitoring runs, `panel_check` and the new action `measure_now` are served by the monitoring loop (it measures at
once, and checks each panel for `panel_check`) instead of being refused as busy; without monitoring, `measure_now`
sweeps the active wiring (4S when all relays are open).

The 3D view offers eight roof types that carry the array on their sun-facing slope (**Jenis atap**, remembered in the
browser, or `?roof=`): `pelana` (gable), `perisai` (hip, limasan), `gablet` (Perisai berpelana: hips up to 55 % of the
height, then a small upright gable), `gambrel` (a steep band of 7 x 15 cm below the panel slope, front and back; the
panel slope starts higher and the cable climbs the band), `kampung` (gable with a lean-to porch on posts over the door and
windows, ending left of the control box), `saltbox`, `sandar` (shed) and `datar` (flat, the panels on a tilted rack with
legs). House details are decoration only (nothing that could look like an object shading a panel): roof tiles with
staggered joints, a ridge cap, white fascia and barge boards, a gutter with a downpipe at the right front corner, framed
windows with mullions and sills, a wooden panelled door with a step, a darker plinth and a soft shadow under the eave. Roof colour rgb(244 163 100); young grey walls (#c9d0d8) with darker sides; a dark grey control
box. Close framing (22 Oct, from the user's sketch): seen from the front left (yaw -48, pitch 33) the eave rises to the
right at about 30 degrees; the roof with the panels fills the upper left of the picture, the front wall with the control box
the lower right, and the house's right corner shows against the background with a margin (`targetView()` fits the
panels, the box and that corner; extra width opens to the left). The roof runs 34 cm above the array so the panels sit
mid-slope. Value labels have a white background over the roof. The 3D area is 640 px high (420 px on a phone). The power path is a cable loop (two conductors) drawn on the
model: from the top of the control box up the front wall, over the eave, up the roof surface through the Wago strip,
around the array (each panel has a short lead to it) and back down into the box (`flashTrack()`, `panelLeads()`). Flashes
of light run inside this cable; a new flash leaves the box when the newest one is half way round. Shown while monitoring is on, the
device online and the newest array measurement recent.

---

## 21. Edge AI output on the web page (22 Oct)

With firmware 3.x the selector (`pemilih.h`, TinyML, 73 numbers) runs ON the ESP32 after every 4S sweep and prints
`# pemilih=<4S|2S2P|TCT>, skor=..., t_us=...` in the sweep block. The gateway now forwards this on-board result whenever
no flow posts its own decision: idle, monitoring, a measurement on request and a panel check
(`Gateway.OBSERVING_TASKS`). The server stores it as a decision with `decided_by = "esp32"`, `trigger = "observe"`,
`applied = 0`; the laptop's own result on the same sweep is stored next to it as the cross-check. Since monitoring is always
on and sweeps 4S, every monitoring sweep carries an on-board AI result.

`GET /twin/state` and `GET /analisis` include `ai = {now: {choice, decided_by, latency_us, model_id, captured_at,
sweep_id, applied, on_esp32}, day: {n, by_choice, on_esp32}, esp32: {fw, weights, weights_match, features}, device_kind,
wiring}`. `now` is the newest 4S sweep's decision, preferring the ESP32's over the laptop's. The web page shows it as a
**recommendation** (Beranda row "AI di ESP32 (TinyML)"; the analyser box on Kurva I-V and Riwayat) with where it was
computed and how long it took: "di ESP32", "di laptop (mode demo: ESP32 tiruan tidak menjalankan AI)", or "di laptop
(firmware ESP32 belum memuat model AI)". The consumer view never switches the wiring by itself.

Not on the ESP32 yet: the curve explanation (section 20, laptop) and the diagnosis `DIAG` (needs a model trained on real
data and a round of all four wirings). The ESP32's own Wi-Fi page (section 16) also shows the on-board AI choice without
the laptop.

---

## 22. Jejak audit (audit trail) in Riwayat (22 Oct)

Riwayat has two tabs: **Ringkasan** (the 24-hour view of section 19) and **Jejak audit**: who did what and when, in
Indonesian sentences, for any period ("24 jam", "7 hari", "30 hari", "Semua" or a date range), newest first, 100 lines per
page. Built by `shadeshift/jejak.py` (pure functions) from what the database already holds:

| Source | Becomes |
|---|---|
| `events` (this device and global ones) | one line each; every known gateway/server message has a sentence (`jejak._POLA`); an unknown message gets a generic one ("Galat sistem", "Catatan sistem") and is never guessed |
| `decisions` | one per sweep, the ESP32's preferred over the laptop's cross-check; by default only when the recommendation changes ("AI di ESP32 mengubah rekomendasi dari 4S ke TCT"), compared with the last one before the period |
| single-panel sweeps | panel condition changes (`kondisi.history`), as warnings |
| sweeps and decisions per local day | one line "Ringkasan harian": measurements, panel checks, the AI's recommendations by wiring, power warnings |

Each line has `siapa` (Pengguna for a command queued from the page or the API; AI di ESP32 / AI di laptop; Sistem for the
gateway and the server; Perangkat for what the ESP32 itself reports), `jenis` (Perintah, Perpindahan relai, Keputusan AI,
Peringatan, Galat, Pemantauan, Perangkat, Pengukuran, Catatan, Ringkasan harian), `teks`, `demo` and `asli` (the original
message). Default view: the important lines only (commands, relay switches, warnings and errors, monitoring start and stop,
connection changes, AI changes) plus the daily summary; a power warning repeated within 30 minutes for the same wiring
counts in the summary instead of being listed again. **Tampilkan semua** (`semua=true`) lists every measurement and every
AI result with the time it took. Filter `kategori`: semua, perintah, relai, ai, peringatan (warnings and errors), sistem.

`GET /jejak.csv` downloads the whole period (every entry, oldest first, UTF-8 with BOM) with the columns `waktu, waktu_utc,
siapa, jenis, keterangan, data, pesan_asli`; `data` is "Mode demo" or "Nyata". Demo data (the emulated ESP32) is marked on
every line and in the file. Nothing is deleted: the trail reaches back as far as the database does. The older
`GET /events.csv` (raw events) stays.

---

## 23. Diagnosis AI on the ESP32, shown on the web page (22 Oct)

The firmware's `DIAG` (section 15-16, firmware 3.2) sweeps 4S, 2S2P, TCT and 4P through the safe sequence, computes the 59
numbers, runs the diagnosis model **on the ESP32** and prints `# diagnosis=<class>, yakin=<0-1>, model=<id>, t_us=<time>`,
then opens all relays. It needs `diagnosis_model.h` in the sketch folder (written when a diagnosis model is activated);
the firmware then reports `diag` in `INFO ... fitur=`.

**Gateway action `diagnose`.** Refused at once, with the reason, on the emulator ("does not run the diagnosis AI") and on
a board whose features lack `diag`; otherwise sends `DIAG` and waits up to 120 s for the result or `# DIAG GAGAL`, then
switches back to the wiring that was active. While monitoring runs, the monitoring loop runs it (like `panel_check`).
`diagnosis AI` is an observing task: the ESP32's selector line on the 4S sweep is stored as usual. The result line is
stored as an event with `data = {class, confidence, model_id, t_us, decided_by: "esp32"}`.

**`GET /devices/{id}/diag`**, also `diag` in `GET /twin/state` and `GET /analisis`:
`{available, on_board (true/false/null = not reported), why (Indonesian, or null), now: {class, nama, confidence,
model_id, t_us, at} or null, failed: {at, text} or null, device_kind}`.

| Place | Shows |
|---|---|
| Beranda row **Diagnosis AI di ESP32** | The cause in words (Bayangan sebagian, Cahaya redup merata, Dioda pelewat terbuka, Dioda pelewat terhubung singkat, Hambatan kabel atau sambungan tinggi, Normal), when it was measured, the confidence, the time on the ESP32, and that it judges the whole array; otherwise why it cannot run ("Belum dipasang", "Tidak berjalan" in demo mode). Button **Diagnosis dengan AI** when available |
| Kurva I-V button **Diagnosis dengan AI** | Disabled with the reason when not available |
| Analyser box (Kurva I-V, Riwayat) | "AI di ESP32 menilai penyebabnya: ..." with the panel from the per-panel check beside it; the basis line says where the cause came from or why the AI diagnosis is missing |
| Jejak audit | Important when the cause changes ("AI di ESP32 mengubah diagnosis dari Normal ke Bayangan sebagian"); failures as Galat with the reason in words |

The model judges the **whole array**; which panel is affected comes from the per-panel check, and the page says both.
Until a model trained on real data is on the board, every place says the model is not installed; the emulator never
shows a cause.

---

## 24. Bukti page: promises and targets next to their evidence (22 Oct)

**Out of the navigation since 22 Oct** (the consumer view is for customers; the promises and targets are for the team and judges). The page `dasbor/halaman/janji.py` and `GET /bukti` stay; add the page back to `dasbor/app.py` when the team needs it, or read `GET /api/v1/bukti` directly.

A fourth page in the navigation, **Bukti**, built by `shadeshift/bukti.py` (pure functions) from `Core.bukti_facts()`;
`GET /bukti` returns it with the control-power design tables (`l3.design()`) and the multimeter entries.

**Only data from a real ESP32 counts as proof** (devices of kind `esp32`, sweeps with source `device`). Demo data never
does; with no real board ever connected the page says so. Lab, simulation and calculation numbers are shown under
"Pembanding, bukan bukti". The automatic reconfiguration of the wiring is **left out** (it waits for the Indonesian
standard question); the page adds no switching button.

| Section | Content |
|---|---|
| Janji proposal | Local dashboard, audit trail, the ESP32's own web page (proven when a board reports `web`), the selector on the ESP32 (proven by its decisions, with the median time), the diagnosis on the ESP32 (section 23), the semiconductor layer (design), at least 3 full trial runs. Status: Terbukti, Sebagian, Belum |
| Empat target | Recovery of at least 4 points of MLPE power, diagnosis at least 85 % on outdoor data, control power at most 0.25 W, decision on the ESP32 within milliseconds. Status: Terpenuhi, Belum terpenuhi, Belum diukur; what was measured, the comparisons, and what is still needed |
| Uji coba di papan | Counted automatically per gateway run of a real ESP32. A full trial passes five checks: on-board AI active (firmware 3.x with the same selector weights, from the run's start record or the INFO event up to 30 s before it), an array sweep, an ESP32 recommendation on one of its sweeps, a round of all four panels, a confirmed stop ("Hentikan semua") |
| Daya kendali | Holding power per wiring for relays and the semiconductor design (calculation), the multimeter entries, and a form to record one (ESP32 and relay power, the wiring); refused on the demo device |

The older technical page "Target vs Bukti" (`dasbor/halaman/bukti.py`) stays out of the navigation.

---

## 25. Perangkat page: status of every part of the system (22 Oct)

The fourth page of the consumer view, **Perangkat**, built by `shadeshift/perangkat.py` (pure) from
`Core.perangkat_facts()`; `GET /devices/{id}/perangkat` returns `{ringkasan: {level, text}, grup: [{judul, baris: [{nama,
keadaan, rincian, waktu}]}], demo}`. States: Baik, Perlu dicek, Belum diperiksa, Tidak terhubung, Tidak tersedia, Mati,
Mode demo. **A part is Baik only when a report or a measurement shows it working**; nothing checked yet says Belum
diperiksa.

| Group | Part | From |
|---|---|---|
| Sambungan | Server lokal dan dasbor; Gateway (heartbeat, data waiting in the outbox); ESP32 (port, firmware from INFO, a lost USB connection); AI di ESP32 (INFO weights fingerprint); Halaman Wi-Fi ESP32 (INFO feature `web`) | device row, heartbeat |
| Pengukuran | ADS1115 (I2C 0x48) and MCP4725 (0x60 or 0x62): found by `SCAN`; Jalur arus (Isc, or "GAGAL: arus tidak terdeteksi"). The voltage and light-sensor rows were removed on 23 Oct at the user's request; a voltage out of range ("GAGAL: Voc di luar") still shows under Relai dan kabel susunan | gateway SCAN, sweeps, error events of the last 24 h |
| Saklar dan panel | Relai dan kabel susunan (a measured wiring, or a failed switch); Panel A-D (the newest panel check, section 19) | sweeps, error events, kondisi |
| Pemantauan | on or off with its intervals; the newest measurement, "Perlu dicek" when it is more than three intervals old | heartbeat, sweeps |

An error counts only when no good sweep has followed it. The gateway sends `INFO` and `SCAN` when it connects to a board
(SCAN only reads the I2C bus) and reports the addresses found in its heartbeat (`gateway.i2c = {at, found}`). The button
**Periksa ulang perangkat** sends both again as raw commands (they appear in the audit trail); it is disabled for the demo
device, whose hardware rows all say Mode demo.

---

## 26. The light AI model of the analyser box, and plain words for customers (22 Oct)

`shadeshift/kebiasaan.py` (pure, numpy-free statistics, runs in milliseconds, nothing to install, offline). It learns
what is normal for THIS array from its own measurements of the last 14 days, per wiring: the median and the median
absolute deviation of power divided by the twin's expected power, and, when the sweeps carry the light sensor, of power
divided by the light reading. It judges the newest measurement against the measurements before it (a robust z-score:
normal, lower, much lower, higher than usual); with the light sensor, low power with normal power-per-light means the
light dropped (a cloud), otherwise something may cover the panel. It needs 8 measurements of a wiring first and says so
until then. A trend (Theil-Sen slope, percent of normal per day) is said only over at least one day.

`GET /analisis?sejak=<ISO>` adds `baru = {judul, lines, dari, sampai}`: what is new since that moment (how many
measurements and when, the power change against the last one before it, the model's verdict on the newest, panel changes,
curve-shape signs that appeared or went away); without `sejak`, since the measurement before the newest. Also
`model = {status, persen, n, min_n}` and `terbaru_at`. The dashboard keeps, per page and device, the newest measurement seen
on the previous visit and passes it as `sejak`, so the box says what arrived since the user last looked; within a visit
new data adds up. The analyser box shows it as a full-width **Yang baru** box above the 24-hour and current boxes.

Plain words for a home owner (Kurva I-V, Riwayat, Beranda rows): the six curve signs have plain names
(`analisis_kurva.MUDAH`: Sebagian panel terhalang, Cahaya yang masuk berkurang, Ada bagian panel yang tidak ikut bekerja,
Panel kurang efisien, Sambungan kabel kurang baik, Ada kebocoran listrik di panel) with one plain sentence each; the hover
text uses Bagian datar, Tikungan, Titik daya terbaik, Ujung kanan; "harapan model kembaran" is "perkiraan normal"; wirings
are named seri (4S), seri-paralel (2S2P), silang (TCT), paralel (4P); units are written out (watt, volt, miliampere).
Kurva I-V opens with the AI box, plain cards (Daya sekarang, Dibanding normal, Tanda gangguan, Diukur), power over 24
hours against the normal, and each panel's power as a bar against the best panel; the I-V and P-V curves, the six signs
(with their technical names in small print), each panel's curve and the calibration button are under **Lihat kurva
lengkap**. The basis line under the box says how each part was computed.

---

## 27. Optional: Gemini rewords the analyser box (22 Oct)

The only cloud service in the project, allowed by the user on 22 Oct as an exception to the local-only rule, and only for
this. `shadeshift/ai_teks.py`; on with `SHADESHIFT_GEMINI_API_KEY` (set by the user in `.env`; never committed), model
`SHADESHIFT_GEMINI_MODEL` (default `gemini-flash-latest`, Google's alias for the current Flash model).

- **What it does:** rewrites the sentences of the three boxes of `GET /analisis` (Yang baru, 24 jam, Saat ini) in simpler
  words. The light model (section 26) and the rules still produce every fact, number and verdict.
- **The guard** (`periksa_jawaban`): the answer must be the same three boxes as JSON, plain text without markdown, emoji,
  arrows or %, no more lines than the facts plus one, and **no number that is not in the facts**. Otherwise it is thrown
  away and the local sentences stay.
- **Never blocking:** the call runs in a background thread when the facts change (new data or new time range) and is cached
  by the facts (64 entries); a page refresh never waits. At most one call per 20 s and 1,000 a day; after any failure it
  waits 5 minutes. Timeout 15 s.
- **Offline, no key, refused key, unknown model, free limit reached:** the local sentences, always. `penulis` in the
  response says `gemini` or `lokal`; with Gemini the basis line says the sentences were reworded by Gemini from the
  laptop's results and the numbers were not changed.
- **Privacy:** only the analysis sentences are sent (no device id, no names, no measurements beyond what the sentences say).
  Free-tier content may be used by Google to improve its products.
- **Where it shows:** only in the analyser box (the basis line says when Gemini reworded it). The Perangkat page has no
  Gemini row (removed 23 Oct at the user's request); `Penulis.status` keeps the last state for the server log.

---

## 28. Predictive maintenance on Beranda (22 Oct)

`shadeshift/perawatan.py` (pure) from `Core.perawatan_state()`: the last 14 days of the device and its maintenance log,
cached for a minute per device (recomputed at once after a new sweep or log entry). Also `perawatan` in
`GET /twin/state`, and one line "Perawatan: ..." in the analyser box when something is due.

| Prediction | Indicator (robust Theil-Sen trend since the last maintenance entry) | Said when |
|---|---|---|
| `kotor`: clean the panels | the array's power per light-sensor reading when at least 80 % of the sweeps carry it (clouds do not count), else against the twin's expectation; the most used wiring | it drops at least 1 % of its start per day; due when it reaches 85 % of its level right after the last cleaning |
| `tertinggal`: check panel X | the panel's power against the best panel of each check round | the same, per panel (a log entry for that panel or for all panels resets it) |
| `sambungan`: check the connections | the curve's flatness near its right end (series resistance), on at most ~150 sweeps | it rises at least 5 % a day and is already 1.2 times its start; due at 1.5 times |
| `bayangan`: recurring shade | panel state "object" (section 19) by local hour | the same panel at about the same hour on at least 2 different days; "besok kemungkinan terulang" |

A trend needs at least 3 days and 8 points; otherwise the summary says "Belum cukup data untuk perkiraan: butuh 3 hari
pengukuran, baru N hari". "Segera" when due within 3 days. Every forecast is worded "perkiraan ... sekitar N hari".
The log (events `maintenance: cleaned|repaired [panel=X]`, shown in Jejak audit as "Pengguna mencatat: ...") starts a
fresh baseline; its effect is the median power of the 24 hours after against the 24 hours before.

**Beranda:** a "Perawatan" card right under the 3D stage: the summary, each prediction with "Sekitar N hari lagi",
"Sekarang" or "Berulang", the last log entries with their effect, and the buttons **Saya sudah membersihkan panel** and
**Panel sudah diperbaiki teknisi**. Demo data says so. One scrollbar on Beranda, the main page's: the model's frame does
not scroll; the 3D page (when embedded) hides its own overflow and reports its height to the dashboard with
`postMessage({type: "shadeshift-tinggi", h})` after every render and on resize, and Beranda sets the frame to that height
(only messages from the local server's origin are accepted).

---

## 29. Rekomendasi Rangkaian: wiring changes a person approves (22 Oct)

The fifth page of the consumer view. The user decided on 22 Oct to build it in full, real switching included: the wiring
changes only after a person approves it on this page, never by itself (the automatic modes stay hidden, section 19).

**Gateway actions.** `compare_wirings`: measure 4S, 2S2P, TCT and 4P once each (labels `banding_<time>_<wiring>`), then
back to the wiring that was active; the relays move only to measure (about 20 s). `apply_wiring {target}` (4S, 2S2P or
TCT; 4P is refused: about 20 V, below the 24 V the controller needs): the firmware's safe order (current off, R0 open,
all relays open, the new ones closed, open-circuit voltage checked; on a failed check every relay opens), an event
`wiring <from> -> <to> (approved by the user)`, and one sweep to measure the result. While monitoring runs both are done
by the monitoring loop, and **monitoring then stays on the new wiring** (it no longer switches back). Both are observing
tasks: the ESP32's AI result on the 4S sweep of a comparison is stored. After a gateway restart the wiring starts again
at 4S.

**Recommendation** (`shadeshift/rangkaian.py`, pure): from the newest comparison when it is at most 30 minutes old: the
wiring with the most measured power among 4S, 2S2P and TCT, if it beats the active one by at least 3 percent; the AI's
choice is credited ("AI di ESP32 juga memilih ...") or the disagreement said ("... saran mengikuti pengukuran").
Without a fresh comparison: the AI's newest choice, said as "Belum diukur". Each recommendation has the reason in plain
words (why that wiring copes with the shade), the measured advantage ("Daya terukur naik sekitar 23 persen, dari 0,49
menjadi 0,60 watt"), and the risks for the approval dialog (a power break of a few seconds, the gain holds only for the
current light, voltage and current change, all relays open on a failed check, do not touch the cables: about 88 V).
After an approved change, another change waits 15 minutes; going back to the previous wiring is always allowed.

**Page** (`/rangkaian`, `static/rangkaian.html` + `rangkaian.js`, embedded like Beranda without its own scrollbar): the
four panels in their real positions with their terminals, the wires routed on the base plane, every wire of the shown
rangkaian in that rangkaian's own colour (seri blue, seri-paralel teal, silang violet, paralel orange; the TCT cross-link
dashed; the legend lists only the rangkaian on screen), the control box, and flashes along each wire in the direction the current flows. The wiring comes from the relay matrix (A+
fixed to P, D- to N; 4S R1 R4 R5, 2S2P R1-R4, TCT R1-R4 R6, 4P R2 R3 R7-R10). Before approval: the active wiring, and
"Lihat rangkaian saran" for a preview. After approval the view splits into **Sebelum** and **Sesudah**, each with its
measured power and the change in percent, for an hour or until "Tampilkan rangkaian sekarang saja". Below: the AI
analysis, the measured power of every wiring as bars (4P greyed with its reason), the buttons **Bandingkan semua
rangkaian**, **Terapkan saran** (opens the approval dialog: what will happen and what can go wrong, then "Ya, ubah
rangkaian" or "Batal") and **Kembalikan ke ...**. Jejak audit: "Pengguna menyetujui perubahan rangkaian dari seri (4S)
ke silang (TCT)", then "Relai memindah rangkaian ...".
