# MLS Property Listing — schema design

**Draft · 2026-06-12 · ENG + Calvin review**

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
unidata
  └── mls_listing_parcel_xref   (listing ↔ parcel, match_method)
        └── mls_listings        (1 row per listing)
              ├── mls_sales     (closed transactions)
              └── mls_media     (image URLs)
```

DDL: [`migrations/kr24_mls_tables.sql`](migrations/kr24_mls_tables.sql)

---

## Coverage (re-survey 2026-06-12, read-only API join)

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

---

## Reproduce

```bash
py -3 tools/audits/mls_survey.py
```

Outputs: `mls_survey_report.json`, `mls_join_quality.json`, `mls_field_fill_probe.json`
