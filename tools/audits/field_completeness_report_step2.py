"""
Step 2 — Field completeness report (Next-stage work plan).

Builds on Step 1 taxonomy and presence rules:
  - Summary completeness table (non-null % / missing %)
  - Spatial missingness (lat/lon grid): heterogeneity + Leaflet choropleth GeoJSON
  - Missingness by normalized city (scity)
  - Missingness by footprint / sqft proxies (parcel-type proxies — Unidata has no usecode)
  - Default-zero ambiguity flags (numeric columns)
  - Example problematic rows (CSV per featured field)
  - Single QA HTML report + CSV exports under outputs/missingness_step2/

Run from repo root:
  python tools/audits/field_completeness_report_step2.py
"""
from __future__ import annotations

import argparse
import csv
import html as html_module
import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from field_missingness_classification import (
    API_FILLABLE,
    CORE_PARCEL,
    DEFAULT_DB_CONFIG,
    EXTERNAL_JOIN,
    FieldRow,
    FOOTPRINT,
    NUMERIC_ZERO_EMPTY,
    SOURCE_MISSING,
    compute_field_rows,
    fetch_columns,
    presence_predicate,
    taxonomy_title,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


SCITY_NORM_SQL = """
    CASE
        WHEN NULLIF(TRIM(scity), '') IS NOT NULL THEN UPPER(
            TRIM(REGEXP_REPLACE(REPLACE(TRIM(scity), '-', ' '), '\\s+', ' ', 'g'))
        )
        ELSE '(NULL)'
    END
"""


@dataclass
class SpatialSummary:
    grid_cells: int
    rows_geocoded: int
    rows_total: int
    verdict: str
    detail: str
    geojson: dict[str, Any]
    cell_missing_rates: list[float] = field(default_factory=list)


@dataclass
class CitySummary:
    verdict: str
    detail: str
    rows_considered: int


@dataclass
class SegmentSummary:
    verdict: str
    detail: str


@dataclass
class ZeroSemantics:
    note: str


def esc(s: object) -> str:
    return html_module.escape(str(s), quote=False)


def pct(part: int, whole: int) -> float:
    return round((part / whole) * 100.0, 4) if whole else 0.0


def spatial_metrics(cell_missing_frac: list[float], global_missing_frac: float) -> tuple[str, str]:
    if len(cell_missing_frac) < 5:
        return (
            "Low confidence",
            "Too few grid cells met the minimum sample — spatial pattern inconclusive.",
        )
    spread = max(cell_missing_frac) - min(cell_missing_frac)
    mean_mr = statistics.mean(cell_missing_frac)
    std_mr = statistics.pstdev(cell_missing_frac)
    cv = (std_mr / mean_mr) if mean_mr >= 0.002 else min(std_mr * 400, 2.0)
    g = global_missing_frac
    detail = (
        f"Across {len(cell_missing_frac)} cells: spread ≈ {spread * 100:.1f} pp; "
        f"mean cell missing ≈ {mean_mr * 100:.2f}% (global {g * 100:.2f}%). "
        f"Relative dispersion (CV) ≈ {cv:.2f}."
    )
    if g < 0.01 and spread < 0.03:
        return (
            "Relatively uniform",
            detail + " Low baseline missingness — geographic variation is minor in absolute terms.",
        )
    if spread >= 0.35 or cv >= 0.55:
        return ("Likely clustered / uneven", detail + " Missingness varies strongly by location.")
    if spread >= 0.18 or cv >= 0.28:
        return ("Moderate geographic variation", detail + " Review darker cells on the map.")
    return ("Relatively uniform", detail + " No extreme geographic concentration detected.")


def city_association(
    city_rows: list[tuple[str, int, int]],
    global_missing_frac: float,
) -> tuple[str, str]:
    if len(city_rows) < 3:
        return ("Insufficient city coverage", "Need more cities above minimum row threshold.")
    rates: list[tuple[str, float]] = []
    for cty, n, pres in city_rows:
        if n <= 0:
            continue
        rates.append((cty, 1.0 - (pres / n)))
    if not rates:
        return ("N/A", "")
    rates.sort(key=lambda x: -x[1])
    worst_city, worst_r = rates[0]
    best_city, best_r = rates[-1]
    spread = worst_r - best_r
    detail = (
        f"Worst: {worst_city} ({worst_r * 100:.2f}% missing). "
        f"Best among sampled: {best_city} ({best_r * 100:.2f}% missing). "
        f"Global reference: {global_missing_frac * 100:.2f}% missing."
    )
    if spread >= 0.25:
        return ("Associated with specific cities", detail)
    if spread >= 0.12:
        return ("Some municipal variation", detail)
    return ("Broadly similar across cities", detail)


def segment_notes(seg_rates: dict[str, float]) -> tuple[str, str]:
    """seg_rates: segment_label -> missing fraction."""
    if len(seg_rates) < 2:
        return ("Limited segmentation", "Not enough segments with rows to compare.")
    vals = list(seg_rates.items())
    vals.sort(key=lambda x: -x[1])
    hi_n, hi_r = vals[0]
    lo_n, lo_r = vals[-1]
    gap = hi_r - lo_r
    detail = "; ".join(f"{k}: {v * 100:.2f}% missing" for k, v in sorted(seg_rates.items()))
    if gap >= 0.20:
        return ("Associated with parcel proxy segment", f"Largest gap {gap * 100:.1f} pp ({hi_n} vs {lo_n}). " + detail)
    if gap >= 0.08:
        return ("Mild segment differences", detail)
    return ("Similar across segments", detail)


def fetch_geocoded_count(cur: psycopg.Cursor, schema: str, table: str) -> int:
    q = sql.SQL(
        "SELECT COUNT(*)::bigint FROM {}.{} WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ).format(sql.Identifier(schema), sql.Identifier(table))
    cur.execute(q)
    return int(cur.fetchone()[0])


def analyze_spatial_grid(
    cur: psycopg.Cursor,
    schema: str,
    table: str,
    column_name: str,
    data_type: str,
    udt_name: str,
    grid_mul: int,
    min_cell_rows: int,
    total_rows: int,
) -> SpatialSummary:
    pred = presence_predicate(column_name, data_type, udt_name)
    geo_rows = fetch_geocoded_count(cur, schema, table)
    q = sql.SQL(
        """
        WITH cells AS (
            SELECT
                FLOOR(lat * {gm})::int AS gx,
                FLOOR(lon * {gm})::int AS gy,
                CASE WHEN ({pred}) THEN 1 ELSE 0 END AS ok
            FROM {sch}.{tbl}
            WHERE lat IS NOT NULL AND lon IS NOT NULL
        )
        SELECT gx, gy, COUNT(*)::bigint AS n, SUM(ok)::bigint AS present_n
        FROM cells
        GROUP BY gx, gy
        HAVING COUNT(*) >= {mn}
        """
    ).format(
        gm=sql.Literal(grid_mul),
        pred=pred,
        sch=sql.Identifier(schema),
        tbl=sql.Identifier(table),
        mn=sql.Literal(min_cell_rows),
    )
    cur.execute(q)
    raw = cur.fetchall()
    if not raw:
        return SpatialSummary(
            grid_cells=0,
            rows_geocoded=geo_rows,
            rows_total=total_rows,
            verdict="No grid cells",
            detail="No locations passed minimum per-cell counts.",
            geojson={"type": "FeatureCollection", "features": []},
        )

    total_n = sum(int(r[2]) for r in raw)
    total_pres = sum(int(r[3]) for r in raw)
    global_miss = 1.0 - (total_pres / total_n) if total_n else 0.0
    rates: list[float] = []
    features: list[dict[str, Any]] = []
    for gx, gy, n, pn in raw:
        n = int(n)
        pn = int(pn)
        miss_frac = 1.0 - (pn / n) if n else 0.0
        rates.append(miss_frac)
        lat_lo = gx / float(grid_mul)
        lat_hi = (gx + 1) / float(grid_mul)
        lon_lo = gy / float(grid_mul)
        lon_hi = (gy + 1) / float(grid_mul)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [lon_lo, lat_lo],
                            [lon_hi, lat_lo],
                            [lon_hi, lat_hi],
                            [lon_lo, lat_hi],
                            [lon_lo, lat_lo],
                        ]
                    ],
                },
                "properties": {
                    "n": n,
                    "missing_pct": round(miss_frac * 100.0, 3),
                    "gx": gx,
                    "gy": gy,
                },
            }
        )

    verdict, detail = spatial_metrics(rates, global_miss)
    return SpatialSummary(
        grid_cells=len(raw),
        rows_geocoded=geo_rows,
        rows_total=total_rows,
        verdict=verdict,
        detail=detail,
        geojson={"type": "FeatureCollection", "features": features},
        cell_missing_rates=rates,
    )


