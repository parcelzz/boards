"""
Step 1 — Classify field missingness (Next-stage work plan).

Queries PostgreSQL column metadata + row-level presence counts for public.unidata,
assigns each field to a product taxonomy (core / footprint / external join /
source-missing / API-fillable), estimates review priority, and writes:

  outputs/missingness_step1/report.html          — main narrative + tables
  outputs/missingness_step1/field_missingness_all.csv
  outputs/missingness_step1/<bucket>/fields.csv — one folder per taxonomy bucket

Run from repo root:
  python tools/audits/field_missingness_classification.py
"""
from __future__ import annotations

import argparse
import csv
import html
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import psycopg
from psycopg import sql


DEFAULT_DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "parcelz",
    "user": "parcelz",
    "password": "INz3TzaMQIK2RLu0Xu31UTbgYRsq",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


# Taxonomy keys match output subfolders under outputs/missingness_step1/
CORE_PARCEL = "core_parcel"
FOOTPRINT = "footprint_related"
EXTERNAL_JOIN = "external_join"
SOURCE_MISSING = "source_missing"
API_FILLABLE = "api_fillable"

# Mirrors the workshop table: Type | Description | Initial handling strategy
TAXONOMY_LABELS: dict[str, tuple[str, str, str]] = {
    CORE_PARCEL: (
        "Core parcel fields",
        "Parcel ID, geometry, address, etc.",
        "Must be complete and reliable.",
    ),
    FOOTPRINT: (
        "Footprint-related fields",
        "Building footprint, footprint area, etc.",
        "Known to be partially missing; treat as enrichment fields.",
    ),
    EXTERNAL_JOIN: (
        "External join fields",
        "building_error, external scores, derived attributes, etc.",
        "Need to clarify the meaning of missing values.",
    ),
    SOURCE_MISSING: (
        "Source-missing fields",
        "Fields not available in the original upstream data (no populated values in this snapshot).",
        "Require product decision.",
    ),
    API_FILLABLE: (
        "API-fillable fields",
        "Fields that can potentially be filled from external APIs.",
        "Evaluate cost and benefit.",
    ),
}


def taxonomy_title(bucket: str) -> str:
    return TAXONOMY_LABELS[bucket][0]


def taxonomy_description(bucket: str) -> str:
    return TAXONOMY_LABELS[bucket][1]


def initial_strategy(bucket: str) -> str:
    return TAXONOMY_LABELS[bucket][2]

# Explicit column → taxonomy (unknown columns fall through rules below)
COLUMN_BUCKET: dict[str, str] = {
    "id": CORE_PARCEL,
    "parcelnumb": CORE_PARCEL,
    "parcel": CORE_PARCEL,
    "scity": CORE_PARCEL,
    "city": CORE_PARCEL,
    "address": CORE_PARCEL,
    "lat": CORE_PARCEL,
    "lon": CORE_PARCEL,
    "footprints": FOOTPRINT,
    "building_area": FOOTPRINT,
    "sqft": FOOTPRINT,
    "yearbuilt": API_FILLABLE,
    "zoning": API_FILLABLE,
    "h3": API_FILLABLE,
    "ready": API_FILLABLE,
    "fldzone": EXTERNAL_JOIN,
    "alquist_fault": EXTERNAL_JOIN,
    "liquefaction": EXTERNAL_JOIN,
    "landslide": EXTERNAL_JOIN,
    "fhszsra": EXTERNAL_JOIN,
    "fhszlra": EXTERNAL_JOIN,
    "created_at": CORE_PARCEL,
    "updated_at": CORE_PARCEL,
}

NUMERIC_ZERO_EMPTY = frozenset({"sqft", "building_area", "fhszsra", "fhszlra", "yearbuilt"})

EXTERNAL_NAME_FRAGMENTS = ("error", "score", "risk", "derived", "external", "vendor")


def classify_column(name: str) -> str:
    """Assign taxonomy using explicit map + naming heuristics."""
    low = name.lower()
    if low in COLUMN_BUCKET:
        return COLUMN_BUCKET[low]
    if low in ("geom", "geometry", "shape", "wkb_geometry") or low.endswith("_geom"):
        return CORE_PARCEL
    if any(frag in low for frag in EXTERNAL_NAME_FRAGMENTS):
        return EXTERNAL_JOIN
    return EXTERNAL_JOIN


