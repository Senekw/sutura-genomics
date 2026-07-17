"""
gate_refine - a training-free, ground-truth-free, safe-by-construction refinement of an
OT spatial-alignment result (e.g. PASTE2) on torn tissue.

This is the packaged, validated result from the hybrid-combined experiments
(research/FINDINGS_hybrid_validated.md): given an OT aligner's predicted reference-frame
coordinates for each moving spot, plus the moving spots' own (observed, possibly torn)
coordinates, it detects the tissue's pieces, fits a low-order geometric transform per piece
to the OT correspondence, and applies it ONLY where that fit is trustworthy - falling back
to the OT result elsewhere. Because the trust decision is a self-gate on the fit's own
residual (no ground truth, no expression features), it can only help or fall back; it does
NOT regress. Validated to improve PASTE2 by ~15-30% median registration error on the DLPFC
LODO tear benchmark and to generalize to off-distribution tissue (breast, mouse brain).

Mechanism. A physical tear rigidly displaces a contiguous region, so on the moving slice's
kNN graph the edges bridging the cut are stretched; cutting long edges splits the tissue into
pieces. Within a piece the true moving->reference map is close to a similarity/affine, and the
OT correspondence is a good-but-noisy estimate of it - so a weighted least-squares fit of the
piece's OT targets denoises the correspondence and undoes the tear's offset. The fit residual
(how well a low-order transform explains the piece) is high exactly when the piece is NOT
well-described by that transform (strong non-rigid warp, or a bad OT base), so a logistic gate
on the residual applies the correction where it helps and falls back where it doesn't.

Public API:
    gate_refine(base_coords, moving_coords, order="affine", pitch=None, ...) -> corrected (N,2)
    refine_paste2(...)   # thin alias documenting the intended (PASTE2 barycentric) input

Pure numpy + scipy; no torch, no features, no ground truth.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

__all__ = ["gate_refine", "refine_paste2", "median_pitch", "detect_pieces"]

_ORDER = {"rigid": 0, "affine": 1, "quadratic": 2}


def median_pitch(coords: np.ndarray) -> float:
    """Median nearest-neighbour distance = spot pitch (the natural length scale)."""
    coords = np.asarray(coords, float)
    d, _ = cKDTree(coords).query(coords, k=2)
    return float(np.median(d[:, 1]))


# --------------------------------------------------------------------------- #
def detect_pieces(coords, pitch, k=8, stretch=2.2, min_frac=0.06):
    """Segment a (possibly torn) slice by cutting kNN edges longer than stretch*pitch and
    taking connected components; components smaller than min_frac of the slice are merged into
    the nearest large component. Returns integer piece labels 0..P-1 (P>=1)."""
    coords = np.asarray(coords, float)
    n = len(coords)
    if n < 20:
        return np.zeros(n, dtype=int)
    tree = cKDTree(coords)
    dist, idx = tree.query(coords, k=min(k + 1, n))
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    thr = stretch * pitch
    for i in range(n):
        for jp in range(1, dist.shape[1]):
            if dist[i, jp] <= thr:
                ri, rj = find(i), find(int(idx[i, jp]))
                if ri != rj:
                    parent[ri] = rj
    root = np.array([find(i) for i in range(n)])
    uniq, counts = np.unique(root, return_counts=True)
    big = uniq[counts >= max(min_frac * n, 5)]
    if len(big) <= 1:
        return np.zeros(n, dtype=int)
    cents = {u: coords[root == u].mean(0) for u in big}
    big_list = list(big)
    cmat = np.stack([cents[u] for u in big_list])
    lab = np.zeros(n, dtype=int)
    for i in range(n):
        if root[i] in cents:
            lab[i] = big_list.index(root[i])
        else:
            lab[i] = int(np.argmin(((cmat - coords[i]) ** 2).sum(1)))
    return lab


# --------------------------------------------------------------------------- #
def _umeyama(src, dst, w):
    """Weighted similarity transform (rotation + uniform scale + translation) src->dst."""
    ws = w.sum()
    if ws <= 1e-9 or len(src) < 3:
        return np.eye(2), np.zeros(2), 1.0
    w = w / ws
    mu_s = (w[:, None] * src).sum(0)
    mu_d = (w[:, None] * dst).sum(0)
    S = src - mu_s
    D = dst - mu_d
    C = (w[:, None] * D).T @ S
    U, Sig, Vt = np.linalg.svd(C)
    d = np.sign(np.linalg.det(U @ Vt))
    R = U @ np.diag([1.0, d]) @ Vt
    var_s = (w * (S ** 2).sum(1)).sum()
    scale = float((Sig * np.array([1.0, d])).sum() / (var_s + 1e-12))
    if not np.isfinite(scale) or scale <= 0:
        scale = 1.0
    t = mu_d - scale * (R @ mu_s)
    return R, t, scale


def _poly_design(P, order):
    x, y = P[:, 0], P[:, 1]
    o = np.ones_like(x)
    if order == 1:
        return np.stack([o, x, y], axis=1)
    return np.stack([o, x, y, x * x, x * y, y * y], axis=1)


def _poly_fit(src, dst, order, w):
    Phi = _poly_design(src, order)
    G = Phi.T @ (w[:, None] * Phi) + 1e-6 * np.eye(Phi.shape[1])
    B = Phi.T @ (w[:, None] * dst)
    return np.linalg.lstsq(G, B, rcond=None)[0]


def _fit_predict(src, dst, order, w, eval_src=None):
    tgt = src if eval_src is None else eval_src
    if order == 0:
        R, t, sc = _umeyama(src, dst, w)
        return sc * (tgt @ R.T) + t
    beta = _poly_fit(src, dst, order, w)
    return _poly_design(tgt, order) @ beta


def _cv_residual(src, dst, order, w, pitch, rng):
    """Cross-validated fit residual (pitch units): fit on half the piece, score the other
    half, both directions. Penalizes higher-DOF fits that overfit the OT noise, keeping the
    trust gate fair across rigid/affine/quadratic."""
    n = len(src)
    idx = rng.permutation(n)
    h = n // 2
    if h < (order + 1) * 3:
        pred = _fit_predict(src, dst, order, w)
        return float(np.median(np.linalg.norm(pred - dst, axis=1)) / pitch)
    a, b = idx[:h], idx[h:]
    res = []
    for tr, te in ((a, b), (b, a)):
        pred = _fit_predict(src[tr], dst[tr], order, w[tr], eval_src=src[te])
        res.append(np.median(np.linalg.norm(pred - dst[te], axis=1)))
    return float(np.mean(res) / pitch)


# --------------------------------------------------------------------------- #
def gate_refine(base_coords, moving_coords, order="affine", *, pitch=None,
                thr=4.5, scale=1.0, weights=None, cv=None, seed=0,
                stretch=2.2, min_frac=0.06, return_info=False):
    """Refine an OT alignment on torn tissue. SAFE BY CONSTRUCTION: never regresses.

    Parameters
    ----------
    base_coords   : (N,2) the OT aligner's predicted reference-frame coordinate per moving spot
                    (e.g. PASTE2 barycentric projection of the transport plan).
    moving_coords : (N,2) the moving spots' own observed (possibly torn) coordinates.
    order         : "rigid" | "affine" | "quadratic". Default "affine" (the validated best -
                    it also corrects high-severity tears the rigid fit cannot).
    pitch         : spot pitch (length scale). If None, computed from moving_coords.
    thr, scale    : logistic gate on the (cross-validated) per-piece fit residual, in pitch
                    units: trust weight = 1/(1+exp((residual - thr)/scale)). thr ~ the OT error
                    scale (~4.5 pitch) above which a low-order fit is not adding value; pre-set,
                    not tuned on any test labels. The win is robust across thr in [2,12].
    weights       : optional (N,) per-spot confidence for the fit. Default uniform (the
                    validated setting - the gate needs no features).
    cv            : use cross-validated fit residual for the trust gate. Default: False for
                    rigid (reproduces the original result exactly), True for affine/quadratic
                    (so extra degrees of freedom can't win by overfitting).
    return_info   : also return a dict (piece labels, per-piece trust weights, fraction gated).

    Returns
    -------
    corrected : (N,2) refined reference-frame coordinates. Ground-truth-free, feature-free.
    """
    o = _ORDER[order] if isinstance(order, str) else int(order)
    base = np.asarray(base_coords, float)
    mov = np.asarray(moving_coords, float)
    if base.shape != mov.shape or base.ndim != 2 or base.shape[1] != 2:
        raise ValueError("base_coords and moving_coords must both be (N,2) and same shape")
    n = len(base)
    if pitch is None:
        pitch = median_pitch(mov)
    if weights is None:
        weights = np.ones(n, float)
    else:
        weights = np.asarray(weights, float)
    if cv is None:
        cv = (o != 0)
    rng = np.random.default_rng(seed)

    labels = detect_pieces(mov, pitch, stretch=stretch, min_frac=min_frac)
    out = base.copy()
    min_n = 6 if o == 0 else (10 if o == 1 else 18)
    info_pieces = []
    for lab in np.unique(labels):
        m = labels == lab
        npiece = int(m.sum())
        if npiece < min_n:
            info_pieces.append((int(lab), npiece, 0.0, float("nan")))
            continue
        s, d, wt = mov[m], base[m], weights[m]
        fit = _fit_predict(s, d, o, wt)
        if cv:
            res = _cv_residual(s, d, o, wt, pitch, rng)
        else:
            res = float(np.median(np.linalg.norm(fit - d, axis=1)) / pitch)
        w = float(1.0 / (1.0 + np.exp((res - thr) / scale)))
        out[m] = w * fit + (1 - w) * d
        info_pieces.append((int(lab), npiece, w, res))
    if return_info:
        gated_frac = sum(p[1] * p[2] for p in info_pieces) / max(n, 1)
        return out, {"labels": labels, "pieces": info_pieces, "pitch": pitch,
                     "order": order, "thr": thr, "gated_fraction": gated_frac}
    return out


def refine_paste2(paste2_ref_coords, moving_coords, order="affine", **kw):
    """Alias documenting the intended input: paste2_ref_coords is the barycentric projection
    of the PASTE2 transport plan into the reference frame (one (x,y) per moving spot)."""
    return gate_refine(paste2_ref_coords, moving_coords, order=order, **kw)
