from datetime import datetime, timezone
from pathlib import Path
import re


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def update_task2(path: Path) -> None:
    now_utc = datetime.now(timezone.utc)
    replacement = (
        f'<time datetime="{now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}">'
        f'{now_utc.strftime("%Y-%m-%d %H:%M UTC")}</time>'
    )
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'<time datetime="[^"]+">[^<]+</time>', replacement, text, count=1)
    path.write_text(text, encoding="utf-8")


def update_unidata(path: Path) -> None:
    now_local = datetime.now().astimezone()
    replacement = (
        f'<time datetime="{now_local.isoformat(timespec="seconds")}">'
        f'{now_local.strftime("%Y-%m-%d %H:%M:%S %Z (UTC%z)")}</time>'
    )
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'<time datetime="[^"]+">[^<]+</time>', replacement, text, count=1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    out = _repo_root() / "outputs" / "parcel_audits"
    update_task2(out / "task2_santa_clara_residential_audit.html")
    update_unidata(out / "unidata_v22_vs_gpkg_audit.html")
    print("Updated report timestamps.")