def bucket_for_row(col: str, missing_pct: float) -> str:
    """Apply completeness override: entirely empty → source_missing."""
    base = classify_column(col)
    if missing_pct >= 100.0:
        return SOURCE_MISSING
    return base


def presence_predicate(column_name: str, data_type: str, udt_name: str) -> sql.Composable:
    col = sql.Identifier(column_name)
    dt = (data_type or "").lower()
    udt = (udt_name or "").lower()

    if dt == "array" or udt.startswith("_"):
        return sql.SQL("{} IS NOT NULL AND cardinality({}) > 0").format(col, col)
    if dt == "boolean":
        return sql.SQL("{} IS NOT NULL").format(col)
    if dt == "USER-DEFINED":
        return sql.SQL("{} IS NOT NULL").format(col)
    if dt in ("character varying", "character", "text", "varchar"):
        return sql.SQL("{} IS NOT NULL AND TRIM({}::text) <> ''").format(col, col)
    if dt in ("smallint", "integer", "bigint", "numeric", "double precision", "real"):
        if column_name.lower() in NUMERIC_ZERO_EMPTY:
            return sql.SQL("{} IS NOT NULL AND {} <> 0").format(col, col)
        return sql.SQL("{} IS NOT NULL").format(col)
    if "timestamp" in dt or dt == "date":
        return sql.SQL("{} IS NOT NULL").format(col)
    if dt in ("json", "jsonb"):
        return sql.SQL("{} IS NOT NULL").format(col)
    if dt == "uuid":
        return sql.SQL("{} IS NOT NULL").format(col)
    # bytea, geometric unknown types, etc.
    return sql.SQL("{} IS NOT NULL").format(col)


