"""
Task 2: Santa Clara residential baseline vs public.unidata (PostgreSQL).
City key: `scity` only (no fallback to `city`); blank/null → `(NULL)`, then normalized.
Residential baseline: GPKG usecode IN ('1','2','3','4','6'), non-null parcelnumb.
Match: baseline row's trimmed parcelnumb (uppercase) exists in Unidata for same city key.
"""
from __future__ import annotations

import argparse
import csv
import html as html_module
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import psycopg
import sqlite3


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


DEFAULT_DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "parcelz",
    "user": "parcelz",
    "password": "INz3TzaMQIK2RLu0Xu31UTbgYRsq",
}


def normalize_city(value: str | None) -> str:
    if value is None:
        return "(NULL)"
    # Hyphens in source labels (e.g. SAN-JOSE) vs spaced forms in Unidata → same bucket.
    cleaned = " ".join(value.strip().replace("-", " ").split())
    return cleaned.upper() if cleaned else "(EMPTY)"


def normalize_apn(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().upper()


def load_unidata_apns_by_city(db_config: dict, schema: str, table: str) -> Tuple[Dict[str, Set[str]], Counter]:
    """city_key_normalized -> set of normalized APNs; plus row counts per city."""
    conn = psycopg.connect(**db_config)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            CASE
                WHEN NULLIF(TRIM(scity), '') IS NOT NULL THEN TRIM(scity)
                ELSE '(NULL)'
            END AS city_raw,
            parcelnumb
        FROM {schema}.{table}
        """
    )
    by_city: Dict[str, Set[str]] = defaultdict(set)
    for city_raw, parcelnumb in cur.fetchall():
        ck = normalize_city(city_raw)
        apn = normalize_apn(parcelnumb)
        if apn:
            by_city[ck].add(apn)
    cur.execute(
        f"""
        SELECT
            CASE
                WHEN NULLIF(TRIM(scity), '') IS NOT NULL THEN TRIM(scity)
                ELSE '(NULL)'
            END AS city_raw,
            COUNT(*)::bigint
        FROM {schema}.{table}
        GROUP BY 1
        """
    )
    counts = Counter()
    for city_raw, cnt in cur.fetchall():
        counts[normalize_city(city_raw)] += int(cnt)
    conn.close()
    return dict(by_city), counts


def iter_residential_baseline_rows(gpkg_path: Path, layer: str) -> Iterable[Tuple[str, str]]:
    conn = sqlite3.connect(str(gpkg_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            CASE
                WHEN NULLIF(TRIM(scity), '') IS NOT NULL THEN TRIM(scity)
                ELSE '(NULL)'
            END AS city_raw,
            parcelnumb
        FROM {layer}
        WHERE parcelnumb IS NOT NULL
          AND TRIM(CAST(parcelnumb AS TEXT)) <> ''
          AND TRIM(CAST(usecode AS TEXT)) IN ('1','2','3','4','6')
        """
    )
    for row in cur:
        yield row["city_raw"], row["parcelnumb"]
    conn.close()


def field_completeness(conn: psycopg.Connection, schema: str, table: str) -> List[dict]:
    """Rows for completeness matrix (aligned with prior Task 2 semantics where sensible)."""
    q = f"""
    SELECT COUNT(*)::bigint AS total FROM {schema}.{table}
    """
    total = conn.execute(q).fetchone()[0]
    exprs = [
        ("lat", "number", "lat IS NOT NULL"),
        ("lon", "number", "lon IS NOT NULL"),
        ("sqft", "number", "sqft IS NOT NULL AND sqft <> 0"),
        ("building_area", "number", "building_area IS NOT NULL AND building_area <> 0"),
        ("fhszlra", "number", "fhszlra IS NOT NULL"),
        ("fhszsra", "number", "fhszsra IS NOT NULL"),
        ("yearbuilt", "number", "yearbuilt IS NOT NULL"),
        ("address", "text", "address IS NOT NULL AND TRIM(address::text) <> ''"),
        ("zoning", "text", "zoning IS NOT NULL AND TRIM(zoning::text) <> ''"),
        ("city", "text", "city IS NOT NULL AND TRIM(city::text) <> ''"),
        ("scity", "text", "scity IS NOT NULL AND TRIM(scity::text) <> ''"),
        ("parcel", "text", "parcel IS NOT NULL AND TRIM(parcel::text) <> ''"),
        ("parcelnumb", "text", "parcelnumb IS NOT NULL AND TRIM(parcelnumb::text) <> ''"),
        ("fldzone", "text", "fldzone IS NOT NULL AND TRIM(fldzone::text) <> ''"),
        ("footprints", "text", "footprints IS NOT NULL AND cardinality(footprints) > 0"),
        ("alquist_fault", "boolean", "alquist_fault IS NOT NULL"),
        ("liquefaction", "boolean", "liquefaction IS NOT NULL"),
        ("landslide", "boolean", "landslide IS NOT NULL"),
        ("ready", "boolean", "ready IS NOT NULL"),
        ("h3", "text", "h3 IS NOT NULL AND TRIM(h3::text) <> ''"),
        ("id", "number", "id IS NOT NULL"),
        ("created_at", "timestamp", "created_at IS NOT NULL"),
        ("updated_at", "timestamp", "updated_at IS NOT NULL"),
    ]
    out: List[dict] = []
    for field_name, field_type, cond in exprs:
        sql = f"SELECT COUNT(*)::bigint FROM {schema}.{table} WHERE {cond}"
        present = conn.execute(sql).fetchone()[0]
        pct = round((present / total) * 100.0, 2) if total else 0.0
        out.append(
            {
                "field": field_name,
                "field_type": field_type,
                "present": int(present),
                "total": int(total),
                "completeness_pct": pct,
            }
        )
    out.sort(key=lambda r: (r["completeness_pct"], r["field"]))
    return out


def _pct_part(n: int, total: int) -> float:
    return round((n / total) * 100.0, 2) if total else 0.0


SCITY_NORM_SQL = """
    CASE
        WHEN NULLIF(TRIM(scity), '') IS NOT NULL THEN UPPER(TRIM(REGEXP_REPLACE(REPLACE(TRIM(scity), '-', ' '), '\\s+', ' ', 'g')))
        ELSE '(NULL)'
    END
"""


