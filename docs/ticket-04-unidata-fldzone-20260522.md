# Ticket #4 — Unidata `fldzone` verification (2026-05-22)

> **Summary:** Post-cutover verification of `public.unidata.fldzone` after positive-area GIS overlap and ordered multi-zone aggregation (`X | AH`, etc.). Compares live table to `public.unidata_backup_20260522`. Prepared for team share-out (@sinical / GIS owners).  
> **Updated:** 2026-05-22 · **Author:** Marwin Reyes · **Status:** Ready for review

---

## Purpose / background

Per team discussion with @sinical:

1. **Positive-area overlap** — Batch polygon GIS queries assign a flood zone only when the parcel polygon has **positive-area** intersection with that zone. **Boundary-only touches** must not add a zone to `fldzone`.
2. **Ordered aggregation** — Parcels crossing multiple zones store **ordered distinct** zone codes joined with ` | ` (space-pipe-space), using an explicit flood-zone display order. Example required output: **`X | AH`** for parcels crossing both X and AH.

The GIS update was applied to **`public.unidata`**. The prior snapshot was preserved as **`public.unidata_backup_20260522`**.

This document records **SQL verification** run against PostgreSQL (`parcelz` database, `public` schema) on **2026-05-22**.

---

## Scope

| Item | Detail |
|------|--------|
| **Column verified** | `fldzone` only |
| **Live table** | `public.unidata` |
| **Backup table** | `public.unidata_backup_20260522` |
| **Out of scope** | GIS source geometry review (positive-area rule proof), other columns |

---

## Method

1. Row-count parity on live vs backup.
2. Count parcels where `fldzone` differs between tables (join on `id`).
3. Distribution query: `SELECT fldzone, COUNT(*) … GROUP BY fldzone` on live and backup.
4. Format checks: NULL/blank counts, pipe-separated values, spacing (` | ` vs `|`).
5. Transition analysis among changed rows (single → multi, etc.).
6. Spot samples for `X | AH` and random changed parcels.

**Connection:** local Cloud SQL proxy `127.0.0.1:5432`, database `parcelz`.

**Machine-readable exports:**

| File | Contents |
|------|----------|
| [ticket-04-unidata-fldzone-20260522-distribution.csv](ticket-04-unidata-fldzone-20260522-distribution.csv) | Live `fldzone` × parcel count (62 values) |
| [ticket-04-unidata-fldzone-20260522-backup-distribution.csv](ticket-04-unidata-fldzone-20260522-backup-distribution.csv) | Backup `fldzone` × parcel count (8 values) |

---

## Results — table parity

| Table | Row count |
|-------|----------:|
| `public.unidata` | **494,142** |
| `public.unidata_backup_20260522` | **494,142** |

**Pass** — same row count; join on `id` is valid for all rows.

---

## Results — change summary

| Metric | Value |
|--------|------:|
| Parcels with `fldzone` changed | **22,482** (**4.55%**) |
| Distinct `fldzone` (live) | **62** |
| Distinct `fldzone` (backup) | **8** |
| Parcels with pipe in `fldzone` (live) | **22,478** |
| Parcels with pipe in `fldzone` (backup) | **0** |

### Transition pattern (among 22,482 changed rows)

| Pattern | Count |
|---------|------:|
| Single zone → multi-zone (e.g. `X` → `X \| AH`) | **22,478** |
| Multi-zone → single zone | **0** |
| Multi-zone → different multi-zone | **0** |
| Blank → single zone | **4** |

The cutover is almost entirely **aggregation**: former single-code parcels now carry ordered multi-zone strings.

### Format checks (live)

| Check | Result |
|-------|--------|
| `fldzone` IS NULL | **0** |
| `fldzone` blank (`TRIM` empty) | **0** |
| Values with `\|` but not ` \| ` spacing | **0** |

**Pass** — all multi-zone values use ` | ` separator consistently.

### Backup blanks resolved on live

Backup had **5** rows with blank `fldzone`. Live assigns a zone to each:

| parcelnumb | backup `fldzone` | live `fldzone` |
|------------|------------------|----------------|
| 35125005 | *(blank)* | X |
| 89813023 | *(blank)* | D |
| 86516005 | *(blank)* | D |
| 01533035 | *(blank)* | VE |
| 89828013 | *(blank)* | A \| D |

---

## Results — `X | AH` (required combination)

