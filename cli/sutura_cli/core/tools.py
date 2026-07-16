"""The agent's tools. Each wraps the EXISTING alignment engine (no alignment
logic is reimplemented here) and emits Events so the front-end can stream the
work. Tools take (ctx, sink, ...), return metadata-only dicts, and keep all raw
expression data inside the WorkContext.

Tools: load_data, qc, distribution_check, align, post_qc.
(generate_report lives in reporting.py; both are exposed via the agent.)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import engine
from .context import Section, WorkContext
from .events import (EventSink, Note, RoutingDecision, StepFinished,
                     StepProgress, StepStarted)


# ======================================================================== #
# load_data
# ======================================================================== #
_SPACERANGER_MARKERS = ("filtered_feature_bc_matrix.h5", "filtered_feature_bc_matrix")
_XENIUM_MARKERS = ("cell_feature_matrix.h5", "cell_feature_matrix", "transcripts.parquet")


def _layers_of(adata):
    for col in ("layer", "Layer", "layer_guess", "spatialLIBD"):
        if col in adata.obs.columns:
            return [None if v is None else str(v) for v in adata.obs[col].tolist()]
    return None


def _has_layers(adata) -> bool:
    return any(c in adata.obs.columns
               for c in ("layer", "Layer", "layer_guess", "spatialLIBD"))


def _discover(path: Path):
    """Return a list of (name, fmt, loader_arg) for a file or directory."""
    path = Path(path).expanduser()
    found = []
    if path.is_file() and path.suffix == ".h5ad":
        return [(path.stem, "h5ad", path)]
    if not path.is_dir():
        return found

    # a single Space Ranger / Xenium sample directory
    names = {p.name for p in path.iterdir()}
    if any(m in names for m in _SPACERANGER_MARKERS) and "spatial" in names:
        return [(path.name, "spaceranger", path)]
    if any(m in names for m in _XENIUM_MARKERS):
        return [(path.name, "xenium", path)]

    # otherwise: all .h5ad in the directory (sorted for determinism), then any
    # nested Space Ranger sample subdirs.
    for f in sorted(path.glob("*.h5ad")):
        found.append((f.stem, "h5ad", f))
    for sub in sorted(p for p in path.iterdir() if p.is_dir()):
        sn = {p.name for p in sub.iterdir()} if sub.is_dir() else set()
        if any(m in sn for m in _SPACERANGER_MARKERS) and "spatial" in sn:
            found.append((sub.name, "spaceranger", sub))
    return found


def _load_one(fmt: str, arg: Path, workdir: Path, name: str):
    """Load one input into an AnnData and ensure an on-disk .h5ad path."""
    import anndata as ad
    if fmt == "h5ad":
        adata = ad.read_h5ad(arg)
        return adata, Path(arg)
    if fmt == "spaceranger":
        import scanpy as sc
        adata = sc.read_visium(arg)
        adata.var_names_make_unique()
    elif fmt == "xenium":
        try:
            import squidpy as sq
            adata = sq.read.xenium(arg)
        except Exception as e:
            raise RuntimeError(
                f"Xenium input detected but could not be read ({type(e).__name__}: "
                f"{e}). Provide a pre-converted .h5ad for now.")
    else:
        raise RuntimeError(f"unsupported format {fmt!r}")
    out = workdir / f"{name}.h5ad"
    adata.write_h5ad(out)
    return adata, out


def load_data(ctx: WorkContext, sink: EventSink, path: str) -> dict:
    sid = "load_data"
    sink.emit(StepStarted(step_id=sid, title="Load data",
                          detail=f"scanning {path}"))
    discovered = _discover(Path(path))
    if not discovered:
        sink.emit(StepFinished(step_id=sid, status="error",
                               summary=f"no readable sections found at {path}"))
        raise FileNotFoundError(
            f"No .h5ad / Space Ranger / Xenium sections found at {path}")

    loaded, warnings = [], []
    total = len(discovered)
    for i, (name, fmt, arg) in enumerate(discovered):
        sink.emit(StepProgress(step_id=sid, pct=int(100 * i / total),
                               message=f"reading {name} ({fmt})"))
        try:
            adata, h5ad_path = _load_one(fmt, arg, ctx.workdir, name)
        except Exception as e:
            warnings.append(str(e))
            sink.emit(Note(text=str(e), level="warn"))
            continue
        has_spatial = "spatial" in adata.obsm
        sec = ctx.add_section(Section(
            id=ctx.new_id(), name=name, fmt=fmt, h5ad_path=Path(h5ad_path),
            source=str(arg), adata=adata,
            n_spots=int(adata.n_obs), n_genes=int(adata.n_vars),
            has_spatial=has_spatial, has_layers=_has_layers(adata)))
        loaded.append(sec.meta())

    if not loaded:
        sink.emit(StepFinished(step_id=sid, status="error",
                               summary="every candidate section failed to load"))
        raise RuntimeError("No sections could be loaded. " + " ".join(warnings))

    sink.emit(StepFinished(
        step_id=sid, status="warn" if warnings else "ok",
        summary=f"{len(loaded)} section(s): " +
                ", ".join(f"{s['name']} ({s['n_spots']} spots)" for s in loaded)))
    return {"sections": loaded, "warnings": warnings}


# ======================================================================== #
# qc
# ======================================================================== #
def qc(ctx: WorkContext, sink: EventSink, section_ids=None) -> dict:
    sid = "qc"
    pipeline = engine.load_pipeline()
    sink.emit(StepStarted(step_id=sid, title="Quality control",
                          detail="validating inputs"))
    secs = ([ctx.resolve(x) for x in section_ids] if section_ids
            else ctx.ordered())
    secs = [s for s in secs if s is not None]
    results, all_pass = [], True
    for i, s in enumerate(secs):
        sink.emit(StepProgress(step_id=sid, pct=int(100 * i / max(1, len(secs))),
                               message=f"QC {s.name}"))
        _adata, err = pipeline.qc_file(str(s.h5ad_path))
        rec = {"id": s.id, "name": s.name, "pass": err is None,
               "n_spots": s.n_spots, "n_genes": s.n_genes,
               "has_layers": s.has_layers, "issue": err}
        if err:
            all_pass = False
            sink.emit(Note(text=f"{s.name}: {err}", level="warn"))
        results.append(rec)
    sink.emit(StepFinished(
        step_id=sid, status="ok" if all_pass else "warn",
        summary=f"{sum(r['pass'] for r in results)}/{len(results)} passed"))
    return {"results": results, "all_pass": all_pass}


# ======================================================================== #
# distribution_check  (routing decision)
# ======================================================================== #
def _projector(ctx: WorkContext):
    if ctx._projector is None:
        orch = engine.load_orchestrator()
        ctx._projector = orch.Projector()
    return ctx._projector


def distribution_check(ctx: WorkContext, sink: EventSink, ref_id: str,
                       mov_id: str) -> dict:
    sid = f"route:{ref_id}-{mov_id}"
    orch = engine.load_orchestrator()
    ref, mov = ctx.resolve(ref_id), ctx.resolve(mov_id)
    if ref is None or mov is None:
        raise ValueError(f"unknown section(s): {ref_id!r}, {mov_id!r}")
    sink.emit(StepStarted(step_id=sid, title="Distribution check",
                          detail=f"{ref.name} vs {mov.name}"))
    cfg = orch.OrchestratorConfig()
    proj = _projector(ctx)
    d = orch.distribution_check(ref.adata, mov.adata, proj, cfg)
    # Honest preview of what will run. Off-distribution is NOT simply "PASTE2":
    # the orchestrator tries auto-adapted Sutura vs PASTE2 and keeps the best
    # (unless the gene panel is too different to adapt the model at all).
    if d["in_distribution"]:
        method = "Sutura (graph model)"
    elif d["gene_overlap"] >= cfg.min_gene_overlap:
        method = "off-distribution: auto-adapt Sutura vs PASTE2, keep best"
    else:
        method = "PASTE2 (gene panel too different to adapt the model)"
    sink.emit(RoutingDecision(
        pair=f"{ref.name} -> {mov.name}", method=method, reason=d["reason"],
        in_distribution=bool(d["in_distribution"]),
        confidence=float(d["confidence"]), mahalanobis=float(d["maha"]),
        gene_overlap=float(d["gene_overlap"])))
    sink.emit(StepFinished(
        step_id=sid, status="ok",
        summary=f"route -> {method} (Mahalanobis {d['maha']:.2f}, "
                f"gene overlap {int(d['gene_overlap']*100)}%)"))
    return {"ref": ref.id, "mov": mov.id, "ref_name": ref.name,
            "mov_name": mov.name, "routed_method": method, **d}


# ======================================================================== #
# align
# ======================================================================== #
_STAGE_MSG = {
    "loading": "loading sections",
    "distribution_check": "checking distribution / routing",
    "aligning_sutura": "aligning with Sutura graph model",
    "auto_adapt": "off-distribution: auto-adapting the model to your data",
    "aligning_paste2": "aligning with PASTE2",
    "post_qc_retry": "post-QC: trying PASTE2 as a safety net",
    "writing_output": "writing aligned output",
    "done": "done",
}


def _forced_align(ctx, ref, mov, method, out_dir):
    """Reuse the engine's method wrappers to force a specific method."""
    import torch
    pipeline = engine.load_pipeline()
    orch = engine.load_orchestrator()
    root = engine.find_repo_root()
    cfg = orch.OrchestratorConfig()
    if method == "paste2":
        pred, pitch = pipeline.align_paste2(ref.adata, mov.adata)
        label, reason = "PASTE2", "method forced by user request"
    elif method in ("sutura", "sutura_zeroshot"):
        from train_cross import ARCACrossNet
        from shared_basis import load_basis
        base_ck = torch.load(root / "results" / cfg.sutura_ckpt,
                             map_location="cpu", weights_only=False)
        hp, dim = base_ck["args"], base_ck["dim"]
        model = ARCACrossNet(dim, hp["hidden"], hp["layers"], hp["attn_dim"])
        model.load_state_dict(base_ck["state_dict"]); model.eval()
        pred, pitch = pipeline.align_sutura(model, ref.adata, mov.adata,
                                            load_basis(), hp["knn"])
        label, reason = "Sutura (graph model)", "method forced by user request"
    else:
        raise ValueError(f"cannot force unknown method {method!r}")
    sc = pipeline._score(pred, ref.adata, mov.adata, pitch)
    aligned = mov.adata.copy()
    aligned.obsm["spatial_aligned"] = pred.astype(np.float32)
    aligned.uns["sutura_alignment"] = {"method": method, "reason": reason,
                                       "metric": sc["metric"], "score": sc["value"]}
    aligned.write_h5ad(Path(out_dir) / "aligned.h5ad")
    return {
        "method": method, "method_label": label, "reason": reason,
        "in_distribution": None, "in_dist_confidence": None,
        "mahalanobis": None, "gene_overlap": None,
        "metric": sc["metric"], "score": sc["value"],
        "has_ground_truth": sc["has_ground_truth"],
        "footprint_coverage": sc["coverage"], "retry": False, "candidates": [],
        "n_ref": int(ref.adata.n_obs), "n_mov": int(mov.adata.n_obs),
        "runtime_seconds": None, "output_file": "aligned.h5ad",
        "aligned_coords": pred.astype(float).round(1).tolist(),
        "ref_coords": np.asarray(ref.adata.obsm["spatial"], float).round(1).tolist(),
    }


