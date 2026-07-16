"""3D reconstruction from aligned serial sections.

Honest description: this is a serial-section z-stack, not a global simultaneous
solve. Each adjacent pair is aligned in-plane by the orchestrator (Sutura or
PASTE2). We then assemble a 3D volume:

  * 2 sections (1 pair): the moving section is already in the reference frame -
    the stack is exact.
  * >2 sections (a chain): pairwise alignment puts section k+1 into section k's
    frame, NOT into the global reference frame. We compose the chain by fitting a
    similarity transform (rotation + uniform scale + translation, Umeyama) for
    each pair from the moving section's original coords to its aligned coords,
    then chaining those transforms back to the first section's frame. This is
    PAIRWISE COMPOSITION, honestly labelled as such - it is not a global
    (simultaneous) registration like GPSA. Residual non-rigid warp within a pair
    is not propagated; the bulk rotation/scale/offset between frames is.

z encodes section order (a fixed slice spacing); it is not measured depth.
"""
from __future__ import annotations

import numpy as np

# identity affine as a 2x3 matrix [A | b], mapping x -> A x + b
_IDENTITY = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


def _fit_similarity(src, dst):
    """Least-squares similarity transform (Umeyama) src -> dst as a 2x3 affine."""
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    if len(src) < 2 or len(src) != len(dst):
        return _IDENTITY.copy()
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    var_s = (xs ** 2).sum() / len(src)
    cov = (xd.T @ xs) / len(src)
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(2)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:   # reflection guard
        S[1, 1] = -1
    R = U @ S @ Vt
    scale = (D * np.diag(S)).sum() / var_s if var_s > 1e-12 else 1.0
    A = scale * R
    b = mu_d - A @ mu_s
    return np.hstack([A, b[:, None]])


def _apply(M, pts):
    pts = np.asarray(pts, float)
    return pts @ M[:, :2].T + M[:, 2]


def _compose(outer, inner):
    """Return the affine mapping x -> outer(inner(x))."""
    A = outer[:, :2] @ inner[:, :2]
    b = outer[:, :2] @ inner[:, 2] + outer[:, 2]
    return np.hstack([A, b[:, None]])


def _as_labels(layers, n):
    if layers is None:
        return ["NA"] * n
    out = ["NA" if v is None else str(v) for v in list(layers)[:n]]
    return out + ["NA"] * (n - len(out))


def build_pointcloud(pairs, z_spacing=None):
    """Assemble a 3D point cloud from an ordered chain of aligned pairs.

    Each pair dict: ref_name, mov_name, ref_coords (n,2), aligned_coords (m,2)
    [moving in the ref's frame], mov_coords (m,2) [moving in its own frame],
    ref_layers, mov_layers, pitch, method.
    Returns a JSON-serialisable reconstruction dict (global reference frame).
    """
    if not pairs:
        return {"kind": "serial_section_zstack", "n_sections": 0,
                "n_points": 0, "sections": [], "points": [],
                "point_fields": ["x", "y", "z", "section_index", "layer"]}

    pitch = float(pairs[0].get("pitch") or 1.0)
    dz = float(z_spacing) if z_spacing else pitch

    sections, points = [], []

    def _add(name, coords, layers, z, method):
        idx = len(sections)
        coords = np.asarray(coords, float)
        for (x, y), lab in zip(coords, _as_labels(layers, len(coords))):
            points.append([round(float(x), 2), round(float(y), 2),
                           round(float(z), 2), idx, lab])
        sections.append({"index": idx, "name": name, "z": round(z, 2),
                         "n_points": int(len(coords)), "method": method})

    # section 0 (first pair's reference) at z=0, in the global frame
    _add(pairs[0]["ref_name"], pairs[0]["ref_coords"], pairs[0].get("ref_layers"),
         0.0, "reference")

    # T maps the CURRENT pair's reference frame -> the global (section-0) frame.
    T = _IDENTITY.copy()
    z = 0.0
    for i, p in enumerate(pairs):
        z += dz
        aligned = np.asarray(p["aligned_coords"], float)   # moving in frame i
        placed = _apply(T, aligned) if i > 0 else aligned  # -> global frame
        _add(p["mov_name"], placed, p.get("mov_layers"), z, p["method"])
        # extend the chain: A maps frame i+1 -> frame i (moving orig -> aligned)
        if i < len(pairs) - 1 and p.get("mov_coords") is not None:
            A = _fit_similarity(p["mov_coords"], aligned)
            T = _compose(T, A)

    xyz = np.asarray([[q[0], q[1], q[2]] for q in points], float)
    n_pairs = len(pairs)
    composition = "exact_single_reference" if n_pairs == 1 else "pairwise_composition"
    note = ("single reference frame - 2-section stack is exact"
            if n_pairs == 1 else
            "pairwise composition: per-pair similarity transforms chained to the "
            "first section's frame; NOT a global simultaneous solve")
    return {
        "kind": "serial_section_zstack",
        "composition": composition,
        "note": note,
        "global_frame": pairs[0]["ref_name"],
        "z_spacing": round(dz, 2),
        "pitch": round(pitch, 2),
        "n_sections": len(sections),
        "n_points": len(points),
        "bounds": {"min": xyz.min(0).round(2).tolist(),
                   "max": xyz.max(0).round(2).tolist()},
        "sections": sections,
        "point_fields": ["x", "y", "z", "section_index", "layer"],
        "points": points,
    }
