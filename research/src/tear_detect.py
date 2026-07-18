"""
tear_detect - GT-free detection & characterization of REAL tissue damage in
spatial-transcriptomics (Visium) sections.

Motivation
----------
The validated alignment "gate" (src/gate_refine.py) was only ever stress-tested on
SYNTHETIC tears (src/warp_slice.py: a single straight cut + rigid translation of
30-45% of the tissue, plus a smooth Gaussian warp). That is the biggest caveat on
the gate result: we never checked whether real tissue damage looks anything like it.

This module finds and characterizes ACTUAL damage in a section with NO ground truth,
using four orthogonal, well-understood signals:

  1. SPATIAL GAPS / VOIDS       - Visium spots sit on a fixed hex lattice. Interior
                                  lattice sites with no spot form holes. Elongated
                                  holes read as cuts/tears; blobby holes as missing
                                  regions. (Lattice-exact; physical-gap fallback when
                                  array coordinates are absent.)
  2. DENSITY DISCONTINUITY      - local spot density drops at a void edge and (for
                                  folds) tissue is over-represented. Measured on the
                                  lattice and in physical space.
  3. EXPRESSION DISCONTINUITY   - transcriptomes change smoothly across healthy
                                  tissue; a cut places very dissimilar tissue in
                                  physical contact. Per-edge expression jump; a
                                  connected chain of high-jump edges coincident with
                                  a gap is a cut line.
  4. BOUNDARY IRREGULARITY      - a healthy section has a compact, smooth outline.
                                  Tears add concave notches, straight cut segments,
                                  and lower solidity.
  + FOLDS                       - a fold stacks tissue onto capture spots -> a locally
                                  coherent spike in total counts / genes-per-spot.

Everything is derived from obsm["spatial"], the count matrix X, and (when present)
obs["array_row"/"array_col"]. No labels, no reference, no alignment.

Public API
----------
    report = characterize(adata, name="section")        -> DamageReport
    row    = report.to_row()                             -> flat dict (for CSV)
    print(report.text())                                 -> human summary

CLI
---
    python research/src/tear_detect.py --report path/to/section.h5ad
    python research/src/tear_detect.py --report path/to/section.h5ad --json

Design notes
------------
* Pure numpy/scipy/sklearn; no scanpy dependency for the core (a light internal
  normalize/PCA). Sparse-safe. Deterministic (fixed SVD seed).
* Robust to the ~50k-spot atlas sections via optional subsampling of the expression
  embedding step only (geometry is always computed on all spots).
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.sparse import issparse
from scipy.spatial import cKDTree
from scipy.spatial import Delaunay

# ------------------------------------------------------------------------- #
# small helpers
# ------------------------------------------------------------------------- #
def _median_pitch(coords: np.ndarray) -> float:
    """Median nearest-neighbor distance = spot pitch."""
    if len(coords) < 2:
        return 1.0
    d, _ = cKDTree(coords).query(coords, k=2)
    return float(np.median(d[:, 1]))


def _robust_z(x: np.ndarray) -> np.ndarray:
    """Median/MAD z-score."""
    med = np.median(x)
    mad = np.median(np.abs(x - med)) + 1e-9
    return (x - med) / (1.4826 * mad)


def _connected_components(adj: dict) -> list[list]:
    """Connected components of a graph given as {node: set(neighbors)}."""
    seen, comps = set(), []
    for start in adj:
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(comp)
    return comps


def _elongation(pts: np.ndarray) -> float:
    """sqrt(lambda_max/lambda_min) of the point cloud's covariance (1 = round, >>1 = line)."""
    if len(pts) < 3:
        return 1.0
    c = pts - pts.mean(0)
    cov = c.T @ c / len(pts)
    ev = np.linalg.eigvalsh(cov)
    ev = np.clip(ev, 1e-12, None)
    return float(np.sqrt(ev[-1] / ev[0]))


