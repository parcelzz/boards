# Audit_unidata

Data quality audit utilities and generated artifacts for **Unidata (`public.unidata` in PostgreSQL)** against a **Santa Clara County GeoPackage baseline**.

The current **Unidata v2.3** snapshot (row counts, per-column missingness under Step 1 rules, processing notes, and timing) is documented in **`docs/unidata_v2.3_data_sheet.md`**, with a machine-readable companion **`docs/unidata_v2.3_field_missingness_step1.csv`**.

This repository is organized around:

- **Parcel inventory audits** (row coverage vs baseline)
- **Field missingness taxonomy (Step 1)**, **field completeness QA (Step 2)**, and **field semantics audit (Step 3)** for the “Next-stage work plan”
- **Task 2 residential baseline coverage audit** (baseline parcels vs Unidata presence + field completeness)

---

## Current status (as of repo state)

| Area | Status |
|------|--------|
| **Next-stage work plan** | **Steps 1–3** are implemented as scripts; **Steps 4–5** use templates under `docs/` (workshop / decisions still to finalize). |
| **Step 1** — field missingness taxonomy | **Done** — `tools/audits/field_missingness_classification.py` → `outputs/missingness_step1/`. |
| **Step 2** — field completeness QA | **Done** — `tools/audits/field_completeness_report_step2.py` → `outputs/missingness_step2/` (includes maps, GeoJSON, example CSVs). |
| **Step 3** — field semantics audit | **Done** — `tools/audits/field_semantics_audit_step3.py` → `outputs/missingness_step3/` (`report.html`, `semantics_by_column.csv`, `hazard_boolean_crosstab.csv`). See `docs/field_semantics_step3.md`. |
| **Step 4** — product field review | **Next** — use `docs/product_field_review_template.md` with Step 1–3 outputs. |
| **Step 5** — external source evaluation | **Template ready** — `docs/external_data_source_evaluation_template.md`. |
| **Unidata vs GPKG audit** | **Available** — `tools/audits/audit_unidata_vs_gpkg.py` → `outputs/parcel_audits/unidata_v22_vs_gpkg_audit.*` (artifact names still use the `v22` prefix; the compared table is the current DB, **v2.3**). |
| **Unidata v2.3 — data sheet** | **In repo** — `docs/unidata_v2.3_data_sheet.md` + `docs/unidata_v2.3_field_missingness_step1.csv` |
| **GPKG → Postgres backfill** | **Available** — `tools/audits/enrich_unidata_from_gpkg.py` (dry run by default; `--apply` updates `public.unidata` from parcel GPKG). |
| **Task 2 residential coverage** | **Available** — `tools/audits/task2_residential_audit.py` → stakeholder HTML, CSV, Markdown under `outputs/parcel_audits/`. |

**Important:** The entire `outputs/` directory is listed in `.gitignore`. A fresh clone contains **no** generated reports until you run the scripts above (or copy artifacts from a teammate). If `outputs/missingness_step3/` is missing, run `py -3 tools/audits/field_semantics_audit_step3.py` with Postgres + `public.unidata` available.

---

## What’s in this repo

### Inputs

- `data/ca_santa_clara_parcel_build_opt.gpkg`
  - GeoPackage baseline used for comparisons, **GPKG backfill** (`enrich_unidata_from_gpkg.py`), and “residential” filtering via `usecode`.
- `data/unidata_v2.3.csv` (optional, local)
  - Full-table export of `public.unidata` when generated (~457 MiB); not required for audits.

### Code

- `tools/audits/`
  - `enrich_unidata_from_gpkg.py`: backfill **missing** parcel fields in **`public.unidata`** from parcel GPKG (no `footprints`); dry run or `--apply`
  - `audit_unidata_vs_gpkg.py`: **Unidata vs GPKG** row-count and key field missingness by normalized `scity` (default output filenames use the legacy `unidata_v22_*` prefix)
  - `field_missingness_classification.py`: **Step 1** missingness taxonomy + HTML report + CSV exports
  - `field_completeness_report_step2.py`: **Step 2** completeness QA (spatial grid, city association, proxies, samples) + HTML/CSV/GeoJSON outputs
  - `field_semantics_audit_step3.py`: **Step 3** semantics audit (NULL vs 0 vs FALSE, hazard crosstab) + HTML/CSV outputs
  - `task2_residential_audit.py`: **Task 2** Santa Clara residential baseline coverage audit + stakeholder-ready HTML + CSV + Markdown
- `tools/reporting/`
  - Helper scripts to render/combine/export reports (for example `combine_html_reports.py`)

### Generated outputs (local only — not tracked in Git)

