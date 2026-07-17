"""PASTE2 speed vs accuracy via SUBSAMPLING. Does aligning fewer spots speed PASTE2 up
while preserving the gated win? Subsample-only (full-res timing is read from the grid log,
~190s for Br8100 sev4) + thread-capped, so it runs light alongside the grid.

For each subsample size N we subsample A and B to N spots, run real PASTE2, and score
paste2 vs gated_rigid/affine on the array-bridge-scored subsampled B spots, with timing.
"""
import os
for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[v] = "2"
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
FULL_REF_S = 190.0   # Br8100 sev4 full-res solve time from the grid log (8-thread)
A0 = ad.read_h5ad(DATA / "DLPFC_151673.h5ad"); B0 = ad.read_h5ad(DATA / "DLPFC_151674.h5ad")
A0.obsm["spatial"] = np.asarray(A0.obsm["spatial"], float)
B0.obsm["spatial"] = np.asarray(B0.obsm["spatial"], float)
SEV, SEED = 4.0, 0


def sub(adata, n, seed):
    if n >= adata.n_obs:
        return adata
    idx = np.sort(np.random.default_rng(seed).choice(adata.n_obs, n, replace=False))
    return adata[idx].copy()


print(f"full sizes A={A0.n_obs} B={B0.n_obs}; full-res ref (grid, 8-thread) = {FULL_REF_S:.0f}s "
      f"(this probe is 2-thread so absolute times run slower; use the N=full row here as the "
      f"2-thread anchor for ratios)", flush=True)
print(f"{'N':>6} {'time_s':>7} {'n_scored':>8} {'paste2':>7} {'g_rigid':>8} {'g_affine':>8} "
      f"{'rigid_beats':>11}", flush=True)
anchor = None
for N in [A0.n_obs, 2500, 1500, 900, 600]:
    A = sub(A0, N, 1); B = sub(B0, N, 2)
    coords = np.asarray(A.obsm["spatial"], float)
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    gt, have = array_bridge(A, B)
    if have.sum() < 30:
        print(f"{N:>6}  skip (bridge too small: {int(have.sum())})", flush=True); continue
    w, _ = apply_warp(B, SEV, seed=SEED, tear=True)
    mov = np.asarray(w.obsm["spatial"], np.float32)
    t0 = time.time()
    try:
        base = hv.paste2_prior(A, w, coords, pitch)
    except Exception as e:
        print(f"{N:>6}  FAILED {e!r}", flush=True); continue
    dt = time.time() - t0
    if anchor is None:
        anchor = dt
    conf = np.ones(B.n_obs, np.float32)
    gr = hv.gated_piecewise(mov, base, conf, pitch, order=0, cv=False, seed=0)
    ga = hv.gated_piecewise(mov, base, conf, pitch, order=1, cv=True, seed=0)
    ep = registration_error_stats(base, gt, mask=have)["median"] / pitch
    egr = registration_error_stats(gr, gt, mask=have)["median"] / pitch
    ega = registration_error_stats(ga, gt, mask=have)["median"] / pitch
    print(f"{N:>6} {dt:>7.0f} {int(have.sum()):>8} {ep:>7.2f} {egr:>8.2f} {ega:>8.2f} "
          f"{str(egr < ep):>11}  ({anchor/dt:.1f}x vs N=full)", flush=True)
print("DONE", flush=True)
