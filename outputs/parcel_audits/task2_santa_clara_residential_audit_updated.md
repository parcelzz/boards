# Task 2 — Santa Clara Residential Coverage Audit (Updated)

_Generated: 2026-04-29 22:42 UTC. Sources: `ca_santa_clara_parcel_build_opt.gpkg` (baseline) and PostgreSQL `public.unidata`._

## Goal

Reduce error / not-available rates when users query the database by quantifying residential parcel coverage vs the county baseline and field completeness in Unidata.

## Executive summary

- **Residential coverage:** **99.99%** of county residential baseline parcels (453,215 of 453,276) appear in `public.unidata` with the same normalized `scity` and `parcelnumb`.
- **Remaining gap:** **61** baseline residential rows still lack that combined match (often `scity` labeling or missing ingest).
- **Field-level cards:** **34** distinct normalized `scity` buckets appear in Unidata (Table 3).
- **Weakest column (overall):** `fhszsra` (2.43%) — see Table 5.

## How to read each table

### Snapshot KPI tiles

| Tile | Meaning |
|------|---------|
| Residential coverage | Matched baseline ÷ residential baseline (same `scity` + parcel number). |
| Baseline rows | Residential parcels in the GeoPackage (`usecode` 1,2,3,4,6) with usable parcel numbers. |
| Matched in Unidata | Baseline rows that found a partner row in Unidata. |
| Missing | Baseline rows without such a partner. |

### Table 1 — Coverage by `scity`

| Column | Meaning |
|--------|---------|
| Place (`scity`) | Normalized **`scity` only** row key (blank → `(NULL)`; hyphens → spaces). |
| Baseline residential rows | Residential GeoPackage rows for this key. |
| Unidata rows (`scity`) | All Unidata rows with this normalized `scity`. |
| Matched baseline (APN) | Baseline rows whose parcel number exists in Unidata under the same `scity`. |
| Missing | Baseline rows without that match. |
| Coverage % | Matched ÷ baseline when baseline > 0. |

### Table 2 — Field completeness matrix

| Column | Meaning |
|--------|---------|
| Field | Column on `unidata`. |
| Type | Rule category (text / number / boolean / array). |
| Present / Total | Rows populated vs all rows. |
| Completeness % | Present ÷ Total. `sqft` / `building_area`: zero counts as missing; `footprints` needs a non-empty array. |

### Table 3 — Field-level cards

One card per normalized `scity` in Unidata; percentages are **within that city bucket only**.

### Table 4 — Top gaps

`scity` buckets with the largest **missing** baseline residential counts (prioritize remediation).

### Table 5 — Weakest fields

Same semantics as Table 2, sorted so the lowest completeness fields surface first.

## What was compared

- **Baseline:** GeoPackage layer `ca_santa_clara_parcel_build_opt`, residential filter `usecode IN ('1','2','3','4','6')`, excluding NULL/blank `parcelnumb`.
- **Target:** PostgreSQL `public.unidata`.
- **City key:** `scity` only — blank/null `scity` is bucketed as `(NULL)`; never falls back to `city`. Then uppercase with whitespace collapsed and **hyphens replaced by spaces** (e.g. `SAN-JOSE` → `SAN JOSE`).
- **Match rule:** A baseline row counts as *found* when its trimmed uppercased `parcelnumb` exists on any Unidata row with the **same** normalized **`scity`** key.

## Overall coverage (residential baseline)

| Metric | Value |
|--------|------:|
| Coverage % | **99.99%** |
| Baseline residential rows (non-null APN) | 453,276 |
| Matched in Unidata (same `scity` + APN) | 453,215 |
| Missing | 61 |

_Interpretation: “Missing” means the baseline residential parcel row had no Unidata row with the same normalized **`scity`** and parcel number (after trim/case normalization)._

## 1. Coverage % by `scity`

Full table: `outputs/parcel_audits/task2_residential_coverage_by_city.csv`. Below: cities with the largest baseline residential counts (preview).