After you run the audit scripts, expect directories such as:

- `outputs/missingness_step1/` — Step 1 report + CSV bucket exports
- `outputs/missingness_step2/` — Step 2 report + summary CSV, GeoJSON, example rows
- `outputs/missingness_step3/` — Step 3 semantics report + `semantics_by_column.csv`, hazard crosstab
- `outputs/parcel_audits/` — Unidata vs GPKG audit, Task 2 reports, combined HTML, supporting notes

### Tracked documentation (in Git)

- `docs/unidata_v2.3_data_sheet.md` — v2.3 totals, **all-column** Step 1 missingness table, process, git hash note, known issues, timings
- `docs/unidata_v2.3_field_missingness_step1.csv` — same missingness as machine-readable export

---

## Key results so far (from current artifacts)

These are taken from `outputs/parcel_audits/task2_findings_null_parcel_and_duplicates.md` and the current audit exports.

### Baseline definition drives most of the apparent row gap

- **GPKG total rows**: 501,656  
- **GPKG rows with non-null `parcelnumb`**: 494,185  
- **GPKG rows with NULL `parcelnumb`**: 7,471  
- **Unidata total rows (v2.3 snapshot)**: 494,142 — see `docs/unidata_v2.3_data_sheet.md` for per-column missingness  

Impact on the Unidata vs GPKG “row delta”:

- **Including NULL `parcelnumb` rows in GPKG baseline**: row delta \(494,142 − 501,656\) = **-7,514**
- **Excluding NULL `parcelnumb` rows (default)**: row delta \(494,142 − 494,185\) = **-43**

Interpretation: the “~7.5k missing parcels” headline is primarily a **baseline-definition issue** (NULL parcel numbers in source), not necessarily missing inventory in Unidata.

---

## Quickstart (reproduce the reports)

### Prerequisites

- **Python**: scripts are plain Python; use a recent Python 3.x. On Windows, if `python` is not on PATH, use **`py -3`** (see **Troubleshooting**).
- **PostgreSQL reachable locally** with a populated Unidata table:
  - Schema/table default: `public.unidata`
  - The scripts connect via `psycopg` to a local DB (`127.0.0.1:5432`) by default.
- **Python packages**:
  - `psycopg` (Postgres driver)

Note: connection parameters are currently set in code via `DEFAULT_DB_CONFIG` in the audit scripts. If your DB credentials differ, update those constants (recommended follow-up: migrate to environment variables).

### Run Step 1 (field missingness taxonomy)

```bash
py -3 tools/audits/field_missingness_classification.py
```

Outputs:

- `outputs/missingness_step1/report.html` (main deliverable)
- `outputs/missingness_step1/field_missingness_all.csv`
- `outputs/missingness_step1/<bucket>/fields.csv`

### Run Step 2 (field completeness QA)

```bash
py -3 tools/audits/field_completeness_report_step2.py
```

Outputs:

- `outputs/missingness_step2/report.html` (main deliverable)
- `outputs/missingness_step2/field_completeness_summary.csv`
- `outputs/missingness_step2/completeness_by_city_long.csv`
- `outputs/missingness_step2/spatial_cells/*.geojson`
- `outputs/missingness_step2/example_records/*_missing_sample.csv`

Notes:

- Step 2 uses the **same “present vs missing” rules** defined in Step 1.
- Spatial maps are Leaflet-based and request OpenStreetMap tiles; you’ll want network access when viewing `outputs/missingness_step2/report.html`.

### Run Step 3 (field semantics audit)

```bash
py -3 tools/audits/field_semantics_audit_step3.py
```

Outputs:

- `outputs/missingness_step3/report.html` (main deliverable)
- `outputs/missingness_step3/semantics_by_column.csv`
- `outputs/missingness_step3/hazard_boolean_crosstab.csv`

See `docs/field_semantics_step3.md` for interpretation and Step 4 handoff.

### Run Unidata vs GPKG audit (by `scity`)

Compared table: current **`public.unidata`** (product snapshot **v2.3**). Default output filenames remain `unidata_v22_*`.

```bash
py -3 tools/audits/audit_unidata_vs_gpkg.py
```

Outputs:

- `outputs/parcel_audits/unidata_v22_vs_gpkg_audit.csv`
- `outputs/parcel_audits/unidata_v22_vs_gpkg_audit.html`

By default the GPKG baseline **excludes NULL/blank `parcelnumb`**. To include those rows (for comparison):

```bash
py -3 tools/audits/audit_unidata_vs_gpkg.py --include-null-parcelnumb
```

### Run GPKG → Unidata backfill (optional)

