"""
ARCA baseline — PASTE2 partial alignment + layer-label transfer accuracy.

Aligns two adjacent DLPFC slices with PASTE2's partial fused Gromov-Wasserstein
solver, then evaluates the alignment by label transfer: map each spot in slice A
to its highest-probability partner in slice B (argmax over the transport matrix
row) and report the fraction whose manual cortical-layer label (obs["layer"])
matches. That fraction is the OT baseline ARCA must beat on warped/torn tissue.

The transport matrix is saved to results/.

Usage:
    python src/baseline_paste.py
    python src/baseline_paste.py --s 0.7 --dissimilarity pca
    python src/baseline_paste.py --subsample 300        # fast pipeline check
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import anndata as ad
import numpy as np

from paste2.PASTE2 import partial_pairwise_align
from paste2.helper import filter_for_common_genes

from scoring import print_report, report

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

DEFAULT_A = "151507"
DEFAULT_B = "151508"


def load_slice(sample_id: str) -> ad.AnnData:
    path = DATA_DIR / f"DLPFC_{sample_id}.h5ad"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run src/prepare_data.py first."
        )
    return ad.read_h5ad(path)


def subsample(adata: ad.AnnData, n: int, seed: int = 0) -> ad.AnnData:
    if n >= adata.n_obs:
        return adata
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(adata.n_obs, size=n, replace=False))
    return adata[idx].copy()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sample-a", default=DEFAULT_A)
    p.add_argument("--sample-b", default=DEFAULT_B)
    p.add_argument("--s", type=float, default=0.99,
                   help="overlap fraction. 0.99 ~ full overlap (adjacent "
                        "sections); the 1%% slack keeps partial-OT feasible "
                        "(m<=min(|p|,|q|); s=1.0 trips a float-rounding "
                        "infeasibility). Lower it for partial/torn tissue.")
    p.add_argument("--alpha", type=float, default=0.1,
                   help="FGW trade-off between expression and spatial geometry")
    p.add_argument("--dissimilarity", default="glmpca",
                   choices=["glmpca", "pca", "kl", "euclidean"])
    p.add_argument("--subsample", type=int, default=0,
                   help="if >0, randomly subsample this many spots per slice "
                        "(fast pipeline check, not a real baseline)")
    args = p.parse_args()

    print("=" * 64)
    print(f"ARCA baseline — PASTE2 partial alignment")
    print(f"  pair          : {args.sample_a} -> {args.sample_b}")
    print(f"  overlap s     : {args.s}")
    print(f"  alpha         : {args.alpha}")
    print(f"  dissimilarity : {args.dissimilarity}")
    if args.subsample:
        print(f"  subsample     : {args.subsample} spots/slice (SMOKE TEST)")
    print("=" * 64)

    A = load_slice(args.sample_a)
    B = load_slice(args.sample_b)
    if args.subsample:
        A = subsample(A, args.subsample, seed=0)
        B = subsample(B, args.subsample, seed=1)

    filter_for_common_genes([A, B])
    print(f"common genes    : {A.n_vars}")
    print(f"A: {A.n_obs} spots | B: {B.n_obs} spots")

    layer_a = A.obs["layer"].astype(str).values
    layer_b = B.obs["layer"].astype(str).values

    print("\nrunning partial_pairwise_align ...")
    t0 = time.time()
    pi = partial_pairwise_align(
        A, B, s=args.s, alpha=args.alpha,
        dissimilarity=args.dissimilarity, verbose=True,
    )
    pi = np.asarray(pi)
    dt = time.time() - t0
    print(f"\nalignment done in {dt:.1f}s — transport matrix {pi.shape}")
    print(f"transported mass: {pi.sum():.4f}  (rows>0: "
          f"{int((pi.sum(axis=1) > 0).sum())}/{pi.shape[0]})")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{args.sample_a}_to_{args.sample_b}"
    if args.subsample:
        tag += f"_sub{args.subsample}"
    npy_path = RESULTS_DIR / f"paste2_transport_{tag}.npy"
    np.save(npy_path, pi)
    # companion metadata for reproducible scoring
    np.savez_compressed(
        RESULTS_DIR / f"paste2_transport_{tag}_meta.npz",
        obs_names_a=A.obs_names.to_numpy(),
        obs_names_b=B.obs_names.to_numpy(),
        layer_a=layer_a, layer_b=layer_b,
        s=args.s, alpha=args.alpha, dissimilarity=args.dissimilarity,
    )
    print(f"saved transport matrix -> {npy_path}")

    print()
    rep = report(pi, layer_a, layer_b)
    print_report(rep, header="BASELINE — PASTE2 layer-label transfer accuracy")
    mo, fl = rep["model"], rep["random_floor"]

    summary = RESULTS_DIR / f"paste2_baseline_{tag}.txt"
    summary.write_text(
        f"PASTE2 baseline {args.sample_a}->{args.sample_b}\n"
        f"s={args.s} alpha={args.alpha} dissimilarity={args.dissimilarity} "
        f"subsample={args.subsample}\n"
        f"runtime_s={dt:.1f}\n"
        f"paste2_accuracy={mo['accuracy']:.4f} "
        f"({mo['n_correct']}/{mo['n_scored']})\n"
        f"random_floor={fl['accuracy_mean']:.4f} +/- {fl['accuracy_std']:.4f} "
        f"({fl['n_trials']} trials)\n"
        f"masked_a_na={mo['n_dropped_a_na']} "
        f"masked_partner_na={mo['n_dropped_partner_na']}\n"
    )
    print(f"wrote summary -> {summary}")


if __name__ == "__main__":
    main()
