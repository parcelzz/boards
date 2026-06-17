# MLS Property Listing — schema design

**Draft · 2026-06-11 · ENG + Calvin review**

Scope: 7 MLS catalog fields only. **Do not add columns to `unidata`.**

---

## Source

| Item | Value |
|------|-------|
| Vendor | MLSListings RESO OData (`full` scope) |
| URL | `https://vendordata.api-v2.mlslistings.com/full` |
| Join key | `ParcelNumber` → normalize → `unidata.parcelnumb` |
| Filter | `CountyOrParish = SantaClara` |
| Listings scanned | 237,915 (all statuses) |

APN normalize: uppercase, strip dashes/non-alphanumeric (`442-49-020` → `44249020`).

---

## Field mapping

| Catalog item | RESO field | Column | Derivation |
|--------------|------------|--------|------------|
| MLS Status | `StandardStatus` | `mls_listings.standard_status` | direct |
| Listing Price | `ListPrice` | `mls_listings.list_price` | direct |
| Sold Price | `ClosePrice` | `mls_listings.close_price` / `mls_sales` | when Closed |
| Listing Type | `PropertyType`, `PropertySubType` | `property_type`, `property_sub_type` | direct |
| Days on Market | `DaysOnMarket` | `mls_listings.days_on_market` | fallback: `CumulativeDaysOnMarket` |
| Price Reduced | `PreviousListPrice` or `OriginalListPrice` vs `ListPrice` | `price_reduced`, `price_reduced_source` | see below |
| AlphaX Listing | *not in MLS* | `mls_listings.alphax_listing` | AlphaX internal |

**Price Reduced rule (corrected):**
- `previous_list_price` when `PreviousListPrice > ListPrice` (rare — 0% fill in feed)
- `original_list_price` when `OriginalListPrice > ListPrice` (primary — 100% fill on active sample)

ETL keys: `ListingKeyNumeric` (PK), `ListingId`, `ModificationTimestamp`, `OnMarketDate`, `CloseDate`.

---

## Tables

```
unidata (494,142 parcels — unchanged)
  └── mls_listing_parcel_xref   listing ↔ parcel link + match quality
        └── mls_listings        1 row per MLS listing (all statuses)
              ├── mls_sales     closed-sale facts (1:1 with closed listing)
              └── mls_media     photo / media URLs per listing
```

DDL: [`db/migrations/kr24_mls_tables.sql`](../../db/migrations/kr24_mls_tables.sql)  

Apply idempotently: `py -3 tools/mls/apply_schema.py`

### `mls_listings` — one row per MLS listing

The primary ingest table. Each row is a single listing from MLSListings (Active, Pending, Closed, Expired, Withdrawn, etc.).

| Column | Type | Purpose |
|--------|------|---------|
| `listing_key_numeric` | `bigint` PK | MLS stable key (`ListingKeyNumeric`) — ETL upsert key |
| `listing_id` | `text` UNIQUE | Human-readable MLS id (e.g. `ML82046248`) |
| `parcel_number_raw` | `text` | Raw `ParcelNumber` from feed (may include dashes) |
| `apn_norm` | `text` | Normalized APN for join to `unidata.parcelnumb` |
| `standard_status` | `text` | **MLS Status** — `StandardStatus` (Active, Closed, Pending, …) |
| `list_price` | `numeric` | **Listing Price** — `ListPrice` |
| `close_price` | `numeric` | **Sold Price** on listing row — `ClosePrice` when closed |
| `original_list_price` | `numeric` | Used for price-reduced derivation |
| `previous_list_price` | `numeric` | Rarely populated in feed; kept for completeness |
| `property_type` | `text` | **Listing Type** — `PropertyType` |
| `property_sub_type` | `text` | **Listing Type** — `PropertySubType` |
| `days_on_market` | `integer` | **Days on Market** — `DaysOnMarket` (fallback: `CumulativeDaysOnMarket`) |
| `price_reduced` | `boolean` | **Price Reduced** — derived flag |
| `price_reduced_source` | `text` | Which price was higher: `previous_list_price` or `original_list_price` |
| `alphax_listing` | `boolean` | **AlphaX Listing** — not in MLS; default `false` until internal source |
| `on_market_date` | `date` | `OnMarketDate` |
| `close_date` | `date` | `CloseDate` |
| `county_or_parish` | `text` | Filter field — Santa Clara ingest uses `SantaClara` |
| `city` | `text` | Situs city from MLS |
| `unparsed_address` | `text` | Full MLS address string |
| `modification_timestamp` | `timestamptz` | ETL incremental sync key (`ModificationTimestamp`) |
| `ingested_at` | `timestamptz` | When this row was written to Postgres |
| `raw_json` | `jsonb` | Full API payload for audit / reprocessing |

**Indexes:** `apn_norm`, `standard_status`, `modification_timestamp`

### `mls_sales` — closed-sale records

Denormalized closed transactions for “last sold price” and sale history. Populated when `standard_status = Closed`.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | `bigserial` PK | Surrogate key |
| `listing_key_numeric` | `bigint` FK → `mls_listings` | One sale row per closed listing |
| `apn_norm` | `text` | Parcel key for parcel-level queries |
| `close_price` | `numeric` | **Sold Price** |
| `close_date` | `date` | Sale / close date |
| `ingested_at` | `timestamptz` | Load timestamp |

**Indexes:** `apn_norm`, `close_date DESC`

### `mls_media` — listing photos and media

Optional enrichment — not one of the 7 catalog fields today, but ready if ParcelIQ shows listing images.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | `bigserial` PK | Surrogate key |
| `media_key_numeric` | `bigint` | MLS media key when present |
| `listing_key_numeric` | `bigint` FK → `mls_listings` | Parent listing |
| `media_category` | `text` | e.g. Photo, Video |
| `media_type` | `text` | MIME / RESO media type |
| `url` | `text` | Media URL (unique per listing + url) |
| `display_order` | `integer` | Sort order in gallery |
| `ingested_at` | `timestamptz` | Load timestamp |

