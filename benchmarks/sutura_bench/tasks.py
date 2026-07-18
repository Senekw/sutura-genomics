"""
Task construction: turn a DatasetSpec + (severity, seed) into everything a method
needs to produce a prediction, plus the ground truth to score it against.

A ``PairContext`` is built once per dataset (expensive parts - reading the
sections, the shared SVD feature basis, the array-bridge ground truth - are
computed once and reused across every severity, seed, and method). A ``Task`` is
one scoring cell: the warped moving coordinates for a given (severity, seed),
carrying a reference back to its PairContext.

Both ground-truth regimes are handled by the same code path:
  * real_serial - A and B are distinct sections; GT = array_bridge(A, B).
  * self_warp   - B is a copy of A; GT = array_bridge(A, A) = identity. Warping A
                  and asking the method to map back to A's own frame.

This mirrors src/hybrid_validate.py::build_dataset and
src/hybrid_robustness.py::build_self so the benchmark's numbers line up with the
research code exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from . import config
from .datasets import DatasetSpec, resolve_section
from .metrics import spot_pitch, registration_error, per_layer_error


class PairContext:
    """Per-dataset, method-independent state. Built once, reused across cells."""

    def __init__(self, spec: DatasetSpec):
        import anndata as ad
        from train_cross import cross_features, array_bridge

        self.spec = spec
        A = ad.read_h5ad(resolve_section(spec.ref))
        A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
        if spec.regime == "self_warp":
            B = A.copy()
        else:
            B = ad.read_h5ad(resolve_section(spec.mov))
            B.obsm["spatial"] = np.asarray(B.obsm["spatial"], float)

        self.A, self.B = A, B
        self.coords = A.obsm["spatial"]
        self.pitch = spot_pitch(self.coords)
        self.Z_A, self.Z_B = cross_features(A, B, config.PCA_DIM, 0)
        gt, have = array_bridge(A, B)
        self.gt = gt
        self.have = have
        self.layers = self._moving_layers(B)

        # lazily-built torch state (only Sutura-style methods need it)
        self._ga = None
        self._a_norm = None

    @staticmethod
    def _moving_layers(B) -> Optional[np.ndarray]:
        for key in ("layer", "Layer", "layer_guess", "spatialLIBD"):
            if key in B.obs:
                return np.asarray(B.obs[key]).astype(str)
        return None

    @property
    def bridge_coverage(self) -> float:
        return float(self.have.mean())

    def graph_A(self):
        """kNN graph tensors for the reference (cached). Requires torch."""
        if self._ga is None:
            import torch
            from train_cross import graph_tensors
            self._ga = graph_tensors(self.coords, self.Z_A, config.KNN, self.pitch)
            self._a_norm = torch.from_numpy((self.coords / self.pitch).astype(np.float32))
        return self._ga, self._a_norm

    def make_task(self, severity: float, seed: int) -> "Task":
        from warp_slice import apply_warp
        w, _ = apply_warp(self.B, severity, seed=seed, tear=True)
        moving = np.asarray(w.obsm["spatial"], np.float32)
        return Task(self, severity, seed, moving)


@dataclass
class Task:
    ctx: PairContext
    severity: float
    seed: int
    moving_coords: np.ndarray          # (n_mov, 2) warped moving spot coordinates
    base: Optional[np.ndarray] = None  # (n_mov, 2) precomputed base alignment (refiners)

    # convenience pass-throughs -------------------------------------------- #
    @property
    def spec(self) -> DatasetSpec:
        return self.ctx.spec

    @property
    def pitch(self) -> float:
        return self.ctx.pitch

    def score(self, pred: np.ndarray) -> dict:
        """Score a prediction against this task's ground truth. Returns the full
        registration-error distribution (px + pitch) plus regime flags."""
        stats = registration_error(pred, self.ctx.gt, mask=self.ctx.have, pitch=self.pitch)
        stats["regime"] = self.spec.regime
        stats["degenerate"] = self.spec.degenerate
        stats["bridge_coverage"] = round(self.ctx.bridge_coverage, 4)
        return stats

    def score_per_layer(self, pred: np.ndarray) -> dict:
        if self.ctx.layers is None:
            return {}
        return per_layer_error(pred, self.ctx.gt, self.ctx.layers, self.pitch,
                               mask=self.ctx.have)