def _straightness(pts: np.ndarray) -> float:
    """Fraction of variance along the principal axis (1 = perfectly straight line)."""
    if len(pts) < 3:
        return 1.0
    c = pts - pts.mean(0)
    cov = c.T @ c / len(pts)
    ev = np.linalg.eigvalsh(cov)
    tot = ev.sum()
    if tot <= 0:
        return 1.0
    return float(ev[-1] / tot)


# ------------------------------------------------------------------------- #
# expression embedding (light, sparse-safe)
# ------------------------------------------------------------------------- #
def _expr_embedding(X, n_comps: int = 30, n_hvg: int = 2000, seed: int = 0):
    """Library-size normalize -> log1p -> top-variance genes -> truncated SVD.
    Returns an (n_spots, n_comps) float32 embedding. Deterministic."""
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import StandardScaler

    Xc = X.tocsr().astype(np.float64) if issparse(X) else np.asarray(X, np.float64)
    # library-size normalization to the median depth
    tot = np.asarray(Xc.sum(1)).ravel()
    tot[tot == 0] = 1.0
    target = np.median(tot)
    if issparse(Xc):
        from scipy.sparse import diags
        Xn = diags(target / tot) @ Xc
        Xn.data = np.log1p(Xn.data)
    else:
        Xn = np.log1p(Xc * (target / tot)[:, None])
    # high-variance gene selection
    if issparse(Xn):
        mean = np.asarray(Xn.mean(0)).ravel()
        sq = np.asarray(Xn.multiply(Xn).mean(0)).ravel()
        var = np.clip(sq - mean ** 2, 0, None)
    else:
        var = Xn.var(0)
    n_hvg = min(n_hvg, Xn.shape[1])
    hv = np.argsort(var)[::-1][:n_hvg]
    Xh = Xn[:, hv]
    Xh = Xh.toarray() if issparse(Xh) else np.asarray(Xh)
    Xh = StandardScaler().fit_transform(Xh)
    k = int(min(n_comps, min(Xh.shape) - 1))
    if k < 2:
        return Xh.astype(np.float32)
    svd = TruncatedSVD(n_components=k, random_state=seed)
    return svd.fit_transform(Xh).astype(np.float32)


# ------------------------------------------------------------------------- #
# Visium hex-lattice occupancy & void detection
# ------------------------------------------------------------------------- #
# hex neighbor offsets in (array_row, array_col) space
_HEX_OFF = [(0, -2), (0, 2), (-1, -1), (-1, 1), (1, -1), (1, 1)]


def _lattice_voids(rows: np.ndarray, cols: np.ndarray):
    """Detect interior empty lattice sites (voids) on the Visium hex grid.

    Returns dict with:
      present        : set of (r,c) occupied
      interior_empty : list of (r,c) empty AND enclosed by tissue
      void_comps     : connected components (list of lists of (r,c)) of interior empties
      n_lat_neigh    : per-spot count of occupied hex neighbors (aligned to input order)
    """
    rows = np.asarray(rows, int)
    cols = np.asarray(cols, int)
    present = set(zip(rows.tolist(), cols.tolist()))

    # per-spot occupied-neighbor count
    n_lat_neigh = np.zeros(len(rows), dtype=int)
    for i, (r, c) in enumerate(zip(rows, cols)):
        n_lat_neigh[i] = sum(((r + dr, c + dc) in present) for dr, dc in _HEX_OFF)

    r0, r1 = rows.min(), rows.max()
    c0, c1 = cols.min(), cols.max()
    # candidate empty sites: valid hex parity, inside the occupied bounding box.
    # Visium uses a single (row+col) parity consistently; infer it from present spots.
    empty = set()
    par = np.array([(r + c) % 2 for r, c in present])
    use_par = int(round(par.mean())) if len(par) else 0
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            if (r + c) % 2 != use_par:
                continue
            if (r, c) not in present:
                empty.add((r, c))

    # flood-fill from the border (r0-1..r1+1 frame) through empty+off-grid to mark exterior
    # exterior = empties connected to outside the bbox. interior = the rest.
    # Build adjacency over empty sites + a virtual "outside".
    empty_adj = {e: set() for e in empty}
    for (r, c) in empty:
        for dr, dc in _HEX_OFF:
            nb = (r + dr, c + dc)
            if nb in empty_adj:
                empty_adj[(r, c)].add(nb)
    # border empties = touching bbox edge -> exterior seeds
    exterior = set()
    stack = [e for e in empty if e[0] in (r0, r1) or e[1] in (c0, c1)
             or e[0] <= r0 + 1 or e[0] >= r1 - 1]
    # more robust: an empty is exterior if any hex-neighbor steps outside bbox
    stack = []
    for (r, c) in empty:
        touches_out = any(not (r0 <= r + dr <= r1 and c0 <= c + dc <= c1)
                          for dr, dc in _HEX_OFF)
        if touches_out:
            stack.append((r, c))
    for s in stack:
        if s not in exterior:
            exterior.add(s)
    st = list(stack)
    while st:
        u = st.pop()
        for v in empty_adj[u]:
            if v not in exterior:
                exterior.add(v)
                st.append(v)
    interior_empty = [e for e in empty if e not in exterior]

    # connected components among interior empties
    int_adj = {e: (empty_adj[e] & set(interior_empty)) for e in interior_empty}
    void_comps = _connected_components(int_adj) if int_adj else []
    return dict(present=present, interior_empty=interior_empty,
                void_comps=void_comps, n_lat_neigh=n_lat_neigh,
                use_par=use_par, bbox=(r0, r1, c0, c1))


