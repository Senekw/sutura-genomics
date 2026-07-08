"""
Auto-adapt agent for the Sutura orchestrator (branch: autoadapt).

When the distribution check flags an input as off-distribution, instead of only
falling back to PASTE2 we try to ADAPT the pretrained shared-basis Sutura model to
the user's own tissue, then keep whichever of {zero-shot Sutura, auto-adapted
Sutura, PASTE2} scores best on the target pair.

Adaptation (frozen shared basis kept throughout - transform only, never refit):
  - start from the pretrained shared-basis checkpoint (results/arca_shared_basis.pt)
  - fine-tune for a few epochs on ADAPTATION DATA drawn from the user's OWN sections,
    holding out the target pair to be solved:
      * if extra adjacent sections exist  -> supervised cross-section fine-tune on
        them (array-bridge GT), e.g. Br8100 adapts on 151675/676, solves 151673/674
      * else                              -> self-supervised fine-tune on synthetic
        tears of one section (GT = its own pre-warp coords)
  - early-stop on a held-out validation split of the adaptation data
Applicability: the frozen basis is the DLPFC gene panel, so adaptation is only
meaningful when the input shares that panel (gene overlap high). With ~0 overlap
(e.g. mouse) the shared-basis features are all-zero and adaptation is skipped.

The target pair's real A<->B correspondence is NEVER used for adaptation (only for
final scoring), so there is no leakage of the answer being solved.

Usage:
  python src/autoadapt.py                 # validate on Br8100, mouse, breast
"""
from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from pathlib import Path

import anndata as ad
import numpy as np
import torch
from scipy.spatial import cKDTree

from train_cross import ARCACrossNet, graph_tensors, array_bridge
from warp_slice import apply_warp
from scoring import registration_error_stats, barycentric_projection
from shared_basis import load_basis, transform

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXT = DATA / "external"
RESULTS = ROOT / "results"


@dataclass
class AdaptConfig:
    epochs: int = 30
    steps_per_epoch: int = 12
    lr: float = 1e-3
    max_severity: float = 8.0
    tear_prob: float = 0.5
    patience: int = 4          # early-stop patience (val checks)
    eval_every: int = 2
    knn: int = 6
    min_gene_overlap: float = 0.5
    val_severities: tuple = (2.0, 6.0)
    score_severity: float = 4.0   # target-pair tear severity used for final scoring
    score_seed: int = 0
    base_ckpt: str = "arca_shared_basis.pt"


# datasets: target pair + adaptation spec
DATASETS = {
    "Br8100": dict(  # held-out DLPFC donor; has extra sibling sections
        ref=DATA / "DLPFC_151673.h5ad", mov=DATA / "DLPFC_151674.h5ad",
        adapt_mode="cross", adapt_ref=DATA / "DLPFC_151675.h5ad",
        adapt_mov=DATA / "DLPFC_151676.h5ad", tissue="human DLPFC",
        prior="DLPFC_Br8100"),
    "mouse": dict(   # no shared genes -> adaptation inapplicable
        ref=EXT / "V1_Mouse_Brain_Sagittal_Posterior.h5ad",
        mov=EXT / "V1_Mouse_Brain_Sagittal_Posterior_Section_2.h5ad",
        adapt_mode="self", adapt_ref=EXT / "V1_Mouse_Brain_Sagittal_Posterior.h5ad",
        adapt_mov=None, tissue="mouse brain", prior="MouseBrain_SagPost"),
    "breast": dict(  # 95% gene overlap; only the target pair -> self-supervised
        ref=EXT / "V1_Breast_Cancer_Block_A_Section_1.h5ad",
        mov=EXT / "V1_Breast_Cancer_Block_A_Section_2.h5ad",
        adapt_mode="self", adapt_ref=EXT / "V1_Breast_Cancer_Block_A_Section_1.h5ad",
        adapt_mov=None, tissue="human breast cancer", prior="BreastCancer_BlockA"),
}


def _pitch(coords):
    return float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))


def _load(p):
    a = ad.read_h5ad(p)
    a.obsm["spatial"] = np.asarray(a.obsm["spatial"], float)
    return a


