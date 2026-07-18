"""Pytest path setup + shared fixtures for the robustness suite.

Puts research/src and src on sys.path so `import robustness_guard`, `import gate_refine`,
and `import scoring` work no matter the working directory pytest is launched from.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_TESTS = Path(__file__).resolve().parent
_RESEARCH = _TESTS.parent
_ROOT = _RESEARCH.parent
for p in (_RESEARCH / "src", _ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture
def torn_grid():
    """Factory for a synthetic torn-tissue case: a square grid reference, moving = reference with
    one half rigidly displaced (a tear), base = reference + isotropic noise (good-but-noisy OT).
    Returns a callable (n_side, tear, noise, seed) -> (base, moving, ref, pitch)."""
    def make(n_side=30, tear=6.0, noise=1.0, seed=0):
        xs, ys = np.meshgrid(np.arange(n_side), np.arange(n_side))
        ref = np.stack([xs.ravel(), ys.ravel()], 1).astype(float)
        moving = ref.copy()
        mask = ref[:, 0] > n_side / 2
        moving[mask, 0] += tear
        moving[mask, 1] += tear * 0.3
        base = ref + np.random.default_rng(seed).normal(0, noise, ref.shape)
        return base, moving, ref, 1.0
    return make


def median_err(pred, gt, pitch=1.0):
    pred = np.asarray(pred, float)
    return float(np.median(np.linalg.norm(pred - np.asarray(gt, float), axis=1)) / pitch)
