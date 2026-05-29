# Release — Unidata v2.3 data sheet

> **Summary:** Release record for the v2.3 `public.unidata` snapshot: row/column totals, full-column Step 1 missingness, GPKG backfill process, known issues, and timings. Companion CSV: `release-unidata-v2.3-field-missingness.csv`.  
> **Updated:** 2026-05-16 · **Author:** Unidata audit team · **Status:** Completed

---

## Purpose

“v2.3” is the **Unidata snapshot in PostgreSQL** after the Santa Clara parcel GPKG backfill. The database does **not** store a `version = 2.3` column; this document is the authoritative release note.

---

## Totals (`public.unidata`)

| Metric | Value |
|--------|------:|
| **Rows** | **494,142** |
| **Columns** | **23** |

**Machine-readable missingness (same rows as below):** [release-unidata-v2.3-field-missingness.csv](release-unidata-v2.3-field-missingness.csv)  
(Step 1 export: taxonomy, strategies, and counts per column.)

**Exported full-table CSV (optional snapshot):**

| Item | Value |
|------|--------|
| Path | `data/unidata_v2.3.csv` |
| Approx. size on disk | ~457 MiB (~479,071,781 bytes) |
| Row content | Full table dump (header + 494,142 data rows) |

---

## Column missingness (Step 1 rules)

Counts were produced with **`compute_field_rows`** from `tools/audits/field_missingness_classification.py` (same logic as Step 1: one full-table scan per run).

**“Present” means:**

- **Text / varchar:** not NULL and `TRIM` non-empty.
- **Boolean / timestamps / json / uuid / generic numerics:** not NULL (for integers **not** in the zero-empty list, **0 counts as present**).
- **Arrays:** not NULL and `cardinality > 0`.
- **These integers treat `0` as missing (same as NULL):** `sqft`, `building_area`, `yearbuilt`, `fhszsra`, `fhszlra`.

Sorted by **missing %** (highest first), then column name.

| column | data_type | present | missing | missing % |
|--------|-----------|--------:|--------:|------------:|
| fhszsra | integer | 12,001 | 482,141 | 97.5713 |
| footprints | ARRAY | 457,990 | 36,152 | 7.3161 |
| yearbuilt | integer | 472,581 | 21,561 | 4.3633 |
| fhszlra | integer | 483,843 | 10,299 | 2.0842 |
| scity | character varying | 492,213 | 1,929 | 0.3904 |
| address | character varying | 492,473 | 1,669 | 0.3378 |
| zoning | character varying | 493,832 | 310 | 0.0627 |
| fldzone | character varying | 494,137 | 5 | 0.0010 |
| alquist_fault | boolean | 494,142 | 0 | 0.0000 |
| building_area | integer | 494,142 | 0 | 0.0000 |
| city | character varying | 494,142 | 0 | 0.0000 |
| created_at | timestamp without time zone | 494,142 | 0 | 0.0000 |
| h3 | character varying | 494,142 | 0 | 0.0000 |
| id | integer | 494,142 | 0 | 0.0000 |
| landslide | boolean | 494,142 | 0 | 0.0000 |
| lat | double precision | 494,142 | 0 | 0.0000 |
| liquefaction | boolean | 494,142 | 0 | 0.0000 |
| lon | double precision | 494,142 | 0 | 0.0000 |
| parcel | character varying | 494,142 | 0 | 0.0000 |
| parcelnumb | character varying | 494,142 | 0 | 0.0000 |
| ready | boolean | 494,142 | 0 | 0.0000 |
| sqft | integer | 494,142 | 0 | 0.0000 |
| updated_at | timestamp without time zone | 494,142 | 0 | 0.0000 |

To refresh after a DB change: run Step 1 (`field_missingness_classification.py`), update `release-unidata-v2.3-field-missingness.csv`, then update the table in this sheet.

---

## How it was processed

1. **Source of donor values:** Santa Clara county parcel GeoPackage (repo baseline: `data/ca_santa_clara_parcel_build_opt.gpkg`), layers that expose **`parcelnumb`** and **`scity`**.
2. **Staging:** Parcel rows were normalized (APN, normalized situs city), merged if multiple GPKGs were used, then loaded into PostgreSQL **temporary** tables in the same session as the updates.
3. **Backfill rules:** Fill **only gaps** — empty text fields; numeric **`sqft` / `building_area` / `yearbuilt`** only when NULL or **0**; **`lat` / `lon`** when missing. **Do not** overwrite non-empty text or positive area values. **`footprints`** are **not** modified.
4. **Join passes (order matters):**  
   - **Pair:** APN + normalized Unidata `scity` ↔ GPKG `(apn, scity_norm)`.  
   - **Singleton:** APN appears under a single `scity_norm` in GPKG when the pair join misses.  
   - **APN-only:** Last resort when situs city still disagrees; one donor row per APN.
5. **Apply:** Three `UPDATE` passes, then **commit**. Rows touched get **`updated_at = NOW()`** (per tooling design).
6. **Implementation reference:** `tools/audits/enrich_unidata_from_gpkg.py` (dry run default; `--apply` commits).

---

## Git hash (reproducibility)

| Field | Value |
|-------|--------|
| **Repository** | `Audit_unidata` |
| **Branch** | `marwin` |
| **Commit** | **None — repository had no commits at the time this sheet was written** (`fatal: ambiguous argument 'HEAD'`). |

**Action for a proper hash next time:** create an initial commit (or tag) **before** running production backfills, then record:

`git rev-parse HEAD`  
and optionally `git status --porcelain` to confirm a clean tree.

---

## Known issues & limitations

- **Version naming:** “v2.3” is a **process / release label**, not enforced in Postgres. Some audit **artifact filenames** still use the legacy `unidata_v22_*` pattern; README calls out current data as v2.3 where it matters.
- **Hazard integers (`fhszsra`, `fhszlra`):** Step 1 treats **0 as missing**; very high missing % reflects product/source semantics, not necessarily “bad import.”
- **`footprints`:** Large remaining missing rate is **expected** for footprint enrichment; GPKG backfill does not fill this column.
- **`yearbuilt`:** Remaining gaps are outside what the parcel GPKG pass is designed to clear entirely.
- **APN-only pass:** Can fill fields when **situs `scity`** in Unidata does not match the GPKG; QA should spot-check mixed-city edge cases.
- **Multi-row APNs in GPKG:** Ambiguous parcels rely on pass order and deduplication rules; rare mismatches are possible.
- **Secrets in repo:** DB connection defaults live in `tools/audits/field_missingness_classification.py`; production should move to environment variables (README already flags this).
- **Runtime environment:** On Windows, `python` may be missing from PATH; **`py -3`** is often required.
- **Large CSV export:** Full dumps are hundreds of MiB because of wide rows (e.g. **`footprints`** arrays); sharing or VCS is awkward without compression or column subsetting.

---

## Processed time (what was measured)

| Step | When | Duration (approx.) | Notes |
|------|------|--------------------|--------|
| Full-table CSV export to `data/unidata_v2.3.csv` | 2026-05-15 | `psql` `\copy`; server reported `COPY 494142`. |
| Step 1 missingness query (23 columns, one scan) | 2026-05-15 | `compute_field_rows` for this sheet / CSV. |

---

## Sign-off block (fill manually)

| Role | Name | Date |
|------|------|------|
| Executed by | | |
| Environment (prod/stage) | | |
| GPKG file checksum / date | | |
| DBA / approver | | |

---

## Related documents

- [Documentation index](index.md)
- [CONVENTIONS.md](CONVENTIONS.md)
- [Step 3 — Field semantics](step-03-field-semantics.md)