def analyze_city_breakdown(
    cur: psycopg.Cursor,
    schema: str,
    table: str,
    column_name: str,
    data_type: str,
    udt_name: str,
    min_city_rows: int,
    max_cities: int,
    global_missing_frac: float,
) -> tuple[CitySummary, list[dict[str, Any]]]:
    pred = presence_predicate(column_name, data_type, udt_name)
    q = sql.SQL(
        """
        SELECT
            sub.scity_norm AS city_key,
            sub.n AS n,
            sub.present_n AS present_n
        FROM (
            SELECT
                {scity_norm} AS scity_norm,
                COUNT(*)::bigint AS n,
                SUM(CASE WHEN ({pred}) THEN 1 ELSE 0 END)::bigint AS present_n
            FROM {sch}.{tbl}
            GROUP BY 1
        ) sub
        WHERE sub.n >= {mn}
        ORDER BY sub.n DESC
        LIMIT {lim}
        """
    ).format(
        scity_norm=sql.SQL(SCITY_NORM_SQL),
        pred=pred,
        sch=sql.Identifier(schema),
        tbl=sql.Identifier(table),
        mn=sql.Literal(min_city_rows),
        lim=sql.Literal(max_cities),
    )
    cur.execute(q)
    rows = [(str(r[0]), int(r[1]), int(r[2])) for r in cur.fetchall()]
    considered = sum(r[1] for r in rows)
    v, d = city_association(rows, global_missing_frac)
    long_rows: list[dict[str, Any]] = []
    for cty, n, pn in rows:
        miss = n - pn
        long_rows.append(
            {
                "field": column_name,
                "city_key": cty,
                "row_count": n,
                "present_count": pn,
                "missing_count": miss,
                "missing_pct": pct(miss, n),
            }
        )
    return CitySummary(v, d + f" (top cities by volume; ≥{min_city_rows} rows each.)", considered), long_rows


