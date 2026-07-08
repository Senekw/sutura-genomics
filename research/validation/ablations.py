"""Sutura validation ablations — independent reproduction + decisive tests.

Run with the validation venv:
    python validation/ablations.py

Tests:
 [A] Reproduce the Sutura headline tear curve from arca_cross.pt (sanity: ~99->118px).
 [B] Array-bridge residual at sev0 — how well are the two RAW slices already pixel-
     aligned (i.e. is gt_A ~= B's own coords, making the task warp-inversion?).
 [C] Expression-NN baseline (cross) — for each B spot predict the A-coordinate of its
     nearest A spot in the SHARED SVD feature space. Uses NO warp info and NO training.
     If this ~matches Sutura, the in-sample win is warp-invariant expression matching.
 [D] Geometry-dependence of the trained model — compare predictions on the warped graph
     vs an unwarped graph vs a coordinate-SHUFFLED graph. If error barely moves, the
     model does not really use the (torn) geometry -> "tear robustness" is structural,
     not learned tear handling.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import torch
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anndata as ad
from train_cross import (SuturaCrossNet, cross_features, array_bridge,
                         graph_tensors)
from warp_slice import apply_warp
from scoring import registration_error_stats

DATA = ROOT / "data"
RESULTS = ROOT / "results"
EVAL_SEV = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
KNN = 6
PCA_DIM = 50
SEED = 0


def med(x):
    return float(np.median(x))


def load_pair(ref_id, smp_id):
    A = ad.read_h5ad(DATA / f"DLPFC_{ref_id}.h5ad")
    B = ad.read_h5ad(DATA / f"DLPFC_{smp_id}.h5ad")
    same_genes = A.var_names.equals(B.var_names)
    a_coords = np.asarray(A.obsm["spatial"], np.float32)
    pitch = float(np.median(cKDTree(a_coords).query(a_coords, k=2)[0][:, 1]))
    Z_A, Z_B = cross_features(A, B, PCA_DIM, SEED)
    gt_A, have = array_bridge(A, B)
    return dict(A=A, B=B, a_coords=a_coords, pitch=pitch, Z_A=Z_A, Z_B=Z_B,
                gt_A=gt_A, have=have, same_genes=same_genes)


def arca_curve(P, ckpt_path):
    """[A] Reproduce Sutura tear curve from a checkpoint."""
    model = SuturaCrossNet(PCA_DIM, 64, 3, 64)
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    model.load_state_dict(ck["state_dict"])
    model.eval()
    ga = graph_tensors(P["a_coords"], P["Z_A"], KNN, P["pitch"])
    a_norm = torch.from_numpy(P["a_coords"] / P["pitch"])
    out = []
    preds = {}
    for sv in EVAL_SEV:
        w, _ = apply_warp(P["B"], sv, seed=0, tear=True)
        gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                           P["Z_B"], KNN, P["pitch"])
        with torch.no_grad():
            pred = model(ga, gb, a_norm).numpy() * P["pitch"]
        preds[sv] = pred
        st = registration_error_stats(pred, P["gt_A"], mask=P["have"])
        out.append((sv, st["median"], st["mean"], st["p90"]))
    return out, model, ga, a_norm, preds


def bridge_residual(P):
    """[B] How far is each B spot's OWN raw coordinate from its array-bridge GT
    target in A? Small => the two raw slices are already pixel-aligned => the
    'predict A-frame coord' task reduces to undoing the warp."""
    b_own = np.asarray(P["B"].obsm["spatial"], np.float32)
    st = registration_error_stats(b_own, P["gt_A"], mask=P["have"])
    return st


def expression_nn_baseline(P):
    """[C] Predict, for each B spot, the A coordinate of its nearest A spot in the
    shared SVD feature space. No warp info, no training. Constant across severity."""
    tree = cKDTree(P["Z_A"])
    _, nn = tree.query(P["Z_B"], k=1)
    pred = P["a_coords"][nn]
    st = registration_error_stats(pred, P["gt_A"], mask=P["have"])
    # also k=10 barycentric (soft) version
    dist, nn10 = tree.query(P["Z_B"], k=10)
    w = 1.0 / (dist + 1e-6)
    w /= w.sum(1, keepdims=True)
    pred10 = (P["a_coords"][nn10] * w[:, :, None]).sum(1)
    st10 = registration_error_stats(pred10, P["gt_A"], mask=P["have"])
    return st, st10


def geometry_ablation(P, model, ga, a_norm):
    """[D] Does the trained model use B's (torn) geometry at all?
    Compare predictions with: warped graph (sev8 tear), unwarped graph (sev0),
    and a coordinate-SHUFFLED graph (geometry destroyed, expression intact)."""
    rng = np.random.default_rng(0)
    # warped sev8 tear
    w8, _ = apply_warp(P["B"], 8.0, seed=0, tear=True)
    c8 = np.asarray(w8.obsm["spatial"], np.float32)
    gb8 = graph_tensors(c8, P["Z_B"], KNN, P["pitch"])
    # unwarped (sev0, no tear) == raw B coords
    c0 = np.asarray(P["B"].obsm["spatial"], np.float32)
    gb0 = graph_tensors(c0, P["Z_B"], KNN, P["pitch"])
    # shuffled coords (destroy all geometry), keep Z_B
    cs = c8[rng.permutation(c8.shape[0])]
    gbs = graph_tensors(cs, P["Z_B"], KNN, P["pitch"])
    res = {}
    for name, gb in [("warp_sev8", gb8), ("unwarped", gb0), ("shuffled_geom", gbs)]:
        with torch.no_grad():
            pred = model(ga, gb, a_norm).numpy() * P["pitch"]
        st = registration_error_stats(pred, P["gt_A"], mask=P["have"])
        res[name] = (pred, st)
    # how different are predictions when geometry changes?
    p8 = res["warp_sev8"][0][P["have"]]
    p0 = res["unwarped"][0][P["have"]]
    ps = res["shuffled_geom"][0][P["have"]]
    d_warp = med(np.linalg.norm(p8 - p0, axis=1))      # warp vs unwarp pred shift
    d_shuf = med(np.linalg.norm(p8 - ps, axis=1))      # warp vs shuffled pred shift
    return res, d_warp, d_shuf


def main():
    print("=" * 72)
    print("Sutura VALIDATION ABLATIONS — independent reproduction")
    print("=" * 72)
    P = load_pair("151507", "151508")
    print(f"pair 151507/151508 | A {P['A'].n_obs} spots, B {P['B'].n_obs} spots | "
          f"pitch {P['pitch']:.1f}px | bridge {100*P['have'].mean():.1f}% | "
          f"same_genes={P['same_genes']}")

    print("\n[A] Reproduce Sutura headline tear curve from arca_cross.pt")
    print("    sev | median  mean   p90   (px)")
    curve, model, ga, a_norm, preds = arca_curve(P, RESULTS / "arca_cross.pt")
    for sv, m, mn, p9 in curve:
        print(f"    {sv:>3.0f} | {m:6.1f} {mn:6.1f} {p9:7.1f}")
    print(f"    -> sev0 median {curve[0][1]:.1f}px, sev8 median {curve[-1][1]:.1f}px "
          f"(brief claims 99 -> 118)")

    print("\n[B] Array-bridge residual (raw B own coords vs bridge GT) — slice-to-slice")
    st = bridge_residual(P)
    print(f"    median {st['median']:.1f}px  mean {st['mean']:.1f}px  p90 {st['p90']:.1f}px "
          f"({st['median']/P['pitch']:.2f} pitches)")
    print("    -> if small, gt_A ~= B's own coords, so 'predict A-frame' == undo the warp")

    print("\n[C] Expression-NN baseline (NO training, NO warp info)")
    st1, st10 = expression_nn_baseline(P)
    print(f"    1-NN   : median {st1['median']:.1f}px  mean {st1['mean']:.1f}px  "
          f"p90 {st1['p90']:.1f}px")
    print(f"    10-NN  : median {st10['median']:.1f}px  mean {st10['mean']:.1f}px  "
          f"p90 {st10['p90']:.1f}px")
    print("    -> constant across ALL severities (Z is warp-invariant). Compare to Sutura.")

    print("\n[D] Geometry-dependence of the trained Sutura model")
    res, d_warp, d_shuf = geometry_ablation(P, model, ga, a_norm)
    for name in ["unwarped", "warp_sev8", "shuffled_geom"]:
        s = res[name][1]
        print(f"    {name:14s}: reg-err median {s['median']:6.1f}px  mean {s['mean']:6.1f}px")
    print(f"    pred shift warp_sev8 vs unwarped : median {d_warp:.1f}px")
    print(f"    pred shift warp_sev8 vs SHUFFLED : median {d_shuf:.1f}px")
    print("    -> if reg-err on shuffled_geom stays low, model ignores B geometry")
    print("=" * 72)


if __name__ == "__main__":
    main()
