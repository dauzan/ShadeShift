# ShadeShift

ShadeShift measures the I-V curve of four small solar panels with an ESP32. When the panels are partly shaded, a tiny AI
model picks the best wiring (4S, 2S2P or TCT) and the relays switch to it. This repository is the system for the
Smart-X DeepTech Hackathon 2026 demo. It runs **100 % locally and free**, and it needs no internet once installed.

New here? Read **[START_HERE.md](START_HERE.md)** first.

## How it fits together

```
 ESP32 + firmware        edge gateway (laptop)            local server (laptop)          dashboard (browser)
 sweeps I-V, switches    owns the USB port, parses,       FastAPI + SQLite database,     Streamlit, 10 pages,
 relays safely, runs  →  runs the AI (ONNX Runtime) as  → ingestion API, WebSocket,   →  live view, replay,
 the AI on the board     a cross-check, measures timing   commands, uploads, audit       CSV upload, audit, status
 (firmware 3.2)          USB serial 115200                http://127.0.0.1:8000          http://127.0.0.1:8501
```

Without hardware, the gateway drives an **emulated ESP32** instead. It replays real lab curves and every value is labeled
**DEMO**. Interfaces, ports and data shapes are defined in [docs/CONTRACT.md](docs/CONTRACT.md).

## Quick start (Windows)

| Step | Command |
|---|---|
| One-time setup (internet needed once, ~4 min) | double-click **`setup.bat`** |
| Demo without hardware | double-click **`start_demo.bat`** (or `start_demo.bat --scenario` to play a shading scenario) |
| With the ESP32 on USB | double-click **`start_live.bat`** (or `start_live.bat --port COM5`) |
| Stop | **Ctrl+C** in that window (the relays are opened first) |

The browser opens http://127.0.0.1:8501. Only this laptop can reach the dashboard.

## Commands (`.venv\Scripts\python run.py <command>`)

| Command | What it does |
|---|---|
| `demo [--scenario [name]]` | Server + emulated ESP32 + dashboard; optionally plays `scenarios/<name>.json` |
| `live [--port COMx]` | Server + ESP32 gateway (port auto-detected) + standby demo device + dashboard |
| `server` | Only the API server (127.0.0.1:8000; endpoint list at `/docs`) |
| `gateway --source serial\|demo` | Only a gateway |
| `dashboard` | Only the dashboard |
| `import-lab` | Import the 120 lab curves into the database (`demo`/`live` do this once automatically) |
| `check` | Check this laptop: Python, packages, ports, lab data, model, digital twin |
| `ports` | List serial ports (to find the ESP32) |
| `test` | Run all automated tests (278) |

Tools: `tools/publish_sample.py` is a test publisher that posts lab curves to the API. `tools/ws_monitor.py` prints the live
stream. `tools/make_samples.py` regenerates `samples/`. `python -m shadeshift.edge.export_onnx` rebuilds
`models/pemilih.onnx` from the C weights header.

## Folders

| Folder | Contents |
|---|---|
| `shadeshift/` | The platform: `server/` (API + SQLite), `gateway/` (edge gateway, demo scenarios), `edge/` (AI selector, ONNX export), `protocol.py`, `commands.py`, `config.py` |
| `dasbor/` | Streamlit dashboard (`app.py`, `halaman/` pages, `umum.py`) |
| `firmware/` | ESP32 firmware v2 (original) and **v3** (AI on the board), logger, guides |
| `SHADESHIFT_ML/` | Research: simulation, models, lab data (`data/data_lab/`, never modified), reports |
| `models/` | `pemilih.onnx`, generated from `SHADESHIFT_ML/edge_ai/pemilih/pemilih_bobot.h` |
| `scenarios/` | Demo shading scenarios |
| `samples/` | Example CSV files for the upload page (good and bad) |
| `tests/` | Automated tests, including a host build of the firmware with simulated hardware |
| `docs/` | Reference documents ([index](docs/README.md)) |
| `data/` | Runtime database and gateway outbox (created on first run, not in git) |

## Documentation

| File | For |
|---|---|
| [START_HERE.md](START_HERE.md) | Setup, Demo Day runbook, what is finished, safe claims, what you must provide |
| [docs/PROMISES.md](docs/PROMISES.md) | **Each proposal promise, the technology that delivers it** |
| [CHANGELOG.md](CHANGELOG.md) | What changed, stage by stage |
| [docs/README.md](docs/README.md) | **Index of every other document** (firmware guide, interfaces, plan, analysis, team notes, research) |

## Configuration

Defaults work out of the box. To change ports, folders, the edge-AI runtime or an optional API token, copy
`.env.example` to `.env`. All variables are listed in [docs/CONTRACT.md §9](docs/CONTRACT.md).

## Everything is free and local

Python, Streamlit, FastAPI, SQLite, ONNX Runtime (CPU only, telemetry switched off), numpy/pandas/scipy, pvlib, pyserial
and the Arduino toolchain are all free and open source. Streamlit's usage statistics and its "Deploy" (cloud) button are
turned off, and the API docs page uses no CDN. No accounts, keys or paid services are involved.
