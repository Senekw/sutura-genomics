"""
tear_detect_realgen - a REALISTIC tissue-damage generator that matches the statistics of
real damage measured by tear_detect.py, as a drop-in replacement for the synthetic tear in
src/warp_slice.apply_warp (whose tear = rigidly translate 30-45% of the tissue).

Why a new generator
-------------------
The measured facts (research/results/tear_detect.csv, and the FINDINGS) are:
  * Real Visium spots are FIXED capture locations -> real damage NEVER displaces coordinates.
    apply_warp displaces 88-99% of spots by 3-17 pitches. That signature is absent in every
    real section (frac_displaced == 0).
  * Real damage = MISSING TISSUE (interior lattice voids; small, often elongated) and FOLDS
    (locally elevated UMI), plus expression seams at genuine cut edges. It is sparse and local
    (real void area fraction is typically < 1%; a handful of voids per damaged section).
  * apply_warp's rigid-translated chunk creates one big, perfectly-rigid "piece" - exactly the
    structure a piecewise gate is built to exploit. Real damage has no such clean rigid piece.

This generator therefore:
  1. keeps the smooth Gaussian cross-section WARP (severity * pitch, identical field to
     warp_slice) as the registration challenge to recover;
  2. models damage as (a) EXCISION - remove a contiguous region of spots -> a real void
     (elongated "cut" strip and/or "missing region" blob), and (b) FOLD - multiply counts in a
     compact region by a fold factor -> a real UMI spike;
  3. does NOT translate any surviving spot beyond the smooth warp (no rigid chunk).

Ground truth is preserved for the SURVIVING spots exactly like apply_warp: obsm["spatial"]
(warped), obsm["spatial_original"] (pre-warp), and the array bridge maps each surviving B spot
to its A twin, so the gate harness scores it with no changes.

Public API (mirrors apply_warp)
-------------------------------
    w, gt = apply_realistic_damage(adata, severity, seed=0, ...)

The defaults are CALIBRATED to the real-damage statistics (see REAL_* constants below, set from
the scan). severity scales warp magnitude and damage extent together, so severity=0 reproduces
the original slice.

CLI (write a damaged copy for inspection):
    python research/src/tear_detect_realgen.py --sample 151508 --severity 4 --seed 0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anndata as ad
import numpy as np
from scipy.sparse import issparse
from scipy.spatial import cKDTree

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent.parent
sys.path.insert(0, str(ROOT / "src"))
from warp_slice import _gaussian_bump_field, median_spot_pitch  # noqa: E402

DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "research" / "results" / "tear_detect_realistic"

# --- calibrated to real damage (median across damaged real sections; see FINDINGS) ---
# Real damaged sections carry a handful of small voids (area fraction well under 1% each) and
# occasional folds with ~1.5-2.2x UMI. We let severity scale the EXTENT so the benchmark still
# sweeps from pristine to heavy, but the GEOMETRY (local, elongated cuts + compact blobs + folds)
# matches what the detector finds in real tissue rather than one rigid 40% chunk.
REAL_CUT_WIDTH_PITCH = 2.5     # real cuts/tears are ragged, ~2-3 pitches wide (not razor-thin)
REAL_FOLD_FACTOR = 1.9         # median real fold UMI ratio
REAL_FOLD_AREA_FRAC = 0.02     # compact fold patch


def _excise_strip(coords, rng, pitch, width_pitch, span_frac):
    """Boolean mask of a ragged, slightly curved strip (a real tear line) of given width crossing
    a fraction `span_frac` of the tissue. Real tears are partial, wavy and a few pitches wide -
    not a razor-straight full-tissue cut."""
    center = coords.mean(0)
    theta = rng.uniform(0, 2 * np.pi)
    axis = np.array([np.cos(theta), np.sin(theta)])       # cut direction
    normal = np.array([-axis[1], axis[0]])
    proj_a = (coords - center) @ axis
    proj_n = (coords - center) @ normal
    span = proj_a.max() - proj_a.min() + 1e-9
    # gentle sinusoidal curvature so the tear is not a perfect line
    amp = rng.uniform(1.0, 3.0) * pitch
    phase = rng.uniform(0, 2 * np.pi)
    curve = amp * np.sin(2 * np.pi * (proj_a - proj_a.min()) / span + phase)
    off = rng.uniform(np.quantile(proj_n, 0.25), np.quantile(proj_n, 0.75))
    dist_to_line = np.abs(proj_n - off - curve)
    in_width = dist_to_line < (0.5 * width_pitch * pitch)
    lo, hi = np.quantile(proj_a, 0.5 - span_frac / 2), np.quantile(proj_a, 0.5 + span_frac / 2)
    in_span = (proj_a >= lo) & (proj_a <= hi)
    return in_width & in_span


def _excise_blob(coords, rng, area_frac, irregular=True):
    """Boolean mask of a (by default irregular) missing region of area ~`area_frac` of tissue.
    Real missing regions are lumpy, not perfect disks - we union 1-3 offset sub-disks so the
    resulting void has a realistic elongation (~1.5-4) rather than a perfectly round hole."""
    n = len(coords)
    k = max(3, int(area_frac * n))
    pitch = median_spot_pitch(coords)
    n_lobes = int(rng.integers(1, 4)) if irregular else 1
    center = coords[rng.integers(n)]
    mask = np.zeros(n, bool)
    per = max(3, k // n_lobes)
    c = center.copy()
    for _ in range(n_lobes):
        d = np.linalg.norm(coords - c, axis=1)
        thr = np.partition(d, min(per, n - 1))[min(per, n - 1)]
        mask |= d <= thr
        # step the next lobe a couple pitches away in a random direction
        step = rng.normal(size=2)
        step /= np.linalg.norm(step) + 1e-9
        c = c + step * rng.uniform(2, 5) * pitch
    return mask


def apply_realistic_damage(adata, severity, *, seed=0, warp=True,
                           excise=True, fold=True, n_bumps=8, bump_width_frac=0.18,
                           cut_width_pitch=REAL_CUT_WIDTH_PITCH,
                           fold_factor=REAL_FOLD_FACTOR,
                           fold_area_frac=REAL_FOLD_AREA_FRAC):
    """Realistic damage + smooth warp. Returns (damaged AnnData, gt dict).

    severity scales BOTH the smooth warp magnitude (pitches) and the excision extent, so it is a
    comparable sweep axis to apply_warp. Damage geometry matches real statistics:
      * one partial straight cut (strip of removed spots) whose length grows with severity
      * one missing-region blob whose area grows with severity
      * one compact fold with elevated counts
    No surviving spot is displaced beyond the smooth warp."""
    coords = np.asarray(adata.obsm["spatial"], float)
    n0 = len(coords)
    pitch = median_spot_pitch(coords)
    extent = float(np.linalg.norm(coords.max(0) - coords.min(0)))
    width = bump_width_frac * extent
    rng = np.random.default_rng(seed)

    # ---- damage masks on the ORIGINAL coordinates ----
    remove = np.zeros(n0, bool)
    if excise and severity > 0:
        # A missing-region blob is the dominant real mode; a clean tear line is present only
        # some of the time (probability grows with severity). Extent scales gently with severity,
        # staying in the measured real range.
        span_frac = float(np.clip(0.12 + 0.04 * severity, 0.12, 0.5))
        blob_area = float(np.clip(0.004 + 0.003 * severity, 0.004, 0.05))
        remove = _excise_blob(coords, rng, blob_area)
        p_cut = float(np.clip(0.25 + 0.06 * severity, 0.25, 0.7))
        if rng.random() < p_cut:
            remove = remove | _excise_strip(coords, rng, pitch, cut_width_pitch, span_frac)

    folded = np.zeros(n0, bool)
    if fold and severity > 0:
        folded = _excise_blob(coords, rng, fold_area_frac) & (~remove)

    keep = ~remove
    kept_idx = np.where(keep)[0]

    # ---- build damaged AnnData on surviving spots ----
    w = adata[kept_idx].copy()
    kcoords = coords[kept_idx]

    # elevate counts in the fold region (stacked tissue -> more captured transcripts)
    if fold and folded.any():
        fmask_kept = folded[kept_idx]
        scale = np.where(fmask_kept, fold_factor, 1.0)
        X = w.X
        if issparse(X):
            from scipy.sparse import diags
            w.X = (diags(scale) @ X.tocsr()).tocsr()
        else:
            X = np.asarray(X, float)
            X[fmask_kept] *= fold_factor
            w.X = X

    # ---- smooth warp on surviving coordinates (the registration challenge) ----
    if warp and severity > 0:
        unit_field = _gaussian_bump_field(kcoords, n_bumps, width, rng)
        disp = severity * pitch * unit_field
    else:
        disp = np.zeros_like(kcoords)
    warped = kcoords + disp

    w.obsm["spatial_original"] = kcoords
    w.obsm["spatial"] = warped
    w.obsm["warp_displacement"] = disp
    w.obs["folded"] = folded[kept_idx]
    w.uns["realistic_damage"] = dict(
        severity=float(severity), seed=int(seed),
        n_removed=int(remove.sum()), removed_frac=float(remove.sum() / n0),
        n_folded=int(folded.sum()), fold_factor=float(fold_factor),
        pitch=pitch, extent=extent, warp=bool(warp), excise=bool(excise), fold=bool(fold),
        max_disp_pitch=float(np.linalg.norm(disp, axis=1).max() / pitch) if len(disp) else 0.0,
    )

    gt = dict(
        obs_names=w.obs_names.to_numpy(),
        warped_xy=warped, original_xy=kcoords, displacement=disp,
        removed_frac=float(remove.sum() / n0),
        array_row=np.asarray(w.obs["array_row"]) if "array_row" in w.obs else None,
        array_col=np.asarray(w.obs["array_col"]) if "array_col" in w.obs else None,
        severity=float(severity), seed=int(seed),
    )
    return w, gt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sample", default="151508")
    p.add_argument("--severity", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-warp", action="store_true")
    p.add_argument("--no-excise", action="store_true")
    p.add_argument("--no-fold", action="store_true")
    args = p.parse_args()

    src = DATA_DIR / f"DLPFC_{args.sample}.h5ad"
    adata = ad.read_h5ad(src)
    adata.obsm["spatial"] = np.asarray(adata.obsm["spatial"], float)
    w, gt = apply_realistic_damage(adata, args.severity, seed=args.seed,
                                   warp=not args.no_warp, excise=not args.no_excise,
                                   fold=not args.no_fold)
    m = w.uns["realistic_damage"]
    print(f"realistic damage {args.sample}: sev={args.severity} seed={args.seed} -> "
          f"kept {w.n_obs}/{adata.n_obs} (removed {m['removed_frac']*100:.1f}%), "
          f"folded {m['n_folded']}, max_warp {m['max_disp_pitch']:.2f} pitch")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"DLPFC_{args.sample}_realdmg_s{args.severity:g}_seed{args.seed}.h5ad"
    w.write_h5ad(out)
    print(f"  wrote -> {out}")


if __name__ == "__main__":
    main()