def align(ctx: WorkContext, sink: EventSink, ref_id: str, mov_id: str,
          out_dir: Path, extras=None, force_method=None) -> dict:
    ref, mov = ctx.resolve(ref_id), ctx.resolve(mov_id)
    if ref is None or mov is None:
        raise ValueError(f"unknown section(s): {ref_id!r}, {mov_id!r}")
    sid = f"align:{ref.id}-{mov.id}"
    out_dir = Path(out_dir)
    label_hint = (f"forcing {force_method}" if force_method
                  else "auto-routed orchestrator")
    sink.emit(StepStarted(step_id=sid, title="Align",
                          detail=f"{ref.name} -> {mov.name} ({label_hint})"))

    if force_method:
        result = _forced_align(ctx, ref, mov, force_method, out_dir)
        sink.emit(StepProgress(step_id=sid, pct=95, message="writing aligned output"))
    else:
        pipeline = engine.load_pipeline()
        extra_paths = [str(ctx.resolve(e).h5ad_path) for e in (extras or [])
                       if ctx.resolve(e)]
        files = [str(ref.h5ad_path), str(mov.h5ad_path), *extra_paths]

        def _progress(stage, pct):
            sink.emit(StepProgress(step_id=sid, pct=int(pct),
                                   message=_STAGE_MSG.get(stage, stage)))
        result = pipeline.run_alignment(files, out_dir, progress=_progress)

    # attach reconstruction inputs (coords + layers; not expression)
    result["ref_name"] = ref.name
    result["mov_name"] = mov.name
    result["ref_layers"] = _layers_of(ref.adata)
    result["mov_layers"] = _layers_of(mov.adata)
    result["_pitch"] = _pitch_of(ref.adata)

    gt = "measured error" if result["has_ground_truth"] else "coverage proxy"
    score_txt = (f"{result['score']:.2f} spot-pitch median error"
                 if result["has_ground_truth"]
                 else f"{result['score']:.2f} footprint coverage")
    sink.emit(StepFinished(
        step_id=sid, status="ok",
        summary=f"{result['method_label']} - {score_txt} ({gt})"))
    return result


