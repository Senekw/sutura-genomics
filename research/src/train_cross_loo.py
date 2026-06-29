"""
Sutura — leave-one-out CROSS-SAMPLE generalization test.

Addresses caveat #2 of the head-to-head (RESUME.md): the original arca_cross was
trained AND evaluated on the SAME 151507/151508 tissue (only warp seeds held out),
so it proved Sutura learns *that pair's* deformation distribution — not that it
generalizes to unseen tissue. This script trains on one set of donor pairs and
evaluates on a DIFFERENT, held-out donor pair (no tissue overlap), so the curve
reported on the held-out pair is a true cross-sample generalization result.

Default split (single held-out pair, leave-one-donor-out):
    train = 151507/151508   (subject 1)
    test  = 151669/151670   (subject 2, never seen during training)

Two things make cross-tissue eval valid where the per-pair model did not:
  1. TRANSFERABLE FEATURES. The original cross_features fit a fresh TruncatedSVD
     per pair; SVD components have arbitrary sign/rotation per fit, so an encoder
     trained on one basis sees garbage on another. Here we fit ONE SVD basis on
     the TRAINING slices only, then .transform every slice (train AND held-out)
     into that same basis. The held-out tissue never touches the basis fit, so
     "model never saw the test tissue" holds for features too, not just weights.
  2. PAIR-AGNOSTIC INFERENCE. SuturaCrossNet's coarse coordinate is attn @ A_coords
     in whatever A frame you pass in, and the encoder is shared — so a model
     trained on pair P predicts in pair Q's A frame with no per-pair parameters.

Supervision & metric are IDENTICAL to train_cross.py: loss = ||pred_A - gt_A|| in
pitch units over array-bridge-matched B spots; eval = registration_error_stats vs
the array-bridge GT in the test pair's own pixel frame. So the held-out curve is
directly comparable to arca_cross_curve.csv (in-sample) and to PASTE2 on the same
held-out pair (run separately; PASTE2 is unsupervised so it has no train/test gap).

Outputs (results/):
    <out>_test_curve.csv   held-out pair, severity sweep (the generalization result)
    <out>_train_curve.csv  training pair, held-out warp seeds (in-sample reference)
    <out>.pt               checkpoint (state_dict + args + per-pair pitch)

Usage:
    python src/train_cross_loo.py            # design summary only (no training)
    python src/train_cross_loo.py --train    # run the LOO train+eval
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import anndata as ad
import numpy as np
import torch
from scipy.sparse import issparse, vstack as svstack
from scipy.spatial import cKDTree
from sklearn.decomposition import TruncatedSVD

from train_cross import SuturaCrossNet, _lognorm, array_bridge, graph_tensors
from warp_slice import apply_warp
from scoring import registration_error_stats

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"


# --------------------------------------------------------------------------- #
# shared, transferable feature basis (fit on TRAINING slices only)
# --------------------------------------------------------------------------- #
def fit_shared_basis(train_slices, dim, seed, feature_mode="global"):
    """Fit ONE TruncatedSVD basis on the lognorm expression of the training
    slices stacked together. Returns a closure that projects any slice (with the
    same gene set) into this fixed basis.

    feature_mode controls how the 50-dim SVD embedding is standardized — the
    knob that decides whether a held-out DONOR's features land in-distribution:
      "global"   — standardize by the TRAINING slices' pooled mean/std. A held-out
                   donor with a batch shift then projects OFF-distribution (this is
                   the diagnosed failure mode of the single-donor LOO run).
      "perslice" — standardize EACH slice by ITS OWN mean/std over spots. Every
                   slice's feature cloud is re-centered to zero-mean/unit-var
                   regardless of donor, a cheap, memory-safe batch correction in
                   embedding space that keeps an unseen donor in-distribution.
    """
    mats = [_lognorm(a) for a in train_slices]
    stacked = svstack(mats) if issparse(mats[0]) else np.vstack(mats)
    svd = TruncatedSVD(n_components=dim, random_state=seed).fit(stacked)
    Ztr = svd.transform(stacked)
    mu, sd = Ztr.mean(0), Ztr.std(0) + 1e-6

    def project(adata):
        Z = svd.transform(_lognorm(adata)).astype(np.float32)
        if feature_mode == "perslice":
            m, s = Z.mean(0), Z.std(0) + 1e-6          # this slice's own stats
            return ((Z - m) / s).astype(np.float32)
        return ((Z - mu) / sd).astype(np.float32)      # pooled training stats

    return project


# --------------------------------------------------------------------------- #
# per-pair instance
# --------------------------------------------------------------------------- #
def build_pair(ref_id, smp_id, project, knn):
    """Load a donor pair and assemble everything the model needs for it.

    project() must already be fit (on the training slices) so features are in the
    shared basis. var_names must match the basis's slices (asserted)."""
    A = ad.read_h5ad(DATA_DIR / f"DLPFC_{ref_id}.h5ad")
    B = ad.read_h5ad(DATA_DIR / f"DLPFC_{smp_id}.h5ad")
    a_coords = np.asarray(A.obsm["spatial"], np.float32)
    pitch = float(np.median(cKDTree(a_coords).query(a_coords, k=2)[0][:, 1]))

    Z_A, Z_B = project(A), project(B)
    gt_A, have = array_bridge(A, B)
    ga = graph_tensors(a_coords, Z_A, knn, pitch)
    return {
        "ref": ref_id, "smp": smp_id, "A": A, "B": B,
        "a_coords": a_coords, "pitch": pitch, "Z_B": Z_B,
        "gt_A": gt_A, "have": have, "ga": ga,
        "a_norm": torch.from_numpy(a_coords / pitch),
        "gt_norm": torch.from_numpy(gt_A / pitch),
        "mask": torch.from_numpy(have),
    }


