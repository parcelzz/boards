# Step 5 — External data source / API evaluation (generated)

Generated: **2026-05-08T17:56:35Z**

This file seeds Step 5 using Step 1 review priority. Update it after the Step 4 workshop confirms the **agreed** P0/P1 list.

## Field ↔ source mapping

| Field (P0/P1) | Candidate source | Join key (parcel ID / address / geometry) |
|---|---|---|
| `fhszsra` |  |  |

## Evaluation matrix (use per candidate source)

| Criterion | Notes / score (1–5 or pass/fail) |
|-----------|-----------------------------------|
| **Coverage** (geography & parcel universe) | |
| **Freshness** (update cadence vs product need) | |
| **Cost** (per-call, seat, or bulk license) | |
| **Rate limits** (and batching strategy) | |
| **Join stability** (APN format, city normalization) | |
| **Spatial match quality** (footprint vs parcel polygon) | |
| **Manual QA burden** (spot checks, edge cases) | |
| **Licensing & redistribution** (cache in DB? expose to users?) | |
| **Operational risk** (downtime, key rotation, compliance) | |

## Pilot plan

1. **Sample size:** e.g. 2,000 parcels stratified by `scity` and missingness pattern.
2. **Success metrics:** fill rate uplift, disagreement rate vs current values, latency.
3. **Rollback:** how to revert or flag enriched rows if quality fails.

## Outcome

| Source | Integrate? (Y/N/Maybe) | Conditions | Owner | Target date |
|--------|------------------------|------------|-------|-------------|
| | | | | |
