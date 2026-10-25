# Changelog

All dates 2026. Each stage is one git commit; details in [PLAN.md](docs/PLAN.md) and [CONTRACT.md](docs/CONTRACT.md).

## Rekomendasi Rangkaian (22 Oct)
- A fifth page, **Rekomendasi Rangkaian**: the four panels and their wiring in 3D (only the main parts) with the current flowing along the real path of each wiring; the AI's recommendation with its reason, the measured gain and the measured power of every wiring (**Bandingkan semua rangkaian** measures them all and returns); **Terapkan saran** asks for approval with what can go wrong, then the relays change the wiring in the firmware's safe order and the view splits into before and after with the measured result. Monitoring stays on the new wiring; 15 minutes between changes, going back always allowed; 4P shown but never applied (below the 24 V window); every step in Jejak audit (CONTRACT section 29).

## Blocked light shown as darkness (22 Oct)
- On the 3D model a blocked panel now darkens (the more light it lost, the darker) under its red radial glow; with less light everywhere all four panels darken evenly. The leaf and cloud illustrations are gone. The whole panel darkens because where on its surface the blockage is cannot be measured (36 cells in series, one bypass diode); a small blockage gives a light shade.

## Predictive maintenance on Beranda (22 Oct)
- A "Perawatan" card under the 3D model predicts what will need attention and roughly when, from the last 14 days: panels getting dirty (power per light reading dropping slowly), one panel falling behind the others, a connection getting worse, shade that comes back at the same hour. The owner logs cleaning or a repair with a button; a fresh baseline starts and the effect is measured. Needs at least 3 days of data and says so until then (CONTRACT section 28).
- Beranda has one scrollbar, the main page's: the 3D frame has no scrollbar of its own and takes the full height of its content.

## Optional Gemini rewording (22 Oct)
- With a Gemini API key (free tier, set in `.env`), the sentences of the analyser box are reworded in simpler words by Gemini Flash. The light model on the laptop still produces every number and verdict; a guard throws away any answer with a number not in the facts, markdown or symbols. Runs in the background and is cached, so the page never waits; without a key, offline or on any error the local sentences stay. The Perangkat page shows its state (CONTRACT section 27).

