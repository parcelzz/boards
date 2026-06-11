# Documentation index

> **Summary:** Catalog of all tracked docs under `docs/`: purpose, status, and last update. Start here; naming rules live in [CONVENTIONS.md](CONVENTIONS.md).  
> **Updated:** 2026-05-27 · **Author:** Unidata audit team · **Status:** Ready for review

---

## Conventions

| Document | Status | Updated |
|----------|--------|---------|
| [CONVENTIONS.md](CONVENTIONS.md) | Ready for review | 2026-05-16 |

---

## Releases

| Document | Summary | Status | Updated |
|----------|---------|--------|---------|
| [release-unidata-v2.3-data-sheet.md](release-unidata-v2.3-data-sheet.md) | v2.3 row/column totals, full-column missingness, GPKG backfill process, known issues, timings | Completed | 2026-05-16 |
| [release-unidata-v2.3-field-missingness.csv](release-unidata-v2.3-field-missingness.csv) | Machine-readable Step 1 missingness for v2.3 (23 columns) | Completed | 2026-05-15 |

---

## Work plan — step guides

| Step | Document | Summary | Status | Updated |
|------|----------|---------|--------|---------|
| 2 | [step-02-field-completeness.md](step-02-field-completeness.md) | How to run Step 2 completeness QA and read `outputs/missingness_step2/` | Completed | 2026-05-16 |
| 3 | [step-03-field-semantics.md](step-03-field-semantics.md) | How to run Step 3 semantics audit and hand off to Step 4 | Completed | 2026-05-16 |

*Step 1 has no separate guide; use `tools/audits/field_missingness_classification.py` and `outputs/missingness_step1/`.*

---

## Work plan — templates & generated outputs

| Step | Template | Generated (from scripts) | Status |
|------|----------|------------------------|--------|
| 4 | [step-04-product-field-review-template.md](step-04-product-field-review-template.md) | [step-04-product-field-review.md](step-04-product-field-review.md) | Template: Ready for review · Generated: WIP |
| 5 | [step-05-external-source-evaluation-template.md](step-05-external-source-evaluation-template.md) | [step-05-external-source-evaluation.md](step-05-external-source-evaluation.md) | Template: Ready for review · Generated: WIP |

Generate Step 4–5 Markdown from audit outputs:

`py -3 tools/workflows/generate_step4_step5.py`

---

## KR 2.4 — ParcelIQ

| Document | Summary | Status | Updated |
|----------|---------|--------|---------|
| [kr24-data-sources-and-gaps.md](kr24-data-sources-and-gaps.md) | **Start here:** sources, coverage gaps, blockers, ingest order (before schema/pull) | Live | 2026-05-29 |
| [parceliq-catalog-coverage.csv](parceliq-catalog-coverage.csv) | Full catalog (~94 items): coverage type, target table/column, column + join coverage | Live | 2026-05-29 |
| [kr24-parceliq-source-matrix.md](kr24-parceliq-source-matrix.md) | Tier 1 subset: target tables, sources, join keys, ETL status | Draft | 2026-05-29 |
| [kr24-parceliq-source-matrix.csv](kr24-parceliq-source-matrix.csv) | Machine-readable Tier 1 matrix (coverage refreshed from report) | Draft | 2026-05-29 |
| [kr24-schema-proposal.md](kr24-schema-proposal.md) | Extension table DDL direction for ENGs + Calvin API read path | Draft | 2026-05-29 |
| [runbooks/parceliq-etl-runbooks.md](runbooks/parceliq-etl-runbooks.md) | Per-pipeline source → script → QC | Draft | 2026-05-29 |

**Coverage report (HTML):** `outputs/parceliq_coverage/report.html` — `py -3 tools/reporting/parceliq_coverage_report.py`

---

## Tickets

| Document | Summary | Status | Updated |
|----------|---------|--------|---------|
| [ticket-03-step-3-field-semantics.md](ticket-03-step-3-field-semantics.md) | Ticket #3: Step 3 field semantics scope, DoD, artifacts | Completed | 2026-05-16 |
| [ticket-04-unidata-fldzone-20260522.md](ticket-04-unidata-fldzone-20260522.md) | Ticket #4: `fldzone` post-cutover verification vs `unidata_backup_20260522` (+ CSVs) | Ready for review | 2026-05-22 |

---

## Quick links (repo root)

| Topic | Location |
|-------|----------|
| Run audits & backfill | [README.md](../README.md) |
| **Final audit report (HTML)** | `outputs/parcel_audits/final_unidata_audit_report.html` — `py -3 tools/reporting/final_unidata_audit_report.py` |
| Generated HTML/CSV (not in Git) | `outputs/missingness_step1/` … `outputs/parcel_audits/` |
| GPKG backfill (attributes) | `tools/audits/enrich_unidata_from_gpkg.py` |
| GPKG backfill (footprints) | `tools/audits/enrich_unidata_footprints.py` |
