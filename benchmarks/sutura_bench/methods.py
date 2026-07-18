"""
The method registry: a unified interface so any alignment method - Sutura,
PASTE2, the gate, or a future method - runs through the same harness and produces
directly comparable numbers.

A method is a ``Method`` with:
  * ``name``          - unique id used in results/leaderboards
  * ``kind``          - "aligner" (produces a base alignment) or "refiner"
                        (post-processes another method's base alignment)
  * ``requires_base`` - True if it consumes ``task.base`` (all refiners, and
                        PASTE2 itself, which *is* the cached base)
  * ``run(task)``     - returns predicted A-frame coords, (n_moving, 2), pixels

The harness computes the PASTE2 base once per (dataset, severity, seed), caches
it, and attaches it as ``task.base`` before invoking any base-consuming method -
so PASTE2 and every gate variant are scored on identical warped slices and one
PASTE2 solve (mirrors src/hybrid_validate.py).

To add a method: write a ``run(task) -> (n,2)`` function and ``register()`` it.
That is the entire extension surface - no harness, metric, or dataset changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from . import config
from .tasks import Task


@dataclass(frozen=True)
class Method:
    name: str
    kind: str                     # "aligner" | "refiner"
    run: Callable[[Task], np.ndarray]
    requires_base: bool = False
    description: str = ""


_REGISTRY: dict[str, Method] = {}


def register(method: Method) -> Method:
    if method.name in _REGISTRY:
        raise ValueError(f"method '{method.name}' already registered")
    _REGISTRY[method.name] = method
    return method


def get(name: str) -> Method:
    if name not in _REGISTRY:
        raise KeyError(f"unknown method '{name}'. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def all_methods() -> list[Method]:
    return list(_REGISTRY.values())


def names() -> list[str]:
    return sorted(_REGISTRY)


# --------------------------------------------------------------------------- #
# PASTE2 base (computed once per cell, shared by paste2 + every refiner)
# --------------------------------------------------------------------------- #
def compute_paste2_base(task: Task) -> np.ndarray:
    """Run real PASTE2 (partial FGW, barycentric) -> A-frame pixel coord per
    moving spot. Slow (minutes); the harness caches the result. Wraps
    src/hybrid_combined.py::paste2_prior on this cell's warped moving section."""
    from warp_slice import apply_warp
    from hybrid_combined import paste2_prior
    ctx = task.ctx
    w, _ = apply_warp(ctx.B, task.severity, seed=task.seed, tear=True)
    return paste2_prior(ctx.A, w, ctx.coords, ctx.pitch).astype(np.float32)


# --------------------------------------------------------------------------- #
# method implementations
# --------------------------------------------------------------------------- #
def _identity(task: Task) -> np.ndarray:
    """No alignment: leave the moving spots where they are. A control that
    measures the perturbation magnitude (how far the warp moved things)."""
    return task.moving_coords.astype(float)


def _paste2(task: Task) -> np.ndarray:
    if task.base is None:
        task.base = compute_paste2_base(task)
    return task.base


def _make_gate(order: str, cv: Optional[bool]) -> Callable[[Task], np.ndarray]:
    def run(task: Task) -> np.ndarray:
        from gate_refine import gate_refine
        if task.base is None:
            task.base = compute_paste2_base(task)
        return gate_refine(task.base, task.moving_coords, order=order,
                           pitch=task.pitch, cv=cv, seed=task.seed)
    return run


# Sutura: checkpoint inference (mirrors src/external_eval.py). Model + args loaded
# once and memoized; features are re-fit per pair via cross_features.
_SUTURA_CACHE: dict = {}


def _load_sutura(ckpt_name: str):
    if ckpt_name in _SUTURA_CACHE:
        return _SUTURA_CACHE[ckpt_name]
    import torch
    from train_cross import ARCACrossNet
    ck = torch.load(config.RESULTS / ckpt_name, map_location="cpu", weights_only=False)
    a = ck["args"]
    m = ARCACrossNet(a["pca_dim"], a["hidden"], a["layers"], a["attn_dim"])
    m.load_state_dict(ck["state_dict"])
    m.eval()
    _SUTURA_CACHE[ckpt_name] = (m, a)
    return m, a


def _make_sutura(ckpt_name: str) -> Callable[[Task], np.ndarray]:
    def run(task: Task) -> np.ndarray:
        import torch
        from train_cross import graph_tensors
        model, a = _load_sutura(ckpt_name)
        ctx = task.ctx
        ga, a_norm = ctx.graph_A()
        gb = graph_tensors(task.moving_coords.astype(float), ctx.Z_B, a["knn"], ctx.pitch)
        with torch.no_grad():
            pred = model(ga, gb, a_norm).numpy() * ctx.pitch
        return pred
    return run


# --------------------------------------------------------------------------- #
# register the standard suite
# --------------------------------------------------------------------------- #
register(Method("identity", "aligner", _identity, requires_base=False,
                description="No alignment (control): the warped moving coords "
                            "themselves. Measures the perturbation magnitude."))

register(Method("paste2", "aligner", _paste2, requires_base=True,
                description="PASTE2 partial-FGW OT baseline (barycentric "
                            "projection). The unsupervised classical reference."))

register(Method("gate_rigid", "refiner", _make_gate("rigid", cv=False),
                requires_base=True,
                description="The gate: per-piece rigid (Umeyama) fit on the "
                            "PASTE2 base, self-gated by fit residual. Reproduces "
                            "the headline 3.73 DLPFC-LODO result."))

register(Method("gate_affine", "refiner", _make_gate("affine", cv=True),
                requires_base=True,
                description="The gate with per-piece affine fits (CV-gated). "
                            "Recommended default; extends the win to high tears."))

register(Method("gate_quad", "refiner", _make_gate("quadratic", cv=True),
                requires_base=True,
                description="The gate with per-piece quadratic fits (CV-gated)."))

register(Method("sutura", "aligner", _make_sutura("arca_cross.pt"),
                requires_base=False,
                description="Sutura (ARCACrossNet) zero-shot from arca_cross.pt "
                            "(trained on Br5292 151507/508). In-distribution on "
                            "Br5292; cross-donor elsewhere."))
