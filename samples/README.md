# Sample upload files

Use them on the dashboard's **Unggah CSV** page or with `POST /api/v1/uploads` (CONTRACT.md §5.5). Regenerate with
`python tools/make_samples.py`. All curves are real halogen-lamp lab measurements from `SHADESHIFT_ML/data/data_lab/`
(that folder is only read, never written).

| File | Format | Expected result |
|---|---|---|
| `V3_opak_4S_u1.csv` | Firmware/logger format, exact copy of the lab file | Accepted; topology 4S from the header; condition `V3_opak`, repeat 1; selector decision |
| `V1c_TCT_u1_plain.csv` | Plain CSV `V,I` (amperes), converted from `V1c_TCT_u1.csv` | Accepted; topology TCT from the file name |
| `V1c_TCT_u1_plain_mA.csv` | Plain CSV `V,I_mA` (milliamperes), same curve | Accepted; current divided by 1000; same Pmax as the file above |
| `bad_too_few_points.csv` | Plain CSV with 5 rows | Rejected: fewer than 10 valid points |
| `bad_non_numeric.csv` | Plain CSV with text in a value | Rejected: values must be numbers |