def _lattice_affine_residual(rows, cols, coords, pitch):
    """Fit an affine map (array_row, array_col) -> physical xy and return the per-spot
    residual in units of pitch.

    KEY REALISM PROBE. In real Visium data the spots are FIXED capture locations, so
    obsm["spatial"] is (up to a global affine) exactly the array lattice -> residual ~ 0.
    A synthetic warp that DISPLACES coordinates (src/warp_slice.py) shows a large residual
    over the displaced region. So this cleanly separates "real damage" (spots never move;
    tissue is missing/folded) from "synthetic damage" (coordinates translated), and it is
    ~0 on healthy real sections (no false positives)."""
    A = np.stack([rows, cols, np.ones_like(rows)], 1).astype(float)
    M, *_ = np.linalg.lstsq(A, coords, rcond=None)
    pred = A @ M
    resid = np.linalg.norm(coords - pred, axis=1) / max(pitch, 1e-9)
    return resid


def _lattice_to_xy(void_comps, rows, cols, coords):
    """Map lattice (r,c) void components to physical xy via nearest present spots.
    Returns list of (n_sites, centroid_xy, elongation, straightness, mean_pitch_area)."""
    # affine from (r,c) -> xy estimated by least squares on present spots
    A = np.stack([rows, cols, np.ones_like(rows)], 1).astype(float)
    # solve xy = A @ M  (M is 3x2)
    M, *_ = np.linalg.lstsq(A, coords, rcond=None)
    out = []
    for comp in void_comps:
        rc = np.array(comp, float)
        Ac = np.stack([rc[:, 0], rc[:, 1], np.ones(len(rc))], 1)
        xy = Ac @ M
        out.append(dict(n_sites=len(comp),
                        centroid=xy.mean(0),
                        elongation=_elongation(xy),
                        straightness=_straightness(xy),
                        xy=xy))
    return out


# ------------------------------------------------------------------------- #
# physical-space fallback (no array coords): Delaunay gap edges
# ------------------------------------------------------------------------- #
def _physical_gaps(coords: np.ndarray, pitch: float, gap_mult: float = 1.8):
    """Interior Delaunay edges longer than gap_mult*pitch flag a physical gap.
    Returns per-spot gap flag and the list of gap-edge midpoints."""
    n = len(coords)
    gap_flag = np.zeros(n, bool)
    mids = []
    if n < 4:
        return gap_flag, np.array(mids).reshape(0, 2)
    try:
        tri = Delaunay(coords)
    except Exception:
        return gap_flag, np.array(mids).reshape(0, 2)
    thr = gap_mult * pitch
    edges = set()
    for s in tri.simplices:
        for a, b in ((s[0], s[1]), (s[1], s[2]), (s[0], s[2])):
            edges.add((min(a, b), max(a, b)))
    for a, b in edges:
        d = np.linalg.norm(coords[a] - coords[b])
        if d > thr:
            gap_flag[a] = gap_flag[b] = True
            mids.append((coords[a] + coords[b]) / 2)
    return gap_flag, np.array(mids).reshape(-1, 2)


