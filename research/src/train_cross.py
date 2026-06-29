"""
Sutura — two-slice CROSS deformation model (scaffold; matches the PASTE2 headline).

Task (identical to the PASTE2 cross stress test):
  reference A = 151507 (fixed), moving B = warped-151508. For each B spot,
  predict its location in A's coordinate frame. Ground truth = the 151507 spot
  at the SAME Visium array position (the array bridge, ~95% coverage), which is
  invariant to the warp. Registration error is then measured in A's pixel frame
  by scoring.registration_error_stats — the SAME metric and axes as
  results/headline_summary.png, so Sutura's curve overlays directly on PASTE2's.

Architecture (deformation-field regression, conditioned on BOTH slices):
  1. Shared expression features: one TruncatedSVD basis fit on A and B together
     (same genes) so embeddings are comparable across slices.
  2. Shared GNN encoder (DeformConv stack from train.py) runs on each slice's
     own kNN graph (A on its fixed coords, B on its WARPED coords; edge feature
     = relative position) -> per-spot embeddings z_A, z_B.
  3. Cross-slice attention: each B spot queries all A spots by embedding
     similarity; the attention-weighted average of A coordinates is a COARSE
     soft-correspondence estimate of the B spot's A-frame location.
  4. Refinement head: MLP([z_B, attended z_A, coarse coord]) -> residual
     displacement. pred_A = coarse + residual. (Soft correspondence + learned
     deformation field; the residual is where tear discontinuities get modeled.)

Supervision: loss = || pred_A - gt_A ||  over array-matched B spots (pitch units).
Because array positions don't move under warp, gt_A is FIXED across severities;
only B's input graph/coords change.

CPU-only. kNN via scipy; message passing via PyG native scatter (no torch_cluster
/ torch_scatter). THIS FILE DOES NOT TRAIN unless run with --train (default just
builds the model and prints a design summary, so the scaffold is safe to inspect).

Usage:
    python src/train_cross.py             # design summary only, no training
    python src/train_cross.py --train     # (later, after design sign-off)
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import anndata as ad
import numpy as np
import torch
import torch.nn as nn
from scipy.sparse import issparse
from scipy.spatial import cKDTree
from sklearn.decomposition import TruncatedSVD

from train import DeformConv, knn_edges          # reuse the single-slice pieces
from scoring import registration_error_stats

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"


# --------------------------------------------------------------------------- #
# shared cross-slice expression features
# --------------------------------------------------------------------------- #
def _lognorm(adata):
    X = adata.X
    X = X.tocsr().astype(np.float32) if issparse(X) else np.asarray(X, np.float32)
    counts = np.asarray(X.sum(1)).ravel()
    counts[counts == 0] = 1.0
    if issparse(X):
        X = X.multiply(1e4 / counts[:, None]).tocsr()
        X.data = np.log1p(X.data)
        return X
    return np.log1p(X * (1e4 / counts[:, None]))


def cross_features(A, B, dim, seed):
    """One SVD basis fit on A and B together -> comparable features for both."""
    from scipy.sparse import vstack as svstack
    Xa, Xb = _lognorm(A), _lognorm(B)
    stacked = svstack([Xa, Xb]) if issparse(Xa) else np.vstack([Xa, Xb])
    svd = TruncatedSVD(n_components=dim, random_state=seed)
    Z = svd.fit_transform(stacked).astype(np.float32)
    mu, sd = Z.mean(0), Z.std(0) + 1e-6
    Z = (Z - mu) / sd
    return Z[:A.n_obs], Z[A.n_obs:]               # Z_A, Z_B


def array_bridge(A, B):
    """gt_A[j] = A coordinate at B spot j's Visium array position; have[j] flag."""
    key = {(int(r), int(c)): i for i, (r, c) in
           enumerate(zip(A.obs["array_row"], A.obs["array_col"]))}
    acoord = np.asarray(A.obsm["spatial"], np.float32)
    gt = np.full((B.n_obs, 2), np.nan, np.float32)
    have = np.zeros(B.n_obs, bool)
    for j, (r, c) in enumerate(zip(B.obs["array_row"], B.obs["array_col"])):
        i = key.get((int(r), int(c)))
        if i is not None:
            gt[j] = acoord[i]
            have[j] = True
    return gt, have


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
class Encoder(nn.Module):
    """Shared GNN encoder: feat -> hidden embeddings (residual DeformConv stack)."""

    def __init__(self, feat_dim, hidden, layers):
        super().__init__()
        self.enc = nn.Linear(feat_dim, hidden)
        self.convs = nn.ModuleList([DeformConv(hidden) for _ in range(layers)])

    def forward(self, x, edge_index, edge_attr):
        h = torch.relu(self.enc(x))
        for conv in self.convs:
            h = h + conv(h, edge_index, edge_attr)
        return h


