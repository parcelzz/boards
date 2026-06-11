# MLSListings Web API 2.0.1 — implementation notes

> Source: *MLSListings API Data Server Guide v2.0.1* (May 2025).  
> Support: data@mlslistings.com · contracts@mlslistings.com

## Base URL

```
https://vendordata.api-v2.mlslistings.com/<scope>
```

| Scope | Typical use |
|-------|-------------|
| `idx` | IDX display feeds |
| `full` | Full replication (match **FULL** scope tokens) |
| `vow` | VOW feeds |

Examples:

- Metadata: `https://vendordata.api-v2.mlslistings.com/full/$metadata`
- Property: `https://vendordata.api-v2.mlslistings.com/full/Property`

## Authentication

- OAuth2 bearer token (issued by MLSListings, **6-month** lifetime, renewed via email).
- Header: `Authorization: Bearer <access_token>`
- Optional: `PrettyPrint: 1` for human-readable lookup values (e.g. city names).

**Do not commit tokens.** Use local `.env` only.

## Resources (RESO OData)

| Resource | Primary key | ParcelIQ use |
|----------|-------------|--------------|
| **Property** | `ListingKeyNumeric` | Status, price, sold, type, DOM, address, beds/baths |
| **Media** | `MediaKeyNumeric` | Exterior/interior image **URLs** (not blobs) |
| **OpenHouse** | `OpenHouseKeyNumeric` | Open house schedule |
| **Member** | `MemberKeyNumeric` | Agent roster |
| **Office** | `OfficeKeyNumeric` | Office roster |
| **PropertyUnit** | `PropertyUnitKeyNumeric` | Multi-family units |

Link Media to Property: `ResourceRecordKeyNumeric` = `ListingKeyNumeric`.

## Key Property fields (RESO → catalog)

| ParcelIQ item | RESO field (guide) |
|---------------|-------------------|
| MLS Status | `StandardStatus` (not `MLSStatus`) |
| Listing Price | `ListPrice` |
| Sold Price | `ClosePrice` when `StandardStatus` = Closed |
| Price Reduced | `OriginalListPrice > ListPrice` (primary; `PreviousListPrice` is null in feed) |
| Listing ID | `ListingId`, `ListingKeyNumeric` |
| Address | `UnparsedAddress`, `City` |
| DOM / list date | `OnMarketDate`, `DaysOnMarket` (confirm in `$metadata`) |
| Incremental sync | `ModificationTimestamp` (UTC / offset) |

**APN / parcel join:** Field **`ParcelNumber`** (dashed format). Normalize before matching `unidata.parcelnumb`. Re-survey (2026-06-11): 94.5% parcel fill, 91.4% listing match rate, 142,757 distinct parcels (28.9% of spine).

**Price Reduced:** Do **not** rely on `PreviousListPrice` (0% fill). Use `OriginalListPrice > ListPrice` — 52% of active sample, 7.3% parcel coverage after join.

## StandardStatus values

Active, ActiveUnderContract, Pending, Closed, Canceled, Expired, Hold, Withdrawn, ComingSoon, Delete, Incomplete

Filter example:

```
/Property?$filter=StandardStatus eq ResourceEnums.StandardStatus'Active'
```

City filter (lookup — no spaces):

```
/Property?$filter=City eq ResourceEnums.City'SanJose'
```

## Sync best practices (from guide)

1. **Incremental:** query where `ModificationTimestamp` > last sync (overlap ~5 min for clock skew).
2. **Bulk initial load:** Step 1 — keys only; Step 2 — batch by `ListingKeyNumeric` (~500 records / 15 min).
3. **Limit `$select`** to 15–20 fields per request.
4. **Photos:** use Media URLs only; do not download image binaries.
5. **No MLS lat/lon** for geo feeds — use assessor/unidata coordinates.

## Local discovery

```bash
py -3 tools/audits/mls_survey.py           # full re-survey
py -3 tools/audits/mls_api_discover.py      # discovery only
```

Outputs: `outputs/parceliq_coverage/mls_survey_report.json`, `mls_join_quality.json`, `mls_field_fill_probe.json`

## Open question for data@mlslistings.com

Confirm our license scope is **`full`** (matches token) and which Property field maps to **Santa Clara County APN** for parcel spine joins.