def analyze_segments(
    cur: psycopg.Cursor,
    schema: str,
    table: str,
    column_name: str,
    data_type: str,
    udt_name: str,
) -> SegmentSummary:
    pred = presence_predicate(column_name, data_type, udt_name)
    seg_expr = sql.SQL(
        "CASE "
        "WHEN footprints IS NOT NULL AND cardinality(footprints) > 0 THEN {fp} "
        "ELSE {nofp} END"
    ).format(fp=sql.Literal("fp_nonempty"), nofp=sql.Literal("fp_empty"))
    q_fp = sql.SQL(
        """
        SELECT {seg} AS seg,
               COUNT(*)::bigint AS n,
               SUM(CASE WHEN ({pred}) THEN 1 ELSE 0 END)::bigint AS present_n
        FROM {sch}.{tbl}
        GROUP BY 1
        """
    ).format(
        seg=seg_expr,
        pred=pred,
        sch=sql.Identifier(schema),
        tbl=sql.Identifier(table),
    )
    cur.execute(q_fp)
    fp_rows = cur.fetchall()

    seg_sq = sql.SQL(
        "CASE WHEN sqft IS NOT NULL AND sqft <> 0 THEN {a} ELSE {b} END"
    ).format(a=sql.Literal("sqft_nonzero"), b=sql.Literal("sqft_zero_or_null"))
    q_sq = sql.SQL(
        """
        SELECT {seg} AS seg,
               COUNT(*)::bigint AS n,
               SUM(CASE WHEN ({pred}) THEN 1 ELSE 0 END)::bigint AS present_n
        FROM {sch}.{tbl}
        GROUP BY 1
        """
    ).format(
        seg=seg_sq,
        pred=pred,
        sch=sql.Identifier(schema),
        tbl=sql.Identifier(table),
    )
    cur.execute(q_sq)
    sq_rows = cur.fetchall()

    rates: dict[str, float] = {}
    for label, rows in (("footprint_proxy", fp_rows), ("sqft_proxy", sq_rows)):
        for seg, n, pn in rows:
            n = int(n)
            if n <= 0:
                continue
            rates[f"{label}:{seg}"] = 1.0 - (int(pn) / n)

    v, d = segment_notes(rates)
    return SegmentSummary(v, d)


def zero_semantics_for_column(
    cur: psycopg.Cursor,
    schema: str,
    table: str,
    column_name: str,
    data_type: str,
) -> ZeroSemantics:
    dt = (data_type or "").lower()
    if dt not in ("smallint", "integer", "bigint", "numeric", "double precision", "real"):
        return ZeroSemantics("N/A — non-numeric type.")
    col = sql.Identifier(column_name)
    sch = sql.Identifier(schema)
    tbl = sql.Identifier(table)
    cur.execute(
        sql.SQL(
            "SELECT COUNT(*) FILTER (WHERE {c} IS NOT NULL)::bigint, "
            "COUNT(*) FILTER (WHERE {c} IS NOT NULL AND {c}::numeric = 0)::bigint "
            "FROM {s}.{t}"
        ).format(c=col, s=sch, t=tbl)
    )
    row = cur.fetchone()
    nn, z = int(row[0]), int(row[1])
    if nn <= 0:
        return ZeroSemantics("No non-null numeric values — zeros irrelevant.")
    z_pct = z / nn
    low = column_name.lower()
    ambiguous = low in NUMERIC_ZERO_EMPTY or "error" in low or low in ("fhszsra", "fhszlra")
    if ambiguous and z_pct >= 0.15:
        return ZeroSemantics(
            f"{z:,} of {nn:,} non-null rows are exact zeros ({z_pct * 100:.1f}%). "
            "Treat as potentially ambiguous: zero may mean unknown until Step 3 confirms semantics."
        )
    if z_pct >= 0.50:
        return ZeroSemantics(
            f"Majority zeros ({z_pct * 100:.1f}% of non-null). Validate whether zero is a real measurement."
        )
    if z_pct <= 0.01:
        return ZeroSemantics("Zeros are rare among non-nulls — likely literal zeros.")
    return ZeroSemantics(
        f"{z_pct * 100:.1f}% of non-null values are zero — generally plausible literals; spot-check edge cases."
    )


