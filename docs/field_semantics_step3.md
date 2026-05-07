# Step 3 — Field semantics audit

**Step 3** locks down *what stored values mean* before **Step 4** (`docs/product_field_review_template.md`): especially **NULL vs FALSE vs TRUE** on booleans, **NULL vs `0`** on numeric fields that Step 1 treats as “empty” when zero, and **empty arrays / blank text**.

Step 2 already surfaces “zero semantics” hints per field; Step 3 **measures** those distributions table-wide and adds a **hazard-flag crosstab** (`liquefaction` × `landslide` × `alquist_fault`).

## Run

From the repository root (PostgreSQL reachable; same `DEFAULT_DB_CONFIG` pattern as Step 1 / Step 2):

```bash
python tools/audits/field_semantics_audit_step3.py
```

Optional: `--db-schema`, `--db-table`, `--out-root`.

## Outputs (`outputs/missingness_step3/`)

| Artifact | Purpose |
|----------|---------|
| `report.html` | **Primary deliverable:** per-column distribution snapshot + auto “verdict” hooks for Step 4. |
| `semantics_by_column.csv` | Full table: counts/Pcts by type (boolean / numeric / text / array / other). |
| `hazard_boolean_crosstab.csv` | Counts for each **N/T/F** combination (N = NULL). Omitted if any of the three columns is missing. |

## How to use in Step 4

1. Sort `semantics_by_column.csv` by `recommended_verdict` (anything not `OK — no auto-flag`) and align with P0/P1 fields from Step 1.
2. For each **boolean** with high `null_pct`, decide: does the product show “unknown” vs “no”?
3. For **`sqft` / `building_area` / `fhszsra` / `fhszlra` / `yearbuilt`**, use `n_zero` and `zero_pct_of_nonnull` to confirm whether **0** is a real value or a sentinel (matches Step 1’s `NUMERIC_ZERO_EMPTY` rule).
4. Use the hazard crosstab to see whether “all FALSE” patterns dominate vs NULL-heavy patterns — that drives compliance copy and API contracts.

## Related

- Step 1: `tools/audits/field_missingness_classification.py`
- Step 2: `docs/field_completeness_step2.md`
- Step 4 template: `docs/product_field_review_template.md`
