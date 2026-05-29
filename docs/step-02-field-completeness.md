# Step 2 — Field completeness report

> **Summary:** Operator guide for Step 2 field completeness QA on `public.unidata`: how to run the script, what lands in `outputs/missingness_step2/`, and how to use results before Step 3 / Step 4.  
> **Updated:** 2026-05-16 · **Author:** Unidata audit team · **Status:** Completed

---

## Purpose

Generate **Step 2** of the Next-Stage Work Plan (field completeness QA) from PostgreSQL `public.unidata`: spatial grids, city slices, proxies, and sample rows—using the same “present vs missing” rules as Step 1.

---

## Prerequisites

- PostgreSQL with `public.unidata` populated
- Step 1 optional but recommended (`outputs/missingness_step1/`)
- Credentials in `tools/audits/field_missingness_classification.py` (`DEFAULT_DB_CONFIG`)

---

## How to run

From the repository root:

```bash
py -3 tools/audits/field_completeness_report_step2.py
```

Optional flags: `--grid-multiplier`, `--min-cell-rows`, `--min-city-rows`, `--max-map-fields`, `--example-limit`, `--out-root`.

---

## Outputs (`outputs/missingness_step2/`)

| Artifact | Purpose |
|----------|---------|
| `report.html` | **Primary deliverable:** summary table, narrative QA, Leaflet spatial maps (OpenStreetMap tiles). |
| `field_completeness_summary.csv` | One row per column: non-null / missing %, spatial & city verdicts, segment proxies, zero-semantics note, example CSV path. |
| `completeness_by_city_long.csv` | Long-format missingness by normalized `scity` (top cities by volume). |
| `spatial_cells/<column>.geojson` | Grid polygons with `missing_pct` and `n` for mapping / GIS. |
| `example_records/<column>_missing_sample.csv` | Sample rows failing the Step 1 “present” predicate. |

Step 1 artifacts remain under `outputs/missingness_step1/` (`report.html`, bucket CSVs).

---

## How to use results

- **Presence rules** match Step 1 (`field_missingness_classification.py`), including numeric fields where `0` is treated as absent for `sqft`, `building_area`, etc.
- **Spatial maps** aggregate rows with non-null `lat` / `lon` into a rectangular grid.
- **Parcel type:** `public.unidata` has no county `usecode`; the report uses proxies (`footprints` nonempty vs empty; `sqft` nonzero vs not).
- **Offline use:** Maps load tiles from `tile.openstreetmap.org`; open `report.html` with network access for basemap tiles.
- Run **Step 3** before final Step 4 priorities; use the **Step 4 template** with these CSV/HTML outputs.

---

## Related documents

- [Documentation index](index.md)
- [Step 3 — Field semantics](step-03-field-semantics.md)
- [Step 4 — Product field review (template)](step-04-product-field-review-template.md)
- [CONVENTIONS.md](CONVENTIONS.md)
