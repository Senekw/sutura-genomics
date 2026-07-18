#!/usr/bin/env python3
"""
make_report.py - aggregate per-pair metrics JSON into a summary CSV and a standalone HTML report.

Reads every ``*.metrics.json`` in --metrics-dir (produced by sutura_align.py for aligned
pairs and by check_samplesheet.py for skipped pairs), and writes:

  * summary.csv        one row per pair, flat columns for downstream analysis
  * sutura_report.html a self-contained, dependency-free report a lab can open in a browser

No third-party dependencies (pure standard library) so it runs in the leanest container.
"""
from __future__ import annotations

import argparse
import csv
import glob
import html
import json
import os
from pathlib import Path


def load_metrics(metrics_dir):
    records = []
    for f in sorted(glob.glob(os.path.join(metrics_dir, "*.metrics.json"))):
        try:
            records.append(json.loads(Path(f).read_text()))
        except Exception as e:
            records.append(dict(pair_id=Path(f).stem, status="failed",
                                error=f"unreadable metrics file: {e}"))
    return records


def _reg(rec):
    m = (rec.get("metrics") or {}).get("registration_error_pitch")
    if isinstance(m, dict):
        return m.get("median"), m.get("p90"), m.get("n")
    return None, None, None


def flatten(rec):
    med, p90, n = _reg(rec)
    routing = rec.get("routing") or {}
    metrics = rec.get("metrics") or {}
    gr = rec.get("gate_refine") or {}
    return {
        "pair_id": rec.get("pair_id", ""),
        "status": rec.get("status", ""),
        "method": rec.get("method", ""),
        "routing_reason": routing.get("reason", ""),
        "gene_overlap": routing.get("gene_overlap", ""),
        "in_distribution": routing.get("in_distribution", ""),
        "confidence": routing.get("confidence", ""),
        "reg_error_median_pitch": med if med is not None else "",
        "reg_error_p90_pitch": p90 if p90 is not None else "",
        "reg_error_n": n if n is not None else "",
        "footprint_coverage": metrics.get("footprint_coverage", ""),
        "local_distortion_pitch": metrics.get("local_distortion_pitch", ""),
        "n_aligned": metrics.get("n_aligned", ""),
        "n_moving": metrics.get("n_moving", ""),
        "gate_kept": gr.get("kept", ""),
        "gate_fraction": gr.get("gated_fraction", ""),
        "runtime_sec": rec.get("runtime_sec", ""),
        "error": rec.get("error", "") or "",
    }


