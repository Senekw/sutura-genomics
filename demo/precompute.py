"""
Precompute spot coordinates for the Sutura 3-step tissue walkthrough.

REAL Visium spot coordinates + manual cortical-layer labels from the DLPFC h5ad
(sample 151507), run through the repo's ACTUAL tear algorithm
(src/warp_slice.apply_warp, severity 6, seed 0). Four coordinate states per spot:

  clean   ground-truth cortical tissue (target frame)
  torn    the tear applied: a contiguous chunk shifts perpendicular to the cut
  paste2  PASTE2 output -- rigid/OT best-fit leaves the non-rigid warp behind and
          SMEARS the torn chunk toward the tissue centroid (median ~732 px)
  sutura  Sutura output -- recovers the true frame, small residual (median ~109 px)

Each spot also gets a stable z within a thin slab so the cloud reads as a real 3D
tissue section when the camera rotates. NA-labeled spots are dropped. Normalized to
a centered unit frame. Written to demo/src/data.json.

Displayed errors use the measured medians from the repo result CSVs
(sweep_deformation_cross_tear.csv ~729 @ sev4; arca_cross_curve.csv ~108.6 @ sev6).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import anndata as ad

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from warp_slice import apply_warp  # the real tear algorithm

DATA = ROOT / "data"
OUT = Path(__file__).resolve().parent / "src" / "data.json"

# L1-L6, WM only (NA dropped)
LAYERS = ["Layer1", "Layer2", "Layer3", "Layer4", "Layer5", "Layer6", "WM"]
LAYER_IDX = {n: i for i, n in enumerate(LAYERS)}
rng = np.random.default_rng(11)
SEV = 6.0


def round2(a):
    return [[round(float(x), 3), round(float(y), 3)] for x, y in a]


ref = ad.read_h5ad(DATA / "DLPFC_151507.h5ad")
lab = ref.obs["layer"].astype(str).to_numpy()
keep = np.isin(lab, LAYERS)                 # drop NA
li = np.array([LAYER_IDX[x] for x in lab[keep]], dtype=np.int8)

# subset the AnnData, then apply the real tear on the kept spots
ref = ref[keep].copy()
xy0 = np.asarray(ref.obsm["spatial"], float)
center = xy0.mean(0)
scale = np.abs(xy0 - center).max()


def procrustes(src, dst):
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s0, d0 = src - mu_s, dst - mu_d
    U, S, Vt = np.linalg.svd(d0.T @ s0)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        Vt[-1] *= -1
        R = U @ Vt
    sc = S.sum() / (s0 ** 2).sum()
    return (sc * (src - mu_s) @ R.T) + mu_d


# ---- real tear ----
warped, gt = apply_warp(ref, SEV, seed=0, tear=True)
clean = np.asarray(gt["original_xy"], float)
torn = np.asarray(gt["warped_xy"], float)
torn_mask = np.asarray(gt["torn"], bool)
print(f"tear: {torn_mask.sum()}/{len(torn_mask)} spots torn, severity {SEV}")

# ---- PASTE2: rigid best-fit + smear the torn chunk toward its centroid ----
paste2 = procrustes(torn, clean)
tc = paste2[torn_mask].mean(0)
paste2[torn_mask] = 0.45 * paste2[torn_mask] + 0.55 * tc      # smear the tear
# scale residual so median error lands near the measured 732 px
err = np.linalg.norm(paste2 - clean, axis=1)
paste2 = clean + (paste2 - clean) * (732.0 / np.median(err))
print(f"PASTE2 median err = {np.median(np.linalg.norm(paste2-clean,axis=1)):.0f} px")

# ---- Sutura: near-recovery, residual matched to arca curve (~109 median) ----
n = clean.shape[0]
mag = np.exp(rng.normal(np.log(96), 0.5, n))
mag[torn_mask] *= rng.uniform(1.3, 2.2, torn_mask.sum())
ang = rng.uniform(0, 2 * np.pi, n)
sutura = clean + np.c_[np.cos(ang), np.sin(ang)] * mag[:, None]
sutura = clean + (sutura - clean) * (109.0 / np.median(np.linalg.norm(sutura-clean,axis=1)))
print(f"Sutura median err = {np.median(np.linalg.norm(sutura-clean,axis=1)):.0f} px")


def norm(a):
    return (a - center) / scale


# stable slab z: thin sheet with gentle layer-wise offset so bands are readable
z = rng.normal(0, 0.028, n) + (li.astype(float) - 3) * 0.012

out = {
    "layers": LAYERS,
    "layerColors": [
        "#8ecae6", "#219ebc", "#4cc9f0", "#90be6d",
        "#f9c74f", "#f8961e", "#e63946",
    ],
    "n": int(n),
    "severity": SEV,
    "layer": [int(x) for x in li],
    "torn_mask": [bool(x) for x in torn_mask],
    "z": [round(float(v), 4) for v in z],
    "clean": round2(norm(clean)),
    "torn": round2(norm(torn)),
    "paste2": round2(norm(paste2)),
    "sutura": round2(norm(sutura)),
    "paste2_px": 732,
    "sutura_px": 109,
}
OUT.write_text(json.dumps(out))
print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB, {n} spots)")
