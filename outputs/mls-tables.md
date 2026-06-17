# MLS tables — short reference

**Database:** `parcelz` · **Join spine:** `public.unidata` (unchanged)  
**DDL:** [`db/migrations/kr24_mls_tables.sql`](../../db/migrations/kr24_mls_tables.sql) · **Apply:** `py -3 tools/mls/apply_schema.py`

MLS data lives in **extension tables**, not on `unidata`. Join by normalized APN:

`apn_norm` = uppercase, strip non-alphanumeric from `ParcelNumber` / `unidata.parcelnumb`

---

## Tables (what each holds)

| Table | Grain | Purpose |
|-------|-------|---------|
| **`mls_listings`** | 1 row / MLS listing | All statuses (Active, Closed, Pending, …). Catalog fields: status, list price, sold price, type, DOM, price reduced. |
| **`mls_sales`** | 1 row / closed listing | Last sold facts (`close_price`, `close_date`) for closed listings. |
| **`mls_media`** | 1 row / photo URL | Listing photos and media URLs. *(Not bulk-loaded yet.)* |
| **`mls_listing_parcel_xref`** | listing ↔ parcel | Links `listing_key_numeric` → `unidata.id` with match method + confidence. |


## Views (query helpers)

| View | Returns |
|------|---------|
| **`mls_latest_live_by_apn`** | Newest Active / Pending listing per parcel (`list_price`, `days_on_market`, …). |
| **`mls_last_sale_by_apn`** | Most recent closed sale per parcel (`close_price`, `close_date`). |

---

## Catalog → column map

| Product field | Table.column |
|---------------|--------------|
| MLS Status | `mls_listings.standard_status` |
| Listing Price | `mls_listings.list_price` |
| Sold Price | `mls_listings.close_price` or `mls_sales.close_price` |
| Listing Type | `mls_listings.property_type`, `property_sub_type` |
| Days on Market | `mls_listings.days_on_market` |
| Price Reduced | `mls_listings.price_reduced` *(use `OriginalListPrice > ListPrice`)* |
| AlphaX Listing | `mls_listings.alphax_listing` *(not in MLS feed — always false today)* |

---

## Loaded counts (last full backfill)

| Table | ~Rows |
|-------|-------|
| `mls_listings` | 238,156 |
| `mls_sales` | 170,162 |
| `mls_listing_parcel_xref` | 217,582 |
| `mls_media` | 0 *(pending)* |

**Daily updates:** `py -3 tools/mls/mls_daily_sync.py --apply`

---

## Example — one parcel

APN `44249020` (Foxworthy Ave):

```sql
SELECT l.listing_id, l.standard_status, l.list_price
FROM mls_latest_live_by_apn v
JOIN mls_listings l ON l.listing_key_numeric = v.listing_key_numeric
WHERE v.apn_norm = '44249020';
```

Full design + coverage: [`kr24-mls-schema-design.md`](kr24-mls-schema-design.md)
