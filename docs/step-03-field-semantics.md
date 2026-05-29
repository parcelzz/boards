# Step 3 — Field semantics audit

> **Summary:** Operator guide for Step 3: measure NULL vs FALSE vs zero vs blank across `public.unidata` before product field review (Step 4). Includes hazard boolean crosstab.  
> **Updated:** 2026-05-16 · **Author:** Unidata audit team · **Status:** Completed

---

## Purpose

Lock down **what stored values mean** before **Step 4**: especially **NULL vs FALSE vs TRUE** on booleans, **NULL vs `0`** on numeric fields Step 1 treats as empty when zero, and **empty arrays / blank text**. Step 2 surfaces zero-semantics hints; Step 3 **measures** them table-wide and adds a **hazard-flag crosstab** (`liquefaction` × `landslide` × `alquist_fault`).

---

## Prerequisites

- PostgreSQL with `public.unidata` populated
- Steps 1–2 recommended (`outputs/missingness_step1/`, `outputs/missingness_step2/`)

---

## How to run

From the repository root:

```bash
py -3 tools/audits/field_semantics_audit_step3.py
```

Optional: `--db-schema`, `--db-table`, `--out-root`.

---

## Outputs (`outputs/missingness_step3/`)

| Artifact | Purpose |
|----------|---------|
| `report.html` | **Primary deliverable:** per-column distribution snapshot + auto “verdict” hooks for Step 4. |
| `semantics_by_column.csv` | Full table: counts/Pcts by type (boolean / numeric / text / array / other). |
| `hazard_boolean_crosstab.csv` | Counts for each **N/T/F** combination (N = NULL). Omitted if any of the three columns is missing. |

---

## How to use results (Step 4 handoff)

1. Sort `semantics_by_column.csv` by `recommended_verdict` (anything not `OK — no auto-flag`) and align with P0/P1 fields from Step 1.
2. For each **boolean** with high `null_pct`, decide: does the product show “unknown” vs “no”?
3. For **`sqft` / `building_area` / `fhszsra` / `fhszlra` / `yearbuilt`**, use `n_zero` and `zero_pct_of_nonnull` to confirm whether **0** is a real value or a sentinel.
4. Use the hazard crosstab for compliance copy and API contracts.

---

## Related documents

- [Documentation index](index.md)
- [Step 2 — Field completeness](step-02-field-completeness.md)
- [Step 4 — Product field review (template)](step-04-product-field-review-template.md)
- [Ticket #3 — Step 3 field semantics](ticket-03-step-3-field-semantics.md)
- [CONVENTIONS.md](CONVENTIONS.md)
