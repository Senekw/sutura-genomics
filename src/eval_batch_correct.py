"""
Evaluate the batch-corrected shared-basis checkpoints on the tear benchmark and
compare the three conditions against PASTE2 (branch: batch-correct):

  shared_basis (none) — shared frozen basis, no batch correction (the 9.58 baseline)
  harmony             — shared basis + Harmony donor integration
  scanorama           — shared basis + Scanorama donor integration
  paste2              — GW/OT baseline, ingested from the prior full-res sweep

Conditions: in-distribution (Br5292, Br5595), held-out (Br8100).
Writes results/batch_correct.csv.

Usage:
  python src/eval_batch_correct.py
"""
from __future__ import annotations

import collections
import csv
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
    "Br5292": dict(ref="DLPFC_151507", mov="DLPFC_151508",
                   condition="in-distribution", prior="DLPFC_Br5292_train"),
    "Br5595": dict(ref="DLPFC_151669", mov="DLPFC_151670",
                   condition="in-distribution", prior="DLPFC_Br5595"),
    "Br8100": dict(ref="DLPFC_151673", mov="DLPFC_151674",
                   condition="held-out", prior="DLPFC_Br8100"),
}
METHODS = {"none": "shared_basis", "harmony": "harmony", "scanorama": "scanorama"}
SEVERITIES = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
SEEDS = [0, 1, 2]


def eval_method(method_key, label):
    ck = torch.load(RESULTS / f"arca_batch_{method_key}.pt", map_location="cpu",
                    weights_only=False)
    a = ck["args"]
    feats = load_feats(method_key)
    model = ARCACrossNet(ck["dim"], a["hidden"], a["layers"], a["attn_dim"])
    model.load_state_dict(ck["state_dict"]); model.eval()

    rows = []
    for name, meta in DONORS.items():
        A = ad.read_h5ad(DATA / f"{meta['ref']}.h5ad")
        B0 = ad.read_h5ad(DATA / f"{meta['mov']}.h5ad")
        A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
        B0.obsm["spatial"] = np.asarray(B0.obsm["spatial"], float)
        coords = A.obsm["spatial"]
        pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
        ga = graph_tensors(coords, feats[meta["ref"]], a["knn"], pitch)
        a_norm = torch.from_numpy((coords / pitch).astype(np.float32))
        Z_B = feats[meta["mov"]]
        gt_A, have = array_bridge(A, B0)
        for seed in SEEDS:
            for sev in SEVERITIES:
                w, _ = apply_warp(B0, sev, seed=seed, tear=True)
                gb = graph_tensors(np.asarray(w.obsm["spatial"], float), Z_B,
                                   a["knn"], pitch)
                with torch.no_grad():
                    pred = model(ga, gb, a_norm).numpy() * pitch
                st = registration_error_stats(pred, gt_A, mask=have)
                rows.append(dict(
                    donor=name, condition=meta["condition"], mode="cross",
                    severity=sev, method=label, seed=seed,
                    median_error=round(st["median"], 2),
                    median_error_pitch=round(st["median"] / pitch, 3),
                    mean_error=round(st["mean"], 2), p90_error=round(st["p90"], 2),
                    pitch_px=round(pitch, 1), n_scored=st["n"]))
    return rows


def ingest_paste2():
    src = RESULTS / "generalization_sweep.csv"
    if not src.exists():
        return []
    prior = {m["prior"]: (n, m["condition"]) for n, m in DONORS.items()}
    rows = []
    for r in csv.DictReader(open(src)):
        if r["dataset"] in prior and r["method"] == "paste2":
            donor, cond = prior[r["dataset"]]
            rows.append(dict(
                donor=donor, condition=cond, mode="cross",
                severity=float(r["severity"]), method="paste2", seed=int(r["seed"]),
                median_error=float(r["median_error"]),
                median_error_pitch=float(r["median_error_pitch"]),
                mean_error=float(r["mean_error"]), p90_error=float(r["p90_error"]),
                pitch_px=float(r["pitch_px"]), n_scored=int(r["n_scored"])))
    return rows


def main():
    rows = []
    for key, label in METHODS.items():
        print(f"evaluating {label} ...")
        rows += eval_method(key, label)
    rows += ingest_paste2()

    out = RESULTS / "batch_correct.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {out} ({len(rows)} rows)")

    agg = collections.defaultdict(list)
    for r in rows:
        agg[(r["condition"], r["donor"], r["method"])].append(r["median_error_pitch"])
    print(f"\n{'condition':16s} {'donor':7s} {'method':13s} {'med(pitch)':>10s}")
    for (c, d, m), v in sorted(agg.items()):
        print(f"{c:16s} {d:7s} {m:13s} {np.mean(v):10.2f}")


if __name__ == "__main__":
    main()