def assert_same_genes(slices):
    """All slices must share var_names in identical order (shared SVD basis)."""
    ref = slices[0].var_names
    for s in slices[1:]:
        if not s.var_names.equals(ref):
            raise ValueError(
                f"gene set mismatch: {s.obs['sample_id'].iloc[0]} var_names differ "
                "from the training reference; shared SVD basis would be invalid.")


def warp_graph(pair, sev, seed, tear, knn):
    """Warp pair's B at (sev, seed, tear) and return its input graph tensors."""
    w, _ = apply_warp(pair["B"], sev, seed=seed, tear=tear)
    return graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                         pair["Z_B"], knn, pair["pitch"])


def eval_curve(model, pair, severities, seed, tear, knn):
    """Severity sweep on one pair; returns list of stat rows (px, pair's frame)."""
    model.eval()
    rows = []
    for sv in severities:
        gb = warp_graph(pair, sv, seed, tear, knn)
        with torch.no_grad():
            pred = model(pair["ga"], gb, pair["a_norm"]).numpy() * pair["pitch"]
        st = registration_error_stats(pred, pair["gt_A"], mask=pair["have"])
        rows.append({"severity": sv, "reg_err_median": st["median"],
                     "reg_err_mean": st["mean"], "reg_err_p90": st["p90"],
                     "n": st["n"]})
    return rows


