#!/usr/bin/env python3
"""
sutura_engine.py - the deploy-time alignment engine used by the Nextflow / Snakemake
integration.

This module wraps the research code in ``src/`` (orchestrator, shared-basis GNN,
PASTE2 baseline, gate refinement) into a single function that aligns ONE real moving
section onto ONE real reference section and returns aligned coordinates plus metrics.

It differs from ``src/orchestrator.py`` in one important way: the research orchestrator
is a *benchmark* harness - it applies a synthetic tear/warp to the moving section and
scores against a known ground truth. Here we align the *real, observed* moving section
(no synthetic warp) - i.e. the actual deploy scenario a lab needs.

Design goals
------------
* Portable: at runtime it needs only the small frozen assets (``shared_basis.npz``,
  ``arca_shared_basis.pt``, and a precomputed distribution reference ``dist_reference.npz``).
  It does NOT need the multi-hundred-MB training h5ad files, so it fits in a lean container.
* Robust: every section is QC'd; a routing failure or a missing asset degrades gracefully
  to an explicit method rather than crashing.
* Honest metrics: with a shared Visium array layout we report true registration error
  (array-bridge GT); otherwise we report ground-truth-free proxies (footprint coverage,
  local distortion) so a lab always gets *some* quality signal.

Public API
----------
    align_pair(ref, mov, *, method="auto", gate_refine=False, ...) -> AlignResult
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np


# --------------------------------------------------------------------------- #
# engine wiring: make src/ importable and locate frozen assets
# --------------------------------------------------------------------------- #
def _resolve_engine_root(engine_root: Optional[str]) -> Path:
    """Locate the repository root that holds ``src/`` and ``results/``.

    Order of precedence: explicit arg -> $SUTURA_ENGINE_ROOT -> walk up from this file.
    """
    candidates = []
    if engine_root:
        candidates.append(Path(engine_root))
    if os.environ.get("SUTURA_ENGINE_ROOT"):
        candidates.append(Path(os.environ["SUTURA_ENGINE_ROOT"]))
    here = Path(__file__).resolve()
    # bin/ -> nextflow/ -> integrations/ -> repo root
    candidates.append(here.parents[3])
    candidates.append(Path.cwd())
    for c in candidates:
        if (c / "src" / "train_cross.py").exists():
            return c
    # last resort: return the first candidate so the caller gets a clear error
    return candidates[0]


def _asset_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets"


class EnginePaths:
    """Resolves and validates every path the engine needs, with clear errors."""

    def __init__(self, engine_root: Optional[str] = None,
                 basis: Optional[str] = None,
                 checkpoint: Optional[str] = None,
                 dist_reference: Optional[str] = None):
        self.root = _resolve_engine_root(engine_root)
        self.src = self.root / "src"
        results = self.root / "results"
        assets = _asset_dir()

        # basis .npz: prefer explicit, then results/, then bundled asset copy
        self.basis = self._first_existing(
            basis, results / "shared_basis.npz", assets / "shared_basis.npz")
        self.checkpoint = self._first_existing(
            checkpoint, results / "arca_shared_basis.pt", assets / "arca_shared_basis.pt")
        # distribution reference is optional (routing degrades gracefully without it)
        self.dist_reference = self._first_existing(
            dist_reference, assets / "dist_reference.npz",
            results / "dist_reference.npz", required=False)

    @staticmethod
    def _first_existing(*paths, required=True):
        for p in paths:
            if p and Path(p).exists():
                return Path(p)
        if required:
            tried = ", ".join(str(p) for p in paths if p)
            raise FileNotFoundError(
                f"required engine asset not found (looked in: {tried}). "
                f"Set --engine-root or copy the asset into integrations/nextflow/assets/.")
        return None

    def add_src_to_syspath(self):
        if str(self.src) not in sys.path:
            sys.path.insert(0, str(self.src))


# --------------------------------------------------------------------------- #
# section loading (AnnData .h5ad OR Space Ranger output directory)
# --------------------------------------------------------------------------- #
def load_section(path: str):
    """Load a spatial section from an .h5ad file or a Space Ranger output directory.

    A Space Ranger directory is detected by the presence of a filtered matrix and a
    ``spatial/`` folder; we read it with scanpy's Visium reader. A directory that
    contains a single .h5ad is also accepted.
    """
    import anndata as ad

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"input section not found: {p}")

    if p.is_file() and p.suffix in (".h5ad", ".h5"):
        if p.suffix == ".h5ad":
            a = ad.read_h5ad(p)
        else:  # bare 10x .h5 with no spatial - unusual, but handle it
            import scanpy as sc
            a = sc.read_10x_h5(p)
        return _normalise_section(a, source=str(p))

    if p.is_dir():
        # Space Ranger output dir?
        has_spatial = (p / "spatial").is_dir()
        matrices = list(p.glob("*filtered_feature_bc_matrix.h5")) + \
            list(p.glob("filtered_feature_bc_matrix.h5"))
        raw = list(p.glob("*raw_feature_bc_matrix.h5"))
        if has_spatial and (matrices or raw or (p / "filtered_feature_bc_matrix").is_dir()):
            import scanpy as sc
            # scanpy expects the .h5; pick filtered if present, else raw
            count_file = None
            for cand in matrices + raw:
                count_file = cand.name
                break
            if count_file is None:
                # matrix in mtx form
                a = sc.read_visium(p)
            else:
                a = sc.read_visium(p, count_file=count_file)
            a.var_names_make_unique()
            return _normalise_section(a, source=str(p))
        # directory holding a single h5ad
        h5ads = list(p.glob("*.h5ad"))
        if len(h5ads) == 1:
            return _normalise_section(ad.read_h5ad(h5ads[0]), source=str(h5ads[0]))
        raise ValueError(
            f"'{p}' is a directory but is not a recognisable Space Ranger output "
            f"(need a spatial/ folder + filtered_feature_bc_matrix) and does not "
            f"contain exactly one .h5ad file.")

    raise ValueError(f"unsupported input '{p}': expected .h5ad, .h5, or a "
                     f"Space Ranger output directory.")


def _normalise_section(a, source: str):
    """Coerce spatial coords to float, record provenance."""
    if "spatial" in a.obsm:
        a.obsm["spatial"] = np.asarray(a.obsm["spatial"], dtype=float)
    a.uns["_sutura_source"] = source
    return a


# --------------------------------------------------------------------------- #
# QC
# --------------------------------------------------------------------------- #
def qc_section(a, tag: str, min_spots: int):
    issues, warnings = [], []
    if a.n_obs < min_spots:
        issues.append(f"{tag}: only {a.n_obs} spots (< {min_spots} required)")
    if "spatial" not in a.obsm:
        issues.append(f"{tag}: missing obsm['spatial'] (no spatial coordinates)")
    if a.n_vars == 0:
        issues.append(f"{tag}: no genes in the expression matrix")
    if not {"array_row", "array_col"} <= set(a.obs.columns):
        warnings.append(f"{tag}: no array_row/array_col - ground-truth error "
                        f"cannot be computed (proxy metrics only)")
    return issues, warnings


# --------------------------------------------------------------------------- #
# distribution routing (portable: uses a precomputed reference, not the raw data)
# --------------------------------------------------------------------------- #
class Router:
    """Decides sutura (in-distribution) vs paste2 (off-distribution) for a pair.

    Reuses the frozen shared basis to embed a section and measures (a) gene-vocabulary
    overlap and (b) Mahalanobis distance of the embedding mean to the training-donor
    distribution. Mirrors src/orchestrator.py's logic but reads a *cached* training
    reference so it needs no bulky data at runtime.
    """

    def __init__(self, paths: EnginePaths, maha_threshold=2.5, min_gene_overlap=0.5,
                 conf_steepness=1.5):
        from shared_basis import load_basis
        b = load_basis(paths.basis)
        self.genes = np.asarray(b["genes"])
        self.gpos = {g: i for i, g in enumerate(self.genes)}
        self.comp = b["components"]
        self.mu = b["feat_mean"]
        self.sd = b["feat_std"]
        self.maha_threshold = maha_threshold
        self.min_gene_overlap = min_gene_overlap
        self.conf_steepness = conf_steepness
        self.tmu = self.tinv = None
        if paths.dist_reference is not None:
            d = np.load(paths.dist_reference, allow_pickle=True)
            self.tmu = d["tmu"]
            self.tinv = d["tinv"]

    def project(self, a):
        import scipy.sparse as sp
        vn = np.asarray(a.var_names)
        keep = [(j, self.gpos[g]) for j, g in enumerate(vn) if g in self.gpos]
        overlap = len(keep) / len(self.genes)
        X = a.X.tocsc() if sp.issparse(a.X) else np.asarray(a.X, np.float32)
        M = np.zeros((a.n_obs, len(self.genes)), np.float32)
        if keep:
            src = [j for j, _ in keep]
            dst = [c for _, c in keep]
            sub = X[:, src].toarray() if sp.issparse(X) else X[:, src]
            M[:, dst] = sub
        counts = M.sum(1, keepdims=True)
        counts[counts == 0] = 1.0
        Z = ((np.log1p(M * (1e4 / counts)) @ self.comp.T) - self.mu) / self.sd
        return Z.astype(np.float32), overlap

    def route(self, A, B):
        Za, ov_a = self.project(A)
        Zb, ov_b = self.project(B)
        overlap = float(min(ov_a, ov_b))
        if overlap < self.min_gene_overlap:
            return dict(method="paste2", in_distribution=False, confidence=0.02,
                        maha=None, gene_overlap=round(overlap, 3),
                        reason=(f"gene-vocabulary overlap {overlap*100:.0f}% < "
                                f"{self.min_gene_overlap*100:.0f}% (incompatible panel) "
                                f"-> PASTE2"))
        if self.tmu is None:
            # no distribution reference available: cannot measure in/off-distribution.
            return dict(method="paste2", in_distribution=None, confidence=None,
                        maha=None, gene_overlap=round(overlap, 3),
                        reason=("no distribution reference asset; defaulting to the "
                                "robust PASTE2 route (use --method sutura to force)"))
        Z = np.vstack([Za, Zb])
        d = Z.mean(0) - self.tmu
        maha = float(np.sqrt(d @ self.tinv @ d))
        conf = float(1.0 / (1.0 + np.exp(-self.conf_steepness *
                                         (self.maha_threshold - maha))))
        in_dist = maha < self.maha_threshold
        return dict(method="sutura" if in_dist else "paste2",
                    in_distribution=bool(in_dist), confidence=round(conf, 3),
                    maha=round(maha, 2), gene_overlap=round(overlap, 3),
                    reason=(f"Mahalanobis {maha:.2f} "
                            f"{'<' if in_dist else '>'} threshold "
                            f"{self.maha_threshold} -> "
                            f"{'Sutura (in-distribution)' if in_dist else 'PASTE2 (off-distribution)'}"))


# --------------------------------------------------------------------------- #
# aligners (REAL moving section, no synthetic warp)
# --------------------------------------------------------------------------- #
def _median_pitch(coords):
    from scipy.spatial import cKDTree
    coords = np.asarray(coords, float)
    d, _ = cKDTree(coords).query(coords, k=2)
    return float(np.median(d[:, 1]))


def align_sutura(A, B, router: Router, paths: EnginePaths, knn_override=None):
    """Shared-basis GNN alignment: predict a reference-frame coordinate for every moving spot."""
    import torch
    from train_cross import ARCACrossNet, graph_tensors

    ck = torch.load(paths.checkpoint, map_location="cpu", weights_only=False)
    a = ck["args"]
    knn = knn_override or a["knn"]
    model = ARCACrossNet(ck["dim"], a["hidden"], a["layers"], a["attn_dim"])
    model.load_state_dict(ck["state_dict"])
    model.eval()

    coords_ref = np.asarray(A.obsm["spatial"], float)
    coords_mov = np.asarray(B.obsm["spatial"], float)
    pitch = _median_pitch(coords_ref)
    Z_A, _ = router.project(A)
    Z_B, _ = router.project(B)
    ga = graph_tensors(coords_ref, Z_A, knn, pitch)
    gb = graph_tensors(coords_mov, Z_B, knn, pitch)
    a_norm = torch.from_numpy((coords_ref / pitch).astype(np.float32))
    with torch.no_grad():
        pred = model(ga, gb, a_norm).numpy() * pitch    # (n_mov, 2) reference-frame coords
    return pred, pitch, dict(base_coords=None)


def align_paste2(A, B, s=0.99, alpha=0.1):
    """PASTE2 partial optimal-transport alignment: barycentric ref-frame coords per moving spot."""
    from paste2.PASTE2 import partial_pairwise_align
    from paste2.helper import filter_for_common_genes
    from scoring import barycentric_projection

    coords_ref = np.asarray(A.obsm["spatial"], float)
    pitch = _median_pitch(coords_ref)
    Aa, Bb = A.copy(), B.copy()
    filter_for_common_genes([Aa, Bb])
    pi = np.asarray(partial_pairwise_align(Aa, Bb, s=s, alpha=alpha,
                                           dissimilarity="pca", verbose=False))
    pred, col_mass = barycentric_projection(pi, np.asarray(Aa.obsm["spatial"], float))
    return pred, pitch, dict(base_coords=pred.copy(), col_mass=col_mass,
                             moving_coords=np.asarray(Bb.obsm["spatial"], float))


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def footprint_coverage(pred, ref_coords):
    """No-GT proxy: spread of predictions vs reference footprint. ~1 healthy, <<1 collapse."""
    finite = np.isfinite(pred).all(1)
    if finite.sum() < 3:
        return None

    def spread(P):
        c = np.nanmean(P, 0)
        return float(np.nanmedian(np.linalg.norm(P - c, axis=1)))
    return round(spread(pred[finite]) / (spread(np.asarray(ref_coords, float)) + 1e-9), 4)


def local_distortion(pred, moving_coords, pitch, k=6):
    """No-GT proxy: how much the moving-frame kNN graph is stretched by the mapping.

    For each moving spot we take its k nearest neighbours in the *observed* moving frame
    and measure the change in edge length after mapping to the reference frame, in pitch
    units. A locally rigid (good) alignment keeps neighbour distances similar; a diffuse
    or collapsed mapping distorts them. Returns the median absolute edge-length change.
    """
    from scipy.spatial import cKDTree
    mov = np.asarray(moving_coords, float)
    pred = np.asarray(pred, float)
    finite = np.isfinite(pred).all(1)
    if finite.sum() < k + 1:
        return None
    idx_map = np.where(finite)[0]
    sub_mov = mov[finite]
    sub_pred = pred[finite]
    tree = cKDTree(sub_mov)
    d, nn = tree.query(sub_mov, k=min(k + 1, len(sub_mov)))
    diffs = []
    for i in range(len(sub_mov)):
        for jj in range(1, nn.shape[1]):
            j = nn[i, jj]
            len_mov = np.linalg.norm(sub_mov[i] - sub_mov[j])
            len_pred = np.linalg.norm(sub_pred[i] - sub_pred[j])
            diffs.append(abs(len_pred - len_mov))
    if not diffs:
        return None
    return round(float(np.median(diffs)) / pitch, 4)


def array_bridge_error(A, B, pred, pitch, extra_mask=None):
    """True registration error (pitch units) when both sections share a Visium array layout."""
    if not ({"array_row", "array_col"} <= set(A.obs.columns) and
            {"array_row", "array_col"} <= set(B.obs.columns)):
        return None
    from train_cross import array_bridge
    from scoring import registration_error_stats
    gt, have = array_bridge(A, B)
    if have.sum() == 0:
        return None
    mask = have.copy()
    if extra_mask is not None:
        mask &= np.asarray(extra_mask, bool)
    stats = registration_error_stats(pred, gt, mask=mask)
    if stats["n"] == 0:
        return None
    # registration_error_stats reports pixels; convert distances to pitch units (the
    # research convention: a good alignment is a few pitch) and keep the raw count.
    return {k: (round(v / pitch, 4) if k in ("mean", "median", "p90", "max")
                else v) for k, v in stats.items()}


# --------------------------------------------------------------------------- #
# result container
# --------------------------------------------------------------------------- #
@dataclass
class AlignResult:
    pair_id: str
    status: str                       # "ok" | "failed"
    method: str = ""
    routing: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    n_ref: int = 0
    n_mov: int = 0
    pitch: float = 0.0
    gate_refine: Optional[dict] = None
    warnings: list = field(default_factory=list)
    error: Optional[str] = None
    runtime_sec: float = 0.0

    def to_json(self):
        return json.dumps(asdict(self), indent=2, default=_json_default)


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


# --------------------------------------------------------------------------- #
# top-level align
# --------------------------------------------------------------------------- #
def align_pair(ref_path, mov_path, *, pair_id="pair", method="auto",
               gate_refine=False, gate_order="affine", subsample=0, seed=0,
               min_spots=100, engine_root=None, basis=None, checkpoint=None,
               dist_reference=None, knn=None):
    """Align one moving section onto one reference section. Never raises for expected
    real-world problems - returns an AlignResult with status='failed' and a reason.

    Returns (AlignResult, aligned_moving_AnnData_or_None).
    """
    import time
    t0 = time.time()
    res = AlignResult(pair_id=pair_id, status="failed")
    try:
        paths = EnginePaths(engine_root, basis, checkpoint, dist_reference)
        paths.add_src_to_syspath()

        A = load_section(ref_path)
        B = load_section(mov_path)

        # QC both sections
        issues, warns = [], []
        for tag, x in [("reference", A), ("moving", B)]:
            i, w = qc_section(x, tag, min_spots)
            issues += i
            warns += w
        res.warnings = warns
        res.n_ref, res.n_mov = int(A.n_obs), int(B.n_obs)
        if issues:
            res.error = "QC failed: " + "; ".join(issues)
            res.runtime_sec = round(time.time() - t0, 2)
            return res, None

        # optional subsampling for speed (deterministic)
        if subsample and subsample > 0:
            A = _subsample(A, subsample, seed)
            B = _subsample(B, subsample, seed + 1)
            res.n_ref, res.n_mov = int(A.n_obs), int(B.n_obs)

        router = Router(paths)

        # routing
        if method == "auto":
            routing = router.route(A, B)
            chosen = routing["method"]
        else:
            chosen = method
            routing = dict(method=method, forced=True,
                           reason=f"method forced to {method} by configuration")
            # still record overlap for the report if cheap
            try:
                _, ov_a = router.project(A)
                _, ov_b = router.project(B)
                routing["gene_overlap"] = round(float(min(ov_a, ov_b)), 3)
            except Exception:
                pass
        res.routing = routing

        # alignment
        if chosen == "sutura":
            pred, pitch, aux = align_sutura(A, B, router, paths, knn_override=knn)
        elif chosen == "paste2":
            pred, pitch, aux = align_paste2(A, B)
        else:
            res.error = f"unknown method '{chosen}' (expected auto|sutura|paste2)"
            res.runtime_sec = round(time.time() - t0, 2)
            return res, None
        res.method = chosen
        res.pitch = round(pitch, 4)

        # optional gate refinement (only meaningful on an OT base such as PASTE2)
        extra_mask = None
        if gate_refine:
            if aux.get("base_coords") is None:
                res.warnings.append(
                    "gate refinement requested but the chosen method is not an OT "
                    "aligner (gate refines a PASTE2-style base); skipped.")
            else:
                from gate_refine import gate_refine as _gate
                base = aux["base_coords"]
                moving = aux["moving_coords"]
                refined, info = _gate(base, moving, order=gate_order,
                                      pitch=pitch, return_info=True)
                # never-regress bookkeeping is meaningful only with GT; if we have array
                # bridge GT, keep the better one, else keep the refined (validated safe).
                cm = aux.get("col_mass")
                mask = (cm > 0) if cm is not None else None
                gt_stats_base = array_bridge_error(A, B, base, pitch, extra_mask=mask)
                gt_stats_ref = array_bridge_error(A, B, refined, pitch, extra_mask=mask)
                kept = True
                if gt_stats_base and gt_stats_ref:
                    kept = gt_stats_ref["median"] <= gt_stats_base["median"]
                res.gate_refine = dict(
                    order=gate_order, gated_fraction=round(float(info["gated_fraction"]), 4),
                    n_pieces=len(info["pieces"]), kept=bool(kept),
                    base_median=gt_stats_base["median"] if gt_stats_base else None,
                    refined_median=gt_stats_ref["median"] if gt_stats_ref else None)
                if kept:
                    pred = refined
                    res.method = chosen + "+gate_refine"

        # metrics
        col_mass = aux.get("col_mass")
        if col_mass is not None:
            extra_mask = col_mass > 0
        metrics = dict(
            footprint_coverage=footprint_coverage(pred, A.obsm["spatial"]),
            local_distortion_pitch=local_distortion(
                pred, B.obsm["spatial"], pitch),
            n_aligned=int(np.isfinite(pred).all(1).sum()),
            n_moving=int(B.n_obs),
        )
        gt = array_bridge_error(A, B, pred, pitch, extra_mask=extra_mask)
        if gt is not None:
            metrics["registration_error_pitch"] = gt
        res.metrics = metrics
        res.status = "ok"
        res.runtime_sec = round(time.time() - t0, 2)

        aligned = _build_aligned_anndata(B, pred, A, res)
        return res, aligned

    except Exception as e:  # anything unexpected -> failed result, not a crash
        import traceback
        res.error = f"{type(e).__name__}: {e}"
        res.warnings.append(traceback.format_exc().splitlines()[-1])
        res.runtime_sec = round(time.time() - t0, 2)
        return res, None


def _subsample(a, n, seed):
    if a.n_obs <= n:
        return a
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(a.n_obs, size=n, replace=False))
    return a[idx].copy()


def _build_aligned_anndata(B, pred, A, res: AlignResult):
    """Return the moving section carrying its aligned reference-frame coordinates."""
    out = B.copy()
    out.obsm["spatial_original"] = np.asarray(B.obsm["spatial"], float)
    out.obsm["spatial_aligned"] = np.asarray(pred, float)
    # convention: overwrite 'spatial' with the aligned frame so downstream tools that
    # read obsm['spatial'] see the registered coordinates; original kept alongside.
    out.obsm["spatial"] = np.asarray(pred, float)
    out.uns["sutura_alignment"] = dict(
        pair_id=res.pair_id, method=res.method, pitch=res.pitch,
        routing=res.routing, metrics=res.metrics,
        reference_source=A.uns.get("_sutura_source", ""),
        moving_source=B.uns.get("_sutura_source", ""))
    return out
