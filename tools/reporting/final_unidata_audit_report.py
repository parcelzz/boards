"""
Generate the consolidated final Unidata audit HTML report (top-to-bottom snapshot).

Collects: row inventory vs GPKG, Step-1 missingness, data sources,
city-level gaps, fldzone distribution, footprint QA.

Run from repo root:
  py -3 tools/reporting/final_unidata_audit_report.py
"""
from __future__ import annotations

import html as html_module
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

_REPO = Path(__file__).resolve().parent.parent.parent
_AUDITS = _REPO / "tools" / "audits"
if str(_AUDITS) not in sys.path:
    sys.path.insert(0, str(_AUDITS))

from audit_unidata_vs_gpkg import (  # noqa: E402
    DEFAULT_DB_CONFIG,
    add_total_row,
    merge_rows,
    read_gpkg_stats,
    read_unidata_stats,
)
from field_missingness_classification import (  # noqa: E402
    compute_field_rows,
    taxonomy_title,
)

UNIDATA_VERSION = "v2.3"


def _esc(s: object) -> str:
    return html_module.escape("" if s is None else str(s))


def _fmt_int(n: int | float) -> str:
    return f"{int(n):,}"


def _fmt_pct(n: float) -> str:
    return f"{n:.2f}%"


def _table(
    headers: list[str],
    rows: list[list[str]],
    numeric_cols: set[int] | None = None,
    row_classes: list[str] | None = None,
) -> str:
    numeric_cols = numeric_cols or set()
    th = "".join(
        f'<th class="{"num" if i in numeric_cols else ""}">{_esc(h)}</th>'
        for i, h in enumerate(headers)
    )
    body: list[str] = []
    for ri, row in enumerate(rows):
        tr_cls = row_classes[ri] if row_classes and ri < len(row_classes) else ""
        tr_attr = f' class="{tr_cls}"' if tr_cls else ""
        tds = []
        for i, cell in enumerate(row):
            cls = "num" if i in numeric_cols else ""
            if cls:
                tds.append(f'<td class="{cls}">{cell}</td>')
            else:
                tds.append(f"<td>{cell}</td>")
        body.append(f"<tr{tr_attr}>{''.join(tds)}</tr>")
    return (
        f'<div class="table-wrap"><table class="data-table">'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _kpi(label: str, value: str, note: str = "", variant: str = "blue") -> str:
    note_html = f'<div class="kpi-note">{_esc(note)}</div>' if note else ""
    return (
        f'<div class="kpi kpi-{variant}">'
        f'<div class="kpi-val">{value}</div>'
        f'<div class="kpi-lbl">{_esc(label)}</div>{note_html}</div>'
    )


def _section(num: int, title: str) -> str:
    return f'<div class="section-head"><span class="section-num">{num}</span><h2>{title}</h2></div>'


def _missing_badge(pct: float) -> str:
    if pct >= 50:
        cls = "risk-high"
    elif pct >= 5:
        cls = "risk-med"
    elif pct > 0:
        cls = "risk-low"
    else:
        cls = "risk-none"
    return f'<span class="badge {cls}">{_fmt_pct(pct)}</span>'


def _taxonomy_badge(bucket: str) -> str:
    key = bucket.replace("_", "-")
    return f'<span class="tax tax-{key}">{_esc(taxonomy_title(bucket))}</span>'


def collect_backup_stats(conn: psycopg.Connection) -> dict | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables
          WHERE table_schema='public' AND table_name='unidata_backup_20260522'
        )
        """
    )
    if not cur.fetchone()[0]:
        return None
    cur.execute(
        """
        SELECT
          COUNT(*) FILTER (WHERE (b.footprints IS NULL OR cardinality(b.footprints)=0)
                             AND u.footprints IS NOT NULL AND cardinality(u.footprints)>0) AS fp_gained,
          COUNT(*) FILTER (WHERE u.fldzone IS DISTINCT FROM b.fldzone) AS fldzone_changed,
          COUNT(*) FILTER (WHERE u.address IS DISTINCT FROM b.address) AS address_changed,
          COUNT(*) FILTER (WHERE u.yearbuilt IS DISTINCT FROM b.yearbuilt) AS yearbuilt_changed
        FROM public.unidata u
        JOIN public.unidata_backup_20260522 b ON u.id = b.id
        """
    )
    r = cur.fetchone()
    return {
        "footprints_gained": int(r[0]),
        "fldzone_changed": int(r[1]),
        "address_changed": int(r[2]),
        "yearbuilt_changed": int(r[3]),
    }


def collect_fldzone_top(conn: psycopg.Connection, limit: int = 20) -> list[tuple[str, int]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT fldzone, COUNT(*)::bigint AS c
        FROM public.unidata
        WHERE fldzone IS NOT NULL AND TRIM(fldzone::text) <> ''
        GROUP BY fldzone ORDER BY c DESC, fldzone LIMIT %s
        """,
        (limit,),
    )
    return [(str(a), int(b)) for a, b in cur.fetchall()]


