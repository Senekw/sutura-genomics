"""
Core alignment pipeline for the Sutura backend (deployment-agnostic; no web deps).

Runs the orchestrator on a REAL uploaded pair of adjacent sections (no synthetic
warp): load & QC -> distribution check (frozen shared basis, Mahalanobis to the
training distribution) -> route (in-dist Sutura / off-dist auto-adapt->PASTE2) ->
post-QC -> write aligned output + metrics. Honesty: the exact method that produced
the result is recorded and returned.

Reused by both the local FastAPI app (backend/app.py) and the Modal deployment
(backend/modal_app.py). Imports the research code from ../src.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import anndata as ad
import numpy as np
import torch
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
RESULTS = ROOT / "results"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from train_cross import ARCACrossNet, graph_tensors, array_bridge          # noqa: E402
from scoring import registration_error_stats, barycentric_projection       # noqa: E402
from shared_basis import load_basis, transform                             # noqa: E402
from orchestrator import Projector, OrchestratorConfig, distribution_check, \
    footprint_coverage_proxy                                               # noqa: E402
import autoadapt                                                           # noqa: E402

MIN_SPOTS = 100
MAX_SPOTS = 200_000


# --------------------------------------------------------------------------- #
# validation / QC
# --------------------------------------------------------------------------- #
def qc_file(path):
    """Validate one uploaded .h5ad. Returns (adata_or_None, error_or_None)."""
    try:
        a = ad.read_h5ad(path)
    except Exception as e:
        return None, f"not a readable .h5ad file ({type(e).__name__}: {e})"
    if "spatial" not in a.obsm:
        return None, "missing obsm['spatial'] spatial coordinates"
    coords = np.asarray(a.obsm["spatial"], float)
    if coords.ndim != 2 or coords.shape[1] < 2:
        return None, "obsm['spatial'] is not an (n, 2) coordinate array"
    if a.n_obs < MIN_SPOTS:
        return None, f"only {a.n_obs} spots (minimum {MIN_SPOTS})"
    if a.n_obs > MAX_SPOTS:
        return None, f"{a.n_obs} spots exceeds limit {MAX_SPOTS}"
    if a.n_vars == 0:
        return None, "no genes in the expression matrix"
    a.obsm["spatial"] = coords
    return a, None


# --------------------------------------------------------------------------- #
# real-pair alignment (no synthetic warp) + scoring
# --------------------------------------------------------------------------- #
def _score(pred, ref, mov, pitch):
    """median error vs array-bridge GT if derivable, else footprint proxy."""
    if {"array_row", "array_col"} <= set(ref.obs.columns) <= set(ref.obs.columns) and \
       {"array_row", "array_col"} <= set(mov.obs.columns):
        gt, have = array_bridge(ref, mov)
        if have.sum() >= 0.5 * mov.n_obs:
            med = registration_error_stats(pred, gt, mask=have)["median"] / pitch
            return {"metric": "median_error_pitch", "value": round(float(med), 3),
                    "has_ground_truth": True,
                    "coverage": round(footprint_coverage_proxy(pred, ref.obsm["spatial"]), 3)}
    cov = footprint_coverage_proxy(pred, ref.obsm["spatial"])
    return {"metric": "footprint_coverage", "value": round(float(cov), 3),
            "has_ground_truth": False, "coverage": round(float(cov), 3)}


def align_sutura(model, ref, mov, basis, knn):
    coords = ref.obsm["spatial"]; pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    ga = graph_tensors(coords, transform(ref, basis), knn, pitch)
    a_norm = torch.from_numpy((coords / pitch).astype(np.float32))
    gb = graph_tensors(np.asarray(mov.obsm["spatial"], float), transform(mov, basis), knn, pitch)
    with torch.no_grad():
        pred = model(ga, gb, a_norm).numpy() * pitch
    return pred, pitch


def align_paste2(ref, mov):
    from paste2.PASTE2 import partial_pairwise_align
    from paste2.helper import filter_for_common_genes
    coords = ref.obsm["spatial"]; pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    Aa, Bb = ref.copy(), mov.copy()
    filter_for_common_genes([Aa, Bb])
    pi = np.asarray(partial_pairwise_align(Aa, Bb, s=0.99, alpha=0.1,
                                           dissimilarity="pca", verbose=False))
    pred, cm = barycentric_projection(pi, Aa.obsm["spatial"])
    # fill any zero-mass columns with the reference centroid to keep output finite
    bad = ~np.isfinite(pred).all(1)
    if bad.any():
        pred[bad] = coords.mean(0)
    return pred, pitch


# --------------------------------------------------------------------------- #
# orchestration (the job worker calls this)
# --------------------------------------------------------------------------- #
def run_alignment(files, out_dir, progress=lambda *_: None):
    """
    files    : list of paths to uploaded .h5ad (>=2; first two are the pair to
               align: ref=files[0], mov=files[1]; any extras are adaptation data).
    out_dir  : directory to write the aligned .h5ad + result.
    progress : callback(stage:str, pct:int) for status updates.
    Returns a result dict (also the API payload).
    """
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    progress("loading", 5)
    if len(files) < 2:
        raise ValueError("need at least 2 sections (a reference and a moving slice)")

    parsed = []
    for f in files:
        a, err = qc_file(f)
        if err:
            raise ValueError(f"{Path(f).name}: {err}")
        parsed.append(a)
    ref, mov = parsed[0], parsed[1]
    extras = parsed[2:]

    cfg = OrchestratorConfig()
    proj = Projector()
    basis = load_basis()
    base_ck = torch.load(RESULTS / cfg.sutura_ckpt, map_location="cpu", weights_only=False)
    hp = base_ck["args"]; dim = base_ck["dim"]; knn = hp["knn"]

    progress("distribution_check", 20)
    dcheck = distribution_check(ref, mov, proj, cfg)

    method_log = []
    t0 = time.time()

    if dcheck["in_distribution"]:
        progress("aligning_sutura", 45)
        model = ARCACrossNet(dim, hp["hidden"], hp["layers"], hp["attn_dim"])
        model.load_state_dict(base_ck["state_dict"]); model.eval()
        pred, pitch = align_sutura(model, ref, mov, basis, knn)
        method = "sutura"
        method_reason = ("in-distribution for the pretrained Sutura model "
                         f"(Mahalanobis {dcheck['maha']} < {cfg.maha_threshold})")
        method_log.append(("sutura", _score(pred, ref, mov, pitch)["value"]))
    else:
        # off-distribution: try auto-adapt (if gene panel compatible), else PASTE2
        progress("auto_adapt", 45)
        candidates = {}
        overlap = dcheck["gene_overlap"]
        # zero-shot Sutura (only meaningful with gene overlap)
        model0 = ARCACrossNet(dim, hp["hidden"], hp["layers"], hp["attn_dim"])
        model0.load_state_dict(base_ck["state_dict"]); model0.eval()
        if overlap >= cfg.min_gene_overlap:
            p0, pitch = align_sutura(model0, ref, mov, basis, knn)
            candidates["sutura_zeroshot"] = (p0, _score(p0, ref, mov, pitch))
        adapt_seconds = 0.0
        # auto-adapt: fine-tune on extras if provided, else self-supervised on ref
        if overlap >= cfg.min_gene_overlap:
            acfg = autoadapt.AdaptConfig(base_ckpt=cfg.sutura_ckpt)
            ds = _adapt_spec(ref, mov, extras, out_dir)
            madapt, adapt_seconds, _, eps = autoadapt.finetune(
                base_ck["state_dict"], dim, hp, ds, basis, acfg)
            pa, pitch = align_sutura(madapt, ref, mov, basis, knn)
            candidates["sutura_adapted"] = (pa, _score(pa, ref, mov, pitch))
            method_log.append(("auto_adapt_epochs", eps))
        progress("aligning_paste2", 70)
        pp, pitch = align_paste2(ref, mov)
        candidates["paste2"] = (pp, _score(pp, ref, mov, pitch))

        # keep the best (lower error, or higher coverage when no GT)
        def rank(item):
            _, sc = item[1]
            return sc["value"] if sc["has_ground_truth"] else -sc["value"]
        best_name, (pred, best_sc) = min(candidates.items(), key=rank)
        method = best_name; pitch = pitch
        method_reason = (f"off-distribution (Mahalanobis {dcheck['maha']}, gene "
                         f"overlap {int(overlap*100)}%); auto-adapt "
                         f"{'ran' if overlap >= cfg.min_gene_overlap else 'not applicable'}; "
                         f"kept the best of {list(candidates)}")
        method_log += [(k, round(v[1]['value'], 3)) for k, v in candidates.items()]

    score = _score(pred, ref, mov, pitch)
    # post-alignment QC + retry safety net (only when a GT metric flags failure)
    retry = False
    if score.get("has_ground_truth") and score["value"] > cfg.retry_error_pitch \
            and method != "paste2":
        progress("post_qc_retry", 85)
        pp, pitch = align_paste2(ref, mov)
        sc2 = _score(pp, ref, mov, pitch)
        retry = True
        if sc2["value"] < score["value"]:
            pred, score, method = pp, sc2, "paste2"
            method_reason += " | post-QC retry: PASTE2 was better, kept it"

    progress("writing_output", 92)
    aligned = mov.copy()
    aligned.obsm["spatial_aligned"] = pred.astype(np.float32)
    aligned.uns["sutura_alignment"] = {
        "method": method, "reason": method_reason,
        "in_distribution": dcheck["in_distribution"],
        "in_dist_confidence": dcheck["confidence"], "metric": score["metric"],
        "score": score["value"], "has_ground_truth": score["has_ground_truth"]}
    out_h5ad = out_dir / "aligned.h5ad"
    aligned.write_h5ad(out_h5ad)

    result = {
        "method": method,
        "method_label": {"sutura": "Sutura", "sutura_zeroshot": "Sutura (zero-shot)",
                         "sutura_adapted": "Sutura (auto-adapted to your data)",
                         "paste2": "PASTE2"}.get(method, method),
        "reason": method_reason,
        "in_distribution": dcheck["in_distribution"],
        "in_dist_confidence": dcheck["confidence"],
        "mahalanobis": dcheck["maha"], "gene_overlap": dcheck["gene_overlap"],
        "metric": score["metric"], "score": score["value"],
        "has_ground_truth": score["has_ground_truth"],
        "footprint_coverage": score["coverage"],
        "retry": retry, "candidates": method_log,
        "n_ref": int(ref.n_obs), "n_mov": int(mov.n_obs),
        "runtime_seconds": round(time.time() - t0, 1),
        "output_file": "aligned.h5ad",
        "aligned_coords": pred.astype(float).round(1).tolist(),
        "ref_coords": np.asarray(ref.obsm["spatial"], float).round(1).tolist(),
    }
    progress("done", 100)
    return result


def _adapt_spec(ref, mov, extras, out_dir):
    """Build an autoadapt.DATASETS-style spec from uploaded sections."""
    if len(extras) >= 2:                         # extra adjacent sections -> supervised
        r = out_dir / "_adapt_ref.h5ad"; m = out_dir / "_adapt_mov.h5ad"
        extras[0].write_h5ad(r); extras[1].write_h5ad(m)
        return dict(adapt_mode="cross", adapt_ref=r, adapt_mov=m)
    rp = out_dir / "_adapt_self.h5ad"; ref.write_h5ad(rp)   # self-supervised on ref
    return dict(adapt_mode="self", adapt_ref=rp, adapt_mov=None)