| `fldzone` (live) | Parcel count |
|------------------|-------------:|
| **X \| AH** | **2,024** |
| X \| AH \| AO | 100 |
| X \| AH \| A | 59 |
| X \| AH \| AE | 26 |
| X \| AH \| A \| AE | 12 |
| X \| AH \| D | 10 |
| Other X+AH combinations | 14 |
| **Total rows mentioning X and AH** | **2,247** |

**Pass** — `X | AH` exists at **2,024** parcels with correct spacing; sampled rows show **X before AH** (ordered aggregation).

### Spot samples: became `X | AH`

| parcelnumb | address | before (backup) | after (live) |
|------------|---------|-----------------|--------------|
| 00340060 | 31 PRIMROSE WAY | X | X \| AH |
| 02212005 | 690 PENITENCIA ST | AH | X \| AH |
| 02813028 | 502 SARK CT | X | X \| AH |
| 02819133 | 955 ERIE CL | X | X \| AH |
| 10414048 | 1370 NORMAN AVE | AH | X \| AH |
| 23506013 | 1144 N 3RD ST | X | X \| AH |
| 29007047 | 1384 BLACKFIELD DR | AH | X \| AH |
| 48101147 | 125 N 33RD ST | AH | X \| AH |

---

## Results — top `fldzone` values (live)

| fldzone | parcel_count |
|---------|-------------:|
| D | 226,345 |
| X | 218,007 |
| AO | 11,925 |
| AE | 8,150 |
| AH | 6,740 |
| X \| D | 6,123 |
| X \| AE | 2,701 |
| A \| D | 2,415 |
| X \| A | 2,287 |
| X \| AO | 2,125 |
| **X \| AH** | **2,024** |
| AO \| D | 1,431 |
| AE \| D | 1,261 |
| A | 485 |
| AH \| D | 244 |
| AH \| AO | 241 |

*Full 62-value distribution:* [ticket-04-unidata-fldzone-20260522-distribution.csv](ticket-04-unidata-fldzone-20260522-distribution.csv)

---

## Results — top `fldzone` values (backup, before)

| fldzone | parcel_count |
|---------|-------------:|
| D | 233,516 |
| X | 227,714 |
| AO | 13,760 |
| AE | 9,871 |
| AH | 7,666 |
| A | 1,588 |
| VE | 22 |
| *(blank)* | 5 |

*Full backup distribution:* [ticket-04-unidata-fldzone-20260522-backup-distribution.csv](ticket-04-unidata-fldzone-20260522-backup-distribution.csv)

---

## Results — where changed rows came from / went to

### Top **new** `fldzone` (live) among changed parcels

| live `fldzone` | parcels |
|----------------|--------:|
| X \| D | 6,123 |
| X \| AE | 2,701 |
| A \| D | 2,415 |
| X \| A | 2,287 |
| X \| AO | 2,125 |
| **X \| AH** | **2,024** |
| AO \| D | 1,431 |
| AE \| D | 1,261 |
| AH \| D | 244 |
| AH \| AO | 241 |

### Top **old** `fldzone` (backup) among changed parcels

| backup `fldzone` | parcels |
|------------------|--------:|
| X | 9,708 |
| D | 7,173 |
| AO | 1,835 |
| AE | 1,721 |
| A | 1,103 |
| AH | 926 |
| VE | 11 |
| *(blank)* | 5 |

Many former **X** or **D** single-zone parcels now have a multi-zone string.

### Random changed samples

| parcelnumb | address | before | after |
|------------|---------|--------|-------|
| 28819013 | 1440 BENT DR | D | X \| D |
| 48810050 | 1349 WOODALE CT | AO | AO \| A |
| 10443024 | (VACANT) | AE | X \| AE |
| 19843013 | 1061 ROBIN WAY | X | X \| A |
| 30322041 | 25 BROOKSIDE AVE | X | X \| D |
| 24406012 | 1641 N CAPITOL AVE | AO | AO \| A |
| 10414160 | LAFAYETTE ST | X | X \| AH \| AO |
| 77933051 | CREEKSIDE CT | AE | X \| AE |
| 52963036 | 300 CREEKSIDE VILLAGE DR | X | X \| AE |
| 70825006 | SANTA TERESA BL | AE | AE \| D |

---

## Full live distribution (62 values)

