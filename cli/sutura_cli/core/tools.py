"""The agent's tools. Each wraps the EXISTING alignment engine (no alignment
logic is reimplemented here) and emits Events so the front-end can stream the
work. Tools take (ctx, sink, ...), return metadata-only dicts, and keep all raw
expression data inside the WorkContext.

Tools: load_data, qc, distribution_check, align, post_qc.
(generate_report lives in reporting.py; both are exposed via the agent.)
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from . import engine
from .context import Section, WorkContext
from .events import (EventSink, Note, RoutingDecision, StepFinished,
                     StepProgress, StepStarted)

# Per-pair alignment time limit. A single pathological pair (e.g. a PASTE2 /
# optimal-transport solve that wedges or grinds for minutes) must not hang the
# whole job — it is skipped like any other bad pair. Generous default; normal
# DLPFC pairs align in well under 30s. Override with SUTURA_ALIGN_TIMEOUT (0 or
# negative disables the limit).
try:
    _ALIGN_TIMEOUT = float(os.environ.get("SUTURA_ALIGN_TIMEOUT", "150"))
except ValueError:
    _ALIGN_TIMEOUT = 150.0


def _call_with_timeout(fn, timeout: float, what: str):
    """Run fn() in a daemon thread and give up after `timeout` seconds. On
    timeout, raise AlignError so the caller skips this pair and continues; the
    underlying engine call keeps running in the (daemon) background thread —
    Python can't safely kill it, but it no longer blocks the pipeline."""
    if not timeout or timeout <= 0:
        return fn()
    box: dict = {}

    def _run():
        try:
            box["r"] = fn()
        except BaseException as e:      # propagate any engine failure verbatim
            box["e"] = e

    t = threading.Thread(target=_run, name="sutura-align", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise AlignError(
            f"{what} exceeded the {int(timeout)}s per-pair time limit and was "
            f"skipped (the engine alignment call was still running). Set "
            f"SUTURA_ALIGN_TIMEOUT to change or disable this limit.")
    if "e" in box:
        raise box["e"]
    return box.get("r")


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


# alternative spatial-coordinate locations we can recover from
_OBSM_SPATIAL_ALIASES = ("spatial", "X_spatial", "spatial_coords", "xy",
                         "X_umap_spatial", "spatial_stereoseq")
_OBS_XY_PAIRS = (("x", "y"), ("X", "Y"),
                 ("imagecol", "imagerow"), ("imagerow", "imagecol"),
                 ("pxl_col_in_fullres", "pxl_row_in_fullres"),
                 ("array_col", "array_row"), ("x_centroid", "y_centroid"),
                 ("center_x", "center_y"))


class LoaderError(ValueError):
    """A user-facing loader problem with an actionable message (no stack trace)."""


class AlignError(RuntimeError):
    """A user-facing alignment failure with a readable message (no stack trace)."""


def _ensure_spatial(adata, name):
    """Guarantee adata.obsm['spatial'] is an (n,2) float array, recovering it from
    common alternative locations. Raises LoaderError with guidance if impossible."""
    import numpy as np
    if "spatial" in adata.obsm:
        coords = np.asarray(adata.obsm["spatial"], float)
        if coords.ndim == 2 and coords.shape[1] >= 2:
            adata.obsm["spatial"] = coords[:, :2]
            return None
    # try alternative obsm keys
    for key in _OBSM_SPATIAL_ALIASES:
        if key in adata.obsm:
            arr = np.asarray(adata.obsm[key], float)
            if arr.ndim == 2 and arr.shape[1] >= 2:
                adata.obsm["spatial"] = arr[:, :2]
                return f"{name}: used obsm['{key}'] as spatial coordinates"
    # try pairs of obs columns
    for cx, cy in _OBS_XY_PAIRS:
        if cx in adata.obs.columns and cy in adata.obs.columns:
            try:
                xy = np.column_stack([adata.obs[cx].to_numpy(float),
                                      adata.obs[cy].to_numpy(float)])
            except (ValueError, TypeError):
                continue
            adata.obsm["spatial"] = xy
            return f"{name}: built spatial coordinates from obs['{cx}'],obs['{cy}']"
    have_obsm = list(adata.obsm.keys()) or ["(none)"]
    raise LoaderError(
        f"{name}: no spatial coordinates found. Sutura needs obsm['spatial'] "
        f"(an n x 2 array of x,y positions). Available obsm keys: {have_obsm}. "
        f"Add coordinates as adata.obsm['spatial'] and re-save the .h5ad.")


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
    """Load one input into an AnnData with obsm['spatial']; return
    (adata, on_disk_h5ad_path, note_or_None). Raises LoaderError on user-facing
    problems (never a bare stack trace)."""
    import anndata as ad
    note = None
    if fmt == "h5ad":
        try:
            adata = ad.read_h5ad(arg)
        except Exception as e:
            raise LoaderError(f"{name}: not a readable .h5ad file "
                              f"({type(e).__name__}: {e}).")
        if adata.n_obs == 0 or adata.n_vars == 0:
            raise LoaderError(f"{name}: the file has {adata.n_obs} cells and "
                              f"{adata.n_vars} genes - it is empty.")
        note = _ensure_spatial(adata, name)
        return adata, Path(arg), note

    if fmt == "spaceranger":
        import scanpy as sc
        h5 = Path(arg)
        if not (h5 / "spatial").is_dir():
            raise LoaderError(
                f"{name}: looks like a Space Ranger dir but has no spatial/ "
                f"subfolder. Expected filtered_feature_bc_matrix.h5 + spatial/.")
        try:
            adata = sc.read_visium(arg)
        except Exception as e:
            raise LoaderError(
                f"{name}: could not read Space Ranger output "
                f"({type(e).__name__}: {e}). Expected a folder with "
                f"filtered_feature_bc_matrix.h5 and a spatial/ subfolder.")
        adata.var_names_make_unique()
        note = _ensure_spatial(adata, name)
    elif fmt == "xenium":
        raise LoaderError(
            f"{name}: Xenium input detected at {arg}, but automated Xenium "
            f"ingest is not available in this environment (no Xenium reader in "
            f"the installed squidpy). Convert the Xenium output to AnnData first "
            f"(cells as obs, obsm['spatial'] = cell x,y centroids) and save a "
            f".h5ad, then point Sutura at that file.")
    else:
        raise LoaderError(f"{name}: unsupported input format {fmt!r}.")
    out = workdir / f"{name}.h5ad"
    adata.write_h5ad(out)
    return adata, out, note


def load_data(ctx: WorkContext, sink: EventSink, path: str) -> dict:
    sid = "load_data"
    sink.emit(StepStarted(step_id=sid, title="Load data",
                          detail=f"scanning {path}"))
    p = Path(path).expanduser()
    if not p.exists():
        sink.emit(StepFinished(step_id=sid, status="error",
                               summary=f"path not found: {path}"))
        raise LoaderError(
            f"Path not found: {path}. Give a folder of .h5ad sections, a single "
            f".h5ad file, or a Space Ranger output directory.")

    discovered = _discover(p)
    if not discovered:
        sink.emit(StepFinished(step_id=sid, status="error",
                               summary=f"no readable sections found at {path}"))
        raise LoaderError(
            f"No sections found at {path}. Sutura looks for: .h5ad files, a "
            f"Space Ranger output dir (filtered_feature_bc_matrix + spatial/), "
            f"or a Xenium bundle. None were found here.")

    loaded, warnings = [], []
    total = len(discovered)
    for i, (name, fmt, arg) in enumerate(discovered):
        sink.emit(StepProgress(step_id=sid, pct=int(100 * i / total),
                               message=f"reading {name} ({fmt})"))
        try:
            adata, h5ad_path, note = _load_one(fmt, arg, ctx.workdir, name)
        except LoaderError as e:
            warnings.append(str(e))
            sink.emit(Note(text=str(e), level="warn"))
            continue
        except Exception as e:                      # never surface a raw traceback
            msg = f"{name}: unexpected error while loading ({type(e).__name__}: {e})"
            warnings.append(msg)
            sink.emit(Note(text=msg, level="warn"))
            continue
        if note:
            sink.emit(Note(text=note, level="info"))
        sec = ctx.add_section(Section(
            id=ctx.new_id(), name=name, fmt=fmt, h5ad_path=Path(h5ad_path),
            source=str(arg), adata=adata,
            n_spots=int(adata.n_obs), n_genes=int(adata.n_vars),
            has_spatial="spatial" in adata.obsm, has_layers=_has_layers(adata)))
        loaded.append(sec.meta())

    if not loaded:
        sink.emit(StepFinished(step_id=sid, status="error",
                               summary="every candidate section failed to load"))
        raise LoaderError(
            "No sections could be loaded:\n  - " + "\n  - ".join(warnings))

    # compact summary: don't dump 35 section names inline
    spots = [s["n_spots"] for s in loaded]
    if len(loaded) <= 4:
        detail = ", ".join(f"{s['name']} ({s['n_spots']:,})" for s in loaded)
    else:
        detail = f"{min(spots):,}–{max(spots):,} spots each"
    sink.emit(StepFinished(
        step_id=sid, status="warn" if warnings else "ok",
        summary=f"loaded {len(loaded)} section(s) · {detail}"))
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

    # gene-panel preflight: alignment needs shared genes
    common = len(set(map(str, ref.adata.var_names)) & set(map(str, mov.adata.var_names)))
    if common == 0:
        raise LoaderError(
            f"{ref.name} and {mov.name} share 0 genes, so they cannot be aligned "
            f"(different gene panels / naming). Ensure both sections use the same "
            f"gene identifiers.")

    what = f"alignment of {ref.name} -> {mov.name}"
    try:
        if force_method:
            result = _call_with_timeout(
                lambda: _forced_align(ctx, ref, mov, force_method, out_dir),
                _ALIGN_TIMEOUT, what)
            sink.emit(StepProgress(step_id=sid, pct=95,
                                   message="writing aligned output"))
        else:
            pipeline = engine.load_pipeline()
            extra_paths = [str(ctx.resolve(e).h5ad_path) for e in (extras or [])
                           if ctx.resolve(e)]
            files = [str(ref.h5ad_path), str(mov.h5ad_path), *extra_paths]

            def _progress(stage, pct):
                sink.emit(StepProgress(step_id=sid, pct=int(pct),
                                       message=_STAGE_MSG.get(stage, stage)))
            result = _call_with_timeout(
                lambda: pipeline.run_alignment(files, out_dir, progress=_progress),
                _ALIGN_TIMEOUT, what)
    except (LoaderError, AlignError):
        raise
    except Exception as e:                          # translate engine failures
        raise AlignError(
            f"alignment of {ref.name} -> {mov.name} failed "
            f"({type(e).__name__}: {e}).") from e

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
    # very low footprint coverage often means the sections don't overlap well,
    # i.e. they may not be adjacent serial slices
    adjacency = None
    if coverage < 0.4:
        adjacency = ("low footprint overlap - these sections may not be adjacent "
                     "serial slices (or are badly misaligned)")
        sink.emit(Note(text=f"{ref.name} -> {mov.name}: {adjacency}", level="warn"))
    sink.emit(StepFinished(
        step_id=sid, status="ok" if good else "warn",
        summary=f"{verdict}: {basis}"))
    out = {"verdict": verdict, "neighbor_consistency": round(consistency, 3),
           "footprint_coverage": round(coverage, 3), "basis": basis}
    if adjacency:
        out["adjacency_warning"] = adjacency
    return out