| City (`scity`) | Baseline residential rows | Unidata rows (`scity`) | Matched baseline (APN) | Missing | Coverage % |
|------|--------------------------:|--------------------:|-----------------------:|--------:|-----------:|
| SAN JOSE | 237,736 | 253,883 | 237,736 | 0 | 100.00% |
| SUNNYVALE | 31,881 | 33,868 | 31,881 | 0 | 100.00% |
| SANTA CLARA | 27,902 | 30,235 | 27,902 | 0 | 100.00% |
| PALO ALTO | 19,102 | 21,023 | 19,102 | 0 | 100.00% |
| MILPITAS | 18,917 | 20,372 | 18,917 | 0 | 100.00% |
| MOUNTAIN VIEW | 18,527 | 20,302 | 18,527 | 0 | 100.00% |
| CUPERTINO | 16,041 | 17,048 | 16,041 | 0 | 100.00% |
| GILROY | 15,084 | 18,063 | 15,084 | 0 | 100.00% |
| LOS ALTOS | 14,823 | 15,987 | 14,823 | 0 | 100.00% |
| MORGAN HILL | 14,054 | 16,768 | 14,054 | 0 | 100.00% |
| LOS GATOS | 13,075 | 15,371 | 13,075 | 0 | 100.00% |
| CAMPBELL | 11,651 | 12,755 | 11,651 | 0 | 100.00% |
| SARATOGA | 10,792 | 11,740 | 10,792 | 0 | 100.00% |
| SAN MARTIN | 1,376 | 2,052 | 1,376 | 0 | 100.00% |
| MONTE SERENO | 1,185 | 1,226 | 1,185 | 0 | 100.00% |
| STANFORD | 914 | 1,094 | 914 | 0 | 100.00% |
| MOUNT HAMILTON | 72 | 109 | 72 | 0 | 100.00% |
| LOS ALTOS HILLS | 59 | 0 | 0 | 59 | 0.00% |
| PORTOLA VALLEY | 31 | 36 | 31 | 0 | 100.00% |
| (NULL) | 29 | 1,929 | 29 | 0 | 100.00% |
| WATSONVILLE | 18 | 29 | 18 | 0 | 100.00% |
| COYOTE | 3 | 9 | 3 | 0 | 100.00% |
| LEXINGTON HILLS | 2 | 0 | 0 | 2 | 0.00% |
| REDWOOD ESTATES | 2 | 6 | 2 | 0 | 100.00% |

_Rows with zero baseline residential parcels but non-zero Unidata rows indicate parcels attributed to that **`scity`** in Unidata without a matching residential baseline row for the same normalized **`scity`** (e.g., naming mismatches or geography outside the residential filter)._

## 2. Field Completeness Matrix (`public.unidata`)

| Field | Type | Present records | Total records | Completeness % |
|-------|------|----------------:|--------------:|---------------:|
| `address` | text | 492,473 | 494,142 | 99.66% |
| `alquist_fault` | boolean | 494,142 | 494,142 | 100.00% |
| `building_area` | number | 460,309 | 494,142 | 93.15% |
| `city` | text | 494,142 | 494,142 | 100.00% |
| `created_at` | timestamp | 494,142 | 494,142 | 100.00% |
| `fhszlra` | number | 483,843 | 494,142 | 97.92% |
| `fhszsra` | number | 12,001 | 494,142 | 2.43% |
| `fldzone` | text | 494,137 | 494,142 | 100.00% |
| `footprints` | text | 457,990 | 494,142 | 92.68% |
| `h3` | text | 494,142 | 494,142 | 100.00% |
| `id` | number | 494,142 | 494,142 | 100.00% |
| `landslide` | boolean | 494,142 | 494,142 | 100.00% |
| `lat` | number | 494,142 | 494,142 | 100.00% |
| `liquefaction` | boolean | 494,142 | 494,142 | 100.00% |
| `lon` | number | 494,142 | 494,142 | 100.00% |
| `parcel` | text | 494,142 | 494,142 | 100.00% |
| `parcelnumb` | text | 494,142 | 494,142 | 100.00% |
| `ready` | boolean | 494,142 | 494,142 | 100.00% |
| `scity` | text | 492,213 | 494,142 | 99.61% |
| `sqft` | number | 473,006 | 494,142 | 95.72% |
| `updated_at` | timestamp | 494,142 | 494,142 | 100.00% |
| `yearbuilt` | number | 472,581 | 494,142 | 95.64% |
| `zoning` | text | 493,832 | 494,142 | 99.94% |

_Notes: `sqft` and `building_area` treat `0` as missing (common ingestion sentinel). `footprints` requires a non-empty varchar array._