def field_coverage_by_scity_all(conn: psycopg.Connection, schema: str, table: str) -> List[tuple[str, dict]]:
    """One grouped query: field completeness per normalized scity (same rules as legacy per-city counts)."""
    q = f"""
    SELECT
        {SCITY_NORM_SQL} AS scity_norm,
        COUNT(*)::bigint AS total,
        SUM(CASE WHEN yearbuilt IS NOT NULL THEN 1 ELSE 0 END)::bigint AS n_yearbuilt,
        SUM(CASE WHEN address IS NOT NULL AND TRIM(address::text) <> '' THEN 1 ELSE 0 END)::bigint AS n_address,
        SUM(CASE WHEN fldzone IS NOT NULL AND TRIM(fldzone::text) <> '' THEN 1 ELSE 0 END)::bigint AS n_fldzone,
        SUM(CASE WHEN zoning IS NOT NULL AND TRIM(zoning::text) <> '' THEN 1 ELSE 0 END)::bigint AS n_zoning,
        SUM(CASE WHEN building_area IS NOT NULL AND building_area <> 0 THEN 1 ELSE 0 END)::bigint AS n_ba,
        SUM(CASE WHEN sqft IS NOT NULL AND sqft <> 0 THEN 1 ELSE 0 END)::bigint AS n_sqft,
        SUM(CASE WHEN lat IS NOT NULL THEN 1 ELSE 0 END)::bigint AS n_lat,
        SUM(CASE WHEN lon IS NOT NULL THEN 1 ELSE 0 END)::bigint AS n_lon,
        SUM(CASE WHEN liquefaction IS NOT NULL AND landslide IS NOT NULL AND alquist_fault IS NOT NULL THEN 1 ELSE 0 END)::bigint AS n_hazard,
        SUM(CASE WHEN footprints IS NOT NULL AND cardinality(footprints) > 0 THEN 1 ELSE 0 END)::bigint AS n_fp
    FROM {schema}.{table}
    GROUP BY 1
    ORDER BY total DESC
    """
    rows = conn.execute(q).fetchall()
    out: List[tuple[str, dict]] = []
    for row in rows:
        sn, total = row[0], int(row[1])
        if total <= 0:
            continue
        stats = {
            "_total": total,
            "yearbuilt": _pct_part(int(row[2]), total),
            "address": _pct_part(int(row[3]), total),
            "fldzone": _pct_part(int(row[4]), total),
            "zoning": _pct_part(int(row[5]), total),
            "building_area": _pct_part(int(row[6]), total),
            "sqft": _pct_part(int(row[7]), total),
            "lat": _pct_part(int(row[8]), total),
            "lon": _pct_part(int(row[9]), total),
            "hazard_all": _pct_part(int(row[10]), total),
            "footprints_nonempty": _pct_part(int(row[11]), total),
        }
        out.append((sn, stats))
    return out


def fmt_int(n: int) -> str:
    return f"{n:,}"


def pct_str(p: float) -> str:
    return f"{p:.2f}%"


def esc(s: object) -> str:
    return html_module.escape(str(s), quote=True)


def coverage_row_class(cov_pct: float, baseline_rows: int) -> str:
    if baseline_rows <= 0:
        return "cov-na"
    if cov_pct >= 99.0:
        return "cov-excellent"
    if cov_pct >= 95.0:
        return "cov-good"
    if cov_pct >= 80.0:
        return "cov-warn"
    return "cov-risk"


def completeness_class(pct_val: float) -> str:
    if pct_val >= 99.0:
        return "comp-excellent"
    if pct_val >= 95.0:
        return "comp-good"
    if pct_val >= 85.0:
        return "comp-warn"
    if pct_val >= 70.0:
        return "comp-risk"
    return "comp-bad"


# Stakeholder narrative blocks (shared semantics HTML ↔ Markdown)
ROOT_CAUSE_ITEMS: List[tuple[str, str]] = [
    (
        "Missing or incomplete upstream data",
        "Some parcels never receive attributes from upstream systems. That appears as unmatched baseline rows or thin columns in Unidata.",
    ),
    (
        "`scity` labeling mismatch",
        "Grouping uses **`scity` only** (no fallback to `city`). Different spelling, hyphens, blanks, or legacy labels between GPKG and Unidata block matches even when an APN exists in the database.",
    ),
    (
        "Multiple sources without merge priority",
        "Conflicting values across feeds (e.g. living area, zoning text) can produce errors, stale fields, or blanks unless a documented source-of-truth order exists.",
    ),
    (
        "Schema vs product expectations",
        "Attributes such as General Plan, historic status, or setbacks may not exist on `public.unidata`; they cannot be measured here until modeled or joined from another table.",
    ),
    (
        "Pipeline defaults and weak validation",
        "Zeros or empty strings used as placeholders, or uncaught parse failures, distort completeness and user-facing “not available” rates.",
    ),
    (
        "Naturally sparse fields",
        "Some columns are legitimately absent for many parcels (e.g. specialized hazard scores). Low completeness is not always a defect.",
    ),
]

RECOMMENDED_ACTION_ITEMS: List[str] = [
    "Publish and enforce a **`scity` normalization map** (including hyphenated and legacy labels) shared by ingest and the county baseline.",
    "Use **Table 1** for geographic prioritization and **Table 4** for the worst residual baseline gaps; drill into APN samples there first.",
    "Use **Table 2** and **Table 5** to drive backfills for columns that matter most to product or compliance.",
    "Establish a **documented merge policy** (ordered sources, tie-break rules, audit logging).",
    "Treat **`0` area fields as unknown** unless business rules say otherwise; validate ranges at ingest.",
    "Add **joins or new columns** for attributes required by the app but not stored on `unidata`.",
    "Refresh this report **after each major Unidata release** so stakeholders compare apples-to-apples.",
]


def _glossary_table_rows_html(rows: List[tuple[str, str]]) -> str:
    parts: List[str] = []
    for col, desc in rows:
        parts.append(f"<tr><th scope='row'>{esc(col)}</th><td>{esc(desc)}</td></tr>")
    return "".join(parts)


