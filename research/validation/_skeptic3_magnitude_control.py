"""
Skeptic #3 control: isolate DISCONTINUITY from MAGNITUDE.

The tear sweep confounds two things at once: as severity rises, the torn block
both (a) stays discontinuous AND (b) is translated by 3*sev pitches, so its
displacement magnitude (mean ~2028px / max ~4337px at sev8) far exceeds anything
the SMOOTH sweep ever reaches (mean 725 / max 1096 at sev8).

This script runs the MISSING control: a PURE SMOOTH warp scaled up to the tear's
magnitude. If PASTE2 also degrades under a high-magnitude *smooth* warp, the
"degrades under tearing" attribution is confounded by magnitude. If it stays
flat, the discontinuity attribution survives.

Same pipeline as src/sweep_deformation.py (cross mode, array-bridge GT,
barycentric + argmax projection). Subsampled for speed, matching the validation
re-run protocol.
"""
import sys
from pathlib import Path
import numpy as np
import anndata as ad

ROOT = Path("/Users/seangplee/biostartup-main")
sys.path.insert(0, str(ROOT / "src"))

from paste2.PASTE2 import partial_pairwise_align
from paste2.helper import filter_for_common_genes
from warp_slice import _gaussian_bump_field, median_spot_pitch
from scoring import (argmax_projection, barycentric_projection,
                     registration_error_stats, report)

DATA = ROOT / "data"
N_SUB = 400
SEED = 0


def array_keys(a):
    return list(zip(a.obs["array_row"].astype(int), a.obs["array_col"].astype(int)))


def subset_common(ref, tgt, n, seed=0):
    rk = {k: i for i, k in enumerate(array_keys(ref))}
    tk = {k: j for j, k in enumerate(array_keys(tgt))}
    common = sorted(set(rk) & set(tk))
    rng = np.random.default_rng(seed)
    if n < len(common):
        common = [common[i] for i in np.sort(rng.choice(len(common), n, replace=False))]
    ri = [rk[k] for k in common]
    ti = [tk[k] for k in common]
    return ref[ri].copy(), tgt[ti].copy()


def gt_targets(ref, warped):
    rk = {k: i for i, k in enumerate(array_keys(ref))}
    rc = np.asarray(ref.obsm["spatial"], float)
    gt = np.full((warped.n_obs, 2), np.nan)
    have = np.zeros(warped.n_obs, bool)
    for j, k in enumerate(array_keys(warped)):
        i = rk.get(k)
        if i is not None:
            gt[j] = rc[i]; have[j] = True
    return gt, have


def smooth_warp(adata, max_disp_px, seed=0, n_bumps=8, bump_width_frac=0.18):
    """Pure smooth Gaussian-bump field, scaled to a target MAX displacement in px."""
    coords = np.asarray(adata.obsm["spatial"], float)
    extent = float(np.linalg.norm(coords.max(0) - coords.min(0)))
    width = bump_width_frac * extent
    rng = np.random.default_rng(seed)
    unit = _gaussian_bump_field(coords, n_bumps, width, rng)  # unit peak
    disp = unit * max_disp_px  # scale so peak == max_disp_px
    w = adata.copy()
    w.obsm["spatial_original"] = coords
    w.obsm["spatial"] = coords + disp
    mag = np.linalg.norm(disp, axis=1)
    return w, float(mag.max()), float(mag.mean())


def run(ref, tgt, max_disp_px, label):
    w, mx, mn = smooth_warp(tgt, max_disp_px, seed=SEED)
    A = ref.copy(); B = w.copy()
    filter_for_common_genes([A, B])
    pi = np.asarray(partial_pairwise_align(A, B, s=0.99, alpha=0.1,
                                           dissimilarity="pca", verbose=False))
    gt, have = gt_targets(A, B)
    pred_b, col = barycentric_projection(pi, A.obsm["spatial"])
    pred_a, _ = argmax_projection(pi, A.obsm["spatial"])
    mask = have & (col > 0)
    rb = registration_error_stats(pred_b, gt, mask=mask)
    ra = registration_error_stats(pred_a, gt, mask=mask)
    lab = report(pi, A.obs["layer"].astype(str).values, B.obs["layer"].astype(str).values)
    print(f"{label:>26}: max={mx:7.0f}px mean={mn:7.0f}px "
          f"| median_bary={rb['median']:7.1f} argmax={ra['median']:7.1f} "
          f"| acc={lab['model']['accuracy']*100:5.1f}% (n={rb['n']})")
    return rb["median"], ra["median"], lab["model"]["accuracy"]


def main():
    ref = ad.read_h5ad(DATA / "DLPFC_151507.h5ad")
    tgt = ad.read_h5ad(DATA / "DLPFC_151508.h5ad")
    ref, tgt = subset_common(ref, tgt, N_SUB, seed=SEED)
    pitch = median_spot_pitch(np.asarray(tgt.obsm["spatial"], float))
    print(f"subsample n={tgt.n_obs}  pitch={pitch:.1f}px  (PASTE2 pca dissim, s=0.99 alpha=0.1)")
    print("=" * 100)
    # smooth baseline (sev0-equivalent), then SMOOTH warps scaled to the tear's mean/max magnitudes
    run(ref, tgt, 0.0, "smooth max=0 (baseline)")
    run(ref, tgt, 1096, "smooth max=1096 (=tear sev8 SMOOTH-part only)")
    run(ref, tgt, 2028, "smooth max=2028 (=tear sev8 MEAN disp)")
    run(ref, tgt, 4337, "smooth max=4337 (=tear sev8 MAX disp)")
    print("=" * 100)
    print("If high-magnitude SMOOTH stays ~flat -> degradation is discontinuity-specific (claim survives).")
    print("If high-magnitude SMOOTH also degrades -> tear effect confounded by magnitude (claim weakened).")


if __name__ == "__main__":
    main()
