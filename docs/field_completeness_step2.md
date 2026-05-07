# Step 2 — Field completeness report

This repo generates **Step 2** of the Next-Stage Work Plan (field completeness QA) from PostgreSQL `public.unidata`.

## Run

From the repository root (requires DB reachable with the credentials in `tools/audits/field_missingness_classification.py`):

```bash
python tools/audits/field_completeness_report_step2.py
```

Optional flags: `--grid-multiplier`, `--min-cell-rows`, `--min-city-rows`, `--max-map-fields`, `--example-limit`, `--out-root`.

## Outputs (`outputs/missingness_step2/`)

| Artifact | Purpose |
|----------|---------|
| `report.html` | **Primary deliverable:** summary table, narrative QA for featured fields, Leaflet spatial maps (OpenStreetMap tiles). |
| `field_completeness_summary.csv` | One row per column: non-null / missing %, spatial & city verdicts, segment proxies, zero-semantics note, example CSV path. |
| `completeness_by_city_long.csv` | Long-format missingness by normalized `scity` (top cities by volume). |
| `spatial_cells/<column>.geojson` | Grid polygons with `missing_pct` and `n` for mapping / GIS. |
| `example_records/<column>_missing_sample.csv` | Sample rows failing the Step 1 “present” predicate. |

**Step 1** artifacts remain under `outputs/missingness_step1/` (`report.html`, bucket CSVs).

## Scope notes

- **Presence rules** match Step 1 (`tools/audits/field_missingness_classification.py`), including numeric fields where `0` is treated as absent for `sqft`, `building_area`, etc.
- **Spatial maps** aggregate rows with non-null `lat` / `lon` into a rectangular grid; verdicts summarize how much missing rates vary across cells.
- **Parcel type:** `public.unidata` does not expose county `usecode`. The report uses **proxies** (`footprints` nonempty vs empty; `sqft` nonzero vs not) instead.
- **Offline use:** Maps load tiles from `tile.openstreetmap.org`; open `report.html` in a browser with network access for basemap tiles.

## Related workshop doc

Use `docs/product_field_review_template.md` (Step 4) together with these CSV/HTML outputs when assigning P0–P3 priorities. Run **Step 3** (`docs/field_semantics_step3.md`) to lock NULL vs FALSE vs zero semantics before final priorities.
