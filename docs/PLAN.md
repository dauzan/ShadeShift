# ShadeShift build plan

> **Status 19 Oct 2026:**
> - **Phase 3 done:** Stages 0, 1, 2, 3, 4, 6 and 8 (see [CHANGELOG.md](../CHANGELOG.md)).
> - **Phase 4 (below, waiting for OK):** fulfil every promise of the proposal and the old zip. Build each feature first, then test it with the real data collected from 20 Oct.
> - Stages 5 and 7 of Phase 3 are folded into Phase 4.
> - **20 Oct: one firmware.** v2.1 and the v2 copy were removed from `firmware/`; `firmware/shadeshift_firmware/` holds firmware 3.2 (everything of v2.1 and v3), with one guide `firmware/CARA_PAKAI.md`. The original v2 stays in `docs/before/firmware/`. Mentions of v2.1 / v3 below are the history of how it was built.

## Phase 4: fulfil the proposal (planned 19 Oct)

**Principle.** A promised feature is never dropped because today's data can't prove it.
- It is built now and shows which data its result comes from: simulation, lab (halogen), or real session.
- It is tested with the sessions recorded from 20 Oct.
- Weak results are shown honestly, not hidden.

**Inputs.**
- The proposal (19 Oct copy: three layers, four targets, §6.2 work flow).
- The old zip: `docs/team/UNTUK_DAUZAN.md`, `docs/team/progress.md`, `SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md`, the reports.
- The team's answers of 19 Oct:
  - data sessions both indoors (lamp) and outdoors (sun);
  - conditions and faults as in the proposal and protocol, as much data as possible;
  - LDR and IR thermometer available;
  - **ESP32 web page** wanted;
  - **per-panel sweep** wanted (MLPE reference);
  - simple UI is fine, but every expected feature must exist;
  - the board stays on a firmware close to v2 for the data days.

### Promise → feature map

| # | Promise (source) | Built in |
|---|---|---|
| P1 | Local dashboard: I-V curve, active topology, warnings (§5, §6.2) | Done (laptop); ESP32 page in 4F |
| P2 | Dashboard **on the ESP32** (§5) | 4F |
| P3 | AI on the ESP32 chooses the topology (§6.2) | Done (firmware v3) |
| P4 | AI **diagnoses the cause, 6 classes** (title, §6.2) | 4D (train), 4E (live, gateway), 4F (on the ESP32) |
| P5 | Diagnosis from sweeps **across topologies** (§6.2) | 4B (full scan), 4D, 4E |
| P6 | Recover **≥ 4 points of ideal-MLPE power** vs the best fixed topology (§6.1) | 4A (per-panel sweep), 4C (metric, live audit) |
| P7 | Diagnosis **≥ 85 %** on outdoor test data (§6.1) | 4B (labels), 4D (evaluation on a held-out day) |
| P8 | Control power **≤ 0.25 W** (§6.1) | 4C (power entry), 4G (L3 page) |
| P9 | Decision on the ESP32 within milliseconds (§6.1) | 4C (shows `t_us` when v3 runs; laptop decision time otherwise) |
| P10 | Semiconductor switch layer, Figure 1 (L3) | 4G |
| P11 | Sweep only on a > 20 % power change (§6.2c) | Done (gateway auto mode) |
| P12 | Labeled dataset (~360 curves, natural shade, injected faults; roadmap months 1–2, protocol) | 4A, 4B |
| P13 | Retrain with real data (roadmap; RENCANA D1) | 4D |
| P14 | Model on the ESP32, size and inference time (roadmap) | Done (selector); diagnosis in 4F |
| P15 | Which panel is faulty (PLN clinic; UNTUK_DAUZAN task 5) | 4B (labels), 4E (map), measured with per-panel sweeps |
| P16 | Anti-flapping ✅, stability rule (UNTUK_DAUZAN task 2) | 4G (behind a switch; evaluated on moving-shade data F1) |
| P17 | Technical report: power, latency, accuracy vs target (Bootcamp rules) | 4C |
| P18 | Temperature and light per measurement (protocol) | 4A (LDR), 4B (IR temperatures) |

### Stages (in order; each is tested, committed, and reported, as in Phase 3)

**4A. Firmware v2.1, data collection (needed before the first data session).** **Done 19 Oct** (laptop-tested, not yet on the board; see CHANGELOG).
- v2 plus only additive, low-risk changes:
  - **Per-panel sweep.** Four extra "topologies" `A`, `B`, `C`, `D`, switched by the **same safe `pindah()` sequence** with `nSeri = 1`. Masks from `rangkaian/daftar_kabel.md`: A = R7; B = R2 + R8; C = R3 + R9; D = R10.
  - **LDR on ADS1115 A2.** The `CAHAYA` command and `# cahaya=<raw>, <V>` in every sweep header. This is a relative light level, not W/m².
  - **`INFO`**, so the gateway knows which features the board has.
- No AI. Everything else is byte-for-byte v2.
- Wiring note for the LDR: LDR from 3.3 V to A2, plus a 10 kΩ resistor from A2 to GND.
- Tested here with the host simulator; per-panel curves in the tests are generated with `sim_core` and marked synthetic.
- If the team keeps plain v2, everything still runs; the per-panel and light features say "needs firmware v2.1 or v3".
- Same additions also go into v3.

