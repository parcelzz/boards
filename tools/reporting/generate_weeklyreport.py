"""
Generate a single weekly HTML report (Steps 1–5).

Output: outputs/weeklyreport.html

This is a presentation artifact meant to be readable and concrete:
- short narrative + "what changed / what matters"
- key numbers
- small tables & bars for top issues
- deep links to Step 1–3 HTML reports and raw CSVs
- includes Step 4/5 workshop docs (Markdown) rendered into HTML blocks
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _f(s: str | None) -> float:
    try:
        return float(s) if s not in (None, "", "—") else 0.0
    except ValueError:
        return 0.0


def _i(s: str | None) -> int:
    try:
        return int(float(s)) if s not in (None, "", "—") else 0
    except ValueError:
        return 0


def esc(s: object) -> str:
    return html.escape(str(s), quote=False)


def _rel(from_dir: Path, to_path: Path) -> str:
    try:
        return to_path.resolve().relative_to(from_dir.resolve()).as_posix()
    except Exception:
        # Fallback: best-effort as_posix
        return to_path.as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _md_to_html(md: str) -> str:
    """
    Tiny, safe Markdown renderer for *this repo's templates*:
    - headings (#, ##, ###)
    - paragraphs
    - bullet lists (- )
    - fenced code blocks (```...```)
    - tables (pipe syntax)
    Everything else is escaped.
    """
    lines = md.splitlines()
    out: list[str] = []
    i = 0

    def flush_paragraph(buf: list[str]) -> None:
        if not buf:
            return
        text = " ".join(x.strip() for x in buf).strip()
        if text:
            out.append(f"<p>{esc(text)}</p>")
        buf.clear()

    def is_table_row(s: str) -> bool:
        return "|" in s and s.strip().startswith("|") and s.strip().endswith("|")

    paragraph: list[str] = []
    in_code = False
    code_lang = ""
    code_buf: list[str] = []

    while i < len(lines):
        ln = lines[i]
        if in_code:
            if ln.strip().startswith("```"):
                code = "\n".join(code_buf)
                out.append(
                    f"<pre><code class='lang-{esc(code_lang)}'>{html.escape(code)}</code></pre>"
                )
                in_code = False
                code_lang = ""
                code_buf.clear()
            else:
                code_buf.append(ln)
            i += 1
            continue

        if ln.strip().startswith("```"):
            flush_paragraph(paragraph)
            in_code = True
            code_lang = ln.strip().lstrip("```").strip()
            i += 1
            continue

        m = re.match(r"^(#{1,3})\s+(.*)$", ln)
        if m:
            flush_paragraph(paragraph)
            level = len(m.group(1))
            text = m.group(2).strip()
            out.append(f"<h{level}>{esc(text)}</h{level}>")
            i += 1
            continue

        if ln.strip().startswith("- "):
            flush_paragraph(paragraph)
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append("<ul>" + "".join(f"<li>{esc(it)}</li>" for it in items) + "</ul>")
            continue

        if is_table_row(ln):
            flush_paragraph(paragraph)
            rows: list[list[str]] = []
            while i < len(lines) and is_table_row(lines[i]):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(row)
                i += 1

            # Optional separator row exists as the 2nd row; remove if it looks like ---.
            if len(rows) >= 2 and all(re.fullmatch(r"-{2,}\s*", c.replace(":", "")) for c in rows[1]):
                header = rows[0]
                body = rows[2:]
            else:
                header = rows[0]
                body = rows[1:]

            thead = "<thead><tr>" + "".join(f"<th>{esc(c)}</th>" for c in header) + "</tr></thead>"
            tbody = "<tbody>" + "".join(
                "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in body
            ) + "</tbody>"
            out.append(f"<div class='table-wrap'><table>{thead}{tbody}</table></div>")
            continue

        if not ln.strip():
            flush_paragraph(paragraph)
            i += 1
            continue

        paragraph.append(ln)
        i += 1

    flush_paragraph(paragraph)
    return "\n".join(out)


@dataclass(frozen=True)
class Step1Field:
    column_name: str
    taxonomy: str
    taxonomy_key: str
    missing_pct: float
    missing_count: int
    total_rows: int
    behavior_risk: str
    review_priority: str


@dataclass(frozen=True)
class Step2Field:
    column_name: str
    missing_pct: float
    spatial_verdict: str
    city_verdict: str
    segment_verdict: str
    examples_csv: str


@dataclass(frozen=True)
class Step3Field:
    column_name: str
    recommended_verdict: str
    notes_for_step4: str


def load_step1(path: Path) -> list[Step1Field]:
    rows = _read_csv(path)
    out: list[Step1Field] = []
    for r in rows:
        out.append(
            Step1Field(
                column_name=r.get("column_name", "").strip(),
                taxonomy=r.get("taxonomy", "").strip(),
                taxonomy_key=r.get("taxonomy_key", "").strip(),
                missing_pct=_f(r.get("missing_pct")),
                missing_count=_i(r.get("missing_count")),
                total_rows=_i(r.get("total_rows")),
                behavior_risk=r.get("product_behavior_risk", "").strip(),
                review_priority=r.get("review_priority", "").strip(),
            )
        )
    return out


def load_step2(path: Path) -> dict[str, Step2Field]:
    rows = _read_csv(path)
    out: dict[str, Step2Field] = {}
    for r in rows:
        col = r.get("column_name", "").strip()
        if not col:
            continue
        out[col.lower()] = Step2Field(
            column_name=col,
            missing_pct=_f(r.get("missing_pct")),
            spatial_verdict=r.get("spatial_verdict", "").strip(),
            city_verdict=r.get("city_verdict", "").strip(),
            segment_verdict=r.get("segment_verdict", "").strip(),
            examples_csv=r.get("examples_csv", "").strip(),
        )
    return out


def load_step3(path: Path) -> dict[str, Step3Field]:
    rows = _read_csv(path)
    out: dict[str, Step3Field] = {}
    for r in rows:
        col = r.get("column_name", "").strip()
        if not col:
            continue
        out[col.lower()] = Step3Field(
            column_name=col,
            recommended_verdict=r.get("recommended_verdict", "").strip(),
            notes_for_step4=r.get("notes_for_step4", "").strip(),
        )
    return out


def bar_row(label: str, pct: float) -> str:
    # Backwards compat helper (kept for other uses).
    w = min(100.0, max(0.0, pct))
    color = "#dc2626" if pct >= 25 else "#d97706" if pct >= 5 else "#16a34a"
    return f"""
    <div class="bar-row-simple">
      <div class="bar-label"><code>{esc(label)}</code></div>
      <div class="bar-track" title="{esc(f"{pct:.2f}%")}">
        <span class="bar-fill" style="width:{w:.1f}%;background:{color}"></span>
      </div>
      <div class="bar-pct">{esc(f"{pct:.2f}%")}</div>
    </div>
    """


def stacked_row(*, label: str, missing: int, total: int) -> str:
    present = max(0, total - missing)
    missing_pct = (missing / total * 100.0) if total else 0.0
    present_pct = 100.0 - missing_pct
    # Data attributes let JS re-scale bars.
    return f"""
    <div class="stack-row" data-total="{total}" data-missing="{missing}">
      <div class="stack-label"><code>{esc(label)}</code></div>
      <div class="stack-bar" title="{esc(f"missing {missing:,} / {total:,} ({missing_pct:.2f}%)")}">
        <span class="seg seg-present" data-pct="{present_pct:.6f}"></span>
        <span class="seg seg-missing" data-pct="{missing_pct:.6f}"></span>
      </div>
      <div class="stack-metric">
        <span class="m-pct">{esc(f"{missing_pct:.2f}%")}</span>
        <span class="m-abs">{esc(f"{missing:,}")}</span>
      </div>
    </div>
    """


def build_html_report(
    *,
    out_path: Path,
    step1: list[Step1Field],
    step2: dict[str, Step2Field],
    step3: dict[str, Step3Field],
    step4_md: str,
    step5_md: str,
    generated_iso: str,
) -> str:
    total_rows = max((f.total_rows for f in step1), default=0)
    n_cols = len(step1)
    high_behavior = sum(1 for f in step1 if f.behavior_risk == "High")
    moderate_behavior = sum(1 for f in step1 if f.behavior_risk == "Moderate")

    top_missing = sorted(step1, key=lambda f: (-f.missing_pct, f.column_name.lower()))[:10]
    top_missing_html = "".join(
        stacked_row(label=f.column_name, missing=f.missing_count, total=f.total_rows) for f in top_missing
    )

    # Step 4/5: render to HTML blocks
    step4_html = _md_to_html(step4_md)
    step5_html = _md_to_html(step5_md)

    base_dir = out_path.parent
    links = {
        "step1_html": _rel(base_dir, _repo_root() / "outputs/missingness_step1/report.html"),
        "step2_html": _rel(base_dir, _repo_root() / "outputs/missingness_step2/report.html"),
        "step3_html": _rel(base_dir, _repo_root() / "outputs/missingness_step3/report.html"),
        "step1_csv": _rel(base_dir, _repo_root() / "outputs/missingness_step1/field_missingness_all.csv"),
        "step2_csv": _rel(base_dir, _repo_root() / "outputs/missingness_step2/field_completeness_summary.csv"),
        "step3_csv": _rel(base_dir, _repo_root() / "outputs/missingness_step3/semantics_by_column.csv"),
        "task2_html": _rel(base_dir, _repo_root() / "outputs/parcel_audits/task2_santa_clara_residential_audit.html"),
        "unidata_vs_gpkg_html": _rel(base_dir, _repo_root() / "outputs/parcel_audits/unidata_v22_vs_gpkg_audit.html"),
    }

    # Build a small "issues" table that merges evidence across steps for the biggest missingness fields.
    def issue_rows() -> str:
        rows = []
        for f in top_missing[:8]:
            s2 = step2.get(f.column_name.lower())
            s3 = step3.get(f.column_name.lower())
            spatial = s2.spatial_verdict if s2 else "—"
            city = s2.city_verdict if s2 else "—"
            segment = s2.segment_verdict if s2 else "—"
            verdict = s3.recommended_verdict if s3 else "—"
            note = s3.notes_for_step4 if s3 else ""
            rows.append(
                "<tr>"
                f"<td><code>{esc(f.column_name)}</code></td>"
                f"<td class='num'>{esc(f'{f.missing_pct:.2f}%')}</td>"
                f"<td>{esc(f.taxonomy)}</td>"
                f"<td><span class='pill pill-{esc(f.behavior_risk.lower() or 'low')}'>{esc(f.behavior_risk or '—')}</span></td>"
                f"<td><span class='pill pill-prio'>{esc(f.review_priority or '—')}</span></td>"
                f"<td class='small'>{esc(spatial)}; {esc(city)}; {esc(segment)}</td>"
                f"<td class='small'>{esc(verdict)}{(' — ' + esc(note)) if note else ''}</td>"
                "</tr>"
            )
        return "".join(rows)

    issues_table = f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Field</th>
            <th class="num">Missing %</th>
            <th>Bucket</th>
            <th>Behavior risk</th>
            <th>Review priority</th>
            <th>Step 2 QA (spatial/city/segment)</th>
            <th>Step 3 semantics flags</th>
          </tr>
        </thead>
        <tbody>{issue_rows()}</tbody>
      </table>
    </div>
    """

    # Secondary chart: "Top 10 review priority" — order by P0/P1 first, then missing %.
    def prio_rank(p: str) -> int:
        s = (p or "").upper()
        if "P0" in s:
            return 0
        if "P1" in s:
            return 1
        if "P2" in s:
            return 2
        return 3

    top_prio = sorted(step1, key=lambda f: (prio_rank(f.review_priority), -f.missing_pct, f.column_name.lower()))[:10]
    top_prio_html = "".join(
        stacked_row(label=f"{f.column_name}", missing=f.missing_count, total=f.total_rows) for f in top_prio
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Weekly data quality report (Steps 1–5)</title>
  <style>
    :root {{
      --bg: #e9e3dd;          /* warm page background like the example */
      --bg2: #e3ddd7;
      --card: #f7f4ef;        /* paper */
      --card2: #fbf9f6;
      --text: #2b2b2b;
      --muted: #666666;
      --line: rgba(0,0,0,0.12);
      --shadow: 0 6px 18px rgba(0,0,0,0.12);
      --title: #d35a1d;       /* warm orange title */
      --accent: #2d6cdf;
      --present: #b9c2cc;     /* neutral gray */
      --missing: #e0504e;     /* red */
    }}
    [data-theme="dark"] {{
      --bg: #0f1217;
      --bg2: #0b0e12;
      --card: #111827;
      --card2: #0f172a;
      --text: #e5e7eb;
      --muted: rgba(229,231,235,0.72);
      --line: rgba(255,255,255,0.14);
      --shadow: 0 10px 28px rgba(0,0,0,0.55);
      --title: #ffb07a;
      --accent: #7dd3fc;
      --present: #6b7280;
      --missing: #f87171;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: linear-gradient(180deg, var(--bg2) 0%, var(--bg) 100%);
      color: var(--text);
      line-height: 1.55;
      font-size: 15px;
    }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(0,0,0,0.08);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }}
    .topbar-inner {{
      max-width: 980px;
      margin: 0 auto;
      padding: 10px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .brand {{
      font-weight: 800;
      letter-spacing: 0.02em;
      font-size: 13px;
      text-transform: uppercase;
      color: var(--text);
      opacity: 0.9;
    }}
    .toggles {{
      display: flex;
      align-items: center;
      gap: 14px;
      color: var(--muted);
      font-size: 12px;
      user-select: none;
      white-space: nowrap;
    }}
    .toggle {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .switch {{
      width: 40px;
      height: 22px;
      border-radius: 999px;
      background: rgba(255,255,255,0.55);
      border: 1px solid var(--line);
      position: relative;
      box-shadow: inset 0 1px 2px rgba(0,0,0,0.15);
    }}
    [data-theme="dark"] .switch {{ background: rgba(255,255,255,0.14); }}
    .switch::after {{
      content: "";
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #fff;
      position: absolute;
      top: 1px;
      left: 1px;
      transition: transform 0.15s ease;
      box-shadow: 0 2px 6px rgba(0,0,0,0.25);
    }}
    input[type="checkbox"] {{ display: none; }}
    input[type="checkbox"]:checked + .switch::after {{ transform: translateX(18px); }}

    /* Chart toggle styled like the example (pill + pink knob) */
    .chart-toggle {{
      margin-top: 10px;
      display: flex;
      justify-content: flex-start;
    }}
    .scale-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      user-select: none;
    }}
    .pill-switch {{
      width: 46px;
      height: 24px;
      border-radius: 999px;
      background: rgba(0,0,0,0.18);
      border: 1px solid var(--line);
      position: relative;
      box-shadow: inset 0 1px 2px rgba(0,0,0,0.25);
      flex-shrink: 0;
    }}
    [data-theme="dark"] .pill-switch {{
      background: rgba(255,255,255,0.12);
      box-shadow: inset 0 1px 2px rgba(0,0,0,0.55);
    }}
    .pill-switch::after {{
      content: "";
      width: 18px;
      height: 18px;
      border-radius: 50%;
      position: absolute;
      top: 2px;
      left: 2px;
      background: #f3f4f6;
      box-shadow: 0 2px 8px rgba(0,0,0,0.35);
      transition: transform 0.15s ease, background 0.15s ease;
    }}
    input.scaleToggle:checked + .pill-switch::after {{
      transform: translateX(22px);
      background: #ff4fa3;
    }}
    .scale-label {{ color: var(--muted); }}

    main {{ max-width: 980px; margin: 0 auto; padding: 18px 14px 56px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px 22px;
      margin: 16px auto;
      box-shadow: var(--shadow);
    }}
    .card.tight {{ padding: 14px 18px; }}
    .hero-title {{
      text-align: center;
      color: var(--title);
      font-weight: 800;
      font-size: 22px;
      line-height: 1.25;
      margin: 2px 0 10px;
    }}
    .hero-sub {{
      text-align: center;
      color: var(--muted);
      margin: 0 0 12px;
      font-size: 13px;
    }}
    .prose {{ font-size: 13px; color: var(--text); }}
    .prose p {{ margin: 8px 0; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    a {{ color: var(--accent); }}
    a:hover {{ text-decoration: underline; }}

    .section-title {{
      text-align: center;
      font-weight: 800;
      color: var(--title);
      margin: 0 0 10px;
      font-size: 18px;
    }}
    .section-sub {{
      text-align: center;
      color: var(--muted);
      margin: 0 0 14px;
      font-size: 12px;
    }}
    code {{
      font-family: ui-monospace, Consolas, monospace;
      background: rgba(255,255,255,0.55);
      color: inherit;
      padding: 2px 6px;
      border-radius: 6px;
      font-size: 12px;
      border: 1px solid var(--line);
    }}
    .stack-row {{
      display: grid;
      grid-template-columns: 240px 1fr 120px;
      gap: 10px;
      align-items: center;
      margin: 10px 0;
      font-size: 12px;
    }}
    .stack-label {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      padding-right: 6px;
    }}
    .stack-bar {{
      height: 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.40);
      border-radius: 4px;
      overflow: hidden;
      display: flex;
    }}
    .seg {{ height: 100%; display: block; }}
    .seg-present {{ background: var(--present); }}
    .seg-missing {{ background: var(--missing); }}
    .stack-metric {{
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      font-variant-numeric: tabular-nums;
      color: var(--muted);
      white-space: nowrap;
    }}
    .stack-metric .m-pct {{ color: var(--text); font-weight: 650; }}
    .stack-metric .m-abs {{ display: none; }}
    .abs-mode .stack-metric .m-abs {{ display: inline; }}
    .abs-mode .stack-metric .m-pct {{ display: none; }}

    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--card2); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px 10px; text-align: left; vertical-align: top; }}
    thead th {{
      background: rgba(255,255,255,0.55);
      font-weight: 800;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: var(--muted);
    }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    td.small {{ color: #475569; font-size: 12px; }}
    .pill {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
      border: 1px solid var(--line);
      background: #f8fafc;
      color: #334155;
      white-space: nowrap;
    }}
    .pill-high {{ background: #fee2e2; border-color: #fecaca; color: #991b1b; }}
    .pill-moderate {{ background: #fef3c7; border-color: #fde68a; color: #92400e; }}
    .pill-low {{ background: #dcfce7; border-color: #bbf7d0; color: #166534; }}
    .pill-prio {{ background: #e0f2fe; border-color: #bae6fd; color: #075985; }}

    @media (max-width: 760px) {{
      .stack-row {{ grid-template-columns: 170px 1fr 100px; }}
    }}
    pre {{
      background: rgba(0,0,0,0.12);
      color: var(--text);
      padding: 12px 14px;
      border-radius: 8px;
      overflow: auto;
      border: 1px solid var(--line);
    }}
    pre code {{ background: transparent; color: inherit; padding: 0; border-radius: 0; }}
  </style>
</head>
<body data-theme="light">
  <div class="topbar">
    <div class="topbar-inner">
      <div class="brand">Audit_unidata — Weekly report</div>
      <div class="toggles">
        <label class="toggle" title="Toggle dark mode">
          <span>Dark</span>
          <input id="darkToggle" type="checkbox" />
          <span class="switch" aria-hidden="true"></span>
        </label>
      </div>
    </div>
  </div>

  <main>
    <section class="card" id="summary">
      <h1 class="hero-title">Unidata Data Quality — Weekly Results (Steps 1–5)</h1>
      <p class="hero-sub">Generated {esc(generated_iso)} · evidence in `outputs/` · decisions in `docs/`</p>
      <div class="prose">
        <p><strong>Rows scanned:</strong> <code>{esc(f"{total_rows:,}")}</code> · <strong>Columns analyzed:</strong> <code>{esc(n_cols)}</code></p>
        <p><strong>Behavior risk:</strong> High <code>{esc(high_behavior)}</code>, Moderate <code>{esc(moderate_behavior)}</code>.</p>
        <p class="muted">This report is designed to be scan-friendly (like the example link): headline first, then charts, then drill-down artifacts.</p>
      </div>
      <div class="muted" style="margin-top:10px">
        Jump to: <a href="#top-missing">Top missing</a> · <a href="#top-prio">Top priority</a> · <a href="#evidence">Evidence</a> · <a href="#step4">Step 4</a> · <a href="#step5">Step 5</a>
      </div>
    </section>

    <section class="card tight" id="top-missing">
      <h2 class="section-title">Top 10 Missing Fields</h2>
      <p class="section-sub">Missing vs present (toggle: percent scale vs absolute missing counts)</p>
      {top_missing_html}
      <div class="chart-toggle">
        <label class="scale-toggle" title="Switch between percent scale and absolute missing counts">
          <input class="scaleToggle" type="checkbox" checked />
          <span class="pill-switch" aria-hidden="true"></span>
          <span class="scale-label">Scale bars to 100%</span>
        </label>
      </div>
      <div class="muted" style="margin-top:10px">
        Legend: <span style="display:inline-block;width:10px;height:10px;background:var(--present);border:1px solid var(--line);vertical-align:middle"></span> present
        · <span style="display:inline-block;width:10px;height:10px;background:var(--missing);border:1px solid var(--line);vertical-align:middle"></span> missing
      </div>
    </section>

    <section class="card tight" id="top-prio">
      <h2 class="section-title">Top 10 Review Priority (Step 1 suggestion)</h2>
      <p class="section-sub">Sorted by P0/P1 first, then missing %</p>
      {top_prio_html}
      <div class="chart-toggle">
        <label class="scale-toggle" title="Switch between percent scale and absolute missing counts">
          <input class="scaleToggle" type="checkbox" checked />
          <span class="pill-switch" aria-hidden="true"></span>
          <span class="scale-label">Scale bars to 100%</span>
        </label>
      </div>
    </section>

    <section class="card" id="evidence">
      <h2 class="section-title">Evidence (Steps 1–3)</h2>
      <p class="section-sub">Computed audits (source of truth)</p>
      <div class="prose">
        <p>
          Step 1: <a href="{esc(links['step1_html'])}">report.html</a> · <a href="{esc(links['step1_csv'])}">field_missingness_all.csv</a><br/>
          Step 2: <a href="{esc(links['step2_html'])}">report.html</a> · <a href="{esc(links['step2_csv'])}">field_completeness_summary.csv</a><br/>
          Step 3: <a href="{esc(links['step3_html'])}">report.html</a> · <a href="{esc(links['step3_csv'])}">semantics_by_column.csv</a>
        </p>
        <p class="muted">Below is a merged view for the biggest missingness fields (Step 2 QA + Step 3 semantics flags).</p>
      </div>
      {issues_table}
    </section>

    <section class="card" id="step4">
      <h2 class="section-title">Step 4 — Product Field Review</h2>
      <p class="section-sub">Decision log (fill agreed priority + user-facing behavior)</p>
      {step4_html}
    </section>

    <section class="card" id="step5">
      <h2 class="section-title">Step 5 — External Source Evaluation</h2>
      <p class="section-sub">Seeded from Step 1 P0/P1 candidates</p>
      {step5_html}
    </section>

    <section class="card tight" id="appendix">
      <h2 class="section-title">Appendix</h2>
      <p class="section-sub">Other audits for context</p>
      <div class="prose">
        <p>
          <a href="{esc(links['task2_html'])}">Task 2 residential coverage</a><br/>
          <a href="{esc(links['unidata_vs_gpkg_html'])}">Unidata vs GPKG audit</a>
        </p>
      </div>
    </section>
  </main>

  <script>
    function setTheme(isDark) {{
      document.body.setAttribute('data-theme', isDark ? 'dark' : 'light');
    }}

    function applyScaleMode(scaleTo100) {{
      // scaleTo100=true: segments use pct-of-total. false: segments use absolute values relative to max total among visible rows.
      const rows = Array.from(document.querySelectorAll('.stack-row'));
      if (!rows.length) return;

      if (scaleTo100) {{
        document.body.classList.remove('abs-mode');
        rows.forEach((r) => {{
          const missing = Number(r.dataset.missing || 0);
          const total = Number(r.dataset.total || 0);
          const present = Math.max(0, total - missing);
          const mp = total > 0 ? (missing / total) * 100 : 0;
          const pp = 100 - mp;
          const segP = r.querySelector('.seg-present');
          const segM = r.querySelector('.seg-missing');
          if (segP) segP.style.width = pp.toFixed(4) + '%';
          if (segM) segM.style.width = mp.toFixed(4) + '%';
        }});
      }} else {{
        document.body.classList.add('abs-mode');
        const maxTotal = Math.max(...rows.map(r => Number(r.dataset.total || 0)));
        rows.forEach((r) => {{
          const missing = Number(r.dataset.missing || 0);
          const total = Number(r.dataset.total || 0);
          const present = Math.max(0, total - missing);
          const scale = maxTotal > 0 ? 100 / maxTotal : 0;
          const segP = r.querySelector('.seg-present');
          const segM = r.querySelector('.seg-missing');
          if (segP) segP.style.width = (present * scale).toFixed(4) + '%';
          if (segM) segM.style.width = (missing * scale).toFixed(4) + '%';
        }});
      }}
    }}

    // Wire toggles
    const dark = document.getElementById('darkToggle');
    if (dark) {{
      dark.addEventListener('change', () => setTheme(dark.checked));
    }}
    const scales = Array.from(document.querySelectorAll('input.scaleToggle'));
    scales.forEach((el) => {{
      el.addEventListener('change', () => {{
        scales.forEach((x) => {{ x.checked = el.checked; }});
        applyScaleMode(el.checked);
      }});
    }});

    // Initial state
    setTheme(false);
    applyScaleMode(true);
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    root = _repo_root()
    p = argparse.ArgumentParser(description="Generate weeklyreport.html (Steps 1–5)")
    p.add_argument("--step1", type=Path, default=root / "outputs/missingness_step1/field_missingness_all.csv")
    p.add_argument("--step2", type=Path, default=root / "outputs/missingness_step2/field_completeness_summary.csv")
    p.add_argument("--step3", type=Path, default=root / "outputs/missingness_step3/semantics_by_column.csv")
    p.add_argument("--step4", type=Path, default=root / "docs/step4_product_field_review.md")
    p.add_argument("--step5", type=Path, default=root / "docs/step5_external_data_source_evaluation.md")
    p.add_argument("--out", type=Path, default=root / "outputs/weeklyreport.html")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    step1 = load_step1(args.step1)
    step2 = load_step2(args.step2) if args.step2.exists() else {}
    step3 = load_step3(args.step3) if args.step3.exists() else {}
    step4_md = _read_text(args.step4) if args.step4.exists() else "# Step 4 missing\n"
    step5_md = _read_text(args.step5) if args.step5.exists() else "# Step 5 missing\n"

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = build_html_report(
        out_path=args.out,
        step1=step1,
        step2=step2,
        step3=step3,
        step4_md=step4_md,
        step5_md=step5_md,
        generated_iso=generated,
    )
    args.out.write_text(doc, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()

