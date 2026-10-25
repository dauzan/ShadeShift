# ShadeShift: before vs. after analysis (Phase 1)

> **Historical record.** This describes the project as it was on 17 Oct 2026, before the rebuild. Most problems listed here are now fixed; see [../CHANGELOG.md](../CHANGELOG.md) and [../START_HERE.md](../START_HERE.md) §3. Links into `dasbor/` open today's rewritten files, so their line numbers no longer match. The original code is in [before/](before/) and in the first git commit.

Written 18 Oct 2026. Scope: compare the original project ("before", the zip, now extracted to [docs/before/](before)) with the current folder ("after"), find what is missing, weakened, simulated or cloud-dependent, and propose a prioritized plan. No project code was changed in this phase.

How to read the evidence column:
- **run**: I executed something and saw the result.
- **diff**: I compared files byte-for-byte.
- **read**: code or doc reading, with file and line.

Model numbers always say where they come from (**sim** = simulation, **lab** = halogen-lamp lab data). That is a team rule from the before docs, and this file follows it too.

---

## 0. Summary

1. **"After" = before + one new thing: a Streamlit dashboard ([dasbor/](../dasbor)).** Its core logic is sound. In a scratch copy of the full original tree, its self-test passes all 3 checks:
   - the selector gives the same decisions as the C code on 38/38 lab curves;
   - the lab losses (0.82 / 2.71 / 4.30 / 12.0 %) match the report;
   - the fake-ESP32 flow works.
2. **The after folder cannot run as delivered.** The dashboard loads its model, twin and lab data from `../SHADESHIFT_ML`, which only exists inside the zip. Running the test in place fails with `FileNotFoundError: ...\SHADESHIFT_ML\edge_ai\pemilih\pemilih_bobot.h`, and `streamlit`, `pvlib` and `pyserial` are not installed on this laptop. (run)
3. **The data path today is ESP32 → USB serial → the Streamlit process.** There is no ingestion port, server, API or database. Sweeps become loose CSV files without timestamps or device id, and the firmware has no WiFi code. (read)
4. **Edge AI is not at the edge.** The selector exists as C (`pemilih.h`, 73 floats) and was compiled for ESP32, but it has never run on the board and is not wired into the firmware. Every decision shown today is computed on the laptop by a Python port of that C code. No ONNX or TFLite anywhere. (read)
5. **No CSV upload page.** Replay only lists files already sitting in two fixed folders. (read)
6. **A no-hardware demo already exists.** "TIRUAN" (Indonesian for fake/emulated) is an emulated ESP32 that replays *real* lab curves and is clearly labeled in the UI. It is the best base for the requested demo mode.
7. **No paid or cloud services in the core pipeline.** The online-only bits are listed in §6 with free local replacements:
   - Streamlit's usage telemetry and its "Deploy" (Streamlit Cloud) button;
   - Google Fonts in a guide page;
   - a claude.ai link;
   - external datasets, one of which needs an IEEE account.
8. **The biggest demo risks:**
   - the project is not self-contained (point 2);
   - a browser refresh or a second tab can leave the ESP32's COM port locked until Streamlit restarts;
   - nothing has ever run against the real ESP32;
   - an `OFF` sent during a running `SIKLUS` cycle is ignored by the firmware while 4S can be at ~88 V (§7, F1).
9. **Scoring reality** (official participant guide): the final score is 20 % proposal + 80 % Demo Day.
   - Within Demo Day, a live prototype "tanpa bug kritis atau workaround" (without critical bugs or workarounds) is **25 %**.
   - A Demo Day score below 2.80 means no funding.
   - So the real-device path must be the primary demo. Replay/emulation can only be a clearly marked fallback.
   - The organizers define L1 as including an **audit trail** and L2 as AI running **at the edge**.

---

## 1. Method

- Extracted `SHADESHIFT_untuk_Dauzan.zip` into `docs/before/` with a script that refuses to overwrite.
  - 264 files.
  - The zip's single top-level folder `SHADESHIFT_untuk_Dauzan/` was stripped, so `docs/before/` mirrors the original project root.
  - The zip itself is untouched.
- Read all 16 `.md` files in `docs/before/`, plus [dasbor/README.md](../dasbor/README.md) and both copies of `progress.md` (the after copy differs only by the dashboard entry; diff).
- Read in full:
  - the firmware ([shadeshift_firmware.ino](before/firmware/shadeshift_firmware/shadeshift_firmware.ino)) and the logger;
  - the C selector ([pemilih.h](before/SHADESHIFT_ML/edge_ai/pemilih/pemilih.h)) and its Python port ([port_c.py](before/SHADESHIFT_ML/edge_ai/pemilih/port_c.py));
  - all four dashboard files.
- Ran:
  - `uji_dasbor.py` in place (fails) and in a scratch mirror of the full tree (passes);
  - a Python replica of the on-board selector test (`uji_pemilih.ino`) with both copies of the weights;
  - a decision comparison of both weight copies on all 38 lab 4S curves.
- Did not:
  - install anything;
  - modify project files;
  - touch hardware;
  - use the network, apart from one read-only PyPI version query.
- A parallel verification workflow re-checks every finding independently. See §12.

---

## 2. The project in brief

SHADESHIFT is a box for 4 small PV modules (2×2, 10 W class; lab setup under a halogen lamp).

**Hardware chain.**
- An ESP32 sweeps the array's I-V curve through a MOSFET electronic load (MCP4725 DAC → LM358 → IRFP260N).
- An ADS1115 reads voltage and current.
- 11 relays switch the array between four topologies: **4S, 2S2P, TCT, 4P**.