def write_example_rows(
    cur: psycopg.Cursor,
    schema: str,
    table: str,
    column_name: str,
    data_type: str,
    udt_name: str,
    out_csv: Path,
    limit: int,
) -> int:
    pred = presence_predicate(column_name, data_type, udt_name)
    q = sql.SQL(
        """
        SELECT parcelnumb, scity, city, lat, lon, address
        FROM {sch}.{tbl}
        WHERE NOT ({pred})
        ORDER BY parcelnumb NULLS LAST
        LIMIT {lim}
        """
    ).format(
        pred=pred,
        sch=sql.Identifier(schema),
        tbl=sql.Identifier(table),
        lim=sql.Literal(limit),
    )
    cur.execute(q)
    cols = [d[0] for d in cur.description]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        n = 0
        for row in cur.fetchall():
            w.writerow(row)
            n += 1
    return n


def pick_featured_fields(rows: list[FieldRow], max_maps: int) -> list[FieldRow]:
    """Prefer fields that drive product risk and have partial missingness (maps are informative)."""
    def score(r: FieldRow) -> tuple[int, float, str]:
        risk_rank = {"High": 0, "Moderate": 1, "Low": 2}.get(r.product_behavior_risk, 1)
        # Skip 100% missing or 0% missing for map emphasis
        edge = 0 if 0 < r.missing_pct < 100 else 1
        return (risk_rank, edge, -r.missing_pct)

    ranked = sorted(rows, key=score)
    featured: list[FieldRow] = []
    for r in ranked:
        if r.column_name.lower() in ("lat", "lon"):
            continue
        if 0 < r.missing_pct < 100 or r.product_behavior_risk == "High":
            featured.append(r)
        if len(featured) >= max_maps:
            break
    # Fallback: ensure we always show something
    if not featured:
        featured = [r for r in rows if r.column_name.lower() not in ("lat", "lon")][:max_maps]
    return featured[:max_maps]


def _bucket_badge_class(bucket: str) -> str:
    """Same class names as Step 1 HTML (`field_missingness_classification.build_html_report`)."""
    return {
        CORE_PARCEL: "badge-core",
        FOOTPRINT: "badge-footprint",
        EXTERNAL_JOIN: "badge-external",
        SOURCE_MISSING: "badge-source",
        API_FILLABLE: "badge-api",
    }.get(bucket, "badge-api")


def _verdict_risk_span(label: str) -> str:
    """Visual language aligned with Step 1 `.risk` / `.risk-*` badges."""
    t = label.lower()
    if any(
        x in t
        for x in (
            "likely clustered",
            "uneven",
            "associated with specific cities",
            "associated with parcel",
        )
    ):
        cls = "risk-high"
    elif any(
        x in t
        for x in (
            "moderate",
            "some municipal",
            "mild segment",
            "insufficient",
            "no grid cells",
            "limited segmentation",
            "no locations passed",
            "some geographic variation",
            "municipal variation",
        )
    ):
        cls = "risk-mod"
    else:
        cls = "risk-low"
    return f'<span class="risk {cls}">{esc(label)}</span>'


def _missing_bar_cell(pct: float) -> str:
    """Missing-% bar + label (severity classes named `pct-sev-*` to avoid clashing with `.risk-*`)."""
    w = min(100.0, max(0.0, pct))
    hue = "#16a34a" if pct < 5 else "#d97706" if pct < 25 else "#dc2626"
    sev = "pct-sev-high" if pct >= 25 else "pct-sev-mid" if pct >= 5 else "pct-sev-low"
    return (
        f'<div class="miss-cell"><div class="bar-track" title="{esc(f"{pct:.4f}% missing")}">'
        f'<span class="bar-fill" style="width:{w:.1f}%;background:{hue}"></span></div>'
        f'<span class="miss-pct {sev}">{esc(f"{pct:.2f}%")}</span></div>'
    )


def prefer_mapped_fields(
    featured: list[FieldRow],
    enriched_by_col: dict[str, dict[str, Any]],
    min_cells: int,
) -> list[FieldRow]:
    """Keep maps only where the grid had enough cells (otherwise Leaflet has nothing useful)."""
    prim = [
        fr
        for fr in featured
        if enriched_by_col.get(fr.column_name, {}).get("grid_cells_used", 0) >= min_cells
    ]
    if prim:
        return prim
    fallback = [
        fr
        for fr in featured
        if enriched_by_col.get(fr.column_name, {}).get("grid_cells_used", 0) > 0
    ]
    return fallback if fallback else featured


