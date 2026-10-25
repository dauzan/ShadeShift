# ShadeShift: what the proposal promises and what delivers it

Status on **21 Oct 2026**, the start of the hackathon. Each promise is mapped to the technology that delivers it, where that runs, and the evidence that exists **today**. Numbers carry their source:
- **measured**: on our hardware;
- **lab**: the halogen-lamp recordings from October;
- **sim**: simulation;
- **calc**: design calculation.

"Laptop-tested" means tested automatically on this laptop: the unchanged firmware is compiled against simulated hardware that replays real lab curves. It has **not run on the real board yet**.

## 1. The system in one picture

```
 4 PV panels (2x2: A top-left, B bottom-left, C top-right, D bottom-right)
      │  relay matrix R0-R10 (wiring 4S / 2S2P / TCT / 4P, or one panel alone)
 ESP32 + ADS1115 + MCP4725 ── firmware 3.2 ── I-V sweeps, safe switching, AI on the board, web page (WiFi)
      │ USB serial
 Laptop: gateway (owns the port, AI cross-check, outbox) → local server (FastAPI + SQLite) → dashboard (Streamlit, 10 pages)
```

Everything runs locally and free: no cloud, no accounts, no internet needed for the demo. Software: Python, FastAPI, SQLite, Streamlit, ONNX Runtime, numpy/scipy. Firmware: Arduino for ESP32.

## 2. The three layers of the proposal

| Layer | Proposal | Technology now | Status |
|---|---|---|---|
| **L1 Digitalization** | Monitoring dashboard with I-V curves, active wiring, warnings, audit trail | Dashboard (10 pages) on the laptop, including the **digital twin** (live mirror of the array + What-if shading); web page on the ESP32 itself; every sweep, decision, command and event stored in SQLite | Laptop: complete, tested. ESP32 page: laptop-tested |
| **L2 Edge AI** | AI on the ESP32 chooses the wiring and diagnoses the cause | Selector (logistic regression, 73 numbers) and diagnosis (59 features, 6 causes) run in C on the ESP32 (`PILIH`, `DIAG`); the laptop gateway runs the same models as a cross-check and when the board has no model | Laptop-tested; the board computes exactly what the laptop computes |
| **L3 Low-power semiconductor switching** | MOSFET switch matrix replacing the relays (Figure 1) | Design and calculations (`SHADESHIFT_ML/saklar/`), shown on the **L3 dan stabilitas** page with the live wiring's holding power | Design only, not built |

## 3. Every promise