class SuturaCrossNet(nn.Module):
    """Two-slice cross model: B spots -> predicted A-frame coordinates (pitch units)."""

    def __init__(self, feat_dim, hidden=64, layers=3, attn_dim=64):
        super().__init__()
        self.encoder = Encoder(feat_dim, hidden, layers)   # shared across slices
        self.q = nn.Linear(hidden, attn_dim)
        self.k = nn.Linear(hidden, attn_dim)
        self.v = nn.Linear(hidden, hidden)
        self.scale = attn_dim ** -0.5
        # refine head: [z_B, attended z_A, coarse coord(2)] -> residual displacement(2)
        self.head = nn.Sequential(
            nn.Linear(2 * hidden + 2, hidden), nn.ReLU(),
            nn.Linear(hidden, 2))

    def forward(self, ga, gb, a_coords_norm, return_match=False):
        """ga/gb: dicts with x, edge_index, edge_attr. a_coords_norm: (n_A,2) pitch units.
        Returns predicted A-frame coords for every B spot, in pitch units.

        If return_match=True, also returns a dict of cross-slice match logits over
        every (B spot, A spot) pair for the contrastive correspondence loss — both
        the raw scaled attention logits (q.k*scale, the distribution actually used
        for the coarse prediction) and the L2-normalized cosine similarity (for the
        canonical temperature-scaled InfoNCE read-out). Inference path (return_match
        False) is byte-for-byte unchanged."""
        z_a = self.encoder(ga["x"], ga["edge_index"], ga["edge_attr"])   # (n_A,H)
        z_b = self.encoder(gb["x"], gb["edge_index"], gb["edge_attr"])   # (n_B,H)

        qb, ka = self.q(z_b), self.k(z_a)                                # (n_B,d),(n_A,d)
        scores = (qb @ ka.T) * self.scale                                # (n_B,n_A)
        attn = torch.softmax(scores, dim=1)
        coarse = attn @ a_coords_norm                                    # (n_B,2) soft corr.
        attended_za = attn @ self.v(z_a)                                 # (n_B,H)

        residual = self.head(torch.cat([z_b, attended_za, coarse], dim=-1))
        pred = coarse + residual                                         # (n_B,2) pitch units
        if not return_match:
            return pred
        qn = torch.nn.functional.normalize(qb, dim=1)
        kn = torch.nn.functional.normalize(ka, dim=1)
        return pred, {"attn_logits": scores, "cos_sim": qn @ kn.T}