def write_curve(path, rows):
    with open(path, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader(); wr.writerows(rows)


# --------------------------------------------------------------------------- #
def parse_pairs(spec):
    """'151507/151508,151509/151510' -> [('151507','151508'),(...)]"""
    out = []
    for chunk in spec.split(","):
        ref, smp = chunk.split("/")
        out.append((ref.strip(), smp.strip()))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--train-pairs", default="151507/151508",
                   help="comma list of ref/sample donor pairs to TRAIN on")
    p.add_argument("--test-pair", default="151669/151670",
                   help="held-out ref/sample pair to EVALUATE on (unseen tissue)")
    p.add_argument("--hidden", type=int, default=64)
    p.add_argument("--layers", type=int, default=3)
    p.add_argument("--attn-dim", type=int, default=64)
    p.add_argument("--knn", type=int, default=6)
    p.add_argument("--pca-dim", type=int, default=50)
    p.add_argument("--feature-mode", choices=["global", "perslice"],
                   default="global",
                   help="SVD-embedding standardization: 'global' (training pooled "
                        "stats) or 'perslice' (per-slice, batch-robust for unseen "
                        "donors)")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--steps-per-epoch", type=int, default=12)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--max-severity", type=float, default=8.0)
    p.add_argument("--tear-prob", type=float, default=0.5)
    p.add_argument("--eval-severities", default="0,1,2,3,4,6,8")
    p.add_argument("--eval-seed", type=int, default=0,
                   help="fixed seed for ALL eval warps (matches the PASTE2 sweep)")
    p.add_argument("--eval-mode", choices=["tear", "smooth"], default="tear")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="arca_loo")
    p.add_argument("--train", action="store_true",
                   help="run training+eval (default: design summary only)")
    args = p.parse_args()

    train_pairs = parse_pairs(args.train_pairs)
    test_ref, test_smp = parse_pairs(args.test_pair)[0]

    # --- load every slice once, fit the shared basis on TRAINING slices only ---
    train_slices = []
    for ref, smp in train_pairs:
        train_slices.append(ad.read_h5ad(DATA_DIR / f"DLPFC_{ref}.h5ad"))
        train_slices.append(ad.read_h5ad(DATA_DIR / f"DLPFC_{smp}.h5ad"))
    test_slices = [ad.read_h5ad(DATA_DIR / f"DLPFC_{test_ref}.h5ad"),
                   ad.read_h5ad(DATA_DIR / f"DLPFC_{test_smp}.h5ad")]
    assert_same_genes(train_slices + test_slices)

    project = fit_shared_basis(train_slices, args.pca_dim, args.seed,
                               feature_mode=args.feature_mode)

    pairs = [build_pair(ref, smp, project, args.knn) for ref, smp in train_pairs]
    test = build_pair(test_ref, test_smp, project, args.knn)

    model = SuturaCrossNet(args.pca_dim, args.hidden, args.layers, args.attn_dim)
    n_params = sum(q.numel() for q in model.parameters())

    print("=" * 70)
    print("Sutura leave-one-out CROSS-SAMPLE generalization — design summary")
    print("=" * 70)
    print(f"  feature basis : shared TruncatedSVD dim={args.pca_dim}, "
          f"fit on {len(train_slices)} TRAINING slices only "
          f"(standardize={args.feature_mode})")
    for pr in pairs:
        print(f"  train pair    : {pr['ref']}/{pr['smp']}  "
              f"(A {pr['A'].n_obs} spots, bridge {100*pr['have'].mean():.1f}%, "
              f"pitch {pr['pitch']:.1f}px)")
    print(f"  TEST pair     : {test['ref']}/{test['smp']}  "
          f"(A {test['A'].n_obs} spots, bridge {100*test['have'].mean():.1f}%, "
          f"pitch {test['pitch']:.1f}px)  <- HELD OUT, unseen donor")
    print(f"  encoder       : shared, {args.layers} DeformConv layers, "
          f"hidden={args.hidden}, params={n_params}")
    print(f"  eval grid     : sev {args.eval_severities} ({args.eval_mode}), "
          f"seed {args.eval_seed} (matches PASTE2 sweep)")
    print("=" * 70)

    if not args.train:
        # forward-pass shape check on the HELD-OUT pair (the real generalization
        # path): trained-elsewhere features must flow through to an unseen frame.
        gb = warp_graph(test, 4.0, seed=1, tear=True, knn=args.knn)
        with torch.no_grad():
            pred = model(test["ga"], gb, test["a_norm"])
        print(f"forward-pass check on held-out {test['ref']}/{test['smp']} OK: "
              f"pred {tuple(pred.shape)} (expected ({test['B'].n_obs}, 2))")
        print("Run with --train to start the LOO train+eval.")
        return

    # ---- training (shared encoder over the training pairs) ----
    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    eval_tear = (args.eval_mode == "tear")
    eval_sev = [float(x) for x in args.eval_severities.split(",")]

    for epoch in range(args.epochs):
        model.train()
        tot = 0.0
        for _ in range(args.steps_per_epoch):
            pr = pairs[int(rng.integers(0, len(pairs)))]      # sample a train pair
            sv = float(rng.uniform(0, args.max_severity))
            gb = warp_graph(pr, sv, seed=int(rng.integers(1, 9999)),
                            tear=bool(rng.random() < args.tear_prob), knn=args.knn)
            opt.zero_grad()
            pred = model(pr["ga"], gb, pr["a_norm"])
            loss = (pred - pr["gt_norm"])[pr["mask"]].norm(dim=1).mean()
            loss.backward()
            opt.step()
            tot += loss.item()
        if epoch % 10 == 0 or epoch == args.epochs - 1:
            # report held-out median at the extremes so we can watch generalization
            te = eval_curve(model, test, [eval_sev[0], eval_sev[-1]],
                            args.eval_seed, eval_tear, args.knn)
            cells = "  ".join(f"sev{r['severity']:g}:{r['reg_err_median']:5.0f}px"
                              for r in te)
            print(f"  epoch {epoch:3d} | L={tot/args.steps_per_epoch:.3f} | "
                  f"HELD-OUT {test['ref']}/{test['smp']}  {cells}")

    # ---- final curves: held-out (generalization) + training (in-sample) ----
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    test_rows = eval_curve(model, test, eval_sev, args.eval_seed, eval_tear, args.knn)
    train_rows = eval_curve(model, pairs[0], eval_sev, args.eval_seed,
                            eval_tear, args.knn)
    write_curve(RESULTS_DIR / f"{args.out}_test_curve.csv", test_rows)
    write_curve(RESULTS_DIR / f"{args.out}_train_curve.csv", train_rows)
    torch.save({"state_dict": model.state_dict(), "args": vars(args),
                "pitch": {f"{pr['ref']}/{pr['smp']}": pr["pitch"] for pr in pairs}
                | {f"{test['ref']}/{test['smp']}": test["pitch"]}},
               RESULTS_DIR / f"{args.out}.pt")

    print("\nHELD-OUT generalization curve (px median, tear regime):")
    for r in test_rows:
        print(f"  sev{r['severity']:g}: median {r['reg_err_median']:6.1f}  "
              f"mean {r['reg_err_mean']:6.1f}  p90 {r['reg_err_p90']:7.1f}  "
              f"(n={r['n']})")
    print(f"\nwrote {args.out}_test_curve.csv, {args.out}_train_curve.csv, "
          f"{args.out}.pt")


if __name__ == "__main__":
    main()
