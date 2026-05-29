# Step 4 — Product field review (generated)

> **Summary:** Auto-generated draft for Step 4 workshop from Step 1 + Step 3 CSVs. Edit priorities in the template or here after review; regenerate with `generate_step4_step5.py`.  
> **Updated:** 2026-05-08 · **Author:** Unidata audit team · **Status:** WIP

**Generated:** 2026-05-08T17:56:35Z

This file is generated from:
- `outputs/missingness_step1/field_missingness_all.csv`
- `outputs/missingness_step3/semantics_by_column.csv` (if present)

## Priority definitions

| Level | Definition |
|-------|------------|
| **P0** | Product cannot function without reliable values |
| **P1** | Major user experience or decision quality |
| **P2** | Explanation, trust, or enrichment |
| **P3** | Optional for this version |

## P0 / P1 candidates (start here)

| Field | Current suggested priority | Agreed priority | OK if unknown for MVP? (Y/N) | User-facing copy / behavior if unknown | Owner | Notes (from Steps 1–3) |
|-------|---------------------------|-----------------|------------------------------|----------------------------------------|-------|------------------------|
| `fhszsra` | P1–P2 |  |  |  |  | External join fields · missing 97.57% · behavior High · Review if this field is P0/P1 in Step 4. |

## Remaining fields (P2 / P3 / informational)

| Field | Current suggested priority | Agreed priority | OK if unknown for MVP? (Y/N) | User-facing copy / behavior if unknown | Owner | Notes (from Steps 1–3) |
|-------|---------------------------|-----------------|------------------------------|----------------------------------------|-------|------------------------|
| `scity` | P2 |  |  |  |  | Core parcel fields · missing 0.39% · behavior Moderate · Review if this field is P0/P1 in Step 4. |
| `address` | P2 |  |  |  |  | Core parcel fields · missing 0.34% · behavior Moderate · Review if this field is P0/P1 in Step 4. |
| `footprints` | P2–P3 |  |  |  |  | Footprint-related fields · missing 7.32% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `building_area` | P2–P3 — Review |  |  |  |  | Footprint-related fields · missing 6.85% · behavior Low · Low Step-1 missing % but non-trivial zeros — spot-check whether zeros are valid. |
| `sqft` | P2–P3 — Review |  |  |  |  | Footprint-related fields · missing 4.28% · behavior Low · Low Step-1 missing % but non-trivial zeros — spot-check whether zeros are valid. |
| `city` | P2 |  |  |  |  | Core parcel fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `created_at` | P2 |  |  |  |  | Core parcel fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `id` | P2 |  |  |  |  | Core parcel fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `lat` | P2 |  |  |  |  | Core parcel fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `lon` | P2 |  |  |  |  | Core parcel fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `parcel` | P2 |  |  |  |  | Core parcel fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `parcelnumb` | P2 |  |  |  |  | Core parcel fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `updated_at` | P2 |  |  |  |  | Core parcel fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `yearbuilt` | P3 |  |  |  |  | API-fillable fields · missing 4.36% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `fhszlra` | P3 |  |  |  |  | External join fields · missing 2.08% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `zoning` | P3 |  |  |  |  | API-fillable fields · missing 0.06% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `fldzone` | P3 |  |  |  |  | External join fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `alquist_fault` | P3 — FALSE-dominated |  |  |  |  | External join fields · missing 0.00% · behavior Low · Among non-NULL booleans, FALSE is 100.00% — verify domain meaning (unknown encoded as FALSE?). |
| `h3` | P3 |  |  |  |  | API-fillable fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |
| `landslide` | P3 — FALSE-dominated |  |  |  |  | External join fields · missing 0.00% · behavior Low · Among non-NULL booleans, FALSE is 100.00% — verify domain meaning (unknown encoded as FALSE?). |
| `liquefaction` | P3 — FALSE-dominated |  |  |  |  | External join fields · missing 0.00% · behavior Low · Among non-NULL booleans, FALSE is 100.00% — verify domain meaning (unknown encoded as FALSE?). |
| `ready` | P3 |  |  |  |  | API-fillable fields · missing 0.00% · behavior Low · Review if this field is P0/P1 in Step 4. |

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| | | |
