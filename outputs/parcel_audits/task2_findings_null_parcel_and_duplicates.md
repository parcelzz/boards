# Task #2 Findings: NULL Parcel Numbers and Duplicate Parcel/Address Cases

## Scope
- Dataset compared:
  - Source GPKG layer: `ca_santa_clara_parcel_build_opt`
  - Target Postgres table: `public.unidata`
- Focus of this check:
  - Records with NULL/blank parcel number
  - Repeated parcel+address combinations in source data
  - Impact on baseline audit totals

## Key Metrics
- GPKG total rows: `501,656`
- GPKG rows with non-null `parcelnumb`: `494,185`
- GPKG rows with NULL `parcelnumb`: `7,471`
- Unidata total rows: `494,142`
- Distinct normalized city keys in Unidata: `34`

## Duplicate Parcel+Address Examples (GPKG)
Top repeated parcel/address clusters identified in source:

1. `48461052` + `2388 MADDEN AVE` -> `12` rows  
   Interpretation from map review: appears to be adjacent units/parts (multi-geometry/apartment-like), not exact overlap duplicates.
2. `12769002` + `3921 FABIAN WAY` -> `10` rows
3. `16754019` + `4410 EL CAMINO REAL STE 108` -> `9` rows
4. `12769001` + `899 E CHARLESTON RD` -> `8` rows
5. `13241104` + `382 CURTNER AVE UNIT 1` -> `6` rows

## NULL `parcelnumb` Examples (GPKG)
Sample records with NULL parcel number:

- `address=4115 EL CAMINO REAL`, `scity=PALO ALTO`
- `address=425 1ST ST`, `scity=LOS ALTOS`
- `address=CAS DR`, `scity=SAN JOSE`
- `address=962 ACACIA AVE`, `scity=LOS ALTOS`
- `address=(NULL)`, `scity=SAN JOSE`
- `address=389 1ST ST`, `scity=LOS ALTOS`
- `address=14200 MILL ST`, `scity=LOS GATOS`

Initial interpretation aligns with prior review: many NULL-parcel records look like auxiliary/irregular geometries and should not be treated as baseline parcel inventory.

## Baseline Impact Verification
Audit totals before/after excluding NULL `parcelnumb` from GPKG baseline:

- Including NULL `parcelnumb`:
  - `expected_gpkg_rows=501,656`
  - `unidata_rows=494,142`
  - `row_delta=-7,514`
- Excluding NULL `parcelnumb`:
  - `expected_gpkg_rows=494,185`
  - `unidata_rows=494,142`
  - `row_delta=-43`

Change explained by excluding NULL `parcelnumb`: `7,471` rows.

This validates that the large gap is primarily due to NULL parcel-number records in the source baseline.

## Output Artifacts
- Excluding NULL baseline (new default):
  - `outputs/parcel_audits/unidata_v22_vs_gpkg_audit.csv`
  - `outputs/parcel_audits/unidata_v22_vs_gpkg_audit.html`
- Including NULL baseline (comparison run):
  - `outputs/parcel_audits/unidata_v22_vs_gpkg_audit_include_null.csv`
  - `outputs/parcel_audits/unidata_v22_vs_gpkg_audit_include_null.html`

## Takeaways
1. The previous ~7.5k shortfall is largely a baseline-definition issue, not a one-to-one parcel loss in Unidata.
2. Excluding NULL `parcelnumb` brings the gap down to `43`, indicating the dataset is close to expected coverage.
3. Repeated parcel/address cases should be interpreted carefully; at least one investigated case (`48461052`) is structurally valid for apartment/multi-part context.

## Next Steps
1. Keep NULL-`parcelnumb` rows excluded from baseline for board-level coverage metrics.
2. Perform targeted review of the remaining `43` gap (city-level and parcel-level trace).
3. Add 10-20 screenshot-backed NULL-parcel examples into the final documentation appendix for audit traceability.
4. Share updated board numbers and this doc with stakeholders for sign-off.
