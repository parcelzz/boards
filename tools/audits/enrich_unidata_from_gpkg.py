"""
Fill missing non-footprint Unidata attributes from county parcel GeoPackages.

Uses the same parcel number + normalized `scity` join as other audits, with a second
pass for APNs that appear only once in the merged GPKG rows, plus a third **APN-only** pass
(``_gpkg_by_apn``) when situs ``scity`` still does not match but the parcel row can supply
address, lat/lon, yearbuilt, zoning, etc.

Never updates `footprints`. Optional numeric fills: `sqft`, `building_area`, `yearbuilt`;
text/location: `address`, `city`, `scity`, `lat`, `lon`, `zoning`.

Staging prefers the best non-empty GPKG value per field: situs **address** / **address2** / **mailadd** /
parsed **original_mailing_address** JSON; **city** from **city** or **mail_city**; **zoning** from
**zoning** or **zoning_description**; **building_area** from **ll_gissqft** or **sqft** when needed.

**Default inputs:** every ``*.gpkg`` under ``data/`` (or ``--gpkg-dir``) is opened; only layers that
have **parcelnumb** and **scity** are loaded. Other GPKGs are skipped with a log line. Multiple parcel
packages merge on ``(apn, scity_norm)``; later files fill empty slots only.

Presence rules match Step 1 / Task 2 (e.g. zero treated as missing for `sqft` and
`building_area`).

Run from repo root:
  py -3 tools/audits/enrich_unidata_from_gpkg.py              # dry run; loads every *.gpkg under data/ with parcel layers
  py -3 tools/audits/enrich_unidata_from_gpkg.py --apply        # report bundle, then UPDATE
  py -3 tools/audits/enrich_unidata_from_gpkg.py --gpkg-path data/ca_santa_clara_parcel_build_opt.gpkg  # single file

Writes the same style of bundle as Steps 1–3 under ``outputs/missingness_gpkg_fill/``:

  - ``report.html`` — title + table: column name, missing %, missing/present counts (``footprints`` omitted)
  - ``report_before_update.html`` — same table as ``report.html`` for that run, with a **Before database update** title (always written when reports are on)
  - ``unidata_columns_missing_step1.csv`` — same missing column set (scopes GPKG comparison SQL)
  - ``unidata_gpkg_field_comparison.csv`` — for Step-1-missing columns on the GPKG extract: matched rows, gaps, recoverable
  - ``unidata_gpkg_gap_detail_sample.csv`` — sample gap rows for those columns only
  - ``report_after_update.html`` — only with ``--apply``: post-commit missingness (HTML only)
  - ``report_before_after.html`` — whenever reports are on: **final** side-by-side tables (same 4-column layout
    as ``report_before_update.html``) listing **every** ``unidata`` column except ``footprints``, with **Missing** /
    **Present** counts always shown (so ``sqft`` / ``building_area`` at **0%** still appear after apply). Dry run:
    both panels are the same snapshot; ``--apply``: true before vs committed after, plus a change-summary table.

``report_after_update.html`` is produced only with ``--apply`` (and reports on): same table layout, **committed**
Unidata after the UPDATE passes. ``report_before_update.html`` is written on **every** report run (dry or apply):
same numbers as ``report.html`` in that run, with a clear **Before database update** title so it is easy to find
next to ``report_after_update.html`` after you re-run the tool.

Use ``--no-report`` to skip writing those files. Pass ``--out-root`` to mirror Step 1’s
``--out-root`` pattern. The main bundle (``report.html`` and the three CSVs) reflects **pre-update**
Unidata in the same run as ``--apply``; ``report_after_update.html`` reflects **post-update** missingness.
Re-running the script later refreshes ``report.html`` from the current DB, so keep ``report_before_update.html``
from the apply run if you need a permanent “before” slide.

Requires: psycopg, local Postgres with `public.unidata`, and at least one parcel-style GPKG.
"""
from __future__ import annotations

import argparse
import csv
import html as html_module
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import psycopg

