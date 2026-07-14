"""
Hybrid OT + learned tear-handling — leave-one-donor-out cross-donor experiment.

Diagnosis (research/FINDINGS_cross_donor_gap_summary.md): our supervised shared-basis
model lacks an explicit cross-dataset correspondence prior — the thing optimal transport
(PASTE2) supplies for free, and why PASTE2 generalizes to a held-out donor while we don't
(held-out ~8.26 spot-pitch vs PASTE2 ~4.36). This script bakes an OT correspondence prior
into the ARCA graph model three ways and asks the only question that matters: does any
hybrid beat PASTE2 (~4.36) on a HELD-OUT donor?

The OT prior here is an entropic-OT correspondence on the shared expression features
(POT ot.sinkhorn), which is the cross-dataset signal PASTE2's FGW leans on. Because it is
expression-based it is WARP-INVARIANT — computed once per pair, so it adds ~no per-step
cost. (This is a fast surrogate for PASTE2's full fused-Gromov-Wasserstein; noted as a
limitation in FINDINGS.)

Variants (each trained with the IDENTICAL LODO protocol as train_cross_loo.py so numbers
are comparable):
  pure_ot     — use the OT correspondence coordinate directly as the prediction (no NN).
  ot_init     — model's coarse coordinate = the OT coordinate; NN learns the residual that
                handles the tear discontinuity OT can't. (subclass, no edit to base model)
  ot_aux      — plain model + an auxiliary loss pulling the model's attention-coordinate
                toward the OT coordinate. (NOTE: no tear-masking yet — see FINDINGS.)
  ot_features — feed the OT coordinate + confidence into the encoder as extra node features.

Eval identical to prior: severities 0,1,2,3,4,6,8 (tear), fixed eval-seed 0, median
registration error; reported in SPOT-PITCH units (px / pitch) to compare to 8.26 / 4.36.

Robustness: each (variant × fold) is wrapped in try/except; results append to
research/results/hybrid_ot.csv after every cell; progress logs to hybrid_ot.log.

Run:  python src/hybrid_ot.py --all            # full sweep (detached-friendly)
      python src/hybrid_ot.py --variant ot_init --fold S1 --epochs 5   # single smoke run
"""
from __future__ import annotations

import argparse
import csv
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import ot
import torch

from train_cross import ARCACrossNet, graph_tensors
from train_cross_loo import (fit_shared_basis, build_pair, warp_graph, parse_pairs)
from scoring import registration_error_stats

import anndata as ad

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS = ROOT / "research" / "results"
LOG = RESULTS / "hybrid_ot.log"
CSV = RESULTS / "hybrid_ot.csv"

# 3 DLPFC donors, one pair each (matches train_cross_loo / run_loo_3donor)
PAIRS = {"S1": ("151507", "151508"),   # Br5292
         "S2": ("151669", "151670"),   # Br5595
         "S3": ("151673", "151674")}   # Br8100
FOLDS = [("S1", ["S2", "S3"]), ("S2", ["S1", "S3"]), ("S3", ["S1", "S2"])]
VARIANTS = ["pure_ot", "ot_init", "ot_aux", "ot_features"]
CSV_FIELDS = ["variant", "fold", "held_out", "severity", "reg_err_median_px",
              "reg_err_median_pitch", "reg_err_mean_px", "n", "pitch", "status", "timestamp"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    RESULTS.mkdir(parents=True, exist_ok=True)
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="ascii", errors="replace") as fh:
        fh.write(line + "\n")


def append_rows(rows):
    RESULTS.mkdir(parents=True, exist_ok=True)
    exists = CSV.exists()
    with open(CSV, "a", newline="", encoding="ascii", errors="replace") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if not exists:
            w.writeheader()
        w.writerows(rows)


# --------------------------------------------------------------------------- #
# OT correspondence prior (expression-feature entropic OT; warp-invariant)
# --------------------------------------------------------------------------- #
def ot_coordinate(Z_B, Z_A, a_coords_norm, reg=0.01):
    """Entropic-OT coupling on expression features -> per-B-spot A-frame coordinate
    (pitch units) + a per-spot confidence (row max of the row-normalized coupling)."""
    M = ot.dist(np.asarray(Z_B, np.float64), np.asarray(Z_A, np.float64), metric="sqeuclidean")
    M /= (M.max() + 1e-9)
    a = np.full(Z_B.shape[0], 1.0 / Z_B.shape[0])
    b = np.full(Z_A.shape[0], 1.0 / Z_A.shape[0])
    P = ot.sinkhorn(a, b, M, reg, numItermax=500)
    P = P / (P.sum(1, keepdims=True) + 1e-12)
    coord = (P @ np.asarray(a_coords_norm, np.float64)).astype(np.float32)   # (nB,2) pitch units
    conf = P.max(1).astype(np.float32)                                        # (nB,)
    return coord, conf