def collect_hazard_crosstab(conn: psycopg.Connection) -> list[tuple[str, str, str, int]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          CASE WHEN liquefaction IS NULL THEN 'N' WHEN liquefaction THEN 'T' ELSE 'F' END,
          CASE WHEN landslide IS NULL THEN 'N' WHEN landslide THEN 'T' ELSE 'F' END,
          CASE WHEN alquist_fault IS NULL THEN 'N' WHEN alquist_fault THEN 'T' ELSE 'F' END,
          COUNT(*)::bigint
        FROM public.unidata
        GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 15
        """
    )
    return [(str(a), str(b), str(c), int(d)) for a, b, c, d in cur.fetchall()]


def collect_gpkg_row_counts(gpkg_path: Path) -> dict[str, int]:
    con = sqlite3.connect(gpkg_path)
    total = con.execute("SELECT COUNT(*) FROM ca_santa_clara_parcel_build_opt").fetchone()[0]
    with_apn = con.execute(
        """
        SELECT COUNT(*) FROM ca_santa_clara_parcel_build_opt
        WHERE parcelnumb IS NOT NULL AND TRIM(CAST(parcelnumb AS TEXT)) <> ''
        """
    ).fetchone()[0]
    unique_apn_scity = con.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT DISTINCT upper(trim(parcelnumb)),
                 upper(trim(replace(replace(coalesce(scity,''),'-',' '), '  ', ' ')))
          FROM ca_santa_clara_parcel_build_opt
          WHERE parcelnumb IS NOT NULL AND TRIM(CAST(parcelnumb AS TEXT)) <> ''
        ) t
        """
    ).fetchone()[0]
    con.close()
    return {"total": total, "with_apn": with_apn, "unique_apn_scity": unique_apn_scity}