# ------------------------------------------------------------------------- #
# neighbor graph & expression / fold discontinuities
# ------------------------------------------------------------------------- #
def _neighbor_edges(coords: np.ndarray, pitch: float, k: int = 6, r_mult: float = 1.5):
    """kNN edges restricted to <= r_mult*pitch (true physical neighbors only)."""
    n = len(coords)
    tree = cKDTree(coords)
    kk = min(k + 1, n)
    d, idx = tree.query(coords, k=kk)
    thr = r_mult * pitch
    edges = set()
    for i in range(n):
        for j in range(1, kk):
            if d[i, j] <= thr:
                a, b = i, idx[i, j]
                edges.add((min(a, b), max(a, b)))
    return np.array(sorted(edges)) if edges else np.zeros((0, 2), int)


def _cosine_dist(U, a, b):
    ua, ub = U[a], U[b]
    na = np.linalg.norm(ua, axis=1) + 1e-9
    nb = np.linalg.norm(ub, axis=1) + 1e-9
    cos = (ua * ub).sum(1) / (na * nb)
    return 1.0 - cos


# ------------------------------------------------------------------------- #
# boundary / shape irregularity via lattice solidity + concave measures
# ------------------------------------------------------------------------- #
def _shape_stats(rows, cols, present, use_par, bbox, n_spots):
    """Solidity and boundary roughness on the lattice grid."""
    r0, r1, c0, c1 = bbox
    # count all on-lattice sites in the filled convex-ish bounding region
    # solidity = occupied / (occupied + interior_empty)  [already have interior below]
    # here compute the tissue's fill fraction of its bounding hull on-lattice
    total_sites = 0
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            if (r + c) % 2 == use_par:
                total_sites += 1
    fill_bbox = n_spots / max(total_sites, 1)
    return dict(fill_bbox=float(fill_bbox), n_lattice_sites=int(total_sites))


# ------------------------------------------------------------------------- #
# report dataclasses
# ------------------------------------------------------------------------- #
@dataclass
class DamageEvent:
    kind: str                 # "tear" | "fold" | "missing_region"
    severity: float           # interpretable, kind-specific (see notes)
    n_spots: int              # spots involved (folds) or sites (voids)
    area_frac: float          # fraction of tissue area
    elongation: float         # >>1 = linear (cut), ~1 = blob
    straightness: float       # 1 = perfectly straight cut
    extra: dict = field(default_factory=dict)


