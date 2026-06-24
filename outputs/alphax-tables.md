# AlphaX tables — short reference

**Source:** Acquisition Tool Postgres (`actool.alphax`, `actool.mls`, `actool.combined`, `actool.comments`)  
**Target:** `parcelz` extension tables · **does not modify `unidata`**  
**DDL:** [`db/migrations/kr24_alphax_tables.sql`](../../db/migrations/kr24_alphax_tables.sql)  
**Apply:** `py -3 tools/alphax/apply_schema.py`  
**Load:** `py -3 tools/alphax/alphax_load_postgres.py --apply`

Credentials in `.env`: `POSTGRES_IP`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`, `POSTGRES_SCHEMA=actool`

---

## Catalog → table map (AlphaX-sourced items only)

| Group | Data item | Tier | Table.column | Update freq | ETL |
|-------|-----------|------|--------------|-------------|-----|
| MLS Property Listing | **AlphaX Listing** | 2 | `mls_listings.alphax_listing` | Weekly | `alphax_load_postgres.py` |
| Investment & Development | **Loan Interest** | 1 | `alphax_proforma_inputs.loan_interest` | Monthly | Awaiting Loan Team feed |
| Investment & Development | **Cost Base** | 1 | `alphax_proforma_inputs.cost_base` | Monthly | Awaiting AlphaX feed |
| Investment & Development | **Development Strategy** | 1 | `alphax_proforma_inputs.development_strategy` | Monthly | From `actool.mls.developmentstatus` |
| Disclosure AI | **Vendor Info** | 3 | `alphax_disclosures.vendor_info` | Monthly | `actool.comments` today; vendor feed later |

**Unified read view:** `alphax_catalog_by_apn` — one row per parcel with any AlphaX signal.

---

## Tables

| Table | Grain | Purpose |
|-------|-------|---------|
| **`alphax_deals`** | 1 row / AlphaX deal | Core deal from `actool.alphax` + `combined` enrichment |
| **`alphax_mls_links`** | 1 row / AlphaX MLS listing | Private listing flag + MLS snapshot |
| **`alphax_proforma_inputs`** | 1 row / deal | Loan interest, cost base, development strategy |
| **`alphax_disclosures`** | 1 row / comment or vendor record | Vendor info / deal comments |
| **`alphax_deal_parcel_xref`** | deal ↔ parcel | Links to `unidata` via MLS xref or APN |

Also sets **`mls_listings.alphax_listing = true`** for matched listings.

---

## Views

| View | Returns |
|------|---------|
| **`alphax_listing_by_apn`** | AlphaX-flagged MLS listing per parcel |
| **`alphax_proforma_by_apn`** | Pro forma fields per parcel (latest deal) |
| **`alphax_catalog_by_apn`** | All AlphaX catalog fields per parcel |

---

## Loaded counts (Santa Clara ingest)

| Table / metric | ~Rows |
|----------------|-------|
| `alphax_deals` | 842 |
| `alphax_mls_links` | 551 |
| `alphax_proforma_inputs` | 842 |
| `alphax_disclosures` | *(varies — actool.comments)* |
| `alphax_deal_parcel_xref` | 159 |
| `mls_listings.alphax_listing = true` | 501 |
| `alphax_catalog_by_apn` | *(parcels with any AlphaX data)* |

---

## Example SQL

```sql
-- All AlphaX catalog fields for one parcel
SELECT alphax_listing, loan_interest, cost_base, development_strategy, vendor_info
FROM alphax_catalog_by_apn
WHERE apn_norm = '44249020';

-- Private listing detail
SELECT apn_norm, listing_id, standard_status, list_price, transaction_status
FROM alphax_listing_by_apn
WHERE apn_norm = '44249020';
```

Full design: [`kr24-alphax-schema-design.md`](kr24-alphax-schema-design.md)