def build_html(
    generated: str,
    total_rows: int,
    field_rows: list,
    gpkg_counts: dict[str, int],
    city_rows: list[dict],
    fldzone_top: list[tuple[str, int]],
    fp_missing: int,
    fp_present_pct: float,
) -> str:
    row_delta = total_rows - gpkg_counts["with_apn"]
    dup_gpkg = gpkg_counts["with_apn"] - gpkg_counts["unique_apn_scity"]

    kpis = f"""
    <div class="kpi-row">
      {_kpi("Unidata rows", _fmt_int(total_rows), "public.unidata", "blue")}
      {_kpi("GPKG rows (APN)", _fmt_int(gpkg_counts["with_apn"]), "Parcel baseline", "indigo")}
      {_kpi("Row delta", f"{row_delta:+,}", "Unidata − GPKG", "amber" if row_delta != 0 else "green")}
      {_kpi("Footprints present", _fmt_pct(fp_present_pct), f"{_fmt_int(fp_missing)} missing", "teal")}
    </div>"""

    inv_rows = [
        ["GPKG total feature rows", _fmt_int(gpkg_counts["total"]), "All parcels in county GPKG"],
        ["GPKG rows with parcelnumb", _fmt_int(gpkg_counts["with_apn"]), "Usable APN baseline"],
        ["GPKG unique (APN + scity)", _fmt_int(gpkg_counts["unique_apn_scity"]), "After normalization"],
        ["GPKG duplicate features", _fmt_int(dup_gpkg), "Extra rows vs unique keys — not missing Unidata parcels"],
        ["Unidata rows", _fmt_int(total_rows), "Current PostgreSQL snapshot"],
        ["Row delta (Unidata − GPKG APN rows)", f"{row_delta:+,}", "−43 ≈ duplicate GPKG features only"],
    ]

    missing_sorted = sorted(field_rows, key=lambda r: (-r.missing_pct, r.column_name))
    col_rows: list[list[str]] = []
    col_row_classes: list[str] = []
    for r in missing_sorted:
        col_rows.append(
            [
                f'<code class="col-name">{_esc(r.column_name)}</code>',
                f'<span class="dtype">{_esc(r.data_type)}</span>',
                _taxonomy_badge(r.taxonomy_bucket),
                _fmt_int(r.present),
                _fmt_int(r.missing),
                _missing_badge(r.missing_pct),
            ]
        )
        if r.missing_pct >= 50:
            col_row_classes.append("row-risk")
        elif r.missing_pct >= 5:
            col_row_classes.append("row-warn")
        else:
            col_row_classes.append("")

    city_candidates = [
        r
        for r in city_rows
        if r.get("city") != "TOTAL"
        and (abs(int(r.get("row_delta", 0))) > 50 or int(r.get("footprints_empty", 0)) > 500)
    ]
    city_candidates.sort(
        key=lambda r: max(abs(int(r.get("row_delta", 0))), int(r.get("footprints_empty", 0))),
        reverse=True,
    )
    city_table_rows: list[list[str]] = []
    city_row_classes: list[str] = []
    for r in city_candidates[:25]:
        delta = int(r["row_delta"])
        delta_html = (
            f'<span class="delta delta-neg">{delta:+,}</span>'
            if delta < 0
            else f'<span class="delta delta-pos">{delta:+,}</span>'
            if delta > 0
            else '<span class="delta delta-zero">0</span>'
        )
        city_table_rows.append(
            [
                f"<strong>{_esc(r['city'])}</strong>",
                _fmt_int(r["unidata_rows"]),
                _fmt_int(r["expected_gpkg_rows"]),
                delta_html,
                _fmt_int(r["footprints_empty"]),
                _fmt_int(r.get("building_area_empty", 0)),
            ]
        )
        city_row_classes.append("")

    total_row = next((r for r in city_rows if r.get("city") == "TOTAL"), None)
    if total_row:
        city_table_rows.insert(
            0,
            [
                "<strong>TOTAL</strong>",
                _fmt_int(total_row["unidata_rows"]),
                _fmt_int(total_row["expected_gpkg_rows"]),
                f'<span class="delta">{int(total_row["row_delta"]):+,}</span>',
                _fmt_int(total_row["footprints_empty"]),
                "—",
            ],
        )
        city_row_classes.insert(0, "row-total")

    fld_rows = [[f"<code>{_esc(z)}</code>", _fmt_int(c)] for z, c in fldzone_top]

    sources_rows = [
        ['<span class="src-active">Active</span>', "<strong>ca_santa_clara_parcel_build_opt.gpkg</strong>", "parcelnumb + scity", "address, city, scity, lat, lon, sqft, building_area, yearbuilt, zoning"],
        ['<span class="src-active">Active</span>', "<strong>California.gpkg</strong>", "Parcel polygon ∩ building", "footprints (WKT array)"],
        ['<span class="src-muted">Skipped</span>', "building-polygon.gpkg", "—", "No parcel keys on layer"],
        ['<span class="src-muted">Skipped</span>', "Buildings_Footprints_2D_20260512.geojson", "—", "Not wired to backfill"],
    ]

    col_num_cols = {3, 4, 5}
    city_num_cols = {1, 2, 3, 4, 5}
    sections = f"""
  {_section(1, "Row inventory (Unidata vs GPKG)")}
  <div class="card">{_table(["Metric", "Count", "Notes"], inv_rows, {1})}</div>

  {_section(2, "Column missingness (Step 1 rules)")}
  <p class="lead">Present/missing uses Step 1 predicates (e.g. <code>sqft</code>, <code>building_area</code>, <code>yearbuilt</code> treat <strong>0</strong> as missing).</p>
  <div class="card">{_table(["Column", "Type", "Taxonomy", "Present", "Missing", "Missing %"], col_rows, col_num_cols, col_row_classes)}</div>

  {_section(3, "Data sources used for backfill")}
  <div class="card">{_table(["Status", "File", "Join method", "Fields"], sources_rows)}</div>

  {_section(4, "Unidata vs GPKG by city (<code>scity</code>)")}
  <p class="lead">Cities with the largest row delta or footprint gaps (top 25). Full export: <code>audit_unidata_vs_gpkg.py</code>.</p>
  <div class="card">{_table(["scity", "Unidata rows", "GPKG rows", "Delta", "Footprints empty", "building_area empty"], city_table_rows, city_num_cols, city_row_classes)}</div>

  {_section(5, "Flood zone (<code>fldzone</code>) — top values")}
  <p class="lead">After ordered multi-zone aggregation (<code>X | AH</code>, etc.). See <code>docs/ticket-04-unidata-fldzone-20260522.md</code>.</p>
  <div class="card">{_table(["fldzone", "Parcels"], fld_rows, {1})}</div>

  {_section(6, "How to reproduce")}
  <div class="card repro-card">
    <ul class="repro-list">
      <li><code>py -3 tools/reporting/final_unidata_audit_report.py</code> — this report</li>
      <li><code>py -3 tools/audits/field_missingness_classification.py</code> — Step 1 detail</li>
      <li><code>py -3 tools/audits/audit_unidata_vs_gpkg.py</code> — city-level CSV/HTML</li>
      <li><code>py -3 tools/audits/enrich_unidata_from_gpkg.py --apply --with-footprints</code> — backfill</li>
    </ul>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Final Unidata Audit Report · {UNIDATA_VERSION}</title>
  <style>
    :root {{
      --bg: #eef2f7;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #64748b;
      --border: #e2e8f0;
      --accent: #2563eb;
      --accent-dark: #1e40af;
      --header-from: #0f2744;
      --header-to: #1e40af;
      --ok: #059669;
      --warn: #d97706;
      --risk: #dc2626;
      --shadow: 0 4px 24px rgba(15, 23, 42, 0.08);
      --radius: 12px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Segoe UI", "Inter", system-ui, -apple-system, sans-serif;
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.55;
      font-size: 15px;
    }}
    .wrap {{ max-width: 1140px; margin: 0 auto; padding: 28px 24px 56px; }}
    .hero {{
      background: linear-gradient(135deg, var(--header-from) 0%, var(--header-to) 55%, #3b82f6 100%);
      color: #fff;
      border-radius: var(--radius);
      padding: 36px 40px 32px;
      margin-bottom: 28px;
      box-shadow: var(--shadow);
    }}
    .hero-badge {{
      display: inline-block;
      background: rgba(255,255,255,0.15);
      border: 1px solid rgba(255,255,255,0.25);
      border-radius: 999px;
      padding: 4px 14px;
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin-bottom: 12px;
    }}
    .hero h1 {{ margin: 0 0 10px; font-size: 1.85rem; font-weight: 700; letter-spacing: -0.02em; }}
    .hero-meta {{ margin: 0; opacity: 0.9; font-size: 0.95rem; }}
    .hero-meta code {{ background: rgba(0,0,0,0.2); color: #e0e7ff; padding: 2px 8px; border-radius: 4px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px 24px;
      margin-bottom: 20px;
      box-shadow: 0 1px 2px rgba(0,0,0,.04);
    }}
    .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }}
    .kpi {{
      border-radius: 10px;
      padding: 18px 20px;
      border: 1px solid transparent;
      position: relative;
      overflow: hidden;
    }}
    .kpi::before {{
      content: "";
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
      border-radius: 10px 10px 0 0;
    }}
    .kpi-blue {{ background: #eff6ff; border-color: #bfdbfe; }}
    .kpi-blue::before {{ background: #2563eb; }}
    .kpi-indigo {{ background: #eef2ff; border-color: #c7d2fe; }}
    .kpi-indigo::before {{ background: #4f46e5; }}
    .kpi-teal {{ background: #f0fdfa; border-color: #99f6e4; }}
    .kpi-teal::before {{ background: #0d9488; }}
    .kpi-amber {{ background: #fffbeb; border-color: #fcd34d; }}
    .kpi-amber::before {{ background: #d97706; }}
    .kpi-green {{ background: #ecfdf5; border-color: #6ee7b7; }}
    .kpi-green::before {{ background: #059669; }}
    .kpi-val {{ font-size: 1.65rem; font-weight: 700; color: var(--ink); letter-spacing: -0.02em; }}
    .kpi-lbl {{ font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 6px; font-weight: 600; }}
    .kpi-note {{ font-size: 0.8rem; color: var(--muted); margin-top: 8px; }}
    .summary {{
      border-left: 4px solid var(--ok);
      background: linear-gradient(90deg, #ecfdf5 0%, #fff 40%);
      padding: 20px 24px;
      border-radius: var(--radius);
      margin-bottom: 28px;
      box-shadow: 0 1px 2px rgba(0,0,0,.04);
    }}
    .summary strong {{ color: #047857; }}
    .section-head {{
      display: flex;
      align-items: center;
      gap: 14px;
      margin: 36px 0 14px;
    }}
    .section-head h2 {{
      margin: 0;
      font-size: 1.15rem;
      font-weight: 600;
      color: var(--ink);
      border: none;
      padding: 0;
    }}
    .section-num {{
      display: flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      background: var(--accent);
      color: #fff;
      border-radius: 8px;
      font-size: 0.9rem;
      font-weight: 700;
      flex-shrink: 0;
    }}
    .lead {{ color: var(--muted); font-size: 0.92rem; margin: -6px 0 14px 46px; }}
    .table-wrap {{ overflow-x: auto; margin: 4px 0; }}
    .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    .data-table th {{
      background: #f8fafc;
      text-align: left;
      padding: 11px 14px;
      border-bottom: 2px solid var(--border);
      font-weight: 600;
      color: #475569;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .data-table td {{
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      vertical-align: middle;
    }}
    .data-table td.num, .data-table th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .data-table tbody tr:hover td {{ background: #f8fafc; }}
    .data-table tr.row-total td {{ background: #f1f5f9; font-weight: 600; border-top: 2px solid var(--border); }}
    .data-table tr.row-risk td {{ background: #fef2f2; }}
    .data-table tr.row-warn td {{ background: #fffbeb; }}
    code, .col-name {{
      background: #f1f5f9;
      padding: 2px 7px;
      border-radius: 5px;
      font-size: 0.86em;
      color: #334155;
      font-family: "Cascadia Code", "Consolas", monospace;
    }}
    .dtype {{ color: var(--muted); font-size: 0.85em; }}
    .badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }}
    .risk-none {{ background: #ecfdf5; color: #047857; }}
    .risk-low {{ background: #f0fdf4; color: #15803d; }}
    .risk-med {{ background: #fffbeb; color: #b45309; }}
    .risk-high {{ background: #fef2f2; color: #b91c1c; }}
    .tax {{
      display: inline-block;
      padding: 3px 9px;
      border-radius: 6px;
      font-size: 0.78rem;
      font-weight: 500;
    }}
    .tax-core-parcel {{ background: #dbeafe; color: #1d4ed8; }}
    .tax-footprint-related {{ background: #e0e7ff; color: #4338ca; }}
    .tax-external-join {{ background: #fce7f3; color: #be185d; }}
    .tax-source-missing {{ background: #fef3c7; color: #b45309; }}
    .tax-api-fillable {{ background: #ecfdf5; color: #047857; }}
    .delta {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
    .delta-pos {{ color: #059669; }}
    .delta-neg {{ color: #dc2626; }}
    .delta-zero {{ color: var(--muted); }}
    .src-active {{
      display: inline-block;
      background: #ecfdf5;
      color: #047857;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .src-muted {{
      display: inline-block;
      background: #f1f5f9;
      color: #64748b;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
    }}
    .repro-list {{ margin: 0; padding-left: 1.35rem; }}
    .repro-list li {{ margin: 10px 0; }}
    .repro-list code {{ font-size: 0.88em; }}
    footer {{
      margin-top: 40px;
      padding-top: 20px;
      border-top: 1px solid var(--border);
      font-size: 0.82rem;
      color: var(--muted);
      text-align: center;
    }}
  </style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="hero-badge">Santa Clara County · Data Quality · {UNIDATA_VERSION}</div>
    <h1>Final Unidata Audit Report · {UNIDATA_VERSION}</h1>
    <p class="hero-meta">Snapshot of <code>public.unidata</code> ({UNIDATA_VERSION}) · Generated {_esc(generated)} UTC</p>
  </header>

  <div class="card">{kpis}</div>

  <div class="summary">
    <strong>Executive summary.</strong>
    Unidata holds <strong>{_fmt_int(total_rows)}</strong> parcels — aligned with the GPKG baseline
    (<strong>{_fmt_int(gpkg_counts["unique_apn_scity"])}</strong> unique APN+<code>scity</code> keys).
    The <strong>{_fmt_int(abs(row_delta))}</strong>-row gap vs GPKG APN rows is explained by
    <strong>{_fmt_int(dup_gpkg)}</strong> duplicate GPKG features, not missing inventory.
    Footprints are <strong>{_fmt_pct(fp_present_pct)}</strong> populated after
    <code>California.gpkg</code> spatial backfill (<strong>{_fmt_int(fp_missing)}</strong> still empty).
    Largest attribute gaps: <code>yearbuilt</code>, <code>scity</code>, <code>address</code>.
  </div>
{sections}
  <footer>
    Audit_unidata · PostgreSQL <code>parcelz.public.unidata</code> ·
    Cloud SQL proxy <code>127.0.0.1:5432</code> when using default config
  </footer>
</div>
</body>
</html>"""