@dataclass
class DamageReport:
    name: str
    n_spots: int
    pitch: float
    # geometry / gaps
    n_voids: int
    n_interior_empty_sites: int
    void_area_frac: float
    largest_void_frac: float
    max_void_elongation: float
    # expression discontinuity
    edge_jump_mean: float
    edge_jump_p95: float
    frac_high_jump_edges: float
    n_cut_lines: int
    max_cut_len: int
    max_cut_straightness: float
    # folds
    n_folds: int
    fold_area_frac: float
    max_fold_zscore: float
    # coordinate displacement (real=~0, synthetic-warp=large) & physical gaps
    max_coord_resid_pitch: float
    p95_coord_resid_pitch: float
    frac_displaced: float
    frac_gap_spots: float
    # boundary / shape
    fill_bbox: float
    boundary_irregularity: float
    # aggregate
    n_tears: int
    n_missing_regions: int
    damage_score: float
    severity_label: str
    events: list = field(default_factory=list)

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("events")
        d["n_events"] = len(self.events)
        return d

    def text(self) -> str:
        parts = []
        n_dmg = self.n_tears + self.n_folds + self.n_missing_regions
        if n_dmg == 0:
            headline = f"'{self.name}': no clear damage detected"
        else:
            bits = []
            if self.n_tears:
                bits.append(f"{self.n_tears} tear{'s' if self.n_tears != 1 else ''}")
            if self.n_folds:
                bits.append(f"{self.n_folds} fold{'s' if self.n_folds != 1 else ''}")
            if self.n_missing_regions:
                bits.append(f"{self.n_missing_regions} missing region"
                            f"{'s' if self.n_missing_regions != 1 else ''}")
            headline = (f"'{self.name}': {', '.join(bits)} detected "
                        f"({self.severity_label} severity)")
        parts.append(headline)
        parts.append(f"  spots={self.n_spots}  pitch={self.pitch:.1f}px  "
                     f"fill={self.fill_bbox:.2f}  damage_score={self.damage_score:.3f}")
        parts.append(f"  voids: {self.n_voids} (interior empty sites "
                     f"{self.n_interior_empty_sites}, {self.void_area_frac*100:.2f}% area, "
                     f"largest {self.largest_void_frac*100:.2f}%, "
                     f"max_elong {self.max_void_elongation:.1f})")
        parts.append(f"  expr discontinuity: mean_jump {self.edge_jump_mean:.3f}  "
                     f"p95 {self.edge_jump_p95:.3f}  high-jump edges "
                     f"{self.frac_high_jump_edges*100:.1f}%  cut-lines {self.n_cut_lines} "
                     f"(max len {self.max_cut_len}, straightness {self.max_cut_straightness:.2f})")
        parts.append(f"  folds: {self.n_folds}  fold area {self.fold_area_frac*100:.2f}%  "
                     f"max UMI z {self.max_fold_zscore:.1f}")
        parts.append(f"  coord displacement (real~0): max {self.max_coord_resid_pitch:.2f} pitch  "
                     f"p95 {self.p95_coord_resid_pitch:.3f}  frac displaced "
                     f"{self.frac_displaced*100:.1f}%  gap-spots {self.frac_gap_spots*100:.1f}%")
        parts.append(f"  boundary irregularity: {self.boundary_irregularity:.3f}")
        for e in self.events[:8]:
            parts.append(f"    - {e.kind}: sev={e.severity:.2f} n={e.n_spots} "
                         f"area={e.area_frac*100:.2f}% elong={e.elongation:.1f} "
                         f"straight={e.straightness:.2f}")
        return "\n".join(parts)