## 3. Field-Level Coverage by `scity` (Unidata rows)

_Per-`scity` completeness for **all 34** normalized buckets is in the HTML report (section 3). Below: the **top 25** buckets by Unidata row count._


### San Jose


253,883 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 96.79% |
| Address | 99.77% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 94.81% |
| Size (`sqft`, non-zero) | 95.88% |
| Zoning | 99.97% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 96.93% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Sunnyvale


33,868 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 98.22% |
| Address | 99.78% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 95.97% |
| Size (`sqft`, non-zero) | 98.34% |
| Zoning | 99.99% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 97.54% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Santa Clara


30,235 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 97.77% |
| Address | 99.78% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 95.97% |
| Size (`sqft`, non-zero) | 97.44% |
| Zoning | 99.89% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 97.84% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Palo Alto


21,023 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 96.35% |
| Address | 99.71% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 91.91% |
| Size (`sqft`, non-zero) | 96.96% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 97.96% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Milpitas


20,372 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 96.84% |
| Address | 98.92% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 90.41% |
| Size (`sqft`, non-zero) | 97.11% |
| Zoning | 99.57% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 74.29% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Mountain View


20,302 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 97.16% |
| Address | 99.74% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 94.90% |
| Size (`sqft`, non-zero) | 97.16% |
| Zoning | 99.88% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 96.26% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Gilroy


18,063 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 90.13% |
| Address | 99.66% |
| Flood zone (`fldzone`) | 99.99% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 86.15% |
| Size (`sqft`, non-zero) | 92.87% |
| Zoning | 99.98% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 84.98% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Cupertino


17,048 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 96.95% |
| Address | 99.90% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 94.21% |
| Size (`sqft`, non-zero) | 97.37% |
| Zoning | 99.91% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 97.25% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Morgan Hill


16,768 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 89.60% |
| Address | 99.57% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 85.66% |
| Size (`sqft`, non-zero) | 92.92% |
| Zoning | 99.98% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 89.00% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Los Altos


15,987 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 96.44% |
| Address | 99.86% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 94.53% |
| Size (`sqft`, non-zero) | 98.08% |
| Zoning | 99.96% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 95.62% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Los Gatos


15,371 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 89.25% |
| Address | 99.47% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 86.53% |
| Size (`sqft`, non-zero) | 91.45% |
| Zoning | 99.82% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 58.58% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Campbell


12,755 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 97.38% |
| Address | 99.88% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 95.35% |
| Size (`sqft`, non-zero) | 97.54% |
| Zoning | 99.93% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 93.12% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Saratoga


11,740 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 93.88% |
| Address | 99.73% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 92.73% |
| Size (`sqft`, non-zero) | 95.78% |
| Zoning | 99.98% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 65.93% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### San Martin


2,052 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 74.17% |
| Address | 99.42% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 67.84% |
| Size (`sqft`, non-zero) | 81.92% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 75.19% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### (Null)


1,929 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 4.46% |
| Address | 85.17% |
| Flood zone (`fldzone`) | 99.90% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 1.04% |
| Size (`sqft`, non-zero) | 21.57% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 14.57% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Monte Sereno


1,226 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 96.90% |
| Address | 100.00% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 96.25% |
| Size (`sqft`, non-zero) | 99.18% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 23.16% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Stanford


1,094 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 84.28% |
| Address | 100.00% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 83.46% |
| Size (`sqft`, non-zero) | 89.67% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 93.33% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Mount Hamilton


109 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 89.91% |
| Address | 100.00% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 66.97% |
| Size (`sqft`, non-zero) | 94.50% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 18.35% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Alviso


103 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 0.00% |
| Address | 100.00% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 0.97% |
| Size (`sqft`, non-zero) | 9.71% |
| Zoning | 92.23% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 10.68% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Livermore


37 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 35.14% |
| Address | 100.00% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 0.00% |
| Size (`sqft`, non-zero) | 67.57% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 35.14% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Portola Valley


36 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 86.11% |
| Address | 100.00% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 83.33% |
| Size (`sqft`, non-zero) | 94.44% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 72.22% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Watsonville


29 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 75.86% |
| Address | 100.00% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 58.62% |
| Size (`sqft`, non-zero) | 86.21% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 44.83% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Hollister


