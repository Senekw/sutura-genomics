"""
Regression detection: compare a fresh run against stored reference results and
flag any method that got worse.

A reference is a snapshot of per-cell median-pitch errors (one per dataset x
method x severity x seed) plus the headline DLPFC-LODO aggregates, written by
``save_reference``. ``check`` re-loads a new run's CSV, matches cells to the
reference, and flags a cell as a REGRESSION when the new error exceeds the
reference by BOTH an absolute and a relative tolerance (so sub-noise wiggle does
not trip it, but a real accuracy loss always does). Improvements and
missing/new cells are reported too.

Tolerances default to 0.05 pitch absolute and 3% relative - wide enough to
absorb the float noise in CV-gated fits (observed <= 0.001 pitch) and PASTE2's
own re-solve jitter, tight enough to catch a genuine method regression.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from . import config
from .report import load, dlpfc_lodo

DEFAULT_ABS_TOL = 0.05      # spot-pitches
DEFAULT_REL_TOL = 0.03      # 3%


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cell_key(dataset, method, severity, seed) -> str:
    return f"{dataset}|{method}|{float(severity):g}|{int(seed)}"


# --------------------------------------------------------------------------- #
# saving a reference
# --------------------------------------------------------------------------- #
def save_reference(csv_path, out_json: Optional[Path] = None,
                   note: str = "") -> Path:
    df = load(csv_path)
    cells = {}
    for _, r in df.iterrows():
        cells[_cell_key(r["dataset"], r["method"], r["severity"], r["seed"])] = \
            round(float(r["median_pitch"]), 4)
    lodo = {r["method"]: round(float(r["lodo_mean"]), 4)
            for _, r in dlpfc_lodo(df).iterrows()}
    ref = {
        "created": _now(),
        "source_csv": Path(csv_path).name,
        "note": note,
        "n_cells": len(cells),
        "dlpfc_lodo": lodo,
        "cells": cells,
    }
    out = Path(out_json) if out_json else config.REFERENCE_RESULTS
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ref, indent=2))
    return out


# --------------------------------------------------------------------------- #
# checking a run against a reference
# --------------------------------------------------------------------------- #
@dataclass
class CellDelta:
    key: str
    reference: float
    current: float
    delta: float          # current - reference (positive = worse)
    pct: float            # relative change


def check(csv_path, ref_json: Optional[Path] = None,
          abs_tol: float = DEFAULT_ABS_TOL, rel_tol: float = DEFAULT_REL_TOL) -> dict:
    ref_path = Path(ref_json) if ref_json else config.REFERENCE_RESULTS
    if not ref_path.exists():
        raise FileNotFoundError(
            f"no reference at {ref_path}. Create one with save_reference(...).")
    ref = json.loads(ref_path.read_text())
    ref_cells = ref["cells"]
    df = load(csv_path)

    regressions, improvements, unchanged = [], [], 0
    matched, new_cells = set(), []
    for _, r in df.iterrows():
        key = _cell_key(r["dataset"], r["method"], r["severity"], r["seed"])
        cur = round(float(r["median_pitch"]), 4)
        if key not in ref_cells:
            new_cells.append(key)
            continue
        matched.add(key)
        base = ref_cells[key]
        delta = cur - base
        pct = delta / base if base > 0 else 0.0
        cd = CellDelta(key, base, cur, round(delta, 4), round(pct, 4))
        if delta > abs_tol and pct > rel_tol:
            regressions.append(cd)
        elif -delta > abs_tol and -pct > rel_tol:
            improvements.append(cd)
        else:
            unchanged += 1
    missing = sorted(set(ref_cells) - matched)

    regressions.sort(key=lambda c: c.delta, reverse=True)
    improvements.sort(key=lambda c: c.delta)
    return {
        "reference": str(ref_path),
        "current_csv": str(csv_path),
        "abs_tol": abs_tol, "rel_tol": rel_tol,
        "n_matched": len(matched), "n_unchanged": unchanged,
        "regressions": [asdict(c) for c in regressions],
        "improvements": [asdict(c) for c in improvements],
        "missing_cells": missing, "new_cells": new_cells,
        "passed": len(regressions) == 0,
    }


def format_report(rep: dict) -> str:
    lines = ["# Regression check", "",
             f"reference: `{Path(rep['reference']).name}`  |  "
             f"current: `{Path(rep['current_csv']).name}`",
             f"tolerance: > {rep['abs_tol']:g} pitch AND > {rep['rel_tol']*100:g}%  |  "
             f"matched {rep['n_matched']} cells ({rep['n_unchanged']} within tolerance)",
             ""]
    verdict = "PASS - no regressions" if rep["passed"] else \
              f"FAIL - {len(rep['regressions'])} regression(s)"
    lines += [f"**{verdict}**", ""]

    if rep["regressions"]:
        lines += ["## Regressions (got worse)", "",
                  "| cell (dataset\\|method\\|sev\\|seed) | reference | current | delta | % |",
                  "|---|---|---|---|---|"]
        for c in rep["regressions"]:
            lines.append(f"| {c['key']} | {c['reference']:.3f} | {c['current']:.3f} "
                         f"| +{c['delta']:.3f} | +{c['pct']*100:.1f}% |")
        lines.append("")
    if rep["improvements"]:
        lines += ["## Improvements (got better)", "",
                  "| cell | reference | current | delta | % |", "|---|---|---|---|---|"]
        for c in rep["improvements"][:30]:
            lines.append(f"| {c['key']} | {c['reference']:.3f} | {c['current']:.3f} "
                         f"| {c['delta']:.3f} | {c['pct']*100:.1f}% |")
        lines.append("")
    if rep["missing_cells"]:
        lines.append(f"_{len(rep['missing_cells'])} reference cell(s) not present in "
                     f"the current run (not scored)._")
    if rep["new_cells"]:
        lines.append(f"_{len(rep['new_cells'])} new cell(s) not in the reference._")
    return "\n".join(lines) + "\n"
