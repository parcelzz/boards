# KR 2.4 — Data sources and gaps (before schema design)

> **Purpose:** Map every ParcelIQ catalog item to a **concrete source**, current **coverage**, and **blocker** — then design schema and only then pull data.  
> **Updated:** 2026-05-29 · **Universe:** Santa Clara County · **494,142** parcels (`public.unidata`)  
> **Coverage snapshot:** [`parceliq-catalog-coverage.csv`](parceliq-catalog-coverage.csv) · [`outputs/parceliq_coverage/report.html`](../outputs/parceliq_coverage/report.html)

---

## Security note (MLS credentials)

If API tokens were shared in chat, email, or Slack, treat them as **compromised**: rotate with MLSListings and store only in a **local `.env`** (gitignored). This repo uses [`.env.example`](../.env.example) with empty placeholders — **never commit real tokens**.

---

## Recommended sequence

```mermaid
flowchart LR
  A[1 Sources and gaps] --> B[2 Schema design]
  B --> C[3 Pilot ingest]
  C --> D[4 Coverage audit]
  D --> A
```

1. **Sources & gaps** (this doc) — what exists, what’s missing, join keys, licenses  
2. **Schema** — [`kr24-schema-proposal.md`](kr24-schema-proposal.md) finalized with ENGs + Calvin  
3. **Pull data** — one source at a time; dry-run → QC → apply  
4. **Re-measure** — `py -3 tools/reporting/parceliq_coverage_report.py`

---

## Tier 1 summary (52 items)

| Bucket | Count | Status |
|--------|------:|--------|
| **≥99% filled** (spine + attrs) | 16 | Ready for API |
| **Partial gaps** | 3 | yearbuilt, footprints, fhszsra |
| **0% — need new source/table** | 33 | MLS, schools, GP, fire, derived, … |

---

## Layer A — `public.unidata` spine (design: keep narrow)

Already live. **Do not add MLS columns here.**

| Data item | Column | Coverage | Source used | Remaining gap | Next action |
|-----------|--------|----------|-------------|---------------|-------------|
| APN | `parcelnumb` | 100% | Core ingest | 0 | — |
| Address | `address` | 99.66% | County Parcels GeoJSON + GPKG | 1,663 | Manual / assessor situs |
| City / scity | `city`, `scity` | ~100% | GPKG + Parcels GeoJSON | 10 scity | Spot-check edge APNs |
| Lot / building | `sqft`, `building_area` | 100% | GPKG | 0 | — |
| Year built | `yearbuilt` | **95.64%** | GPKG (exhausted) | **21,561** | **Assessor bulk file** — export in `outputs/parceliq_coverage/yearbuilt_gaps.csv` |
| Zoning code | `zoning` | 99.94% | GPKG | 310 | GPKG has no value for these APNs; Planning Hub |
| Footprints | `footprints` | **97.34%** | County LiDAR + Microsoft | **13,142** | Vacant/condo/geometry edge cases — document ceiling |
| Flood | `fldzone` | 100% | FEMA / county GIS | 0 | — |
| Fault / landslide / liquefaction | booleans | 100% populated | USGS / county | 0 | Step 3: NULL vs FALSE semantics |
| fhszsra | `fhszsra` | **2.43%** | Unclear | **482,141** | **Product decision:** NULL = unknown vs not-in-SRA |
| Lat / lon / parcel WKT | `lat`, `lon`, `parcel` | 100% | GPKG / county | 0 | — |

**Schema implication:** Spine stays ~23 columns. Gaps above are **backfill**, not new tables (except product call on `fhszsra`).

---

## Layer B — `parcel_attributes` (1:1 extension) — pilot loaded

| Data item | Column | Coverage | Source | Gap | Blocker |
|-----------|--------|----------|--------|-----|---------|
| Zip | `zip` | **99.96%** | GPKG `szip5` + GeoJSON `situs_zip_code` | 203 | — |
| Property type | `property_type` | **99.72%** | GPKG `usecode` / `usedesc` | 1,386 | — |
| Total acres | `total_acres` | **99.92%** | GPKG `deeded_acres` / `gisacre` | 414 | — |
| Jurisdiction | `jurisdiction` | **99.93%** | Parcels GeoJSON | 326 | — |
| County / state | implicit | 100% | Constant SCC / CA | 12 unmatched attrs rows | — |
| **Beds / baths** | `beds_baths` | **0%** | GPKG `numrooms` empty | 494k | **MLS or Assessor bulk** |
| **Stories** | `num_stories` | **0%** | GPKG `numstories` empty | 494k | Same |
| Neighborhood | `neighborhood` | **0%** | GPKG field sparse | 494k | Assessor / geocoder |
| Owner / mail | `owner_name`, `mail_address` | ~93% owner | GPKG | mail partial | Assessor roll; license for display |

