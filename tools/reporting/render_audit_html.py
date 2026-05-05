from __future__ import annotations

import argparse
import csv
import html
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render audit CSV as a styled HTML report.")
    parser.add_argument(
        "--input-csv",
        default=str(_repo_root() / "outputs" / "parcel_audits" / "unidata_v22_vs_gpkg_audit.csv"),
        help="Input CSV path",
    )
    parser.add_argument(
        "--output-html",
        default=str(_repo_root() / "outputs" / "parcel_audits" / "unidata_v22_vs_gpkg_audit.html"),
        help="Output HTML path",
    )
    return parser.parse_args()


def build_table(headers: list[str], rows: list[dict[str, str]]) -> str:
    th = "".join(
        f'<th onclick="sortTable({idx})" title="Click to sort">{html.escape(col)}</th>'
        for idx, col in enumerate(headers)
    )
    tr_rows: list[str] = []
    for row in rows:
        css = "total-row" if row.get("scity") == "TOTAL" else ""
        tds = "".join(f"<td>{html.escape(str(row.get(col, '')))}</td>" for col in headers)
        tr_rows.append(f"<tr class='{css}'>{tds}</tr>")
    tbody = "\n".join(tr_rows)
    return f"<table id='auditTable'><thead><tr>{th}</tr></thead><tbody>{tbody}</tbody></table>"