def _pitch_of(adata) -> float:
    from scipy.spatial import cKDTree
    c = np.asarray(adata.obsm["spatial"], float)
    return float(np.median(cKDTree(c).query(c, k=2)[0][:, 1]))


# ======================================================================== #
# post_qc
# ======================================================================== #
def post_qc(ctx: WorkContext, sink: EventSink, align_result: dict,
            ref_id: str, mov_id: str) -> dict:
    sid = f"postqc:{ref_id}-{mov_id}"
    agents = engine.load_agents()
    ref, mov = ctx.resolve(ref_id), ctx.resolve(mov_id)
    sink.emit(StepStarted(step_id=sid, title="Post-alignment QC",
                          detail=f"{ref.name} -> {mov.name}"))
    pred = np.asarray(align_result["aligned_coords"], float)
    ref_coords = np.asarray(ref.adata.obsm["spatial"], float)
    mov_coords = np.asarray(mov.adata.obsm["spatial"], float)

    consistency = float(np.mean(agents.neighbor_consistency(pred, mov_coords)))
    coverage = float(agents.footprint_coverage(pred, ref_coords))

    # verdict: GT error if available, else coverage/consistency proxies
    if align_result["has_ground_truth"]:
        good = align_result["score"] <= 6.0
        basis = f"median error {align_result['score']:.2f} spot-pitch"
    else:
        good = coverage >= 0.6 and consistency >= 0.5
        basis = f"coverage {coverage:.2f}, neighbour consistency {consistency:.2f}"
    verdict = "pass" if good else "flag"
    sink.emit(StepFinished(
        step_id=sid, status="ok" if good else "warn",
        summary=f"{verdict}: {basis}"))
    return {"verdict": verdict, "neighbor_consistency": round(consistency, 3),
            "footprint_coverage": round(coverage, 3), "basis": basis}