# ------------------------------------------------------------------------- #
# main entry point
# ------------------------------------------------------------------------- #
def characterize(adata, name: str = "section", *,
                 jump_z: float = 3.0, fold_z: float = 3.5,
                 min_void_sites: int = 2, min_cut_len: int = 4,
                 min_fold_spots: int = 3, embed_seed: int = 0,
                 max_embed_spots: int = 40000) -> DamageReport:
    """Characterize real tissue damage in one section. GT-free."""
    coords = np.asarray(adata.obsm["spatial"], float)
    n = len(coords)
    pitch = _median_pitch(coords)
    X = adata.X

    has_array = ("array_row" in adata.obs.columns) and ("array_col" in adata.obs.columns)

    # ---- geometry: voids ----
    if has_array:
        rows = np.asarray(adata.obs["array_row"], int)
        cols = np.asarray(adata.obs["array_col"], int)
        lat = _lattice_voids(rows, cols)
        n_lat_neigh = lat["n_lat_neigh"]
        interior_empty = lat["interior_empty"]
        void_comps = [c for c in lat["void_comps"] if len(c) >= min_void_sites]
        voids_xy = _lattice_to_xy(void_comps, rows, cols, coords)
        shape = _shape_stats(rows, cols, lat["present"], lat["use_par"],
                             lat["bbox"], n)
        fill_bbox = shape["fill_bbox"]
        total_sites = shape["n_lattice_sites"]
        n_interior_empty = len(interior_empty)
        coord_resid = _lattice_affine_residual(rows, cols, coords, pitch)
    else:
        gap_flag, _ = _physical_gaps(coords, pitch)
        n_lat_neigh = np.where(gap_flag, 3, 6)  # crude
        void_comps, voids_xy, interior_empty = [], [], []
        fill_bbox, total_sites, n_interior_empty = float("nan"), n, 0
        coord_resid = np.zeros(n)  # no lattice -> can't measure displacement

    tissue_area_sites = float(total_sites * fill_bbox) if has_array else float(n)
    # void areas as fraction of tissue (sites)
    void_area_frac = (sum(v["n_sites"] for v in voids_xy) / max(n, 1)) if voids_xy else 0.0
    largest_void_frac = (max((v["n_sites"] for v in voids_xy), default=0) / max(n, 1))
    max_void_elong = max((v["elongation"] for v in voids_xy), default=1.0)

    # ---- expression embedding & neighbor discontinuity ----
    if n > max_embed_spots:
        rng = np.random.default_rng(embed_seed)
        sub = np.sort(rng.choice(n, max_embed_spots, replace=False))
    else:
        sub = np.arange(n)
    try:
        U_sub = _expr_embedding(X[sub] if issparse(X) or hasattr(X, "__getitem__") else X,
                                seed=embed_seed)
        U = np.zeros((n, U_sub.shape[1]), np.float32)
        U[sub] = U_sub
        embed_ok = True
    except Exception:
        U = np.zeros((n, 1), np.float32)
        embed_ok = False

    edges = _neighbor_edges(coords, pitch)
    if len(edges) and embed_ok:
        # only score edges whose both endpoints are embedded
        emask = np.zeros(n, bool); emask[sub] = True
        keep = emask[edges[:, 0]] & emask[edges[:, 1]]
        e = edges[keep]
        jumps = _cosine_dist(U, e[:, 0], e[:, 1]) if len(e) else np.zeros(0)
    else:
        e = edges
        jumps = np.zeros(len(edges))
    edge_jump_mean = float(jumps.mean()) if len(jumps) else 0.0
    edge_jump_p95 = float(np.quantile(jumps, 0.95)) if len(jumps) else 0.0
    if len(jumps) > 10:
        jz = _robust_z(jumps)
        high = jz > jump_z
    else:
        high = np.zeros(len(jumps), bool)
    frac_high = float(high.mean()) if len(high) else 0.0

    # ---- cut lines: connected chains of high-jump edges ----
    cut_lines = []
    if high.any():
        hi_edges = e[high]
        # node graph over spots that participate in high-jump edges
        adj = {}
        for a, b in hi_edges:
            adj.setdefault(int(a), set()).add(int(b))
            adj.setdefault(int(b), set()).add(int(a))
        for comp in _connected_components(adj):
            if len(comp) >= min_cut_len:
                pts = coords[comp]
                cut_lines.append(dict(n=len(comp),
                                      straightness=_straightness(pts),
                                      elongation=_elongation(pts),
                                      centroid=pts.mean(0), spots=comp))
    n_cut_lines = len(cut_lines)
    max_cut_len = max((c["n"] for c in cut_lines), default=0)
    max_cut_straight = max((c["straightness"] for c in cut_lines), default=0.0)

    # ---- folds: local total-count spikes, spatially coherent ----
    # A fold stacks extra tissue on fixed capture spots -> local UMI elevation. We use a
    # robust per-spot z (neighbor MAD floored by the GLOBAL MAD so identical-neighbor
    # patches can't blow up) AND require a real elevation RATIO, so noise triplets don't
    # register as folds.
    tot = np.asarray(X.sum(1)).ravel() if issparse(X) else np.asarray(X).sum(1).ravel()
    tot = tot.astype(float)
    global_mad = np.median(np.abs(tot - np.median(tot))) + 1e-9
    fold_z_spot = np.zeros(n)
    fold_ratio = np.ones(n)
    if len(edges):
        nbrs = {i: [] for i in range(n)}
        for a, b in edges:
            nbrs[a].append(b); nbrs[b].append(a)
        for i in range(n):
            if len(nbrs[i]) >= 3:
                nb = tot[nbrs[i]]
                med = np.median(nb)
                mad = np.median(np.abs(nb - med))
                denom = 1.4826 * max(mad, 0.5 * global_mad)
                fold_z_spot[i] = (tot[i] - med) / denom
                fold_ratio[i] = tot[i] / (med + 1e-9)
    fold_cand = (fold_z_spot > fold_z) & (fold_ratio > 1.4)
    fold_comps = []
    if fold_cand.any():
        cand_idx = set(np.where(fold_cand)[0].tolist())
        adjf = {i: set() for i in cand_idx}
        for a, b in edges:
            if a in cand_idx and b in cand_idx:
                adjf[a].add(b); adjf[b].add(a)
        for comp in _connected_components(adjf):
            if len(comp) >= min_fold_spots:
                fold_comps.append(comp)
    n_folds = len(fold_comps)
    fold_spots = sum(len(c) for c in fold_comps)
    fold_area_frac = fold_spots / max(n, 1)
    max_fold_z = float(fold_z_spot.max()) if n else 0.0

    # ---- coordinate displacement (real vs synthetic separator) & physical gaps ----
    max_coord_resid = float(coord_resid.max()) if len(coord_resid) else 0.0
    p95_coord_resid = float(np.quantile(coord_resid, 0.95)) if len(coord_resid) else 0.0
    frac_displaced = float((coord_resid > 0.5).mean()) if len(coord_resid) else 0.0
    gap_flag, gap_mids = _physical_gaps(coords, pitch)
    frac_gap_spots = float(gap_flag.mean())

    # ---- boundary irregularity ----
    # solidity deficit + interior-void contribution
    boundary_irreg = _boundary_irregularity(coords, pitch, fill_bbox if has_array else np.nan)

    # ---- classify void components into tears vs missing regions ----
    events: list[DamageEvent] = []
    n_tears = n_missing = 0
    for v in voids_xy:
        area_frac = v["n_sites"] / max(n, 1)
        # elongated + straight flanks => cut/tear; blobby & sizeable => missing region
        if v["elongation"] >= 2.5:
            kind = "tear"; n_tears += 1
            sev = v["elongation"] * np.sqrt(v["n_sites"])
        elif v["n_sites"] >= max(4, 0.01 * n):
            kind = "missing_region"; n_missing += 1
            sev = area_frac * 100
        else:
            kind = "tear"; n_tears += 1
            sev = v["elongation"] * np.sqrt(v["n_sites"])
        events.append(DamageEvent(kind=kind, severity=float(sev), n_spots=v["n_sites"],
                                  area_frac=float(area_frac), elongation=float(v["elongation"]),
                                  straightness=float(v["straightness"]),
                                  extra=dict(centroid=v["centroid"].tolist())))
    # cut lines that are straight and long are also tears (expression-defined, no lattice hole)
    for c in cut_lines:
        if c["straightness"] >= 0.85 and c["n"] >= min_cut_len:
            n_tears += 1
            events.append(DamageEvent(kind="tear", severity=float(c["n"] * c["straightness"]),
                                      n_spots=c["n"], area_frac=c["n"] / max(n, 1),
                                      elongation=float(c["elongation"]),
                                      straightness=float(c["straightness"]),
                                      extra=dict(source="expr_cut")))
    # folds
    for c in fold_comps:
        z = float(fold_z_spot[c].max())
        events.append(DamageEvent(kind="fold", severity=z, n_spots=len(c),
                                  area_frac=len(c) / max(n, 1),
                                  elongation=_elongation(coords[c]),
                                  straightness=_straightness(coords[c]),
                                  extra=dict(mean_umi_ratio=float(tot[c].mean() /
                                                                  (np.median(tot) + 1e-9)))))

    # ---- aggregate damage score & label ----
    damage_score = float(
        2.0 * void_area_frac
        + 1.5 * largest_void_frac
        + 0.5 * frac_high
        + 0.5 * fold_area_frac
        + 0.3 * min(boundary_irreg, 1.0)
        + 0.05 * n_tears
    )
    if damage_score < 0.02 and (n_tears + n_folds + n_missing) == 0:
        label = "none"
    elif damage_score < 0.05:
        label = "mild"
    elif damage_score < 0.15:
        label = "moderate"
    else:
        label = "severe"

    return DamageReport(
        name=name, n_spots=n, pitch=pitch,
        n_voids=len(voids_xy), n_interior_empty_sites=n_interior_empty,
        void_area_frac=void_area_frac, largest_void_frac=largest_void_frac,
        max_void_elongation=float(max_void_elong),
        edge_jump_mean=edge_jump_mean, edge_jump_p95=edge_jump_p95,
        frac_high_jump_edges=frac_high, n_cut_lines=n_cut_lines,
        max_cut_len=int(max_cut_len), max_cut_straightness=float(max_cut_straight),
        n_folds=n_folds, fold_area_frac=fold_area_frac, max_fold_zscore=max_fold_z,
        max_coord_resid_pitch=max_coord_resid, p95_coord_resid_pitch=p95_coord_resid,
        frac_displaced=frac_displaced, frac_gap_spots=frac_gap_spots,
        fill_bbox=float(fill_bbox), boundary_irregularity=float(boundary_irreg),
        n_tears=n_tears, n_missing_regions=n_missing,
        damage_score=damage_score, severity_label=label, events=events,
    )