def write_task2_html(
    path: Path,
    *,
    title: str,
    generated_iso: str,
    generated_display: str,
    gpkg_name: str,
    schema: str,
    table: str,
    overall_cov: float,
    grand_base: int,
    grand_matched: int,
    grand_miss: int,
    coverage_rows: List[dict],
    completeness: List[dict],
    weakest: List[dict],
    missing_by_city: List[tuple],
    city_highlight_data: List[tuple[str, dict]],
) -> None:
    """Professional multi-color HTML report (opens standalone in any browser)."""

    kpi_cov_cls = "kpi-accent-green" if overall_cov >= 99 else "kpi-accent-amber"
    w0 = weakest[0] if weakest else None
    weakest_label = f"{w0['field']} ({w0['completeness_pct']:.2f}%)" if w0 else "n/a"
    n_scity_cards = len(city_highlight_data)

    coverage_body: List[str] = []
    for r in coverage_rows:
        bl = int(r["baseline_residential_rows"])
        cov = float(r["coverage_pct"])
        ccls = coverage_row_class(cov, bl)
        miss = int(r["missing"])
        miss_cls = "miss-zero" if miss == 0 else "miss-positive"
        coverage_body.append(
            "<tr>"
            f'<td class="city-cell">{esc(r["city"])}</td>'
            f'<td class="num">{esc(fmt_int(bl))}</td>'
            f'<td class="num">{esc(fmt_int(r["unidata_rows_scity"]))}</td>'
            f'<td class="num">{esc(fmt_int(r["matched_baseline_apn"]))}</td>'
            f'<td class="num {miss_cls}">{esc(fmt_int(miss))}</td>'
            f'<td class="num pct-cell {ccls}">{esc(f"{cov:.2f}%")}</td>'
            "</tr>"
        )

    comp_sorted = sorted(completeness, key=lambda x: x["field"])
    comp_rows: List[str] = []
    for r in comp_sorted:
        p = float(r["completeness_pct"])
        cc = completeness_class(p)
        comp_rows.append(
            "<tr>"
            f'<td><code>{esc(r["field"])}</code></td>'
            f'<td><span class="type-badge">{esc(r["field_type"])}</span></td>'
            f'<td class="num">{esc(fmt_int(r["present"]))}</td>'
            f'<td class="num muted">{esc(fmt_int(r["total"]))}</td>'
            f'<td class="num pct-cell {cc}"><strong>{esc(f"{p:.2f}%")}</strong></td>'
            "</tr>"
        )

    weakest_rows: List[str] = []
    for r in weakest:
        p = float(r["completeness_pct"])
        cc = completeness_class(p)
        weakest_rows.append(
            "<tr>"
            f'<td><code>{esc(r["field"])}</code></td>'
            f'<td>{esc(r["field_type"])}</td>'
            f'<td class="num">{esc(fmt_int(r["present"]))}</td>'
            f'<td class="num">{esc(fmt_int(r["total"]))}</td>'
            f'<td class="num pct-cell {cc}">{esc(f"{p:.2f}%")}</td>'
            "</tr>"
        )

    gap_rows: List[str] = []
    for c, miss, cov in missing_by_city[:12]:
        gap_rows.append(
            "<tr>"
            f'<td class="city-cell">{esc(c)}</td>'
            f'<td class="num miss-positive">{esc(fmt_int(miss))}</td>'
            f'<td class="num cov-risk">{esc(f"{cov:.2f}%")}</td>'
            "</tr>"
        )

    city_cards: List[str] = []
    attr_specs = [
        ("yearbuilt", "Year built"),
        ("address", "Address"),
        ("fldzone", "Flood zone (fldzone)"),
        ("hazard_all", "Hazard flags (all non-null)"),
        ("building_area", "Main house area (≠ 0)"),
        ("sqft", "Size / sqft (≠ 0)"),
        ("zoning", "Zoning"),
        ("lat", "Latitude"),
        ("lon", "Longitude"),
        ("footprints_nonempty", "Footprints non-empty"),
    ]
    palette = ["card-teal", "card-indigo", "card-slate", "card-violet", "card-amber", "card-rose", "card-cyan"]
    for idx, (cn, stats) in enumerate(city_highlight_data):
        card_cls = palette[idx % len(palette)]
        rows_mini = []
        for key, label in attr_specs:
            if key not in stats:
                continue
            p = float(stats[key])
            cc = completeness_class(p)
            rows_mini.append(
                f"<tr><td>{esc(label)}</td>"
                f'<td class="num pct-cell {cc}"><strong>{esc(f"{p:.2f}%")}</strong></td></tr>'
            )
        city_cards.append(
            f"""
            <article class="city-card {card_cls}" data-scity="{esc(cn)}">
              <header><h3>{esc(cn.title())}</h3>
              <p class="city-meta">{esc(fmt_int(stats["_total"]))} Unidata rows · normalized <code>scity</code></p></header>
              <table class="mini-table"><tbody>{"".join(rows_mini)}</tbody></table>
            </article>
            """
        )

    summary_html = f"""
    <section class="panel" id="executive-summary">
      <div class="panel-head"><h2>Executive summary</h2><p>What leadership needs to know before scrolling the tables.</p></div>
      <div class="panel-body prose">
        <ul>
          <li><strong>Residential coverage:</strong> {esc(f"{overall_cov}%")} of county residential baseline parcels ({esc(fmt_int(grand_matched))} of {esc(fmt_int(grand_base))}) appear in PostgreSQL <code>{esc(schema)}.{esc(table)}</code> when both sides share the same normalized <code>scity</code> and parcel number (<code>parcelnumb</code>, trimmed and case-normalized).</li>
          <li><strong>Unmatched baseline:</strong> {esc(fmt_int(grand_miss))} residential baseline rows still lack that combined match—often <code>scity</code> label drift or missing ingest rows rather than literal absence of the parcel everywhere.</li>
          <li><strong>Where we measure attributes:</strong> The cards in Table 3 summarize one row count per normalized <code>scity</code> present in Unidata—<strong>{esc(n_scity_cards)}</strong> buckets in this snapshot.</li>
          <li><strong>Soft spots in the schema:</strong> The weakest populated column overall right now is <strong>{esc(weakest_label)}</strong> (see Table 5 for more).</li>
        </ul>
        <p>The KPI tiles directly above mirror these bullets; the <strong>How to read each table</strong> section next defines every column.</p>
      </div>
    </section>
    """

    readers_guide_html = f"""
    <section class="panel" id="readers-guide">
      <div class="panel-head"><h2>How to read each table</h2><p>Short definitions so finance, product, and GIS readers interpret numbers the same way.</p></div>
      <div class="panel-body prose">
        <h3>Snapshot tiles (under the blue header)</h3>
        <table class="data guide-table"><tbody>
          {_glossary_table_rows_html([
              ("Residential coverage", "Matched baseline rows ÷ total residential baseline rows. Uses only **`scity` + `parcelnumb`** matches."),
              ("Baseline rows", "Residential parcels in the county GeoPackage baseline (`usecode` 1,2,3,4,6) with a usable parcel number."),
              ("Matched in Unidata", "Baseline rows that found a partner row in Unidata with the same normalized `scity` and parcel number."),
              ("Missing", "Baseline rows that did not find such a partner."),
          ])}
        </tbody></table>

        <h3>Table 1 — Coverage by <code>scity</code></h3>
        <table class="data guide-table"><tbody>
          {_glossary_table_rows_html([
              ("Place (scity)", "Normalized situs city label for the row. Taken from **`scity` only** (blank → “(NULL)”); hyphens become spaces; spacing and case normalized."),
              ("Baseline rows", "Residential parcels in the GeoPackage for this `scity` key."),
              ("Unidata rows (scity)", "All Unidata rows carrying this normalized `scity` (not limited to residential unless you filter separately)."),
              ("Matched", "Baseline residential rows whose parcel number appears in Unidata under the **same** normalized `scity`."),
              ("Missing", "Baseline residential rows in this bucket without such a match."),
              ("Coverage %", "Matched ÷ Baseline rows when baseline &gt; 0. Gray styling means zero baseline residential rows (nothing to score)."),
          ])}
        </tbody></table>

        <h3>Table 2 — Field completeness matrix</h3>
        <table class="data guide-table"><tbody>
          {_glossary_table_rows_html([
              ("Field", "Column name on `unidata`."),
              ("Type", "How we evaluate presence (text vs numeric vs boolean vs array)."),
              ("Present", "Rows that satisfy the “populated” rule for that field."),
              ("Total", "All rows in `unidata` for this export."),
              ("Completeness %", "Present ÷ Total. Colors highlight excellent → weak tiers."),
          ])}
        </tbody></table>
        <p class="footnote"><code>sqft</code> and <code>building_area</code> treat <strong>0</strong> as missing. <code>footprints</code> must be a non-empty PostgreSQL array.</p>

        <h3>Table 3 — Field-level coverage cards</h3>
        <table class="data guide-table"><tbody>
          {_glossary_table_rows_html([
              ("Each card title", "One normalized `scity` bucket found in Unidata."),
              ("Row count line", "How many Unidata rows belong to that bucket."),
              ("Attribute rows", "Completeness inside <strong>that bucket only</strong>—percent of rows with usable values."),
              ("Hazard flags", "Share of rows where liquefaction, landslide, and Alquist fault columns are all non-null."),
              ("Footprints non-empty", "Share where the footprint geometry array has at least one entry."),
          ])}
        </tbody></table>

        <h3>Table 4 — Top gaps (missing baseline)</h3>
        <table class="data guide-table"><tbody>
          {_glossary_table_rows_html([
              ("scity", "Buckets with the largest counts of unmatched baseline residential parcels."),
              ("Missing", "How many baseline residential rows still lack a Unidata partner."),
              ("Coverage %", "Matched ÷ baseline residential rows for that bucket—low values highlight remediation priorities."),
          ])}
        </tbody></table>

        <h3>Table 5 — Weakest fields</h3>
        <table class="data guide-table"><tbody>
          {_glossary_table_rows_html([
              ("Purpose", "Prioritize engineering + data vendor follow-up."),
              ("Columns", "Same meaning as Table 2 but sorted so the lowest completeness fields appear first."),
          ])}
        </tbody></table>
      </div>
    </section>
    """

    analysis_html = f"""
    <p class="footer-tech">Technical note (analysts): regenerate figures by running <code>task2_residential_audit.py</code> after PostgreSQL or GeoPackage refreshes.</p>
    """

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #eceef4;
      --surface: #ffffff;
      --text: #1c2434;
      --muted: #5c6578;
      --border: #d8dee9;
      --hero-from: #1e3a5f;
      --hero-to: #2d5a87;
      --accent: #0d9488;
      --accent2: #6366f1;
      --rose: #e11d48;
      --amber: #d97706;
      --green: #059669;
      --cyan: #0891b2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
      background: linear-gradient(165deg, #e8ecf6 0%, var(--bg) 45%, #dfe8f3 100%);
      color: var(--text);
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 28px 20px 48px; }}
    .hero {{
      background: linear-gradient(135deg, var(--hero-from) 0%, var(--hero-to) 55%, #3b7ab8 100%);
      color: #fff;
      border-radius: 16px;
      padding: 28px 32px;
      box-shadow: 0 18px 40px rgba(30, 58, 95, 0.35);
      margin-bottom: 22px;
    }}
    .hero h1 {{ margin: 0 0 10px; font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em; }}
    .hero .sub {{ opacity: 0.92; font-size: 0.95rem; margin: 0 0 16px; max-width: 820px; }}
    .hero time {{ font-weight: 600; opacity: 1; }}
    .legend {{
      display: flex; flex-wrap: wrap; gap: 10px 18px; margin-top: 18px;
      padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.22); font-size: 0.82rem;
    }}
    .legend span {{ display: inline-flex; align-items: center; gap: 8px; }}
    .dot {{ width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }}
    .dot-ex {{ background: #34d399; }}
    .dot-gd {{ background: #a3e635; }}
    .dot-wn {{ background: #fbbf24; }}
    .dot-rk {{ background: #fb923c; }}
    .dot-bd {{ background: #f87171; }}
    .dot-na {{ background: #94a3b8; }}

    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
      margin-bottom: 22px;
    }}
    .kpi {{
      background: var(--surface);
      border-radius: 14px;
      padding: 18px 20px;
      border: 1px solid var(--border);
      box-shadow: 0 4px 14px rgba(28, 36, 52, 0.06);
    }}
    .kpi-label {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 8px; }}
    .kpi-value {{ font-size: 1.85rem; font-weight: 800; letter-spacing: -0.03em; color: var(--hero-from); }}
    .kpi-accent-green .kpi-value {{ color: var(--green); }}
    .kpi-accent-amber .kpi-value {{ color: var(--amber); }}
    .kpi-note {{ font-size: 0.8rem; color: var(--muted); margin-top: 6px; }}

    section.panel {{
      background: var(--surface);
      border-radius: 14px;
      border: 1px solid var(--border);
      margin-bottom: 20px;
      box-shadow: 0 4px 18px rgba(28, 36, 52, 0.06);
      overflow: hidden;
    }}
    .panel-head {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(90deg, #f8fafc 0%, #f1f5f9 100%);
    }}
    .panel-head h2 {{ margin: 0; font-size: 1.08rem; color: var(--hero-from); }}
    .panel-head p {{ margin: 8px 0 0; font-size: 0.88rem; color: var(--muted); }}
    .panel-body {{ padding: 16px 20px 20px; }}

    .toolbar {{ margin-bottom: 12px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
    .toolbar input {{
      padding: 10px 14px; border: 1px solid var(--border); border-radius: 10px;
      min-width: 260px; font-size: 0.9rem;
    }}
    .toolbar input:focus {{ outline: 2px solid rgba(99, 102, 241, 0.35); border-color: var(--accent2); }}

    .table-scroll {{ overflow: auto; max-height: 62vh; border-radius: 10px; border: 1px solid var(--border); }}
    table.data {{ width: 100%; border-collapse: collapse; font-size: 0.86rem; min-width: 720px; }}
    .data th {{
      position: sticky; top: 0;
      background: linear-gradient(180deg, #334155 0%, #1e293b 100%);
      color: #f8fafc;
      text-align: right;
      padding: 11px 12px;
      font-weight: 600;
      white-space: nowrap;
      z-index: 1;
    }}
    .data th:first-child {{ text-align: left; }}
    .data td {{ padding: 10px 12px; border-bottom: 1px solid #eef2f7; text-align: right; vertical-align: middle; }}
    .data td:first-child {{ text-align: left; }}
    .data tbody tr:nth-child(even) td {{ background: #fafbfd; }}
    .data tbody tr:hover td {{ background: #eef6ff; }}
    .city-cell {{ font-weight: 600; color: #0f172a; }}
    .num {{ font-variant-numeric: tabular-nums; }}
    .muted {{ color: var(--muted); }}

    .cov-excellent {{ background: #d1fae5 !important; color: #065f46; font-weight: 700; }}
    .cov-good {{ background: #ecfccb !important; color: #3f6212; font-weight: 600; }}
    .cov-warn {{ background: #fef3c7 !important; color: #92400e; }}
    .cov-risk {{ background: #fee2e2 !important; color: #991b1b; font-weight: 700; }}
    .cov-na {{ background: #f1f5f9 !important; color: #64748b; }}

    .comp-excellent {{ background: #d1fae5 !important; color: #065f46; }}
    .comp-good {{ background: #e0f2fe !important; color: #0369a1; }}
    .comp-warn {{ background: #fef9c3 !important; color: #854d0e; }}
    .comp-risk {{ background: #ffedd5 !important; color: #9a3412; }}
    .comp-bad {{ background: #ffe4e6 !important; color: #9f1239; }}

    .miss-zero {{ color: var(--muted); }}
    .miss-positive {{ color: var(--rose); font-weight: 700; }}

    .type-badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 6px;
      font-size: 0.75rem;
      background: #e0e7ff;
      color: #3730a3;
    }}

    .city-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      max-height: 78vh;
      overflow-y: auto;
      padding: 4px 8px 12px 2px;
    }}
    .city-card {{
      border-radius: 14px;
      padding: 18px;
      border: 1px solid var(--border);
      box-shadow: 0 4px 12px rgba(28, 36, 52, 0.05);
    }}
    .city-card header h3 {{ margin: 0 0 6px; font-size: 1.05rem; }}
    .city-meta {{ margin: 0; font-size: 0.82rem; color: var(--muted); }}
    .mini-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-top: 12px; }}
    .mini-table td {{ padding: 6px 0; border-bottom: 1px solid rgba(0,0,0,0.06); }}
    .mini-table td:last-child {{ text-align: right; width: 88px; }}
    .card-teal {{ border-left: 5px solid #0d9488; background: linear-gradient(135deg, #f0fdfa 0%, #fff 50%); }}
    .card-indigo {{ border-left: 5px solid #4f46e5; background: linear-gradient(135deg, #eef2ff 0%, #fff 50%); }}
    .card-slate {{ border-left: 5px solid #475569; background: linear-gradient(135deg, #f8fafc 0%, #fff 50%); }}
    .card-violet {{ border-left: 5px solid #7c3aed; background: linear-gradient(135deg, #f5f3ff 0%, #fff 50%); }}
    .card-amber {{ border-left: 5px solid #d97706; background: linear-gradient(135deg, #fffbeb 0%, #fff 50%); }}
    .card-rose {{ border-left: 5px solid #e11d48; background: linear-gradient(135deg, #fff1f2 0%, #fff 50%); }}
    .card-cyan {{ border-left: 5px solid #0891b2; background: linear-gradient(135deg, #ecfeff 0%, #fff 50%); }}

    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    @media (max-width: 900px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

    .footnote {{ font-size: 0.82rem; color: var(--muted); margin-top: 12px; line-height: 1.45; }}
    .panel-body.prose ul, .panel-body.prose ol {{ margin: 0.4rem 0 0; padding-left: 1.35rem; }}
    .panel-body.prose li {{ margin: 0.55rem 0; line-height: 1.5; }}
    .panel-body.prose h3 {{ font-size: 1rem; color: var(--hero-from); margin: 1.35rem 0 0.65rem; }}
    .panel-body.prose h3:first-child {{ margin-top: 0; }}
    .panel-body.prose p {{ margin: 0.45rem 0; max-width: 900px; }}
    .tight-list {{ list-style: disc; }}
    /* Glossary tables use class "data guide-table" — must override .data th (white on slate) or labels are invisible */
    table.data.guide-table th {{
      position: static;
      top: auto;
      z-index: auto;
      width: 28%;
      text-align: left;
      vertical-align: top;
      cursor: default;
      white-space: normal;
      padding: 12px 14px;
      font-weight: 700;
      color: #0f172a !important;
      background: #dbeafe !important;
      border-bottom: 1px solid #93c5fd;
    }}
    table.data.guide-table th code {{
      color: #1e3a8a;
      background: rgba(255, 255, 255, 0.85);
      padding: 1px 5px;
      border-radius: 4px;
      font-weight: 600;
    }}
    table.data.guide-table td {{
      text-align: left;
      white-space: normal;
      line-height: 1.5;
      border-bottom: 1px solid var(--border);
      color: #1e293b !important;
      background: #ffffff !important;
    }}
    table.data.guide-table tbody tr:nth-child(even) td {{
      background: #f8fafc !important;
    }}
    .ol-actions li {{ margin: 0.55rem 0; }}
    .footer-tech {{
      text-align: center; font-size: 0.82rem; color: var(--muted); margin-top: 10px;
      padding: 18px 12px 0; border-top: 1px solid var(--border); max-width: 1280px; margin-left: auto; margin-right: auto;
    }}
    .footer-tech code {{ background: #e2e8f0; padding: 2px 7px; border-radius: 4px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1>{esc(title)}</h1>
      <p class="sub">Residential baseline (<code style="background:rgba(0,0,0,.2);padding:2px 8px;border-radius:6px;">usecode</code> 1,2,3,4,6) from <strong>{esc(gpkg_name)}</strong>
      compared to PostgreSQL <strong>{esc(f"{schema}.{table}")}</strong>. City grouping uses normalized <code style="background:rgba(0,0,0,.2);padding:2px 8px;border-radius:6px;">scity</code> only (no <code>city</code> fallback), with hyphen normalization.</p>
      <p class="sub">Generated <time datetime="{esc(generated_iso)}">{esc(generated_display)}</time></p>
      <div class="legend">
        <span><i class="dot dot-ex"></i> Coverage ≥99%</span>
        <span><i class="dot dot-gd"></i> 95–99%</span>
        <span><i class="dot dot-wn"></i> 80–95%</span>
        <span><i class="dot dot-bd"></i> &lt;80%</span>
        <span><i class="dot dot-na"></i> No baseline rows</span>
      </div>
    </header>

    <div class="kpis">
      <div class="kpi {kpi_cov_cls}">
        <div class="kpi-label">Residential coverage</div>
        <div class="kpi-value">{esc(f"{overall_cov}%")}</div>
        <div class="kpi-note">Matched ÷ baseline rows</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Baseline rows</div>
        <div class="kpi-value">{esc(fmt_int(grand_base))}</div>
        <div class="kpi-note">Residential + valid APN</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Matched in Unidata</div>
        <div class="kpi-value" style="color:var(--accent)">{esc(fmt_int(grand_matched))}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Missing</div>
        <div class="kpi-value" style="color:var(--rose)">{esc(fmt_int(grand_miss))}</div>
      </div>
    </div>

    {summary_html}
    {readers_guide_html}

    <section class="panel">
      <div class="panel-head">
        <h2>1. Coverage by <code style="font-size:inherit;">scity</code></h2>
        <p>Filter the table; colored cells highlight coverage strength. “Missing” counts baseline residential rows with no matching APN in Unidata for that normalized <code>scity</code>.</p>
      </div>
      <div class="panel-body">
        <div class="toolbar">
          <label for="filterCity"><strong>Filter <code>scity</code>:</strong></label>
          <input type="search" id="filterCity" placeholder="Type to filter (e.g. SAN JOSE)" autocomplete="off" />
        </div>
        <div class="table-scroll">
          <table class="data" id="tblCoverage">
            <thead>
              <tr>
                <th>Place (<code>scity</code>)</th>
                <th>Baseline rows</th>
                <th>Unidata rows (<code>scity</code>)</th>
                <th>Matched</th>
                <th>Missing</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>{"".join(coverage_body)}</tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>2. Field completeness matrix</h2>
        <p>Share of all Unidata rows with a usable value. Row colors reflect completeness tier.</p>
      </div>
      <div class="panel-body">
        <div class="table-scroll" style="max-height: 55vh;">
          <table class="data" style="min-width: 580px;">
            <thead>
              <tr>
                <th>Field</th>
                <th>Type</th>
                <th>Present</th>
                <th>Total</th>
                <th>Completeness</th>
              </tr>
            </thead>
            <tbody>{"".join(comp_rows)}</tbody>
          </table>
        </div>
        <p class="footnote"><code>sqft</code> / <code>building_area</code>: zero treated as missing. <code>footprints</code>: non-empty array required.</p>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>3. Field-level coverage by <code style="font-size:inherit;">scity</code></h2>
        <p><strong>{esc(n_scity_cards)}</strong> distinct normalized <code>scity</code> buckets (every value present in Unidata). Completeness is computed within rows for each bucket. Height / General Plan / setback columns are not on this schema.</p>
      </div>
      <div class="panel-body">
        <div class="toolbar">
          <label for="filterScityCards"><strong>Filter cards:</strong></label>
          <input type="search" id="filterScityCards" placeholder="Filter by scity name…" autocomplete="off" />
        </div>
        <div class="city-grid" id="scityCardGrid">{"".join(city_cards)}</div>
      </div>
    </section>

    <div class="two-col">
      <section class="panel">
        <div class="panel-head">
          <h2>4. Top gaps (missing baseline)</h2>
          <p><code>scity</code> buckets with the largest residential baseline shortfall.</p>
        </div>
        <div class="panel-body">
          <div class="table-scroll" style="max-height: 320px;">
            <table class="data" style="min-width: 400px;">
              <thead><tr><th><code>scity</code></th><th>Missing</th><th>Coverage</th></tr></thead>
              <tbody>{"".join(gap_rows)}</tbody>
            </table>
          </div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head">
          <h2>5. Weakest fields</h2>
          <p>Lowest completeness (snapshot).</p>
        </div>
        <div class="panel-body">
          <div class="table-scroll" style="max-height: 320px;">
            <table class="data" style="min-width: 440px;">
              <thead><tr><th>Field</th><th>Type</th><th>Present</th><th>Total</th><th>%</th></tr></thead>
              <tbody>{"".join(weakest_rows)}</tbody>
            </table>
          </div>
        </div>
      </section>
    </div>

    {analysis_html}
  </div>
  <script>
    document.getElementById("filterCity").addEventListener("input", function () {{
      var q = this.value.toLowerCase();
      var rows = document.querySelectorAll("#tblCoverage tbody tr");
      for (var i = 0; i < rows.length; i++) {{
        var cell = rows[i].cells[0];
        rows[i].style.display = cell && cell.textContent.toLowerCase().indexOf(q) >= 0 ? "" : "none";
      }}
    }});
    var scityFilter = document.getElementById("filterScityCards");
    if (scityFilter) {{
      scityFilter.addEventListener("input", function () {{
        var q = this.value.toLowerCase();
        var cards = document.querySelectorAll("#scityCardGrid article.city-card");
        for (var i = 0; i < cards.length; i++) {{
          var key = (cards[i].getAttribute("data-scity") || "").toLowerCase();
          var title = cards[i].querySelector("h3");
          var tit = title ? title.textContent.toLowerCase() : "";
          var hit = key.indexOf(q) >= 0 || tit.indexOf(q) >= 0;
          cards[i].style.display = hit ? "" : "none";
        }}
      }});
    }}
  </script>
</body>
</html>
"""
    path.write_text(html_doc, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Task 2 residential audit vs Postgres unidata.")
    p.add_argument(
        "--gpkg-path",
        default=str(_repo_root() / "data" / "ca_santa_clara_parcel_build_opt.gpkg"),
    )
    p.add_argument("--gpkg-layer", default="ca_santa_clara_parcel_build_opt")
    p.add_argument("--db-schema", default="public")
    p.add_argument("--db-table", default="unidata")
    p.add_argument(
        "--out-md",
        default=str(_repo_root() / "outputs" / "parcel_audits" / "task2_santa_clara_residential_audit_updated.md"),
    )
    p.add_argument(
        "--out-csv-coverage",
        default=str(_repo_root() / "outputs" / "parcel_audits" / "task2_residential_coverage_by_city.csv"),
    )
    p.add_argument(
        "--out-html",
        default=str(_repo_root() / "outputs" / "parcel_audits" / "task2_santa_clara_residential_audit.html"),
        help="Styled HTML report path",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    gpkg_path = Path(args.gpkg_path)
    out_md = Path(args.out_md)
    out_csv = Path(args.out_csv_coverage)
    out_html = Path(args.out_html)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    unidata_apns, unidata_rows = load_unidata_apns_by_city(
        DEFAULT_DB_CONFIG, args.db_schema, args.db_table
    )

    baseline_total = Counter()
    matched = Counter()
    for city_raw, parcelnumb in iter_residential_baseline_rows(gpkg_path, args.gpkg_layer):
        ck = normalize_city(city_raw)
        apn = normalize_apn(parcelnumb)
        baseline_total[ck] += 1
        if ck in unidata_apns and apn in unidata_apns[ck]:
            matched[ck] += 1

    grand_base = sum(baseline_total.values())
    grand_matched = sum(matched.values())
    grand_miss = grand_base - grand_matched
    overall_cov = round((grand_matched / grand_base) * 100.0, 2) if grand_base else 0.0

    cities_sorted = sorted(set(baseline_total.keys()) | set(unidata_rows.keys()))

    coverage_rows: List[dict] = []
    for city in cities_sorted:
        bt = baseline_total.get(city, 0)
        mt = matched.get(city, 0)
        miss = bt - mt
        cov = round((mt / bt) * 100.0, 2) if bt else 0.0
        coverage_rows.append(
            {
                "city": city,
                "baseline_residential_rows": bt,
                "unidata_rows_scity": unidata_rows.get(city, 0),
                "matched_baseline_apn": mt,
                "missing": miss,
                "coverage_pct": cov,
            }
        )
    coverage_rows.sort(key=lambda r: (-r["baseline_residential_rows"], r["city"]))

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "city",
                "baseline_residential_rows",
                "unidata_rows_scity",
                "matched_baseline_apn",
                "missing",
                "coverage_pct",
            ],
        )
        w.writeheader()
        w.writerows(coverage_rows)

    conn = psycopg.connect(**DEFAULT_DB_CONFIG)
    completeness = field_completeness(conn, args.db_schema, args.db_table)
    weakest = sorted(completeness, key=lambda r: (r["completeness_pct"], r["field"]))[:15]

    city_highlight_data = field_coverage_by_scity_all(conn, args.db_schema, args.db_table)
    md_field_detail_limit = 25
    city_field_lines: List[str] = [
        f"_Per-`scity` completeness for **all {len(city_highlight_data)}** normalized buckets is in the HTML report (section 3). "
        f"Below: the **top {min(md_field_detail_limit, len(city_highlight_data))}** buckets by Unidata row count._\n",
        "",
    ]
    for cn, stats in city_highlight_data[:md_field_detail_limit]:
        tot = stats["_total"]
        city_field_lines.extend(
            [
                f"### {cn.title()}\n",
                "",
                f"{fmt_int(tot)} Unidata rows (normalized `scity` only).\n",
                "",
                "| Attribute | Completeness % |",
                "|-----------|----------------|",
                f"| Year built | {pct_str(stats['yearbuilt'])} |",
                f"| Address | {pct_str(stats['address'])} |",
                f"| Flood zone (`fldzone`) | {pct_str(stats['fldzone'])} |",
                f"| Hazard flags (all non-null) | {pct_str(stats['hazard_all'])} |",
                f"| Main house area (`building_area`, non-zero) | {pct_str(stats['building_area'])} |",
                f"| Size (`sqft`, non-zero) | {pct_str(stats['sqft'])} |",
                f"| Zoning | {pct_str(stats['zoning'])} |",
                f"| Lat / Lon present | {pct_str(stats['lat'])} / {pct_str(stats['lon'])} |",
                f"| Footprints non-empty | {pct_str(stats['footprints_nonempty'])} |",
                "",
                "Note: Height, Historic Status, Setback, General Plan are **not** columns on `public.unidata`.",
                "",
            ]
        )
    if len(city_highlight_data) > md_field_detail_limit:
        city_field_lines.append(
            f"_…{len(city_highlight_data) - md_field_detail_limit} additional `scity` buckets omitted here; open the HTML report for the full card grid._\n"
        )

    conn.close()

    missing_by_city = sorted(
        (
            [
                c,
                baseline_total[c] - matched[c],
                round((matched[c] / baseline_total[c]) * 100.0, 2) if baseline_total[c] else 0.0,
            ]
            for c in baseline_total
            if baseline_total[c] - matched[c] > 0
        ),
        key=lambda t: -t[1],
    )[:15]

    gen_dt = datetime.now(timezone.utc)
    generated_iso = gen_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    generated_display = gen_dt.strftime("%Y-%m-%d %H:%M UTC")

    write_task2_html(
        out_html,
        title="Task 2 — Santa Clara Residential Coverage Audit",
        generated_iso=generated_iso,
        generated_display=generated_display,
        gpkg_name=gpkg_path.name,
        schema=args.db_schema,
        table=args.db_table,
        overall_cov=overall_cov,
        grand_base=grand_base,
        grand_matched=grand_matched,
        grand_miss=grand_miss,
        coverage_rows=coverage_rows,
        completeness=completeness,
        weakest=weakest,
        missing_by_city=missing_by_city,
        city_highlight_data=city_highlight_data,
    )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Sample rows for narrative cities table (all rows in CSV; md shows top by baseline)
    top_md = [r for r in coverage_rows if r["baseline_residential_rows"] > 0]
    top_md.sort(key=lambda r: -r["baseline_residential_rows"])
    sample_table = top_md[:25]

    _wf = weakest[0] if weakest else None
    _weak_summary = (
        f"`{_wf['field']}` ({_wf['completeness_pct']:.2f}%)" if _wf else "n/a"
    )
    _n_scity_md = len(city_highlight_data)

    md_parts: List[str] = [
        "# Task 2 — Santa Clara Residential Coverage Audit (Updated)",
        "",
        f"_Generated: {generated}. Sources: `{gpkg_path.name}` (baseline) and PostgreSQL `{args.db_schema}.{args.db_table}`._",
        "",
        "## Goal",
        "",
        "Reduce error / not-available rates when users query the database by quantifying residential parcel coverage vs the county baseline and field completeness in Unidata.",
        "",
        "## Executive summary",
        "",
        f"- **Residential coverage:** **{overall_cov}%** of county residential baseline parcels ({fmt_int(grand_matched)} of {fmt_int(grand_base)}) appear in `{args.db_schema}.{args.db_table}` with the same normalized `scity` and `parcelnumb`.",
        f"- **Remaining gap:** **{fmt_int(grand_miss)}** baseline residential rows still lack that combined match (often `scity` labeling or missing ingest).",
        f"- **Field-level cards:** **{_n_scity_md}** distinct normalized `scity` buckets appear in Unidata (Table 3).",
        f"- **Weakest column (overall):** {_weak_summary} — see Table 5.",
        "",
        "## How to read each table",
        "",
        "### Snapshot KPI tiles",
        "",
        "| Tile | Meaning |",
        "|------|---------|",
        "| Residential coverage | Matched baseline ÷ residential baseline (same `scity` + parcel number). |",
        "| Baseline rows | Residential parcels in the GeoPackage (`usecode` 1,2,3,4,6) with usable parcel numbers. |",
        "| Matched in Unidata | Baseline rows that found a partner row in Unidata. |",
        "| Missing | Baseline rows without such a partner. |",
        "",
        "### Table 1 — Coverage by `scity`",
        "",
        "| Column | Meaning |",
        "|--------|---------|",
        "| Place (`scity`) | Normalized **`scity` only** row key (blank → `(NULL)`; hyphens → spaces). |",
        "| Baseline residential rows | Residential GeoPackage rows for this key. |",
        "| Unidata rows (`scity`) | All Unidata rows with this normalized `scity`. |",
        "| Matched baseline (APN) | Baseline rows whose parcel number exists in Unidata under the same `scity`. |",
        "| Missing | Baseline rows without that match. |",
        "| Coverage % | Matched ÷ baseline when baseline > 0. |",
        "",
        "### Table 2 — Field completeness matrix",
        "",
        "| Column | Meaning |",
        "|--------|---------|",
        "| Field | Column on `unidata`. |",
        "| Type | Rule category (text / number / boolean / array). |",
        "| Present / Total | Rows populated vs all rows. |",
        "| Completeness % | Present ÷ Total. `sqft` / `building_area`: zero counts as missing; `footprints` needs a non-empty array. |",
        "",
        "### Table 3 — Field-level cards",
        "",
        "One card per normalized `scity` in Unidata; percentages are **within that city bucket only**.",
        "",
        "### Table 4 — Top gaps",
        "",
        "`scity` buckets with the largest **missing** baseline residential counts (prioritize remediation).",
        "",
        "### Table 5 — Weakest fields",
        "",
        "Same semantics as Table 2, sorted so the lowest completeness fields surface first.",
        "",
        "## What was compared",
        "",
        "- **Baseline:** GeoPackage layer `ca_santa_clara_parcel_build_opt`, residential filter `usecode IN ('1','2','3','4','6')`, excluding NULL/blank `parcelnumb`.",
        "- **Target:** PostgreSQL `public.unidata`.",
        "- **City key:** `scity` only — blank/null `scity` is bucketed as `(NULL)`; never falls back to `city`. Then uppercase with whitespace collapsed and **hyphens replaced by spaces** (e.g. `SAN-JOSE` → `SAN JOSE`).",
        "- **Match rule:** A baseline row counts as *found* when its trimmed uppercased `parcelnumb` exists on any Unidata row with the **same** normalized **`scity`** key.",
        "",
        "## Overall coverage (residential baseline)",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Coverage % | **{overall_cov}%** |",
        f"| Baseline residential rows (non-null APN) | {fmt_int(grand_base)} |",
        f"| Matched in Unidata (same `scity` + APN) | {fmt_int(grand_matched)} |",
        f"| Missing | {fmt_int(grand_miss)} |",
        "",
        "_Interpretation: “Missing” means the baseline residential parcel row had no Unidata row with the same normalized **`scity`** and parcel number (after trim/case normalization)._",
        "",
        "## 1. Coverage % by `scity`",
        "",
        "Full table: `outputs/parcel_audits/task2_residential_coverage_by_city.csv`. Below: cities with the largest baseline residential counts (preview).",
        "",
        "| City (`scity`) | Baseline residential rows | Unidata rows (`scity`) | Matched baseline (APN) | Missing | Coverage % |",
        "|------|--------------------------:|--------------------:|-----------------------:|--------:|-----------:|",
    ]
    for r in sample_table:
        md_parts.append(
            f"| {r['city']} | {fmt_int(r['baseline_residential_rows'])} | "
            f"{fmt_int(r['unidata_rows_scity'])} | {fmt_int(r['matched_baseline_apn'])} | "
            f"{fmt_int(r['missing'])} | {r['coverage_pct']:.2f}% |"
        )
    md_parts.extend(
        [
            "",
            "_Rows with zero baseline residential parcels but non-zero Unidata rows indicate parcels attributed to that **`scity`** in Unidata without a matching residential baseline row for the same normalized **`scity`** (e.g., naming mismatches or geography outside the residential filter)._",
            "",
            "## 2. Field Completeness Matrix (`public.unidata`)",
            "",
            "| Field | Type | Present records | Total records | Completeness % |",
            "|-------|------|----------------:|--------------:|---------------:|",
        ]
    )
    for r in sorted(completeness, key=lambda x: x["field"]):
        md_parts.append(
            f"| `{r['field']}` | {r['field_type']} | {fmt_int(r['present'])} | {fmt_int(r['total'])} | {r['completeness_pct']:.2f}% |"
        )

    md_parts.extend(
        [
            "",
            "_Notes: `sqft` and `building_area` treat `0` as missing (common ingestion sentinel). `footprints` requires a non-empty varchar array._",
            "",
            "## 3. Field-Level Coverage by `scity` (Unidata rows)",
            "",
            *city_field_lines,
            "## 4. Key Gaps — Top `scity` Values by Missing Baseline Rows",
            "",
            "| City | Missing records | Coverage % |",
            "|------|----------------:|-----------:|",
        ]
    )
    for c, miss, cov in missing_by_city[:10]:
        md_parts.append(f"| {c} | {fmt_int(miss)} | {cov:.2f}% |")

    md_parts.extend(
        [
            "",
            "## 5. Weakest Fields (Lowest Completeness)",
            "",
            "| Field | Type | Present | Total | Completeness % |",
            "|-------|------|--------:|------:|---------------:|",
        ]
    )
    for r in weakest:
        md_parts.append(
            f"| `{r['field']}` | {r['field_type']} | {fmt_int(r['present'])} | {fmt_int(r['total'])} | {r['completeness_pct']:.2f}% |"
        )

    md_parts.extend(
        [
            "",
            "---",
            "",
            f"_Regenerate after refreshing Postgres or the GeoPackage: `python tools/audits/task2_residential_audit.py` (writes this Markdown, `outputs/parcel_audits/task2_residential_coverage_by_city.csv`, and stakeholder HTML)._",
            "",
        ]
    )

    out_md.write_text("\n".join(md_parts), encoding="utf-8")
    print(f"Wrote {out_md}")
    print(f"Wrote {out_csv}")
    print(f"Wrote {out_html}")
    print(f"Overall residential coverage: {overall_cov}% ({grand_matched}/{grand_base})")


if __name__ == "__main__":
    main()