def _overlap(a, basis):
    gset = set(basis["genes"])
    return float(np.mean([g in gset for g in a.var_names]))


def load_model(state, dim, hp):
    m = ARCACrossNet(dim, hp["hidden"], hp["layers"], hp["attn_dim"])
    m.load_state_dict(state); m.eval()
    return m


def align_median(model, ref, mov, basis, knn, severity, seed):
    """Median registration error (pitch) of model on (ref, warped mov) vs bridge GT."""
    coords = ref.obsm["spatial"]; pitch = _pitch(coords)
    Z_A = transform(ref, basis); Z_B = transform(mov, basis)
    ga = graph_tensors(coords, Z_A, knn, pitch)
    a_norm = torch.from_numpy((coords / pitch).astype(np.float32))
    gt_A, have = array_bridge(ref, mov)
    w, _ = apply_warp(mov, severity, seed=seed, tear=True)
    gb = graph_tensors(np.asarray(w.obsm["spatial"], float), Z_B, knn, pitch)
    with torch.no_grad():
        pred = model(ga, gb, a_norm).numpy() * pitch
    return registration_error_stats(pred, gt_A, mask=have)["median"] / pitch


def finetune(base_state, dim, hp, ds, basis, cfg):
    """Fine-tune from base checkpoint on the user's adaptation data; early-stop."""
    model = load_model(base_state, dim, hp)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr)
    rng = np.random.default_rng(0); torch.manual_seed(0)

    ref = _load(ds["adapt_ref"])
    mov = _load(ds["adapt_mov"]) if ds["adapt_mode"] == "cross" else ref
    coords = ref.obsm["spatial"]; pitch = _pitch(coords)
    Z_A = transform(ref, basis); Z_B = transform(mov, basis)
    ga = graph_tensors(coords, Z_A, cfg.knn, pitch)
    a_norm = torch.from_numpy((coords / pitch).astype(np.float32))
    if ds["adapt_mode"] == "cross":
        gt_A, have = array_bridge(ref, mov)
    else:  # self: moving is a warped copy of ref; GT is ref's own coords
        gt_A, have = coords.copy(), np.ones(ref.n_obs, bool)
    gt_norm = torch.from_numpy((gt_A / pitch).astype(np.float32))
    mask = torch.from_numpy(have)

    def val_score():
        model.eval(); errs = []
        for sv in cfg.val_severities:
            w, _ = apply_warp(mov, sv, seed=777, tear=True)  # val seed disjoint
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), Z_B, cfg.knn, pitch)
            with torch.no_grad():
                pred = model(ga, gb, a_norm).numpy() * pitch
            errs.append(registration_error_stats(pred, gt_A, mask=have)["median"] / pitch)
        return float(np.mean(errs))

    t0 = time.time()
    best_val = val_score(); best_state = {k: v.clone() for k, v in model.state_dict().items()}
    bad = 0
    for epoch in range(cfg.epochs):
        model.train()
        for _ in range(cfg.steps_per_epoch):
            sv = float(rng.uniform(0, cfg.max_severity))
            w, _ = apply_warp(mov, sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < cfg.tear_prob))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), Z_B, cfg.knn, pitch)
            opt.zero_grad()
            loss = (model(ga, gb, a_norm) - gt_norm)[mask].norm(dim=1).mean()
            loss.backward(); opt.step()
        if epoch % cfg.eval_every == 0 or epoch == cfg.epochs - 1:
            v = val_score()
            if v < best_val - 1e-3:
                best_val = v; bad = 0
                best_state = {k: val.clone() for k, val in model.state_dict().items()}
            else:
                bad += 1
                if bad >= cfg.patience:
                    break
    model.load_state_dict(best_state); model.eval()
    return model, time.time() - t0, best_val, epoch + 1