| # | Promise | Technology (where) | Status | Evidence today |
|---|---|---|---|---|
| P1 | Local dashboard: I-V curve, active wiring, warnings | **Langsung** page: live curves, wiring buttons, AI decision with "decided by" and time, twin "expected power" warning; **Kembaran Digital**: wireframe of the array mirroring wiring, relays and per-panel problems, plus What-if shading; **Peristiwa** audit trail | Complete, tested | Twin expected-power error ~8 % (lab, 7 conditions) |
| P2 | Dashboard on the ESP32 | Firmware 3.2 web page: WiFi "SHADESHIFT", http://192.168.4.1, last curve, wiring, AI choice and diagnosis, warnings, STOP | Laptop-tested | — |
| P3 | AI on the ESP32 chooses the wiring | `pemilih.h` after every 4S sweep, `PILIH`; the dashboard's **Pilih susunan otomatis** applies the ESP32's choice | Laptop-tested; C equals the laptop model on 38/38 lab curves | Loss 0.82 % vs 2.71 % for the best fixed wiring, 30 sets (**lab**) |
| P4 | AI diagnoses the cause (6 classes) | Training pipeline (**Model AI** page), live diagnosis on Langsung / Ambil data, `DIAG` on the ESP32 | Built; **no model trained on real data yet** | 78–82 % (**sim**); 10 % (sim-trained) and 37 % (lab-trained, 3 of 6 classes) on lab curves (**lab**) |
| P5 | Diagnosis from sweeps across topologies | One example = one round of 4S, 2S2P, TCT, 4P (59 features); full scans on **Ambil data** | Built | As P4 |
| P6 | Recover ≥ 4 points of ideal-MLPE power vs the best fixed wiring | Single-panel sweeps A–D (MLPE reference = sum of the four panels), recovery computed per scan round and per live **Audit keputusan AI** | Built | 3.35 points (**sim**, below 4). Measured: needs a session with single panels |
| P7 | Diagnosis ≥ 85 % on outdoor test data | Fair test on a held-out day, outdoor accuracy reported (**Model AI**, **Target vs Bukti**) | Built | No outdoor data yet. Needs labeled outdoor sessions on two days |
| P8 | Control power ≤ 0.25 W | Holding power per wiring (**L3** page); multimeter entry (**Target vs Bukti**) | Built | Relays 1.43–2.50 W (**calc**): not met with relays. Semiconductor design 0.13–0.23 W (**calc**). Measured: pending |
| P9 | Decision on the ESP32 in milliseconds | The ESP32 prints its decision time `t_us`; the gateway records it and the laptop's own decision time | Built | Laptop time measured; ESP32 time: on the first board run |
| P10 | Semiconductor switch layer (Figure 1) | Design, ratings, holding power and net-gain tables on the **L3** page | Design only | Net gain of choosing the wiring: relays −0.73 W, MOSFET +0.62 / +0.82 W (**sim/calc**) |
| P11 | Sweep only when power changes > 20 % | Gateway auto mode: monitor sweep, 20 % trigger, 30 s hold (anti-flapping) | Complete | Each monitor sweep cuts power ~3 s: every 10 s loses to fixed TCT; every 5 min roughly ties it (**sim**, 36 moving-shade scenarios). Default is now 5 min |
| P12 | Labeled dataset (~360 curves; natural shade, injected faults) | **Ambil data**: sessions, protocol condition codes, labels, quality checks, temperatures, zip export | Built | 120 old lab curves; new collection starts with the data sessions |
| P13 | Retrain with real data | Dataset from sessions + lab + sim (kept separate), logistic regression / decision tree, fair test, model registry, activation | Built | The pipeline reproduces the published lab result (0.82 % vs 2.71 %) |
| P14 | Model on the ESP32: size and time | Selector: 73 float32 (292 bytes), weights fingerprint checked by the gateway. Diagnosis: exported as a C header when activated | Laptop-tested | Size known; time on the board: first run (`uji_pemilih` prints it) |
| P15 | Which panel is faulty | Measured 2×2 module map from the single-panel sweeps; pattern from the topology sweeps | Built (map rules not validated) | Finding: topology sweeps alone cannot tell **which** single panel (string and row swaps give identical curves), only the pattern |
| P16 | Anti-flapping and stability rule | Hold time ✅; stability rule (lock TCT while power fluctuates) behind a switch | Built, rule **off** | Rule helps slightly on leaf shade, hurts on moving and mixed shade (**sim**) |
| P17 | Technical report: power, latency, accuracy vs target | **Target vs Bukti** page and CSV: each target with its evidence and source | Built | As P6–P9 |
| P18 | Temperature and light per measurement | LDR light reading at start and end of every sweep (relative); IR-thermometer panel temperatures entered per round | Built | LDR: relative only, not W/m² |

## 4. The four performance targets today

| Target | Status | Where it stands |
|---|---|---|
| ≥ 4 points MLPE recovery | Not measured | Simulation 3.35 points. Needs sessions with single-panel sweeps |
| ≥ 85 % outdoor diagnosis | Not measured | Simulation 78–82 %; weak on lab curves. Needs labeled outdoor data on two days |
| ≤ 0.25 W control power | Not met with relays (calc) | Relays 1.43–2.50 W; the semiconductor design 0.13–0.23 W is the path. Multimeter reading pending |
| Decision in milliseconds | Not measured on the board | Measured on the laptop; the ESP32 reports `t_us` on its first run |

**Target vs Bukti** marks a target "met" only from measured evidence.

## 5. What turns "built" into "proven"

1. **Board:** flash firmware 3.2 and run the first check in `firmware/CARA_PAKAI.md` §5. That proves P2, P3, P9 and P14 on real hardware.
2. **Data sessions** with single panels, outdoors, on two days, labeled on **Ambil data**. That gives P6, P7, P12 and P15, and lets P4/P5/P13 train on real data.
3. **Multimeter:** ESP32 and relay power with WiFi off and on. That gives P8.

## 6. Where to read more

| Topic | File |
|---|---|
| Running the system, Demo Day runbook, safe claims | [../START_HERE.md](../START_HERE.md) |
| Firmware, wiring, board checklist (Indonesian) | [../firmware/CARA_PAKAI.md](../firmware/CARA_PAKAI.md) |
| Every interface, formula and data format | [CONTRACT.md](CONTRACT.md) (§12 data collection, §13 targets, §14 training, §15 diagnosis, §16 ESP32 web/DIAG, §17 L3 and stability) |
| How it was built, stage by stage | [PLAN.md](PLAN.md), [../CHANGELOG.md](../CHANGELOG.md) |
