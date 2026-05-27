"""
Step 3 — Field semantics audit (Next-stage work plan).

Builds on Steps 1–2: for each column in public.unidata, quantifies *how* values
are stored (NULL vs literal zero, NULL vs FALSE vs TRUE, empty text, empty
arrays) so product/engineering can lock semantics before Step 4 prioritization.

Writes:
  outputs/missingness_step3/report.html
  outputs/missingness_step3/semantics_by_column.csv
  outputs/missingness_step3/hazard_boolean_crosstab.csv

Run from repo root:
  python tools/audits/field_semantics_audit_step3.py
"""
from __future__ import annotations

import argparse
import csv
import html as html_module
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from field_missingness_classification import (
    DEFAULT_DB_CONFIG,
    NUMERIC_ZERO_EMPTY,
    compute_field_rows,
    fetch_columns,
    taxonomy_title,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def esc(s: object) -> str:
    return html_module.escape(str(s), quote=False)


@dataclass
class ColSemantics:
    column_name: str
    data_type: str
    udt_name: str
    total_rows: int
    taxonomy: str
    taxonomy_key: str
    missing_pct_step1: float
    n_null: int | None = None
    n_true: int | None = None
    n_false: int | None = None
    n_blank: int | None = None
    n_nonempty: int | None = None
    n_zero: int | None = None
    n_negative: int | None = None
    n_positive: int | None = None
    n_empty_array: int | None = None
    n_nonempty_array: int | None = None
    zero_pct_of_nonnull: float | None = None
    null_pct: float | None = None
    false_pct_of_nonnull: float | None = None
    recommended_verdict: str = ""
    notes_for_step4: str = ""

    def as_csv_row(self) -> dict[str, str | float | int]:
        return {
            "column_name": self.column_name,
            "data_type": self.data_type,
            "udt_name": self.udt_name,
            "total_rows": self.total_rows,
            "taxonomy": self.taxonomy,
            "taxonomy_key": self.taxonomy_key,
            "missing_pct_step1": self.missing_pct_step1,
            "n_null": self.n_null if self.n_null is not None else "",
            "n_true": self.n_true if self.n_true is not None else "",
            "n_false": self.n_false if self.n_false is not None else "",
            "n_blank": self.n_blank if self.n_blank is not None else "",
            "n_nonempty": self.n_nonempty if self.n_nonempty is not None else "",
            "n_zero": self.n_zero if self.n_zero is not None else "",
            "n_negative": self.n_negative if self.n_negative is not None else "",
            "n_positive": self.n_positive if self.n_positive is not None else "",
            "n_empty_array": self.n_empty_array if self.n_empty_array is not None else "",
            "n_nonempty_array": self.n_nonempty_array if self.n_nonempty_array is not None else "",
            "zero_pct_of_nonnull": self.zero_pct_of_nonnull
            if self.zero_pct_of_nonnull is not None
            else "",
            "null_pct": self.null_pct if self.null_pct is not None else "",
            "false_pct_of_nonnull": self.false_pct_of_nonnull
            if self.false_pct_of_nonnull is not None
            else "",
            "recommended_verdict": self.recommended_verdict,
            "notes_for_step4": self.notes_for_step4,
        }


def pct(n: int, d: int) -> float:
    return round((n / d) * 100.0, 4) if d else 0.0


def _verdict_and_notes(
    *,
    col_low: str,
    data_type: str,
    total: int,
    n_null: int | None,
    n_true: int | None,
    n_false: int | None,
    n_zero: int | None,
    nn_numeric: int | None,
    missing_pct_step1: float,
) -> tuple[str, str]:
    """Heuristic flags for Step 4 workshop — not business truth."""
    parts_v: list[str] = []
    parts_n: list[str] = []
    dt = (data_type or "").lower()

    if dt == "boolean" and n_null is not None and total > 0:
        np_null = pct(n_null, total)
        if np_null >= 5.0:
            parts_v.append("High boolean NULL rate")
            parts_n.append(
                f"NULL is {np_null:.2f}% of rows — confirm UI/API distinguish unknown vs FALSE."
            )
        nn_b = (n_true or 0) + (n_false or 0)
        if nn_b > 0 and n_false is not None:
            fn = pct(n_false, nn_b)
            if fn >= 85.0:
                parts_v.append("FALSE-dominated")
                parts_n.append(
                    f"Among non-NULL booleans, FALSE is {fn:.2f}% — verify domain meaning "
                    "(unknown encoded as FALSE?)."
                )

    if (
        col_low in NUMERIC_ZERO_EMPTY
        and n_zero is not None
        and nn_numeric is not None
        and nn_numeric > 0
    ):
        zp = pct(n_zero, nn_numeric)
        if zp >= 15.0:
            parts_v.append("Many exact zeros")
            parts_n.append(
                f"Step 1 treats 0 as missing for this field; {zp:.2f}% of non-NULL rows are 0 — "
                "decide if 0 is literal or sentinel."
            )
        elif zp > 1.0 and missing_pct_step1 < 10.0:
            parts_n.append(
                "Low Step-1 missing % but non-trivial zeros — spot-check whether zeros are valid."
            )

    if missing_pct_step1 >= 99.9 and dt == "boolean":
        parts_v.append("Nearly always NULL")
        parts_n.append("Almost no populated booleans — schema vs product expectation.")

    if not parts_v and not parts_n:
        return "OK — no auto-flag", "Review if this field is P0/P1 in Step 4."

    return "; ".join(parts_v) if parts_v else "Review", " ".join(parts_n)


def fetch_boolean_counts(
    cur: psycopg.Cursor, schema: str, table: str, column_name: str
) -> tuple[int, int, int, int]:
    col = sql.Identifier(column_name)
    sch = sql.Identifier(schema)
    tbl = sql.Identifier(table)
    cur.execute(
        sql.SQL(
            "SELECT "
            "COUNT(*) FILTER (WHERE {c} IS NULL)::bigint AS n_null, "
            "COUNT(*) FILTER (WHERE {c} IS TRUE)::bigint AS n_true, "
            "COUNT(*) FILTER (WHERE {c} IS FALSE)::bigint AS n_false, "
            "COUNT(*)::bigint AS total "
            "FROM {s}.{t}"
        ).format(c=col, s=sch, t=tbl)
    )
    r = cur.fetchone()
    return int(r[0]), int(r[1]), int(r[2]), int(r[3])


def fetch_text_counts(
    cur: psycopg.Cursor, schema: str, table: str, column_name: str
) -> tuple[int, int, int, int]:
    col = sql.Identifier(column_name)
    sch = sql.Identifier(schema)
    tbl = sql.Identifier(table)
    cur.execute(
        sql.SQL(
            "SELECT "
            "COUNT(*) FILTER (WHERE {c} IS NULL)::bigint AS n_null, "
            "COUNT(*) FILTER (WHERE {c} IS NOT NULL AND TRIM({c}::text) = '')::bigint AS n_blank, "
            "COUNT(*) FILTER (WHERE {c} IS NOT NULL AND TRIM({c}::text) <> '')::bigint AS n_nonempty, "
            "COUNT(*)::bigint AS total "
            "FROM {s}.{t}"
        ).format(c=col, s=sch, t=tbl)
    )
    r = cur.fetchone()
    return int(r[0]), int(r[1]), int(r[2]), int(r[3])


def fetch_numeric_counts(
    cur: psycopg.Cursor, schema: str, table: str, column_name: str
) -> tuple[int, int, int, int, int]:
    col = sql.Identifier(column_name)
    sch = sql.Identifier(schema)
    tbl = sql.Identifier(table)
    cur.execute(
        sql.SQL(
            "SELECT "
            "COUNT(*) FILTER (WHERE {c} IS NULL)::bigint AS n_null, "
            "COUNT(*) FILTER (WHERE {c} IS NOT NULL AND {c}::numeric = 0)::bigint AS n_zero, "
            "COUNT(*) FILTER (WHERE {c} IS NOT NULL AND {c}::numeric < 0)::bigint AS n_neg, "
            "COUNT(*) FILTER (WHERE {c} IS NOT NULL AND {c}::numeric > 0)::bigint AS n_pos, "
            "COUNT(*)::bigint AS total "
            "FROM {s}.{t}"
        ).format(c=col, s=sch, t=tbl)
    )
    r = cur.fetchone()
    return int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4])


