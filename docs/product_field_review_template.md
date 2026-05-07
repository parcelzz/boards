# Product field review — workshop template (Step 4)

**Meeting goal:** Assign **P0 / P1 / P2 / P3** to each field, decide what may remain unknown for the current release, and record trust implications.

## Priority definitions

| Level | Definition |
|-------|------------|
| **P0** | Product cannot function without reliable values |
| **P1** | Major user experience or decision quality |
| **P2** | Explanation, trust, or enrichment |
| **P3** | Optional for this version |

## Checklist per field

_Use one row per field (tie each row to your latest missingness / QA artifacts — Step 1 CSV/HTML, Step 2 completeness reports, and **Step 3** semantics: `docs/field_semantics_step3.md` / `outputs/missingness_step3/semantics_by_column.csv`)._

| Field | Current suggested priority | Agreed priority | OK if unknown for MVP? (Y/N) | User-facing copy / behavior if unknown | Owner |
|-------|---------------------------|-----------------|------------------------------|----------------------------------------|-------|
| | | | | | |

## Cross-cutting questions

1. **MVP required set:** Which fields are mandatory for launch vs “nice to have”?
2. **Workflows:** Which screens or APIs consume each high-priority field?
3. **Trust:** Where does missing data feel like a bug vs an honest “unknown”?
4. **Hazard booleans:** Does the UI distinguish **unknown** (NULL) from **false**? If not, what change is required?
5. **Zeros:** For `sqft`, `building_area`, `fhszsra`, `fhszlra`, `yearbuilt`, does **0** ever mean “we do not know”? Should we migrate to NULL + availability flags?
6. **Post-work:** Update `SUGGESTED_PRIORITY` / copy in code or docs once decisions are final.

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| | | |
