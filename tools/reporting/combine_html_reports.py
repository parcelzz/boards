from __future__ import annotations

import base64
import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def get_title(html: str, fallback: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback
    return " ".join(match.group(1).split())


def build_combined_html(report_a: str, report_b: str, title_a: str, title_b: str) -> str:
    # Use base64 payloads so embedded HTML cannot break outer <script> parsing.
    report_a_b64 = base64.b64encode(report_a.encode("utf-8")).decode("ascii")
    report_b_b64 = base64.b64encode(report_b.encode("utf-8")).decode("ascii")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Combined Audit Report</title>
  <style>
    :root {{
      --bg: #f3f5f9;
      --panel: #ffffff;
      --text: #111827;
      --muted: #6b7280;
      --line: #dde3ee;
      --accent: #2457a8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    .container {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 20px;
    }}
    .header {{
      background: linear-gradient(135deg, #17386f 0%, #2457a8 70%, #3273dd 100%);
      color: #fff;
      border-radius: 14px;
      padding: 20px 24px;
      margin-bottom: 16px;
    }}
    .header h1 {{
      margin: 0 0 6px;
      font-size: 28px;
    }}
    .header p {{
      margin: 0;
      opacity: 0.92;
    }}
    .tabs {{
      display: flex;
      gap: 10px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }}
    .tab-btn {{
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      padding: 9px 14px;
      border-radius: 10px;
      cursor: pointer;
      font-weight: 600;
    }}
    .tab-btn.active {{
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 8px 20px rgba(17, 24, 39, 0.08);
    }}
    iframe {{
      width: 100%;
      height: calc(100vh - 240px);
      min-height: 760px;
      border: 0;
      display: none;
      background: #fff;
    }}
    iframe.active {{
      display: block;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header class="header">
      <h1>Combined Audit Report</h1>
      <p>Single-file report combining both HTML audits.</p>
    </header>

    <div class="tabs">
      <button class="tab-btn active" data-target="report-a">{title_a}</button>
      <button class="tab-btn" data-target="report-b">{title_b}</button>
    </div>

    <section class="panel">
      <iframe id="report-a" class="active" title="{title_a}"></iframe>
      <iframe id="report-b" title="{title_b}"></iframe>
    </section>
  </div>

  <script>
    function b64ToDataUrl(payload) {{
      return "data:text/html;charset=utf-8;base64," + payload;
    }}

    document.getElementById("report-a").src = b64ToDataUrl("{report_a_b64}");
    document.getElementById("report-b").src = b64ToDataUrl("{report_b_b64}");

    const buttons = [...document.querySelectorAll(".tab-btn")];
    const frames = [...document.querySelectorAll("iframe")];
    buttons.forEach((btn) => {{
      btn.addEventListener("click", () => {{
        buttons.forEach((b) => b.classList.remove("active"));
        frames.forEach((f) => f.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.target).classList.add("active");
      }});
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    base = _repo_root() / "outputs" / "parcel_audits"
    file_a = base / "task2_santa_clara_residential_audit.html"
    file_b = base / "unidata_v22_vs_gpkg_audit.html"
    output = base / "combined_audit_report.html"

    report_a = file_a.read_text(encoding="utf-8")
    report_b = file_b.read_text(encoding="utf-8")

    title_a = get_title(report_a, file_a.name)
    title_b = get_title(report_b, file_b.name)

    merged = build_combined_html(report_a, report_b, title_a, title_b)
    output.write_text(merged, encoding="utf-8")
    print(f"Wrote: {output}")


if __name__ == "__main__":
    main()