**Why it matters.** Under partial shading the best topology changes. A tiny model picks the topology from the *shape* of one 4S sweep.

**Hackathon framing (Smart-X DeepTech, Demo Day 21–23 Oct 2026; 80 % of the score is the live demo).** Three layers:
- **L1 digitalization**: the dashboard.
- **L2 edge AI**: the selector on the ESP32.
- **L3 low-power semiconductor**: a MOSFET switch-matrix design, not built.

**Industry clinic.** PLN's clinic feedback shifted interest toward fault detection and *locating* the faulty panel.

**Glossary used below:**

| Indonesian | English |
|---|---|
| sapuan | sweep |
| susunan | topology |
| pemilih | selector |
| kembaran (digital) | digital twin |
| dasbor | dashboard |
| tiruan | emulated / fake |
| terukur / harapan | measured / expected |
| rugi | loss |
| relai | relay |
| LULUS / GAGAL | PASS / FAIL |

---

## 3. "Before" documentation map

**Main overview file: [UNTUK_DAUZAN.md](before/UNTUK_DAUZAN.md)** ("for Dauzan", the handover document).
- [CLAUDE.md](before/CLAUDE.md) tells the assistant to read it first.
- It holds the product summary, signal chain, design decisions and their reasons, the prioritized task list, the file map, and which numbers may be quoted.
- [progress.md](before/progress.md) is the long-form status log and decision record (it holds the hackathon rules, the PLN clinic notes, and the to-do list up to 21 Oct).
- [README.md](before/README.md) is only a folder map of the *full* project. Several of the folders it lists were deliberately left out of the zip.

| File | Purpose | Notes |
|---|---|---|
| [CLAUDE.md](before/CLAUDE.md) | Instructions for an AI assistant: read UNTUK_DAUZAN first, reply in Indonesian, label every number sim/lab | Archived; not active here |
| [README.md](before/README.md) | Folder map of the full project | Lists folders not in the zip: `_arsip/`, `analisis/`, `wadah_3d/`, `gambar/`, `SHADESHIFT_ML/pcb/`, `berkas_kirim/`, `pendaftaran/` |
| [UNTUK_DAUZAN.md](before/UNTUK_DAUZAN.md) | **Main overview / handover** | Tasks 1–5: run the selector test on ESP32, firmware integration + anti-flapping + 20 % trigger + stability rule, measurements for the technical report, Streamlit dashboard, optional module localization |
| [progress.md](before/progress.md) | Status, concept vs. MLPE (module-level power electronics: microinverters/optimizers on every panel), hardware, models, data, L3, protocol, official rules, decisions, to-dos, log | After copy adds the 17 Oct dashboard entry |
| [firmware/CARA_PAKAI.md](before/firmware/CARA_PAKAI.md) | How to flash and operate firmware v2, bench tests, logger | **Stale**: documents `SUHU`, `URUT_SUHU`, OneWire/DallasTemperature, which v2 does not have (§8) |
| [rangkaian/daftar_belanja.md](before/rangkaian/daftar_belanja.md) | Shopping list with IDR prices | Hardware purchases; team rule says no new purchases |
| [rangkaian/daftar_kabel.md](before/rangkaian/daftar_kabel.md) | Wiring list: relay matrix, GPIO map, measurement path, power | README says it shows the older relay-module arrangement |
| [SHADESHIFT_ML/RENCANA.md](before/SHADESHIFT_ML/RENCANA.md) | Older plan for a "next competition": stages, go/no-go gates, success metrics | Predates Smart-X. Item E1 asks for a real-time display of "active topology, power, power *without* switching" |
| [SHADESHIFT_ML/RINGKASAN_LANGKAH1.md](before/SHADESHIFT_ML/RINGKASAN_LANGKAH1.md) | Step-1 results: sim pipeline, selector, 12/24/48 V sensitivity, moving-shade study, diagnosis | Some physical-test numbers superseded by LAPORAN_UJI_FISIK |
| [SHADESHIFT_ML/CATATAN_BUG_VOC.md](before/SHADESHIFT_ML/CATATAN_BUG_VOC.md) | The Voc simulation bug and its impact | Diagnosis 83–89 % → **78–82 % (sim)**; selector unchanged on lab |
| [SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md](before/SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md) | Outdoor (sun) measurement protocol draft: conditions, metadata, file naming | Not yet updated with the corrections in progress.md §8 |
| [SHADESHIFT_ML/data/data_lab/README.md](before/SHADESHIFT_ML/data/data_lab/README.md) | Lab dataset: conditions V1…V6, naming, known bad files | V5 and V1d must not be used |
| [SHADESHIFT_ML/edge_ai/LAPORAN_JALUR_B.md](before/SHADESHIFT_ML/edge_ai/LAPORAN_JALUR_B.md) | Report on selector alternatives, the lab digital twin (~8 % power error, lab) and diagnosis/CNN attempts | Conclusion: diagnosis cannot be validated with lamp data |
| [SHADESHIFT_ML/edge_ai/pemilih/README.md](before/SHADESHIFT_ML/edge_ai/pemilih/README.md) | How to deploy the selector on ESP32 (C API) | "Not yet run on the board" |
| [SHADESHIFT_ML/saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md](before/SHADESHIFT_ML/saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md) | L3: back-to-back MOSFET switch matrix to replace the relays; holding power and net-gain calculations | Design and calculation only |
| [SHADESHIFT_ML/uji_model/LAPORAN_UJI_FISIK.md](before/SHADESHIFT_ML/uji_model/LAPORAN_UJI_FISIK.md) | Model tests on lab data | Source of the quotable claim: selector loss **0.82 % vs 2.71 %** for the best fixed topology (lab, 30 sets, 6 independent patterns) |

