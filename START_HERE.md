# Start here

ShadeShift reads I-V curves from an ESP32, runs a small AI model that picks the panel wiring, stores everything in a
local database, and shows it on a dashboard. It all runs on one laptop, offline and free. This page covers:
1. Setting it up on a fresh laptop.
2. What is finished, what still needs the real board, and what was not built.
3. Running the Demo Day presentation.
4. What you need to provide.

## 1. Set up a fresh Windows laptop (once, with internet)

1. Install **Python 3.12** from https://www.python.org/downloads/. Tick "Add python.exe to PATH". Team rule: install
   to drive D (Customize installation → install location).
2. Copy this project folder to the laptop, e.g. `D:\ShadeShift`.
3. Double-click **`setup.bat`**. It creates `.venv`, installs the pinned packages (about 600 MB, about 4 minutes) and runs
   a check. Every line of the check must say `OK`.
   - A `WARN` on `onnxruntime` means the Microsoft Visual C++ runtime is missing. The AI still works through its numpy
     fallback (same results, labeled `gateway_numpy`). To get ONNX Runtime back, install the free "Microsoft Visual C++
     Redistributable" (a system install on C:, so ask the laptop owner first).
4. Done. From now on no internet is needed.

For the ESP32 the laptop also needs **Arduino IDE** with "esp32 by Espressif" and the Adafruit ADS1X15 and MCP4725
libraries (only to flash firmware). It may also need the board's USB driver (CP210x or CH340) if Windows does not
recognize it.

## 2. Run it

| You want | Do this | You will see |
|---|---|---|
| Demo without hardware | `start_demo.bat` | Dashboard with device `demo-01` (labeled **DEMO**) |
| Demo with a scripted shading show | `start_demo.bat --scenario` | The same, and the default scenario starts by itself |
| The real device | Plug in the ESP32 and the 12 V adaptor, then `start_live.bat` | Device `esp32-01`, plus `demo-01` waiting as a backup |
| Stop | **Ctrl+C** in the black window | "Stopped." The gateway opens all relays first |

Closing the window is handled like Ctrl+C, but Ctrl+C is the safe habit. Refreshing the browser or opening a second tab
is harmless. The dashboard is at http://127.0.0.1:8501 and works only on this laptop.

**Dashboard pages:**

| Page | What it shows |
|---|---|
| **Langsung** | Live view and controls. Every AI decision says **who decided** (ESP32 or laptop) and **how long** it took |
| **Putar ulang** | Saved lab data, uploads and sessions |
| **Unggah CSV** | Upload curves. Each file is accepted or rejected with the reason |
| **Peristiwa** | Audit trail of every command, switch, decision, alert and error, with CSV download |
| **Status** | Health of the server, gateway, model and firmware |

## 3. What is complete, what still needs the board, what was not built

