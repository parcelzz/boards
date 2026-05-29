"""
Fill missing ``footprints`` on ``public.unidata`` from building polygon GPKG(s).

Default source: ``data/California.gpkg`` (layer ``California``), clipped to a Santa Clara
County bounding box. Only rows with NULL or empty ``footprints`` are updated; existing
footprints are never overwritten.

Matching uses parcel polygon (``parcel`` WKT) intersecting building polygons with
positive-area overlap (intersects, not boundary-only touch).

Run from repo root:
  py -3 tools/audits/enrich_unidata_footprints.py              # dry run (counts only)
  py -3 tools/audits/enrich_unidata_footprints.py --apply      # commit updates

Requires: psycopg, pyogrio, shapely.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import psycopg
import pyogrio
from psycopg import sql
from shapely import wkt
from shapely.strtree import STRtree

from field_missingness_classification import DEFAULT_DB_CONFIG


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


DEFAULT_SCC_BBOX = (-122.17, 37.11, -121.57, 37.48)


def _valid_geom(geom):
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom if geom is not None and not geom.is_empty else None


def _positive_overlap(parcel_geom, building_geom) -> bool:
    if not parcel_geom.intersects(building_geom):
        return False
    if parcel_geom.touches(building_geom):
        return False
    inter = parcel_geom.intersection(building_geom)
    return not inter.is_empty and inter.area > 0


def load_building_geoms(
    source_path: Path,
    layer: str | None,
    bbox: tuple[float, float, float, float] | None,
):
    print(f"Reading buildings from {source_path.name} ...")
    kwargs: dict = {}
    if layer:
        kwargs["layer"] = layer
    if bbox is not None:
        kwargs["bbox"] = bbox
    gdf = pyogrio.read_dataframe(source_path, **kwargs)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    geoms = [_valid_geom(g) for g in gdf.geometry]
    keep = [i for i, g in enumerate(geoms) if g is not None]
    geoms = [geoms[i] for i in keep]
    print(f"  {len(geoms):,} building polygons loaded")
    tree = STRtree(geoms)
    return geoms, tree


def load_missing_parcels(conn: psycopg.Connection, schema: str, table: str) -> list[tuple[int, str]]:
    q = sql.SQL(
        """
        SELECT id, parcel::text
        FROM {schema}.{table}
        WHERE (footprints IS NULL OR cardinality(footprints) = 0)
          AND parcel IS NOT NULL AND TRIM(parcel::text) <> ''
        ORDER BY id
        """
    ).format(schema=sql.Identifier(schema), table=sql.Identifier(table))
    return [(r[0], r[1]) for r in conn.execute(q).fetchall()]


def iter_batches(rows: list[tuple[int, str]], batch_size: int):
    for i in range(0, len(rows), batch_size):
        yield rows[i : i + batch_size]


def match_footprints(
    parcel_rows: list[tuple[int, str]], building_geoms: list, tree: STRtree
) -> list[tuple[int, list[str]]]:
    out: list[tuple[int, list[str]]] = []
    for pid, parcel_wkt in parcel_rows:
        try:
            parcel_geom = _valid_geom(wkt.loads(parcel_wkt))
        except Exception:
            continue
        if parcel_geom is None:
            continue
        hits = tree.query(parcel_geom, predicate="intersects")
        wkts: list[str] = []
        for idx in hits:
            b = building_geoms[int(idx)]
            if _positive_overlap(parcel_geom, b):
                wkts.append(b.wkt)
        if wkts:
            out.append((pid, wkts))
    return out


def apply_batch(conn: psycopg.Connection, schema: str, table: str, updates: list[tuple[int, list[str]]]) -> int:
    if not updates:
        return 0
    q = sql.SQL(
        """
        UPDATE {schema}.{table} u
        SET footprints = %s::varchar[], updated_at = NOW()
        WHERE u.id = %s
        """
    ).format(schema=sql.Identifier(schema), table=sql.Identifier(table))
    with conn.cursor() as cur:
        cur.executemany(q, [(wkts, pid) for pid, wkts in updates])
    return len(updates)


def main() -> None:
    p = argparse.ArgumentParser(description="Fill missing unidata footprints from building GPKG/GeoJSON.")
    p.add_argument(
        "--footprint-source",
        type=Path,
        default=_repo_root() / "data" / "California.gpkg",
        help="Building polygon file (.gpkg or .geojson).",
    )
    p.add_argument("--layer", default=None, help="GPKG layer name (default: California for .gpkg).")
    p.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        default=None,
        metavar=("MINX", "MINY", "MAXX", "MAXY"),
        help="Clip buildings to bbox (default: SCC clip for California.gpkg only).",
    )
    p.add_argument("--db-schema", default="public")
    p.add_argument("--db-table", default="unidata")
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    source_path = Path(args.footprint_source)
    if not source_path.is_absolute():
        source_path = (_repo_root() / source_path).resolve()
    if not source_path.is_file():
        raise SystemExit(f"Building source not found: {source_path}")

    layer = args.layer
    bbox = tuple(args.bbox) if args.bbox else None
    if source_path.suffix.lower() == ".gpkg":
        layer = layer or "California"
        bbox = bbox if bbox is not None else DEFAULT_SCC_BBOX

    building_geoms, tree = load_building_geoms(source_path, layer, bbox)

    print("Loading missing parcels from Unidata ...")
    conn = psycopg.connect(**DEFAULT_DB_CONFIG)
    conn.autocommit = False
    missing_rows = load_missing_parcels(conn, args.db_schema, args.db_table)
    fillable_total = 0
    updated_total = 0
    try:
        for batch in iter_batches(missing_rows, args.batch_size):
            matched = match_footprints(batch, building_geoms, tree)
            fillable_total += len(matched)
            if args.apply and matched:
                apply_batch(conn, args.db_schema, args.db_table, matched)
                conn.commit()
                updated_total += len(matched)

        print(f"Unidata rows missing footprints: {len(missing_rows):,}")
        print(f"Rows with at least one building overlap: {fillable_total:,}")

        if not args.apply:
            conn.rollback()
            print("Dry run complete (no changes). Pass --apply to UPDATE footprints.")
            return

        still = conn.execute(
            sql.SQL(
                """
                SELECT COUNT(*)::bigint FROM {schema}.{table}
                WHERE footprints IS NULL OR cardinality(footprints) = 0
                """
            ).format(schema=sql.Identifier(args.db_schema), table=sql.Identifier(args.db_table))
        ).fetchone()[0]
        print(f"Applied: {updated_total:,} rows updated with footprints.")
        print(f"Footprints still missing: {still:,}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
