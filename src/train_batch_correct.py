"""
Retrain the Sutura cross-slice model from scratch on batch-corrected shared-basis
features (branch: batch-correct). Same architecture and protocol as
train_shared_basis.py; the ONLY change is the node-feature source, which is the
cached batch-corrected features from batch_correct.py (method in none/harmony/
scanorama). Train on Br5292 + Br5595; hold Br8100 out of supervised training.

Usage:
  python src/batch_correct.py --method all      # build feature caches first
  python src/train_batch_correct.py --method harmony
"""
from __future__ import annotations

import argparse
from pathlib import Path

import anndata as ad
import numpy as np
import torch
from scipy.spatial import cKDTree

from train_cross import ARCACrossNet, graph_tensors, array_bridge
from warp_slice import apply_warp
from scoring import registration_error_stats
from batch_correct import load_feats

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

DONORS = {
    "Br5292": dict(ref="DLPFC_151507", mov="DLPFC_151508"),
    "Br5595": dict(ref="DLPFC_151669", mov="DLPFC_151670"),
    "Br8100": dict(ref="DLPFC_151673", mov="DLPFC_151674"),
}
TRAIN_DONORS = ["Br5292", "Br5595"]
HELDOUT = "Br8100"
EVAL_SEV = [0.0, 4.0, 8.0]


def prep(name, feats, knn):
    m = DONORS[name]
    A = ad.read_h5ad(DATA / f"{m['ref']}.h5ad")
    B0 = ad.read_h5ad(DATA / f"{m['mov']}.h5ad")
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B0.obsm["spatial"] = np.asarray(B0.obsm["spatial"], float)
    a = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(a).query(a, k=2)[0][:, 1]))
    Z_A, Z_B = feats[m["ref"]], feats[m["mov"]]
    gt_A, have = array_bridge(A, B0)
    return dict(name=name, B0=B0, pitch=pitch, Z_B=Z_B, gt_A=gt_A, have=have,
                ga=graph_tensors(a, Z_A, knn, pitch),
                a_norm=torch.from_numpy((a / pitch).astype(np.float32)),
                gt_norm=torch.from_numpy((gt_A / pitch).astype(np.float32)),
                mask=torch.from_numpy(have))


def eval_median(model, d, knn, seed=0):
    model.eval(); out = {}
    for sv in EVAL_SEV:
        w, _ = apply_warp(d["B0"], sv, seed=seed, tear=True)
        gb = graph_tensors(np.asarray(w.obsm["spatial"], float), d["Z_B"], knn, d["pitch"])
        with torch.no_grad():
            pred = model(d["ga"], gb, d["a_norm"]).numpy() * d["pitch"]
        out[sv] = registration_error_stats(pred, d["gt_A"], mask=d["have"])["median"] / d["pitch"]
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--method", required=True, choices=["none", "harmony", "scanorama"])
    p.add_argument("--hidden", type=int, default=64)
    p.add_argument("--layers", type=int, default=3)
    p.add_argument("--attn-dim", type=int, default=64)
    p.add_argument("--knn", type=int, default=6)
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--steps-per-epoch", type=int, default=16)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--max-severity", type=float, default=8.0)
    p.add_argument("--tear-prob", type=float, default=0.5)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    feats = load_feats(args.method)
    dim = next(iter(feats.values())).shape[1]
    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)

    train = {n: prep(n, feats, args.knn) for n in TRAIN_DONORS}
    heldout = prep(HELDOUT, feats, args.knn)
    print(f"[{args.method}] dim={dim}  train={TRAIN_DONORS}  heldout={HELDOUT}")

    model = ARCACrossNet(dim, args.hidden, args.layers, args.attn_dim)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    names = list(train)

    for epoch in range(args.epochs):
        model.train(); tot = 0.0
        for _ in range(args.steps_per_epoch):
            d = train[names[int(rng.integers(len(names)))]]
            sv = float(rng.uniform(0, args.max_severity))
            w, _ = apply_warp(d["B0"], sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < args.tear_prob))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), d["Z_B"],
                               args.knn, d["pitch"])
            opt.zero_grad()
            loss = (model(d["ga"], gb, d["a_norm"]) - d["gt_norm"])[d["mask"]].norm(dim=1).mean()
            loss.backward(); opt.step(); tot += loss.item()
        if epoch % 10 == 0 or epoch == args.epochs - 1:
            cells = []
            for n in [*TRAIN_DONORS, HELDOUT]:
                ev = eval_median(model, train.get(n, heldout), args.knn)
                cells.append(f"{n}[{ev[0.0]:.1f}/{ev[8.0]:.1f}]")
            print(f"  [{args.method}] ep{epoch:3d} L={tot/args.steps_per_epoch:.3f} | "
                  "pitch@sev0/8: " + "  ".join(cells))

    out = RESULTS / f"arca_batch_{args.method}.pt"
    torch.save({"state_dict": model.state_dict(), "args": vars(args),
                "dim": dim, "method": args.method,
                "train_donors": TRAIN_DONORS, "heldout": HELDOUT}, out)
    print(f"[{args.method}] wrote checkpoint -> {out}")


if __name__ == "__main__":
    main()
