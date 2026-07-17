"""PASTE2 speed vs accuracy: does subsampling the pair speed up PASTE2 while preserving
the gated win? Thread-capped so it can run alongside the main grid without starving it.

For each subsample size N we subsample A and B to N spots, run real PASTE2, and score
paste2 vs gated_rigid on the (array-bridge-scored) subsampled B spots, with timing.
"""
import os
for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[v] = "2"            # cap threads so we don't oversubscribe the running grid
import sys, time
from pathlib import Path
import numpy as np
SRC = Path(r"C:\Users\karti\arca\src"); sys.path.insert(0, str(SRC))
import anndata as ad
from scipy.spatial import cKDTree
from train_cross import array_bridge
from warp_slice import apply_warp
from scoring import registration_error_stats
import hybrid_validate as hv

DATA = Path(r"C:\Users\karti\arca\data")
A0 = ad.read_h5ad(DATA/"DLPFC_151673.h5ad")
B0 = ad.read_h5ad(DATA/"DLPFC_151674.h5ad")
A0.obsm["spatial"] = np.asarray(A0.obsm["spatial"], float)
B0.obsm["spatial"] = np.asarray(B0.obsm["spatial"], float)
SEV, SEED = 4.0, 0
rng = np.random.default_rng(0)

def sub(adata, n, seed):
    if n >= adata.n_obs:
        return adata
    idx = np.sort(np.random.default_rng(seed).choice(adata.n_obs, n, replace=False))
    return adata[idx].copy()

print(f"full sizes: A={A0.n_obs} B={B0.n_obs}", flush=True)
print(f"{'N':>6} {'time_s':>7} {'n_scored':>8} {'paste2':>7} {'gated':>7} {'gated_beats':>11} {'speedup':>7}", flush=True)
t_full = None
for N in [A0.n_obs, 2500, 1500, 900]:
    A = sub(A0, N, 1); B = sub(B0, N, 2)
    coords = np.asarray(A.obsm["spatial"], float)
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    gt, have = array_bridge(A, B)
    w, _ = apply_warp(B, SEV, seed=SEED, tear=True)
    mov = np.asarray(w.obsm["spatial"], np.float32)
    t0 = time.time()
    try:
        base = hv.paste2_prior(A, w, coords, pitch)
    except Exception as e:
        print(f"{N:>6}  FAILED {e!r}", flush=True); continue
    dt = time.time() - t0
    if t_full is None:
        t_full = dt
    conf = np.ones(B.n_obs, np.float32)
    g = hv.gated_piecewise(mov, base, conf, pitch, order=0, cv=False, seed=0)
    ep = registration_error_stats(base, gt, mask=have)["median"]/pitch
    eg = registration_error_stats(g, gt, mask=have)["median"]/pitch
    print(f"{N:>6} {dt:>7.0f} {int(have.sum()):>8} {ep:>7.3f} {eg:>7.3f} {str(eg<ep):>11} "
          f"{t_full/dt:>6.1f}x", flush=True)
print("DONE", flush=True)
