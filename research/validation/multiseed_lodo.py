"""Sutura held-out MULTI-SEED eval on folds S2 and S3 (error bars on generalization).

The in-sample fold (S1 = 151507/151508) already has 5-seed error bars
(sutura_multiseed_tear.csv). The two held-out donors only had a single warp seed
(seed 0) baked into the lodo_*_test_curve.csv files. This script puts the SAME
5-seed error bars on the held-out folds so the generalization claim carries a CI.

It does NOT retrain. The lodo_*.pt checkpoints store only state_dict + args + pitch
(not the SVD basis), so we deterministically RE-FIT the shared TruncatedSVD basis on
each fold's training slices (random_state = saved seed = 0 -> reproducible) and reuse
train_cross_loo's own build_pair/eval_curve, guaranteeing the features and metric are
bit-identical to how each model was trained and originally evaluated.

Seeds [0, 9999, 10000, 10001, 10002] are disjoint from training's rng.integers(1,9998)
and match the in-sample multi-seed set exactly. Tear regime, full severity grid.

Run: python validation/multiseed_lodo.py
Out: results/sutura_multiseed_lodo.csv
"""
from __future__ import annotations
import sys, csv, argparse
from pathlib import Path
import numpy as np
import torch
import anndata as ad

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from train_cross import ARCACrossNet
from train_cross_loo import (fit_shared_basis, build_pair, eval_curve,
                             parse_pairs, assert_same_genes)

DATA, RESULTS = ROOT / "data", ROOT / "results"
SEEDS = [0, 9999, 10000, 10001, 10002]          # disjoint from training [1,9998]

# (display fold name, held-out donor pair, checkpoint stem)
FOLDS = [
    ("S2", "151669/151670", "lodo_global_heldBr5595"),
    ("S2", "151669/151670", "lodo_perslice_heldBr5595"),
    ("S3", "151673/151674", "lodo_global_heldBr8100"),
    ("S3", "151673/151674", "lodo_perslice_heldBr8100"),
]


def ci95(x):
    x = np.asarray(x, float)
    return 1.96 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0


def load_fold(ckpt_stem):
    """Rebuild the exact (project, test-pair, model) for one trained LODO checkpoint."""
    ck = torch.load(RESULTS / f"{ckpt_stem}.pt", map_location="cpu", weights_only=False)
    a = ck["args"]
    train_pairs = parse_pairs(a["train_pairs"])
    test_ref, test_smp = parse_pairs(a["test_pair"])[0]
    pca_dim, mode, seed, knn = a["pca_dim"], a["feature_mode"], a["seed"], a["knn"]

    train_slices = []
    for ref, smp in train_pairs:
        train_slices.append(ad.read_h5ad(DATA / f"DLPFC_{ref}.h5ad"))
        train_slices.append(ad.read_h5ad(DATA / f"DLPFC_{smp}.h5ad"))
    test_slices = [ad.read_h5ad(DATA / f"DLPFC_{test_ref}.h5ad"),
                   ad.read_h5ad(DATA / f"DLPFC_{test_smp}.h5ad")]
    assert_same_genes(train_slices + test_slices)

    project = fit_shared_basis(train_slices, pca_dim, seed, feature_mode=mode)
    test = build_pair(test_ref, test_smp, project, knn)
    model = ARCACrossNet(pca_dim, a["hidden"], a["layers"], a["attn_dim"])
    model.load_state_dict(ck["state_dict"]); model.eval()
    eval_sev = [float(x) for x in a["eval_severities"].split(",")]
    return model, test, eval_sev, knn, mode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stems", default="",
                    help="comma list of checkpoint stems in results/ to evaluate. "
                         "Each fold's display name, test pair, and feature mode are "
                         "read from the checkpoint's own saved args, so this works "
                         "for any LODO run (e.g. the 2-pair-per-donor stems). "
                         "Default (empty) = the original hardcoded S2/S3 folds.")
    ap.add_argument("--out", default="sutura_multiseed_lodo.csv",
                    help="output CSV name written under results/")
    args = ap.parse_args()

    folds = ([(s.strip(), None, s.strip()) for s in args.stems.split(",") if s.strip()]
             if args.stems else FOLDS)

    out_rows = []
    print("=" * 80)
    print(f"SUTURA held-out MULTI-SEED eval ({len(folds)} checkpoints, tear) — 5 seeds", SEEDS)
    print("=" * 80)
    for fold, pair, stem in folds:
        model, test, eval_sev, knn, mode = load_fold(stem)
        bridge = 100 * test["have"].mean()
        print(f"\n[{fold} / {mode}]  held-out {test['ref']}/{test['smp']} "
              f"(bridge {bridge:.1f}%, pitch {test['pitch']:.1f}px) | ckpt {stem}")
        # per-severity collection of the median across the 5 seeds
        per_sev = {sv: {"median": [], "mean": [], "p90": [], "n": None} for sv in eval_sev}
        for sd in SEEDS:
            rows = eval_curve(model, test, eval_sev, sd, True, knn)
            for r in rows:
                per_sev[r["severity"]]["median"].append(r["reg_err_median"])
                per_sev[r["severity"]]["mean"].append(r["reg_err_mean"])
                per_sev[r["severity"]]["p90"].append(r["reg_err_p90"])
                per_sev[r["severity"]]["n"] = r["n"]
        for sv in eval_sev:
            d = per_sev[sv]
            row = dict(fold=fold, mode=mode, test_pair=f"{test['ref']}/{test['smp']}",
                       severity=sv,
                       median_mean=float(np.mean(d["median"])),
                       median_std=float(np.std(d["median"], ddof=1)),
                       median_ci=float(ci95(d["median"])),
                       mean_mean=float(np.mean(d["mean"])),
                       p90_mean=float(np.mean(d["p90"])),
                       n=d["n"], n_seeds=len(SEEDS))
            out_rows.append(row)
            if sv in (0.0, 4.0, 8.0):
                print(f"   sev{sv:>3.0f}: median {row['median_mean']:7.1f} "
                      f"+/- {row['median_ci']:4.1f} (95%CI)   "
                      f"mean {row['mean_mean']:7.1f}   p90 {row['p90_mean']:7.1f}")

    out_csv = RESULTS / args.out
    with open(out_csv, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        wr.writeheader(); wr.writerows(out_rows)
    print(f"\nwrote {out_csv}  ({len(out_rows)} rows)")


if __name__ == "__main__":
    main()
