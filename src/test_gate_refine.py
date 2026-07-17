"""Unit tests for gate_refine - the packaged, validated OT-alignment refinement.
Run:  python -m pytest src/test_gate_refine.py -v   (from repo root)
Most tests are self-contained (synthetic, no data). Two reproduction tests skip if the
PASTE2 cache / DLPFC data is absent."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
import gate_refine as gr  # noqa: E402

ROOT = SRC.parent
CACHE = ROOT / "research" / "results" / "paste2_cache"


def _median_err(pred, gt, pitch):
    return float(np.median(np.linalg.norm(np.asarray(pred) - gt, axis=1)) / pitch)


# --------------------------------------------------------------------------- #
# synthetic torn-tissue fixture (no external data)
# --------------------------------------------------------------------------- #
def _synthetic_torn(seed=0, n_side=40, tear_offset=6.0, noise=1.2):
    """Grid reference tissue; moving = reference with one half rigidly torn away + noise on
    the OT 'base' estimate. Returns (base_coords, moving_coords, gt, pitch)."""
    rng = np.random.default_rng(seed)
    xs, ys = np.meshgrid(np.arange(n_side), np.arange(n_side))
    ref = np.stack([xs.ravel(), ys.ravel()], 1).astype(float)   # reference-frame truth
    pitch = 1.0
    # moving coords: identity for the left half, translate the right half (a tear)
    moving = ref.copy()
    torn = ref[:, 0] > n_side / 2
    moving[torn, 0] += tear_offset
    moving[torn, 1] += tear_offset * 0.3
    # OT 'base' = the true reference position + isotropic noise (a good-but-noisy correspondence)
    base = ref + rng.normal(0, noise, ref.shape)
    return base, moving, ref, pitch


def test_never_regress_on_bad_base():
    """A garbage base (no rigid structure) must fall back: gated error ~ base error."""
    rng = np.random.default_rng(1)
    moving = rng.normal(0, 10, (500, 2))
    base = rng.normal(0, 50, (500, 2))          # unrelated to moving -> high fit residual
    gt = rng.normal(0, 50, (500, 2))
    for order in ("rigid", "affine", "quadratic"):
        out = gr.gate_refine(base, moving, order=order, pitch=1.0)
        assert _median_err(out, gt, 1.0) <= _median_err(base, gt, 1.0) * 1.03, \
            f"{order} regressed on a bad base"


def test_improves_on_torn_tissue():
    """On a good-but-noisy base over torn tissue, the gate must reduce error."""
    base, moving, gt, pitch = _synthetic_torn()
    be = _median_err(base, gt, pitch)
    for order in ("rigid", "affine"):
        out = gr.gate_refine(base, moving, order=order, pitch=pitch)
        assert _median_err(out, gt, pitch) < be, f"{order} did not improve on torn tissue"


def test_gt_free_and_feature_free_by_signature():
    """The API cannot take ground truth or features - structural guarantee."""
    import inspect
    params = set(inspect.signature(gr.gate_refine).parameters)
    for banned in ("gt", "target", "have", "features", "labels_true", "Z", "expression"):
        assert banned not in params


def test_deterministic():
    base, moving, _, pitch = _synthetic_torn()
    a = gr.gate_refine(base, moving, order="affine", pitch=pitch, seed=0)
    b = gr.gate_refine(base, moving, order="affine", pitch=pitch, seed=0)
    assert np.allclose(a, b)


def test_shapes_and_validation():
    base, moving, _, pitch = _synthetic_torn()
    out = gr.gate_refine(base, moving, pitch=pitch)
    assert out.shape == base.shape
    with pytest.raises(ValueError):
        gr.gate_refine(base[:, :1], moving, pitch=pitch)        # wrong shape
    with pytest.raises(ValueError):
        gr.gate_refine(base[:10], moving, pitch=pitch)          # mismatched N


def test_tiny_input_returns_base():
    base = np.random.default_rng(0).normal(0, 1, (8, 2))
    moving = np.random.default_rng(1).normal(0, 1, (8, 2))
    out = gr.gate_refine(base, moving, pitch=1.0)
    assert np.allclose(out, base)          # too few spots -> no change (safe)


def test_no_tear_single_piece_still_safe():
    """Untorn tissue = one piece; a rigid/affine fit to a good base should not hurt."""
    rng = np.random.default_rng(2)
    ref = rng.normal(0, 10, (600, 2))
    base = ref + rng.normal(0, 0.8, ref.shape)
    moving = ref.copy()
    out = gr.gate_refine(base, moving, order="affine", pitch=1.0)
    assert _median_err(out, ref, 1.0) <= _median_err(base, ref, 1.0) + 1e-6


def test_return_info():
    base, moving, _, pitch = _synthetic_torn()
    out, info = gr.gate_refine(base, moving, order="affine", pitch=pitch, return_info=True)
    assert "labels" in info and "gated_fraction" in info
    assert 0.0 <= info["gated_fraction"] <= 1.0
    assert len(np.unique(info["labels"])) >= 2          # the tear should split into >=2 pieces


# --------------------------------------------------------------------------- #
# reproduction against the validated PASTE2 cache (skips if absent)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not (CACHE / "Br8100_s0_seed0.npz").exists(),
                    reason="PASTE2 cache absent")
def test_reproduces_validated_numbers():
    import anndata as ad
    from scipy.spatial import cKDTree
    from train_cross import array_bridge
    from warp_slice import apply_warp
    base = np.load(CACHE / "Br8100_s0_seed0.npz")["base"]
    A = ad.read_h5ad(ROOT / "data" / "DLPFC_151673.h5ad")
    B = ad.read_h5ad(ROOT / "data" / "DLPFC_151674.h5ad")
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B.obsm["spatial"] = np.asarray(B.obsm["spatial"], float)
    coords = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    gt, have = array_bridge(A, B)
    w, _ = apply_warp(B, 0.0, seed=0, tear=True)
    mov = np.asarray(w.obsm["spatial"], np.float32)

    def err(p):
        return float(np.median(np.linalg.norm(p[have] - gt[have], axis=1)) / pitch)
    assert abs(err(base) - 2.9866) < 0.01                 # PASTE2 base reproduces
    assert abs(err(gr.gate_refine(base, mov, order="rigid", pitch=pitch)) - 1.4611) < 0.01
    assert err(gr.gate_refine(base, mov, order="affine", pitch=pitch)) < err(base)
