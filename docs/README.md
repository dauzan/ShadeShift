# Which document do I need?

You only need **two files** to use ShadeShift:
1. **[../README.md](../README.md)**: what it is and the commands.
2. **[../START_HERE.md](../START_HERE.md)**: setup, the Demo Day runbook, and what is finished.

Everything else is reference, listed here by when you need it. "EN" = English, "ID" = Indonesian.

## Running and presenting

| File | Read it when | Lang |
|---|---|---|
| [../README.md](../README.md) | You want an overview and the list of commands | EN |
| [../START_HERE.md](../START_HERE.md) | You set up a laptop, prepare Demo Day, or check what is done and which claims are safe | EN |
| [PROMISES.md](PROMISES.md) | You prepare the presentation: each proposal promise, the technology that delivers it, its status and today's evidence | EN |
| [../CHANGELOG.md](../CHANGELOG.md) | You want to know what changed, stage by stage | EN |
| [../dasbor/README.md](../dasbor/README.md) | You want details of the ten dashboard pages | ID |
| [../samples/README.md](../samples/README.md) | You test the CSV upload page | EN |

## Hardware and firmware

| File | Read it when | Lang |
|---|---|---|
| [../firmware/CARA_PAKAI.md](../firmware/CARA_PAKAI.md) | You flash the firmware (the only one, 3.2), wire the LDR, run the bench test and the first check, use the web page, DIAG or the manual logger | ID |
| [../rangkaian/daftar_kabel.md](../rangkaian/daftar_kabel.md) | You check the wiring: relays, GPIO, measurement path | ID |
| [../rangkaian/daftar_belanja.md](../rangkaian/daftar_belanja.md) | You need the original parts list (no new purchases planned) | ID |

## Engineering records (how and why the system was built)

| File | Read it when | Lang |
|---|---|---|
| [CONTRACT.md](CONTRACT.md) | You change code: data flow, serial protocol, AI model, API and JSON shapes, database, ports, settings | EN |
| [PLAN.md](PLAN.md) | You want the build stages, decisions and what was not built | EN |
| [ANALYSIS.md](ANALYSIS.md) | You want the review of the original project (historical, 17 Oct) | EN |

## Team notes

| File | Read it when | Lang |
|---|---|---|
| [team/progress.md](team/progress.md) | Team status, decisions and dated log (add new entries at the top of "Log") | ID |
| [team/UNTUK_DAUZAN.md](team/UNTUK_DAUZAN.md) | The original handover: product, hardware, tasks, numbers you may quote | ID |

## Research (the AI model and the experiments behind it)

| File | Content | Lang |
|---|---|---|
| [../SHADESHIFT_ML/edge_ai/pemilih/README.md](../SHADESHIFT_ML/edge_ai/pemilih/README.md) | The selector model and its C code for the ESP32 | ID |
| [../SHADESHIFT_ML/uji_model/LAPORAN_UJI_FISIK.md](../SHADESHIFT_ML/uji_model/LAPORAN_UJI_FISIK.md) | Tests on lab data: source of the 0.82 % vs 2.71 % claim | ID |
| [../SHADESHIFT_ML/edge_ai/LAPORAN_JALUR_B.md](../SHADESHIFT_ML/edge_ai/LAPORAN_JALUR_B.md) | Digital twin (~8 % error) and the diagnosis/CNN attempts | ID |
| [../SHADESHIFT_ML/RINGKASAN_LANGKAH1.md](../SHADESHIFT_ML/RINGKASAN_LANGKAH1.md) | First simulation results (some numbers superseded) | ID |
| [../SHADESHIFT_ML/CATATAN_BUG_VOC.md](../SHADESHIFT_ML/CATATAN_BUG_VOC.md) | The Voc simulation bug and why diagnosis is 78–82 % (sim) | ID |
| [../SHADESHIFT_ML/data/data_lab/README.md](../SHADESHIFT_ML/data/data_lab/README.md) | The lab dataset: conditions, file names, sets not to use | ID |
| [../SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md](../SHADESHIFT_ML/PROTOKOL_LUAR_RUANGAN.md) | Plan for outdoor (sun) measurements | ID |
| [../SHADESHIFT_ML/saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md](../SHADESHIFT_ML/saklar/DESAIN_MATRIKS_SEMIKONDUKTOR.md) | L3: semiconductor switch design (calculation, not built) | ID |
| [../SHADESHIFT_ML/RENCANA.md](../SHADESHIFT_ML/RENCANA.md) | An older plan from before Smart-X | ID |

## The original project

[before/](before/) is an untouched copy of `SHADESHIFT_untuk_Dauzan.zip`, kept for reference; it is never edited. It
is also the only place holding the official **Bootcamp PDF** (hackathon rules). Its documents are the old versions:
read the files above instead.