def fetch_array_counts(
    cur: psycopg.Cursor, schema: str, table: str, column_name: str
) -> tuple[int, int, int, int]:
    col = sql.Identifier(column_name)
    sch = sql.Identifier(schema)
    tbl = sql.Identifier(table)
    cur.execute(
        sql.SQL(
            "SELECT "
            "COUNT(*) FILTER (WHERE {c} IS NULL)::bigint AS n_null, "
            "COUNT(*) FILTER (WHERE {c} IS NOT NULL AND cardinality({c}) = 0)::bigint AS n_empty, "
            "COUNT(*) FILTER (WHERE {c} IS NOT NULL AND cardinality({c}) > 0)::bigint AS n_nonempty, "
            "COUNT(*)::bigint AS total "
            "FROM {s}.{t}"
        ).format(c=col, s=sch, t=tbl)
    )
    r = cur.fetchone()
    return int(r[0]), int(r[1]), int(r[2]), int(r[3])


def fetch_null_total(
    cur: psycopg.Cursor, schema: str, table: str, column_name: str
) -> tuple[int, int]:
    col = sql.Identifier(column_name)
    sch = sql.Identifier(schema)
    tbl = sql.Identifier(table)
    cur.execute(
        sql.SQL(
            "SELECT "
            "COUNT(*) FILTER (WHERE {c} IS NULL)::bigint AS n_null, "
            "COUNT(*)::bigint AS total "
            "FROM {s}.{t}"
        ).format(c=col, s=sch, t=tbl)
    )
    r = cur.fetchone()
    return int(r[0]), int(r[1])


