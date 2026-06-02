# KR 2.4 — ParcelIQ source matrix (Tier 1)

> **Summary:** Priority data items for ParcelIQ KR 2.4 — target tables, authoritative sources, join keys, Unidata coverage (May 2026 post re-audit), and ETL status.  
> **Updated:** 2026-05-29 · **Author:** Unidata audit team · **Status:** Draft for review with ENGs + Calvin  
> **Machine-readable:** [kr24-parceliq-source-matrix.csv](kr24-parceliq-source-matrix.csv)

---

## Scope

- **Parcel universe:** Santa Clara County · **494,142** parcels (`public.unidata` v2.3 spine)
- **Mindset:** Same as Unidata v2.3 — source shortlist → pilot → ingest → QC → audit
- **KR 2.4 difference:** Multiple **target tables** (MLS, assessor attributes, zoning, comps), not only `unidata`

**Coordinate with Calvin:** API field mapping, read path (DB vs cache), deploy expectations, curl-based spot checks.

---

## Executive summary

| Category | Tier 1 items | In `unidata` today | ETL mostly done | Needs new table / source |
|----------|-------------:|:------------------:|:---------------:|:-------------------------|
| Parcel ID & geometry | 8 | **7** | **7** | Zip code |
| Property characteristics | 4 | **2** (sqft, building_area) | **2** | Year built, property type, beds/baths |
| Zoning / GP | 5 | **1** (zoning) | **1** | General plan, FAR, height, density |
| Environmental | 6 | **5** (fldzone + 4 booleans) | **5** | Fire zone, fhszsra gap |
| MLS & valuation | 11 | **0** | **0** | All — new `mls_*` / derived tables |
| Media | 2 | **0** | **0** | MLS media |
| Schools / crime | 4 | **0** | **0** | Third-party APIs |
| AlphaX pro forma | 3 | **0** | **0** | Internal product data |

---

## Proposed target tables (schema direction)

| Table | Purpose | Grain | Primary key |
|-------|---------|-------|-------------|
| **`public.unidata`** | Parcel spine (existing) | 1 row / parcel | `id`, `parcelnumb` + `scity` |
| **`parcel_attributes`** | Assessor attrs not on spine | 1 row / parcel | `parcel_id` or APN+scity |
| **`parcel_zoning`** | Zoning / GP / development regs | 1 row / parcel (or 1:N zone) | APN + effective date |
| **`parcel_hazards`** | Non-fldzone hazards (fire, wetland, …) | 1 row / parcel | APN |
| **`mls_listings`** | Active/historical listings | 1 row / listing | `listing_id` |
| **`mls_sales`** | Sold events | 1 row / sale | `sale_id` |
| **`mls_media`** | Image URLs | 1:N / listing | `listing_id` |
| **`parcel_comps` / `parcel_valuation`** | Derived comps & AVM | 1 row / parcel / snapshot | APN + as_of_date |
| **`parcel_schools`**, **`parcel_crime`** | Neighbor insight | 1:N or tract-level | APN or geoid |
| **`proforma_inputs`** | AlphaX financial assumptions | Product-specific | N/A |

*Final names — align with ENGs in schema design sessions.*

---

## Tier 1 — In `unidata` today (maintain + fill gaps)

| Data item | Column | Present % | Missing | Next source / action | ETL status |
|-----------|--------|----------:|--------:|----------------------|------------|
| Address | `address` | 99.66% | 1,663 | County Parcels GeoJSON (done for most) | **Done** |
| APN | `parcelnumb` | 100% | 0 | — | **Done** |
| City | `city` | 100% | 0 | — | **Done** |
| Situs city | `scity` | 99.998% | 10 | County Parcels GeoJSON | **Done** May 2026 |
| Lot size | `sqft` | 100% | 0 | GPKG | **Done** |
| Building area | `building_area` | 100% | 0 | GPKG | **Done** |
| Zoning | `zoning` | 99.94% | 310 | GPKG + Planning Hub | **Done** / minor gap |
| Flood zone | `fldzone` | 100% | 0 | FEMA / county GIS | **Done** (ticket-04) |
| Fault / landslide / liquefaction | booleans | 100% populated | 0 | Review NULL vs FALSE semantics | **Review** Step 3/4 |
| Footprints | `footprints` | **97.34%** | 13,142 | County Buildings 2D (done +4,649) | **Done** May 2026 |
| Year built | `yearbuilt` | **95.64%** | **21,561** | **Assessor bulk file** (not in Parcels GeoJSON) | **Pilot needed** |
| fhszsra | `fhszsra` | **2.43%** | **482,141** | FEMA NFHL / State FHSZ — **product decision** | **Blocked** on source |