# --------------------------------------------------------------------------- #
# instance construction
# --------------------------------------------------------------------------- #
def graph_tensors(coords, Z, k, pitch):
    edge_index, d, s = knn_edges(coords, k)
    edge_attr = ((coords[d] - coords[s]) / pitch).astype(np.float32)
    return {"x": torch.from_numpy(Z),
            "edge_index": torch.from_numpy(edge_index).long(),
            "edge_attr": torch.from_numpy(edge_attr)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reference", default="151507")
    p.add_argument("--sample", default="151508")
    p.add_argument("--hidden", type=int, default=64)
    p.add_argument("--layers", type=int, default=3)
    p.add_argument("--attn-dim", type=int, default=64)
    p.add_argument("--knn", type=int, default=6)
    p.add_argument("--pca-dim", type=int, default=50)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--steps-per-epoch", type=int, default=8)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--max-severity", type=float, default=8.0)
    p.add_argument("--tear-prob", type=float, default=0.5)
    # Eval grid matched to the PASTE2 tear sweep (run_full_sweep.ps1 regime [2/3]):
    # apply_warp(B, sev, seed=0, tear=True) for sev in 0,1,2,3,4,6,8. Holding
    # eval-seed FIXED across severities reproduces the sweep's exact warped
    # slices, so Sutura's reg-err overlays directly on sweep_deformation_cross_tear.
    p.add_argument("--eval-severities", default="0,1,2,3,4,6,8")
    p.add_argument("--eval-seed", type=int, default=0,
                   help="fixed seed for ALL eval warps (matches the sweep's --seed)")
    p.add_argument("--eval-mode", choices=["tear", "smooth"], default="tear",
                   help="tear=match cross_tear curve; smooth=match cross (smooth) curve")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="arca_cross")
    p.add_argument("--train", action="store_true",
                   help="actually run training (default: print design summary only)")
    args = p.parse_args()

    A = ad.read_h5ad(DATA_DIR / f"DLPFC_{args.reference}.h5ad")
    B0 = ad.read_h5ad(DATA_DIR / f"DLPFC_{args.sample}.h5ad")
    a_coords = np.asarray(A.obsm["spatial"], np.float32)
    pitch = float(np.median(cKDTree(a_coords).query(a_coords, k=2)[0][:, 1]))

    Z_A, Z_B = cross_features(A, B0, args.pca_dim, args.seed)
    gt_A, have = array_bridge(A, B0)
    model = SuturaCrossNet(args.pca_dim, args.hidden, args.layers, args.attn_dim)
    n_params = sum(p.numel() for p in model.parameters())

    print("=" * 68)
    print("Sutura two-slice CROSS model — design summary")
    print("=" * 68)
    print(f"  reference A   : {args.reference}  ({A.n_obs} spots)")
    print(f"  moving   B    : {args.sample}  ({B0.n_obs} spots)")
    print(f"  array bridge  : {int(have.sum())}/{B0.n_obs} B spots have a GT "
          f"target in A ({100*have.mean():.1f}%)")
    print(f"  pitch         : {pitch:.1f} px")
    print(f"  features      : shared TruncatedSVD dim={args.pca_dim} "
          f"(Z_A {Z_A.shape}, Z_B {Z_B.shape})")
    print(f"  encoder       : shared, {args.layers} DeformConv layers, hidden="
          f"{args.hidden}")
    print(f"  cross-attn    : B queries A, attn_dim={args.attn_dim}, "
          f"matrix {B0.n_obs}x{A.n_obs}")
    print(f"  prediction    : coarse soft-corr coord + MLP residual "
          f"(deformation field)")
    print(f"  params        : {n_params}")
    print(f"  loss          : ||pred_A - gt_A|| over {int(have.sum())} matched "
          f"B spots (pitch units)")
    print(f"  eval          : registration error vs severity (incl tears) -> "
          f"{args.out}_curve.csv, overlays on headline_summary.png")
    print("=" * 68)

    if not args.train:
        # forward-pass shape check only (no autograd step) so the scaffold is
        # verified to wire up without committing to training.
        ga = graph_tensors(a_coords, Z_A, args.knn, pitch)
        from warp_slice import apply_warp
        warped, _ = apply_warp(B0, 4.0, seed=1, tear=True)
        gb = graph_tensors(np.asarray(warped.obsm["spatial"], np.float32),
                           Z_B, args.knn, pitch)
        with torch.no_grad():
            pred = model(ga, gb, torch.from_numpy(a_coords / pitch))
        print(f"forward-pass check OK: pred shape {tuple(pred.shape)} "
              f"(expected ({B0.n_obs}, 2))")
        print("Run with --train to start training (held until design sign-off).")
        return

    # ---- training (only with --train) ----
    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    ga = graph_tensors(a_coords, Z_A, args.knn, pitch)
    a_norm = torch.from_numpy(a_coords / pitch)
    gt_norm = torch.from_numpy(gt_A / pitch)
    mask = torch.from_numpy(have)

    from warp_slice import apply_warp
    # Matched eval grid: SAME warped slices the PASTE2 tear sweep was scored on
    # (fixed eval-seed across all severities, tear per --eval-mode). Disjoint from
    # the training seeds (rng.integers(1, 9999) >= 1), so no warp-realization leak.
    eval_tear = (args.eval_mode == "tear")
    eval_sev = [float(x) for x in args.eval_severities.split(",")]
    val = []
    for sv in eval_sev:
        w, _ = apply_warp(B0, sv, seed=args.eval_seed, tear=eval_tear)
        val.append((sv, graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                                       Z_B, args.knn, pitch)))

    for epoch in range(args.epochs):
        model.train()
        tot = 0.0
        for _ in range(args.steps_per_epoch):
            sv = float(rng.uniform(0, args.max_severity))
            w, _ = apply_warp(B0, sv, seed=int(rng.integers(1, 9999)),
                              tear=bool(rng.random() < args.tear_prob))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                               Z_B, args.knn, pitch)
            opt.zero_grad()
            pred = model(ga, gb, a_norm)
            loss = (pred - gt_norm)[mask].norm(dim=1).mean()
            loss.backward()
            opt.step()
            tot += loss.item()
        if epoch % 5 == 0 or epoch == args.epochs - 1:
            model.eval()
            cells = []
            for sv, gb in val:
                with torch.no_grad():
                    pred = model(ga, gb, a_norm).numpy() * pitch
                st = registration_error_stats(pred, gt_A, mask=have)
                cells.append(f"sev{sv:g}:{st['median']:5.0f}px")
            print(f"  epoch {epoch:3d} | L={tot/args.steps_per_epoch:.3f} | "
                  + "  ".join(cells))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    model.eval()
    for sv, gb in val:
        with torch.no_grad():
            pred = model(ga, gb, a_norm).numpy() * pitch
        st = registration_error_stats(pred, gt_A, mask=have)
        rows.append({"severity": sv, "reg_err_median": st["median"],
                     "reg_err_mean": st["mean"], "reg_err_p90": st["p90"],
                     "n": st["n"]})
    with open(RESULTS_DIR / f"{args.out}_curve.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader(); wr.writerows(rows)
    torch.save({"state_dict": model.state_dict(), "args": vars(args),
                "pitch": pitch}, RESULTS_DIR / f"{args.out}.pt")
    print(f"wrote {args.out}_curve.csv + {args.out}.pt")


if __name__ == "__main__":
    main()