**4B. Data-collection page and "full scan" (needed before the first data session).** **Done 19 Oct** (tested with the emulator and a simulated v2.1 board; see CHANGELOG and CONTRACT §12).
- **Session:** date, indoor lamp or sun, sky condition, location note, operator.
- **Full scan** (gateway action): the 4 topologies **and** the 4 single panels in random order, with a temperature pause between rounds. A stop at any time ends it safely. Replaces the old `SIKLUS` / `siklus_otomatis`.
- **Labels per scan:**
  - protocol condition code (A1, B1–B7, C1–C5, D1–D2, E1–E5, F1);
  - **diagnosis class** (normal, partial shading, translucent/uniform dimming, open bypass diode, shorted bypass diode, raised series resistance);
  - **affected module(s) A–D**;
  - repeat, IR temperatures of A–D, note.
- **Quality checks:** incomplete sweeps; light change during a scan (LDR, > 5 %); drift of the A1 reference between start and end; spread between repeats (the proposal claims ≤ 1.8 %).
- **Export:** the lab file format named `LR<date>_<code>_<topology>_u<n>.csv` plus `labels.csv`. Raw data is never modified.
- **Database:** sessions, scans, labels, temperatures, light (migration 2).
- **Protocol note for the team:**
  - shade **different modules and pairs** (all old lab data shades module A);
  - fault resistors 5 Ω / 10 Ω;
  - E1 is the control;
  - E5 is the "shorted bypass diode" class;
  - A1 at the start and end of each session.