def paste2_median(ds, cfg, use_cache=True):
    key_src = RESULTS / "generalization_sweep.csv"
    if use_cache and key_src.exists():
        for r in csv.DictReader(open(key_src)):
            if (r["dataset"] == ds["prior"] and r["method"] == "paste2" and
                    float(r["severity"]) == cfg.score_severity and int(r["seed"]) == 0):
                return float(r["median_error_pitch"])
    # live fallback
    from paste2.PASTE2 import partial_pairwise_align
    from paste2.helper import filter_for_common_genes
    ref = _load(ds["ref"]); mov = _load(ds["mov"])
    coords = ref.obsm["spatial"]; pitch = _pitch(coords)
    gt_A, have = array_bridge(ref, mov)
    w, _ = apply_warp(mov, cfg.score_severity, seed=cfg.score_seed, tear=True)
    Aa, Bb = ref.copy(), w.copy(); filter_for_common_genes([Aa, Bb])
    pi = np.asarray(partial_pairwise_align(Aa, Bb, s=0.99, alpha=0.1,
                                           dissimilarity="pca", verbose=False))
    pb, cm = barycentric_projection(pi, Aa.obsm["spatial"])
    return registration_error_stats(pb, gt_A, mask=have & (cm > 0))["median"] / pitch


def run_autoadapt(name, cfg, basis, base_ck, use_cache=True):
    ds = DATASETS[name]
    hp = base_ck["args"]; dim = base_ck["dim"]; base_state = base_ck["state_dict"]
    ref = _load(ds["ref"]); mov = _load(ds["mov"])
    overlap = min(_overlap(ref, basis), _overlap(mov, basis))

    zero = load_model(base_state, dim, hp)
    zs = (align_median(zero, ref, mov, basis, cfg.knn, cfg.score_severity, cfg.score_seed)
          if overlap >= cfg.min_gene_overlap else float("nan"))
    p2 = paste2_median(ds, cfg, use_cache)

    if overlap >= cfg.min_gene_overlap:
        model, adapt_t, val, eps = finetune(base_state, dim, hp, ds, basis, cfg)
        adp = align_median(model, ref, mov, basis, cfg.knn, cfg.score_severity, cfg.score_seed)
        adapt_applicable = True
    else:
        adp, adapt_t, val, eps = float("nan"), 0.0, float("nan"), 0
        adapt_applicable = False

    cands = {"sutura_zeroshot": zs, "sutura_adapted": adp, "paste2": p2}
    valid = {k: v for k, v in cands.items() if np.isfinite(v)}
    best = min(valid, key=valid.get)
    return dict(
        dataset=name, tissue=ds["tissue"], adapt_mode=ds["adapt_mode"],
        gene_overlap=round(overlap, 3), adapt_applicable=adapt_applicable,
        sutura_zeroshot=None if np.isnan(zs) else round(zs, 3),
        sutura_adapted=None if np.isnan(adp) else round(adp, 3),
        paste2=round(p2, 3), best_method=best, best_error=round(valid[best], 3),
        adapt_seconds=round(adapt_t, 1), adapt_epochs=eps,
        adapt_beats_paste2=bool(np.isfinite(adp) and adp < p2),
        severity=cfg.score_severity, seed=cfg.score_seed)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", default="")
    p.add_argument("--no-paste2-cache", action="store_true")
    p.add_argument("--out", default="autoadapt_eval.csv")
    args = p.parse_args()
    cfg = AdaptConfig()
    basis = load_basis()
    base_ck = torch.load(RESULTS / cfg.base_ckpt, map_location="cpu", weights_only=False)
    names = [n for n in DATASETS if not args.only or n in args.only.split(",")]

    rows = []
    for name in names:
        print(f"\n=== auto-adapt: {name} ===", flush=True)
        r = run_autoadapt(name, cfg, basis, base_ck, not args.no_paste2_cache)
        rows.append(r)
        print(f"  overlap={r['gene_overlap']} applicable={r['adapt_applicable']}")
        print(f"  zero-shot Sutura={r['sutura_zeroshot']}  adapted Sutura={r['sutura_adapted']}"
              f"  PASTE2={r['paste2']}  ({r['adapt_epochs']} ep, {r['adapt_seconds']}s)")
        print(f"  -> BEST: {r['best_method']} ({r['best_error']} pitch); "
              f"adapt beats PASTE2: {r['adapt_beats_paste2']}")

    cols = list(rows[0].keys())
    with open(RESULTS / args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print(f"\nwrote {RESULTS / args.out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