# --------------------------------------------------------------------------- #
# ot_init model: identical to ARCACrossNet but coarse := OT coordinate
# --------------------------------------------------------------------------- #
class OTInitNet(ARCACrossNet):
    def forward(self, ga, gb, a_coords_norm, ot_coarse):
        z_a = self.encoder(ga["x"], ga["edge_index"], ga["edge_attr"])
        z_b = self.encoder(gb["x"], gb["edge_index"], gb["edge_attr"])
        qb, ka = self.q(z_b), self.k(z_a)
        attn = torch.softmax((qb @ ka.T) * self.scale, dim=1)
        attended_za = attn @ self.v(z_a)
        coarse = ot_coarse                                    # OT prior, not attn@coords
        residual = self.head(torch.cat([z_b, attended_za, coarse], dim=-1))
        return coarse + residual


def reg_stats_pitch(pred_px, gt_px, have, pitch):
    st = registration_error_stats(pred_px, gt_px, mask=have)
    return st, st["median"] / pitch


# --------------------------------------------------------------------------- #
# per-(variant,fold) run
# --------------------------------------------------------------------------- #
def run_cell(variant, fold_tag, train_tags, epochs, steps, lr, knn, pca_dim,
             feature_mode, eval_sev, eval_seed, seed):
    t0 = time.time()
    train_pairs = [PAIRS[t] for t in train_tags]
    test_ref, test_smp = PAIRS[fold_tag]

    # load slices, fit shared basis on TRAIN slices only (unchanged protocol)
    train_slices = []
    for ref, smp in train_pairs:
        train_slices.append(ad.read_h5ad(DATA_DIR / f"DLPFC_{ref}.h5ad"))
        train_slices.append(ad.read_h5ad(DATA_DIR / f"DLPFC_{smp}.h5ad"))
    project = fit_shared_basis(train_slices, pca_dim, seed, feature_mode=feature_mode)
    pairs = [build_pair(ref, smp, project, knn) for ref, smp in train_pairs]
    test = build_pair(test_ref, test_smp, project, knn)

    # OT coordinate (warp-invariant) for every pair, once
    def add_ot(pr):
        Z_A = pr["ga"]["x"].numpy()
        coord, conf = ot_coordinate(pr["Z_B"], Z_A, pr["a_norm"].numpy())
        pr["ot_coarse"] = torch.from_numpy(coord)
        pr["ot_conf"] = conf
        return pr
    for pr in pairs:
        add_ot(pr)
    add_ot(test)

    feat_dim = pca_dim
    extra = 0
    if variant == "ot_features":
        extra = 3  # ot_coord(2) + conf(1)
        feat_dim = pca_dim + extra

    def aug_graph(pr, coords_np, warp_ot_coarse):
        """Rebuild B graph tensors, optionally augmenting features for ot_features."""
        Z = pr["Z_B"]
        if variant == "ot_features":
            Z = np.concatenate([Z, pr["ot_coarse"].numpy(), pr["ot_conf"][:, None]], axis=1).astype(np.float32)
        return graph_tensors(coords_np, Z, knn, pr["pitch"])

    def ga_of(pr):
        if variant != "ot_features":
            return pr["ga"]
        # augment A features symmetrically: A's own coord (identity corr) + conf 1
        Z_A = pr["ga"]["x"].numpy()
        aug = np.concatenate([Z_A, pr["a_norm"].numpy(), np.ones((Z_A.shape[0], 1), np.float32)], axis=1).astype(np.float32)
        return graph_tensors(pr["a_coords"], aug, knn, pr["pitch"])

    # ---------- pure OT: no training ----------
    if variant == "pure_ot":
        rows = []
        for sv in eval_sev:
            pred = test["ot_coarse"].numpy() * test["pitch"]   # OT coord is warp-invariant
            st, med_pitch = reg_stats_pitch(pred, test["gt_A"], test["have"], test["pitch"])
            rows.append(_row(variant, fold_tag, test, sv, st, med_pitch, "ok"))
        log(f"{variant} {fold_tag}: median(pitch) sev-mean="
            f"{np.mean([r['reg_err_median_pitch'] for r in rows]):.2f}  ({time.time()-t0:.0f}s)")
        return rows

    # ---------- build model ----------
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    if variant == "ot_init":
        model = OTInitNet(feat_dim, 64, 3, 64)
    else:
        model = ARCACrossNet(feat_dim, 64, 3, 64)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lam = 0.5  # ot_aux weight

    for epoch in range(epochs):
        model.train()
        for _ in range(steps):
            pr = pairs[int(rng.integers(0, len(pairs)))]
            sv = float(rng.uniform(0, 8.0))
            from warp_slice import apply_warp
            w, _ = apply_warp(pr["B"], sv, seed=int(rng.integers(1, 9999)),
                              tear=bool(rng.random() < 0.5))
            coords_np = np.asarray(w.obsm["spatial"], np.float32)
            gb = aug_graph(pr, coords_np, None)
            opt.zero_grad()
            if variant == "ot_init":
                pred = model(ga_of(pr), gb, pr["a_norm"], pr["ot_coarse"])
                loss = (pred - pr["gt_norm"])[pr["mask"]].norm(dim=1).mean()
            elif variant == "ot_aux":
                pred, match = model(ga_of(pr), gb, pr["a_norm"], return_match=True)
                attn = torch.softmax(match["attn_logits"], dim=1)
                attn_coord = attn @ pr["a_norm"]
                main = (pred - pr["gt_norm"])[pr["mask"]].norm(dim=1).mean()
                aux = (attn_coord - pr["ot_coarse"])[pr["mask"]].norm(dim=1).mean()
                loss = main + lam * aux
            else:  # ot_features (features already carry OT; plain forward)
                pred = model(ga_of(pr), gb, pr["a_norm"])
                loss = (pred - pr["gt_norm"])[pr["mask"]].norm(dim=1).mean()
            loss.backward()
            opt.step()

    # ---------- eval on held-out donor ----------
    from warp_slice import apply_warp
    model.eval()
    rows = []
    for sv in eval_sev:
        w, _ = apply_warp(test["B"], sv, seed=eval_seed, tear=True)
        coords_np = np.asarray(w.obsm["spatial"], np.float32)
        gb = aug_graph(test, coords_np, None)
        with torch.no_grad():
            if variant == "ot_init":
                pred = model(ga_of(test), gb, test["a_norm"], test["ot_coarse"]).numpy() * test["pitch"]
            else:
                pred = model(ga_of(test), gb, test["a_norm"]).numpy() * test["pitch"]
        st, med_pitch = reg_stats_pitch(pred, test["gt_A"], test["have"], test["pitch"])
        rows.append(_row(variant, fold_tag, test, sv, st, med_pitch, "ok"))
    log(f"{variant} {fold_tag}: median(pitch) sev-mean="
        f"{np.mean([r['reg_err_median_pitch'] for r in rows]):.2f}  ({time.time()-t0:.0f}s)")
    return rows