def analyze_column(
    cur: psycopg.Cursor,
    schema: str,
    table: str,
    column_name: str,
    data_type: str,
    udt_name: str,
    field_row_lookup: dict[str, Any],
) -> ColSemantics:
    dt = (data_type or "").lower()
    udt = (udt_name or "").lower()
    fr = field_row_lookup.get(column_name.lower())
    missing_pct = float(fr.missing_pct) if fr else 0.0
    tax = taxonomy_title(fr.taxonomy_bucket) if fr else "—"
    tax_key = str(fr.taxonomy_bucket) if fr else "—"
    total_fr = int(fr.total_rows) if fr else 0

    col_low = column_name.lower()

    if dt == "boolean":
        n_null, n_true, n_false, total = fetch_boolean_counts(cur, schema, table, column_name)
        verdict, notes = _verdict_and_notes(
            col_low=col_low,
            data_type=data_type,
            total=total,
            n_null=n_null,
            n_true=n_true,
            n_false=n_false,
            n_zero=None,
            nn_numeric=None,
            missing_pct_step1=missing_pct,
        )
        nn_b = (n_true or 0) + (n_false or 0)
        return ColSemantics(
            column_name=column_name,
            data_type=data_type,
            udt_name=udt_name,
            total_rows=total,
            taxonomy=tax,
            taxonomy_key=tax_key,
            missing_pct_step1=missing_pct,
            n_null=n_null,
            n_true=n_true,
            n_false=n_false,
            null_pct=pct(n_null, total),
            false_pct_of_nonnull=pct(n_false, nn_b) if nn_b else None,
            recommended_verdict=verdict,
            notes_for_step4=notes,
        )

    if dt in ("character varying", "character", "text", "varchar"):
        n_null, n_blank, n_nonempty, total = fetch_text_counts(cur, schema, table, column_name)
        verdict, notes = _verdict_and_notes(
            col_low=col_low,
            data_type=data_type,
            total=total,
            n_null=n_null,
            n_true=None,
            n_false=None,
            n_zero=None,
            nn_numeric=None,
            missing_pct_step1=missing_pct,
        )
        return ColSemantics(
            column_name=column_name,
            data_type=data_type,
            udt_name=udt_name,
            total_rows=total,
            taxonomy=tax,
            taxonomy_key=tax_key,
            missing_pct_step1=missing_pct,
            n_null=n_null,
            n_blank=n_blank,
            n_nonempty=n_nonempty,
            null_pct=pct(n_null, total),
            recommended_verdict=verdict,
            notes_for_step4=notes,
        )

    if dt in ("smallint", "integer", "bigint", "numeric", "double precision", "real"):
        n_null, n_zero, n_negative, n_positive, total = fetch_numeric_counts(
            cur, schema, table, column_name
        )
        nn_num = total - n_null
        zp = pct(n_zero, nn_num) if nn_num else None
        verdict, notes = _verdict_and_notes(
            col_low=col_low,
            data_type=data_type,
            total=total,
            n_null=n_null,
            n_true=None,
            n_false=None,
            n_zero=n_zero,
            nn_numeric=nn_num,
            missing_pct_step1=missing_pct,
        )
        return ColSemantics(
            column_name=column_name,
            data_type=data_type,
            udt_name=udt_name,
            total_rows=total,
            taxonomy=tax,
            taxonomy_key=tax_key,
            missing_pct_step1=missing_pct,
            n_null=n_null,
            n_zero=n_zero,
            n_negative=n_negative,
            n_positive=n_positive,
            zero_pct_of_nonnull=zp,
            null_pct=pct(n_null, total),
            recommended_verdict=verdict,
            notes_for_step4=notes,
        )

    if dt == "array" or udt.startswith("_"):
        n_null, n_empty_array, n_nonempty_array, total = fetch_array_counts(
            cur, schema, table, column_name
        )
        verdict, notes = _verdict_and_notes(
            col_low=col_low,
            data_type=data_type,
            total=total,
            n_null=n_null,
            n_true=None,
            n_false=None,
            n_zero=None,
            nn_numeric=None,
            missing_pct_step1=missing_pct,
        )
        return ColSemantics(
            column_name=column_name,
            data_type=data_type,
            udt_name=udt_name,
            total_rows=total,
            taxonomy=tax,
            taxonomy_key=tax_key,
            missing_pct_step1=missing_pct,
            n_null=n_null,
            n_empty_array=n_empty_array,
            n_nonempty_array=n_nonempty_array,
            null_pct=pct(n_null, total),
            recommended_verdict=verdict,
            notes_for_step4=notes,
        )

    n_null, total = fetch_null_total(cur, schema, table, column_name)
    if total == 0 and total_fr > 0:
        total = total_fr
    verdict, notes = _verdict_and_notes(
        col_low=col_low,
        data_type=data_type,
        total=total,
        n_null=n_null,
        n_true=None,
        n_false=None,
        n_zero=None,
        nn_numeric=None,
        missing_pct_step1=missing_pct,
    )
    return ColSemantics(
        column_name=column_name,
        data_type=data_type,
        udt_name=udt_name,
        total_rows=total,
        taxonomy=tax,
        taxonomy_key=tax_key,
        missing_pct_step1=missing_pct,
        n_null=n_null,
        null_pct=pct(n_null, total) if total else 0.0,
        recommended_verdict=verdict,
        notes_for_step4=notes or "See PG type; only NULL vs non-NULL summarized here.",
    )


