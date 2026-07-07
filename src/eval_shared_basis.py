"""
Fix A — evaluate the shared-frozen-basis Sutura checkpoint on the tear benchmark
and compare against (a) the old per-section-SVD model and (b) PASTE2.

Conditions (tear benchmark, severities 0..8, cross-section, array-bridge GT):
  in-distribution : Br5292 (151507/508), Br5595 (151669/670)   [train donors]
  held-out        : Br8100 (151673/674)                        [never trained on]

Methods:
  sutura_shared  — the new frozen-shared-basis model (results/arca_shared_basis.pt)
  sutura_persvd  — the old per-section-SVD model, ingested from the prior sweep
                   (results/generalization_sweep.csv) for a direct before/after
  paste2         — PASTE2 GW/OT, ingested from the same prior full-resolution run

Writes results/shared_basis_eval.csv.

Usage:
  python src/eval_shared_basis.py
"""
from __future__ import annotations

import csv
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
    "Br5292": dict(ref=DATA / "DLPFC_151507.h5ad", mov=DATA / "DLPFC_151508.h5ad",
                   condition="in-distribution", prior="DLPFC_Br5292_train"),
    "Br5595": dict(ref=DATA / "DLPFC_151669.h5ad", mov=DATA / "DLPFC_151670.h5ad",
                   condition="in-distribution", prior="DLPFC_Br5595"),
    "Br8100": dict(ref=DATA / "DLPFC_151673.h5ad", mov=DATA / "DLPFC_151674.h5ad",
                   condition="held-out", prior="DLPFC_Br8100"),
}
SEVERITIES = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
SEEDS = [0, 1, 2]


def eval_new_model(checkpoint="arca_shared_basis.pt"):
    ck = torch.load(RESULTS / checkpoint, map_location="cpu", weights_only=False)
    a = ck["args"]
    basis = load_basis(ROOT / ck.get("basis_path", "results/shared_basis.npz"))
    model = ARCACrossNet(ck["dim"], a["hidden"], a["layers"], a["attn_dim"])
    model.load_state_dict(ck["state_dict"])
    model.eval()

    rows = []
    for name, meta in DONORS.items():
        A = ad.read_h5ad(meta["ref"]); B0 = ad.read_h5ad(meta["mov"])
        A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
        B0.obsm["spatial"] = np.asarray(B0.obsm["spatial"], float)
        coords = A.obsm["spatial"]
        pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
        Z_A, Z_B = transform(A, basis), transform(B0, basis)
        ga = graph_tensors(coords, Z_A, a["knn"], pitch)
        a_norm = torch.from_numpy((coords / pitch).astype(np.float32))
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
                    severity=sev, method="sutura_shared", seed=seed,
                    median_error=round(st["median"], 2),
                    median_error_pitch=round(st["median"] / pitch, 3),
                    mean_error=round(st["mean"], 2), p90_error=round(st["p90"], 2),
                    pitch_px=round(pitch, 1), n_scored=st["n"]))
        ev = {s: [r["median_error_pitch"] for r in rows
                  if r["donor"] == name and r["severity"] == s] for s in SEVERITIES}
        print(f"  {name:7s} [{meta['condition']:15s}] sutura_shared median pitch "
              f"sev0={np.mean(ev[0.0]):.2f} sev4={np.mean(ev[4.0]):.2f} "
              f"sev8={np.mean(ev[8.0]):.2f}")
    return rows


def ingest_prior():
    """Old per-SVD model + PASTE2 from the prior full-resolution sweep."""
    src = RESULTS / "generalization_sweep.csv"
    if not src.exists():
        print("  (prior generalization_sweep.csv not found; skipping ingest)")
        return []
    prior2donor = {m["prior"]: (n, m["condition"]) for n, m in DONORS.items()}
    method_map = {"sutura": "sutura_persvd", "paste2": "paste2"}
    rows = []
    for r in csv.DictReader(open(src)):
        if r["dataset"] not in prior2donor:
            continue
        donor, cond = prior2donor[r["dataset"]]
        rows.append(dict(
            donor=donor, condition=cond, mode="cross",
            severity=float(r["severity"]), method=method_map[r["method"]],
            seed=int(r["seed"]), median_error=float(r["median_error"]),
            median_error_pitch=float(r["median_error_pitch"]),
            mean_error=float(r["mean_error"]), p90_error=float(r["p90_error"]),
            pitch_px=float(r["pitch_px"]), n_scored=int(r["n_scored"])))
    return rows


def main():
    print("evaluating shared-basis model + ingesting prior baselines ...")
    rows = eval_new_model() + ingest_prior()
    out = RESULTS / "shared_basis_eval.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {out} ({len(rows)} rows)")

    # console summary: severity-averaged median (pitch) per donor x method
    print(f"\n{'donor':8s} {'condition':16s} {'method':15s} {'med(pitch)':>10s}")
    import collections
    agg = collections.defaultdict(list)
    for r in rows:
        agg[(r["donor"], r["condition"], r["method"])].append(r["median_error_pitch"])
    for (d, c, m), v in sorted(agg.items()):
        print(f"{d:8s} {c:16s} {m:15s} {np.mean(v):10.2f}")


if __name__ == "__main__":
    main()
