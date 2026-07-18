#!/usr/bin/env python3
"""
check_samplesheet.py - validate and normalise the sutura-align input samplesheet.

Runs first in the pipeline so a malformed sheet fails fast with a clear message rather
than surfacing halfway through a long batch. Responsibilities:

  * structural validation - required columns present, pair_id unique and well-formed,
    method / gate_refine values legal;
  * path existence - resolve each reference/moving path against the launch directory and
    check it exists (a file, a Space Ranger dir, or a dir holding one .h5ad);
  * missing-input policy - ``--on-missing fail`` aborts with a clear per-row error;
    ``--on-missing skip`` drops the row from the run, records it in skipped.csv, and emits
    a ``<pair_id>.skipped.metrics.json`` so the final report still accounts for it.

Writes ``validated.csv`` (normalised header: pair_id,reference,moving,method,gate_refine)
containing only runnable rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REQUIRED = ["pair_id", "reference", "moving"]
OPTIONAL = ["method", "gate_refine"]
VALID_METHODS = {"auto", "sutura", "paste2"}
TRUE_VALUES = {"true", "1", "yes", "on"}
FALSE_VALUES = {"false", "0", "no", "off", ""}
ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def die(msg):
    print(f"ERROR [samplesheet]: {msg}", file=sys.stderr)
    sys.exit(1)


def read_rows(path):
    """Read CSV rows, skipping blank and #-comment lines. Returns (header, rows)."""
    with open(path, newline="") as fh:
        lines = [ln for ln in fh
                 if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        die(f"samplesheet '{path}' is empty (no data rows)")
    reader = csv.DictReader(lines)
    header = [h.strip() for h in (reader.fieldnames or [])]
    rows = []
    for i, r in enumerate(reader, start=1):
        rows.append({(k.strip() if k else k): (v.strip() if isinstance(v, str) else v)
                     for k, v in r.items()})
    return header, rows


def resolve(path_str, launch_dir):
    p = Path(path_str)
    if not p.is_absolute() and launch_dir:
        p = Path(launch_dir) / p
    return p


def path_exists_as_section(p: Path):
    """A valid input is: an .h5ad/.h5 file, a Space Ranger dir, or a dir with one .h5ad."""
    if p.is_file():
        return p.suffix in (".h5ad", ".h5")
    if p.is_dir():
        if (p / "spatial").is_dir():
            return True
        return len(list(p.glob("*.h5ad"))) == 1
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="validated.csv")
    ap.add_argument("--skipped", default="skipped.csv")
    ap.add_argument("--launch-dir", default="")
    ap.add_argument("--on-missing", choices=["skip", "fail"], default="skip")
    args = ap.parse_args()

    header, rows = read_rows(args.input)

    missing_cols = [c for c in REQUIRED if c not in header]
    if missing_cols:
        die(f"samplesheet is missing required column(s): {', '.join(missing_cols)}. "
            f"Required: {', '.join(REQUIRED)}; optional: {', '.join(OPTIONAL)}.")

    seen_ids = set()
    valid, skipped = [], []

    for n, row in enumerate(rows, start=1):
        pid = (row.get("pair_id") or "").strip()
        if not pid:
            die(f"row {n}: empty pair_id")
        if not ID_RE.match(pid):
            die(f"row {n}: pair_id '{pid}' has illegal characters "
                f"(allowed: letters, digits, '_', '.', '-')")
        if pid in seen_ids:
            die(f"row {n}: duplicate pair_id '{pid}' (must be unique)")
        seen_ids.add(pid)

        ref = (row.get("reference") or "").strip()
        mov = (row.get("moving") or "").strip()
        if not ref:
            die(f"pair '{pid}': empty 'reference' path")
        if not mov:
            die(f"pair '{pid}': empty 'moving' path")

        method = (row.get("method") or "auto").strip() or "auto"
        if method not in VALID_METHODS:
            die(f"pair '{pid}': invalid method '{method}' "
                f"(expected one of {sorted(VALID_METHODS)})")

        graw = (row.get("gate_refine") or "").strip().lower()
        if graw not in TRUE_VALUES | FALSE_VALUES:
            die(f"pair '{pid}': gate_refine '{row.get('gate_refine')}' is not boolean-like "
                f"(use true/false)")
        gate = "true" if graw in TRUE_VALUES else "false"

        # path existence
        missing = []
        for tag, ps in [("reference", ref), ("moving", mov)]:
            rp = resolve(ps, args.launch_dir)
            if not path_exists_as_section(rp):
                missing.append(f"{tag} not found or not a valid section: {ps}")
        if missing:
            reason = "; ".join(missing)
            if args.on_missing == "fail":
                die(f"pair '{pid}': {reason}  "
                    f"(set --on-missing skip / params.on_missing='skip' to continue "
                    f"past missing inputs)")
            print(f"WARNING [samplesheet]: skipping pair '{pid}': {reason}",
                  file=sys.stderr)
            skipped.append(dict(pair_id=pid, reference=ref, moving=mov, reason=reason))
            # emit a metrics record so the report accounts for it
            Path(f"{pid}.skipped.metrics.json").write_text(json.dumps(dict(
                pair_id=pid, status="skipped", method="", routing={},
                metrics={}, error=reason, warnings=[reason]), indent=2))
            continue

        valid.append(dict(pair_id=pid, reference=ref, moving=mov,
                          method=method, gate_refine=gate))

    if not valid:
        die("no runnable pairs after validation "
            "(all rows were skipped or the sheet had no valid rows)")

    with open(args.output, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pair_id", "reference", "moving",
                                           "method", "gate_refine"])
        w.writeheader()
        w.writerows(valid)

    if skipped:
        with open(args.skipped, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["pair_id", "reference", "moving", "reason"])
            w.writeheader()
            w.writerows(skipped)

    print(f"[samplesheet] {len(valid)} valid pair(s), {len(skipped)} skipped")


if __name__ == "__main__":
    main()