def fetch_columns(cur: psycopg.Cursor, schema: str, table: str) -> list[tuple[str, str, str]]:
    cur.execute(
        """
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return [(str(r[0]), str(r[1]), str(r[2])) for r in cur.fetchall()]


def fetch_present_counts_one_scan(
    cur: psycopg.Cursor, schema: str, table: str, cols: list[tuple[str, str, str]]
) -> tuple[int, list[int]]:
    """Single SELECT — one full-table scan — avoids per-column round trips."""
    parts: list[sql.Composable] = [sql.SQL("COUNT(*)::bigint")]
    for column_name, data_type, udt_name in cols:
        pred = presence_predicate(column_name, data_type, udt_name)
        parts.append(sql.SQL("(COUNT(*) FILTER (WHERE {}))::bigint").format(pred))
    stmt = sql.SQL("SELECT {} FROM {}.{}").format(
        sql.SQL(", ").join(parts),
        sql.Identifier(schema),
        sql.Identifier(table),
    )
    cur.execute(stmt)
    row = cur.fetchone()
    if row is None:
        return 0, []
    total = int(row[0])
    presents = [int(row[i]) for i in range(1, len(row))]
    return total, presents


def product_impact_note(bucket: str, missing_pct: float, column_name: str) -> str:
    if bucket == CORE_PARCEL:
        if missing_pct <= 0.5:
            return "Low risk — core identifiers largely present."
        if missing_pct <= 5:
            return "Moderate — gaps may break joins, search, or ownership workflows."
        return "High — missing core parcel identity or location undermines trust."
    if bucket == FOOTPRINT:
        return "Expected partial coverage — affects enrichment UX, not parcel existence."
    if bucket == EXTERNAL_JOIN:
        return "NULL/false semantics matter for hazard and compliance messaging."
    if bucket == SOURCE_MISSING:
        return "Pipeline or scope gap — confirm whether field should ship for MVP."
    return "Backfill candidates — weigh vendor cost vs completeness uplift."


def review_priority(bucket: str, missing_pct: float) -> str:
    if bucket == CORE_PARCEL and missing_pct > 1:
        return "P0–P1"
    if bucket == CORE_PARCEL:
        return "P2"
    if bucket == EXTERNAL_JOIN and missing_pct > 15:
        return "P1–P2"
    if bucket == API_FILLABLE and missing_pct > 20:
        return "P2–P3"
    if bucket == FOOTPRINT:
        return "P2–P3"
    if bucket == SOURCE_MISSING:
        return "P1 (scope)"
    return "P3"


def product_behavior_risk(bucket: str, missing_pct: float) -> str:
    """Whether missingness is likely to affect product behavior (task checklist item 4)."""
    if bucket == SOURCE_MISSING:
        return "High"
    if bucket == CORE_PARCEL:
        if missing_pct > 1:
            return "High"
        if missing_pct > 0:
            return "Moderate"
        return "Low"
    if bucket == EXTERNAL_JOIN:
        if missing_pct > 50:
            return "High"
        if missing_pct > 5:
            return "Moderate"
        return "Low"
    if bucket == API_FILLABLE:
        if missing_pct > 25:
            return "Moderate"
        if missing_pct > 5:
            return "Moderate"
        return "Low"
    if bucket == FOOTPRINT:
        if missing_pct > 15:
            return "Moderate"
        if missing_pct > 0:
            return "Low"
        return "Low"
    return "Moderate"


@dataclass
class FieldRow:
    column_name: str
    data_type: str
    udt_name: str
    total_rows: int
    present: int
    missing: int
    missing_pct: float
    taxonomy_bucket: str
    initial_strategy: str
    product_impact: str
    product_behavior_risk: str
    review_priority: str

    def as_csv_dict(self) -> dict[str, str | float | int]:
        title = taxonomy_title(self.taxonomy_bucket)
        return {
            "column_name": self.column_name,
            "data_type": self.data_type,
            "udt_name": self.udt_name,
            "total_rows": self.total_rows,
            "present_count": self.present,
            "missing_count": self.missing,
            "missing_pct": self.missing_pct,
            "taxonomy": title,
            "taxonomy_key": self.taxonomy_bucket,
            "initial_handling_strategy": self.initial_strategy,
            "product_behavior_risk": self.product_behavior_risk,
            "product_impact": self.product_impact,
            "review_priority": self.review_priority,
        }


def compute_field_rows(schema: str, table: str, db_config: dict) -> list[FieldRow]:
    rows_out: list[FieldRow] = []
    conn_kw = {**db_config, "connect_timeout": 20}
    with psycopg.connect(**conn_kw) as conn:
        conn.autocommit = True
        cur = conn.cursor()
        cols = fetch_columns(cur, schema, table)
        total, presents = fetch_present_counts_one_scan(cur, schema, table, cols)
        if len(presents) != len(cols):
            raise RuntimeError("Column count mismatch between metadata and aggregate query.")
        for idx, (column_name, data_type, udt_name) in enumerate(cols):
            present = presents[idx]
            missing = max(0, total - present)
            missing_pct = round((missing / total) * 100.0, 4) if total else 0.0
            bucket = bucket_for_row(column_name, missing_pct)
            strat = initial_strategy(bucket)
            impact = product_impact_note(bucket, missing_pct, column_name)
            beh = product_behavior_risk(bucket, missing_pct)
            prio = review_priority(bucket, missing_pct)
            rows_out.append(
                FieldRow(
                    column_name=column_name,
                    data_type=data_type,
                    udt_name=udt_name,
                    total_rows=total,
                    present=present,
                    missing=missing,
                    missing_pct=missing_pct,
                    taxonomy_bucket=bucket,
                    initial_strategy=strat,
                    product_impact=impact,
                    product_behavior_risk=beh,
                    review_priority=prio,
                )
            )
    rows_out.sort(key=lambda r: (r.taxonomy_bucket, r.missing_pct, r.column_name))
    return rows_out


def compute_field_rows_on_connection(conn: psycopg.Connection, schema: str, table: str) -> list[FieldRow]:
    """Same logic as ``compute_field_rows`` but on an existing connection.

    Use this from long-running tools (e.g. GPKG enrich) so the missingness snapshot uses the **same**
    transaction and visibility rules as the rest of that run — consistent with Step 1 counts for
    ``sqft`` / ``building_area`` (where NULL or 0 still counts as missing per ``presence_predicate``).
    """
    rows_out: list[FieldRow] = []
    with conn.cursor() as cur:
        cols = fetch_columns(cur, schema, table)
        total, presents = fetch_present_counts_one_scan(cur, schema, table, cols)
        if len(presents) != len(cols):
            raise RuntimeError("Column count mismatch between metadata and aggregate query.")
        for idx, (column_name, data_type, udt_name) in enumerate(cols):
            present = presents[idx]
            missing = max(0, total - present)
            missing_pct = round((missing / total) * 100.0, 4) if total else 0.0
            bucket = bucket_for_row(column_name, missing_pct)
            strat = initial_strategy(bucket)
            impact = product_impact_note(bucket, missing_pct, column_name)
            beh = product_behavior_risk(bucket, missing_pct)
            prio = review_priority(bucket, missing_pct)
            rows_out.append(
                FieldRow(
                    column_name=column_name,
                    data_type=data_type,
                    udt_name=udt_name,
                    total_rows=total,
                    present=present,
                    missing=missing,
                    missing_pct=missing_pct,
                    taxonomy_bucket=bucket,
                    initial_strategy=strat,
                    product_impact=impact,
                    product_behavior_risk=beh,
                    review_priority=prio,
                )
            )
    rows_out.sort(key=lambda r: (r.taxonomy_bucket, r.missing_pct, r.column_name))
    return rows_out


def write_csv(path: Path, field_rows: Iterable[FieldRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "column_name",
        "data_type",
        "udt_name",
        "total_rows",
        "present_count",
        "missing_count",
        "missing_pct",
        "taxonomy",
        "taxonomy_key",
        "initial_handling_strategy",
        "product_behavior_risk",
        "product_impact",
        "review_priority",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in field_rows:
            w.writerow({k: r.as_csv_dict()[k] for k in headers})


def write_bucket_csvs(base_dir: Path, field_rows: list[FieldRow]) -> None:
    by_bucket: dict[str, list[FieldRow]] = {}
    for r in field_rows:
        by_bucket.setdefault(r.taxonomy_bucket, []).append(r)
    for bucket, lst in by_bucket.items():
        write_csv(base_dir / bucket / "fields.csv", lst)


def esc(s: object) -> str:
    return html.escape(str(s), quote=False)


BUCKET_ORDER = [CORE_PARCEL, FOOTPRINT, EXTERNAL_JOIN, SOURCE_MISSING, API_FILLABLE]


def _bucket_badge_class(bucket: str) -> str:
    return {
        CORE_PARCEL: "badge-core",
        FOOTPRINT: "badge-footprint",
        EXTERNAL_JOIN: "badge-external",
        SOURCE_MISSING: "badge-source",
        API_FILLABLE: "badge-api",
    }[bucket]


def _behavior_class(risk: str) -> str:
    return {"High": "risk-high", "Moderate": "risk-mod", "Low": "risk-low"}.get(risk, "risk-mod")


def _priority_class(prio: str) -> str:
    if "P0" in prio or "P1" in prio:
        return "prio-hot"
    if "P2" in prio:
        return "prio-warm"
    return "prio-cool"


def _missing_bar_cell(pct: float) -> str:
    w = min(100.0, max(0.0, pct))
    hue = "#16a34a" if pct < 5 else "#d97706" if pct < 25 else "#dc2626"
    miss_cls = "miss-high" if pct >= 25 else "miss-mid" if pct >= 5 else "miss-low"
    return (
        f'<div class="miss-cell"><div class="bar-track" title="{esc(f"{pct:.2f}% missing")}">'
        f'<span class="bar-fill" style="width:{w:.1f}%;background:{hue}"></span></div>'
        f'<span class="miss-pct {miss_cls}">{esc(f"{pct:.2f}%")}</span></div>'
    )


def build_html_report(field_rows: list[FieldRow], generated_iso: str) -> str:
    total_rows = field_rows[0].total_rows if field_rows else 0
    n_fields = len(field_rows)
    bucket_counts = {b: sum(1 for r in field_rows if r.taxonomy_bucket == b) for b in BUCKET_ORDER}
    n_high_behavior = sum(1 for r in field_rows if r.product_behavior_risk == "High")

    summary_rows = "".join(
        f"<tr class='tax-row tax-{esc(key)}'>"
        f"<td><span class='badge {_bucket_badge_class(key)}'>{esc(taxonomy_title(key))}</span></td>"
        f"<td>{esc(taxonomy_description(key))}</td>"
        f"<td class='strategy'>{esc(initial_strategy(key))}</td></tr>"
        for key in BUCKET_ORDER
    )

    sections: list[str] = []
    for bucket in BUCKET_ORDER:
        title = taxonomy_title(bucket)
        desc = taxonomy_description(bucket)
        subset = [r for r in field_rows if r.taxonomy_bucket == bucket]
        body: list[str] = []
        for r in subset:
            body.append(
                "<tr>"
                f"<td><code>{esc(r.column_name)}</code></td>"
                f"<td><span class='type-tag'>{esc(r.data_type)}</span></td>"
                f"<td class='num'>{esc(f'{r.present:,}')}</td>"
                f"<td class='num miss-n'>{esc(f'{r.missing:,}')}</td>"
                f"<td class='num'>{_missing_bar_cell(r.missing_pct)}</td>"
                f"<td class='small'>{esc(r.initial_strategy)}</td>"
                f"<td><span class='risk {_behavior_class(r.product_behavior_risk)}'>{esc(r.product_behavior_risk)}</span></td>"
                f"<td class='small'>{esc(r.product_impact)}</td>"
                f"<td><span class='prio {_priority_class(r.review_priority)}'>{esc(r.review_priority)}</span></td>"
                "</tr>"
            )
        folder = f"{bucket}/fields.csv"
        sections.append(
            f"""
    <section class="bucket-card bc-{esc(bucket)}" id="{esc(bucket)}">
      <div class="bucket-head">
        <span class="badge {_bucket_badge_class(bucket)}">{esc(title)}</span>
        <h2>{esc(title)} — field detail</h2>
        <p class="muted">{esc(desc)}</p>
        <p class="file-ref">Export: <code>outputs/missingness_step1/{esc(folder)}</code></p>
      </div>
      <div class="table-wrap">
        <table class="stripe">
          <thead>
            <tr>
              <th>Column</th><th>PG type</th><th>Present</th><th>Missing</th><th>Missing %</th>
              <th>Initial handling</th><th>Behavior risk</th><th>Product impact</th><th>Review priority</th>
            </tr>
          </thead>
          <tbody>{''.join(body) if body else '<tr><td colspan="9">No columns in this bucket.</td></tr>'}</tbody>
        </table>
      </div>
    </section>
            """
        )

    checklist = """
    <ol class="checklist">
      <li><span class="ck-i">1</span> Generate a field-level missingness table.</li>
      <li><span class="ck-i">2</span> Classify each field into one of the above categories.</li>
      <li><span class="ck-i">3</span> Mark which fields are core, enrichment (footprint-related), external, source-missing, or API-fillable.</li>
      <li><span class="ck-i">4</span> Identify fields where missingness may affect product behavior (see <strong>Behavior risk</strong>).</li>
      <li><span class="ck-i">5</span> Prioritize fields for product review (see <strong>Review priority</strong>).</li>
    </ol>
    <p class="muted ck-note">Artifacts: <code>field_missingness_all.csv</code> plus one CSV per bucket folder.</p>
    """

    overview_rows = "".join(
        "<tr>"
        f"<td><code>{esc(r.column_name)}</code></td>"
        f"<td><span class='badge {_bucket_badge_class(r.taxonomy_bucket)}'>{esc(taxonomy_title(r.taxonomy_bucket))}</span></td>"
        f"<td class='num'>{_missing_bar_cell(r.missing_pct)}</td>"
        f"<td><span class='risk {_behavior_class(r.product_behavior_risk)}'>{esc(r.product_behavior_risk)}</span></td>"
        f"<td><span class='prio {_priority_class(r.review_priority)}'>{esc(r.review_priority)}</span></td>"
        "</tr>"
        for r in sorted(field_rows, key=lambda x: (-x.missing_pct, x.taxonomy_bucket, x.column_name))
    )

    kpi = f"""
    <div class="kpi-grid">
      <div class="kpi kpi-rows"><div class="kpi-val">{esc(f'{total_rows:,}')}</div><div class="kpi-lbl">Table rows scanned</div></div>
      <div class="kpi kpi-fields"><div class="kpi-val">{esc(n_fields)}</div><div class="kpi-lbl">Columns analyzed</div></div>
      <div class="kpi kpi-alert"><div class="kpi-val">{esc(n_high_behavior)}</div><div class="kpi-lbl">High behavior-risk fields</div></div>
      <div class="kpi kpi-core"><div class="kpi-val">{esc(bucket_counts[CORE_PARCEL])}</div><div class="kpi-lbl">Core parcel fields</div></div>
      <div class="kpi kpi-fp"><div class="kpi-val">{esc(bucket_counts[FOOTPRINT])}</div><div class="kpi-lbl">Footprint / enrichment</div></div>
      <div class="kpi kpi-ext"><div class="kpi-val">{esc(bucket_counts[EXTERNAL_JOIN])}</div><div class="kpi-lbl">External join fields</div></div>
      <div class="kpi kpi-src"><div class="kpi-val">{esc(bucket_counts[SOURCE_MISSING])}</div><div class="kpi-lbl">Source-missing (100%)</div></div>
      <div class="kpi kpi-api"><div class="kpi-val">{esc(bucket_counts[API_FILLABLE])}</div><div class="kpi-lbl">API-fillable fields</div></div>
    </div>
    """

    jump = """
    <nav class="jump" aria-label="Section navigation">
      <a href="#summary-table">Taxonomy</a>
      <a href="#checklist">Checklist</a>
      <a href="#overview">All fields</a>
      <a href="#core_parcel">Core</a>
      <a href="#footprint_related">Footprint</a>
      <a href="#external_join">External</a>
      <a href="#source_missing">Source-missing</a>
      <a href="#api_fillable">API-fillable</a>
    </nav>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Step 1 — Field missingness classification</title>
  <style>
    :root {{
      --bg: #eef2f7;
      --surface: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --line: #dbe3f0;
      --core: #1d4ed8;
      --foot: #0d9488;
      --ext: #7c3aed;
      --src: #e11d48;
      --api: #ea580c;
      --shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: linear-gradient(180deg, #dfe7f4 0%, var(--bg) 140px);
      color: var(--text);
      line-height: 1.55;
      font-size: 15px;
    }}
    header.hero {{
      background: linear-gradient(118deg, #0f172a 0%, #1e3a5f 42%, #2563eb 100%);
      color: #fff;
      padding: 32px 28px 36px;
      box-shadow: var(--shadow);
    }}
    header.hero h1 {{ margin: 0 0 10px; font-size: clamp(1.35rem, 2.5vw, 1.75rem); font-weight: 700; letter-spacing: -0.02em; }}
    header.hero p {{ margin: 0 0 10px; opacity: 0.94; max-width: 920px; }}
    header.hero code {{
      font-family: ui-monospace, Consolas, monospace;
      font-size: 0.88em;
      background: rgba(255,255,255,.14);
      padding: 2px 8px;
      border-radius: 6px;
      color: #e2e8ff;
    }}
    header.hero time {{ font-size: 13px; opacity: 0.85; }}
    .jump {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 14px 28px;
      background: rgba(255,255,255,.55);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--line);
      justify-content: center;
    }}
    .jump a {{
      font-size: 13px;
      font-weight: 600;
      color: #1e40af;
      text-decoration: none;
      padding: 6px 12px;
      border-radius: 999px;
      background: #fff;
      border: 1px solid var(--line);
      box-shadow: 0 1px 2px rgba(15,23,42,.06);
    }}
    .jump a:hover {{ background: #eff6ff; border-color: #93c5fd; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px 20px 56px; }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 22px 24px;
      margin-bottom: 20px;
      box-shadow: var(--shadow);
    }}
    .panel h2 {{ margin: 0 0 14px; font-size: 1.15rem; color: #0f172a; }}
    .muted {{ color: var(--muted); font-size: 14px; }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    .kpi {{
      background: var(--surface);
      border-radius: 14px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      box-shadow: 0 4px 14px rgba(15,23,42,.05);
      border-left: 4px solid #64748b;
    }}
    .kpi-rows {{ border-left-color: #2563eb; }}
    .kpi-fields {{ border-left-color: #6366f1; }}
    .kpi-alert {{ border-left-color: #e11d48; }}
    .kpi-core {{ border-left-color: var(--core); }}
    .kpi-fp {{ border-left-color: var(--foot); }}
    .kpi-ext {{ border-left-color: var(--ext); }}
    .kpi-src {{ border-left-color: var(--src); }}
    .kpi-api {{ border-left-color: var(--api); }}
    .kpi-val {{ font-size: 1.35rem; font-weight: 800; font-variant-numeric: tabular-nums; color: #0f172a; }}
    .kpi-lbl {{ font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-top: 4px; }}

    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: middle; }}
    thead th {{
      background: linear-gradient(180deg, #f1f5fd 0%, #e8eef9 100%);
      font-weight: 700;
      color: #334155;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    tbody tr:hover {{ background: #f8fafc; }}
    .stripe tbody tr:nth-child(even) {{ background: #fafbfd; }}
    .stripe tbody tr:nth-child(even):hover {{ background: #f1f5f9; }}

    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    td.small {{ font-size: 12px; color: #475569; max-width: 220px; }}
    code {{
      font-family: ui-monospace, Consolas, monospace;
      font-size: 12px;
      background: #eef2ff;
      color: #312e81;
      padding: 2px 7px;
      border-radius: 6px;
    }}
    .type-tag {{
      font-size: 11px;
      background: #f1f5f9;
      color: #475569;
      padding: 3px 8px;
      border-radius: 6px;
      white-space: nowrap;
    }}
    .miss-n {{ color: #b45309; font-weight: 600; }}

    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .05em;
      white-space: nowrap;
    }}
    .badge-core {{ background: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }}
    .badge-footprint {{ background: #ccfbf1; color: #0f766e; border: 1px solid #5eead4; }}
    .badge-external {{ background: #ede9fe; color: #5b21b6; border: 1px solid #c4b5fd; }}
    .badge-source {{ background: #ffe4e6; color: #9f1239; border: 1px solid #fda4af; }}
    .badge-api {{ background: #ffedd5; color: #c2410c; border: 1px solid #fdba74; }}

    .risk {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 8px;
      font-weight: 800;
      font-size: 11px;
      letter-spacing: .03em;
    }}
    .risk-high {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
    .risk-mod {{ background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
    .risk-low {{ background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }}

    .prio {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
    }}
    .prio-hot {{ background: #fecaca; color: #7f1d1d; }}
    .prio-warm {{ background: #fde68a; color: #78350f; }}
    .prio-cool {{ background: #e2e8f0; color: #334155; }}

    .miss-cell {{ display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }}
    .bar-track {{
      flex: 1;
      min-width: 72px;
      max-width: 140px;
      height: 8px;
      background: #e2e8f0;
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar-fill {{ display: block; height: 100%; border-radius: 999px; }}
    .miss-pct {{ font-weight: 700; font-size: 12px; min-width: 52px; text-align: right; }}
    .miss-low {{ color: #15803d; }}
    .miss-mid {{ color: #b45309; }}
    .miss-high {{ color: #dc2626; }}

    .tax-row td.strategy {{ font-weight: 500; color: #334155; background: #fafbff; }}
    .tax-row.tax-core_parcel td:first-child {{ border-left: 4px solid var(--core); }}
    .tax-row.tax-footprint_related td:first-child {{ border-left: 4px solid var(--foot); }}
    .tax-row.tax-external_join td:first-child {{ border-left: 4px solid var(--ext); }}
    .tax-row.tax-source_missing td:first-child {{ border-left: 4px solid var(--src); }}
    .tax-row.tax-api_fillable td:first-child {{ border-left: 4px solid var(--api); }}

    .bucket-card {{
      background: var(--surface);
      border-radius: 16px;
      margin-bottom: 22px;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
      overflow: hidden;
    }}
    .bucket-head {{
      padding: 18px 22px;
      border-bottom: 1px solid var(--line);
    }}
    .bucket-head h2 {{ margin: 10px 0 6px; font-size: 1.12rem; }}
    .bc-core_parcel .bucket-head {{ background: linear-gradient(90deg, #eff6ff, #fff); border-left: 5px solid var(--core); }}
    .bc-footprint_related .bucket-head {{ background: linear-gradient(90deg, #f0fdfa, #fff); border-left: 5px solid var(--foot); }}
    .bc-external_join .bucket-head {{ background: linear-gradient(90deg, #f5f3ff, #fff); border-left: 5px solid var(--ext); }}
    .bc-source_missing .bucket-head {{ background: linear-gradient(90deg, #fff1f2, #fff); border-left: 5px solid var(--src); }}
    .bc-api_fillable .bucket-head {{ background: linear-gradient(90deg, #fff7ed, #fff); border-left: 5px solid var(--api); }}

    .table-wrap {{ overflow-x: auto; padding: 0 0 12px; }}
    .checklist {{ list-style: none; padding: 0; margin: 0; }}
    .checklist li {{
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 10px 12px;
      margin-bottom: 8px;
      background: #f8fafc;
      border-radius: 10px;
      border: 1px solid var(--line);
    }}
    .ck-i {{
      flex-shrink: 0;
      width: 26px;
      height: 26px;
      border-radius: 8px;
      background: #2563eb;
      color: #fff;
      font-weight: 800;
      font-size: 13px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .ck-note {{ margin-top: 14px; margin-bottom: 0; }}
    .file-ref {{ font-size: 13px; margin: 0; }}
    .file-ref code {{ background: #f1f5f9; color: #334155; }}
    .section-h2 {{ margin: 28px 4px 12px; font-size: 1.2rem; color: #0f172a; }}
  </style>
</head>
<body>
  <header class="hero">
    <h1>Next-stage work plan · Step 1: Classify field missingness</h1>
    <p>Systematic missingness analysis for <code>public.unidata</code>: counts per column, taxonomy placement, behavior risk, and review priority — exported as CSV per bucket.</p>
    <p><time datetime="{esc(generated_iso)}">Generated {esc(generated_iso)}</time></p>
  </header>
  {jump}
  <main>
    {kpi}
    <section class="panel" id="summary-table">
      <h2>Classification reference (your workshop table)</h2>
      <p class="muted">Type · Description · Initial handling strategy — aligned with Step 1 instructions.</p>
      <div class="table-wrap">
        <table class="stripe">
          <thead>
            <tr><th>Type</th><th>Description</th><th>Initial handling strategy</th></tr>
          </thead>
          <tbody>{summary_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="panel" id="checklist">
      <h2>To do (checklist)</h2>
      {checklist}
    </section>

    <section class="panel" id="overview">
      <h2>All fields — sorted by missing %</h2>
      <p class="muted">Full export: <code>outputs/missingness_step1/field_missingness_all.csv</code> (includes behavior risk &amp; handling columns).</p>
      <div class="table-wrap">
        <table class="stripe">
          <thead>
            <tr><th>Column</th><th>Taxonomy bucket</th><th>Missing %</th><th>Behavior risk</th><th>Review priority</th></tr>
          </thead>
          <tbody>{overview_rows}</tbody>
        </table>
      </div>
    </section>

    <h2 class="section-h2">Detailed tables by taxonomy bucket</h2>
    {"".join(sections)}
  </main>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Step 1 missingness classification for public.unidata")
    p.add_argument("--db-schema", default="public")
    p.add_argument("--db-table", default="unidata")
    p.add_argument(
        "--out-root",
        type=Path,
        default=_repo_root() / "outputs" / "missingness_step1",
        help="Directory for HTML + CSV outputs",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    rows = compute_field_rows(args.db_schema, args.db_table, DEFAULT_DB_CONFIG)

    write_csv(out_root / "field_missingness_all.csv", rows)
    write_bucket_csvs(out_root, rows)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    html_doc = build_html_report(rows, generated)
    (out_root / "report.html").write_text(html_doc, encoding="utf-8")

    print(f"Wrote {out_root / 'report.html'}")
    print(f"Wrote {out_root / 'field_missingness_all.csv'}")
    for key in TAXONOMY_LABELS:
        print(f"Wrote {out_root / key / 'fields.csv'}")


if __name__ == "__main__":
    main()