def build_html(headers: list[str], rows: list[dict[str, str]], source_csv: Path) -> str:
    table_html = build_table(headers, rows)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Unidata v2.2 vs GPKG Audit</title>
  <style>
    body {{
      font-family: "Segoe UI", Arial, sans-serif;
      margin: 20px;
      background: linear-gradient(180deg, #f5f7ff 0%, #eef6ff 100%);
      color: #1f2937;
    }}
    h1 {{
      margin: 0 0 8px 0;
      color: #0b3a66;
      letter-spacing: 0.2px;
    }}
    .meta {{ margin-bottom: 16px; color: #4b5563; }}
    .controls {{
      margin: 10px 0 14px 0;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .card {{
      background: #ffffff;
      border: 1px solid #dbe7ff;
      border-radius: 10px;
      box-shadow: 0 4px 14px rgba(33, 72, 131, 0.08);
      padding: 12px 14px;
      margin-bottom: 12px;
    }}
    .card h2 {{
      margin: 0 0 8px 0;
      font-size: 16px;
      color: #1d4f91;
    }}
    .card p {{
      margin: 6px 0;
      color: #374151;
      line-height: 1.45;
    }}
    .glossary {{
      margin-top: 8px;
      overflow: auto;
    }}
    .glossary table {{
      min-width: 780px;
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .glossary th, .glossary td {{
      text-align: left;
      border-bottom: 1px solid #e5e7eb;
      padding: 7px 8px;
      white-space: normal;
    }}
    .glossary th {{
      background: #f9fafb;
      position: static;
      cursor: default;
    }}
    input {{
      padding: 8px 10px;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      min-width: 260px;
      background: white;
    }}
    .table-wrap {{
      background: white;
      border: 1px solid #dbe7ff;
      border-radius: 10px;
      box-shadow: 0 4px 14px rgba(33, 72, 131, 0.08);
      overflow: auto;
      max-height: 75vh;
    }}
    table {{
      width: max-content;
      min-width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid #e7eefc;
      padding: 8px 10px;
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{
      position: sticky;
      top: 0;
      background: linear-gradient(180deg, #2e67aa 0%, #24558f 100%);
      color: #ffffff;
      cursor: pointer;
      user-select: none;
      z-index: 1;
    }}
    tbody tr:nth-child(odd) td {{ background: #fbfdff; }}
    tr:hover td {{ background: #eaf3ff; }}
    .total-row td {{
      font-weight: 700;
      background: #e5f7f4 !important;
      border-top: 2px solid #41b3a2;
    }}
    .hint {{
      color: #6b7280;
      font-size: 12px;
      margin-top: 8px;
    }}
    .metric-good {{
      background: #e7f8ee !important;
      color: #11643a;
      font-weight: 600;
    }}
    .metric-warn {{
      background: #fff7e1 !important;
      color: #8a5a00;
      font-weight: 600;
    }}
    .metric-bad {{
      background: #ffe8e8 !important;
      color: #9f1d1d;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <h1>Unidata v2.2 vs GPKG Audit</h1>
  <div class="card">
    <h2>How to read this table</h2>
    <p>This report compares <strong>target dataset</strong> (<code>unidata v2.2</code> in Postgres) against the <strong>full source dataset</strong> (<code>gpkg</code> file), grouped by <code>scity</code>.</p>
    <p>Use <code>coverage_pct</code> to see whether unidata has the expected number of rows for a city. A value below 100% means rows are missing in unidata; above 100% means unidata has more rows than the gpkg source for that city.</p>
    <p>Non-empty columns (like <code>gpkg_address_nonempty</code>) show data completeness for key fields. The <code>TOTAL</code> row summarizes all cities.</p>
  </div>
  <div class="card glossary">
    <h2>Column glossary</h2>
    <table>
      <thead>
        <tr><th>Column</th><th>Meaning</th></tr>
      </thead>
      <tbody>
        <tr><td><code>scity</code></td><td>City key used for grouping (normalized from <code>scity</code>, with fallback to <code>city</code>).</td></tr>
        <tr><td><code>gpkg_rows</code></td><td>Total rows in source gpkg for this city.</td></tr>
        <tr><td><code>unidata_rows</code></td><td>Total rows in target <code>unidata v2.2</code> for this city.</td></tr>
        <tr><td><code>coverage_pct</code></td><td><code>unidata_rows / gpkg_rows * 100</code>. Quick coverage indicator.</td></tr>
        <tr><td><code>rows_delta</code></td><td><code>unidata_rows - gpkg_rows</code>. Negative = missing rows, positive = extra rows.</td></tr>
        <tr><td><code>*_address_nonempty</code></td><td>Rows where address field is present (not null/blank).</td></tr>
        <tr><td><code>*_address_fill_pct</code></td><td>Address completeness percentage in each dataset.</td></tr>
        <tr><td><code>*_zoning_nonempty</code></td><td>Rows where zoning value is present.</td></tr>
        <tr><td><code>*_yearbuilt_nonempty</code></td><td>Rows where year built is present.</td></tr>
        <tr><td><code>*_lat_nonempty</code> / <code>*_lon_nonempty</code></td><td>Rows with latitude/longitude present.</td></tr>
        <tr><td><code>*_sqft_nonempty</code></td><td>Rows where square footage is present.</td></tr>
      </tbody>
    </table>
  </div>
  <div class="controls">
    <label for="cityFilter"><strong>Filter by city:</strong></label>
    <input id="cityFilter" type="text" placeholder="Type city name (e.g., SAN JOSE)" onkeyup="filterCity()" />
  </div>
  <div class="table-wrap">
    {table_html}
  </div>
  <div class="hint">Tip: click any header to sort ascending/descending.</div>

  <script>
    let sortDir = {{}};
    const headers = {headers!r};

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
        const city = rows[i].cells[0].innerText.toLowerCase();
        rows[i].style.display = city.includes(filter) ? "" : "none";
      }}
    }}

    function colorizeMetrics() {{
      const table = document.getElementById("auditTable");
      const rows = table.tBodies[0].rows;
      const coverageIdx = headers.indexOf("coverage_pct");
      const deltaIdx = headers.indexOf("rows_delta");
      for (let i = 0; i < rows.length; i++) {{
        const row = rows[i];
        if (coverageIdx >= 0) {{
          const v = Number(row.cells[coverageIdx].innerText);
          if (!Number.isNaN(v)) {{
            if (v >= 99) row.cells[coverageIdx].classList.add("metric-good");
            else if (v >= 95) row.cells[coverageIdx].classList.add("metric-warn");
            else row.cells[coverageIdx].classList.add("metric-bad");
          }}
        }}
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

    colorizeMetrics();
  </script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    input_csv = Path(args.input_csv)
    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)

    with input_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames or []

    report = build_html(headers, rows, input_csv)
    output_html.write_text(report, encoding="utf-8")
    print(f"HTML report written to: {output_html}")


if __name__ == "__main__":
    main()
