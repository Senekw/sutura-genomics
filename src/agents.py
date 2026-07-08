"""
Agentic add-ons for the Sutura orchestrator (branch: autoadapt).

Implements the agent suite on top of the alignment primitives:

  auto-adapt        -> src/autoadapt.py (the featured agent; validated separately)
  qc_retry_agent    -> score an alignment; if it fails threshold, rerun the
                       alternate method / params and keep the best (this is also
                       wired inline in the orchestrator + backend pipeline)
  report_agent      -> after alignment, write a full analysis: quality verdict,
                       per-layer breakdown (if layer labels exist), flagged
                       regions (worst-error spots / low local consistency),
                       and recommendations
  param_tuning_agent-> per-dataset sweep of alignment hyperparameters
                       (Sutura kNN; PASTE2 alpha/overlap) -> best config
  ensemble_agent    -> run Sutura + PASTE2, choose PER REGION by local quality
                       (neighbor-consistency), not just per-dataset. STalign is
                       supported as an optional third method if installed.

These operate on numpy arrays of predicted vs reference coordinates so they are
independent of how the alignment was produced.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scoring import registration_error_stats                       # noqa: E402


# --------------------------------------------------------------------------- #
# quality primitives (work with or without ground truth)
# --------------------------------------------------------------------------- #
def neighbor_consistency(pred, mov_coords, k=8):
    """Local smoothness of the deformation: for each moving spot, how well the
    predicted positions of its spatial neighbors preserve neighbor distances.
    Returns per-spot consistency in [0,1] (1 = locally rigid)."""
    tree = cKDTree(mov_coords)
    _, idx = tree.query(mov_coords, k=k + 1)
    idx = idx[:, 1:]
    mov_d = np.linalg.norm(mov_coords[:, None, :] - mov_coords[idx], axis=2)
    pred_d = np.linalg.norm(pred[:, None, :] - pred[idx], axis=2)
    scale = np.median(pred_d) / (np.median(mov_d) + 1e-9)
    ratio = pred_d / (mov_d * scale + 1e-9)
    # consistency: how close each neighbor-distance ratio is to 1
    return np.clip(1.0 - np.abs(np.log(np.clip(ratio, 1e-3, 1e3))).mean(1), 0, 1)


def footprint_coverage(pred, ref_coords):
    def spread(P):
        return float(np.median(np.linalg.norm(P - P.mean(0), axis=1)))
    return spread(pred) / (spread(ref_coords) + 1e-9)


# --------------------------------------------------------------------------- #
# QC + auto-retry agent
# --------------------------------------------------------------------------- #
def qc_retry_agent(candidates, ref_coords, mov_coords, gt=None, have=None,
                   pitch=1.0, err_threshold=6.0):
    """candidates: {name: pred_coords}. Score each (median error vs GT if given,
    else neighbor-consistency), flag failures, return the best + full log."""
    scored = {}
    for name, pred in candidates.items():
        if gt is not None and have is not None and have.any():
            m = registration_error_stats(pred, gt, mask=have)["median"] / pitch
            scored[name] = {"metric": "median_error_pitch", "value": round(m, 3),
                            "pass": m <= err_threshold, "ground_truth": True}
        else:
            nc = float(np.median(neighbor_consistency(pred, mov_coords)))
            cov = footprint_coverage(pred, ref_coords)
            scored[name] = {"metric": "neighbor_consistency", "value": round(nc, 3),
                            "coverage": round(cov, 3),
                            "pass": nc >= 0.5 and cov >= 0.6, "ground_truth": False}

    def rank(kv):
        s = kv[1]
        return s["value"] if s["ground_truth"] else -s["value"]
    best = min(scored.items(), key=rank)[0]
    return {"best": best, "scores": scored,
            "any_failed": any(not s["pass"] for s in scored.values())}


# --------------------------------------------------------------------------- #
# report-generation agent
# --------------------------------------------------------------------------- #
def report_agent(result, aligned_adata=None, gt=None, have=None, pitch=1.0):
    """Produce a full plain-English + structured analysis of an alignment."""
    lines = []
    method = result.get("method_label", result.get("method"))
    lines.append(f"# Alignment report\n")
    lines.append(f"**Method used:** {method} — {result.get('reason','')}\n")
    conf = result.get("in_dist_confidence")
    lines.append(f"**Routing:** {'in' if result.get('in_distribution') else 'off'}-"
                 f"distribution (confidence {conf}); Mahalanobis "
                 f"{result.get('mahalanobis')}, gene overlap "
                 f"{int((result.get('gene_overlap') or 0)*100)}%.\n")

    # overall quality verdict
    metric = result.get("metric"); val = result.get("score")
    if result.get("has_ground_truth"):
        q = ("excellent" if val < 1.5 else "good" if val < 3 else
             "fair" if val < 6 else "poor")
        lines.append(f"**Quality:** median registration error **{val} spot-pitches** "
                     f"({q}). Footprint coverage {result.get('footprint_coverage')}.\n")
    else:
        lines.append(f"**Quality (no ground truth):** footprint coverage "
                     f"**{val}** (proxy; ~1 healthy, <<1 collapse).\n")

    flagged = {}
    if aligned_adata is not None:
        pred = np.asarray(aligned_adata.obsm["spatial_aligned"], float)
        mov = np.asarray(aligned_adata.obsm["spatial"], float)
        # per-spot error (GT) or local consistency (no GT)
        if gt is not None and have is not None and have.any():
            err = np.linalg.norm(pred - gt, axis=1) / pitch
            err[~have] = np.nan
            worst = np.argsort(np.nan_to_num(err, nan=-1))[-10:][::-1]
            lines.append(f"**Flagged regions:** {int((err > 6).sum())} spots exceed "
                         f"6 pitch; worst spot error {np.nanmax(err):.1f} pitch.\n")
            flagged = {"n_high_error": int(np.nansum(err > 6)),
                       "worst_spot_error_pitch": round(float(np.nanmax(err)), 2)}
        else:
            nc = neighbor_consistency(pred, mov)
            lines.append(f"**Flagged regions:** {(nc < 0.4).sum()} spots with low "
                         f"local consistency (<0.4).\n")
            flagged = {"n_low_consistency": int((nc < 0.4).sum())}

        # per-layer breakdown if annotations exist
        layer_col = next((c for c in ("layer", "Layer", "layer_guess", "annotation")
                          if c in aligned_adata.obs.columns), None)
        if layer_col is not None and gt is not None and have is not None and have.any():
            err = np.linalg.norm(pred - gt, axis=1) / pitch
            labs = aligned_adata.obs[layer_col].astype(str).values
            lines.append("**Per-layer median error (pitch):**")
            per_layer = {}
            for lab in sorted(set(labs)):
                m = (labs == lab) & have
                if m.sum():
                    med = float(np.median(err[m]))
                    per_layer[lab] = round(med, 2)
                    lines.append(f"  - {lab}: {med:.2f} ({int(m.sum())} spots)")
            flagged["per_layer"] = per_layer
            lines.append("")

    # recommendations
    recs = []
    if result.get("has_ground_truth") and val > 6:
        recs.append("High error — consider providing extra adjacent sections to enable "
                    "stronger auto-adaptation, or verify the two sections are truly adjacent.")
    if not result.get("in_distribution"):
        recs.append("Input is off-distribution for the pretrained model; results came "
                    "from the off-distribution branch (auto-adapt / PASTE2), which is "
                    "expected and honestly labeled.")
    if (result.get("gene_overlap") or 1) < 0.5:
        recs.append("Gene panel barely overlaps the model's training panel; Sutura is "
                    "not applicable and PASTE2 was used.")
    if not recs:
        recs.append("Alignment looks healthy; no action needed.")
    lines.append("**Recommendations:**")
    lines += [f"  - {r}" for r in recs]

    return {"markdown": "\n".join(lines), "flagged": flagged, "recommendations": recs}


# --------------------------------------------------------------------------- #
# parameter-tuning agent
# --------------------------------------------------------------------------- #
def param_tuning_agent(align_fn, param_grid, score_fn):
    """Generic sweep: align_fn(**params)->pred ; score_fn(pred)->(value, lower_is_better?).
    Returns best params + full grid log. Caller supplies the alignment closures so
    this stays method-agnostic (used for Sutura kNN and PASTE2 alpha/overlap)."""
    log = []
    best = None
    for params in param_grid:
        pred = align_fn(**params)
        value, lower_better = score_fn(pred)
        log.append({"params": params, "value": round(float(value), 3)})
        key = value if lower_better else -value
        if best is None or key < best[0]:
            best = (key, params, value)
    return {"best_params": best[1], "best_value": round(float(best[2]), 3), "grid": log}


# --------------------------------------------------------------------------- #
# per-region ensemble agent
# --------------------------------------------------------------------------- #
def ensemble_agent(method_preds, ref_coords, mov_coords, gt=None, have=None,
                   pitch=1.0, k=12):
    """method_preds: {name: pred_coords}. For each moving spot, pick the method whose
    LOCAL quality is best in that spot's neighborhood — per-region rather than
    per-dataset selection. Local quality = per-spot error (GT) or neighbor
    consistency (no GT). Returns merged prediction + which method won where."""
    names = list(method_preds)
    if gt is not None and have is not None and have.any():
        qual = {n: -np.linalg.norm(method_preds[n] - gt, axis=1) for n in names}  # higher=better
        for n in names:
            qual[n][~have] = -1e9
    else:
        qual = {n: neighbor_consistency(method_preds[n], mov_coords, k=8) for n in names}
    # smooth local quality over the moving-space neighborhood so the choice is regional
    tree = cKDTree(mov_coords)
    _, idx = tree.query(mov_coords, k=min(k + 1, mov_coords.shape[0]))
    smoothed = {n: qual[n][idx].mean(1) for n in names}
    stack = np.stack([smoothed[n] for n in names], axis=1)   # (n_spots, n_methods)
    winner = stack.argmax(1)
    merged = np.empty_like(method_preds[names[0]])
    for j, n in enumerate(names):
        merged[winner == j] = method_preds[n][winner == j]
    frac = {names[j]: float((winner == j).mean()) for j in range(len(names))}
    out = {"merged": merged, "region_fraction": frac}
    if gt is not None and have is not None and have.any():
        out["merged_median_pitch"] = round(
            registration_error_stats(merged, gt, mask=have)["median"] / pitch, 3)
    return out
