from __future__ import annotations

import json
import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def extract_title(html: str, fallback: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback
    return " ".join(match.group(1).split())


def extract_generated_time(html: str) -> dict[str, str] | None:
    match = re.search(
        r'<time\s+datetime="([^"]+)">([^<]+)</time>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return {"datetime": match.group(1), "label": " ".join(match.group(2).split())}


def html_to_json_payload(html_path: Path) -> dict:
    html = html_path.read_text(encoding="utf-8")
    return {
        "source_html": html_path.name,
        "title": extract_title(html, html_path.stem),
        "generated_time": extract_generated_time(html),
        "html": html,
    }


def write_report_json(html_path: Path, json_path: Path) -> None:
    payload = html_to_json_payload(html_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {json_path}")


def main() -> None:
    base = _repo_root() / "outputs" / "parcel_audits"
    write_report_json(
        base / "task2_santa_clara_residential_audit.html",
        base / "task2_santa_clara_residential_audit.json",
    )
    write_report_json(
        base / "unidata_v22_vs_gpkg_audit.html",
        base / "unidata_v22_vs_gpkg_audit.json",
    )


if __name__ == "__main__":
    main()