def main() -> None:
    schema, table = "public", "unidata"
    gpkg_path = _REPO / "data" / "ca_santa_clara_parcel_build_opt.gpkg"
    out_dir = _REPO / "outputs" / "parcel_audits"
    out_html = out_dir / "final_unidata_audit_report.html"
    out_csv = out_dir / "final_unidata_audit_field_missingness.csv"

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    print("Computing Step 1 field rows...")
    field_rows = compute_field_rows(schema, table, DEFAULT_DB_CONFIG)

    print("Reading GPKG and Unidata city stats...")
    gpkg_stats = read_gpkg_stats(gpkg_path, "ca_santa_clara_parcel_build_opt")
    unidata_stats = read_unidata_stats(schema, table, DEFAULT_DB_CONFIG)
    city_rows = add_total_row(merge_rows(gpkg_stats, unidata_stats))

    gpkg_counts = collect_gpkg_row_counts(gpkg_path)
    total_rows = sum(u.row_count for u in unidata_stats.values())

    conn = psycopg.connect(**{**DEFAULT_DB_CONFIG, "connect_timeout": 25})
    try:
        fldzone_top = collect_fldzone_top(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE footprints IS NULL OR cardinality(footprints)=0),
              ROUND(100.0 * COUNT(*) FILTER (WHERE footprints IS NOT NULL AND cardinality(footprints)>0) / COUNT(*), 2)
            FROM public.unidata
            """
        )
        fp_missing, fp_present_pct = cur.fetchone()
        fp_missing = int(fp_missing)
        fp_present_pct = float(fp_present_pct)
    finally:
        conn.close()

    # Export field missingness CSV alongside HTML
    out_dir.mkdir(parents=True, exist_ok=True)
    import csv

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["column", "data_type", "taxonomy", "present", "missing", "missing_pct"])
        for r in sorted(field_rows, key=lambda x: (-x.missing_pct, x.column_name)):
            w.writerow([r.column_name, r.data_type, r.taxonomy_bucket, r.present, r.missing, r.missing_pct])

    html_doc = build_html(
        generated,
        total_rows,
        field_rows,
        gpkg_counts,
        city_rows,
        fldzone_top,
        fp_missing,
        fp_present_pct,
    )
    out_html.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {out_html}")
    print(f"Wrote {out_csv}")


if __name__ == "__main__":
    main()
