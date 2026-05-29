# Ticket #3 — Step 3 field semantics

> **Summary:** Ticket write-up for building the Step 3 field semantics / literal-value QA report: scope, acceptance criteria, artifacts, and handoff to Step 4.  
> **Updated:** 2026-05-16 · **Author:** Unidata audit team · **Status:** Completed

<!-- Suggested GitHub issue TITLE: Build Field Semantics & Literal-Value QA Report (Step 3) -->

---

## Purpose / background

**Step 1** completed field-level missingness classification and identified taxonomy, baseline missing %, and review priority hints.

**Step 2** completed field completeness and spatial QA: non-null / missing %, lat/lon grid maps, city slices, footprint/sqft proxies, example “bad” rows, and **zero-semantics** notes per field.

The **next phase** turns Step 2’s questions into **measurable literal-level evidence**: how values are actually stored (NULL vs `FALSE` vs `TRUE`, NULL vs numeric `0`, blank strings, empty arrays) and how hazard-related booleans co-occur—so product and engineering can lock semantics before Step 4 prioritization and external enrichment decisions.

---

## Objective

Generate a **field semantics / literal-value QA report** that quantifies **what is in the database**, not only “how much is missing,” and surfaces patterns that distort trust, compliance copy, or downstream logic.

---

## Scope of work

### 1. Field literal & default-value metrics

For **each column** on `public.unidata` (PostgreSQL):

- Compute **type-appropriate** counts (examples):
  - **Boolean:** NULL vs TRUE vs FALSE
  - **Numeric:** NULL vs zero vs negative vs positive (zeros isolated for fields where Step 1 treats `0` as “empty”)
  - **Text:** NULL vs blank (trim) vs non-empty
  - **Arrays:** NULL vs empty cardinality vs non-empty
  - **Other types:** NULL vs non-NULL
- Attach **Step 1 context**: repeat **taxonomy** and **missing_pct** per column so reviewers can compare “Step 1 missing %” with “what literals remain.”
- Emit **heuristic** `recommended_verdict` and `notes_for_step4` for workshop triage (not a substitute for product sign-off).

### 2. Joint pattern analysis (hazard booleans)

Where `liquefaction`, `landslide`, and `alquist_fault` all exist:

- Build a **full crosstab** of stored states using codes **N** (NULL), **T** (TRUE), **F** (FALSE).
- Report **row counts** per combination so teams can see dominance of “all false,” “all unknown,” or mixed patterns.

_**Note:** Step 3 does **not** add new spatial choropleths; geographic QA remains Step 2. Step 3 complements Step 2 with **cross-column literal** patterns._

### 3. Semantic QA review (data vs meaning)

Using Step 2’s “zero semantics” and Step 1 presence rules, validate whether common literals are **semantically valid**:

- **Exact zeros** on `NUMERIC_ZERO_EMPTY` fields (`sqft`, `building_area`, `fhszsra`, `fhszlra`, `yearbuilt`, etc.) — sentinel vs real value?
- **FALSE vs NULL** on hazard and other booleans — is “unknown” incorrectly encoded as FALSE?
- **Empty or placeholder-like text** where missingness should be explicit NULL?

### 4. Product impact assessment

Flag fields where **stored-value ambiguity** is likely to affect:

- User-facing workflows and “unknown” messaging
- Scoring / modeling that treats NULL and 0 differently
- Trust / explainability (especially hazard and regulatory-adjacent fields)
- Search, filter, and API contracts (what clients receive when value is “unset”)

---

## Deliverables

| Deliverable | Location (after run) |
|-------------|----------------------|
| **Semantics QA HTML report** (narrative + tables + Step 1–4 context) | `outputs/missingness_step3/report.html` |
| **Per-column semantics CSV** (counts, %, verdicts, Step 4 notes) | `outputs/missingness_step3/semantics_by_column.csv` |
| **Hazard boolean crosstab CSV** | `outputs/missingness_step3/hazard_boolean_crosstab.csv` |
| **Operator / handoff doc** | `docs/step-03-field-semantics.md` |
| **Ticket writeup / checklist** | `docs/ticket-03-step-3-field-semantics.md` (this file) |

**Implementation:** `tools/audits/field_semantics_audit_step3.py`  

**Run (repo root):**

```bash
python tools/audits/field_semantics_audit_step3.py
```

---

## Expected output

This report will directly support:

- **Step 4:** Product field review (`docs/step-04-product-field-review-template.md`) with P0–P3 and “OK if unknown?” decisions backed by counts
- **Default-value & NULL policy:** when to use NULL vs `0` vs availability flags
- **External enrichment evaluation (Step 5):** which fields need vendor/API backfill vs ingest fix
- **Downstream QA and modeling:** explicit handling of boolean UNKNOWN vs FALSE and numeric sentinels

---

## Risks / notes

- **Heuristic verdicts** in the CSV are triage hints only; legal/product must approve hazard and compliance semantics.
- **Hazard crosstab** is skipped automatically if any of the three columns is absent—confirm schema before interpreting “no file.”
- **High share of zeros** on area/year fields may reflect pipeline defaults, not ground truth—spot-check against county/UI sources.
- **Step 1 “missing” vs Step 3 “zero count”** can look contradictory by design when `0` is treated as missing in Step 1; Step 3 clarifies how many non-NULL zeros exist.
- **No spatial layer in Step 3**—pair this ticket’s outputs with **Step 2** maps for geography × semantics investigations.

---

## Definition of done

- [ ] Script runs successfully against target `public.unidata` (or agreed schema/table).
- [ ] All three artifacts exist under `outputs/missingness_step3/`.
- [ ] HTML report reviewed for readability (stakeholder pass).
- [ ] Step 4 owner has `semantics_by_column.csv` for workshop prep.
- [ ] Follow-up tickets filed for any P0 fields requiring ingest, API, or documentation changes.

---

## Related documents

- [Documentation index](index.md)
- [Step 3 — Field semantics](step-03-field-semantics.md)
- [CONVENTIONS.md](CONVENTIONS.md)