| fldzone | parcel_count |
|---------|-------------:|
| D | 226,345 |
| X | 218,007 |
| AO | 11,925 |
| AE | 8,150 |
| AH | 6,740 |
| X \| D | 6,123 |
| X \| AE | 2,701 |
| A \| D | 2,415 |
| X \| A | 2,287 |
| X \| AO | 2,125 |
| X \| AH | 2,024 |
| AO \| D | 1,431 |
| AE \| D | 1,261 |
| A | 485 |
| AH \| D | 244 |
| AH \| AO | 241 |
| X \| A \| D | 161 |
| X \| AE \| D | 159 |
| AO \| A | 112 |
| A \| AE | 110 |
| X \| AO \| AE | 110 |
| AO \| AE | 107 |
| X \| AH \| AO | 100 |
| AH \| A | 98 |
| X \| A \| AE | 91 |
| X \| AO \| A | 73 |
| A \| AE \| D | 72 |
| X \| AH \| A | 59 |
| AO \| AE \| D | 54 |
| X \| AO \| D | 53 |
| AH \| AE | 38 |
| AO \| A \| D | 33 |
| AE \| VE | 27 |
| X \| AH \| AE | 26 |
| X \| A \| AE \| D | 19 |
| X \| AO \| AE \| D | 16 |
| AH \| AO \| D | 15 |
| VE | 12 |
| X \| AH \| A \| AE | 12 |
| X \| AH \| D | 10 |
| X \| AO \| A \| AE | 9 |
| AH \| A \| D | 7 |
| A \| AE \| VE | 6 |
| X \| AH \| AO \| A | 6 |
| AH \| AE \| D | 5 |
| AO \| A \| AE \| D | 5 |
| X \| AO \| A \| D | 5 |
| AH \| AO \| A | 4 |
| AH \| A \| AE | 3 |
| X \| AH \| A \| D | 3 |
| X \| AH \| AO \| AE | 3 |
| AH \| A \| AE \| D | 2 |
| AH \| AO \| AE | 2 |
| AO \| A \| AE | 2 |
| X \| A \| AE \| VE \| D | 2 |
| AH \| AO \| A \| D | 1 |
| X \| AH \| A \| AE \| D | 1 |
| X \| AH \| AE \| D | 1 |
| X \| AH \| AO \| A \| D | 1 |
| X \| AH \| AO \| AE \| D | 1 |
| X \| AH \| AO \| D | 1 |
| X \| AO \| A \| AE \| D | 1 |

---

## Acceptance criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Backup table exists with same row count as live | **Pass** |
| 2 | Multi-zone values use ` \| ` between ordered codes | **Pass** (22,478 rows) |
| 3 | `X \| AH` present at expected scale | **Pass** (2,024 rows) |
| 4 | No NULL/blank `fldzone` on live | **Pass** |
| 5 | Backup blank rows resolved | **Pass** (5 → 0 blank) |
| 6 | Positive-area overlap excludes touch-only zones | **Not verified in SQL** — requires GIS spot-check if required for sign-off |

---

## Verdict

**`fldzone` update: approved for team review (SQL verification).**

- **22,482** parcels (4.55%) changed vs `unidata_backup_20260522`.
- Aggregation behavior matches the stated rules: **ordered distinct** codes, **`X | AH` = 2,024**, consistent ` | ` formatting.
- **Open item:** Confirm positive-area vs boundary-touch behavior on a small GIS sample if product/compliance needs geometric proof.

---

## Artifacts

| Artifact | Path |
|----------|------|
| This report | `docs/ticket-04-unidata-fldzone-20260522.md` |
| Live distribution CSV | `docs/ticket-04-unidata-fldzone-20260522-distribution.csv` |
| Backup distribution CSV | `docs/ticket-04-unidata-fldzone-20260522-backup-distribution.csv` |

---

## Team share-out (copy/paste)

**Subject:** Unidata `fldzone` verification — 2026-05-22

Backup: `public.unidata_backup_20260522` (494,142 rows). Live: `public.unidata`.

- **22,482** parcels updated (**4.55%**); **22,478** now have multi-zone `fldzone` (` | ` separated).
- **`X | AH`:** **2,024** parcels; format and order verified on samples.
- Live: **62** distinct `fldzone` values (backup had **8** singles + 5 blanks).
- Format: no NULL/blank on live; all pipes use ` | `.
- Full report: `docs/ticket-04-unidata-fldzone-20260522.md` (+ CSVs in same folder).

**@sinical** — GIS spot-check on positive-area overlap still optional for full sign-off.

---

## Related documents

- [Documentation index](index.md)
- [CONVENTIONS.md](CONVENTIONS.md)
- [release-unidata-v2.3-data-sheet.md](release-unidata-v2.3-data-sheet.md) — prior release baseline (v2.3; pre–fldzone aggregation)
