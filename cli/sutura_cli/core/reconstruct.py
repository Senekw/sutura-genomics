"""3D reconstruction from aligned serial sections.

Honest description: this is a serial-section z-stack. Each section is aligned
in-plane by the orchestrator (Sutura or PASTE2); we then place the sections at
increasing z to assemble a 3D point cloud. The reference section sits at z=0 and
each aligned moving section is offset by `z_spacing` (defaults to the in-plane
spot pitch, so voxels are roughly isotropic).

We do NOT invent depth: z encodes section order only. For a 2-section job (e.g.
the DLPFC demo pair) both sections share the reference frame exactly, so the
stack is faithful. For longer chains the alignment is pairwise-to-neighbour, and
that is recorded in the bundle rather than hidden.
"""
from __future__ import annotations

import numpy as np


def build_pointcloud(pairs, z_spacing=None):
    """Assemble a 3D point cloud from aligned pairs.

    pairs: ordered list of dicts, each with
        ref_name, mov_name, ref_coords (n,2), aligned_coords (m,2),
        ref_layers (n,) or None, mov_layers (m,) or None, pitch (float), method.
    Returns a JSON-serialisable reconstruction dict.
    """
    if not pairs:
        return {"n_sections": 0, "n_points": 0, "sections": [], "points": []}

    pitch = float(pairs[0].get("pitch") or 1.0)
    dz = float(z_spacing) if z_spacing else pitch

    sections = []          # metadata per placed section
    points = []            # [x, y, z, section_idx, layer]
    placed_names = []

    def _add(name, coords, layers, z, method):
        idx = len(sections)
        coords = np.asarray(coords, float)
        labels = _as_labels(layers, len(coords))
        for (x, y), lab in zip(coords, labels):
            points.append([round(float(x), 2), round(float(y), 2),
                           round(float(z), 2), idx, lab])
        sections.append({"index": idx, "name": name, "z": round(z, 2),
                         "n_points": int(len(coords)), "method": method})
        placed_names.append(name)

    # reference section of the whole stack (from the first pair) at z=0
    first = pairs[0]
    _add(first["ref_name"], first["ref_coords"], first.get("ref_layers"),
         0.0, "reference")

    z = 0.0
    for p in pairs:
        z += dz
        _add(p["mov_name"], p["aligned_coords"], p.get("mov_layers"), z, p["method"])

    xyz = np.asarray([[pt[0], pt[1], pt[2]] for pt in points], float) \
        if points else np.zeros((0, 3))
    bounds = {
        "min": xyz.min(0).round(2).tolist() if len(xyz) else [0, 0, 0],
        "max": xyz.max(0).round(2).tolist() if len(xyz) else [0, 0, 0],
    }
    return {
        "kind": "serial_section_zstack",
        "note": ("z encodes section order (pairwise-to-neighbour alignment); "
                 "in-plane coordinates are the orchestrator's aligned output"),
        "z_spacing": round(dz, 2),
        "pitch": round(pitch, 2),
        "n_sections": len(sections),
        "n_points": len(points),
        "bounds": bounds,
        "sections": sections,
        "point_fields": ["x", "y", "z", "section_index", "layer"],
        "points": points,
    }


def _as_labels(layers, n):
    if layers is None:
        return ["NA"] * n
    out = []
    for v in list(layers)[:n]:
        out.append("NA" if v is None else str(v))
    if len(out) < n:
        out += ["NA"] * (n - len(out))
    return out