The official hackathon rules are in a PDF in the zip, `DeepTech for Smart-X Hackathon 2026_Bootcamp.pdf`, summarized in progress.md §10:
- a working prototype "without critical bugs or workarounds";
- a technical report with **power, latency and accuracy** against the partner's targets;
- the L1/L2/L3 layers;
- the final score is 20 % proposal + 80 % demo.

---

## 4. "After" project map

```
D:\ShadeShift
├── SHADESHIFT_untuk_Dauzan.zip   original project (36 MB), untouched
├── progress.md                   before's copy + 17 Oct dashboard entry
├── dasbor/                       NEW: Streamlit dashboard
│   ├── app.py                    UI: "live" page (serial or TIRUAN) and "replay" page
│   ├── inti.py                   sweep parsing, Pmax, selector (via port_c.py), twin (via cocokkan_lampu.py), light-scale calibration
│   ├── koneksi.py                serial reader thread + CSV saving, emulated ESP32 (TIRUAN), auto-select flow, auto mode
│   ├── uji_dasbor.py             self-test (3 checks)
│   ├── requirements.txt          streamlit>=1.40, pandas, numpy, scipy, pvlib, pyserial
│   ├── README.md
│   └── gambar_langsung.png, gambar_putar_ulang.png   screenshots
└── docs/before/                  the zip, extracted in this phase
```

**Stack.** Python (3.12.4 on this laptop), Streamlit with Altair charts, numpy/pandas/scipy, pvlib (only for the twin), pyserial (only for a real device). The device runs Arduino firmware v2 over USB serial at 115200 baud. No server, no database, not a git repository.

**How to run.** The documented steps ([dasbor/README.md](../dasbor/README.md)) are `pip install -r requirements.txt`, `cd dasbor`, `streamlit run app.py`, and the test is `python uji_dasbor.py`. What actually happens on this laptop:

