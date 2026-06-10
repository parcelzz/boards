# KR 2.4 — Schema proposal for ENG + Calvin review

**Status:** Draft · **Date:** 2026-05-29 · **Author:** Unidata audit team

## Purpose

Align API read path (Calvin) and database schema (ENGs) with the [ParcelIQ catalog](parceliq-catalog-coverage.csv). **`public.unidata` remains the 494,142-row parcel spine**; enrichment lives in joined tables.

## Spine (existing — no schema change for MVP)

| Table | Grain | PK | API notes |
|-------|-------|-----|-----------|
| `public.unidata` | 1 row / parcel | `id`, `parcelnumb` + `scity` | Calvin: existing Parcel.z endpoints |

## Extension tables (KR 2.4)

| Table | Grain | Join key | Tier 1 fields | Pilot script |
|-------|-------|----------|---------------|--------------|
| `parcel_attributes` | 1:1 parcel | `unidata_id` | zip, property_type, beds_baths | `pilot_parcel_attributes_ingest.py` |
| `parcel_zoning` | 1:1 parcel | `unidata_id` | general_plan, FAR, height (partial from GPKG today) | `pilot_parcel_zoning_ingest.py` |
| `parcel_hazards` | 1:1 parcel | `unidata_id` | fire_zone, wetland, … | `pilot_fire_hazard_ingest.py` |
| `parcel_ownership` | 1:1 or 1:N | `unidata_id` | owner, mail address | (attrs pilot includes owner) |
| `mls_listings` | 1:N listing | `apn_norm` xref | status, price, DOM | `pilot_mls_ingest.py` (stub) — see [kr24-mls-schema-design.md](kr24-mls-schema-design.md) |
| `mls_sales` | 1:N sale | `apn` | last sold price | MLS vendor |
| `mls_media` | 1:N / listing | `listing_id` | image URLs | MLS vendor |
| `parcel_valuation` | 1:1 / snapshot | `unidata_id` | AVM, price/sqft, equity | `parceliq_derived_coverage.py` |
| `parcel_comps` | 1:N / parcel | `unidata_id` | comps, similar listings | ENG derivation |
| `parcel_schools` | 1:N | `unidata_id` | name, distance, rating | GreatSchools API |
| `parcel_crime` | 1:1 or tract | `unidata_id` / tract | crime metrics | LexisNexis license |
| `proforma_inputs` | product | `apn` | loan interest, cost base | AlphaX internal |

## API read path (Calvin)

1. **Parcel detail:** `unidata` + LEFT JOIN `parcel_attributes`, `parcel_zoning`, `parcel_hazards` on `unidata_id`.
2. **MLS overlay:** separate endpoint or nested resource keyed by `apn`; do not denormalize into `unidata`.
3. **Coverage verification:** curl sample APNs after each backfill; map JSON fields to catalog rows in [parceliq-catalog-coverage.csv](parceliq-catalog-coverage.csv).

## Decisions needed

| Topic | Options | Recommendation |
|-------|---------|----------------|
| Zip on spine vs attrs | Add `unidata.zip` vs `parcel_attributes.zip` | **attrs** unless Parcel.z filters require spine column |
| `fhszsra` semantics | NULL = unknown vs not-in-SRA | Product call before more ETL |
| MLS xref | Address match vs APN match rate | Track **join coverage %** separately from feed freshness |
| AVM snapshot grain | 1 row / parcel / day vs latest only | Latest-only for MVP |

## DDL location

Pilot scripts use `CREATE TABLE IF NOT EXISTS` for:

- `tools/audits/pilot_parcel_attributes_ingest.py`
- `tools/audits/pilot_parcel_zoning_ingest.py`
- `tools/audits/pilot_fire_hazard_ingest.py`
- `tools/reporting/parceliq_derived_coverage.py`

Formal migrations should move to ENG-owned migration tool after review session.

## Next meeting agenda

1. Confirm table names and `unidata_id` FK pattern.
2. Calvin: which Tier 1 fields are P0 for API v1.
3. MLS vendor timeline and `listing_id` ↔ APN xref strategy.
4. Approve Assessor bulk purchase for **yearbuilt** (~21.5k gaps).