---

## Tier 1 — New tables / sources (KR 2.4 build)

### MLS (highest product priority — not in DB today)

| Data item | Source | Join key | Suggested table |
|-----------|--------|----------|-----------------|
| MLS Status, Listing Price, Sold Price, Listing Type, DOM | MLS feed | `listing_id`, xref APN | `mls_listings` |
| Exterior / Interior images | MLS | `listing_id` | `mls_media` |
| Similar listings, Recently sold, Last sold price | MLS + derived | APN + market | `parcel_comps`, `mls_sales` |

**ETL status:** Not started · **Owner:** MLS vendor contract + Marwin (audit) + ENG (schema)

### Assessor / county (extend beyond `unidata`)

| Data item | Source | Join key | Suggested table |
|-----------|--------|----------|-----------------|
| Zip code | Assessor situs / USPS | APN + address | `parcel_attributes` |
| Property type | Assessor roll | APN + scity | `parcel_attributes` |
| Year built | Assessor characteristic file | APN | `unidata.yearbuilt` or `parcel_attributes` |
| Beds / baths | Assessor or MLS | APN | `parcel_attributes` |

**Sources to evaluate first:**

- https://www.sccassessor.org/about-us/purchase-data/bulk-data  
- https://data.sccgov.org/ (Parcels — already used for scity/address)  
- https://gisdata-sccplanning.hub.arcgis.com/ (zoning, general plan)

### Zoning & development (mostly new columns/tables)

| Data item | Source | Notes |
|-----------|--------|-------|
| General plan | County Planning GIS | Not in `unidata` today |
| Floor area limit, Height limit, Density | County zoning GIS | Link via APN or spatial join |

### Environmental (extend `unidata` or `parcel_hazards`)

| Data item | Source | Notes |
|-----------|--------|-------|
| Fire (FHSZ) | State FHSZ | Separate from `fldzone` |
| fhszsra | FEMA NFHL | ~98% gap — decide if P0 for MVP |

### Neighbor insight (third-party)

| Data item | Source | Notes |
|-----------|--------|-------|
| Schools | GreatSchools / NCES | Spatial; quarterly refresh |
| Crime | LexisNexis / CoreLogic | License; tract or point |

### Derived / AlphaX (do after base tables)

| Data item | Source | Notes |
|-----------|--------|-------|
| AVM, Comps, Price/sqft | DERIVED | Requires MLS + parcel base |
| Loan interest, Cost base, Dev strategy | AlphaX | Not county ingest |

---

## Recommended KR 2.4 phase plan

| Phase | Focus | Deliverable |
|-------|--------|-------------|
| **1** | Lock schema with ENGs + Calvin | ERD + API field map |
| **2** | Close `unidata` gaps | Assessor pilot for **yearbuilt**; spot-check 10 `scity`, 13k footprint gaps |
| **3** | MLS pilot | `mls_listings` sample + coverage % by APN |
| **4** | `parcel_attributes` | zip, property type, beds/baths |
| **5** | `parcel_zoning` + hazards | Planning Hub + FEMA |
| **6** | Derived comps/AVM | After MLS live |

---

## Sources already evaluated (May 2026 re-audit)

| Source | Verdict | Use for |
|--------|---------|---------|
| `Addional.geojson` / `California.gpkg` | Skip (duplicate Microsoft) | — |
| `Buildings_Footprints_2D.geojson` | **Applied** | footprints (+4,649) |
| `Parcels_20260529.geojson` | **Applied** | scity (+1,919), address (+6) |
| `ca_santa_clara_parcel_build_opt.gpkg` | Applied earlier | parcel attributes |
| Assessor bulk | **Not started** | yearbuilt, beds/baths |

---

## How to refresh coverage numbers

```bash
py -3 tools/reporting/final_unidata_audit_report.py
# → outputs/parcel_audits/final_unidata_audit_field_missingness.csv
```

Update the CSV column `present_pct` / `missing_count` from that export after each backfill.

---

## Related docs

- [README.md](../README.md) — runbooks  
- [release-unidata-v2.3-data-sheet.md](release-unidata-v2.3-data-sheet.md) — v2.3 baseline  
- [index.md](index.md) — doc catalog  
