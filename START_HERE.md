# Start here

ShadeShift reads I-V curves from an ESP32, runs a small AI model that picks the panel wiring, stores everything in a
local database, and shows it on a dashboard. It all runs on one laptop, offline and free. This page covers:
1. Setting it up on a fresh laptop.
2. What is finished, what still needs the real board, and what was not built.
3. Running the Demo Day presentation.
4. What you need to provide.

For the presentation: [docs/PROMISES.md](docs/PROMISES.md) maps every proposal promise to the technology that delivers it
and to the evidence that exists today.

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

**Dashboard pages (consumer view, 22 Oct; CONTRACT section 19):**

| Page | What it shows |
|---|---|
| **Beranda** | The 3D model of the array with the condition of each panel (power, percent of the best panel, likely cause), problem cards with where to look and what to do, and the monitoring control (**Mulai pemantauan**) |
| **Kurva I-V** | Plain first: the AI box (what is new since your last visit, 24 hours, now), power now and against normal, power over 24 hours, each panel's power; the full I-V curve, the six signs and each panel's curve under **Lihat kurva lengkap**; **Ukur sekarang**, **Periksa setiap panel**, **Diagnosis dengan AI** |
| **Rekomendasi Rangkaian** | The panels and their wiring in 3D with the current flowing; the AI's recommendation with reason and measured gain; **Bandingkan semua rangkaian** (measures every wiring, about 20 s); **Terapkan saran** (asks for approval, then switches safely and shows before and after) |
| **Perangkat** | Status of every part: server, gateway, ESP32 (port, firmware, AI on board, Wi-Fi page), ADS1115 and MCP4725 on the I2C bus, voltage sensor, current path, light sensor, relays, panels A to D, monitoring; each Baik, Perlu dicek or Belum diperiksa, with when it was checked |
| **Riwayat** | Tab **Ringkasan**: the last 24 hours: each panel's condition over time, array power against the expectation, events and a summary in sentences; the latest values. Tab **Jejak audit**: who did what and when, for 24 hours up to everything, with a CSV download |

The earlier pages below are still in the code but no longer in the navigation (add them back in `dasbor/app.py`):