## Light AI model, what is new, plain words (22 Oct)
- A light AI model on the laptop learns what is normal for this array from its own last 14 days, judges every new measurement (normal, lower, much lower, higher than usual), uses the light sensor to tell a cloud from something covering a panel, and spots a trend over days. Nothing to install, offline (CONTRACT section 26).
- The analyser box on Kurva I-V and Riwayat has a **Yang baru** box: what arrived since you last looked (how many measurements and when, the power change, the model's verdict, panel changes, new or gone signs).
- Plain words for customers on Kurva I-V, Riwayat and Beranda: no Voc, Isc, MPP or "susunan 4S"; signs with everyday names; "perkiraan normal" instead of the twin's expectation. Kurva I-V opens simple (cards, power over time, each panel) with the full curve under **Lihat kurva lengkap**.

## Perangkat page replaces Bukti in the navigation (22 Oct)
- The fourth page is now **Perangkat**, a status centre for every part of the system: the server, the gateway, the ESP32 (port, firmware, AI on board, Wi-Fi page), ADS1115 and MCP4725 (found on the I2C bus), the voltage sensor, the current path, the light sensor, the relays, panels A to D and monitoring, each Baik, Perlu dicek, Belum diperiksa and so on, with when it was checked. A part is Baik only when a report or a measurement shows it working. The gateway asks the board for SCAN when it connects; **Periksa ulang perangkat** asks again (CONTRACT section 25).
- The Bukti page (promises and targets) is out of the navigation: the consumer view is for customers. Its code and `GET /api/v1/bukti` stay for the team.

## Prettier house, eight roof types (22 Oct)
- The house in the 3D view has roof tiles with staggered joints, a ridge cap, white fascia, a gutter and downpipe, framed windows with mullions and sills, a wooden door with a step, a plinth and a soft shadow under the eave. Decoration only: no chimney or plants, so nothing looks like an object shading a panel.
- Three more roof types: Perisai berpelana (Dutch gable), Gambrel (a steep band below the panel slope), Kampung dengan emper (a porch roof on posts over the door). Eight in total; every face checked flat in the tests, the porch kept clear of the control box.

## Close 3D framing (22 Oct)
- Beranda's 3D view now frames the house close, as in the user's sketch: the orange roof with the panels fills the upper left, the young grey front wall with the dark grey control box the lower right, and the house's right corner shows against the background. Camera from the front left (yaw -48, pitch 33), the roof extends further above the panels, value labels on white, the 3D area 640 px high. Every roof type keeps working.

## Bukti page (22 Oct)
- New fourth page **Bukti**: the proposal's promises and four targets next to their evidence, in Indonesian words, from real ESP32 data only (demo data never counts; lab, simulation and calculation numbers are labelled comparisons). Full trial runs on the board are counted automatically from five checks (on-board AI active, array sweep, ESP32 recommendation, four panels checked, confirmed stop). Control power: the relay and semiconductor calculation per wiring and a form for multimeter readings. The automatic reconfiguration is left out (CONTRACT section 24).

## Diagnosis AI on the ESP32 on the web page (22 Oct)
- New gateway action `diagnose` sends `DIAG` to the board; the cause it computes on the ESP32 shows on Beranda (row **Diagnosis AI di ESP32**, with a **Diagnosis dengan AI** button), in the analyser box and in Jejak audit (important when the cause changes), in Indonesian words with the confidence and the time on the board. Without a model on the board, or in demo mode, every place says why instead of showing a cause (CONTRACT section 23). Works once a board runs firmware 3.2 with `diagnosis_model.h`.

## Jejak audit in Riwayat (22 Oct)
- Riwayat has a second tab, **Jejak audit**: who did what and when (Pengguna, AI di ESP32, AI di laptop, Sistem, Perangkat), in Indonesian sentences, for 24 hours, 7 days, 30 days, everything or a date range. By default the important lines (commands, relay switches, warnings and errors, monitoring, connection changes, AI recommendation changes) and one summary line per day; **Tampilkan semua** lists every measurement and AI result, 100 lines per page. **Unduh jejak audit (CSV)** saves the whole period with the original system messages. Demo data says Mode demo on every line (CONTRACT section 22).

## Edge AI output on the web page (22 Oct)
- The AI that runs on the ESP32 (firmware 3.x selector) now reaches the web page while monitoring runs: the gateway forwards the on-board result during monitoring, measurements on request and panel checks, stored as decided by the ESP32 (observation, never applied). Beranda shows "AI di ESP32 (TinyML)" with its recommendation, the time it took on the board and that the wiring is not switched automatically; the analyser box says where the recommendation was computed. Demo mode says it was computed on the laptop (CONTRACT section 21).

## Roof types, flashes of light, monitoring always on (22 Oct)
- Monitoring starts by itself when the system starts (`SHADESHIFT_MONITOR_AUTO`, default on); after Hentikan semua it stays off until restarted. Ukur sekarang (`measure_now`) and Periksa setiap panel work while monitoring runs.
- The 3D view: five roof types to choose from (pelana, perisai, saltbox, sandar, datar with a panel rack), roof colour rgb(244 163 100), white walls with grey shaded sides. The power path is a cable drawn on the model (up the wall, over the eave, through the Wago strip, around the array, a lead to each panel) and flashes of light run inside it from the control box and back; a new flash starts when the previous one is half way.

## Curve analyser, hover explanations, house in the 3D view (22 Oct)
- The I-V curve explains itself: every point says which part of the curve it is and, where the shape deviates, which of the six classic deviations it is (steps, low current, low voltage, rounder knee, series resistance, shunt or uneven light), what it means and the likely causes (CONTRACT section 20). Deviations are drawn as red bands with their names; a list shows which of the six are visible.
- An analyser box with an AI badge on Kurva I-V and Riwayat: the last 24 hours (wide) and the current data (narrow), with a short thinking animation when the page opens. Rule-based and local; it says so.
- The 3D view: a brown roof tilted towards the sun over half of a house with white walls, the control box on the front wall, and a moving yellow power path from the panels to the control box while monitoring is on.
- Fixed: the expected curve used an old "assumed shading" setting from the removed sidebar; the consumer view now always compares with the unshaded twin. The chart toolbar icons are hidden.

## Consumer view focused on the digital twin (22 Oct)
- The dashboard now has three pages in a top navigation bar, white theme, words only: **Beranda** (solid 3D model of the array with the condition of each panel, problem cards with advice, monitoring control), **Kurva I-V** (latest curve with key points, the twin's expectation, a reading in words, each panel's curve, measure now, check each panel, set the expectation reference) and **Riwayat** (24-hour panel timeline, array power against expectation, events and summary in sentences, latest values). The other pages stay in the code, out of the navigation. Automatic switching is not shown.
- Monitoring mode (`monitor_start` / `monitor_stop`) measures without deciding: an array sweep every 5 min, a panel check every 30 min. One-off `panel_check`.
- Condition rules in `shadeshift/kondisi.py`, in `/twin/state` (`kondisi`) and the new `/riwayat` (CONTRACT section 19). The 3D model shows only what was measured: a glow over the whole panel and a leaf illustration for light lost on one panel, see-through panels with a glow at the diode or along the cable for electrical problems, a cloud when all panels and the light sensor drop together.
- The demo device answers single-panel sweeps from the lab twin, marked `# tiruan model=kembaran`; every page says **Mode demo**.

## Dashboard shows only SHADESHIFT (22 Oct)
- The dashboard pages carry no framework branding: no toolbar menu, About dialog, Deploy button, run-status indicator or coloured top line (`client.toolbarMode = "minimal"` plus page CSS in `dasbor/app.py`). Uncaught errors show only their type and message (`client.showErrorDetails = "type"`). Same flags in `run.py` and `.streamlit/config.toml`.
- A native React web front end was tried and dropped: the Streamlit dashboard stays the data-visualization layer.

## Digital Twin page (21 Oct)
- New dashboard page **Kembaran Digital**: a wireframe model of the real array (four landscape panels of 9 × 4 cells and the control box with R0–R10). The user cannot move the camera. Plain JavaScript, works offline.
- **Camera angles**: each panel's back has a terminal box with its 1N5822 bypass diode and a cable to the control box. Clicking a blue marker turns the camera (animated) to the panel's back for a diode problem, or to a low side view of its cable and connectors for series resistance, zoomed and highlighted; **Kembali ke tampak atas** returns. The overview offers the same views when the AI diagnosis is a bypass-diode fault or series resistance. Direct links: `view=` and `focus=` (CONTRACT §18).
- **Live mirror**: active wiring and closed relays, per-panel markers (green healthy, red light, blue electrical, grey dashed unknown; position only from single-panel sweeps), temperatures, last sweep vs the twin's expectation, AI diagnosis and pattern with their validation status; click a panel for its card.
- **What-if (simulation)**: Shade brush (circle outline, size up to the whole array, solid or shade cloth) painting per-cell shade; the twin predicts every wiring's power, ideal MLPE, the best wiring and the AI's pick; a log; **Ukur sekarang** compares the prediction with a live measurement.
- The sidebar's twin slider, shading list and calibrate button moved to this page (calibrate, alert threshold); the brush replaces the assumed-shading list. API `/twin/state`, `/twin/whatif` (CONTRACT §18).

## Stage 4H: documentation of the promises (21 Oct)
- New [docs/PROMISES.md](docs/PROMISES.md): the system in one picture, the proposal's three layers, all 18 promises with the technology, status and today's evidence (labeled measured / lab / sim / calc), the four performance targets, and what turns "built" into "proven" (board, data sessions, multimeter). Linked from README, START_HERE and docs/README.
- Demo replay of real sessions: not built (optional; the Putar ulang page already shows recorded sessions).

## Stage 4G: L3 page and the stability rule (20 Oct)
- New page **L3 dan stabilitas**: the team's semiconductor-switch design as data (labeled calculation): holding power per wiring, relays 1.43–2.50 W vs semiconductor 0.13–0.23 W (target ≤ 0.25 W), net gain (relays −0.73 W, MOSFET +0.62 / +0.82 W), the active wiring's holding power, the multimeter entries. API `/l3`.
- Stability rule built into auto mode (lock TCT while the last 3 monitor sweeps vary > 10 %), **off by default**, switchable on the Langsung page; lock/release are events. API `/stability` replays every measured dynamic scan (F1, D2).
- New simulation `SHADESHIFT_ML/uji_stabilitas.py` (research code unchanged; fixed TCT reproduces the published numbers). Simulation, 36 moving-shade scenarios with the ~3 s power cut of each monitor sweep: auto mode monitoring every 10 s loses to fixed TCT in all 36; every 5 min it roughly ties fixed TCT (+1.2 / +0.2 / −1.0 points for moving / mixed / leaf shade), so the default interval is now 300 s. The stability rule (window = last 3 monitor sweeps) helps a little on leaf shade (+0.5 at 1–2 min) and hurts on moving and mixed shade (−0.8 to −1.4); it stays off.
- Claims corrected accordingly (Status page, Langsung caption, START_HERE). The rule's window is now the last 3 sweeps (a fixed 30 s window could never fire at sensible intervals).
- Also: two tests made robust to a busy laptop.

## One firmware (20 Oct)
- `firmware/shadeshift_firmware/` now holds the project's only firmware, **3.2**: the original v2 measuring code plus single panels A–D, light sensor, `INFO`, AI on the ESP32 (`PILIH`, `DIAG`), the web page and the safety fixes. Removed: the v2.1 folder and the v2 copy (the original v2 stays untouched in `docs/before/firmware/` as the emergency fallback, and in git history).
- One guide, `firmware/CARA_PAKAI.md` (flashing, LDR wiring, bench test with `BENCH 1`, AI self-test, a 30-minute first check incl. WiFi on/off, data days, web page, DIAG, all commands, safety). The logger stays.
- New test: for the commands v2 had, firmware 3.2 gives exactly the original v2's measurements (the original is compiled read-only from `docs/before/`). The v2.1 panel and light tests now run on firmware 3.2.
- Messages and docs say "firmware 3.2" instead of "v2.1 / v3.1"; the boot banner prints the version; the restore tool no longer reports the replaced v2 files.

## Stage 4F: firmware v3.2, diagnosis on the ESP32 and its own web page (20 Oct)
- `DIAG`: the ESP32 sweeps 4S, 2S2P, TCT, 4P through the safe switch, computes the same 59 features as the laptop (with `pemilih.h`, on the printed numbers) and runs the active diagnosis model: `# diagnosis=…, yakin=…, model=…, t_us=…`. Tested: the board's class and confidence equal the laptop's on lab curves, for logistic regression and tree models. OFF stops it.
- The model reaches the board through the Model AI page: activating a diagnosis model writes `diagnosis_model.h` into firmware v3. Without it, DIAG refuses plainly.
- Web page from the ESP32: WiFi "SHADESHIFT", http://192.168.4.1, no internet; active wiring, Pmax, last I-V curve (SVG), the board's selector and diagnosis, warnings, and a STOP button that also stops running tasks. Read-only. `WEB 0/1` switches WiFi; the password must be changed in the sketch.
- Gateway: the board's diagnosis becomes an event and a measured `diagnosis_us` metric. `INFO` lists `web` and `diag`.
- Host simulator: WiFi and web-server stand-ins; page requests are scripted and served only when the firmware calls `handleClient()`, as on the board.
- **Not yet flashed.** Checklist in `firmware/CARA_PAKAI_v3.md` (change the WiFi password, phone test, DIAG, power with WiFi on and off).

## Stage 4E: live diagnosis and module map (20 Oct)
- Finding from the wiring list: the 2S2P strings are A+B and C+D and TCT ties the rows A∥C and B∥D, so swapping strings or rows leaves every topology curve unchanged. The topology sweeps alone cannot tell which single module is affected, only the pattern (one module, a string pair, a row pair, a diagonal, three, all). The exact position comes from the single-panel sweeps.
- New training task **pattern** (Model AI page), labeled from the recorded modules.
- Measured 2×2 map from the single panels: each panel relative to the best panel of the round and to its own A1 value; simple hints (current drop = shade, voltage drop = bypassed cells, neither = series resistance), marked as not validated.
- Live diagnosis per round: cause and pattern from the active models with their confidence and how they were tested ("not validated with measured data" until they are), plus whether the pattern agrees with the map. Shown on Langsung (newest round) and Ambil data (per scan).
- The decision audit also sweeps 4P, so it can be diagnosed. Target vs Bukti's diagnosis row now uses the active model ("met" only with a held-out-day test on real data, outdoor accuracy ≥ 85 %).
- API: `/scans/{id}/diagnosis`, `/devices/{id}/diagnosis` (CONTRACT §5.12, §15).

## Stage 4D: training the AI on measured data (20 Oct)
- Dataset builder: one example = one round (the same shading through 4S, 2S2P, TCT, 4P), from three sources kept separate: real sessions, the 30 lab rounds, and the research simulator (generated once and cached). Features from `port_c.py`, so the ESP32 computes the same numbers.
- Models in numpy/scipy (no new dependency): logistic regression (same objective as the research code's scikit-learn model) and a small decision tree.
- Fair test, never by repeat: held-out day when real data spans two days; otherwise leave-one-scan-out (marked weaker) or, without real data, leave-one-lab-pattern-out. Reports: accuracy, balanced accuracy, recall per class, confusion matrix, classes not tested; for the selector, its power loss next to the active selector and the best fixed wiring on the same rounds.
- Check: through this pipeline the shipped selector loses 0.82 % and the best fixed wiring (2S2P) 2.71 % on the lab rounds, exactly the published lab claim.
- Model registry (schema 5) with the shipped selector as the first entry. Activation: a diagnosis model by flag; a selector only if it lost less power than the active one, and then every copy is rewritten together (the weight headers, the on-board self-test's expected decisions, firmware v3, ONNX).
- C headers for the ESP32 (selector in the `pemilih_bobot.h` layout; diagnosis as `DIAG_*` arrays, compiled in a test).
- Import of session zips from another laptop. New page **Model AI**. API: `/training/data`, `/models…`, `/sessions/import` (CONTRACT §5.11, §14).
- Today, with lab and simulation only, the diagnosis is weak (simulation-trained 10 % on lab curves, lab-trained 37 % with 3 of 6 classes), as the research found. Real sessions are needed.

## Stage 4C: proving the targets (20 Oct)
- Ideal-MLPE reference = the sum of the four single-panel Pmax of the same round; each topology as % of it; recovery = the AI's mean % MLPE minus the best fixed topology's. Definitions identical to the research code that produced the proposal's numbers (`shadeshift/evaluation.py`, CONTRACT §13).
- Every full-scan round is evaluated: the AI's choice comes from the ESP32's own line (firmware v3) or the same model on the server. Dynamic conditions and rounds whose light changed > 5 % are listed but not counted.
- Live **Audit keputusan AI** (Langsung page, action `audit_decision`): 4S → AI decides → sweep 2S2P, TCT and panels A–D → switch to the AI's choice; the measured loss is stored. Database schema 4 (panels, 4P, MLPE in `evaluations`).
- New page **Target vs Bukti**: the four proposal targets (≥ 4 points recovery, ≥ 85 % outdoor diagnosis, ≤ 0.25 W control power, millisecond decisions), each with its evidence labeled measured / lab / sim / calc and "met" only from measured evidence; multimeter entry for ESP32 and relay power; measured timings; CSV for the technical report.
- API: `/evidence`, `/evidence/rounds`, `/evidence.csv`, `/metrics` (CONTRACT §5.10).
- Fixes: the server now stops within 5 s on Ctrl+C (it could wait for a gateway long-poll, and the launcher then force-stopped it); a test that depended on how long earlier tests took. 311 tests pass.

## Stage 4B: data collection, sessions and labeled full scans (19 Oct)
- New dashboard page **Ambil data**: start a session (place, sky, location, operator), pick the protocol condition code, check modules and diagnosis class, run a **full scan**, watch progress, read the quality checks, enter the panel temperatures per repeat, correct labels, end the session, download the zip.
- Condition catalog from the outdoor protocol with the team's corrections (5 Ω / 10 Ω resistors, E1 as a control, E5 = shorted bypass), 6 diagnosis classes (`shadeshift/fieldwork.py`, `GET /fieldwork/catalog`).
- Gateway action `full_scan`: every round sweeps the 4 topologies and, with firmware v2.1 / v3.1, the 4 single panels, in random order; all relays open during the pause between rounds; Stop ends it between steps. Files are named like the protocol (`LR1020_B2_TCT_u1`), repeats continue across scans, emulator scans are named `TIRUAN…`.
- Quality checks per scan: complete, light steady (LDR, 5 %), repeat spread (1.8 %), 4P vs the sum of the four panels; per session: A1 drift.
- Export zip: raw files exactly as received, incomplete sweeps in `_dibuang/`, `labels.csv`, `sesi.json`, `BACA_SAYA.txt` ("DATA TIRUAN" for emulator sessions).
- Database schema 3: `sessions`, `scans`, `sweeps.scan_id`. API: `/sessions…`, `/scans/{id}` (CONTRACT §5.8, §12).
- Langsung page: buttons for panels A–D when the firmware has them.
- Fixes found while testing:
  - the server computed the digital-twin expectation inside the database write lock; while the twin warmed up, every other write (heartbeats, commands) waited and could fail with "database is locked". It is now computed before the transaction;
  - command results went straight to the server and could arrive before the sweeps still in the gateway's outbox (a scan looked "done" with sweeps missing), and were lost if the server was briefly down. They now go through the outbox, in order;
  - a long full scan would have been marked "no result from gateway" after 120 s; its limit now scales with the scan length.
- New test: every API route must be documented in CONTRACT. 305 tests pass.

## Stage 4A: firmware v2.1, per-panel sweeps and light sensor (19 Oct)
- New `firmware/shadeshift_firmware_v2_1/` = v2 plus only these additions (every v2 command and output line unchanged):
  - `A`, `B`, `C`, `D`: one panel alone, through the same safe switch (Voc check for one panel), then `SWEEP` as usual. Relays from the wiring list: A = R7, B = R2+R8, C = R3+R9, D = R10;
  - LDR on ADS1115 A2: `# cahaya=` before and `# cahaya_akhir=` after every sweep, and the `CAHAYA` command;
  - `INFO` (`fw=2.1.0`, chip id, features) and `fw=` at the end of `STATUS`.
- Firmware v3 is now 3.1.0 with the same additions (`INFO` also lists `fitur=`).
- Laptop side: parser (`light_v`, `light_end_v` in the sweep header), API allowlist (`A`–`D`, `CAHAYA`; `cycle` may include panels), gateway reads both `INFO` forms, snapshot has `latest_by_panel`, upload override accepts panels, dashboard colours and Status page ("pemilih di laptop" for v2.1).
- Database schema 2: `sweeps.topology` also accepts `A`–`D` (table rebuilt by a migration that keeps all rows; foreign keys checked).
- The emulator refuses `A`–`D` with an honest `# GAGAL` line: the lab recordings have no single-panel curves.
- Tests: v2.1 compiled unchanged against simulated hardware; old commands give exactly the v2 output; panel relays, Voc check, light lines; schema and migration; 295 tests pass. Single-panel curves in tests are synthetic. **Not yet run on the board.** Guide: `firmware/CARA_PAKAI_v2_1.md`.

## Cleanup: documents and unused files (18 Oct)
- The top level now holds only `README.md`, `START_HERE.md` and `CHANGELOG.md`. The other documents moved to `docs/`: `ANALYSIS.md`, `CONTRACT.md`, `PLAN.md`, and `team/progress.md` and `team/UNTUK_DAUZAN.md`.
- New index [docs/README.md](docs/README.md) lists every document, who it is for, and its language.
- Removed unused files (still in `docs/before/`): `SHADESHIFT_ML/cek_inti.py` (needed a file never in the zip), `firmware/siklus_otomatis.py` (unreferenced), `SHADESHIFT_ML/edge_ai/kembaran_lab/cnn_diagnosis.pt` (rejected model), `SHADESHIFT_ML/hasil/pohon_d3_TCT.txt` (stale).
- Also removed: the old dashboard screenshots and `dasbor/requirements.txt`.

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
- `docs/ANALYSIS.md`: before/after comparison, missing and simulated parts, cloud dependencies, bugs, firmware safety findings, claims to qualify.
- `docs/CONTRACT.md`: interfaces. `docs/PLAN.md`: stages and decisions.

## Before (up to 17 Oct): `SHADESHIFT_untuk_Dauzan.zip`
- Firmware v2, simulation and model research, lab data.
- A Streamlit dashboard (`dasbor/`) that talked to the ESP32 directly over serial and needed the full project tree next to it.
