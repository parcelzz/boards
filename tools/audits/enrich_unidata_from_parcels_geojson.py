"""
Fill missing ``scity`` (and ``address`` when empty) on ``public.unidata`` from county parcel GeoJSON.

Expects Santa Clara County open-data parcel export with ``apn`` and situs address fields.

Run from repo root:
  py -3 tools/audits/enrich_unidata_from_parcels_geojson.py --apply
"""
from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

import psycopg
import pyogrio
from psycopg import sql

from enrich_unidata_from_gpkg import normalize_apn, normalize_scity
from field_missingness_classification import DEFAULT_DB_CONFIG


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _build_situs_address(row) -> str | None:
    parts: list[str] = []
    for col in (
        "situs_house_number",
        "situs_house_number_suffix",
        "situs_street_direction",
        "situs_street_name",
        "situs_street_type",
        "situs_unit_number",
    ):
        v = row.get(col)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ("none", "nan"):
            parts.append(s)
    addr = " ".join(parts).strip()
    return addr or None


def load_staging_rows(geojson_path: Path) -> list[tuple[str, str, str | None, str | None]]:
    """(apn, scity_norm, scity_raw, address) best row per apn (longest address wins)."""
    cols = [
        "apn",
        "situs_house_number",
        "situs_house_number_suffix",
        "situs_street_direction",
        "situs_street_name",
        "situs_street_type",
        "situs_unit_number",
        "situs_city_name",
    ]
    print(f"Reading {geojson_path.name} ...")
    df = pyogrio.read_dataframe(geojson_path, columns=cols)
    print(f"  {len(df):,} parcel rows")

    by_apn: dict[str, tuple[str, str, str | None, str | None]] = {}
    for row in df.to_dict(orient="records"):
        apn = normalize_apn(row.get("apn"))
        if not apn:
            continue
        scity_raw = str(row.get("situs_city_name") or "").strip() or None
        scity_norm = normalize_scity(scity_raw)
        addr = _build_situs_address(row)
        prev = by_apn.get(apn)
        if prev is None or (addr and len(addr) > len(prev[3] or "")):
            by_apn[apn] = (apn, scity_norm, scity_raw, addr)

    out = list(by_apn.values())
    print(f"  {len(out):,} unique APN rows for staging")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Fill missing scity/address from county parcel GeoJSON.")
    p.add_argument(
        "--parcels-geojson",
        type=Path,
        default=_repo_root() / "data" / "Parcels_20260529.geojson",
    )
    p.add_argument("--db-schema", default="public")
    p.add_argument("--db-table", default="unidata")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    path = Path(args.parcels_geojson)
    if not path.is_absolute():
        path = (_repo_root() / path).resolve()
    if not path.is_file():
        raise SystemExit(f"GeoJSON not found: {path}")

    rows = load_staging_rows(path)
    if not rows:
        raise SystemExit("No staging rows loaded.")

    conn = psycopg.connect(**DEFAULT_DB_CONFIG)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE _parcel_geo_enrich (
                    apn text NOT NULL,
                    scity_norm text NOT NULL,
                    scity_raw text,
                    address text
                ) ON COMMIT DROP
                """
            )
            buf = StringIO()
            for apn, sn, scity_raw, addr in rows:
                cols = [
                    apn,
                    sn,
                    scity_raw or "",
                    addr or "",
                ]
                buf.write(",".join('"' + c.replace('"', '""') + '"' for c in cols) + "\n")
            buf.seek(0)
            with cur.copy(
                "COPY _parcel_geo_enrich (apn, scity_norm, scity_raw, address) FROM STDIN WITH (FORMAT csv, QUOTE '\"')"
            ) as cp:
                cp.write(buf.getvalue())

            cur.execute(
                """
                SELECT COUNT(*)::bigint FROM {schema}.{table} u
                INNER JOIN _parcel_geo_enrich s ON upper(trim(u.parcelnumb)) = s.apn
                WHERE (u.scity IS NULL OR TRIM(u.scity::text) = '')
                  AND s.scity_raw IS NOT NULL AND TRIM(s.scity_raw) <> ''
                """.format(schema=args.db_schema, table=args.db_table)
            )
            scity_would = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)::bigint FROM {schema}.{table} u
                INNER JOIN _parcel_geo_enrich s ON upper(trim(u.parcelnumb)) = s.apn
                WHERE (u.address IS NULL OR TRIM(u.address::text) = '')
                  AND s.address IS NOT NULL AND TRIM(s.address) <> ''
                """.format(schema=args.db_schema, table=args.db_table)
            )
            addr_would = cur.fetchone()[0]

            print(f"Would update scity: {scity_would:,}")
            print(f"Would update address: {addr_would:,}")

            if not args.apply:
                conn.rollback()
                print("Dry run complete (no changes). Pass --apply to UPDATE.")
                return

            cur.execute(
                sql.SQL(
                    """
                    UPDATE {schema}.{table} u
                    SET scity = s.scity_raw, updated_at = NOW()
                    FROM _parcel_geo_enrich s
                    WHERE upper(trim(u.parcelnumb)) = s.apn
                      AND (u.scity IS NULL OR TRIM(u.scity::text) = '')
                      AND s.scity_raw IS NOT NULL AND TRIM(s.scity_raw) <> ''
                    """
                ).format(
                    schema=sql.Identifier(args.db_schema),
                    table=sql.Identifier(args.db_table),
                )
            )
            scity_updated = cur.rowcount

            cur.execute(
                sql.SQL(
                    """
                    UPDATE {schema}.{table} u
                    SET address = s.address, updated_at = NOW()
                    FROM _parcel_geo_enrich s
                    WHERE upper(trim(u.parcelnumb)) = s.apn
                      AND (u.address IS NULL OR TRIM(u.address::text) = '')
                      AND s.address IS NOT NULL AND TRIM(s.address) <> ''
                    """
                ).format(
                    schema=sql.Identifier(args.db_schema),
                    table=sql.Identifier(args.db_table),
                )
            )
            addr_updated = cur.rowcount
            conn.commit()
            print(f"Applied scity updates: {scity_updated:,}")
            print(f"Applied address updates: {addr_updated:,}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