def write_csv(rows, path):
    cols = ["pair_id", "status", "method", "routing_reason", "gene_overlap",
            "in_distribution", "confidence", "reg_error_median_pitch",
            "reg_error_p90_pitch", "reg_error_n", "footprint_coverage",
            "local_distortion_pitch", "n_aligned", "n_moving", "gate_kept",
            "gate_fraction", "runtime_sec", "error"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


STATUS_BADGE = {
    "ok": ("#0a7d34", "#e6f6ec", "OK"),
    "failed": ("#b3261e", "#fce8e6", "FAILED"),
    "skipped": ("#8a6d00", "#fff6da", "SKIPPED"),
}


def esc(x):
    return html.escape("" if x is None else str(x))


def html_report(rows, run_name):
    n_total = len(rows)
    n_ok = sum(1 for r in rows if r["status"] == "ok")
    n_fail = sum(1 for r in rows if r["status"] == "failed")
    n_skip = sum(1 for r in rows if r["status"] == "skipped")
    meds = [float(r["reg_error_median_pitch"]) for r in rows
            if r["reg_error_median_pitch"] not in ("", None)]
    med_summary = (f"{min(meds):.2f} - {max(meds):.2f} pitch (median "
                   f"{sorted(meds)[len(meds)//2]:.2f})") if meds else "n/a"

    header_cells = ["Pair", "Status", "Method", "Routing", "Gene overlap",
                    "Reg. error (median pitch)", "Reg. error (p90)",
                    "Footprint cov.", "Local distortion", "Spots", "Gate",
                    "Runtime (s)", "Notes"]

    def row_html(r):
        color, bg, label = STATUS_BADGE.get(r["status"], ("#555", "#eee", r["status"].upper()))
        badge = (f'<span class="badge" style="color:{color};background:{bg}">'
                 f'{esc(label)}</span>')
        spots = f'{esc(r["n_aligned"])}/{esc(r["n_moving"])}' if r["n_moving"] != "" else ""
        gate = ""
        if r["gate_kept"] != "":
            gate = "kept" if r["gate_kept"] in (True, "True", "true") else "not kept"
            if r["gate_fraction"] != "":
                gate += f' ({r["gate_fraction"]})'
        note = esc(r["error"]) if r["error"] else esc(r["routing_reason"])
        cells = [
            f'<strong>{esc(r["pair_id"])}</strong>',
            badge,
            esc(r["method"]),
            esc(r["routing_reason"]) if r["status"] == "ok" else "",
            esc(r["gene_overlap"]),
            esc(r["reg_error_median_pitch"]),
            esc(r["reg_error_p90_pitch"]),
            esc(r["footprint_coverage"]),
            esc(r["local_distortion_pitch"]),
            spots,
            esc(gate),
            esc(r["runtime_sec"]),
            f'<span class="note">{note}</span>',
        ]
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    body_rows = "\n".join(row_html(r) for r in rows)
    head = "".join(f"<th>{esc(h)}</th>" for h in header_cells)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sutura-align report</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 2rem; line-height: 1.45; color: #1a1a1a; background: #fafafa; }}
  @media (prefers-color-scheme: dark) {{
     body {{ color: #e6e6e6; background: #16181c; }}
     .card {{ background: #22252b !important; border-color: #333 !important; }}
     th {{ background: #2a2e35 !important; }}
     tr:nth-child(even) td {{ background: #1d2025 !important; }}
     .note {{ color: #9aa0a6 !important; }}
  }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
  .sub {{ color: #666; margin-bottom: 1.5rem; }}
  .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }}
  .card {{ background: #fff; border: 1px solid #e3e3e3; border-radius: 10px;
          padding: 1rem 1.25rem; min-width: 130px; }}
  .card .n {{ font-size: 1.8rem; font-weight: 700; }}
  .card .l {{ color: #777; font-size: .85rem; text-transform: uppercase; letter-spacing: .04em; }}
  .tablewrap {{ overflow-x: auto; border-radius: 10px; border: 1px solid #e3e3e3; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .88rem; }}
  th, td {{ padding: .5rem .7rem; text-align: left; white-space: nowrap; border-bottom: 1px solid #ececec; }}
  th {{ background: #f2f2f4; position: sticky; top: 0; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  .badge {{ padding: .1rem .5rem; border-radius: 999px; font-size: .78rem; font-weight: 700; }}
  .note {{ color: #777; white-space: normal; max-width: 340px; display: inline-block; }}
  footer {{ margin-top: 2rem; color: #999; font-size: .8rem; }}
  code {{ background: rgba(127,127,127,.15); padding: .05rem .3rem; border-radius: 4px; }}
</style></head><body>
  <h1>sutura-align &mdash; alignment report</h1>
  <div class="sub">Run: <code>{esc(run_name)}</code></div>
  <div class="cards">
    <div class="card"><div class="n">{n_total}</div><div class="l">pairs</div></div>
    <div class="card"><div class="n" style="color:#0a7d34">{n_ok}</div><div class="l">aligned</div></div>
    <div class="card"><div class="n" style="color:#b3261e">{n_fail}</div><div class="l">failed</div></div>
    <div class="card"><div class="n" style="color:#8a6d00">{n_skip}</div><div class="l">skipped</div></div>
    <div class="card"><div class="n" style="font-size:1.1rem">{esc(med_summary)}</div>
        <div class="l">reg. error range</div></div>
  </div>
  <div class="tablewrap"><table>
    <thead><tr>{head}</tr></thead>
    <tbody>
{body_rows}
    </tbody>
  </table></div>
  <footer>
    Registration error is Euclidean distance in spot-pitch units, measured against the shared
    Visium array bridge where both sections carry array coordinates; a good alignment is a few
    pitch. <em>Footprint coverage</em> (~1 healthy) and <em>local distortion</em> (lower better)
    are ground-truth-free proxies reported for every pair. Generated by sutura-align.
  </footer>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics-dir", default=".")
    ap.add_argument("--html", default="sutura_report.html")
    ap.add_argument("--summary", default="summary.csv")
    ap.add_argument("--run-name", default="sutura-align")
    args = ap.parse_args()

    records = load_metrics(args.metrics_dir)
    rows = [flatten(r) for r in records]
    rows.sort(key=lambda r: (r["status"] != "ok", r["pair_id"]))

    write_csv(rows, args.summary)
    Path(args.html).write_text(html_report(rows, args.run_name), encoding="utf-8")
    print(f"[report] {len(rows)} pair(s) -> {args.html}, {args.summary}")


if __name__ == "__main__":
    main()