21 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 80.95% |
| Address | 100.00% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 0.00% |
| Size (`sqft`, non-zero) | 85.71% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 85.71% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### East Foothills


19 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 5.26% |
| Address | 84.21% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 0.00% |
| Size (`sqft`, non-zero) | 42.11% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 10.53% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

### Loyola


15 Unidata rows (normalized `scity` only).


| Attribute | Completeness % |
|-----------|----------------|
| Year built | 6.67% |
| Address | 86.67% |
| Flood zone (`fldzone`) | 100.00% |
| Hazard flags (all non-null) | 100.00% |
| Main house area (`building_area`, non-zero) | 0.00% |
| Size (`sqft`, non-zero) | 40.00% |
| Zoning | 100.00% |
| Lat / Lon present | 100.00% / 100.00% |
| Footprints non-empty | 20.00% |

Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.

_…9 additional `scity` buckets omitted here; open the HTML report for the full card grid._

## 4. Key Gaps — Top `scity` Values by Missing Baseline Rows

| City | Missing records | Coverage % |
|------|----------------:|-----------:|
| LOS ALTOS HILLS | 59 | 0.00% |
| LEXINGTON HILLS | 2 | 0.00% |

## 5. Weakest Fields (Lowest Completeness)

| Field | Type | Present | Total | Completeness % |
|-------|------|--------:|------:|---------------:|
| `fhszsra` | number | 12,001 | 494,142 | 2.43% |
| `footprints` | text | 457,990 | 494,142 | 92.68% |
| `building_area` | number | 460,309 | 494,142 | 93.15% |
| `yearbuilt` | number | 472,581 | 494,142 | 95.64% |
| `sqft` | number | 473,006 | 494,142 | 95.72% |
| `fhszlra` | number | 483,843 | 494,142 | 97.92% |
| `scity` | text | 492,213 | 494,142 | 99.61% |
| `address` | text | 492,473 | 494,142 | 99.66% |
| `zoning` | text | 493,832 | 494,142 | 99.94% |
| `alquist_fault` | boolean | 494,142 | 494,142 | 100.00% |
| `city` | text | 494,142 | 494,142 | 100.00% |
| `created_at` | timestamp | 494,142 | 494,142 | 100.00% |
| `fldzone` | text | 494,137 | 494,142 | 100.00% |
| `h3` | text | 494,142 | 494,142 | 100.00% |
| `id` | number | 494,142 | 494,142 | 100.00% |

## Root cause analysis

### Missing or incomplete upstream data

Some parcels never receive attributes from upstream systems. That appears as unmatched baseline rows or thin columns in Unidata.

### `scity` labeling mismatch

Grouping uses **`scity` only** (no fallback to `city`). Different spelling, hyphens, blanks, or legacy labels between GPKG and Unidata block matches even when an APN exists in the database.

### Multiple sources without merge priority

Conflicting values across feeds (e.g. living area, zoning text) can produce errors, stale fields, or blanks unless a documented source-of-truth order exists.

### Schema vs product expectations

Attributes such as General Plan, historic status, or setbacks may not exist on `public.unidata`; they cannot be measured here until modeled or joined from another table.

### Pipeline defaults and weak validation

Zeros or empty strings used as placeholders, or uncaught parse failures, distort completeness and user-facing “not available” rates.

### Naturally sparse fields

Some columns are legitimately absent for many parcels (e.g. specialized hazard scores). Low completeness is not always a defect.

## Suggested solutions & next steps

1. Publish and enforce a **`scity` normalization map** (including hyphenated and legacy labels) shared by ingest and the county baseline.
2. Use **Table 1** for geographic prioritization and **Table 4** for the worst residual baseline gaps; drill into APN samples there first.
3. Use **Table 2** and **Table 5** to drive backfills for columns that matter most to product or compliance.
4. Establish a **documented merge policy** (ordered sources, tie-break rules, audit logging).
5. Treat **`0` area fields as unknown** unless business rules say otherwise; validate ranges at ingest.
6. Add **joins or new columns** for attributes required by the app but not stored on `unidata`.
7. Refresh this report **after each major Unidata release** so stakeholders compare apples-to-apples.

---

_Regenerate after refreshing Postgres or the GeoPackage: `python tools/audits/task2_residential_audit.py` (writes this Markdown, `outputs/parcel_audits/task2_residential_coverage_by_city.csv`, and stakeholder HTML)._
