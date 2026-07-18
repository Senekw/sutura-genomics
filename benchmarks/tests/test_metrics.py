"""Metrics tests: parity with the canonical src/ implementations + correctness."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from sutura_bench import metrics


def test_registration_error_basic():
    pred = np.array([[0.0, 0.0], [3.0, 4.0], [0.0, 0.0]])
    gt = np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
    st = metrics.registration_error(pred, gt, pitch=2.0)
    # distances: 0, 5, 0 -> median 0, mean 5/3, max 5
    assert st["max_px"] == 5.0
    assert st["median_px"] == 0.0
    assert st["mean_px"] == pytest.approx(5.0 / 3)
    assert st["median_pitch"] == 0.0
    assert st["max_pitch"] == 2.5
    assert st["n"] == 3


def test_registration_error_mask_and_nan():
    pred = np.array([[0.0, 0.0], [10.0, 0.0], [np.nan, 0.0]])
    gt = np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
    mask = np.array([True, False, True])
    st = metrics.registration_error(pred, gt, mask=mask)
    # spot 1 masked out, spot 2 is NaN -> only spot 0 scored
    assert st["n"] == 1
    assert st["median_px"] == 0.0


def test_parity_with_src_scoring():
    """metrics.* must reproduce src/scoring.py bit-for-bit on random input."""
    import scoring
    rng = np.random.default_rng(0)
    pred = rng.normal(size=(200, 2))
    gt = rng.normal(size=(200, 2))
    mask = rng.random(200) > 0.2
    ours = metrics.registration_error_stats(pred, gt, mask=mask)
    theirs = scoring.registration_error_stats(pred, gt, mask=mask)
    for k in ("mean", "median", "p90", "max", "n"):
        assert ours[k] == pytest.approx(theirs[k], rel=1e-12), k

    # projections
    pi = rng.random((50, 40))
    src = rng.normal(size=(50, 2))
    for fn in ("barycentric_projection", "argmax_projection"):
        op, ocm = getattr(metrics, fn)(pi, src)
        tp, tcm = getattr(scoring, fn)(pi, src)
        assert np.allclose(op, tp, equal_nan=True)
        assert np.allclose(ocm, tcm)

    # label transfer + floor
    la = np.array(["L1", "L2", "NA", "L3"] * 10)
    lb = np.array(["L1", "L3", "L2", "NA"] * 10)
    pil = rng.random((40, 40))
    assert metrics.label_transfer_accuracy(pil, la, lb) == scoring.label_transfer_accuracy(pil, la, lb)
    assert metrics.random_mapping_floor(la, lb, n_trials=10, seed=1) == \
        scoring.random_mapping_floor(la, lb, n_trials=10, seed=1)


def test_pitch_parity():
    import warp_slice
    rng = np.random.default_rng(1)
    coords = rng.normal(size=(300, 2)) * 100
    assert metrics.spot_pitch(coords) == pytest.approx(warp_slice.median_spot_pitch(coords))


def test_footprint_and_neighbor():
    rng = np.random.default_rng(2)
    ref = rng.normal(size=(200, 2)) * 50
    # identity pred -> coverage ~1, perfect neighbor consistency
    assert metrics.footprint_coverage(ref, ref) == pytest.approx(1.0, abs=1e-6)
    nc = metrics.neighbor_consistency(ref, ref)
    assert np.median(nc) == pytest.approx(1.0, abs=1e-9)
    # collapse to centroid -> tiny coverage
    collapsed = np.zeros_like(ref)
    assert metrics.footprint_coverage(collapsed, ref) < 0.01


def test_per_layer_error():
    pred = np.array([[0.0, 0.0], [1.0, 0.0], [5.0, 0.0], [0.0, 0.0]])
    gt = np.zeros((4, 2))
    layers = np.array(["A", "A", "B", "NA"])
    out = metrics.per_layer_error(pred, gt, layers, pitch=1.0)
    assert out["A"]["n"] == 2 and out["B"]["n"] == 1
    assert "NA" not in out                      # NA dropped
    assert out["overall"]["n"] == 3
    assert out["B"]["median_pitch"] == 5.0


def test_self_warp_flag():
    assert metrics.is_degenerate_self_warp("self_warp", 0.5) is True
    assert metrics.is_degenerate_self_warp("self_warp", 3.0) is False
    assert metrics.is_degenerate_self_warp("real_serial", 0.1) is False
