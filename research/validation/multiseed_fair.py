"""Item 1 (multi-seed CIs) + Item 2 (same-estimator fair comparison) for Sutura.

Run: python validation/multiseed_fair.py

Item 1 — multi-seed eval of the trained checkpoint over 5 warp seeds DISJOINT from
training (training drew rng.integers(1,9999) -> [1,9998]; we use 0,9999,10000,10001,
10002). Gives per-severity median/mean/p90 as mean +/- std (and a 95% normal CI) so the
headline curve has error bars.

Item 2 — fair head-to-head estimator. PASTE2's 658->838 px is a barycentric (soft) plan
projection; its hard-correspondence (argmax) number is 728->863. Sutura regresses a
coordinate, so we add a HARD version: snap each Sutura prediction to its nearest A spot.
That makes both methods 'pick one A spot per B spot' -> like-for-like.
"""
from __future__ import annotations
import sys, csv
from pathlib import Path
import numpy as np
import torch
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import anndata as ad
from train_cross import SuturaCrossNet, cross_features, array_bridge, graph_tensors
from warp_slice import apply_warp
from scoring import registration_error_stats

DATA, RESULTS = ROOT / "data", ROOT / "results"
EVAL_SEV = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
SEEDS = [0, 9999, 10000, 10001, 10002]   # all disjoint from training's [1,9998]
KNN, PCA_DIM, FEAT_SEED = 6, 50, 0


def load_model_and_pair(ref_id, smp_id, ckpt):
    A = ad.read_h5ad(DATA / f"DLPFC_{ref_id}.h5ad")
    B = ad.read_h5ad(DATA / f"DLPFC_{smp_id}.h5ad")
    a_coords = np.asarray(A.obsm["spatial"], np.float32)
    pitch = float(np.median(cKDTree(a_coords).query(a_coords, k=2)[0][:, 1]))
    Z_A, Z_B = cross_features(A, B, PCA_DIM, FEAT_SEED)
    gt_A, have = array_bridge(A, B)
    model = SuturaCrossNet(PCA_DIM, 64, 3, 64)
    ck = torch.load(ckpt, map_location="cpu", weights_only=False)
    model.load_state_dict(ck["state_dict"]); model.eval()
    ga = graph_tensors(a_coords, Z_A, KNN, pitch)
    a_norm = torch.from_numpy(a_coords / pitch)
    atree = cKDTree(a_coords)
    return dict(A=A, B=B, a_coords=a_coords, pitch=pitch, Z_B=Z_B, gt_A=gt_A,
                have=have, model=model, ga=ga, a_norm=a_norm, atree=atree)


def predict(P, sev, seed):
    w, _ = apply_warp(P["B"], sev, seed=seed, tear=True)
    gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32), P["Z_B"], KNN, P["pitch"])
    with torch.no_grad():
        return P["model"](P["ga"], gb, P["a_norm"]).numpy() * P["pitch"]


def ci95(x):
    x = np.asarray(x, float)
    return 1.96 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0


def main():
    P = load_model_and_pair("151507", "151508", RESULTS / "arca_cross.pt")
    print("=" * 78)
    print("ITEM 1 — Sutura multi-seed eval (in-sample 151507/151508, tear), 5 seeds")
    print(f"  seeds {SEEDS} (disjoint from training [1,9998]) | bridge {100*P['have'].mean():.1f}%")
    print("=" * 78)
    # collect soft (direct regression) medians per (sev, seed)
    rows = []
    for sev in EVAL_SEV:
        meds, means, p90s, snap_meds = [], [], [], []
        for sd in SEEDS:
            pred = predict(P, sev, sd)
            st = registration_error_stats(pred, P["gt_A"], mask=P["have"])
            meds.append(st["median"]); means.append(st["mean"]); p90s.append(st["p90"])
            # Item 2: snap to nearest A spot (hard correspondence)
            _, nn = P["atree"].query(pred, k=1)
            snapped = P["a_coords"][nn]
            sst = registration_error_stats(snapped, P["gt_A"], mask=P["have"])
            snap_meds.append(sst["median"])
        rows.append(dict(severity=sev,
            median_mean=np.mean(meds), median_std=np.std(meds, ddof=1), median_ci=ci95(meds),
            mean_mean=np.mean(means), p90_mean=np.mean(p90s),
            snap_median_mean=np.mean(snap_meds), snap_median_ci=ci95(snap_meds)))
    print("\n  DIRECT regression error (px), median across 5 seeds:")
    print("  sev |  median (mean +/- 95%CI)   |  mean   |  p90")
    for r in rows:
        print(f"  {r['severity']:>3.0f} | {r['median_mean']:6.1f} +/- {r['median_ci']:4.1f}"
              f"            | {r['mean_mean']:6.1f} | {r['p90_mean']:7.1f}")

    print("\n" + "=" * 78)
    print("ITEM 2 — FAIR same-estimator (hard correspondence: pick one A spot per B spot)")
    print("=" * 78)
    print("  sev | Sutura snapped-to-nearest-A (median px, 5-seed) | PASTE2 argmax (CSV)")
    # PASTE2 argmax in-sample only has sev0/sev8 in sweep_deformation_argmax_tear.csv
    paste_argmax = {0.0: 728.6, 8.0: 863.1}
    for r in rows:
        pa = paste_argmax.get(r['severity'], None)
        pa_s = f"{pa:.0f}" if pa else "  -"
        print(f"  {r['severity']:>3.0f} | {r['snap_median_mean']:6.1f} +/- {r['snap_median_ci']:4.1f}"
              f"                          | {pa_s}")
    print("\n  -> Both columns are now 'one A spot per B spot'. PASTE2 argmax in-sample = 728->863 px;")
    print("     held-out PASTE2 argmax = 600->730 px (sweep_deformation_cross_tear_loo.csv).")

    # persist
    with open(RESULTS / "sutura_multiseed_tear.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
    print(f"\nwrote {RESULTS/'sutura_multiseed_tear.csv'}")


if __name__ == "__main__":
    main()
