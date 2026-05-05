from __future__ import annotations

import argparse
import csv
import html
import sqlite3
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import psycopg


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


DEFAULT_DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "parcelz",
    "user": "parcelz",
    "password": "INz3TzaMQIK2RLu0Xu31UTbgYRsq",
}


@dataclass
class CityStats:
    scity: str
    row_count: int
    footprints_empty: int
    building_area_empty: int
    fldzone_empty: int
    alquist_fault_empty: int
    liquefaction_empty: int
    landslide_empty: int
    fhszsra_empty: int
    fhszlra_empty: int


def normalize_city(value: str | None) -> str:
    if value is None:
        return "(NULL)"
    cleaned = " ".join(value.strip().replace("-", " ").split())
    return cleaned.upper() if cleaned else "(EMPTY)"


def read_gpkg_stats(gpkg_path: Path, layer: str, exclude_null_parcelnumb: bool = True) -> Dict[str, CityStats]:
    conn = sqlite3.connect(str(gpkg_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    where_clause = ""
    if exclude_null_parcelnumb:
        where_clause = "WHERE parcelnumb IS NOT NULL AND TRIM(CAST(parcelnumb AS TEXT)) <> ''"
    cur.execute(
        f"""
        SELECT
            COALESCE(NULLIF(TRIM(scity), ''), '(NULL)') AS city_key,
            COUNT(*) AS row_count
        FROM {layer}
        {where_clause}
        GROUP BY city_key
        """
    )

    out: Dict[str, CityStats] = {}
    for row in cur.fetchall():
        city = normalize_city(row["city_key"])
        current = out.get(city)
        if current is None:
            out[city] = CityStats(
                scity=city,
                row_count=row["row_count"] or 0,
                footprints_empty=0,
                building_area_empty=0,
                fldzone_empty=0,
                alquist_fault_empty=0,
                liquefaction_empty=0,
                landslide_empty=0,
                fhszsra_empty=0,
                fhszlra_empty=0,
            )
        else:
            current.row_count += row["row_count"] or 0
    conn.close()
    return out


def read_unidata_stats(schema: str, table: str, db_config: dict) -> Dict[str, CityStats]:
    conn = psycopg.connect(**db_config)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            COALESCE(NULLIF(TRIM(scity), ''), '(NULL)') AS city_key,
            COUNT(*) AS row_count,
            SUM(
                CASE
                    WHEN footprints IS NULL OR cardinality(footprints) = 0
                    THEN 1
                    ELSE 0
                END
            ) AS footprints_empty,
            SUM(
                CASE
                    WHEN building_area IS NULL
                        OR TRIM(CAST(building_area AS TEXT)) = ''
                        OR building_area = 0
                    THEN 1
                    ELSE 0
                END
            ) AS building_area_empty,
            SUM(CASE WHEN fldzone IS NULL OR TRIM(CAST(fldzone AS TEXT)) = '' THEN 1 ELSE 0 END) AS fldzone_empty,
            SUM(CASE WHEN alquist_fault IS NULL OR TRIM(CAST(alquist_fault AS TEXT)) = '' THEN 1 ELSE 0 END) AS alquist_fault_empty,
            SUM(CASE WHEN liquefaction IS NULL OR TRIM(CAST(liquefaction AS TEXT)) = '' THEN 1 ELSE 0 END) AS liquefaction_empty,
            SUM(CASE WHEN landslide IS NULL OR TRIM(CAST(landslide AS TEXT)) = '' THEN 1 ELSE 0 END) AS landslide_empty,
            SUM(CASE WHEN fhszsra IS NULL OR TRIM(CAST(fhszsra AS TEXT)) = '' THEN 1 ELSE 0 END) AS fhszsra_empty,
            SUM(CASE WHEN fhszlra IS NULL OR TRIM(CAST(fhszlra AS TEXT)) = '' THEN 1 ELSE 0 END) AS fhszlra_empty
        FROM {schema}.{table}
        GROUP BY city_key
        """
    )

    out: Dict[str, CityStats] = {}
    for row in cur.fetchall():
        city = normalize_city(row[0])
        current = out.get(city)
        if current is None:
            out[city] = CityStats(
                scity=city,
                row_count=row[1] or 0,
                footprints_empty=row[2] or 0,
                building_area_empty=row[3] or 0,
                fldzone_empty=row[4] or 0,
                alquist_fault_empty=row[5] or 0,
                liquefaction_empty=row[6] or 0,
                landslide_empty=row[7] or 0,
                fhszsra_empty=row[8] or 0,
                fhszlra_empty=row[9] or 0,
            )
        else:
            current.row_count += row[1] or 0
            current.footprints_empty += row[2] or 0
            current.building_area_empty += row[3] or 0
            current.fldzone_empty += row[4] or 0
            current.alquist_fault_empty += row[5] or 0
            current.liquefaction_empty += row[6] or 0
            current.landslide_empty += row[7] or 0
            current.fhszsra_empty += row[8] or 0 
            current.fhszlra_empty += row[9] or 0
    conn.close()
    return out


def pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def merge_rows(
    gpkg_stats: Dict[str, CityStats],
    unidata_stats: Dict[str, CityStats],
) -> List[dict]:
    cities = sorted(set(gpkg_stats.keys()) | set(unidata_stats.keys()))
    rows: List[dict] = []

    for city in cities:
        g = gpkg_stats.get(city, CityStats(city, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        u = unidata_stats.get(city, CityStats(city, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        rows.append(
            {
                "city": city,
                "unidata_rows": u.row_count,
                "expected_gpkg_rows": g.row_count,
                "row_delta": u.row_count - g.row_count,
                "footprints_empty": u.footprints_empty,
                "building_area_empty": u.building_area_empty,
                "fldzone_empty": u.fldzone_empty,
                "alquist_fault_empty": u.alquist_fault_empty,
                "liquefaction_empty": u.liquefaction_empty,
                "landslide_empty": u.landslide_empty,
                "fhszsra_empty": u.fhszsra_empty,
                "fhszlra_empty": u.fhszlra_empty,
            }
        )
    return rows


def add_total_row(rows: List[dict]) -> List[dict]:
    total = {
        "city": "TOTAL",
        "unidata_rows": 0,
        "expected_gpkg_rows": 0,
        "row_delta": 0,
        "footprints_empty": 0,
        "building_area_empty": 0,
        "fldzone_empty": 0,
        "alquist_fault_empty": 0,
        "liquefaction_empty": 0,
        "landslide_empty": 0,
        "fhszsra_empty": 0,
        "fhszlra_empty": 0,
    }

    for row in rows:
        for key in total:
            if key == "city":
                continue
            total[key] += row[key]

    return rows + [total]


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row_delta_breakdown_panel(rows: Iterable[dict]) -> str:
    """HTML panel explaining net row_delta as shortfalls minus surpluses per city."""
    rows = list(rows)
    data = [r for r in rows if str(r.get("city", "")).upper() != "TOTAL"]

    def as_int(row: dict, key: str) -> int:
        try:
            return int(row[key])
        except (TypeError, ValueError):
            return 0

    neg = [r for r in data if as_int(r, "row_delta") < 0]
    pos = [r for r in data if as_int(r, "row_delta") > 0]
    neg.sort(key=lambda r: as_int(r, "row_delta"))
    pos.sort(key=lambda r: -as_int(r, "row_delta"))

    sum_neg = sum(as_int(r, "row_delta") for r in neg)
    sum_pos = sum(as_int(r, "row_delta") for r in pos)
    net = sum_neg + sum_pos

    def esc(value: object) -> str:
        return html.escape(str(value))

    def table_for(caption: str, subset: List[dict], cols: Tuple[str, ...]) -> str:
        if not subset:
            return f"<p class='hint'>{esc(caption)}: none.</p>"
        header = "".join(f"<th>{esc(c)}</th>" for c in cols)
        body_lines: List[str] = []
        for r in subset:
            cells = "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols)
            body_lines.append(f"<tr>{cells}</tr>")
        return f"""<p><strong>{esc(caption)}</strong> ({len(subset)} cities)</p>
        <div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{"".join(body_lines)}</tbody></table></div>"""

    return f"""
    <section class="panel">
      <div class="panel-header"><h2>Row delta (net shortfall vs GPKG)</h2></div>
      <div class="panel-body">
        <p><code>row_delta</code> = <code>unidata_rows</code> − <code>expected_gpkg_rows</code> per city.
        Negative means Unidata has fewer parcels than the GPKG layer for that city key; positive means Unidata has more.</p>
        <p>The total row delta is the sum across cities: shortfalls ({esc(sum_neg)}) plus surpluses (+{esc(sum_pos)}) = <strong>{esc(net)}</strong>.</p>
        {table_for("Fewer rows in Unidata than GPKG (negative row_delta)", neg, ("city", "unidata_rows", "expected_gpkg_rows", "row_delta"))}
        {table_for("More rows in Unidata than GPKG (positive row_delta)", pos, ("city", "unidata_rows", "expected_gpkg_rows", "row_delta"))}
      </div>
    </section>
    """


def write_html(path: Path, rows: Iterable[dict], title: str = "Unidata v2.2 vs GPKG Audit") -> None:
    rows = list(rows)
    if not rows:
        return

    target_headers = [
        "city",
        "unidata_rows",
        "expected_gpkg_rows",
        "row_delta",
        "footprints_empty",
        "building_area_empty",
        "fldzone_empty",
        "alquist_fault_empty",
        "liquefaction_empty",
        "landslide_empty",
        "fhszsra_empty",
        "fhszlra_empty",
    ]
    description_map = {
        "city": "Normalized scity key used for grouping both datasets (scity only; no city fallback).",
        "unidata_rows": "Total rows found in the Unidata target table.",
        "expected_gpkg_rows": "Expected rows from the GPKG source table for this scity key.",
        "row_delta": "Difference: unidata_rows - expected_gpkg_rows (negative means missing in Unidata).",
        "footprints_empty": "Unidata rows where footprints is null or an empty varchar[] (no geometry strings).",
        "building_area_empty": "Unidata rows where building_area is null, blank, or zero (integer column; zero treated as empty).",
        "fldzone_empty": "Unidata rows where fldzone is null/blank.",
        "alquist_fault_empty": "Unidata rows where alquist_fault is null (boolean; FALSE counts as populated).",
        "liquefaction_empty": "Unidata rows where liquefaction is null (boolean; FALSE counts as populated).",
        "landslide_empty": "Unidata rows where landslide is null (boolean; FALSE counts as populated).",
        "fhszsra_empty": "Unidata rows where fhszsra is null or blank text (integer).",
        "fhszlra_empty": "Unidata rows where fhszlra is null or blank text (integer).",
    }
    def resolve_value(row: dict, col: str) -> object:
        return row.get(col, "")

    def esc(value: object) -> str:
        return html.escape(str(value))

    header_cells = "".join(
        f"<th onclick=\"sortTable({i})\" title=\"Click to sort\">{esc(col)}</th>"
        for i, col in enumerate(target_headers)
    )

    body_rows: List[str] = []
    key_column = "city"
    for row in rows:
        key_value = resolve_value(row, key_column)
        row_class = "total-row" if str(key_value).upper() == "TOTAL" else ""
        cells = "".join(f"<td>{esc(resolve_value(row, col))}</td>" for col in target_headers)
        body_rows.append(f"<tr class='{row_class}'>{cells}</tr>")

    glossary_rows = "".join(
        f"<tr><td><code>{esc(col)}</code></td><td>{esc(description_map.get(col, 'Field copied directly from source output table.'))}</td></tr>"
        for col in target_headers
    )

    delta_panel = row_delta_breakdown_panel(rows)

    generated_at = datetime.now().astimezone()
    generated_iso = generated_at.isoformat(timespec="seconds")
    generated_display = generated_at.strftime("%Y-%m-%d %H:%M:%S %Z (UTC%z)")

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #f3f5f9;
      --card: #ffffff;
      --muted: #6b7280;
      --text: #111827;
      --accent-2: #2d6cdf;
      --line: #e5eaf2;
      --good-bg: #e8f8ef;
      --good-text: #0f6a3b;
      --warn-bg: #fff7df;
      --warn-text: #8a5a00;
      --bad-bg: #ffe9e9;
      --bad-text: #9f1d1d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: radial-gradient(circle at top left, #eff4ff 0%, var(--bg) 42%, #eef3fb 100%);
      color: var(--text);
    }}
    .container {{
      max-width: 1520px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      background: linear-gradient(135deg, #17386f 0%, #2457a8 55%, #3273dd 100%);
      color: #fff;
      border-radius: 14px;
      padding: 24px 26px;
      box-shadow: 0 10px 30px rgba(25, 52, 102, 0.26);
      margin-bottom: 18px;
    }}
    .hero h1 {{
      margin: 0 0 8px 0;
      font-size: 30px;
      line-height: 1.2;
      letter-spacing: 0.2px;
    }}
    .hero p {{
      margin: 0;
      color: rgba(255, 255, 255, 0.92);
      max-width: 980px;
      line-height: 1.45;
    }}
    .hero-meta {{
      font-size: 13px;
      color: rgba(255, 255, 255, 0.88);
      margin: 0 0 14px 0;
      letter-spacing: 0.02em;
    }}
    .hero-meta time {{
      font-weight: 600;
      color: #fff;
    }}
    .hero-summary {{
      margin: 0;
      padding-top: 16px;
      border-top: 1px solid rgba(255, 255, 255, 0.22);
    }}
    .hero-summary p + p {{
      margin-top: 10px;
    }}
    .hero-summary strong {{
      color: #fff;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .kpi {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
    }}
    .kpi-label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.4px;
      margin-bottom: 6px;
    }}
    .kpi-value {{
      font-size: 27px;
      font-weight: 700;
      line-height: 1.1;
      color: #0f274d;
    }}
    .panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
      margin-bottom: 14px;
    }}
    .panel-header {{
      padding: 14px 16px 8px 16px;
      border-bottom: 1px solid var(--line);
    }}
    .panel h2 {{
      margin: 0;
      font-size: 16px;
      color: #173a73;
    }}
    .panel-body {{ padding: 12px 16px 16px 16px; }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .controls input {{
      padding: 9px 11px;
      min-width: 280px;
      border: 1px solid #cfd8e5;
      border-radius: 8px;
      font-size: 14px;
      outline: none;
      background: #fff;
    }}
    .controls input:focus {{
      border-color: var(--accent-2);
      box-shadow: 0 0 0 3px rgba(45, 108, 223, 0.15);
    }}
    .chip {{
      font-size: 12px;
      color: var(--muted);
      border: 1px solid #d8dfeb;
      padding: 6px 10px;
      border-radius: 999px;
      background: #f8fbff;
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 68vh;
      border-radius: 12px;
      border: 1px solid var(--line);
    }}
    table {{
      width: max-content;
      min-width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      background: #fff;
    }}
    th, td {{
      border-bottom: 1px solid #e7edf6;
      padding: 9px 11px;
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{
      position: sticky;
      top: 0;
      background: #183c75;
      color: #fff;
      cursor: pointer;
      user-select: none;
      z-index: 2;
      font-weight: 600;
      letter-spacing: 0.2px;
    }}
    tbody tr:nth-child(odd) td {{ background: #fcfdff; }}
    tbody tr:hover td {{ background: #eef4ff; }}
    .total-row td {{
      font-weight: 700;
      background: #e7f7f3 !important;
      border-top: 2px solid #3bb69d;
    }}
    .hint {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 8px;
    }}
    .metric-good {{ background: var(--good-bg) !important; color: var(--good-text); font-weight: 700; }}
    .metric-warn {{ background: var(--warn-bg) !important; color: var(--warn-text); font-weight: 700; }}
    .metric-bad {{ background: var(--bad-bg) !important; color: var(--bad-text); font-weight: 700; }}
  </style>
</head>
<body>
  <div class="container">
    <section class="hero">
      <h1>{esc(title)}</h1>
      <p class="hero-meta">Report generated: <time datetime="{esc(generated_iso)}">{esc(generated_display)}</time></p>
      <div class="hero-summary">
        <p><strong>What this is:</strong> A parcel-level audit that compares the Unidata target table (PostgreSQL) to the source GeoPackage layer, grouped by normalized <code style="background:rgba(0,0,0,.15);padding:2px 6px;border-radius:4px;">scity</code> only (no <code>city</code> fallback; blank <code>scity</code> → <code>(NULL)</code>). Hyphens are normalized to spaces before grouping. Row counts and completeness checks are computed when you run <code style="background:rgba(0,0,0,.15);padding:2px 6px;border-radius:4px;">audit_unidata_vs_gpkg.py</code>.</p>
        <p><strong>How to read the table:</strong> <em>Row delta</em> is Unidata rows minus expected GPKG rows per normalized <code>scity</code> (negative ⇒ fewer parcels in Unidata than in the source for that key). Columns ending in <em>_empty</em> count Unidata rows missing that attribute, using the rules in &ldquo;Column meanings&rdquo; below.</p>
        <p>This HTML matches the exported CSV schema; regenerate both files together so timestamps stay in sync.</p>
      </div>
    </section>
    <section class="grid">
      <div class="kpi"><div class="kpi-label">Total Cities</div><div class="kpi-value" id="kpiCities">-</div></div>
      <div class="kpi"><div class="kpi-label">Source Rows</div><div class="kpi-value" id="kpiSourceRows">-</div></div>
      <div class="kpi"><div class="kpi-label">Target Rows</div><div class="kpi-value" id="kpiTargetRows">-</div></div>
      <div class="kpi"><div class="kpi-label">Total Row Delta</div><div class="kpi-value" id="kpiDelta">-</div></div>
    </section>
{delta_panel}
    <div class="panel">
      <div class="panel-header"><h2>Controls</h2></div>
      <div class="panel-body">
        <div class="controls">
          <label for="cityFilter"><strong>Filter first column:</strong></label>
          <input id="cityFilter" type="text" placeholder="Type to filter rows" onkeyup="filterCity()" />
          <span class="chip">Click header to sort</span>
          <span class="chip">Dynamic columns from CSV schema</span>
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-header"><h2>Column meanings</h2></div>
      <div class="panel-body">
        <div class="table-wrap">
          <table>
            <thead><tr><th>Column</th><th>Meaning</th></tr></thead>
            <tbody>
              {glossary_rows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-header"><h2>Audit Table</h2></div>
      <div class="panel-body">
        <div class="table-wrap">
          <table id="auditTable">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>
{''.join(body_rows)}
            </tbody>
          </table>
        </div>
        <div class="hint">Tip: click any header to sort ascending/descending.</div>
      </div>
    </div>
  </div>
  <script>
    const headers = {target_headers!r};
    let sortDir = {{}};

    function toSortableValue(v) {{
      const n = Number(v);
      if (!Number.isNaN(n)) return n;
      return v.toString().toLowerCase();
    }}

    function sortTable(colIdx) {{
      const table = document.getElementById("auditTable");
      const tbody = table.tBodies[0];
      const rows = Array.from(tbody.rows);
      sortDir[colIdx] = !sortDir[colIdx];
      const dir = sortDir[colIdx] ? 1 : -1;

      rows.sort((a, b) => {{
        const av = toSortableValue(a.cells[colIdx].innerText.trim());
        const bv = toSortableValue(b.cells[colIdx].innerText.trim());
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return 0;
      }});

      rows.forEach(r => tbody.appendChild(r));
    }}

    function filterCity() {{
      const filter = document.getElementById("cityFilter").value.toLowerCase();
      const table = document.getElementById("auditTable");
      const rows = table.tBodies[0].rows;
      for (let i = 0; i < rows.length; i++) {{
        const key = rows[i].cells[0].innerText.toLowerCase();
        rows[i].style.display = key.includes(filter) ? "" : "none";
      }}
    }}

    function colorizeMetrics() {{
      const table = document.getElementById("auditTable");
      const rows = table.tBodies[0].rows;
      const deltaIdx = headers.indexOf("row_delta");
      for (let i = 0; i < rows.length; i++) {{
        const row = rows[i];
        if (deltaIdx >= 0) {{
          const d = Number(row.cells[deltaIdx].innerText);
          if (!Number.isNaN(d)) {{
            if (Math.abs(d) <= 50) row.cells[deltaIdx].classList.add("metric-good");
            else if (Math.abs(d) <= 500) row.cells[deltaIdx].classList.add("metric-warn");
            else row.cells[deltaIdx].classList.add("metric-bad");
          }}
        }}
      }}
    }}

    function numberFmt(v) {{
      const n = Number(v);
      return Number.isNaN(n) ? "-" : n.toLocaleString("en-US");
    }}

    function fillKpis() {{
      const rows = Array.from(document.getElementById("auditTable").tBodies[0].rows);
      const dataRows = rows.filter(r => !r.classList.contains("total-row"));
      const totalRow = rows.find(r => r.classList.contains("total-row"));
      document.getElementById("kpiCities").innerText = numberFmt(dataRows.length);

      if (!totalRow) return;
      const sourceIdx = headers.indexOf("expected_gpkg_rows");
      const targetIdx = headers.indexOf("unidata_rows");
      const deltaIdx = headers.indexOf("row_delta");

      if (sourceIdx >= 0) document.getElementById("kpiSourceRows").innerText = numberFmt(totalRow.cells[sourceIdx].innerText);
      if (targetIdx >= 0) document.getElementById("kpiTargetRows").innerText = numberFmt(totalRow.cells[targetIdx].innerText);
      if (deltaIdx >= 0) document.getElementById("kpiDelta").innerText = numberFmt(totalRow.cells[deltaIdx].innerText);
    }}

    colorizeMetrics();
    fillKpis();
  </script>
</body>
</html>
"""

    path.write_text(html_text, encoding="utf-8")


def print_preview(rows: List[dict], max_rows: int = 15) -> None:
    preview = rows[:max_rows]
    headers = list(preview[0].keys()) if preview else []
    if not headers:
        print("No rows to show.")
        return

    widths = {h: max(len(h), *(len(str(r[h])) for r in preview)) for h in headers}
    print(" | ".join(h.ljust(widths[h]) for h in headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for row in preview:
        print(" | ".join(str(row[h]).ljust(widths[h]) for h in headers))
    if len(rows) > max_rows:
        print(f"... ({len(rows) - max_rows} more rows)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit unidata v2.2 against source gpkg by scity.")
    parser.add_argument(
        "--gpkg-path",
        default=str(_repo_root() / "data" / "ca_santa_clara_parcel_build_opt.gpkg"),
        help="Path to source gpkg file",
    )
    parser.add_argument(
        "--gpkg-layer",
        default="ca_santa_clara_parcel_build_opt",
        help="Layer/table name inside the gpkg",
    )
    parser.add_argument("--db-schema", default="public", help="Schema for unidata table")
    parser.add_argument("--db-table", default="unidata", help="Unidata table name")
    parser.add_argument(
        "--out-csv",
        default=str(_repo_root() / "outputs" / "parcel_audits" / "unidata_v22_vs_gpkg_audit.csv"),
        help="Output csv path",
    )
    parser.add_argument(
        "--out-html",
        default=str(_repo_root() / "outputs" / "parcel_audits" / "unidata_v22_vs_gpkg_audit.html"),
        help="Output html path",
    )
    parser.add_argument(
        "--include-null-parcelnumb",
        action="store_true",
        help="Include GPKG rows where parcelnumb is NULL/blank (disabled by default).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_csv = Path(args.out_csv)
    out_html = Path(args.out_html)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_html.parent.mkdir(parents=True, exist_ok=True)

    gpkg_stats = read_gpkg_stats(
        Path(args.gpkg_path),
        args.gpkg_layer,
        exclude_null_parcelnumb=not args.include_null_parcelnumb,
    )
    unidata_stats = read_unidata_stats(args.db_schema, args.db_table, DEFAULT_DB_CONFIG)

    rows = merge_rows(gpkg_stats, unidata_stats)
    rows = add_total_row(rows)
    write_csv(out_csv, rows)
    write_html(out_html, rows)
    print_preview(rows, max_rows=20)
    print(f"\nWrote full audit table to: {out_csv}")
    print(f"Wrote html audit report to: {out_html}")


if __name__ == "__main__":
    main()
