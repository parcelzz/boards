# MLS Property Listing — schema design

**Draft · 2026-06-10 · ENG + Calvin review**

Scope: 7 MLS catalog fields only. **Do not add columns to `unidata`.**

---

## Source

| Item | Value |
|------|-------|
| Vendor | MLSListings RESO OData (`full` scope) |
| URL | `https://vendordata.api-v2.mlslistings.com/full` |
| Join key | `ParcelNumber` → normalize → `unidata.parcelnumb` |
| Filter | `CountyOrParish = SantaClara` |

APN normalize: uppercase, strip dashes/non-alphanumeric (`442-49-020` → `44249020`).

---

## Field mapping

| Catalog item | RESO field | Column |
|--------------|------------|--------|
| MLS Status | `StandardStatus` | `mls_listings.standard_status` |
| Listing Price | `ListPrice` | `mls_listings.list_price` |
| Sold Price | `ClosePrice` | `mls_listings.close_price` / `mls_sales` |
| Listing Type | `PropertyType`, `PropertySubType` | `mls_listings.property_type`, `property_sub_type` |
| Days on Market | `DaysOnMarket` | `mls_listings.days_on_market` |
| Price Reduced | `PreviousListPrice` > `ListPrice` | `mls_listings.price_reduced` |
| AlphaX Listing | *not in MLS* | `mls_listings.alphax_listing` (AlphaX internal) |

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

## Coverage (projected, API join — no ingest yet)

Denominator: **494,142** unidata parcels.

| Data item | Coverage | Parcels |
|-----------|----------|---------|
| MLS Status | 26.67% | 131,764 |
| Listing Price | 26.67% | 131,763 |
| Sold Price | 26.30% | 129,970 |
| Listing Type | 26.67% | 131,764 |
| Days on Market | 21.71% | 107,281 |
| Price Reduced | 0.00% | 0 |
| AlphaX Listing | 0.00% | 0 |

Source: `outputs/parceliq_coverage/mls_catalog_coverage.json` (180,736 SC listings scanned).

---

## Gaps

- **Price Reduced** — `PreviousListPrice` is null in feed → 0% today
- **AlphaX Listing** — not in MLS; needs internal source
- **Days on Market** — often null on closed listings
- **APN join** — ~93% of listings have parcel #; ~90% match unidata when present

---

**Ingest:** after schema approval only.

---

## Scripts & outputs

| File | Purpose |
|------|---------|
| `tools/audits/mls_catalog_coverage_fast.py` | Coverage calculation |
| `tools/audits/mls_api_discover.py` | API discovery |
| `docs/parceliq-catalog-coverage.csv` | Catalog with coverage % |
