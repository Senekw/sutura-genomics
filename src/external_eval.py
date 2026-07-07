"""
Sutura zero-shot generalization sweep across external spatial-transcriptomics
datasets (branch: external-eval; diagnostic only, no retraining).

The pretrained cross-slice checkpoint (results/arca_cross.pt, trained on DLPFC
donor Br5292 = 151507/151508) is applied ZERO-SHOT to adjacent-section pairs
from other donors / tissues / species. For each dataset we reproduce the repo's
synthetic tear benchmark (warp_slice.apply_warp, tear=True, severities 0..8) and
score median registration error against the Visium array-bridge ground truth,
head-to-head with the PASTE2 (GW/OT) baseline on the SAME warped slices.

Design decisions (see FINDINGS_sweep.md):
  * FULL resolution, no subsampling. The model is bound to a specific,
    non-canonical TruncatedSVD feature basis (its encoder was trained on the SVD
    of the full training slices). Subsampling or cropping the input re-fits the
    SVD, rotating/flipping the basis, which breaks the encoder even on the
    training donor. So every dataset is run at native density; the SVD is
    re-fit per dataset exactly as any real zero-shot application must.
  * Cross-section mode (moving = a real adjacent section, not a self-warp), which
    is the regime the model was trained on; self-mode is out of distribution and
    fails even on the training donor.
  * Sutura is a sub-second forward pass, so it runs the full severity x seed grid.
    PASTE2 GW-OT costs ~250 s/slice-pair but is nearly warp-invariant (alpha=0.1
    weights expression, which the warp leaves intact), so it runs a coarser grid.
  * 10x datasets carry no cortical-layer labels, so only registration error is
    reported.

Usage:
  python src/external_eval.py                       # full sweep (~50 min)
  python src/external_eval.py --only DLPFC_Br5595 --paste2-severities 0,8  # quick
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import anndata as ad
import numpy as np
import torch
from scipy.spatial import cKDTree

from train_cross import (ARCACrossNet, cross_features, graph_tensors,
                         array_bridge)
from warp_slice import apply_warp
from scoring import registration_error_stats, barycentric_projection
from paste2.PASTE2 import partial_pairwise_align
from paste2.helper import filter_for_common_genes

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXT = DATA / "external"
RESULTS = ROOT / "results"
CKPT = RESULTS / "arca_cross.pt"

# name, tissue, kind, reference file, moving file
DATASETS = [
    dict(name="DLPFC_Br5595", tissue="human DLPFC (cortex)",
         kind="cross-donor, same tissue",
         ref=DATA / "DLPFC_151669.h5ad", mov=DATA / "DLPFC_151670.h5ad"),
    dict(name="DLPFC_Br8100", tissue="human DLPFC (cortex)",
         kind="cross-donor, same tissue",
         ref=DATA / "DLPFC_151673.h5ad", mov=DATA / "DLPFC_151674.h5ad"),
    dict(name="MouseBrain_SagPost", tissue="mouse brain (sagittal)",
         kind="cross-species, neural",
         ref=EXT / "V1_Mouse_Brain_Sagittal_Posterior.h5ad",
         mov=EXT / "V1_Mouse_Brain_Sagittal_Posterior_Section_2.h5ad"),
    dict(name="BreastCancer_BlockA", tissue="human breast cancer",
         kind="cross-tissue, non-neural",
         ref=EXT / "V1_Breast_Cancer_Block_A_Section_1.h5ad",
         mov=EXT / "V1_Breast_Cancer_Block_A_Section_2.h5ad"),
]

# In-distribution anchor: reuse the existing full-resolution train-donor curves
# (results/arca_cross_curve.csv = Sutura, sweep_deformation_cross_tear.csv = PASTE2)
# rather than recomputing 7x250 s of PASTE2 on data we already have.
TRAIN_ANCHOR = dict(name="DLPFC_Br5292_train", tissue="human DLPFC (cortex)",
                    kind="in-distribution (train donor)")


def load_model():
    ck = torch.load(CKPT, map_location="cpu", weights_only=False)
    a = ck["args"]
    m = ARCACrossNet(a["pca_dim"], a["hidden"], a["layers"], a["attn_dim"])
    m.load_state_dict(ck["state_dict"])
    m.eval()
    return m, a


def _row(ds, sev, method, seed, st, pitch, dt):
    return dict(
        dataset=ds["name"], tissue=ds["tissue"], kind=ds["kind"], mode="cross",
        severity=sev, method=method, seed=seed,
        median_error=round(st["median"], 2),
        median_error_pitch=round(st["median"] / pitch, 3),
        mean_error=round(st["mean"], 2), p90_error=round(st["p90"], 2),
        pitch_px=round(pitch, 1), n_scored=st["n"], runtime_s=round(dt, 2))


def run_dataset(model, mp, ds, severities, seeds, p2_sev, p2_seeds):
    A = ad.read_h5ad(ds["ref"])
    B0 = ad.read_h5ad(ds["mov"])
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B0.obsm["spatial"] = np.asarray(B0.obsm["spatial"], float)
    a_coords = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(a_coords).query(a_coords, k=2)[0][:, 1]))
    gt_A, have = array_bridge(A, B0)
    Z_A, Z_B = cross_features(A, B0, mp["pca_dim"], 0)   # re-fit SVD per dataset
    ga = graph_tensors(a_coords, Z_A, mp["knn"], pitch)
    a_norm = torch.from_numpy((a_coords / pitch).astype(np.float32))

    print(f"\n=== {ds['name']} ({ds['tissue']}; {ds['kind']}) ===")
    print(f"    A={A.n_obs} B={B0.n_obs} pitch={pitch:.0f}px bridge={have.mean()*100:.0f}%")

    rows = []
    # --- Sutura: full grid (cheap) ---
    for seed in seeds:
        for sev in severities:
            w, _ = apply_warp(B0, sev, seed=seed, tear=True)
            t0 = time.time()
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), Z_B,
                               mp["knn"], pitch)
            with torch.no_grad():
                pred = model(ga, gb, a_norm).numpy() * pitch
            st = registration_error_stats(pred, gt_A, mask=have)
            rows.append(_row(ds, sev, "sutura", seed, st, pitch, time.time() - t0))
        print(f"    sutura seed{seed}: " + " ".join(
            f"s{r['severity']:g}={r['median_error_pitch']:.1f}p"
            for r in rows if r["method"] == "sutura" and r["seed"] == seed))

    # --- PASTE2: coarse grid, full resolution ---
    for seed in p2_seeds:
        for sev in p2_sev:
            w, _ = apply_warp(B0, sev, seed=seed, tear=True)
            Aa, Bb = A.copy(), w.copy()
            filter_for_common_genes([Aa, Bb])
            t0 = time.time()
            pi = np.asarray(partial_pairwise_align(
                Aa, Bb, s=0.99, alpha=0.1, dissimilarity="pca", verbose=False))
            pb, cm = barycentric_projection(pi, Aa.obsm["spatial"])
            st = registration_error_stats(pb, gt_A, mask=have & (cm > 0))
            dt = time.time() - t0
            rows.append(_row(ds, sev, "paste2", seed, st, pitch, dt))
            print(f"    paste2 seed{seed} sev{sev:g}: "
                  f"{st['median']/pitch:.2f}p  ({dt:.0f}s)")
    return rows


def anchor_rows():
    """Ingest existing full-resolution train-donor curves as anchor rows."""
    pitch = 137.00364958642524
    rows = []
    su = RESULTS / "arca_cross_curve.csv"
    if su.exists():
        for r in csv.DictReader(open(su)):
            m = float(r["reg_err_median"])
            st = {"median": m, "mean": float(r["reg_err_mean"]),
                  "p90": float(r["reg_err_p90"]), "n": int(r["n"])}
            rows.append(_row(TRAIN_ANCHOR, float(r["severity"]), "sutura", 0,
                             st, pitch, 0.0))
    pa = RESULTS / "sweep_deformation_cross_tear.csv"
    if pa.exists():
        for r in csv.DictReader(open(pa)):
            st = {"median": float(r["reg_err_median"]),
                  "mean": float(r["reg_err_mean"]),
                  "p90": float(r["reg_err_p90"]), "n": int(r["n_reg_scored"])}
            rows.append(_row(TRAIN_ANCHOR, float(r["severity"]), "paste2", 0,
                             st, pitch, float(r["runtime_s"])))
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--severities", default="0,1,2,3,4,6,8")
    p.add_argument("--seeds", default="0,1,2")
    p.add_argument("--paste2-severities", default="0,2,4,6,8")
    p.add_argument("--paste2-seeds", default="0")
    p.add_argument("--only", default="")
    p.add_argument("--no-anchor", action="store_true")
    p.add_argument("--out", default="generalization_sweep.csv")
    args = p.parse_args()

    sev = [float(x) for x in args.severities.split(",")]
    seeds = [int(x) for x in args.seeds.split(",")]
    p2s = [float(x) for x in args.paste2_severities.split(",")]
    p2seeds = [int(x) for x in args.paste2_seeds.split(",")]
    model, mp = load_model()
    print(f"loaded {CKPT.name}: trained {mp['reference']}/{mp['sample']} "
          f"pca_dim={mp['pca_dim']} hidden={mp['hidden']} layers={mp['layers']}")

    datasets = [d for d in DATASETS
                if not args.only or any(s in d["name"] for s in args.only.split(","))]
    rows = [] if args.no_anchor else anchor_rows()
    for ds in datasets:
        rows += run_dataset(model, mp, ds, sev, seeds, p2s, p2seeds)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / args.out
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