**Schema implication:** Table exists (`parcel_attributes`). Add columns only after source proves fill rate (beds/baths from MLS RESO `BedroomsTotal`, `BathroomsTotalInteger`).

---

## Layer C — `parcel_zoning` — partial

| Data item | Column | Coverage | Source | Gap |
|-----------|--------|----------|--------|-----|
| Zoning desc (support) | `zoning_code`, `zoning_description` | ~99.8% join | GPKG | matches unidata zoning |
| **General plan** | `general_plan` | **0%** | SCC Planning Hub GIS | all |
| **Floor area / height / density** | `floor_area_limit`, etc. | **0%** | Planning + zoning regs | all |

**Blocker:** Need Planning Hub layer URLs and whether regs are **parcel join** or **zone polygon join**.

---

## Layer D — `parcel_hazards` — fire blocked on GIS

| Data item | Column | Coverage | Source |
|-----------|--------|----------|--------|
| **Fire zone** | `fire_zone` | **0%** | CAL FIRE FHSZ (State) |
| Wetland / farmland / hazwaste | various | 0% | NWI, USDA, EPA |

**Blocker:** Download FHSZ for Santa Clara; spatial join on `unidata.parcel` (same pattern as `fldzone`).

---

## Layer E — MLS (MLSListings) — **API verified; 0% ingest**

### Connection (verified 2026-06-10)

| Item | Value |
|------|-------|
| Base URL | `https://vendordata.api-v2.mlslistings.com/full` |
| Auth | `Authorization: Bearer <MLS_AUTH_TOKEN>` in local `.env` |
| Total Property rows | ~511,753 |
| Active / Pending / Closed | ~6,489 / ~1,504 / ~364,747 |
| Schema design | [kr24-mls-schema-design.md](kr24-mls-schema-design.md) |
| DDL draft | [migrations/kr24_mls_tables.sql](migrations/kr24_mls_tables.sql) |

**Do not commit tokens.** Use `.env` only.

### Discovery commands

```bash
py -3 tools/audits/mls_api_discover.py
py -3 tools/audits/mls_apn_join_pilot.py --county SantaClara --status Active --top 100
```

Outputs:

- `outputs/parceliq_coverage/mls_api_discovery.json`
- `outputs/parceliq_coverage/mls_catalog_field_map.json`
- `outputs/parceliq_coverage/mls_apn_join_pilot.json`

Review discovery JSON for:
   - `$metadata` — full RESO resource/field list  
   - Sample `Property` keys — map to catalog columns  
   - `$count` — order-of-magnitude listing count (not 494k — only listed/sold properties)

### RESO fields → ParcelIQ catalog (expected mapping)

| ParcelIQ item | RESO Data Dictionary (typical) | Notes |
|---------------|-------------------------------|--------|
| MLS Status | `StandardStatus` | Active, Pending, Closed, … |
| Listing Price | `ListPrice` | |
| Sold Price | `ClosePrice` | Closed listings |
| Listing Type | `PropertyType` / `PropertySubType` | |
| Days on Market | `DaysOnMarket` or derived from `OnMarketDate` | |
| Last sold price | `ClosePrice` + `CloseDate` on Closed | → `mls_sales` |
| Beds / baths | `BedroomsTotal`, `BathroomsTotalInteger` | Can backfill `parcel_attributes` |
| Images | `Media` resource or `MediaURL` | → `mls_media` URLs only |
| APN xref | **`ParcelNumber`** (confirmed) | Normalize dashes/suffixes; see join pilot |

### APN join pilot (Santa Clara Active, n=100)

| Metric | Result |
|--------|--------|
| `ParcelNumber` filled | 93% |
| Normalized APN matches `unidata.parcelnumb` | **90.3%** of filled |
| Price reduced derivable in sample | 0% (PreviousListPrice mostly null) |