| Page | What it shows |
|---|---|
| **Langsung** | Live view and controls. Every AI decision says **who decided** (ESP32 or laptop) and **how long** it took |
| **Kembaran Digital** | The digital twin: a wireframe of the real array mirroring the live state (wiring, relays, per-panel problems, temperatures), and a What-if mode where you paint shade with the Shade brush and see every wiring's predicted power and the AI's pick; **Ukur sekarang** checks the prediction against a real measurement |
| **Model AI** | Train the diagnosis and the selector on measured data, tested fairly (another day, or another scan), keep every version, choose the active one, download the ESP32 header, import session zips from another laptop |
| **L3 dan stabilitas** | The semiconductor-switch design (calculation: relays 1.43–2.50 W vs 0.13–0.23 W, the only way to the ≤ 0.25 W target) and the stability-rule evidence |
| **Target vs Bukti** | The four proposal targets next to their evidence (measured / lab / simulation / calculation): power recovery vs ideal MLPE, diagnosis, control power (multimeter entry), decision time; CSV for the technical report |
| **Ambil data** | Measurement sessions: label the condition, run a full scan (4 topologies + 4 single panels), check quality, enter panel temperatures, export the session as training files |
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
| Dashboard (10 pages) and one-command start/stop | **Complete**, tested; screenshots checked for the first 5 and the Kembaran Digital page (Ambil data, Target vs Bukti, Model AI and L3 are tested by the page tests only) |
| Demo mode: emulated ESP32 + 3 shading scenarios, everything labeled DEMO | **Complete**, tested (the AI picks TCT → 4S → TCT, matching the lab data) |
| **One firmware, 3.2** (`firmware/shadeshift_firmware/`): the original v2 measuring code plus single-panel sweeps A–D, LDR light sensor, `INFO`, the AI choosing the wiring on the ESP32 (TinyML, `PILIH`), diagnosis on the ESP32 (`DIAG`), the ESP32 web page, safety fixes | **Written and tested on the laptop with simulated hardware**; for the shared commands its measurements equal the original v2's. **Not yet flashed.** Guide and first check: [firmware/CARA_PAKAI.md](firmware/CARA_PAKAI.md) |
| Data collection: sessions, labeled full scans, quality checks (complete, light steady, repeat spread, 4P vs panel sum, A1 drift), temperatures, ZIP export with `labels.csv` | **Complete**, tested end to end with the emulator and a simulated board with single panels. **Not yet used with the real board** |
| Technical-report page (latency tables, manual power entry, targets vs evidence) | **Not built.** The timings are already recorded: `GET http://127.0.0.1:8000/api/v1/metrics/summary` |
| Decision audit (sweep all 3 topologies to measure the AI's real loss), stability rule (lock TCT when power fluctuates) | **Not built.** The stability rule is unvalidated and switched off |
| Proving the targets: ideal-MLPE reference from the single panels, recovery points vs the best fixed topology, live **Audit keputusan AI**, Target vs Bukti page with multimeter entry and CSV | **Complete**, tested with the emulator and a simulated v2.1 board (synthetic panel curves). Real numbers appear after the first session with firmware v2.1 |
| Training on measured data: dataset from sessions + lab + simulation (kept separate), logistic regression and decision tree, fair test by day or scan, model registry, activation, ESP32 headers, session import | **Complete**, tested. It reproduces the published lab numbers (0.82 % vs 2.71 %). **No model trained on real data yet**: that needs your sessions |
| Live diagnosis: cause and pattern from the active models (with their validation status), measured 2×2 module map from the single panels, agreement between the two; on Langsung and Ambil data | **Complete**, tested with synthetic panel curves. Meaningful once models are trained on your sessions |
| L3 page (semiconductor-switch design: holding power per wiring vs relays, net gain, live wiring, multimeter entries) and the stability rule (built, off by default, evaluated in simulation and on F1 scans) | **Complete**, tested. Simulation result: the rule does not help (stays off); auto mode must monitor rarely (default now every 5 min) |
| MQTT bridge | **Not built** (not needed: HTTP ingestion) |
| Offline installer folder (wheels on USB) | **Not built** (not needed: you present from an installed laptop) |

**Known issues:**
- The model-claim texts on the Status page are in English inside the Indonesian UI.
- One full test run once ended with a crash dump after all tests had finished; three reruns were clean; the cause is unknown.
- Fixed 20 Oct: on a busy laptop, Ctrl+C sometimes had to force-stop the server (it waited for a gateway long-poll). The server now stops within 5 s; relays were always opened first.
- `TAHAN` (hold at maximum power) is not in the firmware on purpose: heat risk until a heat check on the board.

## 4. Demo Day runbook

**Data sessions (from 20 Oct), firmware 3.2:**
1. Once, before the first session: change the WiFi password, flash firmware 3.2, wire the LDR and run the ~30-minute first check ([firmware/CARA_PAKAI.md](firmware/CARA_PAKAI.md) sections 1, 2, 5). Bring the IR thermometer. If WiFi changes the readings, type `WEB 0` while measuring.
2. `start_live.bat`, page **Ambil data**, device `esp32-01`. The page must not say "Firmware alat tidak melaporkan sapuan per panel".
3. **Mulai sesi** (place, sky, location, operator). First scan: **A1** (no shade).
4. For each condition: set up the shade or fault (faults today: **E2 and E5 only**; press **STOP** first), choose the code, check the modules and class, **Mulai scan penuh**. During each pause, measure the panel temperatures and type them in the scan's box.
5. Read the quality line of each scan. ⚠️ light changed → repeat the scan. ⚠️ 4P above the panel sum → check the relays.
6. Shade **different modules and pairs** (the old lab data always shaded module A). Last scan: **A1** again (drift check).
7. **Akhiri sesi**, then **Siapkan zip** → **Unduh zip**. Keep the zip; the raw files inside are exactly what the board sent.
8. On the laptop that trains (if it is another one): page **Model AI** → **Impor zip sesi**. Then **Latih dan uji** for the diagnosis. A selector is activated only if it beat the current one on the test rounds; afterwards restart and reflash the firmware.

**Before leaving (19–20 Oct):**
1. On the board: the first check of [firmware/CARA_PAKAI.md](firmware/CARA_PAKAI.md) (incl. `uji_pemilih` → `LULUS 12/12`) if not done yet, and **write down** `t_us` and the ESP32 + relay power from the
   multimeter (for the technical report).
2. On the demo laptop: `start_live.bat`. The Status page should show `v3.2 (3.2.0)` and "ya, bobot sama". Run
   **Pilih susunan otomatis** once: it should say **"Diputuskan oleh: ESP32 (di papan)"**.
3. Also run `start_demo.bat --scenario kilat` once, to rehearse the backup.
4. Pack: halogen lamp, shade cloth, the ESP32 USB cable, the 12 V adaptor, spare relay module and wires, the charged laptop.

**Optional: simpler sentences by Gemini (needs internet).** Get a free API key yourself at Google AI Studio, then add
one line to `.env` in the project folder: `SHADESHIFT_GEMINI_API_KEY=<your key>` (never share or commit it), and restart
`start_live.bat`. When it works, the note under the AI box on Kurva I-V and Riwayat says the sentences were reworded by
Gemini. Without internet the
page simply uses the laptop's own sentences, so nothing changes for an offline demo.

**At the venue, consumer view (22 Oct):**
1. Lamp on, 12 V adaptor in, ESP32 on USB, `start_live.bat`. **Kurva I-V**: no shade, **Ukur sekarang**, then **Jadikan pengukuran ini acuan harapan** (the twin's expectation now matches this lamp).
2. **Beranda**: under the 3D model, the **Perawatan** card predicts cleaning and checks once there are 3 days of data (until then it says how much more it needs); after cleaning the panels press **Saya sudah membersihkan panel**. The row **AI di ESP32 (TinyML)** shows the recommendation computed on the board itself and how long it took (if it says "di laptop", the firmware on the board has no AI weights: reflash firmware 3.2). Monitoring is already on (it starts by itself with `start_live.bat`); the first panel check runs within seconds and all four panels should read Normal. After **Hentikan semua**, press **Mulai pemantauan** to restart it. Choose the roof type under the model (**Jenis atap**). The row **Diagnosis AI di ESP32** says 'Belum dipasang' until a diagnosis model trained on real data is flashed with the firmware; with one, **Diagnosis dengan AI** measures all four wirings and shows the cause.
3. Put cardboard or a leaf on panel A. On **Kurva I-V** press **Periksa setiap panel** (about 20 s). **Beranda** now says "Kemungkinan ada benda atau kotoran menutupi panel A", panel A glows red, and the card says where to look and what to do. Click panel A to zoom in.
4. **Kurva I-V**: the analyser box explains what changed; move the pointer along the curve: each part says what it is, and the red band says "Anak tangga pada kurva" with its meaning. Panel A's own curve is low. **Riwayat**: the 24-hour analysis, the event and the timeline; tab **Jejak audit** shows your button presses (Pengguna), the monitoring and the AI's recommendations line by line, and **Unduh jejak audit (CSV)** saves them.
5. **If the hardware fails:** pick `demo-01` and press **Mulai pemantauan** on Beranda (the standby demo device does not start it by itself). In the row **Rekaman lab yang diputar (mode demo)** choose a lab condition (for example `V3_paranet65`, shade cloth on panel A) and press **Terapkan**: the panels are checked again. Every page says **Mode demo**; say clearly that the array curves are lab recordings and the panel curves come from the twin.
6. Press **Hentikan semua** before anyone touches the wiring: 4S can reach about 88 V DC. That stop also completes a trial run: the team's Bukti page (out of the navigation; `http://127.0.0.1:8000/api/v1/bukti`) counts a full trial when the board's AI was active, the array and all four panels were measured, and the stop was confirmed. Three are promised before Demo Day. Before the demo, open **Perangkat**: every part should say Baik (ADS1115 and MCP4725 found, sensors and relays measured); anything that says Perlu dicek says what to check.

**At the venue, earlier flow (pages now out of the navigation):**
1. Power: lamp on, 12 V adaptor in, ESP32 on USB. Run `start_live.bat`.
2. **Langsung** page, device `esp32-01`: **STATUS**, then **4S** and **SWEEP** with no shade. Then press
   **Kalibrasi skala dari sapuan terakhir** in the sidebar, so the digital twin's "expected power" matches this lamp.
   - If switching fails with "Voc di luar …", the lamp is dimmer than in the lab. Type `VPANEL 17` in the command box and retry.
   - If a sweep fails with "arus tidak terdeteksi", there is not enough light: move the lamp closer.
3. Show: **Pilih susunan otomatis** with no shade, then cover module A (or A+B) with the shade cloth and run it again.
   The topology changes, the decision says "ESP32 (di papan)", and the time per decision is shown.
4. Press **Audit keputusan AI** once: the AI decides, then every topology is measured, so the judges see the real loss of the decision. Then show **Target vs Bukti**: each proposal target with its evidence and where it comes from.
5. **Kembaran Digital**: show the live mirror (wiring, markers), then switch to **What-if**, paint a shadow on panel A with the Shade brush and read the predicted power per wiring and the AI's pick. Put real cardboard on panel A the same way and press **Ukur sekarang**: prediction vs measurement.
6. Optional: let a judge open **http://192.168.4.1** on a phone (WiFi "SHADESHIFT") and type `DIAG` in the **Perintah firmware** box on the Langsung page: the diagnosis runs on the ESP32 itself (about 20 s; the phone shows the result).
7. Show the **Peristiwa** page (audit trail) and the **Putar ulang** lab summary (0.82 % vs 2.71 %, lab).
8. **If the hardware fails:** pick `demo-01` in the device list and press **Mulai skenario** (`default`). Say clearly that
   it replays real lab measurements; the dashboard labels it DEMO.
9. Press **STOP** before anyone touches the wiring: 4S can reach about 88 V DC. The STOP that needs no software is
   unplugging the 12 V adaptor.

## 5. Claims: use these, avoid those

Say where every number comes from: lab (halogen lamp), simulation, or measured today.

| Use | Avoid |
|---|---|
| "On lab data the AI loses 0.82 % of power vs 2.71 % for the best fixed wiring (2S2P), among 4S/2S2P/TCT (30 sets, 6 shading patterns)." | "High accuracy" (accuracy is 68.9 % in simulation, balanced 47.5 %) |
| "The model is 73 numbers (292 bytes) and runs on the ESP32 in `t_us` µs" (only after measuring on the board) | "Quantized" (it is float32), "CNN" (explored, not used) |
| "Diagnosis of the cause: 78–82 % in **simulation** only; it fails on lab data" | 83–89 % (old, from before a bug fix), any diagnosis accuracy on real data |
| "Under moving shade, sweeping to check the power costs energy: checking every 10 s loses to fixed TCT; every 5 min it roughly ties (simulation). The gain is on steady shade (lab: 0.82 % vs 2.71 %)" | "Auto mode always beats fixed wiring", "the stability rule helps" |
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
7. Data files are named `<LR|DR><MMDD>_<code>[-<modules>]_<topology>_u<n>.csv`: `LR` outdoors (protocol), `DR` indoors (my choice), `TIRUAN` for the emulator. Modules are added only when they differ from the protocol's default (e.g. `B2-C`).
8. Faults in the data sessions: E2 (open bypass diode) and E5 (shorted bypass) only, team decision of 20 Oct. E1 stays in the list, marked as a control, but is not measured.
9. Quality limits: light change 5 % (protocol; measured in LDR volts, so approximate), repeat spread 1.8 % (proposal), A1 drift 5 % (my assumption; the protocol gives none). Panel temperatures are entered per round (repeat).
10. "Decision within milliseconds" is counted as met when the ESP32's decision time (p95) is below 1 s; the proposal gives no exact number.
11. The best fixed topology for the recovery metric is chosen after seeing all rounds (the strongest fixed competitor), and 4P is not a candidate, as in the lab and simulation claims.
12. Module-map rules (power below 90 % of the best panel = affected; Isc / Voc drops decide the hint) are my first guesses, shown as "not validated" until your data checks them.

## 7. What you need to provide or do

1. **Flash and test the board** with the first check in [firmware/CARA_PAKAI.md](firmware/CARA_PAKAI.md) (change the WiFi password `WEB_SANDI` first). One firmware for data days and Demo Day; the original v2 in `docs/before/firmware/` is only the emergency fallback. Tell me what you see; anything odd can be fixed before Demo Day.
2. **Wire the LDR** (LDR from 3.3 V to A2, 10 kΩ from A2 to GND) and bring the IR thermometer to every session.
3. **Measure power** of the ESP32 and the relays with the multimeter you have (no purchases), and `t_us` from the board.
4. **The real COM port** if auto-detection does not find the ESP32 (`.venv\Scripts\python run.py ports`).
5. **Send me the first session zip** after 20 Oct, so the next stages (MLPE reference, training on real data) use it.
6. **Calibration constants** in the firmware (`R_ATAS`, `R_BAWAH`, offsets) if you have measured values. Until then,
   absolute watts may be slightly off, but the AI uses curve shape and is not affected.