from field_missingness_classification import (
    DEFAULT_DB_CONFIG,
    FieldRow,
    compute_field_rows,
    taxonomy_title,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


_WS = re.compile(r"\s+")


def normalize_apn(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def normalize_scity(value: str | None) -> str:
    if value is None or not str(value).strip():
        return "(NULL)"
    s = _WS.sub(" ", str(value).strip().replace("-", " "))
    return s.upper()


def _sqlite_quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _gpkg_feature_table_names(gpkg_path: Path) -> list[str]:
    import sqlite3

    conn = sqlite3.connect(str(gpkg_path))
    cur = conn.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name"
    )
    out = [str(r[0]) for r in cur.fetchall()]
    conn.close()
    return out


def _table_column_names_lower(gpkg_path: Path, table: str) -> set[str]:
    import sqlite3

    conn = sqlite3.connect(str(gpkg_path))
    q = _sqlite_quote_ident(table)
    cur = conn.execute(f"PRAGMA table_info({q})")
    cols = {str(r[1]).lower() for r in cur.fetchall()}
    conn.close()
    return cols


def _parcel_layer_for_gpkg(gpkg_path: Path) -> str | None:
    """First features table that has parcelnumb + scity (parcel-style extract)."""
    for tbl in _gpkg_feature_table_names(gpkg_path):
        cols = _table_column_names_lower(gpkg_path, tbl)
        if "parcelnumb" in cols and "scity" in cols:
            return tbl
    return None


def _gpkg_path_sort_key(p: Path) -> tuple[int, str]:
    n = p.name.lower()
    if "parcel" in n or "santa_clara" in n or "build_opt" in n:
        return (0, n)
    return (1, n)


def _pick_nonempty_str(a: str | None, b: str | None) -> str | None:
    if a is not None and str(a).strip() != "":
        return a
    if b is not None and str(b).strip() != "":
        return b
    return a


def _pick_float(a: float | None, b: float | None) -> float | None:
    if a is not None:
        return a
    return b


def _pick_pos_int(a: int | None, b: int | None) -> int | None:
    if a is not None and a > 0:
        return a
    if b is not None and b > 0:
        return b
    return a


def _floatish(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int_positive(v: Any) -> int | None:
    f = _floatish(v)
    if f is None or f <= 0:
        return None
    return int(round(f))


def _first_nonempty(*vals: Any) -> str | None:
    """First stripped non-empty string among values (skips None, '', '{}')."""
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if not s or s == "{}":
            continue
        return s
    return None


def _mail_from_original_mailing_json(raw: Any) -> tuple[str | None, str | None]:
    """Parse GPKG ``original_mailing_address`` JSON for mail line + city, if present."""
    if raw is None:
        return None, None
    s = str(raw).strip()
    if not s.startswith("{"):
        return None, None
    try:
        d = json.loads(s)
        if not isinstance(d, dict):
            return None, None
        ma = d.get("mailadd")
        mc = d.get("mail_city")
        line = str(ma).strip() if ma else None
        city = str(mc).strip() if mc else None
        return (line or None, city or None)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, None


def iter_gpkg_rows(gpkg_path: Path, layer: str) -> Iterator[dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(str(gpkg_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    qt = _sqlite_quote_ident(layer)
    cur.execute(
        f"""
        SELECT
            parcelnumb,
            scity,
            city,
            address,
            address2,
            mailadd,
            mail_city,
            original_mailing_address,
            lat,
            lon,
            sqft,
            ll_gissqft,
            yearbuilt,
            zoning,
            zoning_description
        FROM {qt}
        WHERE parcelnumb IS NOT NULL
          AND TRIM(CAST(parcelnumb AS TEXT)) <> ''
        """
    )
    for row in cur:
        yield dict(row)
    conn.close()


def sql_literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


GPKG_MAPPABLE_COLS = frozenset(
    {"address", "city", "scity", "lat", "lon", "sqft", "building_area", "yearbuilt", "zoning"}
)


def _all_gpkg_compare_specs() -> list[tuple[str, str, str, str, str]]:
    """field_name, u_missing_sql, src_present_sql, proposed_sql, current_display_sql."""
    b = "[blank]"
    return [
        (
            "address",
            "(u.address IS NULL OR TRIM(u.address::text) = '')",
            "src.address IS NOT NULL AND TRIM(src.address) <> ''",
            "src.address::text",
            f"COALESCE(NULLIF(TRIM(u.address::text), ''), {sql_literal(b)})",
        ),
        (
            "city",
            "(u.city IS NULL OR TRIM(u.city::text) = '')",
            "src.city IS NOT NULL AND TRIM(src.city) <> ''",
            "src.city::text",
            f"COALESCE(NULLIF(TRIM(u.city::text), ''), {sql_literal(b)})",
        ),
        (
            "scity",
            "(u.scity IS NULL OR TRIM(u.scity::text) = '')",
            "src.scity_raw IS NOT NULL AND TRIM(src.scity_raw) <> ''",
            "src.scity_raw::text",
            f"COALESCE(NULLIF(TRIM(u.scity::text), ''), {sql_literal(b)})",
        ),
        (
            "lat",
            "u.lat IS NULL",
            "src.lat IS NOT NULL",
            "src.lat::text",
            f"COALESCE(u.lat::text, {sql_literal(b)})",
        ),
        (
            "lon",
            "u.lon IS NULL",
            "src.lon IS NOT NULL",
            "src.lon::text",
            f"COALESCE(u.lon::text, {sql_literal(b)})",
        ),
        (
            "sqft",
            "(u.sqft IS NULL OR u.sqft = 0)",
            "src.sqft IS NOT NULL AND src.sqft <> 0",
            "src.sqft::text",
            f"CASE WHEN u.sqft IS NULL THEN {sql_literal(b)} ELSE u.sqft::text END",
        ),
        (
            "building_area",
            "(u.building_area IS NULL OR u.building_area = 0)",
            "src.building_area IS NOT NULL AND src.building_area <> 0",
            "src.building_area::text",
            f"CASE WHEN u.building_area IS NULL THEN {sql_literal(b)} ELSE u.building_area::text END",
        ),
        (
            "yearbuilt",
            "(u.yearbuilt IS NULL OR u.yearbuilt = 0)",
            "src.yearbuilt IS NOT NULL AND src.yearbuilt <> 0",
            "src.yearbuilt::text",
            f"CASE WHEN u.yearbuilt IS NULL THEN {sql_literal(b)} ELSE u.yearbuilt::text END",
        ),
        (
            "zoning",
            "(u.zoning IS NULL OR TRIM(u.zoning::text) = '')",
            "src.zoning IS NOT NULL AND TRIM(src.zoning) <> ''",
            "src.zoning::text",
            f"COALESCE(NULLIF(TRIM(u.zoning::text), ''), {sql_literal(b)})",
        ),
    ]


def _needs_any_sql_from_specs(specs: list[tuple[str, str, str, str, str]]) -> str:
    return "(" + " OR ".join(f"({u_miss})" for _, u_miss, _, _, _ in specs) + ")"


def _gpkg_can_fill_sql_from_specs(specs: list[tuple[str, str, str, str, str]], table_alias: str) -> str:
    parts: list[str] = []
    for _, u_miss, src_pres, _, _ in specs:
        g_has = src_pres.replace("src.", f"{table_alias}.")
        parts.append(f"(({u_miss}) AND ({g_has}))")
    return "(" + " OR ".join(parts) + ")"


def _step1_missing_nonfootprint_rows(field_rows: list[FieldRow]) -> list[FieldRow]:
    """Columns with missing > 0; omit only the footprints geometry array (not sqft/building_area)."""
    out: list[FieldRow] = []
    for r in field_rows:
        if r.column_name.lower() == "footprints":
            continue
        if r.missing <= 0:
            continue
        out.append(r)
    # Same tie-break as Step 1 overview (`field_missingness_classification.build_html_report`).
    out.sort(key=lambda x: (-x.missing_pct, x.taxonomy_bucket, x.column_name))
    return out


def _report_missing_bar_cell(pct: float) -> str:
    """Missing % bar + label; extra decimals when 0 < pct < 0.01 so tiny rates are not shown as 0.00%."""
    esc = html_module.escape
    w = min(100.0, max(0.0, pct))
    hue = "#16a34a" if pct < 5 else "#d97706" if pct < 25 else "#dc2626"
    miss_cls = "miss-high" if pct >= 25 else "miss-mid" if pct >= 5 else "miss-low"
    pct_label = f"{pct:.4f}%" if 0 < pct < 0.01 else f"{pct:.2f}%"
    tip = f"{pct_label} missing"
    return (
        f'<div class="miss-cell"><div class="bar-track" title="{esc(tip)}">'
        f'<span class="bar-fill" style="width:{w:.1f}%;background:{hue}"></span></div>'
        f'<span class="miss-pct {miss_cls}">{esc(pct_label)}</span></div>'
    )


def _report_gpkg_compare_specs(field_rows: list[FieldRow]) -> list[tuple[str, str, str, str, str]]:
    """GPKG comparison rows only for Step-1-missing columns that exist on the staged GPKG extract."""
    missing = {r.column_name for r in _step1_missing_nonfootprint_rows(field_rows)}
    return [s for s in _all_gpkg_compare_specs() if s[0] in missing]


def _comparison_subselects(
    schema: str,
    table: str,
    scity_expr: str,
    tier: str,
    join_sql: str,
    src_alias: str,
    field_specs: list[tuple[str, str, str, str, str]],
) -> str:
    """One SELECT per field: matched-row counts vs missing vs GPKG presence (pair or singleton join)."""
    parts: list[str] = []
    for fname, u_miss, src_pres, _, _ in field_specs:
        g_has = src_pres.replace("src.", f"{src_alias}.")
        parts.append(
            f"""
            SELECT {sql_literal(tier)} AS match_tier,
              {sql_literal(fname)} AS field_name,
              COUNT(*)::bigint AS matched_rows,
              COUNT(*) FILTER (WHERE {u_miss})::bigint AS n_unidata_missing,
              COUNT(*) FILTER (WHERE {g_has})::bigint AS n_gpkg_has,
              COUNT(*) FILTER (WHERE ({u_miss}) AND ({g_has}))::bigint AS n_recoverable
            FROM {schema}.{table} u
            {join_sql}
            WHERE u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
            """.strip()
        )
    return " UNION ALL ".join(parts)


def _gap_detail_subselects(
    schema: str,
    table: str,
    scity_expr: str,
    tier: str,
    join_sql: str,
    not_exists: str,
    src_alias: str,
    field_specs: list[tuple[str, str, str, str, str]],
) -> str:
    """Per-field rows where Unidata is missing on a matched parcel; show GPKG side and comparison."""
    parts: list[str] = []
    for fname, u_miss, src_pres, proposed, cur_disp in field_specs:
        g_has = src_pres.replace("src.", f"{src_alias}.")
        prop_adj = proposed.replace("src.", f"{src_alias}.")
        cmp_note = f"CASE WHEN ({g_has}) THEN 'recoverable from GPKG' ELSE 'Unidata missing; GPKG empty' END"
        sort_k = f"CASE WHEN ({g_has}) THEN 0 ELSE 1 END"
        parts.append(
            f"""
            SELECT {sql_literal(tier)} AS match_tier,
              {sql_literal(fname)} AS field_name,
              TRIM(u.parcelnumb::text) AS parcelnumb,
              TRIM(COALESCE(u.scity::text, '')) AS unidata_scity,
              ({cur_disp}) AS unidata_value,
              ({prop_adj}) AS gpkg_value,
              {cmp_note} AS comparison,
              {sort_k} AS _sort
            FROM {schema}.{table} u
            {join_sql}
            WHERE u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
              AND ({u_miss})
              {not_exists}
            """.strip()
        )
    return " UNION ALL ".join(parts)


def _recoverable_parcel_or_pred(src_alias: str, field_specs: list[tuple[str, str, str, str, str]]) -> str:
    """OR of (u_miss AND g_has) for tracked fields — for distinct-parcel KPI."""
    bits: list[str] = []
    for _, u_miss, src_pres, _, _ in field_specs:
        g_has = src_pres.replace("src.", f"{src_alias}.")
        bits.append(f"(({u_miss}) AND ({g_has}))")
    return "(" + " OR ".join(bits) + ")"


def _gpkg_fill_report_css() -> str:
    """Styles for the minimal missing-columns HTML report (single page)."""
    return """
    :root {
      --bg: #f1f5f9;
      --surface: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --line-strong: #cbd5e1;
      --shadow: 0 1px 3px rgba(15, 23, 42, 0.06), 0 12px 40px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      font-size: 15px;
      -webkit-font-smoothing: antialiased;
    }
    main {
      max-width: 920px;
      margin: 0 auto;
      padding: 40px 20px 64px;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line-strong);
      border-radius: 12px;
      padding: 28px 28px 24px;
      box-shadow: var(--shadow);
    }
    .report-header {
      margin-bottom: 22px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--line);
    }
    .report-title {
      margin: 0 0 8px;
      font-size: 1.25rem;
      font-weight: 600;
      letter-spacing: -0.025em;
      color: var(--text);
      line-height: 1.35;
    }
    .report-meta {
      margin: 0;
      font-size: 13px;
      font-weight: 500;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }
    .report-meta time { color: inherit; }
    .muted { color: var(--muted); font-size: 14px; }
    .table-wrap {
      overflow-x: auto;
      padding: 0;
      margin: 0 -4px;
      border-radius: 8px;
      -webkit-overflow-scrolling: touch;
    }
    .table-wrap.missing-report-scroll { max-width: 100%; }
    table.missing-cols {
      width: max(100%, 720px);
      min-width: 720px;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    table.missing-cols thead th {
      padding: 12px 16px;
      text-align: left;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #475569;
      background: #f8fafc;
      border-bottom: 1px solid var(--line-strong);
      white-space: nowrap;
    }
    table.missing-cols thead th.num { text-align: right; }
    table.missing-cols tbody td {
      padding: 13px 16px;
      vertical-align: middle;
      border-bottom: 1px solid var(--line);
      color: #1e293b;
    }
    table.missing-cols tbody tr:last-child td { border-bottom: none; }
    table.missing-cols tbody tr:hover td { background: #f8fafc; }
    table.missing-cols tbody tr:nth-child(even) td { background: #fcfcfd; }
    table.missing-cols tbody tr:nth-child(even):hover td { background: #f1f5f9; }
    table.missing-cols th:first-child,
    table.missing-cols td:first-child {
      min-width: 11rem;
      white-space: nowrap;
    }
    table.missing-cols th:nth-child(2),
    table.missing-cols td:nth-child(2) { min-width: 13rem; }
    table.missing-cols th.num:nth-child(3),
    table.missing-cols td.num:nth-child(3),
    table.missing-cols th.num:nth-child(4),
    table.missing-cols td.num:nth-child(4) {
      min-width: 7rem;
    }
    .num {
      text-align: right;
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum" 1;
    }
    table.missing-cols code {
      font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
      font-size: 13px;
      font-weight: 500;
      color: #0f172a;
      background: #f1f5f9;
      border: 1px solid var(--line);
      padding: 4px 10px;
      border-radius: 6px;
    }
    .miss-cell {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 12px;
      flex-wrap: nowrap;
    }
    .bar-track {
      flex: 1;
      min-width: 80px;
      max-width: 160px;
      height: 10px;
      background: #e2e8f0;
      border-radius: 999px;
      overflow: hidden;
      box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.08);
    }
    .bar-fill {
      display: block;
      height: 100%;
      border-radius: 999px;
      box-shadow: inset 0 -1px 0 rgba(255, 255, 255, 0.2);
    }
    .miss-pct {
      font-weight: 600;
      font-size: 13px;
      min-width: 4.5rem;
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    .miss-low { color: #15803d; }
    .miss-mid { color: #c2410c; }
    .miss-high { color: #b91c1c; }
    main.wide { max-width: 1280px; }
    .compare-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.25rem;
      align-items: start;
    }
    @media (max-width: 1100px) {
      .compare-grid { grid-template-columns: 1fr; }
    }
    .compare-panel h2.panel-subtitle {
      margin: 0 0 12px;
      font-size: 1rem;
      font-weight: 600;
      color: #334155;
    }
    table.diff-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 13px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    table.diff-table thead th {
      padding: 10px 12px;
      text-align: left;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #475569;
      background: #f8fafc;
      border-bottom: 1px solid var(--line-strong);
    }
    table.diff-table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: middle;
    }
    table.diff-table tbody tr:last-child td { border-bottom: none; }
    table.diff-table tbody tr:nth-child(even) td { background: #fcfcfd; }
    table.diff-table .num { text-align: right; font-variant-numeric: tabular-nums; }
    .delta-up { color: #15803d; font-weight: 600; }
    .delta-down { color: #b91c1c; font-weight: 600; }
    .section-block { margin-top: 2rem; }
    .section-block > h2.section-title {
      margin: 0 0 14px;
      font-size: 1.05rem;
      font-weight: 600;
      color: #0f172a;
    }
    """


def _missing_columns_html(
    step1_missing: list[FieldRow],
    title: str,
    gen_iso: str,
    *,
    subtitle: str | None = None,
) -> str:
    """Full HTML document: Step-1 missing columns table (same layout as ``report.html``)."""
    esc = html_module.escape

    if step1_missing:
        step1_rows_html = "".join(
            "<tr>"
            f"<td><code>{esc(r.column_name)}</code></td>"
            f"<td class='num'>{_report_missing_bar_cell(r.missing_pct)}</td>"
            f"<td class='num'>{r.missing:,}</td>"
            f"<td class='num'>{r.present:,}</td>"
            "</tr>"
            for r in step1_missing
        )
    else:
        step1_rows_html = (
            "<tr><td colspan='4' class='muted'>No columns with missing values under Step 1 rules, or only "
            "<code>footprints</code> would apply (that column is excluded here).</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{esc(title)}</title>
  <style>{_gpkg_fill_report_css()}</style>
</head>
<body>
  <main>
    <section class="panel" id="missing-columns">
      <header class="report-header">
        <h1 class="report-title">{esc(title)}</h1>
        <p class="report-meta"><time datetime="{esc(gen_iso)}">Generated {esc(gen_iso)}</time></p>
        {f'<p class="report-meta muted">{esc(subtitle)}</p>' if subtitle else ""}
      </header>
      <div class="table-wrap missing-report-scroll">
        <table class="missing-cols">
          <thead>
            <tr>
              <th>Column</th>
              <th>Missing %</th>
              <th class="num">Missing</th>
              <th class="num">Present</th>
            </tr>
          </thead>
          <tbody>{step1_rows_html}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def write_unidata_missingness_html(
    out_root: Path,
    schema: str,
    table: str,
    filename: str,
    title: str,
    *,
    subtitle: str | None = None,
    field_rows: list[FieldRow] | None = None,
) -> None:
    """Write only the missing-columns HTML (no GPKG comparison CSVs). Uses current DB state."""
    out_root.mkdir(parents=True, exist_ok=True)
    rows = field_rows if field_rows is not None else compute_field_rows(schema, table, DEFAULT_DB_CONFIG)
    step1_missing = _step1_missing_nonfootprint_rows(rows)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (out_root / filename).write_text(
        _missing_columns_html(step1_missing, title, gen, subtitle=subtitle),
        encoding="utf-8",
    )


def _fmt_step1_pct_label(pct: float) -> str:
    if 0 < pct < 0.01:
        return f"{pct:.4f}%"
    return f"{pct:.2f}%"


def _all_non_footprint_column_order(
    field_rows_b: list[FieldRow],
    field_rows_a: list[FieldRow],
) -> list[str]:
    """Every Unidata column except ``footprints``, same order in both panels (high missing first)."""
    db = {r.column_name.lower(): r for r in field_rows_b}
    da = {r.column_name.lower(): r for r in field_rows_a}
    all_low = (set(db.keys()) | set(da.keys())) - {"footprints"}

    def sort_key(low: str) -> tuple:
        rb = db.get(low)
        ra = da.get(low)
        mb = rb.missing_pct if rb else 0.0
        ma = ra.missing_pct if ra else 0.0
        return (-max(mb, ma), low)

    ordered = sorted(all_low, key=sort_key)
    return [db[low].column_name if low in db else da[low].column_name for low in ordered]


def _missingness_rows_html_ordered(names: list[str], by_lower: dict[str, FieldRow]) -> str:
    esc = html_module.escape
    parts: list[str] = []
    for name in names:
        r = by_lower[name.lower()]
        parts.append(
            "<tr>"
            f"<td><code>{esc(r.column_name)}</code></td>"
            f"<td class='num'>{_report_missing_bar_cell(r.missing_pct)}</td>"
            f"<td class='num'>{r.missing:,}</td>"
            f"<td class='num'>{r.present:,}</td>"
            "</tr>"
        )
    return "".join(parts)


def _delta_missing_rows_html(before_m: int, after_m: int) -> str:
    d = before_m - after_m
    if d == 0:
        return '<span class="muted">0</span>'
    cls = "delta-up" if d > 0 else "delta-down"
    sign = "+" if d > 0 else ""
    return f'<span class="{cls}">{sign}{d:,}</span>'


def _final_diff_summary_tbody(names: list[str], db: dict[str, FieldRow], da: dict[str, FieldRow]) -> str:
    esc = html_module.escape
    parts: list[str] = []
    for name in names:
        low = name.lower()
        rb, ra = db[low], da[low]
        pct_b = esc(_fmt_step1_pct_label(rb.missing_pct))
        pct_a = esc(_fmt_step1_pct_label(ra.missing_pct))
        parts.append(
            "<tr>"
            f"<td><code>{esc(rb.column_name)}</code></td>"
            f"<td class='num'>{pct_b}</td>"
            f"<td class='num'>{pct_a}</td>"
            f"<td class='num'>{_delta_missing_rows_html(rb.missing, ra.missing)}</td>"
            "</tr>"
        )
    return "".join(parts)


def write_gpkg_before_after_final_html(
    out_root: Path,
    field_rows_before: list[FieldRow],
    field_rows_after: list[FieldRow],
    *,
    dry_run: bool,
) -> None:
    """Side-by-side tables (Step-1 style: Column / Missing % / Missing count / Present count) for all columns except ``footprints``."""
    out_root.mkdir(parents=True, exist_ok=True)
    names = _all_non_footprint_column_order(field_rows_before, field_rows_after)
    db = {r.column_name.lower(): r for r in field_rows_before}
    da = {r.column_name.lower(): r for r in field_rows_after}
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    esc = html_module.escape
    before_rows = _missingness_rows_html_ordered(names, db)
    after_rows = _missingness_rows_html_ordered(names, da)
    diff_body = _final_diff_summary_tbody(names, db, da)
    title = "Unidata missingness — before & after (all columns except footprints)"
    if dry_run:
        intro = (
            "Every column on <code>unidata</code> except <code>footprints</code>, with "
            "<strong>Missing %</strong>, <strong>Missing</strong> row count, and <strong>Present</strong> row count "
            "(same layout as <code>report_before_update.html</code>). "
            "Dry run: both panels use the same snapshot — no UPDATE was applied."
        )
        after_note = (
            '<p class="report-meta muted">Dry run: identical to the left panel (no database changes).</p>'
        )
    else:
        intro = (
            "Every column on <code>unidata</code> except <code>footprints</code>, with "
            "<strong>Missing %</strong>, <strong>Missing</strong> count, and <strong>Present</strong> count "
            "(same layout as <code>report_before_update.html</code>). "
            "Columns that reach <strong>0%</strong> missing after the GPKG apply (e.g. <code>sqft</code>, "
            "<code>building_area</code>) still appear so you can compare counts. "
            "<strong>Δ missing rows</strong> = missing before − missing after (positive ⇒ rows fixed)."
        )
        after_note = ""
    before_panel_title = "Before database update: missing Unidata columns (excluding footprints)"
    after_panel_title = "After database update: missing Unidata columns (excluding footprints)"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{esc(title)}</title>
  <style>{_gpkg_fill_report_css()}</style>
</head>
<body>
  <main class="wide">
    <section class="panel">
      <header class="report-header">
        <h1 class="report-title">{esc(title)}</h1>
        <p class="report-meta"><time datetime="{esc(gen)}">Generated {esc(gen)}</time></p>
        <p class="report-meta muted">{intro}</p>
      </header>
    </section>
    <section class="panel section-block">
      <h2 class="section-title">Side-by-side (same row order)</h2>
      <div class="compare-grid">
        <div class="compare-panel">
          <h2 class="panel-subtitle">{esc(before_panel_title)}</h2>
          <div class="table-wrap missing-report-scroll">
            <table class="missing-cols">
              <thead>
                <tr>
                  <th>Column</th>
                  <th>Missing %</th>
                  <th class="num">Missing</th>
                  <th class="num">Present</th>
                </tr>
              </thead>
              <tbody>{before_rows}</tbody>
            </table>
          </div>
        </div>
        <div class="compare-panel">
          <h2 class="panel-subtitle">{esc(after_panel_title)}</h2>
          {after_note}
          <div class="table-wrap missing-report-scroll">
            <table class="missing-cols">
              <thead>
                <tr>
                  <th>Column</th>
                  <th>Missing %</th>
                  <th class="num">Missing</th>
                  <th class="num">Present</th>
                </tr>
              </thead>
              <tbody>{after_rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
    <section class="panel section-block">
      <h2 class="section-title">Change summary (percent + row delta)</h2>
      <div class="table-wrap">
        <table class="diff-table">
          <thead>
            <tr>
              <th>Column</th>
              <th class="num">Before missing %</th>
              <th class="num">After missing %</th>
              <th class="num">Δ missing rows</th>
            </tr>
          </thead>
          <tbody>{diff_body}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""
    (out_root / "report_before_after.html").write_text(html, encoding="utf-8")


def write_gpkg_fill_report(
    conn: psycopg.Connection,
    out_root: Path,
    schema: str,
    table: str,
    scity_expr: str,
    preview_limit: int,
    n_staged_gpkg: int,
    *,
    dry_run: bool,
) -> list[FieldRow]:
    """Write ``report.html``, ``report_before_update.html`` (same pre-UPDATE snapshot, clearer title),
    plus GPKG comparison CSVs. Returns field-level snapshot rows (same source as Step 1 rules) for callers.
    """
    out_root.mkdir(parents=True, exist_ok=True)

    not_ex_single = f"""
      AND NOT EXISTS (
          SELECT 1 FROM _gpkg_by_pair g2
          WHERE g2.apn = upper(trim(u.parcelnumb))
            AND g2.scity_norm = ({scity_expr})
      )
    """

    join_pair_sql = f"""
    INNER JOIN _gpkg_by_pair g
    ON upper(trim(u.parcelnumb)) = g.apn
    AND ({scity_expr}) = g.scity_norm
    """
    join_single_sql = f"""
    INNER JOIN _gpkg_singleton s
    ON upper(trim(u.parcelnumb)) = s.apn
    {not_ex_single}
    """

    field_rows = compute_field_rows(schema, table, DEFAULT_DB_CONFIG)
    step1_missing = _step1_missing_nonfootprint_rows(field_rows)
    report_specs = _report_gpkg_compare_specs(field_rows)
    full_kpi_specs = _all_gpkg_compare_specs()

    snap_path = out_root / "unidata_columns_missing_step1.csv"
    with snap_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "column_name",
                "taxonomy",
                "taxonomy_key",
                "missing_pct",
                "missing_count",
                "present_count",
                "total_rows",
                "behavior_risk",
                "review_priority",
                "on_gpkg_parcel_extract",
            ]
        )
        for r in step1_missing:
            w.writerow(
                [
                    r.column_name,
                    taxonomy_title(r.taxonomy_bucket),
                    r.taxonomy_bucket,
                    f"{r.missing_pct:.4f}",
                    r.missing,
                    r.present,
                    r.total_rows,
                    r.product_behavior_risk,
                    r.review_priority,
                    "yes" if r.column_name in GPKG_MAPPABLE_COLS else "no",
                ]
            )

    cmp_pair_sql = ""
    cmp_single_sql = ""
    detail_sql = ""
    gap_pair = ""
    gap_single = ""
    if report_specs:
        cmp_pair_sql = _comparison_subselects(
            schema, table, scity_expr, "pair", join_pair_sql, "g", report_specs
        )
        cmp_single_sql = _comparison_subselects(
            schema, table, scity_expr, "singleton", join_single_sql, "s", report_specs
        )
        gap_pair = _gap_detail_subselects(
            schema, table, scity_expr, "pair", join_pair_sql, "", "g", report_specs
        )
        gap_single = _gap_detail_subselects(
            schema, table, scity_expr, "singleton", join_single_sql, "", "s", report_specs
        )
        detail_sql = f"""
    SELECT match_tier, field_name, parcelnumb, unidata_scity, unidata_value, gpkg_value, comparison
    FROM (
      SELECT match_tier, field_name, parcelnumb, unidata_scity, unidata_value, gpkg_value, comparison, _sort
      FROM (
        {gap_pair}
        UNION ALL
        {gap_single}
      ) _u
    ) _v
    ORDER BY _v._sort, _v.match_tier, _v.parcelnumb, _v.field_name
    LIMIT {int(preview_limit)}
    """

    matched_pair_q = f"""
    SELECT COUNT(*)::bigint FROM {schema}.{table} u
    {join_pair_sql}
    WHERE u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
    """
    matched_single_q = f"""
    SELECT COUNT(*)::bigint FROM {schema}.{table} u
    {join_single_sql}
    WHERE u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
    """
    rec_pair_parcels_q = f"""
    SELECT COUNT(DISTINCT u.id)::bigint FROM {schema}.{table} u
    {join_pair_sql}
    WHERE u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
      AND {_recoverable_parcel_or_pred("g", full_kpi_specs)}
    """
    rec_single_parcels_q = f"""
    SELECT COUNT(DISTINCT u.id)::bigint FROM {schema}.{table} u
    {join_single_sql}
    WHERE u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
      AND {_recoverable_parcel_or_pred("s", full_kpi_specs)}
    """

    comparison_rows: list[tuple[Any, ...]] = []
    detail: list[tuple[Any, ...]] = []
    n_matched_pair = 0
    n_matched_single = 0
    n_rec_parcel_pair = 0
    n_rec_parcel_single = 0

    with conn.cursor() as cur:
        cur.execute(matched_pair_q)
        n_matched_pair = int(cur.fetchone()[0])
        cur.execute(matched_single_q)
        n_matched_single = int(cur.fetchone()[0])
        cur.execute(rec_pair_parcels_q)
        n_rec_parcel_pair = int(cur.fetchone()[0])
        cur.execute(rec_single_parcels_q)
        n_rec_parcel_single = int(cur.fetchone()[0])

        if report_specs:
            cur.execute(cmp_pair_sql)
            comparison_rows.extend(cur.fetchall())
            cur.execute(cmp_single_sql)
            comparison_rows.extend(cur.fetchall())
            cur.execute(detail_sql)
            detail = cur.fetchall()

    cmp_path = out_root / "unidata_gpkg_field_comparison.csv"
    with cmp_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["match_tier", "field_name", "matched_rows", "n_unidata_missing", "n_gpkg_has", "n_recoverable"]
        )
        w.writerows(comparison_rows)

    det_path = out_root / "unidata_gpkg_gap_detail_sample.csv"
    with det_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["match_tier", "field_name", "parcelnumb", "unidata_scity", "unidata_value", "gpkg_value", "comparison"]
        )
        for r in detail:
            w.writerow([str(x) if x is not None else "" for x in r])

    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title = "Backfill plan: missing Unidata columns from GPKG (excluding footprints)"
    (out_root / "report.html").write_text(
        _missing_columns_html(step1_missing, title, gen),
        encoding="utf-8",
    )
    before_title = "Before database update: missing Unidata columns (excluding footprints)"
    before_sub = (
        "Dry run: no UPDATE runs. Re-run with --apply to change Unidata; this file still records the pre-run snapshot."
        if dry_run
        else "Snapshot immediately before this run’s GPKG UPDATE passes (same numbers as report.html in this run)."
    )
    (out_root / "report_before_update.html").write_text(
        _missing_columns_html(step1_missing, before_title, gen, subtitle=before_sub),
        encoding="utf-8",
    )
    return field_rows


def load_staging_rows(gpkg_path: Path, layer: str) -> list[tuple]:
    """Rows for COPY into Postgres temp table (apn, scity_norm, ...)."""
    out: list[tuple] = []
    for r in iter_gpkg_rows(gpkg_path, layer):
        apn = normalize_apn(r.get("parcelnumb"))
        if not apn:
            continue
        sn = normalize_scity(r.get("scity"))
        mail_line, mail_city_json = _mail_from_original_mailing_json(r.get("original_mailing_address"))
        addr = _first_nonempty(
            r.get("address"),
            r.get("address2"),
            r.get("mailadd"),
            mail_line,
        )
        city = _first_nonempty(r.get("city"), r.get("mail_city"), mail_city_json)
        scity_raw = (r.get("scity") or "").strip() or None
        lat = _floatish(r.get("lat"))
        lon = _floatish(r.get("lon"))
        sqft = _int_positive(r.get("ll_gissqft")) or _int_positive(r.get("sqft"))
        barea = _int_positive(r.get("ll_gissqft")) or _int_positive(r.get("sqft"))
        yb = _int_positive(r.get("yearbuilt"))
        if yb is not None and yb > 3000:
            yb = None
        zon = _first_nonempty(r.get("zoning"), r.get("zoning_description"))
        out.append((apn, sn, addr, city, scity_raw, lat, lon, sqft, barea, yb, zon))
    return out


def _merge_staging_row(prev: tuple[Any, ...], new: tuple[Any, ...]) -> tuple[Any, ...]:
    """Merge two staging tuples for the same (apn, scity_norm); prefer filled values from `prev`, then `new`."""
    if prev[0] != new[0] or prev[1] != new[1]:
        return prev
    return (
        prev[0],
        prev[1],
        _pick_nonempty_str(prev[2], new[2]),
        _pick_nonempty_str(prev[3], new[3]),
        _pick_nonempty_str(prev[4], new[4]),
        _pick_float(prev[5], new[5]),
        _pick_float(prev[6], new[6]),
        _pick_pos_int(prev[7], new[7]),
        _pick_pos_int(prev[8], new[8]),
        _pick_pos_int(prev[9], new[9]),
        _pick_nonempty_str(prev[10], new[10]),
    )


def load_merged_staging_rows(
    gpkg_paths: list[Path],
    layer_override: str | None,
) -> tuple[list[tuple[Any, ...]], list[str]]:
    """Load parcel rows from several GeoPackages and merge on (apn, scity_norm)."""
    notes: list[str] = []
    merged: dict[tuple[str, str], tuple[Any, ...]] = {}
    ordered = sorted(gpkg_paths, key=_gpkg_path_sort_key)
    single = len(gpkg_paths) == 1
    for path in ordered:
        layer = layer_override if (single and layer_override) else _parcel_layer_for_gpkg(path)
        if not layer:
            notes.append(
                f"skip {path.name} (no parcel extract: need features layer with parcelnumb + scity)"
            )
            continue
        chunk = load_staging_rows(path, layer)
        notes.append(f"use {path.name} layer {layer!r}: {len(chunk):,} raw rows")
        for row in chunk:
            key = (str(row[0]), str(row[1]))
            if key not in merged:
                merged[key] = row
            else:
                merged[key] = _merge_staging_row(merged[key], row)
    return list(merged.values()), notes


def main() -> None:
    p = argparse.ArgumentParser(description="Enrich public.unidata from county GPKG (no footprints).")
    p.add_argument(
        "--gpkg-path",
        action="append",
        default=None,
        metavar="PATH",
        help="GeoPackage file (repeatable). Default: all *.gpkg under --gpkg-dir that contain a parcel layer.",
    )
    p.add_argument(
        "--gpkg-dir",
        type=Path,
        default=None,
        help="Scanned for *.gpkg when --gpkg-path is omitted (default: <repo>/data).",
    )
    p.add_argument(
        "--gpkg-layer",
        default=None,
        metavar="NAME",
        help="Force features layer name when exactly one --gpkg-path is given; otherwise auto-detect per file.",
    )
    p.add_argument("--db-schema", default="public")
    p.add_argument("--db-table", default="unidata")
    p.add_argument(
        "--apply",
        action="store_true",
        help="Run UPDATE after staging. Report bundle is written first unless --no-report.",
    )
    p.add_argument(
        "--out-root",
        type=Path,
        default=_repo_root() / "outputs" / "missingness_gpkg_fill",
        help="Directory for report.html + CSVs (same pattern as Step 1 --out-root).",
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing report.html and companion CSVs.",
    )
    p.add_argument(
        "--preview-limit",
        type=int,
        default=8000,
        metavar="N",
        help="Max rows in the HTML/CSV detail sample (default 8000).",
    )
    args = p.parse_args()
    dry_run = not args.apply

    out_root = Path(args.out_root)
    if not out_root.is_absolute():
        out_root = _repo_root() / out_root

    gpkg_dir = args.gpkg_dir if args.gpkg_dir is not None else _repo_root() / "data"
    gpkg_dir = Path(gpkg_dir)
    if not gpkg_dir.is_absolute():
        gpkg_dir = (_repo_root() / gpkg_dir).resolve()
    else:
        gpkg_dir = gpkg_dir.resolve()

    if args.gpkg_path:
        paths = [Path(p) for p in args.gpkg_path]
    else:
        paths = sorted(gpkg_dir.glob("*.gpkg"))

    resolved: list[Path] = []
    for p in paths:
        q = p.resolve() if p.is_absolute() else (_repo_root() / p).resolve()
        if not q.is_file():
            raise SystemExit(f"GPKG not found: {q}")
        resolved.append(q)
    paths = resolved

    if not paths:
        raise SystemExit(f"No .gpkg files under {gpkg_dir}")

    layer_override = args.gpkg_layer if len(paths) == 1 else None
    if len(paths) > 1 and args.gpkg_layer:
        print("Note: --gpkg-layer ignored when multiple --gpkg-path; using auto-detect per file.")

    print("Loading GeoPackage(s) into memory...")
    rows, gpkg_notes = load_merged_staging_rows(paths, layer_override)
    for line in gpkg_notes:
        print(f"  {line}")
    if not rows:
        raise SystemExit("No parcel rows loaded from any GPKG (need parcelnumb + scity on a features layer).")
    print(f"  merged {len(rows):,} unique (apn, scity_norm) rows for staging")

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for t in rows:
        w.writerow(["" if v is None else v for v in t])
    buf.seek(0)

    schema, table = args.db_schema, args.db_table

    ddl_stmts = [
        """
        CREATE TEMP TABLE _gpkg_enrich (
            apn text NOT NULL,
            scity_norm text NOT NULL,
            address text,
            city text,
            scity_raw text,
            lat double precision,
            lon double precision,
            sqft integer,
            building_area integer,
            yearbuilt integer,
            zoning text
        ) ON COMMIT DROP
        """,
        "CREATE INDEX _gpkg_enrich_pair ON _gpkg_enrich (apn, scity_norm)",
        "CREATE INDEX _gpkg_enrich_apn ON _gpkg_enrich (apn)",
        """
        CREATE TEMP TABLE _gpkg_by_pair ON COMMIT DROP AS
        SELECT DISTINCT ON (apn, scity_norm)
            apn, scity_norm, address, city, scity_raw, lat, lon, sqft, building_area, yearbuilt, zoning
        FROM _gpkg_enrich
        ORDER BY apn, scity_norm
        """,
        "CREATE UNIQUE INDEX _gpkg_by_pair_key ON _gpkg_by_pair (apn, scity_norm)",
        """
        CREATE TEMP TABLE _gpkg_singleton ON COMMIT DROP AS
        SELECT DISTINCT ON (e.apn)
            e.apn, e.scity_norm, e.address, e.city, e.scity_raw, e.lat, e.lon,
            e.sqft, e.building_area, e.yearbuilt, e.zoning
        FROM _gpkg_enrich e
        INNER JOIN (
            SELECT apn
            FROM _gpkg_enrich
            GROUP BY apn
            HAVING COUNT(DISTINCT scity_norm) = 1
        ) u ON u.apn = e.apn
        ORDER BY e.apn, e.scity_norm
        """,
        "CREATE INDEX _gpkg_singleton_apn ON _gpkg_singleton (apn)",
        """
        CREATE TEMP TABLE _gpkg_by_apn ON COMMIT DROP AS
        SELECT DISTINCT ON (apn)
            apn, scity_norm, address, city, scity_raw, lat, lon, sqft, building_area, yearbuilt, zoning
        FROM _gpkg_enrich
        ORDER BY apn,
            (CASE WHEN scity_norm = '(NULL)' THEN 1 ELSE 0 END),
            scity_norm
        """,
        "CREATE UNIQUE INDEX _gpkg_by_apn_key ON _gpkg_by_apn (apn)",
    ]

    scity_expr = """
    CASE
        WHEN NULLIF(TRIM(u.scity), '') IS NOT NULL THEN UPPER(
            TRIM(REGEXP_REPLACE(REPLACE(TRIM(u.scity), '-', ' '), '\\s+', ' ', 'g'))
        )
        ELSE '(NULL)'
    END
    """

    all_gpkg_specs = _all_gpkg_compare_specs()
    needs_any = _needs_any_sql_from_specs(all_gpkg_specs)
    gpkg_can_fill = _gpkg_can_fill_sql_from_specs(all_gpkg_specs, "g")
    gpkg_can_fill_s = _gpkg_can_fill_sql_from_specs(all_gpkg_specs, "s")
    gpkg_can_fill_a = _gpkg_can_fill_sql_from_specs(all_gpkg_specs, "a")

    upd_pair = f"""
    UPDATE {schema}.{table} u
    SET
        address = CASE
            WHEN u.address IS NULL OR TRIM(u.address::text) = '' THEN COALESCE(g.address, u.address)
            ELSE u.address END,
        city = CASE
            WHEN u.city IS NULL OR TRIM(u.city::text) = '' THEN COALESCE(g.city, u.city)
            ELSE u.city END,
        scity = CASE
            WHEN u.scity IS NULL OR TRIM(u.scity::text) = '' THEN COALESCE(g.scity_raw, u.scity)
            ELSE u.scity END,
        lat = COALESCE(u.lat, g.lat),
        lon = COALESCE(u.lon, g.lon),
        sqft = CASE WHEN u.sqft IS NULL OR u.sqft = 0 THEN COALESCE(g.sqft, u.sqft) ELSE u.sqft END,
        building_area = CASE
            WHEN u.building_area IS NULL OR u.building_area = 0 THEN COALESCE(g.building_area, u.building_area)
            ELSE u.building_area END,
        yearbuilt = CASE
            WHEN u.yearbuilt IS NULL OR u.yearbuilt = 0 THEN COALESCE(g.yearbuilt, u.yearbuilt) ELSE u.yearbuilt END,
        zoning = CASE
            WHEN u.zoning IS NULL OR TRIM(u.zoning::text) = '' THEN COALESCE(g.zoning, u.zoning)
            ELSE u.zoning END,
        updated_at = NOW()
    FROM _gpkg_by_pair g
    WHERE {needs_any}
      AND ({gpkg_can_fill})
      AND u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
      AND upper(trim(u.parcelnumb)) = g.apn
      AND ({scity_expr}) = g.scity_norm
    """

    upd_single = f"""
    UPDATE {schema}.{table} u
    SET
        address = CASE
            WHEN u.address IS NULL OR TRIM(u.address::text) = '' THEN COALESCE(s.address, u.address)
            ELSE u.address END,
        city = CASE
            WHEN u.city IS NULL OR TRIM(u.city::text) = '' THEN COALESCE(s.city, u.city)
            ELSE u.city END,
        scity = CASE
            WHEN u.scity IS NULL OR TRIM(u.scity::text) = '' THEN COALESCE(s.scity_raw, u.scity)
            ELSE u.scity END,
        lat = COALESCE(u.lat, s.lat),
        lon = COALESCE(u.lon, s.lon),
        sqft = CASE WHEN u.sqft IS NULL OR u.sqft = 0 THEN COALESCE(s.sqft, u.sqft) ELSE u.sqft END,
        building_area = CASE
            WHEN u.building_area IS NULL OR u.building_area = 0 THEN COALESCE(s.building_area, u.building_area)
            ELSE u.building_area END,
        yearbuilt = CASE
            WHEN u.yearbuilt IS NULL OR u.yearbuilt = 0 THEN COALESCE(s.yearbuilt, u.yearbuilt) ELSE u.yearbuilt END,
        zoning = CASE
            WHEN u.zoning IS NULL OR TRIM(u.zoning::text) = '' THEN COALESCE(s.zoning, u.zoning)
            ELSE u.zoning END,
        updated_at = NOW()
    FROM _gpkg_singleton s
    WHERE {needs_any}
      AND ({gpkg_can_fill_s})
      AND u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
      AND upper(trim(u.parcelnumb)) = s.apn
      AND NOT EXISTS (
          SELECT 1 FROM _gpkg_by_pair g2
          WHERE g2.apn = upper(trim(u.parcelnumb))
            AND g2.scity_norm = ({scity_expr})
      )
    """

    upd_apn = f"""
    UPDATE {schema}.{table} u
    SET
        address = CASE
            WHEN u.address IS NULL OR TRIM(u.address::text) = '' THEN COALESCE(a.address, u.address)
            ELSE u.address END,
        city = CASE
            WHEN u.city IS NULL OR TRIM(u.city::text) = '' THEN COALESCE(a.city, u.city)
            ELSE u.city END,
        scity = CASE
            WHEN u.scity IS NULL OR TRIM(u.scity::text) = '' THEN COALESCE(a.scity_raw, u.scity)
            ELSE u.scity END,
        lat = COALESCE(u.lat, a.lat),
        lon = COALESCE(u.lon, a.lon),
        sqft = CASE WHEN u.sqft IS NULL OR u.sqft = 0 THEN COALESCE(a.sqft, u.sqft) ELSE u.sqft END,
        building_area = CASE
            WHEN u.building_area IS NULL OR u.building_area = 0 THEN COALESCE(a.building_area, u.building_area)
            ELSE u.building_area END,
        yearbuilt = CASE
            WHEN u.yearbuilt IS NULL OR u.yearbuilt = 0 THEN COALESCE(a.yearbuilt, u.yearbuilt) ELSE u.yearbuilt END,
        zoning = CASE
            WHEN u.zoning IS NULL OR TRIM(u.zoning::text) = '' THEN COALESCE(a.zoning, u.zoning)
            ELSE u.zoning END,
        updated_at = NOW()
    FROM _gpkg_by_apn a
    WHERE {needs_any}
      AND ({gpkg_can_fill_a})
      AND u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
      AND upper(trim(u.parcelnumb)) = a.apn
    """

    count_apn = f"""
    SELECT count(*)::bigint FROM {schema}.{table} u
    INNER JOIN _gpkg_by_apn a ON upper(trim(u.parcelnumb)) = a.apn
    WHERE {needs_any}
      AND ({gpkg_can_fill_a})
      AND u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
    """

    count_pair = f"""
    SELECT count(*)::bigint FROM {schema}.{table} u
    INNER JOIN _gpkg_by_pair g ON upper(trim(u.parcelnumb)) = g.apn AND ({scity_expr}) = g.scity_norm
    WHERE {needs_any}
      AND ({gpkg_can_fill})
      AND u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
    """

    count_single = f"""
    SELECT count(*)::bigint FROM {schema}.{table} u
    INNER JOIN _gpkg_singleton s ON upper(trim(u.parcelnumb)) = s.apn
    WHERE {needs_any}
      AND ({gpkg_can_fill_s})
      AND u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
      AND NOT EXISTS (
          SELECT 1 FROM _gpkg_by_pair g2
          WHERE g2.apn = upper(trim(u.parcelnumb))
            AND g2.scity_norm = ({scity_expr})
      )
    """

    conn = psycopg.connect(**DEFAULT_DB_CONFIG)
    conn.autocommit = False
    field_rows_before: list[FieldRow] | None = None
    try:
        for stmt in ddl_stmts[:3]:
            conn.execute(stmt)
        buf.seek(0)
        with conn.cursor() as cur:
            with cur.copy(
                "COPY _gpkg_enrich (apn, scity_norm, address, city, scity_raw, lat, lon, sqft, building_area, yearbuilt, zoning) FROM STDIN WITH (FORMAT csv, NULL '')"
            ) as copy:
                while True:
                    chunk = buf.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    copy.write(chunk)
        for stmt in ddl_stmts[3:]:
            conn.execute(stmt)

        n_pair = conn.execute(count_pair).fetchone()[0]
        n_single = conn.execute(count_single).fetchone()[0]
        n_apn = conn.execute(count_apn).fetchone()[0]
        count_matched_pair = f"""
        SELECT COUNT(*)::bigint FROM {schema}.{table} u
        INNER JOIN _gpkg_by_pair g ON upper(trim(u.parcelnumb)) = g.apn AND ({scity_expr}) = g.scity_norm
        WHERE u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
        """
        count_matched_single = f"""
        SELECT COUNT(*)::bigint FROM {schema}.{table} u
        INNER JOIN _gpkg_singleton s ON upper(trim(u.parcelnumb)) = s.apn
        WHERE u.parcelnumb IS NOT NULL AND TRIM(u.parcelnumb::text) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM _gpkg_by_pair g2
              WHERE g2.apn = upper(trim(u.parcelnumb))
                AND g2.scity_norm = ({scity_expr})
          )
        """
        n_join_pair = conn.execute(count_matched_pair).fetchone()[0]
        n_join_single = conn.execute(count_matched_single).fetchone()[0]
        print(
            f"Unidata rows joined to GPKG (pair): {int(n_join_pair):,}; "
            f"singleton fallback pool: {int(n_join_single):,}"
        )
        print(
            "Rows that would still receive UPDATE on --apply (any listed field missing + GPKG has value): "
            f"pair {int(n_pair):,}; singleton {int(n_single):,}; apn-only {int(n_apn):,}"
        )

        if not args.no_report:
            field_rows_before = write_gpkg_fill_report(
                conn,
                out_root,
                schema,
                table,
                scity_expr,
                args.preview_limit,
                len(rows),
                dry_run=dry_run,
            )
            print(f"Wrote {out_root / 'report.html'}")
            print(f"Wrote {out_root / 'report_before_update.html'}")
            print(f"Wrote {out_root / 'unidata_columns_missing_step1.csv'}")
            print(f"Wrote {out_root / 'unidata_gpkg_field_comparison.csv'}")
            print(f"Wrote {out_root / 'unidata_gpkg_gap_detail_sample.csv'}")

        if dry_run:
            if not args.no_report and field_rows_before is not None:
                write_gpkg_before_after_final_html(
                    out_root, field_rows_before, field_rows_before, dry_run=True
                )
                print(f"Wrote {out_root / 'report_before_after.html'}")
            conn.rollback()
            print("Dry run complete (rolled back). Pass --apply to UPDATE unidata.")
        else:
            r1 = conn.execute(upd_pair).rowcount
            r2 = conn.execute(upd_single).rowcount
            r3 = conn.execute(upd_apn).rowcount
            conn.commit()
            print(f"Applied: pass 1 (pair) rowcount={r1}; pass 2 (singleton) rowcount={r2}; pass 3 (apn-only) rowcount={r3}.")
            if not args.no_report and field_rows_before is not None:
                field_rows_after = compute_field_rows(schema, table, DEFAULT_DB_CONFIG)
                write_unidata_missingness_html(
                    out_root,
                    schema,
                    table,
                    "report_after_update.html",
                    "After GPKG apply: missing Unidata columns (excluding footprints)",
                    subtitle="Post-commit snapshot: reflects Unidata after this run’s UPDATE statements.",
                    field_rows=field_rows_after,
                )
                print(f"Wrote {out_root / 'report_after_update.html'}")
                write_gpkg_before_after_final_html(
                    out_root, field_rows_before, field_rows_after, dry_run=False
                )
                print(f"Wrote {out_root / 'report_before_after.html'}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