| Part | Status |
|---|---|
| Local server: SQLite database, HTTP ingestion API, WebSocket live stream, command queue, CSV upload, lab import, audit trail | **Complete**, tested |
| Edge gateway: owns the USB port, runs the AI (ONNX Runtime), measures switch/sweep/decision time, keeps data if the server is down | **Complete**, tested against the emulated ESP32 and real lab curves. **Not yet run with the real ESP32** |
| Safe Stop: no command after OFF; "done" only after the device confirms all relays open; blocked bench commands | **Complete**, tested |
| Dashboard (5 pages) and one-command start/stop | **Complete**, tested; screenshots checked |
| Demo mode: emulated ESP32 + 3 shading scenarios, everything labeled DEMO | **Complete**, tested (the AI picks TCT → 4S → TCT, matching the lab data) |
| Firmware v3: AI on the ESP32 (TinyML), `PILIH`, `INFO` weights fingerprint, safety fixes | **Written and tested on the laptop with simulated hardware. Not yet flashed or run on the board.** Checklist: [firmware/CARA_PAKAI_v3.md](firmware/CARA_PAKAI_v3.md) |
| Technical-report page (latency tables, manual power entry, targets vs evidence) | **Not built.** The timings are already recorded: `GET http://127.0.0.1:8000/api/v1/metrics/summary` |
| Decision audit (sweep all 3 topologies to measure the AI's real loss), stability rule (lock TCT when power fluctuates) | **Not built.** The stability rule is unvalidated and switched off |
| Fault localization (which module is shaded, for PLN), L3 semiconductor page, session ZIP export, MQTT bridge | **Not built** (PLAN Stage 7) |
| Offline installer folder (wheels on USB) | **Not built** (not needed: you present from an installed laptop) |

**Known issues:**
- The model-claim texts on the Status page are in English inside the Indonesian UI.
- One full test run once ended with a crash dump after all tests had finished; three reruns were clean; the cause is unknown.
- `TAHAN` (hold at maximum power) is not in firmware v3 on purpose: heat risk until a heat check on the board.

## 4. Demo Day runbook

**Before leaving (19–20 Oct):**
1. On the board: flash `uji_pemilih` (`LULUS 12/12`), then firmware v3. Follow the checklist in
   [firmware/CARA_PAKAI_v3.md](firmware/CARA_PAKAI_v3.md) and **write down** `t_us` and the ESP32 + relay power from the
   multimeter (for the technical report).
2. On the demo laptop: `start_live.bat`. The Status page should show `v3 (3.0.0)` and "ya, bobot sama". Run
   **Pilih susunan otomatis** once: it should say **"Diputuskan oleh: ESP32 (di papan)"**.
3. Also run `start_demo.bat --scenario kilat` once, to rehearse the backup.
4. Pack: halogen lamp, shade cloth, the ESP32 USB cable, the 12 V adaptor, spare relay module and wires, the charged laptop.

**At the venue (indoors, halogen lamp):**
1. Power: lamp on, 12 V adaptor in, ESP32 on USB. Run `start_live.bat`.
2. **Langsung** page, device `esp32-01`: **STATUS**, then **4S** and **SWEEP** with no shade. Then press
   **Kalibrasi skala dari sapuan terakhir** in the sidebar, so the digital twin's "expected power" matches this lamp.
   - If switching fails with "Voc di luar …", the lamp is dimmer than in the lab. Type `VPANEL 17` in the command box and retry.
   - If a sweep fails with "arus tidak terdeteksi", there is not enough light: move the lamp closer.
3. Show: **Pilih susunan otomatis** with no shade, then cover module A (or A+B) with the shade cloth and run it again.
   The topology changes, the decision says "ESP32 (di papan)", and the time per decision is shown.
4. Show the **Peristiwa** page (audit trail) and the **Putar ulang** lab summary (0.82 % vs 2.71 %, lab).
5. **If the hardware fails:** pick `demo-01` in the device list and press **Mulai skenario** (`default`). Say clearly that
   it replays real lab measurements; the dashboard labels it DEMO.
6. Press **STOP** before anyone touches the wiring: 4S can reach about 88 V DC. The STOP that needs no software is
   unplugging the 12 V adaptor.

## 5. Claims: use these, avoid those

Say where every number comes from: lab (halogen lamp), simulation, or measured today.

| Use | Avoid |
|---|---|
| "On lab data the AI loses 0.82 % of power vs 2.71 % for the best fixed wiring (2S2P), among 4S/2S2P/TCT (30 sets, 6 shading patterns)." | "High accuracy" (accuracy is 68.9 % in simulation, balanced 47.5 %) |
| "The model is 73 numbers (292 bytes) and runs on the ESP32 in `t_us` µs" (only after measuring on the board) | "Quantized" (it is float32), "CNN" (explored, not used) |
| "Diagnosis of the cause: 78–82 % in **simulation** only; it fails on lab data" | 83–89 % (old, from before a bug fix), any diagnosis accuracy on real data |
| "The 20 % trigger rule beats fixed TCT on average in simulation, but is worse in 10 of 12 leaf-shade scenarios" | "Never worse than the best fixed wiring" |
| "Expected power comes from a digital twin fitted to the lab lamp (~8 % error on 7 lab conditions)" | Calling a large difference a "diagnosis": it is an indication |
| "In the lab, 4P measured highest in all 30 sets but is outside the 24 V controller window" | Hiding the 4P convention if asked |
| TRL 4 now | TRL 5 before a sun session; TRL 6 |

## 6. Assumptions

1. The demo laptop runs Windows 10/11 with Python 3.12 and has this project already installed (no offline installer).
2. The ESP32 stays on USB serial; there is no WiFi in this version.
3. Without hardware, "realistic data" means replaying the **measured** lab curves, not invented curves.
4. Emulated switch and sweep times (~0.65 s, ~3 s) are estimates from the firmware delays, labeled "emulated". Real
   values appear when the board is connected.
5. Lab conditions V5 and V1d are excluded (as `data_lab/README.md` says). Raw lab files are never modified (checked by a test).
6. Documents are in English and the dashboard is in Indonesian, as before.

## 7. What you need to provide or do

1. **Flash and test the board** with the checklist (19–20 Oct). Tell me what you see; anything odd can be fixed before Demo Day.
2. **Measure power** of the ESP32 and the relays with the multimeter you have (no purchases), and `t_us` from the board.
3. **The real COM port** if auto-detection does not find the ESP32 (`.venv\Scripts\python run.py ports`).
4. **Decide** whether to build any of the "not built" items above. The technical-report page is the most useful for judging.
5. **Calibration constants** in the firmware (`R_ATAS`, `R_BAWAH`, offsets) if you have measured values. Until then,
   absolute watts may be slightly off, but the AI uses curve shape and is not affected.
