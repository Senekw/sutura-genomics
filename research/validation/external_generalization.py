"""Zero-shot external-generalization test for the pretrained Sutura checkpoint.

Diagnostic: how far does Sutura (trained ONLY on DLPFC 151507/151508) generalize
to an external tissue it never saw, under our standard synthetic-tear benchmark?

Methodology (identical metric to our main benchmark, self-consistency mode):
  * Take one real external Visium section as the reference A.
  * For each severity s in 0..8 and each seed, warp a copy B with our standard
    Gaussian-bump + tear field (src/warp_slice.apply_warp, tear=True). The warp
    stores each spot's ORIGINAL coordinate, giving exact ground truth.
  * Sutura (zero-shot, arca_cross.pt, no retraining): predict each B spot's
    coordinate in A's frame; error = ||pred - original||, median in px.
  * PASTE2 baseline on the same torn pair: partial OT plan -> barycentric
    projection into A's frame; error = ||pred - original||, median in px.

Why self-consistency and not a cross-section bridge: our DLPFC ground truth uses
the shared Visium array frame across adjacent slices (array_bridge). Two
independently captured external sections do NOT share an array frame, so there is
no exact cross-section correspondence to score against. The synthetic-tear self
benchmark is the same protocol our main 'self' benchmark uses and yields exact GT
on any single section. (Section 2 is downloaded too, but only S1 is scored.)

Run (smoke first): ... external_generalization.py --smoke
Full grid:         ... external_generalization.py
"""
from __future__ import annotations
import argparse, csv, sys, time
from pathlib import Path

import numpy as np
import anndata as ad
import scanpy as sc
import torch
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from train_cross import ARCACrossNet, cross_features, graph_tensors  # noqa: E402
from warp_slice import apply_warp  # noqa: E402
from scoring import barycentric_projection, registration_error_stats  # noqa: E402
from paste2.PASTE2 import partial_pairwise_align  # noqa: E402
from paste2.helper import filter_for_common_genes  # noqa: E402

DATA = ROOT / "data" / "external"
RESULTS = ROOT / "results"
CKPT = RESULTS / "arca_cross.pt"
KNN, PCA_DIM, FEAT_SEED = 6, 50, 0

SEVERITIES = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
SEEDS = [0, 9999, 10000]  # disjoint from training's [1, 9998]


def load_section(tag, max_spots, seed=0):
    a = ad.read_h5ad(DATA / f"{tag}.h5ad")
    a.var_names_make_unique()
    sc.pp.filter_genes(a, min_cells=3)  # drop all-zero genes (faster SVD/PASTE2)
    if max_spots and a.n_obs > max_spots:
        rng = np.random.default_rng(seed)
        keep = np.sort(rng.choice(a.n_obs, max_spots, replace=False))
        a = a[keep].copy()
    return a


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="breast_A_S1")
    p.add_argument("--dataset-name", default="Breast_Cancer_Block_A_S1")
    p.add_argument("--max-spots", type=int, default=1200,
                   help="subsample spots to keep PASTE2 tractable (0 = all)")
    p.add_argument("--dissimilarity", default="pca",
                   choices=["glmpca", "pca", "kl", "euclidean"])
    p.add_argument("--s", type=float, default=0.99)
    p.add_argument("--alpha", type=float, default=0.1)
    p.add_argument("--smoke", action="store_true",
                   help="single (sev=4, seed=0) run to validate + time")
    p.add_argument("--out", default=str(RESULTS / "external_generalization.csv"))
    args = p.parse_args()

    A = load_section(args.dataset, args.max_spots)
    B = A.copy()  # self-consistency: moving section is a warped copy of A
    a_coords = np.asarray(A.obsm["spatial"], np.float32)
    pitch = float(np.median(cKDTree(a_coords).query(a_coords, k=2)[0][:, 1]))
    gt = a_coords.astype(float)                 # exact GT (original coordinates)
    have = np.ones(A.n_obs, bool)

    Z_A, Z_B = cross_features(A, B, PCA_DIM, FEAT_SEED)
    model = ARCACrossNet(PCA_DIM, 64, 3, 64)
    ck = torch.load(CKPT, map_location="cpu", weights_only=False)
    model.load_state_dict(ck["state_dict"]); model.eval()
    ga = graph_tensors(a_coords, Z_A, KNN, pitch)
    a_norm = torch.from_numpy(a_coords / pitch)

    print("=" * 74)
    print(f"ZERO-SHOT external generalization — {args.dataset_name}")
    print(f"  spots={A.n_obs}  genes={A.n_vars}  pitch={pitch:.1f}px  "
          f"diss={args.dissimilarity}  checkpoint={CKPT.name} (no retraining)")
    print("=" * 74)

    sevs = [4.0] if args.smoke else SEVERITIES
    seeds = [0] if args.smoke else SEEDS
    rows = []
    for sev in sevs:
        for sd in seeds:
            w, _ = apply_warp(B, sev, seed=sd, tear=True)
            wc = np.asarray(w.obsm["spatial"], np.float32)

            # --- No-op reference: leave B spots at their warped positions ---
            med_noop = registration_error_stats(wc, gt, mask=have)["median"]

            # --- Sutura (zero-shot) ---
            t0 = time.time()
            gb = graph_tensors(wc, Z_B, KNN, pitch)
            with torch.no_grad():
                pred = model(ga, gb, a_norm).numpy() * pitch
            med_s = registration_error_stats(pred, gt, mask=have)["median"]
            t_s = time.time() - t0

            # --- PASTE2 baseline (same torn pair) ---
            t0 = time.time()
            Aa, Bb = A.copy(), w.copy()
            filter_for_common_genes([Aa, Bb])
            pi = np.asarray(partial_pairwise_align(
                Aa, Bb, s=args.s, alpha=args.alpha,
                dissimilarity=args.dissimilarity, verbose=False))
            pred_b, col_mass = barycentric_projection(pi, a_coords)
            med_p = registration_error_stats(
                pred_b, gt, mask=(col_mass > 0))["median"]
            t_p = time.time() - t0

            rows.append(dict(dataset=args.dataset_name, severity=sev,
                             method="Sutura", median_error=round(med_s, 2), seed=sd))
            rows.append(dict(dataset=args.dataset_name, severity=sev,
                             method="PASTE2", median_error=round(med_p, 2), seed=sd))
            rows.append(dict(dataset=args.dataset_name, severity=sev,
                             method="No-op (unaligned)", median_error=round(med_noop, 2), seed=sd))
            print(f"  sev={sev:>4} seed={sd:<6} | Sutura {med_s:8.1f}px ({t_s:4.1f}s)"
                  f" | PASTE2 {med_p:8.1f}px ({t_p:5.1f}s) | no-op {med_noop:8.1f}px")

    if not args.smoke:
        RESULTS.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=["dataset", "severity", "method",
                                                "median_error", "seed"])
            wr.writeheader(); wr.writerows(rows)
        print(f"\nwrote {args.out}  ({len(rows)} rows)")


if __name__ == "__main__":
    main()