def _boundary_irregularity(coords: np.ndarray, pitch: float, fill_bbox: float) -> float:
    """Roughness of the tissue outline: alpha-shape-free proxy = perimeter spots'
    local convexity deficit. Returns ~0 for a smooth compact section, higher for ragged."""
    n = len(coords)
    if n < 20:
        return 0.0
    try:
        tri = Delaunay(coords)
    except Exception:
        return 0.0
    # boundary edges = simplex edges belonging to exactly one triangle after alpha-pruning
    from collections import Counter
    ec = Counter()
    thr = 1.8 * pitch
    for s in tri.simplices:
        for a, b in ((s[0], s[1]), (s[1], s[2]), (s[0], s[2])):
            d = np.linalg.norm(coords[a] - coords[b])
            if d <= thr:
                ec[(min(a, b), max(a, b))] += 1
    boundary_nodes = set()
    for (a, b), cnt in ec.items():
        if cnt == 1:
            boundary_nodes.add(a); boundary_nodes.add(b)
    if not boundary_nodes:
        return 0.0
    bpts = coords[sorted(boundary_nodes)]
    # convex hull perimeter vs actual boundary node count-based perimeter proxy
    try:
        from scipy.spatial import ConvexHull
        hull = ConvexHull(coords)
        hull_perim = hull.area  # in 2D, .area is the perimeter
    except Exception:
        return 0.0
    # actual outline length ~ boundary_nodes * pitch (each boundary spot ~1 pitch of edge)
    outline_len = len(boundary_nodes) * pitch
    # irregularity: how much longer the real outline is than the convex hull (>=0)
    return float(max(outline_len / (hull_perim + 1e-9) - 1.0, 0.0))


# ------------------------------------------------------------------------- #
# CLI
# ------------------------------------------------------------------------- #
def _load(path: str):
    import anndata as ad
    a = ad.read_h5ad(path)
    a.obsm["spatial"] = np.asarray(a.obsm["spatial"], float)
    return a


def main():
    ap = argparse.ArgumentParser(description="Detect & characterize real tissue damage (GT-free).")
    ap.add_argument("--report", required=True, help="path to a .h5ad section")
    ap.add_argument("--name", default=None)
    ap.add_argument("--json", action="store_true", help="emit the flat row as JSON")
    args = ap.parse_args()
    a = _load(args.report)
    name = args.name or Path(args.report).stem
    rep = characterize(a, name=name)
    if args.json:
        print(json.dumps(rep.to_row(), indent=2))
    else:
        print(rep.text())


if __name__ == "__main__":
    main()
