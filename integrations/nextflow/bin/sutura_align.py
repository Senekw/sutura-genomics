#!/usr/bin/env python3
"""
sutura_align.py - command-line entry point for a SINGLE alignment pair.

This is what the Nextflow ``SUTURA_ALIGN`` process (and the Snakemake rule) call. It aligns
one moving section onto one reference section, writes the aligned output and a metrics JSON,
and is robust to real-world messiness: a bad pair produces a ``status=failed`` metrics record
rather than crashing the whole run.

Outputs (into --outdir):
    <pair_id>.aligned.h5ad     aligned moving section (obsm['spatial_aligned'], obsm['spatial'])
    <pair_id>.coords.csv       barcode, x_aligned, y_aligned, x_original, y_original
    <pair_id>.metrics.json     routing decision, method, quality metrics, status, timing

Exit codes:
    0  handled outcome (success OR a cleanly-reported failure) - lets batch runs complete
    2  handled failure AND --strict was given
    1  unexpected internal error

Example:
    sutura_align.py \
        --reference data/DLPFC_151507.h5ad \
        --moving    data/DLPFC_151508.h5ad \
        --pair-id   Br5292 --method auto --gate-refine \
        --outdir    results/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# make the engine importable whether run from repo, container, or Nextflow work dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sutura_engine as eng  # noqa: E402


def _write_coords_csv(aligned, path):
    import numpy as np
    barcodes = list(map(str, aligned.obs_names))
    al = np.asarray(aligned.obsm["spatial_aligned"], float)
    orig = np.asarray(aligned.obsm["spatial_original"], float)
    with open(path, "w", newline="") as fh:
        fh.write("barcode,x_aligned,y_aligned,x_original,y_original\n")
        for i, bc in enumerate(barcodes):
            fh.write(f"{bc},{al[i,0]:.6f},{al[i,1]:.6f},"
                     f"{orig[i,0]:.6f},{orig[i,1]:.6f}\n")


def main():
    ap = argparse.ArgumentParser(
        description="Align one moving spatial section onto one reference section.")
    ap.add_argument("--reference", required=True,
                    help="reference section: .h5ad file or Space Ranger output dir")
    ap.add_argument("--moving", required=True,
                    help="moving section: .h5ad file or Space Ranger output dir")
    ap.add_argument("--pair-id", default="pair", help="identifier for this pair")
    ap.add_argument("--outdir", default=".", help="output directory")
    ap.add_argument("--method", default="auto", choices=["auto", "sutura", "paste2"],
                    help="auto = distribution-routed (default); or force a method")
    ap.add_argument("--gate-refine", action="store_true",
                    help="apply the training-free gate refinement to an OT (PASTE2) base")
    ap.add_argument("--gate-order", default="affine",
                    choices=["rigid", "affine", "quadratic"])
    ap.add_argument("--subsample", type=int, default=0,
                    help="cap each section to N spots (0 = no subsampling)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-spots", type=int, default=100)
    ap.add_argument("--knn", type=int, default=None,
                    help="override the GNN kNN graph degree (default: checkpoint value)")
    ap.add_argument("--output-format", default="both",
                    choices=["h5ad", "csv", "both"])
    ap.add_argument("--engine-root", default=None,
                    help="repo root with src/ + results/ (default: auto-detect / $SUTURA_ENGINE_ROOT)")
    ap.add_argument("--basis", default=None, help="override path to shared_basis.npz")
    ap.add_argument("--checkpoint", default=None, help="override path to arca_shared_basis.pt")
    ap.add_argument("--dist-reference", default=None, help="override path to dist_reference.npz")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero (2) on a handled alignment failure")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    metrics_path = outdir / f"{args.pair_id}.metrics.json"

    try:
        res, aligned = eng.align_pair(
            args.reference, args.moving,
            pair_id=args.pair_id, method=args.method,
            gate_refine=args.gate_refine, gate_order=args.gate_order,
            subsample=args.subsample, seed=args.seed, min_spots=args.min_spots,
            engine_root=args.engine_root, basis=args.basis,
            checkpoint=args.checkpoint, dist_reference=args.dist_reference,
            knn=args.knn)
    except Exception as e:  # truly unexpected - still leave a record, exit 1
        import traceback
        metrics_path.write_text(
            eng.AlignResult(pair_id=args.pair_id, status="failed",
                            error=f"{type(e).__name__}: {e}").to_json())
        traceback.print_exc()
        return 1

    metrics_path.write_text(res.to_json())

    if res.status == "ok" and aligned is not None:
        if args.output_format in ("h5ad", "both"):
            aligned.write_h5ad(outdir / f"{args.pair_id}.aligned.h5ad")
        if args.output_format in ("csv", "both"):
            _write_coords_csv(aligned, outdir / f"{args.pair_id}.coords.csv")
        print(f"[{args.pair_id}] OK  method={res.method}  "
              f"metrics={res.metrics}  ({res.runtime_sec}s)")
        return 0

    # handled failure
    print(f"[{args.pair_id}] FAILED: {res.error}", file=sys.stderr)
    return 2 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
