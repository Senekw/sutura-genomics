"""
Baseline reproduction: re-derive the project's headline numbers through the new
harness and prove they match the prior research results.

It runs PASTE2 + the gate (rigid/affine) + Sutura across the DLPFC donors and the
two off-distribution pairs (all from the cached PASTE2 bases, so it is fast and
deterministic), then:

  1. cross-checks every PASTE2 / gate cell against research/results/hybrid_validate.csv
     (the prior authoritative run) and reports the maximum discrepancy;
  2. recomputes the headline aggregates and compares them to their published values:
       - PASTE2 DLPFC-LODO (7-severity grid, seed 0)        ~ 4.28
       - gate_rigid DLPFC-LODO (5-severity grid, seed 0)      = 3.73  (the headline)
       - gate_affine DLPFC-LODO (7-severity grid, seed 0)     = 3.08
       - Sutura in-distribution on Br5292 (sev-avg, seed 0)   ~ 1-3 pitch (< PASTE2)

Writes benchmarks/results/REPRODUCTION.md and prints a PASS/FAIL summary.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import config, harness, report
from .harness import RunConfig

# published headline values (from research/FINDINGS_hybrid_validated.md and
# research/FINDINGS_cross_donor_gap_summary.md)
HEADLINE = {
    "paste2_lodo_7grid_seed0": 4.28,
    "gate_rigid_lodo_5grid_seed0": 3.73,
    "gate_affine_lodo_7grid_seed0": 3.08,
}
FIVE_GRID = [0.0, 2.0, 4.0, 6.0, 8.0]
SEVEN_GRID = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
DLPFC = ["Br5292", "Br5595", "Br8100"]

# map our method names to hybrid_validate.csv config names for cross-check
XCHECK = {"paste2": "paste2", "gate_rigid": "gated_rigid", "gate_affine": "gated_affine"}


def _lodo_mean(df, method, grid, seed):
    sub = df[(df["method"] == method) & (df["seed"] == seed)
             & (df["dataset"].isin(DLPFC)) & (df["severity"].isin(grid))]
    if sub.empty:
        return float("nan")
    per_donor = sub.groupby("dataset")["median_pitch"].mean()
    return float(per_donor.mean())


def _sev_avg(df, method, dataset, grid, seed):
    sub = df[(df["method"] == method) & (df["dataset"] == dataset)
             & (df["seed"] == seed) & (df["severity"].isin(grid))]
    return float(sub["median_pitch"].mean()) if not sub.empty else float("nan")


def _crosscheck(df) -> tuple[float, list]:
    """Max abs diff of our PASTE2/gate cells vs hybrid_validate.csv."""
    ref_csv = config.RESEARCH_RESULTS / "hybrid_validate.csv"
    if not ref_csv.exists():
        return float("nan"), []
    ref = pd.read_csv(ref_csv)
    ref = ref[ref["status"] == "ok"]
    diffs, rows = [], []
    for ours, theirs in XCHECK.items():
        for _, r in df[df["method"] == ours].iterrows():
            m = ref[(ref["dataset"] == r["dataset"]) & (ref["config"] == theirs)
                    & (np.isclose(ref["severity"], r["severity"]))
                    & (ref["seed"] == r["seed"])]
            if not m.empty:
                d = abs(float(m["err_pitch"].iloc[0]) - float(r["median_pitch"]))
                diffs.append(d)
                if d > 0.01:
                    rows.append((r["dataset"], ours, r["severity"], r["seed"],
                                 float(m["err_pitch"].iloc[0]), float(r["median_pitch"]), d))
    return (max(diffs) if diffs else float("nan")), rows


def main(quick: bool = False):
    config.ensure_dirs()
    seeds = [0] if quick else [0, 1, 2]
    ds = [d for d in DLPFC + ["breast", "mousebrain"]]
    ms = ["paste2", "gate_rigid", "gate_affine", "sutura"]
    cfg = RunConfig(datasets=ds, methods=ms, seeds=seeds, severities=None,
                    run_tag="reproduce", resume=True)
    out = harness.run(cfg)
    df = report.load(out)

    # ---- cross-check vs the prior authoritative CSV ---------------------- #
    max_diff, bad = _crosscheck(df)

    # ---- headline aggregates -------------------------------------------- #
    got = {
        "paste2_lodo_7grid_seed0": _lodo_mean(df, "paste2", SEVEN_GRID, 0),
        "gate_rigid_lodo_5grid_seed0": _lodo_mean(df, "gate_rigid", FIVE_GRID, 0),
        "gate_affine_lodo_7grid_seed0": _lodo_mean(df, "gate_affine", SEVEN_GRID, 0),
    }
    sutura_br5292 = _sev_avg(df, "sutura", "Br5292", SEVEN_GRID, 0)
    paste2_br5292 = _sev_avg(df, "paste2", "Br5292", SEVEN_GRID, 0)

    # ---- verdicts ------------------------------------------------------- #
    lines = ["# Baseline reproduction", "",
             f"_Run through `sutura_bench` on {len(ds)} datasets, seeds {seeds}. "
             f"PASTE2/gate cells derive from cached bases; Sutura is checkpoint "
             f"inference (arca_cross.pt)._", ""]

    lines += ["## Cross-check vs prior authoritative run (hybrid_validate.csv)", ""]
    if np.isnan(max_diff):
        lines.append("- hybrid_validate.csv not found; skipped.")
    else:
        ok = max_diff <= 0.01
        lines.append(f"- Max |delta| across all matched PASTE2/gate cells: "
                     f"**{max_diff:.4f} pitch** ({'MATCH' if ok else 'MISMATCH'}, "
                     f"tolerance 0.01).")
        if bad:
            lines.append("- Cells exceeding 0.01:")
            for d, m, s, sd, refv, curv, dd in bad[:20]:
                lines.append(f"  - {d} {m} sev{s:g} seed{sd}: ref {refv:.3f} vs "
                             f"cur {curv:.3f} (delta {dd:.3f})")

    lines += ["", "## Headline aggregates vs published values", "",
              "| quantity | published | reproduced | delta | verdict |",
              "|---|---|---|---|---|"]
    all_ok = np.isnan(max_diff) or max_diff <= 0.01
    for k, pub in HEADLINE.items():
        cur = got[k]
        delta = cur - pub
        verdict = "OK" if abs(delta) <= 0.05 else "CHECK"
        if verdict != "OK":
            all_ok = False
        lines.append(f"| {k} | {pub:.2f} | {cur:.3f} | {delta:+.3f} | {verdict} |")
    lines.append("")

    lines += ["## Sutura in-distribution (Br5292, checkpoint arca_cross.pt)", "",
              f"- Sutura sev-avg (7-grid, seed 0): **{sutura_br5292:.3f} pitch**",
              f"- PASTE2 sev-avg (same grid): {paste2_br5292:.3f} pitch",
              f"- Sutura {'beats' if sutura_br5292 < paste2_br5292 else 'does NOT beat'} "
              f"PASTE2 in-distribution "
              f"({'expected: it is trained on this donor' if sutura_br5292 < paste2_br5292 else 'unexpected'}).",
              ""]

    verdict = "PASS" if all_ok else "REVIEW"
    lines.insert(1, f"\n**Overall: {verdict}**\n")

    md = config.BENCH_RESULTS / "REPRODUCTION.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote -> {md}")
    return all_ok
