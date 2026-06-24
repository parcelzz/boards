# AlphaX — schema design

**Draft · 2026-05-29 · mirrors MLS extension pattern**

Scope: **all ParcelIQ catalog items with AlphaX as authoritative source.**  
**Do not add columns to `unidata`.** Extension tables + MLS flag only.

---

## Catalog coverage

| Group | Data item | Tier | Use case | Source today | Target column | Status |
|-------|-----------|------|----------|--------------|---------------|--------|
| MLS Property Listing | AlphaX Listing | 2 | Query / Filter, Display | `actool.mls` | `mls_listings.alphax_listing` | **Ingest live** |
| Investment & Development | Loan Interest | 1 | Pro Forma | Loan Team (future) | `alphax_proforma_inputs.loan_interest` | Schema ready |
| Investment & Development | Cost Base | 1 | Pro Forma | AlphaX (future) | `alphax_proforma_inputs.cost_base` | Schema ready |
| Investment & Development | Development Strategy | 1 | Feasibility, Pro Forma | `actool.mls.developmentstatus` | `alphax_proforma_inputs.development_strategy` | **Partial ingest** |
| Disclosure AI | Vendor Info | 3 | Display | `actool.comments` (interim) | `alphax_disclosures.vendor_info` | **Partial ingest** |

---

## Source

| Item | Value |
|------|-------|
| System | Acquisition Tool Postgres |
| Host | `POSTGRES_IP` in `.env` |
| Schema | `POSTGRES_SCHEMA=actool` (default) |
| Tables | `alphax`, `mls`, `combined`, `comments` |
| Join key | `fid` (deal ↔ MLS/combined); `ParcelNumber` → `apn_norm` → `unidata` |
| Filter | `CountyOrParish = SantaClara` (default ingest) |

---

## Tables

```
unidata (unchanged)
  └── alphax_deal_parcel_xref
        └── alphax_deals
              ├── alphax_proforma_inputs   (loan interest, cost base, dev strategy)
              ├── alphax_disclosures       (vendor info)
              └── alphax_mls_links → mls_listings.alphax_listing
```

DDL: [`db/migrations/kr24_alphax_tables.sql`](../../db/migrations/kr24_alphax_tables.sql)  
Apply: `py -3 tools/alphax/apply_schema.py`

### `alphax_deals`

From `actool.alphax` LEFT JOIN `actool.combined` on `fid`.

| Column | Catalog / purpose |
|--------|-------------------|
| `source_id` | ETL key (`actool.alphax.id`) |
| `fid` | Bridge to MLS / combined |
| `transaction_status`, `utility_status`, `ifund` | Deal workflow |
| `alphax_held`, `attom_id`, `list_price_snapshot`, `close_price_snapshot` | Combined enrichment |
| `zoning`, `property_type`, `lat`, `lon` | Context for feasibility |

### `alphax_mls_links`

| Column | Catalog / purpose |
|--------|-------------------|
| `listing_key_numeric` | Join to `mls_listings` |
| `alphax_timestamp`, `link_source` | **AlphaX Listing** detection |
| `development_status` | MLS `DevelopmentStatus` snapshot |

### `alphax_proforma_inputs`

One row per deal. Parcel access via `alphax_deal_parcel_xref` or `alphax_proforma_by_apn`.

| Column | Catalog item | Source |
|--------|--------------|--------|
| `loan_interest` | Loan Interest | Loan Team feed (NULL today) |
| `cost_base` | Cost Base | AlphaX feed (NULL today) |
| `development_strategy` | Development Strategy | `actool.mls.developmentstatus` |
| `strategy_source` | — | `actool_mls` \| `loan_team` |

### `alphax_disclosures`

| Column | Catalog item | Source |
|--------|--------------|--------|
| `vendor_info` | Vendor Info | `actool.comments.content` (interim); Disclosure AI vendor feed later |
| `disclosure_type` | — | `deal_comment` \| `vendor` |
| `source_comment_id` | — | Upsert key from `actool.comments.id` |

### `alphax_deal_parcel_xref`

Links deals to `unidata.id` via `mls_xref` or `apn_exact` (same pattern as MLS).

---

## Views

| View | Use case |
|------|----------|
| `alphax_listing_by_apn` | **AlphaX Listing** per parcel |
| `alphax_proforma_by_apn` | Investment fields per parcel |
| `alphax_catalog_by_apn` | Single API read path for all AlphaX catalog columns |

---

## Join strategy

```sql
SELECT alphax_listing, loan_interest, cost_base, development_strategy, vendor_info
FROM public.alphax_catalog_by_apn
WHERE apn_norm = '44249020';
```

---

## Gaps / next feeds

| Field | Blocker | Owner |
|-------|---------|-------|
| Loan Interest | Not in `actool` — Loan Team monthly feed | AlphaX Loan Team |
| Cost Base | Not in `actool` — product pro forma API | AlphaX |
| Vendor Info (production) | Disclosure AI vendor payload | AlphaX |

`loan_interest` and `cost_base` columns exist; ingest will populate when source endpoints are wired.

---

## Ingest

```bash
py -3 tools/alphax/apply_schema.py
py -3 tools/alphax/alphax_load_postgres.py --apply
```

Manifest: `outputs/parceliq_coverage/alphax_load_manifest.json`

Short reference: [`alphax-tables.md`](alphax-tables.md)
