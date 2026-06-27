"""Benchmark STalign (diffeomorphic LDDMM) on the SAME tear benchmark as PASTE2/Sutura.

STalign aligns two slices by diffeomorphic metric mapping of their (rasterized) spatial
density. We align source = warped-151508 to target = 151507, transform the warped B spots
into A's frame, and score against the SAME array-bridge ground truth used everywhere else.
This directly tests the thesis "diffeomorphic methods structurally cannot represent a tear."

Usage:
  python validation/run_stalign.py --severities 0,8 --niter 500   # smoke
  python validation/run_stalign.py --severities 0,4,8 --niter 1500 # full
"""
from __future__ import annotations
import sys, csv, time, argparse
from pathlib import Path
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import anndata as ad
from scipy.spatial import cKDTree
from warp_slice import apply_warp
from train_cross import array_bridge
from scoring import registration_error_stats
from STalign import STalign as ST

DATA, RESULTS = ROOT / "data", ROOT / "results"


def run(args):
    A = ad.read_h5ad(DATA / f"DLPFC_{args.reference}.h5ad")
    B = ad.read_h5ad(DATA / f"DLPFC_{args.sample}.h5ad")
    cA = np.asarray(A.obsm["spatial"], float)            # [x,y]
    pitch = float(np.median(cKDTree(cA).query(cA, k=2)[0][:, 1]))
    gt_A, have = array_bridge(A, B)                       # A-frame [x,y] target per B spot
    dx = args.dx if args.dx > 0 else pitch / 2.0

    # rasterize TARGET (A) once
    xJ, yJ = cA[:, 0], cA[:, 1]
    XJ, YJ, J = ST.rasterize(xJ, yJ, dx=dx, draw=False)
    J = torch.tensor(ST.normalize(J), dtype=torch.float64)
    xvJ = [torch.tensor(YJ, dtype=torch.float64), torch.tensor(XJ, dtype=torch.float64)]

    rows = []
    for sev in [float(s) for s in args.severities.split(",")]:
        t0 = time.time()
        w, _ = apply_warp(B, sev, seed=args.seed, tear=True)
        cB = np.asarray(w.obsm["spatial"], float)        # warped [x,y]
        xI, yI = cB[:, 0], cB[:, 1]
        XI, YI, I = ST.rasterize(xI, yI, dx=dx, draw=False)
        I = torch.tensor(ST.normalize(I), dtype=torch.float64)
        xvI = [torch.tensor(YI, dtype=torch.float64), torch.tensor(XI, dtype=torch.float64)]

        out = ST.LDDMM(xvI, I, xvJ, J, niter=args.niter, device="cpu",
                       dtype=torch.float64, a=args.a * dx)
        Amat, v, xv = out["A"], out["v"], out["xv"]

        pts = np.stack([yI, xI], -1)                     # SOURCE points [row,col]=[y,x]
        tpts = ST.transform_points_source_to_target(xv, v, Amat, pts)
        tpts = tpts.detach().numpy() if hasattr(tpts, "detach") else np.asarray(tpts)
        pred = np.stack([tpts[:, 1], tpts[:, 0]], -1)    # back to [x,y]

        st = registration_error_stats(pred, gt_A, mask=have)
        dt = time.time() - t0
        rows.append(dict(severity=sev, reg_err_median=st["median"], reg_err_mean=st["mean"],
                         reg_err_p90=st["p90"], n=st["n"], runtime_s=dt))
        print(f"  sev{sev:>3.0f}: median {st['median']:7.1f}px  mean {st['mean']:7.1f}px  "
              f"p90 {st['p90']:7.1f}px  (n={st['n']}, {dt:.0f}s)")

    out_csv = RESULTS / f"stalign_tear{args.suffix}.csv"
    with open(out_csv, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
    print(f"wrote {out_csv}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--reference", default="151507")
    p.add_argument("--sample", default="151508")
    p.add_argument("--severities", default="0,4,8")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--niter", type=int, default=1500)
    p.add_argument("--dx", type=float, default=0)     # 0 -> pitch/2
    p.add_argument("--a", type=float, default=5.0)    # smoothness scale (in units of dx)
    p.add_argument("--suffix", default="")
    run(p.parse_args())
