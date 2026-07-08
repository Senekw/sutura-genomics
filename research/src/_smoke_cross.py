"""Smoke harness for Sutura cross model: per-epoch loss + val logging -> PNG.

Reuses train_cross internals so it exercises the SAME model/data path as the
real run; it just records train loss and val reg-error every epoch and plots
both, so we can eyeball that training is healthy before the full run.
"""
from __future__ import annotations

import csv
from pathlib import Path

import anndata as ad
import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scipy.spatial import cKDTree

from train_cross import (SuturaCrossNet, cross_features, array_bridge,
                         graph_tensors, DATA_DIR, RESULTS_DIR)
from warp_slice import apply_warp
from scoring import registration_error_stats

EPOCHS = 30
STEPS = 8
KNN = 6
PCA = 50
LR = 1e-3
MAXSEV = 8.0
TEARPROB = 0.5
VAL_SEV = [0.0, 2.0, 4.0, 8.0]
SEED = 0


def main():
    rng = np.random.default_rng(SEED)
    torch.manual_seed(SEED)

    A = ad.read_h5ad(DATA_DIR / "DLPFC_151507.h5ad")
    B0 = ad.read_h5ad(DATA_DIR / "DLPFC_151508.h5ad")
    a_coords = np.asarray(A.obsm["spatial"], np.float32)
    pitch = float(np.median(cKDTree(a_coords).query(a_coords, k=2)[0][:, 1]))

    Z_A, Z_B = cross_features(A, B0, PCA, SEED)
    gt_A, have = array_bridge(A, B0)
    model = SuturaCrossNet(PCA, 64, 3, 64)
    opt = torch.optim.Adam(model.parameters(), lr=LR)

    ga = graph_tensors(a_coords, Z_A, KNN, pitch)
    a_norm = torch.from_numpy(a_coords / pitch)
    gt_norm = torch.from_numpy(gt_A / pitch)
    mask = torch.from_numpy(have)

    val = []
    for i, sv in enumerate(VAL_SEV):
        w, _ = apply_warp(B0, sv, seed=10_000 + i, tear=(sv > 0))
        val.append((sv, graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                                      Z_B, KNN, pitch)))

    hist = {"epoch": [], "train_loss": [],
            **{f"val_sev{int(s)}": [] for s in VAL_SEV}}

    for epoch in range(EPOCHS):
        model.train()
        tot = 0.0
        for _ in range(STEPS):
            sv = float(rng.uniform(0, MAXSEV))
            w, _ = apply_warp(B0, sv, seed=int(rng.integers(1, 9999)),
                              tear=bool(rng.random() < TEARPROB))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                               Z_B, KNN, pitch)
            opt.zero_grad()
            pred = model(ga, gb, a_norm)
            loss = (pred - gt_norm)[mask].norm(dim=1).mean()
            loss.backward()
            opt.step()
            tot += loss.item()
        model.eval()
        hist["epoch"].append(epoch)
        hist["train_loss"].append(tot / STEPS)
        line = [f"L={tot/STEPS:6.3f}"]
        for sv, gb in val:
            with torch.no_grad():
                pred = model(ga, gb, a_norm).numpy() * pitch
            st = registration_error_stats(pred, gt_A, mask=have)
            hist[f"val_sev{int(sv)}"].append(st["median"])
            line.append(f"sev{sv:g}:{st['median']:5.0f}px")
        print(f"  epoch {epoch:3d} | " + "  ".join(line))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS_DIR / "arca_cross_smoke_history.csv"
    with open(csv_path, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(hist.keys()))
        wr.writeheader()
        for i in range(len(hist["epoch"])):
            wr.writerow({k: hist[k][i] for k in hist})

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    ax1.plot(hist["epoch"], hist["train_loss"], "o-", color="tab:blue")
    ax1.set_xlabel("epoch"); ax1.set_ylabel("train loss (pitch units)")
    ax1.set_title("Sutura cross — training loss"); ax1.grid(alpha=0.3)
    for sv in VAL_SEV:
        ax2.plot(hist["epoch"], hist[f"val_sev{int(sv)}"], "o-",
                 label=f"sev {sv:g}" + (" (tear)" if sv > 0 else ""))
    ax2.set_xlabel("epoch"); ax2.set_ylabel("val reg-err median (px)")
    ax2.set_title("Sutura cross — val registration error")
    ax2.legend(); ax2.grid(alpha=0.3)
    fig.tight_layout()
    png = RESULTS_DIR / "arca_cross_smoke_loss.png"
    fig.savefig(png, dpi=120)
    print(f"\nwrote {csv_path}")
    print(f"wrote {png}")


if __name__ == "__main__":
    main()