def _row(variant, fold_tag, test, sv, st, med_pitch, status):
    return {"variant": variant, "fold": fold_tag,
            "held_out": f"{test['ref']}/{test['smp']}", "severity": sv,
            "reg_err_median_px": round(st["median"], 2),
            "reg_err_median_pitch": round(med_pitch, 3),
            "reg_err_mean_px": round(st["mean"], 2), "n": st["n"],
            "pitch": round(test["pitch"], 1), "status": status,
            "timestamp": now()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true", help="run every variant x fold")
    p.add_argument("--variant", choices=VARIANTS)
    p.add_argument("--fold", choices=list(PAIRS.keys()))
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--steps", type=int, default=24)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--knn", type=int, default=6)
    p.add_argument("--pca-dim", type=int, default=50)
    p.add_argument("--feature-mode", default="perslice", choices=["global", "perslice"])
    p.add_argument("--eval-severities", default="0,1,2,3,4,6,8")
    p.add_argument("--eval-seed", type=int, default=0)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    eval_sev = [float(x) for x in args.eval_severities.split(",")]

    if args.all:
        combos = [(v, f, tr) for v in VARIANTS for (f, tr) in FOLDS]
    else:
        if not (args.variant and args.fold):
            p.error("pass --all, or both --variant and --fold")
        tr = dict(FOLDS)[args.fold]
        combos = [(args.variant, args.fold, tr)]

    log(f"=== hybrid_ot START ({len(combos)} cells) mode={args.feature_mode} "
        f"epochs={args.epochs} steps={args.steps} ===")
    ok = fail = 0
    for variant, fold_tag, train_tags in combos:
        try:
            rows = run_cell(variant, fold_tag, train_tags, args.epochs, args.steps,
                            args.lr, args.knn, args.pca_dim, args.feature_mode,
                            eval_sev, args.eval_seed, args.seed)
            append_rows(rows)
            ok += 1
        except Exception as e:
            fail += 1
            log(f"  !! FAILED {variant} {fold_tag}: {type(e).__name__}: {e}")
            log(traceback.format_exc())
            append_rows([{"variant": variant, "fold": fold_tag, "held_out": "",
                          "severity": "", "reg_err_median_px": "",
                          "reg_err_median_pitch": "", "reg_err_mean_px": "", "n": "",
                          "pitch": "", "status": f"FAILED: {type(e).__name__}: {e}"[:120],
                          "timestamp": now()}])
    log(f"=== hybrid_ot DONE ok={ok} fail={fail} -> {CSV} ===")


if __name__ == "__main__":
    main()