**Unmatched edge cases:** multi-APN strings (`799-03-055 and 799-03-054`), `TBD` placeholders, condo suffixes (`841-63-012-1`), trailing `R`, zero-padded sentinels (`000-000-004`). Xref table should log `match_method` and support address fallback.

### Join strategy (decided for draft schema)

| Approach | Pros | Cons |
|----------|------|------|
| **APN match** to `unidata.parcelnumb` | Stable, matches 494k spine | MLS APN format may differ (dashes, leading zeros) |
| **Address + zip match** | Works when APN missing on listing | Normalization burden; dupes |
| **ListingKey only** | Native MLS grain | No parcel coverage until xref built |

**Recommend:** Store raw MLS fields + normalized `apn_norm` + `match_method` + `match_confidence`. Report **parcel join coverage** separately from **listing count**.

### MLS scope note

MLSListings covers **Bay Area** (Santa Clara, San Mateo, Santa Cruz, Monterey, San Benito). Our spine is **Santa Clara County only** — filter replication by county/ city or post-filter on ingest.

### Schema tables (draft — see [kr24-mls-schema-design.md](kr24-mls-schema-design.md))

| Table | Grain | Key fields |
|-------|-------|------------|
| `mls_listings` | 1 row / listing | `listing_key_numeric`, `listing_id`, `standard_status`, `list_price`, `close_price`, `property_type`, `days_on_market`, `apn_norm`, `modification_timestamp` |
| `mls_sales` | 1 row / closed sale | `listing_key_numeric`, `apn_norm`, `close_price`, `close_date` |
| `mls_media` | 1:N | `listing_key_numeric`, `media_category`, `url` |
| `mls_listing_parcel_xref` | listing ↔ parcel | `listing_key_numeric`, `unidata_id`, `match_method`, `match_confidence` |

**Do not pull bulk MLS until:** ENG approves DDL, Calvin API shape agreed, backfill depth decided.

---

## Layer F — Derived / third-party (0% — blocked on upstream)

| Group | Depends on | Tables |
|-------|------------|--------|
| AVM, comps, equity, ROE | MLS + stable attrs + ENG models | `parcel_valuation`, `parcel_comps` |
| Market analytics (median price, DOM) | MLS aggregates | `market_analytics` |
| Schools | GreatSchools / NCES API + license | `parcel_schools` |
| Crime | LexisNexis / CoreLogic license | `parcel_crime` |
| AlphaX pro forma | Internal product | `proforma_inputs` |

---

## Priority order for schema + ingest

| Phase | Source | Schema target | Why first |
|-------|--------|---------------|-----------|
| **0** | *(done)* | Coverage baseline | [`parceliq-catalog-coverage.csv`](parceliq-catalog-coverage.csv) |
| **1** | Assessor bulk | `unidata.yearbuilt` | 21.5k gap; no MLS dependency |
| **2** | MLSListings RESO | `mls_*` + xref | Unblocks 11+ Tier 1 catalog rows |
| **3** | MLS → attrs | `parcel_attributes.beds_baths` | 0% today |
| **4** | Planning Hub | `parcel_zoning` GP/FAR/height | Feasibility / Tier 1 zoning |
| **5** | CAL FIRE FHSZ | `parcel_hazards.fire_zone` | Tier 1 fire |
| **6** | GreatSchools / crime | neighbor tables | License + cost |
| **7** | ENG derivation | valuation / comps | After MLS stable |

---

## Open decisions (need product + ENG + Calvin)

1. **fhszsra:** Is NULL “unknown” or “not in SRA”?  
2. **MLS xref:** Primary key = APN vs address vs hybrid?  
3. **API read path:** Calvin joins in SQL vs materialized view vs API aggregation?  
4. **Historical MLS:** Closed listings backfill depth (12 mo / 5 yr / full)?  
5. **Assessor bulk:** Purchase timeline for yearbuilt + beds/baths?

---

## Related docs

| Doc | Role |
|-----|------|
| [kr24-schema-proposal.md](kr24-schema-proposal.md) | Table list for ENG review |
| [runbooks/parceliq-etl-runbooks.md](runbooks/parceliq-etl-runbooks.md) | Per-pipeline commands |
| [kr24-parceliq-source-matrix.csv](kr24-parceliq-source-matrix.csv) | Tier 1 subset with coverage |