def build_html(
    enriched: list[dict[str, Any]],
    featured: list[FieldRow],
    generated_iso: str,
    out_root: Path,
) -> str:
    map_sections: list[str] = []
    for fr in featured:
        slug = fr.column_name.replace("/", "_")
        b = fr.taxonomy_bucket
        gj_path = out_root / "spatial_cells" / f"{slug}.geojson"
        gj_script_id = f"gj-{slug}"
        raw_geojson = gj_path.read_text(encoding="utf-8").replace("</script>", "<\\/script>")
        map_sections.append(
            f"""
    <section class="bucket-card bc-{esc(b)}" id="map-{esc(slug)}">
      <div class="bucket-head">
        <span class="badge {_bucket_badge_class(b)}">Spatial map</span>
        <h2>Spatial missingness · <code>{esc(fr.column_name)}</code></h2>
        <p class="muted">{esc(taxonomy_title(b))} — polygons are lat/lon grid cells colored by % missing.</p>
        <p class="file-ref">GeoJSON: <code>outputs/missingness_step2/spatial_cells/{esc(slug)}.geojson</code></p>
      </div>
      <div class="table-wrap map-wrap">
        <div class="map-legend" role="figure" aria-label="Map color legend">
          <span class="map-legend-title">Missing rate</span>
          <span class="lg lg-g"><i></i> &lt;5%</span>
          <span class="lg lg-b"><i></i> 5–12%</span>
          <span class="lg lg-y"><i></i> 12–25%</span>
          <span class="lg lg-o"><i></i> 25–40%</span>
          <span class="lg lg-r"><i></i> ≥40%</span>
        </div>
        <p class="muted map-note">Only rows with both <code>lat</code> and <code>lon</code> populate this layer.</p>
        <div id="leaflet-{esc(slug)}" class="leaflet-map"></div>
        <script type="application/json" id="{esc(gj_script_id)}">{raw_geojson}</script>
      </div>
    </section>
"""
        )

    map_js_blocks: list[str] = []
    for fr in featured:
        slug = fr.column_name.replace("/", "_")
        gj_script_id = f"gj-{slug}"
        map_js_blocks.append(
            f"""
(function() {{
  var el = document.getElementById('leaflet-{slug}');
  var dataEl = document.getElementById('{gj_script_id}');
  var data = dataEl.textContent;
  var fc = JSON.parse(data);
  if (!fc.features || fc.features.length === 0) {{
    el.innerHTML = '<div class="map-empty">No grid cells met the minimum row threshold for this field.</div>';
    return;
  }}
  var map = L.map(el).setView([37.35, -121.95], 10);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }}).addTo(map);
  function colorFor(p) {{
    if (p >= 40) return '#7f1d1d';
    if (p >= 25) return '#ea580c';
    if (p >= 12) return '#ca8a04';
    if (p >= 5) return '#2563eb';
    return '#15803d';
  }}
  var gj = L.geoJSON(fc, {{
    style: function(f) {{
      var mp = f.properties.missing_pct || 0;
      return {{
        color: '#334155',
        weight: 0.4,
        fillColor: colorFor(mp),
        fillOpacity: 0.55
      }};
    }},
    onEachFeature: function(f, layer) {{
      layer.bindPopup('<strong>Missing</strong> ' + f.properties.missing_pct +
        '%<br/><strong>n=</strong>' + f.properties.n);
    }}
  }}).addTo(map);
  map.fitBounds(gj.getBounds(), {{ padding: [24, 24], maxZoom: 12 }});
}})();
"""
        )

    enriched_rows_html = "".join(
        "<tr>"
        f"<td><code>{esc(e['column_name'])}</code></td>"
        f"<td><span class='badge {_bucket_badge_class(e['taxonomy_bucket'])}'>{esc(e['taxonomy'])}</span></td>"
        f"<td class='num'>{esc(e['non_null_pct'])}%</td>"
        f"<td class='num'>{_missing_bar_cell(float(e['missing_pct']))}</td>"
        f"<td>{_verdict_risk_span(str(e['spatial_verdict']))}</td>"
        f"<td>{_verdict_risk_span(str(e['city_verdict']))}</td>"
        f"<td>{_verdict_risk_span(str(e['segment_verdict']))}</td>"
        f"<td class='small'>{esc(e['zero_semantics'])}</td>"
        f"<td class='small'>{esc(e['product_impact'])}</td>"
        "</tr>"
        for e in enriched
    )

    feat_cols = {f.column_name for f in featured}
    featured_detail = ""
    for e in enriched:
        if e["column_name"] not in feat_cols:
            continue
        b = e["taxonomy_bucket"]
        featured_detail += f"""
    <section class="bucket-card bc-{esc(b)}" id="detail-{esc(e['column_name'])}">
      <div class="bucket-head">
        <span class="badge {_bucket_badge_class(b)}">{esc(e['taxonomy'])}</span>
        <h2><code>{esc(e['column_name'])}</code> — field QA detail</h2>
        <p class="muted">Same presence semantics as Step 1; dimensions below summarize completeness signals.</p>
      </div>
      <div class="table-wrap">
        <table class="stripe">
          <thead>
            <tr><th>Dimension</th><th>Verdict</th><th>Notes</th></tr>
          </thead>
          <tbody>
            <tr><td>Spatial pattern</td><td>{_verdict_risk_span(str(e['spatial_verdict']))}</td><td class="small">{esc(e['spatial_detail'])}</td></tr>
            <tr><td>City association</td><td>{_verdict_risk_span(str(e['city_verdict']))}</td><td class="small">{esc(e['city_detail'])}</td></tr>
            <tr><td>Parcel proxies</td><td>{_verdict_risk_span(str(e['segment_verdict']))}</td><td class="small">{esc(e['segment_detail'])} — Unidata has no county <code>usecode</code>; footprint/sqft buckets proxy parcel enrichment.</td></tr>
            <tr><td>Zero semantics</td><td><span class="type-tag">Review</span></td><td class="small">{esc(e['zero_semantics'])}</td></tr>
            <tr><td>Artifacts</td><td><span class="type-tag">CSV / GIS</span></td><td class="small"><code>{esc(e['examples_csv'])}</code> · <code>{esc(e['geojson_rel'])}</code></td></tr>
          </tbody>
        </table>
      </div>
    </section>
"""

    checklist = """
    <ol class="checklist">
      <li><span class="ck-i">1</span> Create a summary table for field completeness.</li>
      <li><span class="ck-i">2</span> Create spatial missingness maps for key fields (lat/lon grid).</li>
      <li><span class="ck-i">3</span> Check missingness by city / footprint–sqft proxies.</li>
      <li><span class="ck-i">4</span> Identify examples of problematic records (CSV per featured field).</li>
      <li><span class="ck-i">5</span> Publish documentation links (see repo docs).</li>
    </ol>
    <p class="muted ck-note">Artifacts: <code>field_completeness_summary.csv</code>, <code>completeness_by_city_long.csv</code>, GeoJSON under <code>spatial_cells/</code>.</p>
    """

    total_rows = enriched[0]["total_rows"] if enriched else 0
    n_cols = len(enriched)
    n_geo = enriched[0]["rows_geocoded"] if enriched else 0
    n_maps = len(featured)
    kpi = f"""
    <div class="kpi-grid">
      <div class="kpi kpi-rows"><div class="kpi-val">{esc(f'{total_rows:,}')}</div><div class="kpi-lbl">Table rows scanned</div></div>
      <div class="kpi kpi-fields"><div class="kpi-val">{esc(n_cols)}</div><div class="kpi-lbl">Columns analyzed</div></div>
      <div class="kpi kpi-core"><div class="kpi-val">{esc(f'{n_geo:,}')}</div><div class="kpi-lbl">Rows with lat/lon</div></div>
      <div class="kpi kpi-ext"><div class="kpi-val">{esc(n_maps)}</div><div class="kpi-lbl">Featured map fields</div></div>
    </div>
    """

    jump_parts = [
        '<nav class="jump" aria-label="Section navigation">',
        '      <a href="#summary">Summary table</a>',
        '      <a href="#checklist">Checklist</a>',
        '      <a href="#featured">Featured QA</a>',
    ]
    for fr in featured:
        slug = fr.column_name.replace("/", "_")
        jump_parts.append(f'      <a href="#map-{esc(slug)}">Map: {esc(fr.column_name)}</a>')
    jump_parts.append("    </nav>")
    jump = "\n    ".join(jump_parts)

    leaflet_css = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    leaflet_js = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Step 2 — Field completeness report</title>
  <link rel="stylesheet" href="{leaflet_css}" crossorigin=""/>
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
      background: rgba(15, 23, 42, 0.35);
      padding: 3px 9px;
      border-radius: 6px;
      color: #ffffff;
      border: 1px solid rgba(255,255,255,.22);
    }}
    header.hero time {{ font-size: 13px; opacity: 0.92; color: rgba(255,255,255,.95); }}
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
      font-weight: 650;
      color: #1e3a8a;
      text-decoration: none;
      padding: 7px 14px;
      border-radius: 999px;
      background: #ffffff;
      border: 1px solid #cbd5e1;
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
    .muted {{ color: #475569; font-size: 14px; }}
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
    .kpi-lbl {{ font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: #475569; margin-top: 4px; }}

    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .stripe td {{ color: #1e293b; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: middle; }}
    thead th {{
      background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
      font-weight: 800;
      color: #1e293b;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .06em;
      border-bottom: 2px solid #cbd5e1;
    }}
    tbody tr:hover {{ background: #f8fafc; }}
    .stripe tbody tr:nth-child(even) {{ background: #fafbfd; }}
    .stripe tbody tr:nth-child(even):hover {{ background: #f1f5f9; }}

    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    td.small {{ font-size: 12px; color: #334155; max-width: 280px; line-height: 1.5; }}
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
      font-weight: 700;
      background: #f1f5f9;
      color: #334155;
      padding: 4px 9px;
      border-radius: 6px;
      white-space: nowrap;
      border: 1px solid #e2e8f0;
    }}

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
    .badge-core {{ background: #eff6ff; color: #1e3a8a; border: 1px solid #93c5fd; }}
    .badge-footprint {{ background: #ecfdf5; color: #115e59; border: 1px solid #5eead4; }}
    .badge-external {{ background: #f5f3ff; color: #4c1d95; border: 1px solid #c4b5fd; }}
    .badge-source {{ background: #fff1f2; color: #9f1239; border: 1px solid #fda4af; }}
    .badge-api {{ background: #fff7ed; color: #9a3412; border: 1px solid #fdba74; }}

    .risk {{
      display: inline-block;
      padding: 5px 11px;
      border-radius: 8px;
      font-weight: 800;
      font-size: 11px;
      letter-spacing: .02em;
      line-height: 1.35;
      border: 1px solid transparent;
    }}
    .risk-high {{ background: #fef2f2; color: #7f1d1d; border-color: #fca5a5; }}
    .risk-mod {{ background: #fffbeb; color: #78350f; border-color: #fcd34d; }}
    .risk-low {{ background: #ecfdf5; color: #065f46; border-color: #6ee7b7; }}

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
    .miss-pct {{ font-weight: 800; font-size: 12px; min-width: 54px; text-align: right; }}
    .pct-sev-low {{ color: #047857; }}
    .pct-sev-mid {{ color: #b45309; }}
    .pct-sev-high {{ color: #b91c1c; }}

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
      background: #ffffff;
      color: #0f172a;
    }}
    .bucket-head h2 {{ margin: 10px 0 6px; font-size: 1.12rem; color: #0f172a; font-weight: 700; }}
    .bucket-head .muted {{ color: #475569; }}
    .bucket-head .badge {{ vertical-align: middle; }}
    .bc-core_parcel .bucket-head {{ border-left: 5px solid var(--core); }}
    .bc-footprint_related .bucket-head {{ border-left: 5px solid var(--foot); }}
    .bc-external_join .bucket-head {{ border-left: 5px solid var(--ext); }}
    .bc-source_missing .bucket-head {{ border-left: 5px solid var(--src); }}
    .bc-api_fillable .bucket-head {{ border-left: 5px solid var(--api); }}

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
      border: 1px solid #cbd5e1;
      color: #1e293b;
      line-height: 1.5;
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
    .file-ref {{ font-size: 13px; margin: 14px 0 0; }}
    .file-ref code {{ background: #f1f5f9; color: #334155; }}
    .section-h2 {{ margin: 28px 4px 12px; font-size: 1.2rem; color: #0f172a; }}

    .map-wrap {{ padding: 0 22px 18px; }}
    .map-note {{ margin: 6px 0 10px; font-size: 14px; }}
    .map-legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      align-items: center;
      padding: 12px 14px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 10px;
      margin-bottom: 8px;
      font-size: 12px;
    }}
    .map-legend-title {{ font-weight: 800; color: #0f172a; margin-right: 8px; }}
    .lg {{ display: inline-flex; align-items: center; gap: 6px; color: #1e293b; font-weight: 600; }}
    .lg i {{
      display: inline-block;
      width: 18px;
      height: 12px;
      border-radius: 3px;
      border: 1px solid rgba(0,0,0,.12);
    }}
    .lg-g i {{ background: #15803d; }}
    .lg-b i {{ background: #2563eb; }}
    .lg-y i {{ background: #ca8a04; }}
    .lg-o i {{ background: #ea580c; }}
    .lg-r i {{ background: #7f1d1d; }}

    .leaflet-map {{
      height: 420px;
      border-radius: 12px;
      margin-top: 10px;
      border: 1px solid var(--line);
      background: #e2e8f0;
    }}
    .leaflet-map.leaflet-container {{
      font-family: inherit;
      color: #1e293b;
    }}
    .map-empty {{
      padding: 28px;
      text-align: center;
      color: #475569;
      background: #f8fafc;
      border-radius: 12px;
      border: 1px dashed #94a3b8;
      font-weight: 500;
    }}
  </style>
</head>
<body>
  <header class="hero">
    <h1>Next-stage work plan · Step 2: Field completeness report</h1>
    <p>Completeness analysis for <code>public.unidata</code>: summary metrics, spatial maps (lat/lon grid), city slices, and enrichment proxies — using the same presence rules as Step 1.</p>
    <p><time datetime="{esc(generated_iso)}">Generated {esc(generated_iso)}</time></p>
  </header>
  {jump}
  <main>
    {kpi}
    <section class="panel" id="summary">
      <h2>Completeness summary</h2>
      <p class="muted">Non-null % reflects Step 1 “present” semantics (e.g. <code>sqft</code> must be non-null and ≠ 0).</p>
      <div class="table-wrap">
        <table class="stripe">
          <thead>
            <tr>
              <th>Field</th><th>Taxonomy</th><th>Non-null %</th><th>Missing %</th>
              <th>Spatial</th><th>City</th><th>Proxies</th>
              <th>Zeros</th><th>Product impact</th>
            </tr>
          </thead>
          <tbody>{enriched_rows_html}</tbody>
        </table>
      </div>
      <p class="muted file-ref">Export: <code>outputs/missingness_step2/field_completeness_summary.csv</code></p>
    </section>

    <section class="panel" id="checklist">
      <h2>To do (checklist)</h2>
      {checklist}
    </section>

    <section class="panel" id="featured">
      <h2>Featured fields — QA detail</h2>
      <p class="muted">Deeper narrative per highlighted column (below maps). Unidata has no county <code>usecode</code>; footprint / sqft segments proxy parcel enrichment.</p>
      {featured_detail}
    </section>

    <h2 class="section-h2">Spatial missingness maps</h2>
    {"".join(map_sections)}

  </main>
  <script src="{leaflet_js}" crossorigin=""></script>
  <script>
    {"".join(map_js_blocks)}
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Step 2 field completeness report")
    p.add_argument("--db-schema", default="public")
    p.add_argument("--db-table", default="unidata")
    p.add_argument(
        "--out-root",
        type=Path,
        default=_repo_root() / "outputs" / "missingness_step2",
        help="Output directory",
    )
    p.add_argument("--grid-multiplier", type=int, default=55, help="FLOOR(coord * k) grid resolution")
    p.add_argument("--min-cell-rows", type=int, default=80, help="Minimum rows per grid cell")
    p.add_argument("--min-city-rows", type=int, default=400, help="Minimum rows per city slice")
    p.add_argument("--max-cities", type=int, default=60)
    p.add_argument("--max-map-fields", type=int, default=6)
    p.add_argument("--example-limit", type=int, default=25)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    schema = args.db_schema
    table = args.db_table
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    spatial_dir = out_root / "spatial_cells"
    spatial_dir.mkdir(parents=True, exist_ok=True)
    examples_dir = out_root / "example_records"
    examples_dir.mkdir(parents=True, exist_ok=True)

    conn_kw = {**DEFAULT_DB_CONFIG, "connect_timeout": 25}
    field_rows = compute_field_rows(schema, table, DEFAULT_DB_CONFIG)
    featured_list = pick_featured_fields(field_rows, args.max_map_fields)

    enriched: list[dict[str, Any]] = []
    city_long_all: list[dict[str, Any]] = []

    with psycopg.connect(**conn_kw) as conn:
        conn.autocommit = True
        cur = conn.cursor()
        cols = fetch_columns(cur, schema, table)
        col_lookup = {name: (dt, ut) for name, dt, ut in cols}

        for fr in field_rows:
            cname = fr.column_name
            dt, ut = col_lookup.get(cname, (fr.data_type, fr.udt_name))
            global_miss_frac = fr.missing_pct / 100.0

            sp = analyze_spatial_grid(
                cur,
                schema,
                table,
                cname,
                dt,
                ut,
                args.grid_multiplier,
                args.min_cell_rows,
                fr.total_rows,
            )
            slug = cname.replace("/", "_")
            gj_rel = f"outputs/missingness_step2/spatial_cells/{slug}.geojson"
            (spatial_dir / f"{slug}.geojson").write_text(
                json.dumps(sp.geojson), encoding="utf-8"
            )

            cs, long_city = analyze_city_breakdown(
                cur,
                schema,
                table,
                cname,
                dt,
                ut,
                args.min_city_rows,
                args.max_cities,
                global_miss_frac,
            )
            city_long_all.extend(long_city)

            seg = analyze_segments(cur, schema, table, cname, dt, ut)
            zs = zero_semantics_for_column(cur, schema, table, cname, dt)

            ex_path = examples_dir / f"{slug}_missing_sample.csv"
            n_ex = write_example_rows(
                cur, schema, table, cname, dt, ut, ex_path, args.example_limit
            )
            ex_rel = f"outputs/missingness_step2/example_records/{slug}_missing_sample.csv"

            enriched.append(
                {
                    "column_name": cname,
                    "taxonomy_bucket": fr.taxonomy_bucket,
                    "taxonomy": taxonomy_title(fr.taxonomy_bucket),
                    "total_rows": fr.total_rows,
                    "non_null_pct": round(100.0 - fr.missing_pct, 4),
                    "missing_pct": fr.missing_pct,
                    "spatial_verdict": sp.verdict,
                    "spatial_detail": sp.detail,
                    "city_verdict": cs.verdict,
                    "city_detail": cs.detail,
                    "segment_verdict": seg.verdict,
                    "segment_detail": seg.detail,
                    "zero_semantics": zs.note,
                    "product_impact": f"{fr.product_behavior_risk} — {fr.product_impact}",
                    "examples_csv": ex_rel,
                    "examples_written": n_ex,
                    "geojson_rel": gj_rel,
                    "grid_cells_used": sp.grid_cells,
                    "rows_geocoded": sp.rows_geocoded,
                }
            )

    summary_csv = out_root / "field_completeness_summary.csv"
    keys = [
        "column_name",
        "taxonomy",
        "non_null_pct",
        "missing_pct",
        "spatial_verdict",
        "spatial_detail",
        "city_verdict",
        "city_detail",
        "segment_verdict",
        "segment_detail",
        "zero_semantics",
        "product_impact",
        "examples_csv",
        "examples_written",
        "geojson_rel",
        "grid_cells_used",
        "rows_geocoded",
    ]
    with summary_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for row in enriched:
            w.writerow({k: row[k] for k in keys})

    city_csv = out_root / "completeness_by_city_long.csv"
    if city_long_all:
        with city_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(city_long_all[0].keys()))
            w.writeheader()
            for row in city_long_all:
                w.writerow(row)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    enriched_by_col = {e["column_name"]: e for e in enriched}
    mapped_featured = prefer_mapped_fields(
        featured_list, enriched_by_col, min_cells=5
    )
    html_doc = build_html(enriched, mapped_featured, generated, out_root)
    (out_root / "report.html").write_text(html_doc, encoding="utf-8")

    print(f"Wrote {out_root / 'report.html'}")
    print(f"Wrote {summary_csv}")
    print(f"Wrote {city_csv} ({len(city_long_all)} rows)")
    print(f"Featured maps: {[f.column_name for f in mapped_featured]}")


if __name__ == "__main__":
    main()