**4C. Proving the targets live.** **Done 20 Oct** (tested with synthetic panel curves; real numbers from the sessions; see CHANGELOG and CONTRACT §13).
- **MLPE reference:** the sum of the four single-panel Pmax values. For each scan the system shows:
  - each topology as "% of ideal MLPE";
  - the AI's choice;
  - the best fixed topology;
  - the **recovery in points** (the proposal's metric).
- **Decision audit:** after an AI decision, a full scan measures the result live.
- **"Target vs Bukti" page:**
  - the four proposal targets;
  - the evidence for each, labeled by source: recovery points, diagnosis accuracy, measured control power (entry from the multimeter), decision time (`t_us` from the ESP32 with v3, or the laptop), sweep and switch times;
  - CSV export for the technical report.

**4D. AI pipeline on real data (runs as soon as a session exists).** **Done 20 Oct** (built and tested with lab and simulation; no real session yet; see CHANGELOG and CONTRACT §14).
- A dataset builder reads the labeled sessions (plus the old lab data and simulation, kept separate).
- It trains:
  - the **6-class diagnosis model** (decision tree / logistic regression, as in the proposal) from cross-topology features;
  - the **selector** again.
- Train/test is split **by day or condition, never by repeat**; this avoids the leakage the team found before.
- Reports: accuracy, confusion matrix, loss vs fixed topologies, and the sim → real gap.
- **Model registry:** every model version records what it was trained on, its test results, and whether it is active.
- Export to ONNX (gateway) and C headers (ESP32).
- The current models stay as the "simulation" baseline.

**4E. Live diagnosis and localization (gateway and dashboard).** **Done 20 Oct** (the topology sweeps give the pattern, not the position: see CONTRACT §15).
- After a full scan: the diagnosis class, its confidence, the model version and its validation status (simulation-only until real results exist).
- **2×2 module map** (A top-left, B bottom-left, C top-right, D bottom-right):
  - **measured** localization from the per-panel sweeps (Pmax, Voc and Isc of each panel compared with the others and with the A1 reference);
  - plus **inferred** localization from the topology sweeps only (what would scale to a PLN plant without per-panel sweeps), evaluated against the measured one.

**4F. Firmware v3 update and ESP32 web page.** **Done 20 Oct** (v3.2, laptop-tested; not yet flashed; see CHANGELOG and CONTRACT §16).
- v3 gets the 4A additions, plus:
  - the **diagnosis model in C**: a `DIAG` command runs the cross-topology scan and prints `# diagnosis=…`;
  - an **ESP32 web page**:
    - its own WiFi access point "SHADESHIFT" (no router, no internet, password set in the sketch);
    - http://192.168.4.1 shows the last I-V curve (inline SVG, no CDN), the active topology, the AI decision and warnings;
    - the page is read-only, plus an OFF button; switching stays on the laptop or serial;
  - a WiFi on/off switch in the sketch, so the AP can be disabled if it disturbs measurements.
- Tested with the host simulator (WiFi and web stubs).
- The team flashes it when the board is free.

**4G. L3 page and stability rule.** **Done 20 Oct** (rule built and evaluated: off; auto-mode interval now 5 min; see CHANGELOG and CONTRACT §17).
- **L3 page:** Figure 1 data (relay vs MOSFET holding power, net gain) from `SHADESHIFT_ML/saklar/*.csv`, labeled "calculation". Plus live: "holding power of the active topology", and the measured relay power when entered in 4C.
- **Stability rule** (lock TCT while power fluctuates): built behind a switch and evaluated on the moving-shade session (protocol F1). It stays off unless the data supports it.

**4H. Docs, demo scenarios from real sessions, rehearsal checklist.** **Done 21 Oct as documentation only** (`docs/PROMISES.md`, at the team's request); the demo replay of real sessions was not built.
- Demo mode can replay the new real sessions, including per-panel sweeps.
- README, START_HERE and CHANGELOG updated.

### Order and data dependency

| Stage | Can be built and tested now with | Gets real numbers from |
|---|---|---|
| 4A | Host firmware simulator | The first session (per-panel curves, LDR) |
| 4B | The emulator plus synthetic single-panel curves (tests only) | Every session |
| 4C | Old lab data (no MLPE reference) and synthetic per-panel curves | The first session with per-panel sweeps |
| 4D | Simulation data, existing lab data | The labeled sessions; a held-out day for the test |
| 4E | Same as 4D | Sessions with faults and varied module positions |
| 4F | Host simulator | The board |
| 4G | Existing calculations; old simulation for the stability rule | Measured relay power; moving-shade session |

4A and 4B come first because the data sessions start on 20 Oct.

### Decision needed from the team
- **Firmware for the data sessions:**
  - v2.1 (recommended: v2 plus per-panel sweeps and LDR, no AI; per-panel and light data get recorded);
  - or plain v2 (no per-panel sweeps or light readings in the data; the MLPE metric and measured localization can't be computed from those sessions).
- The LDR needs one fixed resistor (10 kΩ suggested) and a wire to A2.

---

# Phase 3 (done)

Goal: a demo for Smart-X Demo Day (21–23 Oct 2026) that runs 100 % locally, free and offline. Data flows device → edge → server → dashboard as defined in [CONTRACT.md](CONTRACT.md), and every gap marked P0 in [ANALYSIS.md](ANALYSIS.md) is closed.

Stages are ordered so that **missing features come first**, and every stage leaves a working, demonstrable system. After each stage I:
1. run its tests;
2. fix what fails;
3. commit;
4. tell you briefly what changed and how to verify it.

A feature that cannot be finished now gets a real foundation (code, interfaces, config, tests where possible) and is labeled **Foundation** in the code, the docs and the UI. Nothing fake is presented as real.

---

## 1. Decisions taken (with reasons)

| # | Decision | Why |
|---|---|---|
| 1 | **Restore the working tree** from `docs/before/` into the root: `SHADESHIFT_ML/`, `firmware/`, `rangkaian/`, `foto/`, `UNTUK_DAUZAN.md`. Copy, don't move; `docs/before/` stays an untouched snapshot | The dashboard was built to sit next to `SHADESHIFT_ML/` (ANALYSIS R1/B1). Restoring makes it run with **zero code changes** and gives the team a place to edit the firmware. The six large simulation CSVs (~75 MB, research only) stay in `docs/before/` and the zip; a script copies them back if retraining is needed |
| 2 | **USB serial + laptop edge gateway**, no WiFi in v1 | Your decision (18 Oct). Works with today's firmware |
| 3 | **FastAPI + uvicorn + SQLite (stdlib `sqlite3`)** for the server | Built-in validation, WebSocket and OpenAPI. Free and local. uvicorn, starlette, websockets and python-multipart are *already installed* as Streamlit 1.66 dependencies, so only `fastapi` and `pydantic` are new. No ORM: one small module with the SQL from CONTRACT §10 |
| 4 | **Keep Streamlit** for the dashboard, turned into a pure API client | It works and the team knows it. Moving serial ownership to the gateway removes the "refresh locks the COM port" risk (B2) |
| 5 | **Edge AI = feature extraction (C-identical Python) + ONNX Runtime**, with the ONNX file **generated from `pemilih_bobot.h`** | One source of truth for ESP32, gateway and server. Parity with C on 38/38 lab curves is a test. TFLite is not needed for a 73-float linear model |
| 6 | **Reuse `koneksi.py` as the gateway core**: serial reader, sweep assembly, emulator, auto-select, auto mode | It already does 80 % of the gateway's job and passes its self-test. We add hooks, timing capture and the server uplink instead of rewriting |
| 7 | Move `dasbor/inti.py` and `dasbor/koneksi.py` into a shared package `shadeshift/`. Leave **one-line shims** in `dasbor/` | Gateway, server and dashboard import the same code; `dasbor/uji_dasbor.py` and team scripts keep working |
| 8 | Firmware v3 (on-device selector) is built as a **Foundation**: written and unit-checked here, verified on the board by the team | No board here. `arduino-cli` + esp32 core is a heavy install (§3) |
| 9 | **Language**: docs in English; new platform code (API, DB, gateway, server) uses English names; existing Indonesian modules keep their style; the **dashboard UI text stays Indonesian**, as today | You write to me in English; the team, judges and the existing UI are Indonesian. Say if you want otherwise |
| 10 | `docs/before/CLAUDE.md` is **not** restored to the root | It instructs AI assistants to reply in Indonesian, which would change how future sessions answer you. I can add an English `CLAUDE.md` with the project rules if you want |
| 11 | **Raw-command allowlist** on the server (CONTRACT §5.3). `RELAI`, `UJIRELAI`, `DAC`, `CEKVOC 0` and `SIKLUS`/`LANJUT`/`BATAL` are blocked from the dashboard. A gateway-run `cycle` action and an always-available `stop` replace SIKLUS | The firmware accepts `RELAI`/`UJIRELAI` whenever no topology is active, i.e. with panels attached; its docs say "only without panels". During SIKLUS the firmware ignores `OFF` (ANALYSIS F1, safety). Bench work stays in the Arduino Serial Monitor |
| 12 | **The real-device path is the primary demo. Demo mode is a clearly watermarked fallback** | Official rubric: a live prototype "without critical bugs or workarounds" is 25 % of the Demo Day score (ANALYSIS summary point 9). Replayed data must never pass as live |

---

## 2. Stages

**Order agreed on 18 Oct (overrides the numbering below):**
1. Stage 2: gateway, with only the Stop safety fix from the review.
2. Stage 3: dashboard on the server, plus the CSV upload page.
3. Stage 4: demo mode.
4. Stage 6: firmware v3, the TinyML part (the model running on the ESP32).
5. Stage 8: start guide and docs.

Stages 5 and 7 and the remaining review polish come only if time allows.

Effort: **S** < 1 h, **M** 1–3 h, **L** > 3 h of build time. P0 = demo-critical, P1 = strengthens judging, P2 = foundation.

### Stage 0: Runnable baseline and repo hygiene (P0, S–M)

Prerequisite for everything.

- `git init`, plus a `.gitignore` covering `.venv/`, `.cache/`, `data/`, `wheels/`, `__pycache__/`, the zip, and the large simulation CSVs in `SHADESHIFT_ML/data/` and in `docs/before/`.
- Restore the working tree (Decision 1). The lab data in `data_lab/` must stay **byte-identical**; a test checks hashes against `docs/before/`.
- Root `requirements.txt` with pinned versions (streamlit 1.66.0, pvlib 0.16.1, pyserial 3.5, numpy, pandas, scipy as installed), plus `requirements-dev.txt` (pytest). `dasbor/requirements.txt` becomes `-r ../requirements.txt`.
- `.streamlit/config.toml`: `browser.gatherUsageStats = false`, `client.toolbarMode = "viewer"` (no Deploy button), `server.headless = true` (B4).
- `shadeshift/config.py`: reads env vars and `.env` (CONTRACT §9). `.env.example` is added.
- `tests/test_baseline.py`: the 3 existing `uji_dasbor.py` checks as pytest tests, plus a raw-data integrity test.
- Fix the README install order (R2). Re-copy the current weights into `uji_pemilih/` in the **working copy** (D2).

**Verify**
- `python -m pytest -q` passes.
- `python dasbor/uji_dasbor.py` prints `SEMUA LULUS` in place.
- `streamlit run dasbor/app.py` serves HTTP 200 (headless smoke test).

**Done when** the original dashboard runs from this folder, offline, with no Deploy button.

**Commit:** `Stage 0: restore runnable baseline, pin deps, offline Streamlit config, tests`

### Stage 1: Local server: SQLite + ingestion API + WebSocket + test publisher (P0, L)

Closes M1 and M2 ★ (no ingestion port, no persistent storage).

- `shadeshift/server/`:
  - `db.py`: schema v1 and migrations, WAL;
  - `models.py`: pydantic shapes from CONTRACT §5;
  - `app.py`: the routes of CONTRACT §5.1–5.7 (ingest, heartbeat and runs, commands with long-poll, reads, snapshot, uploads, lab import, twin, settings, `/stream` WebSocket, health);
  - `csv_import.py`: firmware and plain CSV parsing and validation (§6);
  - `twin.py`: twin wrapper with cache; degrades to "unavailable" without pvlib.
- `/docs` served without any CDN, or disabled (CONTRACT §5.1).
- Optional write token (`SHADESHIFT_API_TOKEN`).
- Test publisher `tools/publish_sample.py`: heartbeats as `publisher-01`, posts lab sweeps as `source=demo` with `replay_of`, and prints the server's derived Pmax.
- `tools/ws_monitor.py`: prints the live stream.
- `samples/`: good and bad CSV examples (firmware format, plain `V,I`, `I_mA`, too few points, non-numeric).

**Tests** (`tests/test_server_*.py`, FastAPI TestClient):
- ingest → read round trip;
- idempotent UUIDs;
- 404/409 rules;
- long-poll commands;
- WebSocket receives `hello` + `sweep`;
- token on/off;
- limits;
- upload good/bad/duplicate;
- lab import of 120 files with `data_lab` unchanged;
- derived Pmax equal to `inti` (lab numbers reproduced from DB rows).

**Verify:** `python run.py server`, then `python tools/publish_sample.py` and `python tools/ws_monitor.py`. Check `/api/v1/health` in a browser.

**Commit:** `Stage 1: local FastAPI+SQLite server with ingestion, commands, uploads, WebSocket stream`

### Stage 2: Edge gateway + edge AI on ONNX Runtime (P0, L)

Closes M3 ★ and part of S2 (edge AI missing; decisions not labeled).

- `shadeshift/edge/`:
  - `export_onnx.py` builds `models/pemilih.onnx` + `.json` from `pemilih_bobot.h` (needs `onnx`, used only for generation);
  - `selector.py` provides `EdgeSelector.decide(sweep)`, which returns choice, scores, features, latency_us, decided_by and model_id. It uses ONNX Runtime, or the numpy fallback when the hash mismatches or the runtime is missing.
- `shadeshift/gateway/`:
  - `main.py` with `--source serial|demo`;
  - `uplink.py`: heartbeat every 2 s, outbox (SQLite) with retry and backoff, batched log/events/metrics;
  - `commands.py`: long-poll, then executes raw commands or actions;
  - timing capture (`switch_ms`, `sweep_ms`, `decision_us`, `e2e_decision_ms`, provenance `measured` or `emulated`);
  - a selector decision on every 4S sweep (`observe`);
  - `auto_select` and auto mode run here, reusing `koneksi.py`;
  - `cycle` and `stop` actions (Decision 11);
  - the gateway checks of CONTRACT §3.2: completeness, response matching, `STATUS` sync on connect, failure hints (ANALYSIS B10, B11, F4, F5);
  - `SHADESHIFT_SERIAL_PORT=auto` detects the ESP32 by USB id and never assumes COM3 (B12).
- `run.py` with subcommands `server | gateway | dashboard | demo | live | test | check | ports | import-lab` (dashboard wiring lands in Stage 3).

**Tests:**
- ONNX vs numpy vs C parity (38/38, |Δscore| ≤ 1e-4);
- fallback when onnxruntime is absent;
- end-to-end with the emulator: server in-process + gateway → `auto_select` → DB holds 2 sweeps + 1 applied decision `gateway_onnx`;
- outbox: server down → queue → server up → flushed exactly once.

**Verify:** `python run.py server` + `python run.py gateway --source demo`, then send `auto_select` from `tools/` and watch `ws_monitor`.

**Commit:** `Stage 2: edge gateway (serial/emulator) with ONNX Runtime selector, outbox and commands`

### Stage 3: Dashboard on the API + CSV upload page + one-command start (P0, L)

Closes M4 ★, B2 and S2 (no CSV upload page; refresh/tab can lock the COM port; selector decision not labeled with where it ran).

- `dasbor/app.py` becomes a multipage app using `st.navigation`, with pages:

| Page | Contents |
|---|---|
| **Langsung** (Live) | Device picker with online status; DEMO banner for emulators; topology / SWEEP / OFF / STATUS / free-command buttons sent as commands; auto-select; auto-mode settings; metrics with **"decided by: gateway (ONNX Runtime) / ESP32"** and latency; I-V and P-V charts with the dashed twin curve; history; alerts; serial log |
| **Putar ulang** (Replay) | From the DB: lab import, recorded runs, uploads; same charts; lab summary table (0.82 / 2.71 / 4.30 / 12.0 %, lab) |
| **Unggah CSV** (Upload CSV) | Multi-file upload to `/uploads`; per-file result table (accepted/rejected with the reason); curves; selector decision (`server_onnx`); link to Replay |
| **Peristiwa** (Events, audit trail) | Every command, switch, decision, alert and error with timestamps; filter; CSV export (`/events.csv`). The organizers' L1 definition asks for an audit trail |
| **Status** | Health of server, gateway, twin and model; provenance legend |

- Safety in the UI:
  - a **Stop** button on every page;
  - a "≈88 V DC on 4S" warning next to the topology buttons;
  - 4P marked "manual only" (the selector never outputs it);
  - blocked commands explained, not silently dropped.
- Demo devices get a watermark on every chart and table ("DEMO — replayed lab data"), not only a banner (Decision 12).

- Twin settings, calibration and the alert threshold move to server settings, shared by all tabs.
- The dashboard no longer opens serial ports. The old direct mode is retired; `firmware/logger_shadeshift.py` stays for manual use.
- `run.py demo` and `run.py live` (ESP32 port auto-detected; `--port COMx` overrides) start server + gateway(s) + dashboard, open the browser, and stop everything on Ctrl+C. `run.py check` validates Python, packages, ports, model, lab data and pvlib.

**Tests:**
- Streamlit `AppTest` runs each page against a live test server and checks there are no exceptions and key elements are present;
- upload end-to-end with `samples/`;
- two simultaneous dashboard sessions do not interfere.

**Verify:**
- `python run.py demo` opens the dashboard.
- On Live with `demo-01`, press auto-select and watch the switch.
- On Upload, drop `samples/*.csv` and check accepted and rejected files.

**Commit:** `Stage 3: dashboard as API client (live, replay, CSV upload, status) and one-command start`

### Stage 4: Demo mode (P0, M)

★ Realistic data with no hardware; safety net for the presentation.

- `shadeshift/gateway/demo.py`: scenario player for `scenarios/*.json` (CONTRACT §6.4) on top of the emulator. It validates conditions, supports `speed`, loops, and starts auto mode.
- Ships `scenarios/default.json`, `scenarios/kilat.json` (a short 60 s version for rehearsals) and `scenarios/v6_kelemahan.json` (shows the selector's known weak case honestly).
- `run.py live` also starts `demo-01` in **standby**, so the dashboard can switch to it instantly if the hardware fails.
- Persistent DEMO banner, plus `source=demo` and `replay_of` in every table.
- Live-page controls for the demo device: condition picker, scenario start/stop, speed.

**Tests:**
- the scenario loader rejects unknown conditions;
- a 20× speed scenario produces the expected sequence of conditions and switches in the DB;
- standby demo does not send sweeps until started.

**Verify:** `python run.py demo` → Live → `demo-01` → start the `kilat` scenario. Within about 60 s you see condition changes, re-selection and the switch history.

**Commit:** `Stage 4: demo mode with scenario playback and standby demo device`

### Stage 5: Edge control logic + technical-report metrics (P1, M–L)

Closes M6, M7 and RENCANA E1 (no latency measurements; no stability rule; no "power vs fixed topology" view).

- `shadeshift/edge/rules.py` holds pure, unit-tested functions:
  - the trigger + hold rule (existing logic);
  - the **stability rule** (lock TCT when the coefficient of variation of Pmax over a window exceeds a threshold), labeled "not validated in sim yet".
  - The gateway auto mode uses these functions.
- `audit_decision` action: sweep 4S, 2S2P and TCT and store an evaluation. This yields a live **measured loss** of the selector on the actual setup; in demo it reproduces lab numbers from replayed data.
- **Technical** page (Laporan teknis):
  - latency table (switch, sweep, decision, end-to-end) with n / mean / p95 / max and provenance;
  - accuracy claims with sim/lab labels;
  - audit results;
  - a **manual entry** form for measured ESP32 + relay power (W), since there is no power sensor, and for panel temperatures (IR thermometer);
  - "gain vs 4S" and "gain vs best fixed (2S2P)" per audit, labeled;
  - **targets vs evidence**: each proposal target (≥ 4 points recovery, ≥ 85 % outdoor diagnosis, ≤ 0.25 W control power, millisecond decisions) next to the current evidence and its label. "Not measured yet" until a real measurement exists (ANALYSIS §7.2);
  - a **TKT card**: current level 4 (team rule), the next step after the sun session, and the roadmap target.
- Stability-rule evaluation in `dinamis.py` is added as a **Foundation**: a policy function plus a TODO run command (CPU-heavy simulation, can run overnight).

**Tests:**
- rule unit tests (trigger, hold, stability, release);
- audit end-to-end in demo;
- metrics summary math.

**Verify:** start the `kilat` scenario, then open the Technical page and check latency stats and audit losses.

**Commit:** `Stage 5: edge auto-mode rules incl. stability lock, decision audit, technical report page`

### Stage 6: Firmware v3 Foundation, on-device edge AI (P1, M)

Toward M3 on the ESP32 itself.

- `firmware/shadeshift_firmware_v3/` is a copy of v2 with:
  - the sweep stored in arrays;
  - `pemilih.h` run after 4S sweeps;
  - `# pemilih=…, skor=…, t_us=…`;
  - an `INFO` command;
  - `# meta t_ms=…, seq=…`;
  - a `TAHAN` hold-at-MPP monitor, **marked "check heat on hardware first"**;
  - the safe switching sequence **unchanged**;
  - current weights copied in;
  - firmware fixes from ANALYSIS §7.1:
    - `OFF`/`BATAL` also work inside SIKLUS, between steps and at the prompts (F1);
    - a failed sweep inside SIKLUS stops the cycle (F3);
    - `DAC` refused while R0 is closed, and negative values rejected (F2);
    - `RELAI`/`UJIRELAI` need an explicit `BENCH 1` mode (F2).
- Gateway parser support for the v3 lines: a device decision is stored as `decided_by=esp32`, and the gateway's own ONNX decision is stored next to it, with disagreement flagged.
- `firmware/CARA_PAKAI_v3.md` and a **hardware checklist** for the team: flash `uji_pemilih` (expect `LULUS 12/12`), then v3, then `run.py live`, and check timings.
- Parser tests use **clearly marked synthetic** v3 lines. The emulator does **not** fake `# pemilih=` lines.
- Compile check only if you approve installing `arduino-cli` + esp32 core (§3). Otherwise the team compiles in Arduino IDE.

**Commit:** `Stage 6: firmware v3 foundation (on-device selector, INFO, meta, TAHAN) + parser support`

### Stage 7: P2 foundations: localization, L3, export, MQTT (P2, M–L)

- **Fault localization (PLN)**, `shadeshift/edge/localize.py`:
  - twin matching: compare measured Pmax across the 4 topologies with twin predictions for "module X / pair X+Y shaded" candidates and rank modules A–D;
  - evaluated on the lab sets with known shading (V3: A, V4: A+B, V6: A+D) and reported **as lab, 6 patterns**;
  - shown as "experimental" on a 2×2 module map (A top-left, B bottom-left, C top-right, D bottom-right) in the Live page; the map reads "not available" when there is no 4-topology data;
  - if it does not beat chance on lab data, it ships as interface + TODO only, and we say so.
- **L3 page**: relay vs semiconductor holding power and net gain from `SHADESHIFT_ML/saklar/*.csv`, labeled "calculation, not measured".
- **Session export**: `GET /runs/{id}/export` (ZIP: firmware-format CSVs + decisions + metrics) for the technical report.
- **MQTT bridge (optional)**: `tools/mqtt_bridge.py` maps `shadeshift/<device>/sweep` to the HTTP ingest when `paho-mqtt` and a local Mosquitto exist. Its test is skipped otherwise. It stays a Foundation; nothing depends on it.

**Commit:** `Stage 7: P2 foundations (localization experiment, L3 page, export, optional MQTT bridge)`

### Stage 8: Packaging and docs (P0, M)

- `scripts/setup.bat` / `setup.ps1`: create `.venv` on the project drive, install from `requirements.txt`, or with `-Offline` from `wheels/`.
- `scripts/make_wheelhouse.bat`: `pip download` everything into `wheels/` once, for laptops without internet.
- **Offline USB kit** list in `START_HERE.md`. All are free; download them once while online:
  - Python 3.12 installer (python.org);
  - `wheels/`;
  - the Microsoft Visual C++ Redistributable, which ONNX Runtime needs on some fresh Windows installs. Without it the gateway falls back to numpy automatically and says so;
  - the ESP32 USB-serial driver (CP210x or CH340, depending on the board), because Windows may otherwise try Windows Update for it.
- `start_demo.bat` and `start_live.bat`: double-click starters.
- **Fresh-venv test**: build a new venv from `wheels/` with no network, then run `run.py check` and `run.py test`.
- `README.md`, `START_HERE.md` and `CHANGELOG.md`, covering:
  - what is complete vs Foundation;
  - how to run everything from a fresh laptop;
  - assumptions;
  - what you need to provide;
  - a **Demo Day runbook**: bring the halogen lamp; one unshaded sweep + "calibrate twin"; set `VPANEL` if the Voc check fails; the shade-cloth anomaly demo; how to switch to `demo-01` in one click if hardware fails;
  - a **"claims to avoid"** list (ANALYSIS §7.2 and §9).
- Update the dashboard README; add a new entry at the top of `progress.md`'s Log (team rule); update ANALYSIS §12.

**Commit:** `Stage 8: setup scripts, offline wheelhouse, README/START_HERE/CHANGELOG`

### Demo-critical path

Stages **0 → 1 → 2 → 3 → 4** are the minimum for a reliable offline demo. Stages 5–7 strengthen judging and can be trimmed if time runs out. Stage 8 is always done.

---

## 3. Dependencies to install (your approval needed)

All go into `D:\ShadeShift\.venv`. pip cache and temp files stay on D:.

| Stage | Package | Size (approx.) | Runtime or dev | Note |
|---|---|---|---|---|
| 0 | `pytest` 9.1.1 | 1 MB | dev | |
| 1 | `fastapi` 0.143.3 (+ `pydantic`, `pydantic-core`, `annotated-types`) | 5 MB | runtime | uvicorn, starlette, websockets and python-multipart are already present |
| 1 | `httpx` | 1 MB | dev | Needed by FastAPI's TestClient |
| 2 | `onnxruntime` 1.31.0 | 15 MB wheel, ~45 MB installed | runtime | Edge AI runtime |
| 2 | `onnx` 1.23.2 | 15 MB wheel | dev | Only to generate `pemilih.onnx`; the generated file is committed |
| 6 | `arduino-cli` + esp32 core + 2 Adafruit libraries | **0.5–1 GB, heavy** | dev, optional | Only for compile checks. **I will ask separately** |
| 7 | `paho-mqtt` 2.1.0 | < 1 MB | optional | Only if you want the MQTT foundation exercised; Mosquitto itself is not installed |

Already installed with your approval: streamlit 1.66.0, pvlib 0.16.1 and pyserial 3.5, with their dependencies. That is 535 MB of venv plus 145 MB of pip cache on D:. The cache can be deleted; it is bigger than my earlier estimate.

**Compatibility, checked against PyPI metadata (18 Oct):** no conflicts with what is installed.
- fastapi 0.143.3 needs `starlette>=0.46` and `pydantic>=2.9`; Streamlit allows `starlette<2`, so the installed 1.8.0 fits both.
- onnxruntime 1.31.0 needs `protobuf>=4.25.8` and `numpy>=1.21.6`; onnx 1.23.2 needs `protobuf>=6.31.1` (installed: 7.36.2).
- New small transitive packages: `typing-inspection`, `annotated-doc`, `pydantic-core`, `flatbuffers`, `ml_dtypes`, `httpcore`, `pluggy`, `iniconfig`, `colorama`.

---

## 4. Traceability: ANALYSIS findings → stages

| Finding | Stage |
|---|---|
| R1/B1 not runnable in place; M5 one-command start | 0, 3, 8 |
| R2/B3 install order and version pin; B4 telemetry/Deploy | 0 |
| M1 ingestion port ★; M2 storage; M8 ids and timestamps; M9 health | 1, 2 |
| M3 edge AI ★; S2 labeling of where decisions run | 2, 3, 6 |
| M4 CSV upload page ★ | 1 (endpoint), 3 (page) |
| Demo mode ★; S1/S6 honest emulator labeling | 2, 4 |
| B2 COM-port lock | 2, 3 (gateway owns the port) |
| M6 technical metrics; M7 stability rule; RENCANA E1 | 5 |
| D2 stale weights in `uji_pemilih` | 0 (working copy), 6 |
| D1, D3–D9 doc inconsistencies | 6 (firmware docs), 8 (others, noted in docs, originals untouched) |
| M10 localization; M11 L3; M13 export | 7 |
| B5 `None` topology after a short sweep; B6 emulator interleaving | 2 (gateway guards; emulator serializes commands) |
| B7 no metadata in saved sweeps | 1, 2 (DB stores time, device, run, provenance) |
| B8 shade-net (paranet) transmission 0.137 vs 0.11 | 8 (documented; the twin uses the computed 0.137) |
| B9 dashboard sweeps missing from replay | 1, 3 (replay reads the DB, not file names) |
| B10 state not synced; B11 wrong-line matching; B12 COM3 default | 2 |
| F1 OFF ignored during SIKLUS (safety) | 1 (blocked from API), 2 (`cycle`/`stop`), 6 (firmware fix) |
| F2 unguarded DAC, RELAI with panels attached | 1 (blocked from API), 6 (firmware guards) |
| F3 dead sweep-failure check; F5 undetected data loss | 2 (completeness check), 6 (firmware fix) |
| F4 dim-light failures | 2 (failure hints), 8 (runbook) |
| F6 hardware fragility | 4 (standby demo fallback), 8 (runbook) |
| F7 nominal calibration constants | 8 (documented; "absolute watts uncalibrated" note) |
| §7.2 claims to qualify; L1 audit trail; targets vs evidence | 3 (Events page), 5 (Technical page), 8 (claims-to-avoid list) |
| M12 tests | every stage |

---

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| No hardware here, so the serial path is only proven against the emulator | The emulator speaks the exact v2 line protocol. Real-firmware samples (lab files) are parser tests. The team gets a hardware checklist (Stage 6). Anything untested on hardware is labeled so |
| Little time before 21 Oct | P0 path first (Stages 0–4). Each stage is committed and runnable. P1/P2 can be cut without breaking anything |
| Port 8000 or 8501 already in use on the demo laptop | Both are configurable. `run.py check` reports conflicts |
| Twin unavailable (pvlib missing or broken) | Dashboard and alerts degrade to "expected power unavailable"; everything else works. The twin is fast (≈0.15 s per simulation, one-time 3.3 s calibration) and cached |
| Streamlit API drift | Exact pins. `AppTest` smoke tests in CI-style `run.py test` |
| PowerShell execution policy blocks `.ps1` | `.bat` starters; `.ps1` called with `-ExecutionPolicy Bypass` from the `.bat` |
| Honesty slip (demo data or laptop decisions shown as device results) | Enforced in the schema (`source`, `decided_by`, `provenance` CHECK constraints) and shown on every page. Tests assert the labels |
| Demo-day mishap (refresh, second screen, unplugged cable) | Dashboards are stateless API clients. The gateway reconnects. The standby demo device takes over in one click |

---

## 6. What I need from you

**Now:**
1. OK for this plan and the contract.
2. OK to install the Stage 0–2 packages in §3: pytest, fastapi, httpx, onnxruntime, onnx. All small or medium.

**Later:**
- **Stage 6:** OK or not for `arduino-cli` + esp32 core (heavy). Without it, you compile the v3 sketch in Arduino IDE.
- **Before Demo Day (only you can do these):**
  - the real COM port name;
  - running the hardware checklist with the ESP32 (flash `uji_pemilih`, then try `run.py live`);
  - measuring ESP32 + relay power with a USB meter or multimeter and entering it on the Technical page;
  - optionally flashing firmware v3 for on-device decisions.
- Decisions 9 and 10 in §1 (UI language; English `CLAUDE.md`), if you want them changed.

## 7. Assumptions

1. The demo laptop runs Windows 10/11 with Python 3.12. Internet only for setup, or never if the wheelhouse is carried on USB.
2. Git stays local (no remote). Commits use your existing global git identity ("Dzaldy") and end with the attribution line required by this environment.
3. The six large simulation CSVs are not needed for the demo. Retraining can restore them from `docs/before/` or the zip.
4. Lab conditions V1, V1b, V1c, V3, V4 and V6 are valid demo material. V5 and V1d are excluded by default, as the data README says.
5. "Realistic sample data" means replaying the **measured** lab curves (halogen lamp), not synthetic curves. Synthetic data appears only in clearly marked parser tests.
6. Timing in demo mode uses the estimates already in the code (0.6 s switch, 1.5 s sweep) and is labeled `emulated`. Real values appear only when hardware is connected.
