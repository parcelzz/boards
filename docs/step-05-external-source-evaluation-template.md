# Step 5 — External source evaluation (template)

> **Summary:** Template to evaluate APIs and bulk sources for filling P0/P1 fields: coverage, cost, join quality, licensing, and pilot plan.  
> **Updated:** 2026-05-16 · **Author:** Unidata audit team · **Status:** Ready for review

---

## Purpose

Document one evaluation per **candidate** source (API, licensed file, or government bulk download), tied to fields marked **P0** or **P1** in the Step 4 product review.

---

## How to use this template

- Complete after Step 4 priorities are drafted.
- Copy sections per candidate source; link outcomes to [step-05-external-source-evaluation.md](step-05-external-source-evaluation.md) when generated.

---

## Field ↔ source mapping

| Field (P0/P1) | Candidate source | Join key (parcel ID / address / geometry) |
|-----------------|------------------|-------------------------------------------|
| | | |

---

## Evaluation matrix

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

---

## Pilot plan

1. **Sample size:** e.g. 2,000 parcels stratified by `scity` and missingness pattern.
2. **Success metrics:** fill rate uplift, disagreement rate vs current values, latency.
3. **Rollback:** how to revert or flag enriched rows if quality fails.

---

## Outcome

| Source | Integrate? (Y/N/Maybe) | Conditions | Owner | Target date |
|--------|------------------------|------------|-------|-------------|
| | | | | |

---

## Related documents

- [Documentation index](index.md)
- [Step 4 — Product field review (template)](step-04-product-field-review-template.md)
- [CONVENTIONS.md](CONVENTIONS.md)
