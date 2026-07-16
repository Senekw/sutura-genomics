"""Bridge to the existing Sutura/ARCA alignment engine.

This module does NOT reimplement any alignment logic. It locates the research
repository (which holds src/, backend/pipeline.py, the trained checkpoints and
the frozen shared basis) and lazily imports the existing entry points so the CLI
can call them as tools:

    - backend.pipeline.run_alignment  (the full routed orchestrator)
    - backend.pipeline.qc_file        (input validation)
    - backend.pipeline.align_paste2 / align_sutura  (for forced-method reruns)
    - orchestrator.Projector / distribution_check   (routing decision)
    - agents.neighbor_consistency / footprint_coverage (post-QC primitives)

Repo discovery order:
    1. $SUTURA_REPO if set and valid.
    2. Walk up from this file (works for an in-tree / editable install).
    3. A few common sibling locations.
A repo is "valid" if it contains src/ and results/arca_shared_basis.pt.
"""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

_CKPT_REL = Path("results") / "arca_shared_basis.pt"


def _is_repo(p: Path) -> bool:
    try:
        return (p / "src").is_dir() and (p / "backend" / "pipeline.py").is_file() \
            and (p / _CKPT_REL).is_file()
    except OSError:
        return False


@functools.lru_cache(maxsize=1)
def find_repo_root() -> Path:
    """Locate the research repo that provides the alignment engine."""
    env = os.environ.get("SUTURA_REPO")
    if env:
        p = Path(env).expanduser().resolve()
        if _is_repo(p):
            return p
        raise RuntimeError(
            f"SUTURA_REPO={env!r} does not look like the Sutura repo "
            f"(missing src/ or {_CKPT_REL}).")

    here = Path(__file__).resolve()
    for parent in here.parents:
        if _is_repo(parent):
            return parent

    for cand in (Path.home() / "arca", Path.cwd()):
        if _is_repo(cand):
            return cand.resolve()

    raise RuntimeError(
        "Could not locate the Sutura alignment engine. Set the SUTURA_REPO "
        "environment variable to the repository root (the directory that "
        f"contains src/ and {_CKPT_REL}).")


@functools.lru_cache(maxsize=1)
def _prepare_sys_path() -> Path:
    """Put the repo's src/ and backend/ on sys.path (the code is not packaged)."""
    root = find_repo_root()
    for sub in ("src", "backend"):
        p = str(root / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    return root


def load_pipeline():
    """Import and return the backend.pipeline module (the orchestrator wrapper)."""
    _prepare_sys_path()
    import pipeline  # backend/pipeline.py, on sys.path
    return pipeline


def load_orchestrator():
    _prepare_sys_path()
    import orchestrator
    return orchestrator


def load_agents():
    _prepare_sys_path()
    import agents
    return agents


def engine_versions() -> dict:
    """Metadata about the underlying engine (safe to log / put in the bundle)."""
    root = find_repo_root()
    info = {"repo_root": str(root), "checkpoint": str(root / _CKPT_REL)}
    try:
        import importlib.metadata as m
        for pkg in ("scanpy", "anndata", "torch", "pot"):
            try:
                info[pkg] = m.version(pkg)
            except Exception:
                pass
    except Exception:
        pass
    return info
