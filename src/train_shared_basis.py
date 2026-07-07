"""
Fix A — retrain the Sutura cross-slice model FROM SCRATCH on frozen shared-basis
features (src/shared_basis.py).

Supervised training uses TWO DLPFC donors (Br5292 = 151507/508, Br5595 =
151669/670); donor Br8100 (151673/674) is held fully out of training. Node
features come from the frozen basis (transform-only), so — unlike arca_cross.pt —
every section is described in the same coordinate system and the encoder is not
tied to a per-section SVD orientation.

Each training step samples one train donor pair, warps its moving slice with a
random severity/tear (warp_slice.apply_warp), and regresses each moving spot's
location in the reference frame against the Visium array-bridge ground truth
(pitch units). Architecture is identical to train_cross.ARCACrossNet.

Usage:
  python src/train_shared_basis.py                 # full train, save checkpoint
  python src/train_shared_basis.py --epochs 4 --quick   # smoke
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
from shared_basis import load_basis, transform

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

DONORS = {
    "Br5292": dict(ref=DATA / "DLPFC_151507.h5ad", mov=DATA / "DLPFC_151508.h5ad"),
    "Br5595": dict(ref=DATA / "DLPFC_151669.h5ad", mov=DATA / "DLPFC_151670.h5ad"),
    "Br8100": dict(ref=DATA / "DLPFC_151673.h5ad", mov=DATA / "DLPFC_151674.h5ad"),
}
TRAIN_DONORS = ["Br5292", "Br5595"]
HELDOUT = "Br8100"
EVAL_SEV = [0.0, 2.0, 4.0, 8.0]


def prep_donor(name, basis, knn):
    A = ad.read_h5ad(DONORS[name]["ref"])
    B0 = ad.read_h5ad(DONORS[name]["mov"])
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B0.obsm["spatial"] = np.asarray(B0.obsm["spatial"], float)
    a = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(a).query(a, k=2)[0][:, 1]))
    Z_A, Z_B = transform(A, basis), transform(B0, basis)   # FROZEN basis
    gt_A, have = array_bridge(A, B0)
    return dict(
        name=name, A=A, B0=B0, a_coords=a, pitch=pitch, Z_B=Z_B,
        ga=graph_tensors(a, Z_A, knn, pitch),
        a_norm=torch.from_numpy((a / pitch).astype(np.float32)),
        gt_norm=torch.from_numpy((gt_A / pitch).astype(np.float32)),
        gt_A=gt_A, mask=torch.from_numpy(have), have=have)


def eval_median(model, d, knn, seed=0, tear=True):
    out = {}
    model.eval()
    for sv in EVAL_SEV:
        w, _ = apply_warp(d["B0"], sv, seed=seed, tear=tear)
        gb = graph_tensors(np.asarray(w.obsm["spatial"], float), d["Z_B"], knn,
                           d["pitch"])
        with torch.no_grad():
            pred = model(d["ga"], gb, d["a_norm"]).numpy() * d["pitch"]
        out[sv] = registration_error_stats(pred, d["gt_A"], mask=d["have"])["median"] / d["pitch"]
    return out


def main():
    p = argparse.ArgumentParser()
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
    p.add_argument("--quick", action="store_true")
    p.add_argument("--basis", default="results/shared_basis.npz")
    p.add_argument("--out", default="arca_shared_basis")
    args = p.parse_args()

    basis = load_basis(ROOT / args.basis)
    dim = basis["components"].shape[0]
    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)

    train = {n: prep_donor(n, basis, args.knn) for n in TRAIN_DONORS}
    heldout = prep_donor(HELDOUT, basis, args.knn)
    print(f"frozen basis: genes={len(basis['genes'])} dim={dim}")
    for n, d in {**train, HELDOUT: heldout}.items():
        tag = "TRAIN" if n in TRAIN_DONORS else "HELD-OUT"
        print(f"  {n:7s} [{tag:8s}] ref={d['A'].n_obs} mov={d['B0'].n_obs} "
              f"pitch={d['pitch']:.0f} bridge={d['have'].mean()*100:.0f}%")

    model = ARCACrossNet(dim, args.hidden, args.layers, args.attn_dim)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    names = list(train)

    for epoch in range(args.epochs):
        model.train()
        tot = 0.0
        for _ in range(args.steps_per_epoch):
            d = train[names[int(rng.integers(len(names)))]]
            sv = float(rng.uniform(0, args.max_severity))
            w, _ = apply_warp(d["B0"], sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < args.tear_prob))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), d["Z_B"],
                               args.knn, d["pitch"])
            opt.zero_grad()
            pred = model(d["ga"], gb, d["a_norm"])
            loss = (pred - d["gt_norm"])[d["mask"]].norm(dim=1).mean()
            loss.backward()
            opt.step()
            tot += loss.item()
        if epoch % 5 == 0 or epoch == args.epochs - 1:
            cells = []
            for n in [*TRAIN_DONORS, HELDOUT]:
                d = train.get(n, heldout)
                ev = eval_median(model, d, args.knn)
                cells.append(f"{n}[{ev[0.0]:.1f}/{ev[4.0]:.1f}/{ev[8.0]:.1f}]")
            print(f"  ep{epoch:3d} L={tot/args.steps_per_epoch:.3f} | "
                  "med pitch@sev0/4/8: " + "  ".join(cells))
        if args.quick and epoch >= 3:
            break

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{args.out}.pt"
    torch.save({"state_dict": model.state_dict(), "args": vars(args),
                "dim": dim, "pitch": {n: train.get(n, heldout)["pitch"]
                                      for n in DONORS},
                "basis_path": args.basis,
                "train_donors": TRAIN_DONORS, "heldout": HELDOUT},
               out)
    print(f"\nwrote checkpoint -> {out}")


if __name__ == "__main__":
    main()
