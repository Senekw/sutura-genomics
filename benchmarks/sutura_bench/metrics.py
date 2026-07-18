"""
All evaluation metrics for spatial-alignment benchmarks, in one place.

This module is the single authority for how a benchmark number is computed. It is
numpy-only (no torch, no anndata) so it can be imported and unit-tested cheaply,
and every formula mirrors the repo's canonical research implementation:

  - registration error / projections / label transfer  <- src/scoring.py
  - spot pitch (the normalization length scale)         <- src/warp_slice.py
  - neighbor consistency / footprint coverage           <- src/agents.py

``tests/test_metrics.py`` asserts these reproduce the src/ implementations
bit-for-bit, so the benchmark measures exactly what prior experiments measured
while remaining self-contained (it does not break if src/ is refactored).

The headline metric of the whole project is **median registration error in
spot-pitches**: the per-spot Euclidean distance between a method's predicted
reference-frame coordinate and the ground-truth coordinate, divided by the spot
pitch, then median-reduced over the scorable spots.

Honest self-alignment handling
------------------------------
Two ground-truth regimes exist and MUST NOT be averaged together:

  * ``array_bridge`` (real serial sections): B and A are physically distinct
    adjacent sections sharing the Visium array grid; the correspondence is an
    honest cross-section target. This is the regime every headline number uses.
  * ``self_warp`` (degenerate): a single section is warped against a copy of
    itself, so an aligner that just matches identical expression is near-exact
    and there is essentially nothing to refine. Refinement methods (the gate)
    cannot be validated here. Cells scored in this regime are tagged
    ``regime="self_warp"`` and ``degenerate=True`` by the harness and are never
    pooled with real-serial results in the leaderboard.

``SELF_WARP_FLOOR_PITCH`` documents the error below which a self-warp result is
effectively "solved by the degeneracy" rather than by the method.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.spatial import cKDTree

NA = "NA"
# below this median-pitch error on a self-warp pair, the score reflects the
# degeneracy (identical-copy matching) more than the method's real skill.
SELF_WARP_FLOOR_PITCH = 1.0


# --------------------------------------------------------------------------- #
# length scale
# --------------------------------------------------------------------------- #
def spot_pitch(coords: np.ndarray) -> float:
    """Median nearest-neighbour distance - the spot-to-spot pitch (the natural
    length unit). Mirrors src/warp_slice.py::median_spot_pitch."""
    coords = np.asarray(coords, float)
    d, _ = cKDTree(coords).query(coords, k=2)
    return float(np.median(d[:, 1]))


# --------------------------------------------------------------------------- #
# transport-plan -> coordinates
# --------------------------------------------------------------------------- #
def barycentric_projection(pi, source_coords):
    """Soft-map each target spot into the source frame via the transport plan.

    pi is (n_src, n_tgt); source_coords is (n_src, d). Returns
    (pred (n_tgt, d), col_mass (n_tgt,)); columns with ~zero mass yield NaN.
    Mirrors src/scoring.py::barycentric_projection.
    """
    pi = np.asarray(pi, dtype=float)
    source_coords = np.asarray(source_coords, dtype=float)
    col_mass = pi.sum(axis=0)
    safe = col_mass > 0
    pred = np.full((pi.shape[1], source_coords.shape[1]), np.nan)
    pred[safe] = (pi[:, safe].T @ source_coords) / col_mass[safe, None]
    return pred, col_mass


def argmax_projection(pi, source_coords):
    """Hard-map each target spot to its single best source partner. Avoids the
    centroid-smearing a diffuse plan causes. Mirrors src/scoring.py."""
    pi = np.asarray(pi, dtype=float)
    source_coords = np.asarray(source_coords, dtype=float)
    col_mass = pi.sum(axis=0)
    safe = col_mass > 0
    best = pi.argmax(axis=0)
    pred = np.full((pi.shape[1], source_coords.shape[1]), np.nan)
    pred[safe] = source_coords[best[safe]]
    return pred, col_mass


# --------------------------------------------------------------------------- #
# registration error (THE headline metric)
# --------------------------------------------------------------------------- #
def registration_error(pred_coords, gt_coords, mask: Optional[np.ndarray] = None,
                       pitch: Optional[float] = None) -> dict:
    """Euclidean error between predicted and ground-truth coordinates.

    Reports the full distribution (mean/median/p90/p95/p99/max) in the native
    coordinate units, plus - when ``pitch`` is given - the same statistics in
    spot-pitch units (the comparable metric across datasets). ``mask`` selects
    scorable spots (e.g. those with a GT target and nonzero transported mass);
    non-finite predictions are always dropped.

    The ``*_px`` fields extend src/scoring.py::registration_error_stats (which
    returns mean/median/p90/max); the extra percentiles and pitch-normalized
    fields are added here. ``median_pitch`` is the number every leaderboard uses.
    """
    pred = np.asarray(pred_coords, dtype=float)
    gt = np.asarray(gt_coords, dtype=float)
    err = np.linalg.norm(pred - gt, axis=1)
    valid = np.isfinite(err)
    if mask is not None:
        valid &= np.asarray(mask, dtype=bool)
    e = err[valid]
    if e.size == 0:
        out = {"mean_px": float("nan"), "median_px": float("nan"),
               "p90_px": float("nan"), "p95_px": float("nan"),
               "p99_px": float("nan"), "max_px": float("nan"), "n": 0}
    else:
        out = {
            "mean_px": float(e.mean()),
            "median_px": float(np.median(e)),
            "p90_px": float(np.percentile(e, 90)),
            "p95_px": float(np.percentile(e, 95)),
            "p99_px": float(np.percentile(e, 99)),
            "max_px": float(e.max()),
            "n": int(e.size),
        }
    if pitch is not None and pitch > 0:
        for k in ("mean", "median", "p90", "p95", "p99", "max"):
            out[f"{k}_pitch"] = out[f"{k}_px"] / pitch
    return out


def registration_error_stats(pred_coords, gt_coords, mask=None) -> dict:
    """Backwards-compatible alias returning the exact {mean, median, p90, max, n}
    schema of src/scoring.py (pixel units, keys without the _px suffix)."""
    full = registration_error(pred_coords, gt_coords, mask=mask)
    return {"mean": full["mean_px"], "median": full["median_px"],
            "p90": full["p90_px"], "max": full["max_px"], "n": full["n"]}


# --------------------------------------------------------------------------- #
# per-layer registration accuracy
# --------------------------------------------------------------------------- #
def per_layer_error(pred_coords, gt_coords, layers, pitch, mask=None) -> dict:
    """Median registration error (spot-pitches) broken down by annotation layer.

    Mirrors the per-layer breakdown in src/agents.py::report_agent. ``layers`` is
    one label per moving spot; spots labelled NA (or masked/non-finite) are
    dropped. Returns {layer: {"median_pitch", "n"}} plus an "overall" entry.
    """
    pred = np.asarray(pred_coords, float)
    gt = np.asarray(gt_coords, float)
    layers = np.asarray(layers).astype(str)
    err = np.linalg.norm(pred - gt, axis=1) / pitch
    valid = np.isfinite(err)
    if mask is not None:
        valid &= np.asarray(mask, dtype=bool)
    valid &= (layers != NA)

    out = {}
    for lab in sorted(set(layers[valid])):
        sel = valid & (layers == lab)
        if sel.any():
            out[lab] = {"median_pitch": float(np.median(err[sel])),
                        "n": int(sel.sum())}
    if valid.any():
        out["overall"] = {"median_pitch": float(np.median(err[valid])),
                          "n": int(valid.sum())}
    return out


# --------------------------------------------------------------------------- #
# label-transfer accuracy (for transport-plan methods)
# --------------------------------------------------------------------------- #
def label_transfer_accuracy(pi, layer_a, layer_b) -> dict:
    """Accuracy of argmax A->B label transfer, masking NA on both slices.
    Mirrors src/scoring.py::label_transfer_accuracy."""
    pi = np.asarray(pi)
    layer_a = np.asarray(layer_a).astype(str)
    layer_b = np.asarray(layer_b).astype(str)
    j_star = pi.argmax(axis=1)
    predicted = layer_b[j_star]
    valid = (layer_a != NA) & (predicted != NA)
    correct = (predicted == layer_a) & valid
    n_valid = int(valid.sum())
    return {
        "accuracy": float(correct.sum() / max(n_valid, 1)),
        "n_correct": int(correct.sum()),
        "n_scored": n_valid,
        "n_dropped_a_na": int((layer_a == NA).sum()),
        "n_dropped_partner_na": int(((layer_a != NA) & (predicted == NA)).sum()),
    }


def random_mapping_floor(layer_a, layer_b, n_trials: int = 50, seed: int = 0) -> dict:
    """Chance floor for label transfer (uniform-random A->B partner, NA-masked,
    averaged over shuffles). Mirrors src/scoring.py::random_mapping_floor."""
    layer_a = np.asarray(layer_a).astype(str)
    layer_b = np.asarray(layer_b).astype(str)
    rng = np.random.default_rng(seed)
    n_a, n_b = layer_a.shape[0], layer_b.shape[0]
    accs = []
    for _ in range(n_trials):
        j = rng.integers(0, n_b, size=n_a)
        predicted = layer_b[j]
        valid = (layer_a != NA) & (predicted != NA)
        accs.append(((predicted == layer_a) & valid).sum() / max(valid.sum(), 1))
    accs = np.asarray(accs)
    return {"accuracy_mean": float(accs.mean()), "accuracy_std": float(accs.std()),
            "n_trials": n_trials}


# --------------------------------------------------------------------------- #
# ground-truth-free structural quality (used where no correspondence exists)
# --------------------------------------------------------------------------- #
def neighbor_consistency(pred, mov_coords, k: int = 8) -> np.ndarray:
    """Per-spot local rigidity in [0,1] (1 = neighbourhood distances preserved).

    For each moving spot, compare neighbour distances before vs after alignment,
    scale-normalized. Mirrors src/agents.py::neighbor_consistency. Reduce with
    np.median(...) for a scalar. Ground-truth-free.
    """
    pred = np.asarray(pred, float)
    mov = np.asarray(mov_coords, float)
    n = len(mov)
    kq = min(k + 1, n)
    _, idx = cKDTree(mov).query(mov, k=kq)
    nb = idx[:, 1:]
    mov_d = np.linalg.norm(mov[:, None, :] - mov[nb], axis=2)
    pred_d = np.linalg.norm(pred[:, None, :] - pred[nb], axis=2)
    denom = np.median(mov_d)
    scale = np.median(pred_d) / denom if denom > 0 else 1.0
    scale = scale if scale > 0 else 1.0
    ratio = pred_d / (mov_d * scale + 1e-12)
    ratio = np.where(np.isfinite(ratio) & (ratio > 0), ratio, 1.0)
    return np.clip(1.0 - np.abs(np.log(ratio)).mean(axis=1), 0.0, 1.0)


def footprint_coverage(pred, ref_coords) -> float:
    """Ratio of predicted radial spread to reference footprint spread (~1 healthy,
    <<1 = collapse to centroid). Mirrors src/agents.py::footprint_coverage and
    src/orchestrator.py::footprint_coverage_proxy. Ground-truth-free."""
    pred = np.asarray(pred, float)
    ref = np.asarray(ref_coords, float)
    pf = pred[np.isfinite(pred).all(1)]
    if pf.size == 0:
        return 0.0
    spread_pred = np.median(np.linalg.norm(pf - pf.mean(0), axis=1))
    spread_ref = np.median(np.linalg.norm(ref - ref.mean(0), axis=1))
    return float(spread_pred / (spread_ref + 1e-9))


# --------------------------------------------------------------------------- #
# honest self-alignment flagging
# --------------------------------------------------------------------------- #
def is_degenerate_self_warp(regime: str, median_pitch: float) -> bool:
    """True when a score comes from the self-warp regime AND is at/below the
    degeneracy floor, i.e. it reflects identical-copy matching rather than the
    method's real skill. Used by reporting to caveat such rows, never to average
    them with real-serial results."""
    return regime == "self_warp" and (
        not np.isfinite(median_pitch) or median_pitch <= SELF_WARP_FLOOR_PITCH)
