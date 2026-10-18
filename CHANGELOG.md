# Changelog

All dates 2026. Each stage is one git commit; details in [PLAN.md](PLAN.md) and [CONTRACT.md](CONTRACT.md).

## Stage 8: setup, start scripts, documentation (18 Oct)
- `setup.bat`: creates `.venv`, installs pinned packages, runs `run.py check`. Tested on a brand-new environment: all checks OK and the full test suite passes there.
- `start_demo.bat`, `start_live.bat`: double-click starters.
- `README.md`, `START_HERE.md` (setup, status, Demo Day runbook, claims, assumptions, what to provide), this changelog.

## Stage 6: firmware v3, the AI on the ESP32 (18 Oct)
- `firmware/shadeshift_firmware_v3/`:
  - the selector (`pemilih.h`) runs on the board after every 4S sweep and prints its decision and time (`t_us`);
  - `PILIH` performs the whole auto-select on the board;
  - `INFO` reports the weights fingerprint (`w=cbe60e1a8194`).
- Safety fixes in v3:
  - OFF works inside SIKLUS and PILIH;
  - a failed sweep stops SIKLUS;
  - RELAI, UJIRELAI and DAC work only in `BENCH 1` mode.
- Unchanged in v3: the safe switching sequence and the sweep format.
- Gateway: applies the ESP32's decision (`decided_by=esp32`), keeps its own as a cross-check, and warns about stale weights on the board.
- Tested on the laptop: the unchanged sketch is compiled against simulated hardware that replays lab curves, and the C model equals ONNX on 38/38 lab curves. **Not yet run on the board.**

## Stage 4: demo mode (18 Oct)
- Scenario player on the emulated ESP32, with three scenarios: `default`, `kilat` (3x speed) and `v6_kelemahan` (the known weak case).
- Auto mode reacts to the shading changes as it would on hardware.
- Everything is labeled DEMO, and STOP ends a scenario.
- `start_demo.bat --scenario` starts the default show directly.

## Stage 3: dashboard on the server, CSV upload, one-command start (18 Oct)
- Dashboard rebuilt as an API client with five pages: Langsung, Putar ulang, Unggah CSV, Peristiwa, Status.
- Every decision shows who made it. The dashboard no longer opens the COM port, so a refresh or a second tab cannot lock it.
- `run.py demo` / `live` start everything and stop in a safe order (relays open first). The dashboard listens on 127.0.0.1 only.

## Stage 2: edge gateway and edge AI (18 Oct)
- The gateway owns the serial port (ESP32 auto-detected by USB id) or the emulated device.
- It runs the selector with ONNX Runtime (`models/pemilih.onnx`, generated from the C weights header), with a numpy fallback.
- It measures timings and sends everything to the server through an outbox that survives server downtime.
- Safe Stop:
  - a latch means no task can write after OFF;
  - a stop is handed out first, and relay commands queued with it are cancelled;
  - Stop reports done only when the device confirms all relays are open.
- The stability rule is off by default because it is unvalidated. All packages are pinned.

## Stage 1: local server (18 Oct)
- FastAPI + SQLite: ingestion (sweeps, decisions, events, metrics, evaluations, serial log), runs, command queue with gateway long-poll.
- Raw-command allowlist: RELAI, UJIRELAI, DAC, CEKVOC 0, SIKLUS and TAHAN 1 are blocked from the API.
- Reads, snapshot, audit trail CSV, CSV uploads with validation, read-only lab import, digital-twin expectation and alerts, WebSocket stream, optional write token, offline `/docs`.
- Test publisher `tools/publish_sample.py` and `tools/ws_monitor.py`; example files in `samples/`.
- The lab numbers (0.82 / 2.71 / 4.30 / 12.0 %, lab) are reproduced from database rows.

## Stage 0: runnable baseline (18 Oct)
- The original zip is extracted to `docs/before/`, byte-identical to the zip.
- The working tree is restored from it, which makes the existing dashboard run again.
- Dependencies are pinned. Streamlit runs without telemetry or the "Deploy" (cloud) button.
- The `uji_pemilih` sketch now has the current weights; it previously held a stale copy.

## Phases 1–2: analysis and plan (17–18 Oct)
- `ANALYSIS.md`: before/after comparison, missing and simulated parts, cloud dependencies, bugs, firmware safety findings, claims to qualify.
- `CONTRACT.md`: interfaces. `PLAN.md`: stages and decisions.

## Before (up to 17 Oct): `SHADESHIFT_untuk_Dauzan.zip`
- Firmware v2, simulation and model research, lab data.
- A Streamlit dashboard (`dasbor/`) that talked to the ESP32 directly over serial and needed the full project tree next to it.