### `mls_listing_parcel_xref` — listing ↔ parcel join

Explicit bridge when APN-only join is insufficient (missing parcel number, condo suffixes, fuzzy address match).

| Column | Type | Purpose |
|--------|------|---------|
| `id` | `bigserial` PK | Surrogate key |
| `listing_key_numeric` | `bigint` FK → `mls_listings` | MLS listing |
| `unidata_id` | `bigint` FK → `unidata.id` | Parcel spine row |
| `match_method` | `text` | `apn_exact`, `address_fuzzy`, `manual`, `unmatched` |
| `match_confidence` | `numeric(3,2)` | Score for non-exact matches |
| `created_at` | `timestamptz` | When match was recorded |

**Indexes:** `unidata_id`, `listing_key_numeric`

### Views (read helpers)

| View | Returns | Use case |
|------|---------|----------|
| `mls_last_sale_by_apn` | Latest `close_price` + `close_date` per `apn_norm` | **Sold Price** catalog row — “what did this parcel last sell for?” |
| `mls_latest_live_by_apn` | Latest Active / Pending / AUC listing per `apn_norm` | **Live** MLS Status, Price, DOM, Price Reduced |

Live statuses: `Active`, `Pending`, `ActiveUnderContract`.

---

## Join strategy

**Primary join (simple path):**

```sql
-- apn_norm on MLS side = normalized unidata.parcelnumb
upper(regexp_replace(unidata.parcelnumb, '[^A-Z0-9]', '', 'gi'))
```

Example: MLS `442-49-020` → `44249020` = `unidata.parcelnumb` for 1787 Foxworthy Ave, San Jose.

**Explicit join (xref path):**

```sql
SELECT u.*, l.*
FROM public.unidata u
JOIN public.mls_listing_parcel_xref x ON x.unidata_id = u.id
JOIN public.mls_listings l ON l.listing_key_numeric = x.listing_key_numeric;
```

**Coverage concepts (for catalog reporting):**

| Term | Meaning |
|------|---------|
| **History coverage** | Parcel ever had a matched MLS listing (any status) |
| **Live coverage** | Parcel has Active / Pending / AUC listing now (~0.6% of spine) |
| **Field fill** | Among matched listings, % where the RESO field is non-null |

---

## Coverage (re-survey 2026-06-11, read-only API join)

Denominator: **494,142** unidata parcels. Source: `outputs/parceliq_coverage/mls_survey_report.json`

### Full history (all listing statuses)

| Data item | Coverage | Parcels | Field fill (matched listings) |
|-----------|----------|---------|-------------------------------|
| MLS Status | **28.89%** | 142,757 | 100% |
| Listing Price | **28.89%** | 142,756 | 100% |
| Sold Price | **26.31%** | 129,994 | 76% |
| Listing Type | **28.89%** | 142,757 | 100% |
| Days on Market | **23.50%** | 116,109 | 73% |
| Price Reduced | **7.30%** | 36,062 | 20% |
| AlphaX Listing | **0.00%** | 0 | n/a |

### Live listings only (Active / Pending / AUC)

| Data item | Live coverage | Parcels |
|-----------|---------------|---------|
| MLS Status / Price / Type | **0.58%** | 2,868 |
| Days on Market | **0.57%** | 2,804 |
| Price Reduced | **0.18%** | 886 |
| Sold Price | **0.00%** | 0 |

---

## Join quality

Source: `outputs/parceliq_coverage/mls_join_quality.json`

| Metric | Value |
|--------|-------|
| Listings with ParcelNumber | 94.5% |
| APN match to unidata | 91.4% of all listings |
| Distinct matched parcels | 142,757 (28.9% of spine) |

| Unmatched bucket | Count |
|------------------|-------|
| no_parcel_number | 13,137 |
| suffix_mismatch | 6,401 |
| not_in_unidata | 875 |
| tbd_placeholder | 152 |
| multi_apn_partial | 4 |

---

## Gaps

- **AlphaX Listing** — not in MLS feed (`SpecialListingConditions` = Standard only)
- **Price Reduced** — `PreviousListPrice` always null; use `OriginalListPrice` instead
- **Days on Market** — null on ~27% of matched closed listings
- **APN suffixes** — condo/unit suffixes (`841-63-012-1`) need xref fallback

---

## Decisions needed

1. Approve table DDL (`mls_listings`, `mls_sales`, `mls_media`, xref)
2. Calvin: MLS as separate API endpoint, not on `unidata`
3. Closed listing backfill depth (currently full SC history scanned)
4. AlphaX Listing internal source

**Ingest:** after schema approval only.

Planned ETL shape (not implemented):

1. **Initial backfill** — paginate MLSListings OData (`CountyOrParish = SantaClara`), upsert into `mls_listings` by `listing_key_numeric`.
2. **Daily delta** — `ModificationTimestamp` since last run.
3. **Derived loads** — insert/update `mls_sales` for closed listings; optional `mls_media` from Media resource.
4. **Xref build** — APN exact match first; queue fuzzy/manual for unmatched buckets.
5. **QC** — compare row counts and coverage to `mls_survey_report.json` baselines.

Auth: `MLS_AUTH_TOKEN` in local `.env` (gitignored). Survey script: `tools/mls/mls_survey.py`.

---

## Reproduce

```bash
py -3 tools/mls/mls_survey.py
```

Outputs: `mls_survey_report.json`, `mls_join_quality.json`, `mls_field_fill_probe.json`

Review CSV: [`mls-schema-review.csv`](mls-schema-review.csv)