def fetch_hazard_crosstab(
    cur: psycopg.Cursor, schema: str, table: str, known_columns: set[str]
) -> list[dict[str, str | int]]:
    needed = {"liquefaction", "landslide", "alquist_fault"}
    if not needed <= {c.lower() for c in known_columns}:
        return []
    sch = sql.Identifier(schema)
    tbl = sql.Identifier(table)
    q = sql.SQL(
        """
        SELECT
            CASE WHEN liquefaction IS NULL THEN 'N' WHEN liquefaction THEN 'T' ELSE 'F' END AS liquefaction,
            CASE WHEN landslide IS NULL THEN 'N' WHEN landslide THEN 'T' ELSE 'F' END AS landslide,
            CASE WHEN alquist_fault IS NULL THEN 'N' WHEN alquist_fault THEN 'T' ELSE 'F' END AS alquist_fault,
            COUNT(*)::bigint AS row_count
        FROM {s}.{t}
        GROUP BY 1, 2, 3
        ORDER BY row_count DESC
        """
    ).format(s=sch, t=tbl)
    cur.execute(q)
    out: list[dict[str, str | int]] = []
    for r in cur.fetchall():
        out.append(
            {
                "liquefaction": str(r[0]),
                "landslide": str(r[1]),
                "alquist_fault": str(r[2]),
                "row_count": int(r[3]),
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, str | float | int]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def write_bucket_csvs(
    out_root: Path, semantics: list[ColSemantics], fieldnames: list[str]
) -> None:
    """
    Mirrors Step 1 structure: write per-taxonomy exports for easier review.

    Output paths:
      outputs/missingness_step3/<taxonomy_key>/semantics_by_column.csv
    """
    by_bucket: dict[str, list[dict[str, str | float | int]]] = {}
    for s in semantics:
        by_bucket.setdefault(s.taxonomy_key, []).append(s.as_csv_row())

    for bucket_key, rows in by_bucket.items():
        # Keep Step 3 bucketed files separate from the global CSV name.
        write_csv(out_root / bucket_key / "semantics_by_column.csv", rows, fieldnames)


def build_html(
    rows: list[ColSemantics],
    hazard_rows: list[dict[str, str | int]],
    generated_iso: str,
) -> str:
    body_rows = []
    for r in rows:
        summary = ""
        if r.n_true is not None:
            summary = f"T={r.n_true:,} F={r.n_false:,} NULL={r.n_null:,}"
        elif r.n_zero is not None:
            summary = f"0={r.n_zero:,} &lt;0={r.n_negative:,} &gt;0={r.n_positive:,} NULL={r.n_null:,}"
        elif r.n_blank is not None:
            summary = f"blank={r.n_blank:,} text={r.n_nonempty:,} NULL={r.n_null:,}"
        elif r.n_empty_array is not None:
            summary = f"∅arr={r.n_empty_array:,} nonempty={r.n_nonempty_array:,} NULL={r.n_null:,}"
        elif r.n_null is not None:
            summary = f"NULL={r.n_null:,} total={r.total_rows:,}"
        body_rows.append(
            "<tr>"
            f"<td><code>{esc(r.column_name)}</code></td>"
            f"<td>{esc(r.data_type)}</td>"
            f"<td>{esc(r.taxonomy)}</td>"
            f"<td class='num'>{esc(r.missing_pct_step1)}</td>"
            f"<td class='small'>{esc(summary)}</td>"
            f"<td class='small'>{esc(r.recommended_verdict)}</td>"
            f"<td class='small'>{esc(r.notes_for_step4)}</td>"
            "</tr>"
        )
    if hazard_rows:
        hz = "".join(
            "<tr>"
            f"<td><code>{esc(h['liquefaction'])}</code></td>"
            f"<td><code>{esc(h['landslide'])}</code></td>"
            f"<td><code>{esc(h['alquist_fault'])}</code></td>"
            f"<td class='num'>{h['row_count']:,}</td>"
            "</tr>"
            for h in hazard_rows[:40]
        )
    else:
        hz = '<tr><td colspan="4" class="small"><em>liquefaction / landslide / alquist_fault not all present — crosstab skipped.</em></td></tr>'
    n_flagged = sum(1 for r in rows if not r.recommended_verdict.startswith("OK"))
    kpi_block = f"""    <div class="kpi-grid">
      <div class="kpi kpi-fields"><div class="kpi-val">{len(rows):,}</div><div class="kpi-lbl">Columns analyzed</div></div>
      <div class="kpi kpi-alert"><div class="kpi-val">{n_flagged:,}</div><div class="kpi-lbl">Auto-flagged for Step 4</div></div>
    </div>"""
    step_checklist = """    <ol class="checklist">
      <li><span class="ck-i">1</span><strong>Step 1 — Missingness.</strong> Classifies columns (taxonomy) and percent missing — same rules as <code>outputs/missingness_step1/</code>.</li>
      <li><span class="ck-i">2</span><strong>Step 2 — Completeness QA.</strong> Maps, city slices, samples; surfaces “zero semantics” questions.</li>
      <li><span class="ck-i">3</span><strong>Step 3 — Semantics (this report).</strong> Counts how values are stored (NULL vs literals, zeros, blanks) for Step 4 decisions.</li>
      <li><span class="ck-i">4</span><strong>Step 4 — Product review.</strong> Use <code>docs/step-04-product-field-review-template.md</code> with the CSV/HTML from Steps 1–3.</li>
    </ol>
    <p class="muted ck-note"><strong>Hazard crosstab:</strong> each column shows <code>N</code> (NULL), <code>T</code>, or <code>F</code> per field; <strong>rows</strong> is parcel count. <strong>Main table:</strong> distribution snapshot depends on PostgreSQL type (boolean vs numeric vs text).</p>"""
    guide_rows = """
          <tr><th scope="row">Column</th><td>PostgreSQL column name on <code>public.unidata</code>.</td></tr>
          <tr><th scope="row">PG type</th><td>Physical type; drives which counts appear in the snapshot.</td></tr>
          <tr><th scope="row">Taxonomy</th><td>Step 1 category (core parcel, external join, API-fillable, etc.).</td></tr>
          <tr><th scope="row">Step 1 missing %</th><td>Percent failing Step 1 “present” rules (e.g. <code>0</code> counts as missing for selected numerics).</td></tr>
          <tr><th scope="row">Distribution snapshot</th><td>T/F/NULL, zero/positive/negative, blanks, or empty arrays — whichever applies.</td></tr>
          <tr><th scope="row">Auto verdict</th><td>Heuristic flag; confirm in Step 4.</td></tr>
          <tr><th scope="row">Notes for Step 4</th><td>Workshop talking points (docs, UI, API contracts).</td></tr>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Step 3 — Field semantics audit</title>
  <style>
    :root {{
      /* Professional neutrals + single accent (corporate / analytics) */
      --surface: #ffffff;
      --surface-muted: #f9fafb;
      --surface-row: #f8fafc;
      --bg-page: #eef1f5;
      --bg-grad-top: #e4e9f0;
      --text-primary: #111827;
      --text-body: #374151;
      --text-muted: #6b7280;
      --text-on-dark: #f3f4f6;
      --text-on-dark-muted: rgba(243, 244, 246, 0.88);
      --border: #e5e7eb;
      --border-strong: #d1d5db;
      --accent: #0c4a6e;
      --accent-bright: #0369a1;
      --accent-soft: #e0f2fe;
      --kpi-neutral: #64748b;
      --kpi-fields: #0369a1;
      --kpi-alert: #b91c1c;
      --code-bg: #f1f5f9;
      --code-text: #0f172a;
      --code-border: #e2e8f0;
      --shadow-xs: 0 1px 2px rgba(17, 24, 39, 0.04);
      --shadow-sm: 0 1px 3px rgba(17, 24, 39, 0.06);
      --shadow-md: 0 4px 12px rgba(17, 24, 39, 0.07);
      --shadow-lg: 0 12px 32px rgba(17, 24, 39, 0.09);
      --radius-lg: 14px;
      --radius-md: 10px;
      --radius-pill: 999px;
      --font-sans: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif;
      --font-mono: ui-monospace, "Cascadia Mono", "SF Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      font-family: var(--font-sans);
      background: linear-gradient(180deg, var(--bg-grad-top) 0%, var(--bg-page) 18rem, var(--bg-page) 100%);
      color: var(--text-body);
      line-height: 1.6;
      font-size: 15px;
      -webkit-font-smoothing: antialiased;
    }}
    header.hero {{
      background: linear-gradient(155deg, #0b1220 0%, #152232 38%, #0c4a6e 92%);
      color: var(--text-on-dark);
      padding: 2.25rem 2rem 2.5rem;
      box-shadow: var(--shadow-lg);
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }}
    header.hero h1 {{
      margin: 0 0 0.75rem;
      font-size: clamp(1.375rem, 2.4vw, 1.875rem);
      font-weight: 700;
      letter-spacing: -0.025em;
      color: #ffffff;
      line-height: 1.25;
    }}
    header.hero p {{
      margin: 0 0 0.65rem;
      max-width: 46rem;
      color: var(--text-on-dark-muted);
      font-size: 0.96875rem;
    }}
    header.hero strong {{ color: #ffffff; font-weight: 600; }}
    header.hero code {{
      font-family: var(--font-mono);
      font-size: 0.84em;
      font-weight: 500;
      background: rgba(255, 255, 255, 0.11);
      color: #f8fafc;
      padding: 0.2rem 0.55rem;
      border-radius: 6px;
      border: 1px solid rgba(255, 255, 255, 0.2);
      letter-spacing: 0.01em;
    }}
    header.hero time {{
      display: block;
      margin-top: 0.35rem;
      font-size: 0.8125rem;
      font-weight: 500;
      color: rgba(226, 232, 240, 0.75);
      font-variant-numeric: tabular-nums;
    }}
    .jump {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      justify-content: center;
      padding: 0.875rem 1.5rem;
      background: rgba(255, 255, 255, 0.72);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border);
    }}
    .jump a {{
      font-size: 0.8125rem;
      font-weight: 600;
      color: var(--accent);
      text-decoration: none;
      padding: 0.5rem 1rem;
      border-radius: var(--radius-pill);
      background: var(--surface);
      border: 1px solid var(--border);
      box-shadow: var(--shadow-xs);
      transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    }}
    .jump a:hover {{
      background: var(--accent-soft);
      border-color: #7dd3fc;
      color: #075985;
    }}
    .jump a:focus-visible {{
      outline: 2px solid var(--accent-bright);
      outline-offset: 2px;
    }}
    main {{ max-width: 78rem; margin: 0 auto; padding: 1.75rem 1.25rem 3.5rem; }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 1.5rem 1.625rem;
      margin-bottom: 1.5rem;
      box-shadow: var(--shadow-sm);
    }}
    .panel h2 {{
      margin: 0 0 0.875rem;
      font-size: 1.125rem;
      font-weight: 700;
      color: var(--text-primary);
      letter-spacing: -0.015em;
    }}
    .muted {{ color: var(--text-muted); font-size: 0.875rem; line-height: 1.6; }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
      gap: 1rem;
      margin-bottom: 1.25rem;
    }}
    .kpi {{
      background: var(--surface);
      border-radius: var(--radius-md);
      padding: 1.125rem 1.25rem;
      border: 1px solid var(--border);
      box-shadow: var(--shadow-xs);
      border-left: 4px solid var(--kpi-neutral);
    }}
    .kpi-fields {{ border-left-color: var(--kpi-fields); }}
    .kpi-alert {{ border-left-color: var(--kpi-alert); }}
    .kpi-val {{
      font-size: 1.5rem;
      font-weight: 800;
      font-variant-numeric: tabular-nums;
      color: var(--text-primary);
      letter-spacing: -0.02em;
      line-height: 1.2;
    }}
    .kpi-lbl {{
      font-size: 0.6875rem;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
      margin-top: 0.375rem;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.8125rem; }}
    .stripe td {{ color: var(--text-body); }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 0.7rem 0.85rem;
      text-align: left;
      vertical-align: middle;
    }}
    thead th {{
      background: linear-gradient(180deg, #f9fafb 0%, #f3f4f6 100%);
      font-weight: 700;
      color: var(--text-primary);
      font-size: 0.6875rem;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      border-bottom: 2px solid var(--border-strong);
    }}
    thead th.num {{ text-align: right; }}
    tbody th[scope="row"] {{
      background: var(--surface-muted);
      font-weight: 600;
      color: var(--text-primary);
      text-align: left;
      border-right: 1px solid var(--border);
      font-size: 0.8125rem;
    }}
    tbody tr {{ transition: background 0.1s ease; }}
    tbody tr:hover {{ background: #f3f8fb; }}
    .stripe tbody tr:nth-child(even) {{ background: var(--surface-row); }}
    .stripe tbody tr:nth-child(even):hover {{ background: #eef5f9; }}
    .num {{
      text-align: right;
      font-variant-numeric: tabular-nums;
      color: var(--text-body);
    }}
    td.small {{
      font-size: 0.8125rem;
      color: var(--text-body);
      max-width: 22rem;
      line-height: 1.55;
      vertical-align: top;
    }}
    code {{
      font-family: var(--font-mono);
      font-size: 0.78em;
      font-weight: 500;
      background: var(--code-bg);
      color: var(--code-text);
      padding: 0.15rem 0.45rem;
      border-radius: 5px;
      border: 1px solid var(--code-border);
    }}
    .table-wrap {{ overflow-x: auto; margin: 0.5rem 0 0; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--surface); }}
    .table-wrap.tall {{
      max-height: 75vh;
      overflow: auto;
      margin-top: 1rem;
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-xs);
    }}
    .table-wrap.tall thead th {{
      position: sticky;
      top: 0;
      z-index: 2;
      box-shadow: 0 1px 0 var(--border-strong);
    }}
    .table-wrap.tall table {{ margin: 0; }}
    .checklist {{ list-style: none; padding: 0; margin: 0; }}
    .checklist li {{
      display: flex;
      gap: 0.75rem;
      align-items: flex-start;
      padding: 0.8rem 1rem;
      margin-bottom: 0.5rem;
      background: var(--surface-muted);
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      color: var(--text-body);
      line-height: 1.55;
    }}
    .ck-i {{
      flex-shrink: 0;
      width: 1.75rem;
      height: 1.75rem;
      border-radius: 7px;
      background: linear-gradient(145deg, var(--accent-bright) 0%, var(--accent) 100%);
      color: #ffffff;
      font-weight: 800;
      font-size: 0.8125rem;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 1px 2px rgba(12, 74, 110, 0.35);
    }}
    .ck-note {{ margin-top: 1rem; margin-bottom: 0; }}
    .file-ref {{ font-size: 0.8125rem; margin: 1rem 0 0; color: var(--text-muted); }}
    .file-ref code {{
      background: #eef2f6;
      color: #334155;
      border-color: #dbe1e8;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <header class="hero">
    <h1>Next-stage work plan · Step 3: Field semantics audit</h1>
    <p><strong>What this is:</strong> Measures <strong>how values are stored</strong> (NULL vs <code>FALSE</code> vs <code>TRUE</code>, NULL vs numeric <code>0</code>, blanks, empty arrays), not only “how many cells look empty.” Use with Step 2 completeness QA and Step 4 product review.</p>
    <p><strong>Use it with:</strong> Step 2 “zero semantics” notes and <code>docs/step-04-product-field-review-template.md</code> — Step 3 supplies counts; Step 4 records product decisions.</p>
    <p><time datetime="{esc(generated_iso)}">Generated {esc(generated_iso)}</time></p>
  </header>
  <nav class="jump" aria-label="Section navigation">
    <a href="#about">Overview</a>
    <a href="#kpis">Snapshot</a>
    <a href="#hazard">Hazard crosstab</a>
    <a href="#columns">Per-column table</a>
  </nav>
  <main>
    <section id="kpis">{kpi_block}</section>
    <section class="panel" id="about">
      <h2>How this report fits the plan</h2>
      <p class="muted">Same layout conventions as Step 2 (<code>field_completeness_report_step2.py</code>). Each step adds evidence before the workshop.</p>
{step_checklist}
    </section>
    <section class="panel" id="hazard">
      <h2>Hazard booleans — joint patterns</h2>
      <p class="muted">Each row is one stored combination for <code>liquefaction</code>, <code>landslide</code>, and <code>alquist_fault</code>. The <strong>rows</strong> column counts parcels in that combination.</p>
      <div class="table-wrap">
        <table class="stripe">
          <thead><tr><th>liquefaction</th><th>landslide</th><th>alquist_fault</th><th class="num">rows</th></tr></thead>
          <tbody>{hz}</tbody>
        </table>
      </div>
      <p class="muted file-ref">Export: <code>outputs/missingness_step3/hazard_boolean_crosstab.csv</code></p>
    </section>
    <section class="panel" id="columns">
      <h2>Per-column semantics</h2>
      <p class="muted">One row per column. Distribution snapshot depends on PostgreSQL type (boolean vs numeric vs text vs array).</p>
      <div class="table-wrap">
        <table class="stripe">
          <thead><tr><th scope="col">Column header</th><th scope="col">Meaning</th></tr></thead>
          <tbody>{guide_rows}
          </tbody>
        </table>
      </div>
      <div class="table-wrap tall">
        <table class="stripe">
          <thead>
            <tr>
              <th>Column</th><th>PG type</th><th>Taxonomy</th><th class="num">Step 1 missing %</th>
              <th>Distribution snapshot</th><th>Auto verdict</th><th>Notes for Step 4</th>
            </tr>
          </thead>
          <tbody>{"".join(body_rows)}</tbody>
        </table>
      </div>
      <p class="muted file-ref">Export: <code>outputs/missingness_step3/semantics_by_column.csv</code></p>
    </section>
  </main>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Step 3 field semantics audit")
    p.add_argument("--db-schema", default="public")
    p.add_argument("--db-table", default="unidata")
    p.add_argument(
        "--out-root",
        type=Path,
        default=_repo_root() / "outputs" / "missingness_step3",
        help="Output directory",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    schema, table = args.db_schema, args.db_table
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    field_rows = compute_field_rows(schema, table, DEFAULT_DB_CONFIG)
    lookup = {r.column_name.lower(): r for r in field_rows}

    semantics: list[ColSemantics] = []
    conn_kw = {**DEFAULT_DB_CONFIG, "connect_timeout": 25}
    with psycopg.connect(**conn_kw) as conn:
        conn.autocommit = True
        cur = conn.cursor()
        cols = fetch_columns(cur, schema, table)
        for column_name, data_type, udt_name in cols:
            semantics.append(
                analyze_column(cur, schema, table, column_name, data_type, udt_name, lookup)
            )
        hazard = fetch_hazard_crosstab(cur, schema, table, {c[0] for c in cols})

    fieldnames = [
        "column_name",
        "data_type",
        "udt_name",
        "total_rows",
        "taxonomy",
        "taxonomy_key",
        "missing_pct_step1",
        "n_null",
        "n_true",
        "n_false",
        "n_blank",
        "n_nonempty",
        "n_zero",
        "n_negative",
        "n_positive",
        "n_empty_array",
        "n_nonempty_array",
        "zero_pct_of_nonnull",
        "null_pct",
        "false_pct_of_nonnull",
        "recommended_verdict",
        "notes_for_step4",
    ]
    write_csv(
        out_root / "semantics_by_column.csv",
        [s.as_csv_row() for s in semantics],
        fieldnames,
    )
    write_bucket_csvs(out_root, semantics, fieldnames)
    hz_names = ["liquefaction", "landslide", "alquist_fault", "row_count"]
    write_csv(out_root / "hazard_boolean_crosstab.csv", hazard, hz_names)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    html_doc = build_html(semantics, hazard, generated)
    (out_root / "report.html").write_text(html_doc, encoding="utf-8")

    print(f"Wrote {out_root / 'report.html'}")
    print(f"Wrote {out_root / 'semantics_by_column.csv'}")
    print(f"Wrote {out_root / 'hazard_boolean_crosstab.csv'} ({len(hazard)} patterns)")


if __name__ == "__main__":
    main()
