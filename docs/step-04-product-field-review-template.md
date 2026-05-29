# Step 4 — Product field review (template)

> **Summary:** Workshop template to assign P0–P3 priorities per field, decide MVP “unknown” tolerance, and record product copy/behavior. Use with Step 1–3 outputs.  
> **Updated:** 2026-05-16 · **Author:** Unidata audit team · **Status:** Ready for review

---

## Purpose

Assign **P0 / P1 / P2 / P3** to each field, decide what may remain unknown for the current release, and record trust implications before external enrichment (Step 5).

---

## How to use this template

- One row per field in the checklist below.
- Tie each row to: Step 1 `outputs/missingness_step1/`, Step 2 `outputs/missingness_step2/`, Step 3 `outputs/missingness_step3/semantics_by_column.csv`.
- Optionally pre-fill from generated [step-04-product-field-review.md](step-04-product-field-review.md) (`py -3 tools/workflows/generate_step4_step5.py`).

---

## Priority definitions

| Level | Definition |
|-------|------------|
| **P0** | Product cannot function without reliable values |
| **P1** | Major user experience or decision quality |
| **P2** | Explanation, trust, or enrichment |
| **P3** | Optional for this version |

---

## Checklist per field

| Field | Current suggested priority | Agreed priority | OK if unknown for MVP? (Y/N) | User-facing copy / behavior if unknown | Owner |
|-------|---------------------------|-----------------|------------------------------|----------------------------------------|-------|
| | | | | | |

---

## Cross-cutting questions

1. **MVP required set:** Which fields are mandatory for launch vs “nice to have”?
2. **Workflows:** Which screens or APIs consume each high-priority field?
3. **Trust:** Where does missing data feel like a bug vs an honest “unknown”?
4. **Hazard booleans:** Does the UI distinguish **unknown** (NULL) from **false**? If not, what change is required?
5. **Zeros:** For `sqft`, `building_area`, `fhszsra`, `fhszlra`, `yearbuilt`, does **0** ever mean “we do not know”? Should we migrate to NULL + availability flags?
6. **Post-work:** Update `SUGGESTED_PRIORITY` / copy in code or docs once decisions are final.

---

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| | | |

---

## Related documents

- [Documentation index](index.md)
- [Step 3 — Field semantics](step-03-field-semantics.md)
- [Step 5 — External source evaluation (template)](step-05-external-source-evaluation-template.md)
- [CONVENTIONS.md](CONVENTIONS.md)