Preview only (transaction rolled back; writes report bundle under `outputs/missingness_gpkg_fill/` unless `--no-report`):

```bash
py -3 tools/audits/enrich_unidata_from_gpkg.py --gpkg-path data/ca_santa_clara_parcel_build_opt.gpkg
```

Apply updates to **`public.unidata`**:

```bash
py -3 tools/audits/enrich_unidata_from_gpkg.py --gpkg-path data/ca_santa_clara_parcel_build_opt.gpkg --apply
```

### Run Task 2 (Santa Clara residential baseline coverage)

```bash
py -3 tools/audits/task2_residential_audit.py
```

Outputs:

- `outputs/parcel_audits/task2_santa_clara_residential_audit.html` (stakeholder-ready)
- `outputs/parcel_audits/task2_santa_clara_residential_audit_updated.md`
- `outputs/parcel_audits/task2_residential_coverage_by_city.csv`

### Optional: combine two HTML audits into one file

```bash
py -3 tools/reporting/combine_html_reports.py
```

Output:

- `outputs/parcel_audits/combined_audit_report.html`

---

## How matching and grouping works (important)

### City key normalization

All three major audits intentionally group using **`scity` only** (no fallback to `city`), with normalization:

- blank/NULL `scity` → `(NULL)`
- hyphens become spaces (`SAN-JOSE` → `SAN JOSE`)
- whitespace collapsed; case normalized to uppercase

This is required so “city buckets” are comparable across sources, but it also means:

- `scity` label drift between sources can look like coverage loss even when APNs exist.

### Parcel match rule (Task 2 residential coverage)

For Task 2, a baseline row is “matched” when:

- baseline `parcelnumb` (trimmed, uppercased) exists in Unidata **for the same normalized `scity` bucket**

---

## Where to find the final deliverables

Primary HTML/CSV paths (populate your `outputs/` folder by running the commands in **Quickstart**):

- **Step 1 missingness taxonomy report**: `outputs/missingness_step1/report.html`
- **Step 2 completeness QA report**: `outputs/missingness_step2/report.html`
- **Step 3 semantics audit report**: `outputs/missingness_step3/report.html`
- **Task 2 stakeholder report (residential coverage)**: `outputs/parcel_audits/task2_santa_clara_residential_audit.html`
- **Unidata vs GPKG audit report**: `outputs/parcel_audits/unidata_v22_vs_gpkg_audit.html` (legacy filename; data = v2.3)
- **Unidata v2.3 data sheet (all columns + missingness)**: `docs/unidata_v2.3_data_sheet.md`
- **Combined HTML** (Task 2 + Unidata vs GPKG): `outputs/parcel_audits/combined_audit_report.html`

Supporting notes:

- `outputs/parcel_audits/task2_findings_null_parcel_and_duplicates.md`
- `outputs/parcel_audits/stakeholder_update_draft.txt`

---

## Documentation templates (for workshops / review)

- `docs/product_field_review_template.md` (Step 4)
- `docs/external_data_source_evaluation_template.md` (Step 5)
- `docs/field_completeness_step2.md` (how to run Step 2; output glossary)
- `docs/field_semantics_step3.md` (how to run Step 3; Step 4 handoff)
- `docs/ticket_03_step3_field_semantics.md` (Ticket #3 writeup — same style as Task #2 findings: scope, metrics, artifacts, DoD)
- `docs/unidata_v2.3_data_sheet.md` (v2.3 totals, full-column missingness, process, known issues, timings)

---

## Troubleshooting

### `python` not found (Windows)

Use the Python launcher:

```bash
py -3 tools/audits/field_missingness_classification.py
```

### “psycopg” import error

Install the dependency in your active environment:

```bash
py -3 -m pip install psycopg
```

### Database connection fails

Ensure:

- PostgreSQL is reachable at `127.0.0.1:5432`
- The target table exists: `public.unidata` (or pass `--db-schema/--db-table` where supported)
- Credentials in `DEFAULT_DB_CONFIG` match your local setup

### `outputs/` or `missingness_step3` missing in the file explorer

- Reports are **generated by scripts**, not stored in Git (see `.gitignore`).
- Run the matching command from **Quickstart** (for Step 3: `py -3 tools/audits/field_semantics_audit_step3.py`).
- If the folder exists on disk but the IDE hides it, turn off hiding of excluded / gitignored files in the explorer settings.

---

## Suggested follow-ups (not implemented yet)

- Move DB credentials out of code into **environment variables** or a local config file.
- Add `requirements.txt` (or `pyproject.toml`) so anyone can reproduce the environment quickly.
- Add a small “sample” dataset option so the repo can run without the full GPKG / full database.

