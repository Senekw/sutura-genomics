"""
ARCA — leave-one-out training WITH a donor-invariant contrastive correspondence
loss (option (a) from RESUME.md). Tests whether supervising the cross-slice
SIMILARITY GEOMETRY (not just per-spot coordinates) lets the learned matching
transfer to unseen donors, where coordinate regression alone did not.

Loss = L_reg + lambda * L_contrastive
  L_reg : the existing ||pred_A - gt_A|| coordinate loss (pitch units).
  L_c   : SOFT cross-entropy of the cross-slice match distribution against a
          Gaussian target centered on each B spot's array-bridge A-partner p(j):
              t[j,i] proportional to exp(-||A[i]-A[p(j)]||^2 / 2 sigma^2)
          so near-true neighbours share mass (no false-negative penalty on
          continuous tissue). The denominator (logsumexp) spans ALL A spots, so
          every other A spot is a negative. Target support is sparse (A spots
          within 4 sigma of the partner), precomputed once per pair (warp-
          invariant, like gt_A).

Two read-outs for the match logits ell[j,i] (--readout), ablated:
  cosine : L2-normalized shared q/k projections, ell = (qhat . khat) / temp
           (canonical temperature-scaled InfoNCE).
  attn   : the model's raw scaled attention logits ell = (q . k) * scale
           (the distribution actually used for the coarse prediction; no norm).

New diagnostic: held-out top-1 MATCH ACCURACY = fraction of bridged B spots whose
argmax_i ell[j,i] equals p(j). This directly measures whether correspondence
transfers, independent of the coordinate head (it was ~0 held-out before).

Everything else (folds, shared SVD basis on training slices only, eval grid,
metric) is identical to train_cross_loo.py so curves overlay on the 3-donor LOO.

Usage:
    python src/train_cross_contrastive.py --train \
        --train-pairs 151507/151508,151669/151670 --test-pair 151673/151674 \
        --readout cosine --lambda-contrastive 1.0 --out arca_ctr_demo
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import anndata as ad
import numpy as np
import torch
from scipy.spatial import cKDTree

from train_cross import ARCACrossNet
from train_cross_loo import (fit_shared_basis, build_pair, warp_graph,
                             assert_same_genes, parse_pairs, write_curve)
from scoring import registration_error_stats

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"


# --------------------------------------------------------------------------- #
# correspondence supervision: array-bridge partner index + soft Gaussian target
# --------------------------------------------------------------------------- #
def partner_index(A, B):
    """p[j] = index of the A spot at B spot j's Visium array position (-1 none).
    Warp-invariant (array positions don't move), so computed once per pair."""
    key = {(int(r), int(c)): i for i, (r, c) in
           enumerate(zip(A.obs["array_row"], A.obs["array_col"]))}
    p = np.full(B.n_obs, -1, np.int64)
    for j, (r, c) in enumerate(zip(B.obs["array_row"], B.obs["array_col"])):
        i = key.get((int(r), int(c)))
        if i is not None:
            p[j] = i
    return p


def soft_target(a_coords, partner, pitch, sigma_pitch):
    """Sparse Gaussian target over A spots around each bridged B spot's partner.
    Returns torch COO pieces (tj, ti, tw) + the bridged-B index list. tw rows sum
    to 1 over each j, so L_c is a proper soft cross-entropy."""
    sigma = sigma_pitch * pitch
    radius = 4.0 * sigma
    tree = cKDTree(a_coords)
    bridged = np.where(partner >= 0)[0]
    tj, ti, tw = [], [], []
    for j in bridged:
        p = int(partner[j])
        nb = tree.query_ball_point(a_coords[p], radius)        # incl. p itself
        d2 = ((a_coords[nb] - a_coords[p]) ** 2).sum(1)
        w = np.exp(-d2 / (2.0 * sigma * sigma))
        w /= w.sum()
        tj.extend([j] * len(nb)); ti.extend(nb); tw.extend(w)
    return {
        "tj": torch.tensor(tj, dtype=torch.long),
        "ti": torch.tensor(ti, dtype=torch.long),
        "tw": torch.tensor(tw, dtype=torch.float32),
        "bridged": torch.tensor(bridged, dtype=torch.long),
        "partner": partner,
    }


def match_logits(aux, readout, temp):
    """Pick the (n_B, n_A) match-logit matrix for the chosen read-out."""
    if readout == "cosine":
        return aux["cos_sim"] / temp
    return aux["attn_logits"]


def contrastive_loss(logits, ct):
    """Soft cross-entropy: mean_j ( logsumexp_i ell[j,i] - sum_i t[j,i] ell[j,i] ),
    averaged over bridged B spots (rows whose target mass sums to 1)."""
    lse = torch.logsumexp(logits, dim=1)                       # (n_B,)
    gathered = logits[ct["tj"], ct["ti"]]                      # (nnz,)
    wsum = torch.zeros(logits.shape[0]).index_add(
        0, ct["tj"], ct["tw"] * gathered)                      # (n_B,)
    return (lse - wsum)[ct["bridged"]].mean()


def match_top1(logits, ct):
    """Fraction of bridged B spots whose argmax A partner is the true one."""
    pi = logits.argmax(dim=1).cpu().numpy()
    b = ct["bridged"].cpu().numpy()
    return float((pi[b] == ct["partner"][b]).mean())


# --------------------------------------------------------------------------- #
def eval_curve(model, pair, severities, seed, tear, knn, readout, temp):
    """Per-severity registration error + held-out top-1 match accuracy."""
    model.eval()
    rows = []
    for sv in severities:
        gb = warp_graph(pair, sv, seed, tear, knn)
        with torch.no_grad():
            pred, aux = model(pair["ga"], gb, pair["a_norm"], return_match=True)
        pred = pred.numpy() * pair["pitch"]
        st = registration_error_stats(pred, pair["gt_A"], mask=pair["have"])
        acc = match_top1(match_logits(aux, readout, temp), pair["ct"])
        rows.append({"severity": sv, "reg_err_median": st["median"],
                     "reg_err_mean": st["mean"], "reg_err_p90": st["p90"],
                     "match_top1": acc, "n": st["n"]})
    return rows


def attach_correspondence(pair, sigma_pitch):
    """Add partner index + sparse soft target to a built pair dict."""
    p = partner_index(pair["A"], pair["B"])
    pair["ct"] = soft_target(pair["a_coords"], p, pair["pitch"], sigma_pitch)
    return pair


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-pairs", default="151507/151508,151669/151670")
    ap.add_argument("--test-pair", default="151673/151674")
    ap.add_argument("--feature-mode", choices=["global", "perslice"],
                    default="global")
    ap.add_argument("--readout", choices=["cosine", "attn"], default="cosine")
    ap.add_argument("--lambda-contrastive", type=float, default=1.0)
    ap.add_argument("--temp", type=float, default=0.07)
    ap.add_argument("--target-sigma", type=float, default=1.0,
                    help="Gaussian target width in spot-pitches")
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--attn-dim", type=int, default=64)
    ap.add_argument("--knn", type=int, default=6)
    ap.add_argument("--pca-dim", type=int, default=50)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--steps-per-epoch", type=int, default=24)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--max-severity", type=float, default=8.0)
    ap.add_argument("--tear-prob", type=float, default=0.5)
    ap.add_argument("--eval-severities", default="0,1,2,3,4,6,8")
    ap.add_argument("--eval-seed", type=int, default=0)
    ap.add_argument("--eval-mode", choices=["tear", "smooth"], default="tear")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="arca_ctr")
    ap.add_argument("--train", action="store_true")
    args = ap.parse_args()

    train_pairs = parse_pairs(args.train_pairs)
    test_ref, test_smp = parse_pairs(args.test_pair)[0]

    train_slices = []
    for ref, smp in train_pairs:
        train_slices.append(ad.read_h5ad(DATA_DIR / f"DLPFC_{ref}.h5ad"))
        train_slices.append(ad.read_h5ad(DATA_DIR / f"DLPFC_{smp}.h5ad"))
    test_slices = [ad.read_h5ad(DATA_DIR / f"DLPFC_{test_ref}.h5ad"),
                   ad.read_h5ad(DATA_DIR / f"DLPFC_{test_smp}.h5ad")]
    assert_same_genes(train_slices + test_slices)

    project = fit_shared_basis(train_slices, args.pca_dim, args.seed,
                               feature_mode=args.feature_mode)
    pairs = [attach_correspondence(build_pair(r, s, project, args.knn),
                                   args.target_sigma) for r, s in train_pairs]
    test = attach_correspondence(build_pair(test_ref, test_smp, project,
                                            args.knn), args.target_sigma)

    model = ARCACrossNet(args.pca_dim, args.hidden, args.layers, args.attn_dim)
    n_params = sum(q.numel() for q in model.parameters())

    print("=" * 72)
    print("ARCA LOO + contrastive correspondence loss")
    print("=" * 72)
    print(f"  readout       : {args.readout}  lambda={args.lambda_contrastive}  "
          f"temp={args.temp}  sigma={args.target_sigma} pitch")
    print(f"  feature mode  : {args.feature_mode} (SVD on {len(train_slices)} "
          f"train slices)")
    for pr in pairs:
        nb = int((pr['ct']['partner'] >= 0).sum())
        print(f"  train pair    : {pr['ref']}/{pr['smp']}  bridge {nb} spots")
    nb = int((test['ct']['partner'] >= 0).sum())
    print(f"  TEST pair     : {test['ref']}/{test['smp']}  bridge {nb} spots "
          f"<- HELD OUT")
    print(f"  params        : {n_params}")
    print("=" * 72)

    eval_sev = [float(x) for x in args.eval_severities.split(",")]
    eval_tear = (args.eval_mode == "tear")

    if not args.train:
        gb = warp_graph(test, 4.0, seed=1, tear=True, knn=args.knn)
        with torch.no_grad():
            pred, aux = model(test["ga"], gb, test["a_norm"], return_match=True)
        lg = match_logits(aux, args.readout, args.temp)
        print(f"forward+match OK: pred {tuple(pred.shape)}, "
              f"logits {tuple(lg.shape)}, "
              f"untrained held-out top1={match_top1(lg, test['ct']):.3f}")
        print("Run with --train to train.")
        return

    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    for epoch in range(args.epochs):
        model.train()
        tr, tc = 0.0, 0.0
        for _ in range(args.steps_per_epoch):
            pr = pairs[int(rng.integers(0, len(pairs)))]
            sv = float(rng.uniform(0, args.max_severity))
            gb = warp_graph(pr, sv, seed=int(rng.integers(1, 9999)),
                            tear=bool(rng.random() < args.tear_prob), knn=args.knn)
            opt.zero_grad()
            pred, aux = model(pr["ga"], gb, pr["a_norm"], return_match=True)
            l_reg = (pred - pr["gt_norm"])[pr["mask"]].norm(dim=1).mean()
            l_c = contrastive_loss(match_logits(aux, args.readout, args.temp),
                                   pr["ct"])
            loss = l_reg + args.lambda_contrastive * l_c
            loss.backward()
            opt.step()
            tr += l_reg.item(); tc += l_c.item()
        if epoch % 10 == 0 or epoch == args.epochs - 1:
            te = eval_curve(model, test, [eval_sev[0], eval_sev[-1]],
                            args.eval_seed, eval_tear, args.knn,
                            args.readout, args.temp)
            cells = "  ".join(f"sev{r['severity']:g}:{r['reg_err_median']:5.0f}px"
                              f"/acc{r['match_top1']:.2f}" for r in te)
            print(f"  ep {epoch:3d} | Lreg={tr/args.steps_per_epoch:.3f} "
                  f"Lc={tc/args.steps_per_epoch:.3f} | HELD-OUT {cells}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    test_rows = eval_curve(model, test, eval_sev, args.eval_seed, eval_tear,
                           args.knn, args.readout, args.temp)
    train_rows = eval_curve(model, pairs[0], eval_sev, args.eval_seed, eval_tear,
                            args.knn, args.readout, args.temp)
    write_curve(RESULTS_DIR / f"{args.out}_test_curve.csv", test_rows)
    write_curve(RESULTS_DIR / f"{args.out}_train_curve.csv", train_rows)
    torch.save({"state_dict": model.state_dict(), "args": vars(args)},
               RESULTS_DIR / f"{args.out}.pt")
    print(f"\nHELD-OUT (test) curve:")
    for r in test_rows:
        print(f"  sev{r['severity']:g}: median {r['reg_err_median']:6.1f}px  "
              f"match_top1 {r['match_top1']:.3f}  (n={r['n']})")
    print(f"wrote {args.out}_test_curve.csv, {args.out}_train_curve.csv, "
          f"{args.out}.pt")


if __name__ == "__main__":
    main()
