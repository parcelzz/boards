# Audit_unidata

Data quality audits and GPKG backfill for **`public.unidata`** (PostgreSQL) vs the **Santa Clara County** parcel baseline.

**Latest snapshot:** **494,142** rows · **23** columns · DB label **v2.3** (release notes in [`docs/release-unidata-v2.3-data-sheet.md`](docs/release-unidata-v2.3-data-sheet.md)).

---

## Current status (May 2026)

| Area | Status |
|------|--------|
| **Final audit report** | [`outputs/parcel_audits/final_unidata_audit_report.html`](outputs/parcel_audits/final_unidata_audit_report.html) — regenerate: `py -3 tools/reporting/final_unidata_audit_report.py` |
| **Steps 1–3** (missingness, completeness, semantics) | Scripts ready → `outputs/missingness_step1/` … `step3/` |
| **Unidata vs GPKG** | `tools/audits/audit_unidata_vs_gpkg.py` → `outputs/parcel_audits/unidata_v22_vs_gpkg_audit.*` |
| **GPKG backfill (attributes)** | `enrich_unidata_from_gpkg.py` — parcel GPKG → address, zoning, sqft, etc. |
| **GPKG backfill (footprints)** | `enrich_unidata_footprints.py` — `California.gpkg` spatial match on parcel polygon |
| **fldzone verification** | [`docs/ticket-04-unidata-fldzone-20260522.md`](docs/ticket-04-unidata-fldzone-20260522.md) |
| **Steps 4–5** | Templates in `docs/` (workshop / external sources) |

### Snapshot highlights (live DB)

| Metric | Value |
|--------|------:|
| Unidata rows | **494,142** |
| GPKG rows with `parcelnumb` | **494,185** (43 extra = duplicate GPKG features, not missing parcels) |
| Footprints present | **~96.4%** (~17.8k still empty) |
| Largest gaps | `yearbuilt`, `scity`, `address`, `footprints` (where no GPKG/building overlap) |

**Backfill applied (vs `unidata_backup_20260522`):** ~40k parcel-field updates; **18,361** footprints added from `California.gpkg` (spatial only — not parcel number).

---

## Data inputs (`data/`)

| File | Role |
|------|------|
| `ca_santa_clara_parcel_build_opt.gpkg` | Parcel baseline + attribute backfill (`parcelnumb` + `scity`) |
| `California.gpkg` | Building footprints (parcel polygon ∩ building polygon) |
| `building-polygon.gpkg` | Not used (no parcel keys on layer) |
| `unidata_v2.3.csv` | Optional full export (~457 MiB) |

---

## Quickstart

**Prerequisites:** Python 3.x, `psycopg`, `pyogrio`, `shapely`; Postgres at `127.0.0.1:5432` (Cloud SQL proxy) with `public.unidata`. Credentials in `DEFAULT_DB_CONFIG` inside audit scripts.

```bash
# Final top-to-bottom report (HTML + field CSV)
py -3 tools/reporting/final_unidata_audit_report.py

# Step 1–3 detail reports
py -3 tools/audits/field_missingness_classification.py
py -3 tools/audits/field_completeness_report_step2.py
py -3 tools/audits/field_semantics_audit_step3.py

# Unidata vs GPKG by scity
py -3 tools/audits/audit_unidata_vs_gpkg.py

# Backfill missing values (preview = dry run; --apply commits)
py -3 tools/audits/enrich_unidata_from_gpkg.py --apply
py -3 tools/audits/enrich_unidata_footprints.py --apply
# Or both: py -3 tools/audits/enrich_unidata_from_gpkg.py --apply --with-footprints
```

`outputs/` is gitignored — run scripts locally to generate reports.

---

## Matching rules

- **City grouping:** normalized **`scity` only** (uppercase, hyphens → spaces; blank → `(NULL)`).
- **Parcel GPKG join:** `parcelnumb` + normalized `scity` (singleton / APN-only fallbacks in enrich script).
- **Footprint join:** **`parcel`** WKT polygon vs `California.gpkg` buildings (positive-area overlap).

---

## Main deliverables

| Deliverable | Path |
|-------------|------|
| **Final audit (start here)** | `outputs/parcel_audits/final_unidata_audit_report.html` |
| Step 1 missingness | `outputs/missingness_step1/report.html` |
| Step 2 completeness | `outputs/missingness_step2/report.html` |
| Step 3 semantics | `outputs/missingness_step3/report.html` |
| Unidata vs GPKG | `outputs/parcel_audits/unidata_v22_vs_gpkg_audit.html` |
| v2.3 release sheet | `docs/release-unidata-v2.3-data-sheet.md` |
| Documentation index | [`docs/index.md`](docs/index.md) |

---

## Troubleshooting

- **Windows:** use `py -3` if `python` is not on PATH.
- **DB connection fails:** ensure Cloud SQL proxy on port **5432**; update `DEFAULT_DB_CONFIG` in `tools/audits/field_missingness_classification.py`.
- **Missing packages:** `py -3 -m pip install psycopg pyogrio shapely`

---

## Follow-ups

- Move DB credentials to environment variables.
- Add `requirements.txt`.
- Optional: spatial join `building-polygon.gpkg` for remaining footprint gaps.
