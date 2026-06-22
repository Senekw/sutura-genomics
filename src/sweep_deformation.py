"""
ARCA — deformation stress test for the OT baseline (PASTE2).

For a sweep of warp severities, warp slice 151508 with a known displacement
field (src/warp_slice.apply_warp), run PASTE2 partial alignment of
(reference, warped-151508), and measure how badly registration degrades:

  * registration error (px) — soft-map each warped spot back into the reference
    frame via the transport plan (barycentric projection) and compare to the
    ground-truth target. mean / median / p90 reported.
  * layer-label transfer accuracy + random floor (reused from src/scoring.py).

Reference modes:
  cross (default) — reference = real adjacent slice 151507; GT target for a
        warped 151508 spot is the 151507 spot at the same Visium array position
        (95% of spots have a match; both slices share the same pixel frame).
  self            — reference = the ORIGINAL (unwarped) 151508; GT target is the
        spot's own original coordinate. Exact, zero-baseline registration error.

Outputs:
  results/sweep_deformation[_<suffix>].csv   severity vs error/accuracy table
  results/sweep_deformation[_<suffix>].png   the registration-error curve

Usage (validate small first):
  python src/sweep_deformation.py --subsample 250 --severities 0,3,8 \
         --dissimilarity pca --suffix smoke
Full sweep (expensive — see plan before running):
  python src/sweep_deformation.py --severities 0,1,2,3,4,6,8
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import anndata as ad
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from paste2.PASTE2 import partial_pairwise_align
from paste2.helper import filter_for_common_genes

from warp_slice import apply_warp
from scoring import (argmax_projection, barycentric_projection,
                     registration_error_stats, report)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"


def load_slice(sample_id: str) -> ad.AnnData:
    path = DATA_DIR / f"DLPFC_{sample_id}.h5ad"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run src/prepare_data.py.")
    return ad.read_h5ad(path)


def array_keys(adata):
    return list(zip(adata.obs["array_row"].astype(int),
                    adata.obs["array_col"].astype(int)))


def subset_to_common_positions(ref, target, n, seed=0):
    """Subset both slices to n shared Visium array positions (keeps the GT
    bridge exact and runs fast). Used only for the small validation."""
    rk = {k: i for i, k in enumerate(array_keys(ref))}
    tk = {k: j for j, k in enumerate(array_keys(target))}
    common = sorted(set(rk) & set(tk))
    rng = np.random.default_rng(seed)
    if n < len(common):
        common = [common[i] for i in
                  np.sort(rng.choice(len(common), n, replace=False))]
    ri = [rk[k] for k in common]
    ti = [tk[k] for k in common]
    return ref[ri].copy(), target[ti].copy()


def gt_targets(ref, warped_target, mode):
    """Ground-truth reference-frame coordinate for each warped target spot."""
    if mode == "self":
        # reference IS the original slice; target's true home is its own
        # pre-warp coordinate.
        return np.asarray(warped_target.obsm["spatial_original"], dtype=float), \
            np.ones(warped_target.n_obs, dtype=bool)
    # cross: match by Visium array position into the reference slice.
    rk = {k: i for i, k in enumerate(array_keys(ref))}
    rcoord = np.asarray(ref.obsm["spatial"], dtype=float)
    gt = np.full((warped_target.n_obs, 2), np.nan)
    have = np.zeros(warped_target.n_obs, dtype=bool)
    for j, k in enumerate(array_keys(warped_target)):
        i = rk.get(k)
        if i is not None:
            gt[j] = rcoord[i]
            have[j] = True
    return gt, have


def run_one(ref, target_orig, severity, *, seed, tear, mode, s, alpha,
            dissimilarity, save_path=None):
    """Warp, align, and score a single severity level.

    Registration error is computed with BOTH the soft barycentric projection
    and the hard argmax projection, so we can tell a real degradation from a
    barycentric-smearing artifact. If save_path is given, the transport matrix
    is persisted there (so the run can be re-scored without re-aligning)."""
    warped, _ = apply_warp(target_orig, severity, seed=seed, tear=tear)

    A = ref.copy()
    B = warped.copy()
    filter_for_common_genes([A, B])

    t0 = time.time()
    pi = np.asarray(partial_pairwise_align(
        A, B, s=s, alpha=alpha, dissimilarity=dissimilarity, verbose=False))
    dt = time.time() - t0

    if save_path is not None:
        np.save(save_path, pi)

    # registration error: project B spots into A's frame, compare to GT target.
    gt, have = gt_targets(A, B, mode)
    pred_b, col_mass = barycentric_projection(pi, A.obsm["spatial"])
    pred_a, _ = argmax_projection(pi, A.obsm["spatial"])
    mask = have & (col_mass > 0)
    reg_bary = registration_error_stats(pred_b, gt, mask=mask)
    reg_arg = registration_error_stats(pred_a, gt, mask=mask)

    # label transfer (A->B) + random floor, reused from scoring.py
    lab = report(pi, A.obs["layer"].astype(str).values,
                 B.obs["layer"].astype(str).values)

    warp_meta = warped.uns["warp"]
    return {
        "severity": severity,
        "max_disp_px": warp_meta["max_disp_px"],
        "mean_disp_px": warp_meta["mean_disp_px"],
        # barycentric (soft) projection — original columns, kept for continuity
        "reg_err_mean": reg_bary["mean"],
        "reg_err_median": reg_bary["median"],
        "reg_err_p90": reg_bary["p90"],
        # argmax (hard) projection
        "reg_err_mean_argmax": reg_arg["mean"],
        "reg_err_median_argmax": reg_arg["median"],
        "reg_err_p90_argmax": reg_arg["p90"],
        "n_reg_scored": reg_bary["n"],
        "paste2_acc": lab["model"]["accuracy"],
        "random_floor": lab["random_floor"]["accuracy_mean"],
        "n_label_scored": lab["model"]["n_scored"],
        "runtime_s": dt,
    }


def make_plot(rows, png_path, *, mode, pitch_px):
    sev = [r["severity"] for r in rows]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

    ax1.plot(sev, [r["reg_err_median"] for r in rows], "o-",
             label="median (barycentric)")
    ax1.plot(sev, [r["reg_err_median_argmax"] for r in rows], "D-",
             color="crimson", label="median (argmax)")
    ax1.plot(sev, [r["reg_err_mean"] for r in rows], "s--",
             label="mean (barycentric)")
    if pitch_px:
        ax1.axhline(pitch_px, color="gray", ls=":", lw=1,
                    label=f"1 spot pitch ({pitch_px:.0f}px)")
    ax1.set_xlabel("warp severity (spot-pitches)")
    ax1.set_ylabel("registration error (px)")
    ax1.set_title(f"PASTE2 registration error vs deformation ({mode})")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)

    ax2.plot(sev, [r["paste2_acc"] for r in rows], "o-", label="PASTE2 accuracy")
    ax2.plot(sev, [r["random_floor"] for r in rows], "--", color="gray",
             label="random floor")
    ax2.set_xlabel("warp severity (spot-pitches)")
    ax2.set_ylabel("layer-label transfer accuracy")
    ax2.set_ylim(0, 1)
    ax2.set_title("Label-transfer accuracy vs deformation")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(png_path, dpi=130)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reference", default="151507")
    p.add_argument("--sample", default="151508")
    p.add_argument("--mode", choices=["cross", "self"], default="cross")
    p.add_argument("--severities", default="0,1,2,3,4,6,8",
                   help="comma-separated warp severities (spot-pitches)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--tear", action="store_true")
    p.add_argument("--s", type=float, default=0.99,
                   help="PASTE2 overlap fraction (0.99 ~ full; s=1.0 trips a "
                        "partial-OT float-rounding infeasibility)")
    p.add_argument("--alpha", type=float, default=0.1)
    p.add_argument("--dissimilarity", default="glmpca",
                   choices=["glmpca", "pca", "kl", "euclidean"])
    p.add_argument("--subsample", type=int, default=0,
                   help="subsample N shared array positions (validation only)")
    p.add_argument("--suffix", default="")
    args = p.parse_args()

    severities = [float(x) for x in args.severities.split(",")]

    ref_full = load_slice(args.reference if args.mode == "cross" else args.sample)
    target_full = load_slice(args.sample)
    if args.mode == "self":
        ref_full = target_full  # reference frame = original (unwarped) slice

    if args.subsample:
        ref_full, target_full = subset_to_common_positions(
            ref_full, target_full, args.subsample, seed=args.seed)

    from scipy.spatial import cKDTree
    d, _ = cKDTree(target_full.obsm["spatial"]).query(
        target_full.obsm["spatial"], k=2)
    pitch_px = float(np.median(d[:, 1]))

    print("=" * 70)
    print(f"ARCA deformation sweep — mode={args.mode}  "
          f"ref={args.reference} sample={args.sample}")
    print(f"  severities    : {severities}")
    print(f"  dissimilarity : {args.dissimilarity}  s={args.s} alpha={args.alpha}"
          f"  tear={args.tear}")
    print(f"  spots         : ref={ref_full.n_obs} target={target_full.n_obs}"
          f"  pitch={pitch_px:.1f}px")
    if args.subsample:
        print(f"  SUBSAMPLE     : {args.subsample} shared positions (validation)")
    print("=" * 70)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.suffix}" if args.suffix else ""

    rows = []
    for sev in severities:
        from warp_slice import sev_tag
        pi_path = RESULTS_DIR / f"pi{suffix}_sev{sev_tag(sev)}.npy"
        r = run_one(ref_full, target_full, sev, seed=args.seed, tear=args.tear,
                    mode=args.mode, s=args.s, alpha=args.alpha,
                    dissimilarity=args.dissimilarity, save_path=pi_path)
        rows.append(r)
        print(f"  sev={sev:>4}: reg_err median bary={r['reg_err_median']:7.1f}px "
              f"argmax={r['reg_err_median_argmax']:7.1f}px  "
              f"acc={r['paste2_acc']*100:5.1f}% "
              f"floor={r['random_floor']*100:4.1f}%  "
              f"({r['runtime_s']:.0f}s)")

    csv_path = RESULTS_DIR / f"sweep_deformation{suffix}.csv"
    png_path = RESULTS_DIR / f"sweep_deformation{suffix}.png"

    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    make_plot(rows, png_path, mode=args.mode, pitch_px=pitch_px)
    print(f"\nwrote CSV  -> {csv_path}")
    print(f"wrote plot -> {png_path}")


if __name__ == "__main__":
    main()