| Check | Result | How checked |
|---|---|---|
| `python uji_dasbor.py` in place | **Fails**: `FileNotFoundError: D:\ShadeShift\SHADESHIFT_ML\edge_ai\pemilih\pemilih_bobot.h` ([inti.py:9](../dasbor/inti.py#L9) points to `../SHADESHIFT_ML`) | run |
| `import streamlit` / `pvlib` / `serial` | All `ModuleNotFoundError` | run |
| `uji_dasbor.py` in a scratch copy of the full tree | **Passes**. Selector = C on 38/38; 30 lab sets, mean loss selector / fixed 2S2P / TCT / 4S = 0.82 / 2.71 / 4.30 / 12.0 % (lab); TIRUAN flow on V6_paranet65 picks TCT | run |
| Streamlit UI | Not launched here (not installed). The screenshots show it ran in the previous session's environment | read |
| Real ESP32 | Never connected ([dasbor/README.md:48](../dasbor/README.md#L48)) | read |
| Digital twin | Not exercised by the self-test. It needs pvlib through `sim_core.py` | read |

The README's install order is also wrong: `pip install -r requirements.txt` comes *before* `cd dasbor`, but the file lives in `dasbor/`.

**What works (in the full tree).**
- Live page:
  - topology buttons, SWEEP, a free-text command box, LANJUT/BATAL (continue/cancel prompts during multi-topology cycles);
  - I-V and P-V charts with the twin's dashed expected curve;
  - measured vs expected Pmax with a warning threshold (default 15 %);
  - one-shot "auto select" (4S sweep → selector → switch → sweep);
  - "auto mode": re-sweep every N s, re-select only if power changes by more than 20 %, minimum hold time. This runs on the laptop.
- Replay page: lab or dashboard folders, the four curves, selector vs best measured, and a summary table of all lab sets.
- Sweeps from a real device are saved as CSV in `SHADESHIFT_ML/data/data_dasbor/`. Raw lab data is never written.

---

## 5. Before vs. after

### 5.1 What improved

| ID | Improvement | Evidence |
|---|---|---|
| I1 | A dashboard now exists. Before: "Dasbor Streamlit BELUM" (not yet) | progress.md diff (diff) |
| I2 | No-hardware rehearsal: TIRUAN answers 4S/2S2P/TCT/4P, SWEEP, OFF, VOC, STATUS from real lab curves; the condition can be changed live to mimic shading changes | [koneksi.py:8-67](../dasbor/koneksi.py#L8-L67) (read) |
| I3 | Selector parity is guaranteed by construction: weights are parsed straight from the C header, so the laptop and the ESP32 cannot drift apart | [inti.py:119-125](../dasbor/inti.py#L119-L125) (read); 38/38 (run) |
| I4 | Expected power from the twin, with one-click light-scale calibration from an unshaded sweep | [inti.py:205-212](../dasbor/inti.py#L205-L212) (read) |
| I5 | The 20 % trigger rule from `dinamis.py` (best policy in sim) can be tried end-to-end, on the laptop | [koneksi.py:188-201](../dasbor/koneksi.py#L188-L201) (read) |
| I6 | Honest labeling: TIRUAN banner, "indication, **not** a validated diagnosis", "kembaran ~8 % error" captions | [app.py:69-70](../dasbor/app.py#L69-L70), [app.py:109](../dasbor/app.py#L109) (read) |
| I7 | An automated self-test that reproduces the report's lab numbers | [uji_dasbor.py](../dasbor/uji_dasbor.py) (run) |

### 5.2 What regressed

| ID | Regression | Impact | Evidence |
|---|---|---|---|
| R1 | **The after folder is incomplete.** It dropped `SHADESHIFT_ML/` (weights, port_c.py, twin, sim_core.py, lab data), `firmware/`, `rangkaian/`, `foto/` and the docs. The dashboard hard-depends on `../SHADESHIFT_ML`, so it cannot start | Critical: nothing runs in place | (run) |
| R2 | Install instructions got worse: wrong order (README), and `requirements.txt` pins `streamlit>=1.40` although the code needs **streamlit ≥ 1.51**. `width=` on `st.button` exists from 1.48, `width="stretch"` on `st.dataframe` from 1.49, and `width=` on `st.altair_chart` from 1.51 | Medium: any Streamlit 1.40–1.50 crashes with `TypeError` on the live page | [app.py:114](../dasbor/app.py#L114), [app.py:180](../dasbor/app.py#L180) (read). Versions checked against Streamlit's source at the release tags |

Nothing that worked in "before" was made functionally worse. The firmware, logger and models are unchanged, just missing from the folder.

### 5.3 What is missing

| ID | Missing | Notes |
|---|---|---|
| M1 | **Dedicated ingestion port** (user-reported) | No HTTP/WebSocket/MQTT endpoint, server or API. Only a COM port is opened by the Streamlit session itself. Only one program can own the port (the dashboard *or* the logger) |
| M2 | **Persistent storage** | No database. Sweeps are CSV files without capture time, device id, firmware version or the selector decision. TIRUAN sessions are not saved at all ([koneksi.py:75](../dasbor/koneksi.py#L75)) |
| M3 | **Edge AI on an edge runtime** (user-reported) | `pemilih.h` is not in the firmware: `sapuan()` only prints points ([.ino:117-152](before/firmware/shadeshift_firmware/shadeshift_firmware.ino#L117-L152)). `uji_pemilih` never ran on the board. No ONNX/TFLite export. The anti-flapping, 20 % trigger and stability rule exist nowhere in firmware |
| M4 | **CSV upload page** (user-reported) | Replay only lists `data_lab/` and `data_dasbor/` ([app.py:234-235](../dasbor/app.py#L234-L235)) |
| M5 | **One-command start on a fresh laptop, offline** | No venv, no start script, no lock file. The README "Belum diuji" ("not yet tested") section admits the real-device path is untested |
| M6 | **Technical-report metrics** (official requirement) | Decision latency, sweep duration and relay switch time are not measured or shown. ESP32+relay power is not recorded. Simulations assume 3 s sweeps and 0.6 s switching, which were never measured |
| M7 | **Stability rule** (lock TCT when power fluctuates) | Listed as an agreed workaround in progress.md (16 Oct). Not implemented anywhere, also not in the dashboard ([dasbor/README.md:24](../dasbor/README.md#L24)) |
| M8 | **Device identity, timestamps, sequence numbers** | The protocol has none. The ESP32 has no RTC, so time must come from the receiver |
| M9 | **Health/status** | No "device online / last seen" indicator, no reconnect logic, no gateway concept |
| M10 | **PLN's request: locate the faulty module** | No experiment or code. UNTUK_DAUZAN task 5 marks it optional |
| M11 | **L3 visibility in the demo** | The semiconductor-switch design (calculation: relay holding power 1.43–2.50 W vs MOSFET 0.13–0.23 W) is not shown anywhere |
| M12 | **Tests for anything beyond the selector** | No tests for parsing edge cases, saving, the twin, or the UI. No single test command |
| M13 | **Data export** | No session export (CSV/JSON) for the technical report |

### 5.4 What is simulated or "faked", and how it is labeled

| ID | What | Real or not | Labeled? |
|---|---|---|---|
| S1 | TIRUAN (emulated ESP32) | Replays **real lab curves**, picking one of 3 repeats at random. Switch and sweep delays (0.6 s, 1.5 s) are guesses. Supports only part of the firmware commands (SIKLUS, PANTAU, KAL, CEKVOC, VPANEL and others are "ignored") | Yes: yellow banner and "Tersambung: TIRUAN" ("Connected: TIRUAN") |
| S2 | Selector decision ("Keputusan pemilih") | Computed **on the laptop** with the same weights as `pemilih.h`, *not* on the ESP32 | **Weakly.** The metric label does not say where it ran; only a button tooltip says "dihitung di laptop" ("computed on the laptop"). Must be fixed so a judge can't mistake it for on-device AI |
| S3 | Auto mode / trigger rule | Runs on the laptop, not in firmware | Yes, in the expander caption |
| S4 | Expected power (twin) | Simulation fitted on lab condition V1c. Power error ~8 % on 7 lab conditions (lab); shading presets are nominal | Yes |
| S5 | Diagnosis (6 classes) | **Sim only** (78–82 %). Fails on lab data (3–13 %). Not shown in the dashboard, which is correct | n/a |
| S6 | "Data source" (user-reported) | Without hardware, everything shown is replayed lab data. With hardware, the path is real but has never been exercised | Yes in the UI. Untested in reality |

---

## 6. Paid, cloud and online dependencies

The core pipeline uses only free, local, open-source parts: Python, Streamlit, numpy/pandas/scipy, pvlib, pyserial, Arduino core and libraries. Nothing needs a paid API, an account or a card. These items touch the internet or a third party:

| Where | What | Problem | Free local replacement |
|---|---|---|---|
| Streamlit (after) | Usage-statistics telemetry is on by default; the toolbar shows a **Deploy** button (Streamlit Community Cloud) | Telemetry calls out when online; Deploy invites a cloud account | `.streamlit/config.toml`: `browser.gatherUsageStats = false`, `client.toolbarMode = "viewer"` |
| [panduan_data.html](before/SHADESHIFT_ML/panduan_data/panduan_data.html) | Google Fonts | Offline it silently falls back to system fonts. Cosmetic only | System font stack, or vendored font files |
| [progress.md:72](before/progress.md#L72) | Guide hosted as a claude.ai artifact | Needs internet and an account to view | The same content exists locally as `panduan_data.html` |
| panduan_data.html / progress.md §8 | External datasets: TECNALIA (Zenodo), Mendeley, **IEEE DataPort** | Need internet; licenses not checked; IEEE DataPort generally needs an IEEE account | Not needed for the demo. If used later: Zenodo/Mendeley only, after checking licenses; skip IEEE DataPort |
| Firmware setup | Arduino IDE, esp32 core, Adafruit libraries | Free, but downloaded once | Document a one-time setup; optionally `arduino-cli` with a local package cache |
| [daftar_belanja.md](before/rangkaian/daftar_belanja.md), protocol | Purchases: Tokopedia/Shopee list, BH1750 light sensor, solar power meter | Costs money and conflicts with the team rule "no new purchases" | Use the existing LDR (free ADS1115 channel A2) as a *relative* light indicator; manual IR-thermometer temperature entry |

No component has to be swapped for the new architecture either. SQLite, Mosquitto, FastAPI/Flask, ONNX Runtime and Streamlit are all free and local.

---

## 7. Bugs and demo risks in the after code

| ID | Severity | Problem | Trigger | Evidence |
|---|---|---|---|---|
| B1 | Critical | Hard-coded `../SHADESHIFT_ML`. Fails in this folder | Any start in place | [inti.py:9](../dasbor/inti.py#L9) (run) |
| B2 | High | **COM port stays locked after a browser refresh or second tab.** The connection object lives in `st.session_state` (per browser session); its reader thread keeps the port open, so the new session's `serial.Serial(...)` gets "Access is denied" until Streamlit is restarted | Refresh the page during the demo, or open it on the projector *and* the laptop | [app.py:77](../dasbor/app.py#L77), [koneksi.py:78](../dasbor/koneksi.py#L78), [koneksi.py:89](../dasbor/koneksi.py#L89) (read; needs a device or virtual COM port to reproduce) |
| B3 | Medium | Version pin `streamlit>=1.40` is too loose: the code needs ≥ 1.51 (`width=` on `st.button` 1.48, `st.dataframe` 1.49, `st.altair_chart` 1.51). `st.fragment(run_every=…)` is fine from 1.40 | Streamlit 1.40–1.50 already installed → `TypeError` | `dasbor/requirements.txt` (since replaced by the pinned root `requirements.txt`), `dasbor/app.py:114` of the old dashboard (read + Streamlit source at release tags) |
| B4 | Medium | Telemetry on, Deploy (cloud) button visible; no `.streamlit/config.toml` | Every run | Screenshots show "Deploy" (read) |
| B5 | Low | If a 4S sweep has fewer than 10 valid points, the selector returns `None` and the auto flow then tries to switch to topology `None`. This surfaces as an unclear `'NoneType' object has no attribute 'strip'` error | Partial or failed real sweep | [inti.py:134](../dasbor/inti.py#L134), [koneksi.py:166-169](../dasbor/koneksi.py#L166-L169) (read) |
| B6 | Low | TIRUAN runs every command in its own thread, while the real firmware is strictly sequential. Rapid clicks can interleave (for example SWEEP during a switch → "pick a topology first") | Fast clicking in demo mode | [koneksi.py:30-31](../dasbor/koneksi.py#L30-L31) (read) |
| B7 | Low | Saved sweeps carry no capture time or device id; TIRUAN sweeps are not saved | Always | [koneksi.py:113-120](../dasbor/koneksi.py#L113-L120) (read) |
| B8 | Low | The twin's shade-net (paranet) transmission is computed from V3_paranet65 only. It comes out at **0.137** (run with pvlib); the dashboard README says ~0.14; LAPORAN_JALUR_B says 0.11 | Shading presets | [inti.py:176-188](../dasbor/inti.py#L176-L188), [LAPORAN_JALUR_B.md:26](before/SHADESHIFT_ML/edge_ai/LAPORAN_JALUR_B.md#L26) (run) |
| B9 | Medium | Sweeps captured by the dashboard never show up on the replay page. Replay only lists `<condition>_<topology>_u<n>.csv`, but the dashboard saves names like `auto_HHMMSS_4S`, `dasbor_HHMMSS` or `pantau_…`, plus `_2` suffixes | Any live session | [inti.py:108](../dasbor/inti.py#L108), [koneksi.py:115-118](../dasbor/koneksi.py#L115-L118) (read, workflow reader) |
| B10 | Low | Topology state is not synced from the device. Nothing sends or parses `STATUS` on connect, so the UI can show "terbuka" (open) while relays are closed | Board not reset on port open | [koneksi.py:101-103](../dasbor/koneksi.py#L101-L103) (read, workflow reader) |
| B11 | Low | The waits accept *any* `# siap:` or `# SELESAI` line, whichever command caused it. Sweeps are never checked for completeness against `N=201` | Serial glitch | [koneksi.py:150-156](../dasbor/koneksi.py#L150-L156) (read, workflow reader) |
| B12 | Low | The manual-port default is `COM3`, which on **this** laptop is a Bluetooth serial link, not an ESP32 | First connection attempt | [app.py:88](../dasbor/app.py#L88), Windows device query (workflow reader) |

### 7.1 Firmware and hardware risks (before code, still current)

| ID | Severity | Problem | Evidence |
|---|---|---|---|
| F1 | **High (safety)** | `OFF`/`STOP` cannot stop a running `SIKLUS`. While SIKLUS switches and sweeps, the firmware does not read serial; at the LANJUT/BATAL prompts every other line is read and silently dropped. A dashboard `OFF` therefore does nothing during a cycle, with 4S at up to ~88 V DC | [.ino:154-164, 174-186](before/firmware/shadeshift_firmware/shadeshift_firmware.ino#L154-L186) |
| F2 | Medium | `DAC <n>` is accepted while a topology is active and R0 is closed, which can hold the MOSFET in its linear region indefinitely; there is no thermal or over-current check besides the 4 A fuse. `RELAI`/`UJIRELAI` are refused only while a topology is active, although the docs say "only without panels" | [.ino:196, 205, 266](before/firmware/shadeshift_firmware/shadeshift_firmware.ino#L196) |
| F3 | Medium | SIKLUS sweep-failure detection is dead code. A failed sweep returns without clearing `topoAktif`, so `if (topoAktif < 0)` never fires and the cycle continues with a missing CSV | [.ino:130, 182](before/firmware/shadeshift_firmware/shadeshift_firmware.ino#L182) |
| F4 | Medium | Dim-light demo risk. Sweeps abort with "arus tidak terdeteksi" (no current detected) below a hard-coded 5 mA, and lab currents are only ~16 mA. The Voc window depends on `VPANEL`. Without the halogen lamp, or with a dimmer one, sweeps or switches can fail on stage | [.ino:104, 126, 130](before/firmware/shadeshift_firmware/shadeshift_firmware.ino#L126) |
| F5 | Medium | No sequence numbers, checksums or ids. Real data loss already happened unnoticed: `V3_paranet75_TCT_u2.csv` has 204 lines where its siblings have 208, and a corrupted row `35.2742,02113,0.00219,0.0770` (run: `wc -l`, `awk`) | data_lab file |
| F6 | Medium | Prototype fragility: breadboard and dupont wiring, mixed relay modules with dead channels, past relay faults (V1d, V5). No spares can be bought | [daftar_kabel.md:32, 48](before/rangkaian/daftar_kabel.md#L32), data_lab README |
| F7 | Low | Calibration constants (`R_ATAS`, `R_BAWAH`, `R_SHUNT`, offsets) are the nominal placeholders marked "fill in after measuring". The selector is unaffected (it uses shape ratios), but absolute watts may be off | [.ino:34-39](before/firmware/shadeshift_firmware/shadeshift_firmware.ino#L34-L39) |

### 7.2 Claims that must be qualified in the dashboard and pitch

| Claim in the docs | What the data actually supports |
|---|---|
| Trigger rule "tidak pernah lebih buruk" (never worse) than the best fixed topology (sim) | True only for per-type **averages**: trigger-20 % 89.7 / 91.8 / 83.1 vs fixed TCT 89.6 / 89.2 / 80.9 (% of MLPE energy). Per scenario it is worse than fixed TCT in **10 of 12** leaf, 5 of 12 moving and 6 of 12 mixed scenarios, and down to −5.04 points vs the best fixed topology of that scenario. Scenarios are synthetic (`hasil/dinamis_ringkasan.csv`; run) |
| Selector lab loss 0.82 % vs 2.71 % | Valid, but only among {4S, 2S2P, TCT}. In the lab, **4P was the best measured topology in 30 of 30 sets** (run), and 2S2P/TCT lab Vmp (14–29.5 V) is also below the 30 V controller window used to exclude 4P. State the convention when quoting |
| Dynamic-shading results (`dinamis.py`) | Assume continuous power monitoring at the MPP and a perfect full scan per sweep. The real device measures power only by sweeping. Today's auto mode re-sweeps periodically |
| Loss numbers | Three different metrics appear in the docs: points of % MLPE power (sim), % loss vs best measured (lab), % of MLPE energy over time (dynamic sim). Label which one is shown |
| Measured Pmax vs expected | With ~1 % current noise, max(V·I) over a sweep overestimates Pmax by ~0.7–1.8 % (sim). Thresholds should allow for it |
| "Model kecil" quantized (PDF wording for L2) | The model is float32 (73 floats), not quantized. Don't claim quantization |
| Proposal targets | ≥ 4 points recovery: sim ~3.35 points vs fixed TCT, lab ~2 %. ≥ 85 % outdoor diagnosis: no outdoor data. ≤ 0.25 W control: relays 1.43–2.50 W calculated. Millisecond decisions: unmeasured. Show these as "target vs current evidence", not as achieved |

---

## 8. Documentation inconsistencies in "before"

| ID | Inconsistency | Evidence |
|---|---|---|
| D1 | `CARA_PAKAI.md` and the outdoor protocol tell you to install OneWire/DallasTemperature, set `URUT_SUHU` and type `SUHU`. Firmware v2 has no temperature code ("tidak ada sensor suhu", no temperature sensor) and no `SUHU` command | [CARA_PAKAI.md:5,13,21](before/firmware/CARA_PAKAI.md#L5), [.ino:4](before/firmware/shadeshift_firmware/shadeshift_firmware.ino#L4) |
| D2 | **Stale weights in the board-test sketch.** `uji_pemilih/pemilih_bobot.h` differs from the current `pemilih/pemilih_bobot.h` (all means, scales, weights and biases). Both still give `LULUS 12/12` on the sketch's test vectors and identical decisions on all 38 lab curves (same 0.82 % lab loss), so the board test would not reveal it. But the flashed model would not be the evaluated one. The sketch itself says to copy the headers from `edge_ai/pemilih/` | (diff, run) |
| D3 | The logger saves to `<project>/data_lab/` (`firmware/../data_lab`). The lab dataset and the dashboard use `SHADESHIFT_ML/data/data_lab/` | [logger_shadeshift.py](before/firmware/logger_shadeshift.py) (read) |
| D4 | `pemilih.h` refers to `SPESIFIKASI.md`, which is not in the zip. CARA_PAKAI refers to a notebook function `pmax_ukur` that is not in the zip | [pemilih.h:5](before/SHADESHIFT_ML/edge_ai/pemilih/pemilih.h#L5), [CARA_PAKAI.md:48](before/firmware/CARA_PAKAI.md#L48) |
| D5 | Voltage limit: the protocol says ~139 V (GAIN_ONE math); progress.md says ~110–120 V effective because of the 3.3 V supply | [PROTOKOL_LUAR_RUANGAN.md:8](before/SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md#L8), [progress.md:38](before/progress.md#L38) |
| D6 | The protocol still lists fault resistors E3/E4 as 1 Ω and 2.2 Ω; progress.md says they are too small and proposes 5 Ω and 10 Ω | [PROTOKOL_LUAR_RUANGAN.md:45](before/SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md#L45), [progress.md:74](before/progress.md#L74) |
| D7 | Older physical-test numbers (24 curves, fixed 2S2P 2.76 %) in RINGKASAN_LANGKAH1 vs the current report (30 sets, 2.71 %). The dashboard correctly uses the current ones | [RINGKASAN_LANGKAH1.md:30](before/SHADESHIFT_ML/RINGKASAN_LANGKAH1.md#L30) |
| D8 | The proposal quotes diagnosis 83–89 %. The corrected figure is **78–82 % (sim)**, and it fails on lab data | [CATATAN_BUG_VOC.md](before/SHADESHIFT_ML/CATATAN_BUG_VOC.md) |
| D9 | UNTUK_DAUZAN's install line (`streamlit pandas matplotlib pyserial`) differs from the dashboard's needs (pvlib, scipy; matplotlib unused) | [UNTUK_DAUZAN.md:53](before/UNTUK_DAUZAN.md#L53) |

---

## 9. Rules from the before docs that Phases 2–3 must keep

- Raw lab files (`data_lab/*.csv`) are never modified. Bad rows are handled in code.
- No new purchases. Use existing hardware: the LDR as a relative light indicator, temperature entered manually from the IR thermometer.
- Every model number names its source (sim/lab).
  - Never claim diagnosis accuracy on real data.
  - Never claim the CNN is used.
  - Use 78–82 % (sim), not 83–89 %.
  - The selector's sim accuracy is only 68.9 % (balanced 47.5 %). The quotable result is the **lab loss 0.82 % vs 2.71 %**.
- Relays switch only through the firmware's safe sequence: DAC 0 → open R0 → open all → close the target relays → Voc check → close R0. 4S can reach about 88 V DC.
- Downloads and installs only on drive D. In practice: a virtual environment under `D:\ShadeShift`.
- Log technical progress in `progress.md` (newest entry at the top of "Log").
- Safe TRL claim: 4. Claim TRL 5 only after the sun session.

---

## 10. Prioritized improvements

Ordered by what makes or breaks a live, offline demo on 21–23 Oct, then by judging value. Items marked ★ are the user's three examples. Everything else was found in this analysis.

### P0: demo-critical
1. **Make the project self-contained and one-command runnable offline** (R1, B1, M5).
   - Copy the runtime assets into the project: selector headers and port, twin code and parameters, `sim_core.py`, lab data. Raw files stay byte-identical.
   - Configure paths via env vars, pin dependencies, use a venv on D:, add one start script for Windows, and optionally an offline wheel folder.
   - `git init` with a `.gitignore` that keeps ~75 MB of simulation CSVs out of git.
2. ★ **Real ingestion port and storage** (M1, M2, M8). Add a local server with:
   - HTTP JSON ingest plus a WebSocket live stream;
   - SQLite storage;
   - a documented API.
   A small **gateway** process bridges the *existing* USB-serial firmware to it, so no firmware change is needed for the demo. It stamps time and device id.
3. ★ **Edge AI at the edge** (M3, S2).
   - **Now:** export the selector to ONNX and run it with ONNX Runtime inside the gateway, parity-tested against `port_c.py` and the C header (38/38 lab curves). Label every decision with where it ran.
   - **Next, on hardware:** a firmware foundation that stores sweep points, calls `pemilih.h` on the ESP32, prints `# pemilih=…` (the dashboard already parses this) and inference time. Re-copy the current weights into `uji_pemilih` first (D2).
4. ★ **Demo mode.** Extend TIRUAN into scenario playback: real lab curves over a timeline (for example clear → shade on A → shade on A+D → clear). Feed it through the *same* ingestion path, mark it `DEMO` in the database and the UI, and fall back to it automatically when no device is found.
5. ★ **CSV upload page** (M4). Accept the logger/lab format and a plain `V,I[,P]` CSV with validation, size limits and clear errors. Store in the database, then run the selector and twin on it.
6. **Remove demo-breaking risks** (B2, B3, B4).
   - Make the server or gateway the single owner of the COM port, so refreshes and extra tabs are harmless.
   - Pin Streamlit.
   - Disable telemetry and hide Deploy.

### P1: strengthens judging (technical report: power, latency, accuracy)
7. **Measure and show latency** (M6): selector inference time (gateway, later ESP32), sweep duration, and relay switch time from timestamps. Store them in the database for the report.
8. **Decision logic at the edge** (M7): the 20 % trigger and minimum hold time move from the dashboard into the gateway or edge logic, plus the **stability rule** (lock TCT under fluctuating power). Evaluate the rule in simulation (`dinamis.py`) and label it sim.
9. **Energy recovered vs a fixed topology** (RENCANA E1, "power without switching"), shown live with clear labels.
10. **Health and status** (M9): device online, last seen, gateway and database status; a `/health` endpoint.
11. **Docs cleanup** (D1–D9) and the `START_HERE.md`, `README.md`, `CHANGELOG.md` the user asked for.
12. **Tests in one command** (M12): unit (parser, Pmax, selector parity, database), integration (ingest → database → API), and an end-to-end demo-mode smoke test.

### P2: foundation only (clearly labeled, completed later)
13. **Fault localization for PLN** (M10): an interface and a simulation-labeled baseline that says which module or string is likely affected, using four-topology sweeps or expected-vs-measured deviation. No accuracy claims on real data.
14. **L3 panel** (M11): relay vs MOSFET holding power and net gain, labeled "calculation, not measured".
15. **MQTT option**: Mosquitto (free, local) as an alternative transport, plus a **WiFi firmware variant** that POSTs sweeps directly. Both stay foundations until the board is available.
16. **Session export** (M13): CSV/JSON plus a short report for the technical report.
17. Diagnosis panel: keep it out of the main demo. At most an "experimental, simulation-only" tab.

---

## 11. Assumptions and open questions

**Assumptions** (say if any is wrong):
1. `docs/before/` should mirror the original project root, so I stripped the zip's top-level folder.
2. "After" means the current root (`dasbor/` + `progress.md`). The previous session worked inside the full tree (the screenshots prove the UI ran), so the missing `SHADESHIFT_ML/` is a packaging omission, not an intentional removal.
3. New documents are written in **English**, because you wrote to me in English. Code identifiers stay Indonesian, as in the existing code.
4. The demo laptop runs Windows with Python 3.12 (COM ports and PowerShell in the docs). Internet is available once for setup, never during the demo.
5. I have no ESP32 or relay hardware. Anything that needs the board is built and tested against the emulator and marked "not verified on hardware".
6. The team rules in §9 stay in force.

**Open questions:**
1. May I install the dashboard's own dependencies (`streamlit`, `pvlib`, `pyserial`), and later `fastapi`/`uvicorn`, `onnx`/`onnxruntime` and `pytest`, into a virtual environment under `D:\ShadeShift\.venv`? That is roughly 300–400 MB in total. I will ask again before the heavy ones in Phase 3.
2. During the demo, should the ESP32 stay on **USB serial** with the laptop gateway (works with today's firmware, recommended)? Or do you want a **WiFi** variant too (needs flashing and testing on your board)?
3. Can you run a firmware update on the real board before 21 Oct, so that `uji_pemilih` and an updated `sapuan()` can be verified?

---

## 12. Verification status

**Independent workflow (18 Oct, 23:56–00:31).** 3 of 6 area readers finished before the account's usage limit stopped the run:
- overview + official rules (all 12 PDF pages and the participant guide);
- firmware/hardware (37 files);
- ML/simulation (42 files).

Their findings are merged above (B9–B12, F1–F7, §7.2, summary point 9). They **confirmed** R1, B1, M1–M4, D1, D2, D3 and the cloud items in §6 independently. The edge-AI reader, the L3/guides reader, the after-code bug hunt, the diff lenses and the adversarial verification batches did not run.

**Checked directly by me** (run or diff):
- R1/B1 in-place failure; missing packages;
- self-test in a full-tree copy, also on numpy 2.5 / pandas 3.0;
- D2 weights diff and its effect (12/12 board test with both copies; identical decisions on all 38 lab 4S curves);
- R2/B3 minimum Streamlit version from Streamlit's source at release tags;
- twin timing (≈0.15 s per simulation) and paranet transmission 0.137.

**Snapshot integrity.**
- My first weights check imported `port_c.py` from `docs/before/`, and Python wrote a `__pycache__/port_c.cpython-312.pyc` into the snapshot. The workflow reader caught this.
- I removed that one file. `docs/before/` now matches the zip exactly: 264 entries, 0 mismatches, 0 extra files.
- Later reads of the snapshot use `python -B`.

**Not yet independently verified:** B2 (port lock after refresh; needs a device or virtual COM port), B5, B6 and D4–D9 (read-only findings). The Phase 2 review includes an ANALYSIS verification lens.

**Phase 2 review corrections (18 Oct):**
- **B5:** there is no `AttributeError`. After a short 4S sweep the flow sends nothing, waits 10 s, reports "gagal pindah ke None" (failed to switch to None), and auto mode ends silently.
- **B6:** the emulator's real hazards were worse than described. An OFF during a switch was undone when the switch finished, and an OFF during a sweep crashed the sweep thread.
- **B2:** correct for a refresh or a closed tab. A second tab cannot connect while the first holds the port.

All three were fixed in Stages 2–3: the gateway owns the port, the emulator runs one command at a time, and short sweeps give a clear error.

**Resolution status:** see [CHANGELOG.md](../CHANGELOG.md) and the status table in [START_HERE.md](../START_HERE.md) §3.
