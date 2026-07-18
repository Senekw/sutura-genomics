"""
Comprehensive robustness / adversarial-input test suite for the gate_refine alignment pipeline
and its hardened guard layer (research/src/robustness_guard.py).

Each test corresponds to a failure mode catalogued in research/FINDINGS_robustness.md. The suite
proves that:
  * every malformed input raises a clear RobustnessError (never a raw scipy/numpy stack trace),
  * no input ever yields a silently-wrong or NaN-leaking result,
  * good input still refines correctly and is bit-for-bit deterministic,
  * numerical behaviour is stable across scale, aspect ratio, and degenerate geometry, and
  * the resource-limit guard degrades gracefully instead of running unbounded.

Run:  python -m pytest research/tests/test_robustness.py -v
"""
from __future__ import annotations

import types
import warnings

import numpy as np
import pytest

import robustness_guard as rg
import gate_refine as gr
from conftest import median_err


# =========================================================================== #
# S1. Shape / dtype / structural validation
# =========================================================================== #
class TestShapeValidation:
    def test_3d_coords_rejected(self, torn_grid):
        with pytest.raises(rg.RobustnessError, match=r"\(N, 2\)"):
            rg.safe_gate_refine(np.random.rand(50, 3), np.random.rand(50, 3), pitch=1.0)

    def test_1d_coords_rejected(self):
        with pytest.raises(rg.RobustnessError, match=r"\(N, 2\)"):
            rg.safe_gate_refine(np.random.rand(50), np.random.rand(50), pitch=1.0)

    def test_mismatched_n_rejected(self):
        with pytest.raises(rg.RobustnessError, match="same shape"):
            rg.safe_gate_refine(np.zeros((50, 2)), np.zeros((40, 2)), pitch=1.0)

    def test_list_input_coerced(self):
        out = rg.safe_gate_refine([[0, 0], [1, 1]] * 30, [[0, 0], [1, 1]] * 30, pitch=1.0)
        assert out.shape == (60, 2)

    def test_int_input_coerced_to_float(self):
        out = rg.safe_gate_refine(np.zeros((50, 2), int), np.ones((50, 2), int), pitch=1.0)
        assert out.dtype == np.float64

    def test_non_numeric_input_rejected(self):
        with pytest.raises(rg.RobustnessError):
            rg.safe_gate_refine(np.array([["a", "b"]] * 30), np.zeros((30, 2)), pitch=1.0)

    def test_bad_order_lists_valid_options(self, torn_grid):
        b, m, _, p = torn_grid()
        with pytest.raises(rg.RobustnessError, match="rigid.*affine.*quadratic"):
            rg.safe_gate_refine(b, m, order="cubic", pitch=p)


# =========================================================================== #
# S2. Empty / tiny inputs
# =========================================================================== #
class TestEmptyAndTiny:
    def test_empty_returns_empty(self):
        out = rg.safe_gate_refine(np.zeros((0, 2)), np.zeros((0, 2)), pitch=1.0)
        assert out.shape == (0, 2)

    def test_empty_with_info(self):
        out, info = rg.safe_gate_refine(np.zeros((0, 2)), np.zeros((0, 2)),
                                        pitch=1.0, return_info=True)
        assert out.shape == (0, 2) and info["gated_fraction"] == 0.0

    def test_single_spot_returns_base(self):
        base = np.array([[3.0, 4.0]])
        out = rg.safe_gate_refine(base, np.array([[0.0, 0.0]]), pitch=1.0)
        assert np.allclose(out, base)

    def test_tiny_input_unchanged(self):
        base = np.random.default_rng(0).normal(0, 1, (8, 2))
        moving = np.random.default_rng(1).normal(0, 1, (8, 2))
        out = rg.safe_gate_refine(base, moving, pitch=1.0)
        assert np.allclose(out, base)   # too few spots to fit -> safe fallback

    def test_pitch_none_single_spot_rejected(self):
        with pytest.raises(rg.RobustnessError, match="fewer than 2 spots"):
            rg.safe_gate_refine(np.zeros((1, 2)), np.zeros((1, 2)))


# =========================================================================== #
# S3. Non-finite coordinates (NaN / inf)
# =========================================================================== #
class TestNonFinite:
    def test_nan_in_moving_raises_clear(self, torn_grid):
        b, m, _, p = torn_grid()
        m[::10] = np.nan
        with pytest.raises(rg.RobustnessError, match="NaN/inf"):
            rg.safe_gate_refine(b, m, pitch=p)

    def test_inf_in_moving_raises_clear(self, torn_grid):
        b, m, _, p = torn_grid()
        m[::10] = np.inf
        with pytest.raises(rg.RobustnessError, match="NaN/inf"):
            rg.safe_gate_refine(b, m, pitch=p)

    def test_moving_nan_drop_mode(self, torn_grid):
        b, m, _, p = torn_grid()
        bad = np.zeros(len(m), bool); bad[::10] = True
        m[bad] = np.nan
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            out = rg.safe_gate_refine(b, m, pitch=p, on_nonfinite_moving="drop")
        assert out.shape == b.shape
        assert np.isnan(out[bad]).all()               # dropped rows are NaN
        assert np.isfinite(out[~bad]).all()           # everything else finite

    def test_partial_nan_base_handled(self, torn_grid):
        """NaN rows in the OT base are legitimate (zero transported mass) and must be filled."""
        b, m, ref, p = torn_grid()
        b[::7] = np.nan
        out = rg.safe_gate_refine(b, m, order="affine", pitch=p)
        assert np.isfinite(out).all(), "guard leaked NaN from a partially-NaN base"

    def test_all_nan_base_rejected(self, torn_grid):
        b, m, _, p = torn_grid()
        b[:] = np.nan
        with pytest.raises(rg.RobustnessError, match="entirely non-finite"):
            rg.safe_gate_refine(b, m, pitch=p)

    def test_inf_in_base_handled(self, torn_grid):
        b, m, _, p = torn_grid()
        b[::10] = np.inf
        out = rg.safe_gate_refine(b, m, order="affine", pitch=p)
        assert np.isfinite(out).all()


# =========================================================================== #
# S4. Pitch / degenerate geometry (the silent divide-by-zero class)
# =========================================================================== #
class TestPitchAndDegenerate:
    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_bad_pitch_rejected(self, torn_grid, bad):
        b, m, _, _ = torn_grid()
        with pytest.raises(rg.RobustnessError, match="positive finite"):
            rg.safe_gate_refine(b, m, pitch=bad)

    def test_all_identical_coords_rejected(self):
        with pytest.raises(rg.RobustnessError, match="degenerate|positive finite"):
            rg.safe_gate_refine(np.zeros((100, 2)), np.zeros((100, 2)))

    def test_duplicate_moving_pitch_none_rejected(self, torn_grid):
        b, m, _, _ = torn_grid()
        with pytest.raises(rg.RobustnessError):
            rg.safe_gate_refine(b, np.zeros_like(m))       # pitch inferred -> 0 -> reject

    def test_negligible_pitch_relative_to_span_rejected(self, torn_grid):
        b, m, _, _ = torn_grid()
        with pytest.raises(rg.RobustnessError, match="negligible|positive finite"):
            rg.safe_gate_refine(b, m, pitch=1e-15)

    def test_collinear_moving_no_crash(self):
        line = np.stack([np.arange(200.0), np.zeros(200)], 1)
        out = rg.safe_gate_refine(line + 0.1, line, pitch=1.0)
        assert np.isfinite(out).all()

    def test_single_cluster_no_crash(self):
        rng = np.random.default_rng(0)
        pts = rng.random((200, 2))
        out = rg.safe_gate_refine(pts + rng.normal(0, 0.01, pts.shape), pts, pitch=0.05)
        assert np.isfinite(out).all()


# =========================================================================== #
# S5. Weights validation
# =========================================================================== #
class TestWeights:
    def test_wrong_length_rejected(self, torn_grid):
        b, m, _, p = torn_grid()
        with pytest.raises(rg.RobustnessError, match="length"):
            rg.safe_gate_refine(b, m, pitch=p, weights=np.ones(5))

    def test_nan_weights_rejected(self, torn_grid):
        b, m, _, p = torn_grid()
        with pytest.raises(rg.RobustnessError, match="finite"):
            rg.safe_gate_refine(b, m, pitch=p, weights=np.full(len(b), np.nan))

    def test_negative_weights_rejected(self, torn_grid):
        b, m, _, p = torn_grid()
        with pytest.raises(rg.RobustnessError, match=">= 0"):
            rg.safe_gate_refine(b, m, pitch=p, weights=-np.ones(len(b)))

    def test_all_zero_weights_rejected(self, torn_grid):
        b, m, _, p = torn_grid()
        with pytest.raises(rg.RobustnessError, match="sum to 0"):
            rg.safe_gate_refine(b, m, pitch=p, weights=np.zeros(len(b)))

    def test_valid_weights_work(self, torn_grid):
        b, m, _, p = torn_grid()
        w = np.ones(len(b)); w[::2] = 0.5
        out = rg.safe_gate_refine(b, m, pitch=p, weights=w)
        assert np.isfinite(out).all()


# =========================================================================== #
# S6. Numerical stability across scale / aspect ratio
# =========================================================================== #
class TestNumericalStability:
    @pytest.mark.parametrize("scale", [1e-9, 1e-6, 1e-3, 1e3, 1e6, 1e9, 1e12])
    def test_scale_invariance_no_nan(self, torn_grid, scale):
        b, m, ref, _ = torn_grid()
        out = rg.safe_gate_refine(b * scale, m * scale, order="affine", pitch=scale)
        assert np.isfinite(out).all()

    def test_scale_covariance_result_matches(self, torn_grid):
        """Refinement should be equivariant to global rescaling: refine(s*x)/s == refine(x)."""
        b, m, ref, p = torn_grid()
        out1 = rg.safe_gate_refine(b, m, order="affine", pitch=p, seed=0)
        s = 1e6
        out2 = rg.safe_gate_refine(b * s, m * s, order="affine", pitch=p * s, seed=0) / s
        # improvement over base should transfer; coords match to float precision
        assert np.allclose(out1, out2, rtol=1e-6, atol=1e-6 * (np.abs(out1).max() + 1))

    def test_extreme_aspect_ratio_no_nan(self, torn_grid):
        b, m, _, p = torn_grid()
        m2 = m.copy(); m2[:, 1] *= 1e6
        out = rg.safe_gate_refine(b, m2, pitch=p)
        assert np.isfinite(out).all()

    def test_no_nan_propagation_extreme_noise(self, torn_grid):
        b, m, _, p = torn_grid(noise=1e8)
        out = rg.safe_gate_refine(b, m, order="quadratic", pitch=p)
        assert np.isfinite(out).all()

    @pytest.mark.parametrize("scale", [1.0, 1e3, 1e6, 1e9, 1e12])
    @pytest.mark.parametrize("order", ["rigid", "affine", "quadratic"])
    def test_never_regress_at_any_scale(self, torn_grid, order, scale):
        """The 'never regress' property must hold at ANY coordinate magnitude. The raw
        un-normalised quadratic fit BLOWS UP past ~1e6 (err 0.13 -> 2.2, worse than base);
        the guard's pitch-normalisation keeps it stable. This is the regression test for that fix."""
        b, m, ref, _ = torn_grid()
        base_err = median_err(b, ref, 1.0)
        out = rg.safe_gate_refine(b * scale, m * scale, order=order, pitch=scale, seed=0) / scale
        assert median_err(out, ref, 1.0) <= base_err * 1.03, \
            f"{order} regressed at scale {scale:g}"

    def test_scale_stability_result_constant(self, torn_grid):
        """Error is (near-)constant across 12 orders of magnitude of coordinate scale."""
        b, m, ref, _ = torn_grid()
        errs = []
        for scale in (1.0, 1e6, 1e12):
            out = rg.safe_gate_refine(b * scale, m * scale, order="quadratic",
                                      pitch=scale, seed=0) / scale
            errs.append(median_err(out, ref, 1.0))
        assert max(errs) - min(errs) < 1e-4


# =========================================================================== #
# S7. Determinism / reproducibility
# =========================================================================== #
class TestDeterminism:
    def test_bit_identical_repeated(self, torn_grid):
        b, m, _, p = torn_grid()
        outs = [rg.safe_gate_refine(b, m, order="affine", pitch=p, seed=0) for _ in range(5)]
        for o in outs[1:]:
            assert np.array_equal(outs[0], o)

    def test_identical_values_identical_output_any_dtype(self, torn_grid):
        """Same float64 VALUES via different dtype containers give identical output (the guard
        canonicalises to float64, so an int-valued or float64 container yields the same result)."""
        b, m, _, p = torn_grid()
        bi = np.round(b).astype(np.int64)             # integer-valued coordinates
        o_f = rg.safe_gate_refine(bi.astype(np.float64), m, order="affine", pitch=p)
        o_i = rg.safe_gate_refine(bi, m, order="affine", pitch=p)   # int container, same values
        assert np.array_equal(o_f, o_i)

    def test_float32_input_only_small_precision_difference(self, torn_grid):
        """Documented caveat: lower-precision INPUT changes results only at ~1e-5 pitch, never
        catastrophically (values already differ before the guard sees them)."""
        b, m, _, p = torn_grid()
        o64 = rg.safe_gate_refine(b, m, order="affine", pitch=p)
        o32 = rg.safe_gate_refine(b.astype(np.float32), m, order="affine", pitch=p)
        assert np.abs(o64 - o32).max() < 1e-3

    def test_memory_layout_invariant(self, torn_grid):
        b, m, _, p = torn_grid()
        oc = rg.safe_gate_refine(np.ascontiguousarray(b), m, order="affine", pitch=p)
        of = rg.safe_gate_refine(np.asfortranarray(b), m, order="affine", pitch=p)
        assert np.array_equal(oc, of)

    def test_different_seed_cv_stable(self, torn_grid):
        """CV split seed changes the residual estimate only marginally (not wildly)."""
        b, m, ref, p = torn_grid()
        errs = [median_err(rg.safe_gate_refine(b, m, order="affine", pitch=p, seed=s), ref, p)
                for s in range(4)]
        assert np.std(errs) < 0.1 * (np.mean(errs) + 1e-9)


# =========================================================================== #
# S8. Correctness preserved (the guard must not change good results)
# =========================================================================== #
class TestCorrectnessPreserved:
    def test_matches_raw_gate_on_clean_input(self, torn_grid):
        b, m, _, p = torn_grid()
        raw = gr.gate_refine(b, m, order="affine", pitch=p, seed=0)
        safe = rg.safe_gate_refine(b, m, order="affine", pitch=p, seed=0)
        assert np.allclose(raw, safe)

    def test_improves_on_torn_tissue(self, torn_grid):
        b, m, ref, p = torn_grid()
        be = median_err(b, ref, p)
        for order in ("rigid", "affine"):
            out = rg.safe_gate_refine(b, m, order=order, pitch=p)
            assert median_err(out, ref, p) < be

    def test_never_regress_on_garbage_base(self):
        rng = np.random.default_rng(1)
        moving = rng.normal(0, 10, (500, 2))
        base = rng.normal(0, 50, (500, 2))
        gt = rng.normal(0, 50, (500, 2))
        for order in rg.VALID_ORDERS:
            out = rg.safe_gate_refine(base, moving, order=order, pitch=1.0)
            assert median_err(out, gt) <= median_err(base, gt) * 1.03

    def test_return_info_shape(self, torn_grid):
        b, m, _, p = torn_grid()
        out, info = rg.safe_gate_refine(b, m, order="affine", pitch=p, return_info=True)
        assert "labels" in info and 0.0 <= info["gated_fraction"] <= 1.0
        assert len(np.unique(info["labels"])) >= 2


# =========================================================================== #
# S9. Resource limits / graceful degradation
# =========================================================================== #
class TestResourceLimits:
    def test_oversize_errors_by_default(self, torn_grid):
        b, m, _, p = torn_grid(n_side=40)          # 1600 spots
        with pytest.raises(rg.RobustnessError, match="exceeds max_spots"):
            rg.safe_gate_refine(b, m, pitch=p, max_spots=100)

    def test_oversize_subsample_mode(self, torn_grid):
        b, m, _, p = torn_grid(n_side=40)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            out = rg.safe_gate_refine(b, m, pitch=p, max_spots=200, on_oversize="subsample")
        assert out.shape == b.shape
        assert np.isfinite(out).sum(0).min() > 0    # some spots placed
        assert np.isnan(out).any()                  # non-selected returned as NaN

    def test_subsample_deterministic(self, torn_grid):
        b, m, _, p = torn_grid(n_side=40)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            o1 = rg.safe_gate_refine(b, m, pitch=p, max_spots=200, on_oversize="subsample",
                                     subsample_seed=3)
            o2 = rg.safe_gate_refine(b, m, pitch=p, max_spots=200, on_oversize="subsample",
                                     subsample_seed=3)
        assert np.array_equal(np.isnan(o1), np.isnan(o2))
        assert np.allclose(o1[~np.isnan(o1).any(1)], o2[~np.isnan(o2).any(1)])

    def test_warn_threshold_emits(self, torn_grid):
        b, m, _, p = torn_grid(n_side=40)
        with pytest.warns(RuntimeWarning, match="may take a while"):
            rg.safe_gate_refine(b, m, pitch=p, warn_spots=100, max_spots=10_000)


# =========================================================================== #
# S10. Transport-plan / scoring guards
# =========================================================================== #
class TestScoringGuards:
    def test_plan_nan_rejected(self):
        with pytest.raises(rg.RobustnessError, match="NaN/inf"):
            rg.validate_transport_plan(np.full((5, 6), np.nan))

    def test_plan_negative_rejected(self):
        with pytest.raises(rg.RobustnessError, match="negative"):
            rg.validate_transport_plan(-np.ones((5, 6)))

    def test_plan_empty_rejected(self):
        with pytest.raises(rg.RobustnessError, match="empty"):
            rg.validate_transport_plan(np.zeros((0, 0)))

    def test_plan_shape_mismatch_rejected(self):
        with pytest.raises(rg.RobustnessError, match="rows"):
            rg.validate_transport_plan(np.ones((5, 6)), n_a=4)

    def test_barycentric_mismatch_rejected(self):
        with pytest.raises(rg.RobustnessError, match="rows"):
            rg.safe_barycentric_projection(np.ones((50, 60)), np.random.rand(40, 2))

    def test_barycentric_all_zero_warns(self):
        with pytest.warns(RuntimeWarning, match="no mass"):
            pred, mass = rg.safe_barycentric_projection(np.zeros((50, 60)), np.random.rand(50, 2))
        assert np.isnan(pred).all() and (mass == 0).all()

    def test_barycentric_valid_matches_raw(self):
        import scoring as sc
        rng = np.random.default_rng(0)
        pi = rng.random((30, 40))
        coords = rng.random((30, 2))
        p1, m1 = rg.safe_barycentric_projection(pi, coords)
        p2, m2 = sc.barycentric_projection(pi, coords)
        assert np.allclose(p1, p2) and np.allclose(m1, m2)


# =========================================================================== #
# S11. Section-level (AnnData) validation
# =========================================================================== #
def _stub_section(n=100, spatial=True, key="spatial", genes=tuple(f"g{i}" for i in range(20)),
                  X=None, obs_cols=("array_row", "array_col")):
    """A lightweight duck-typed AnnData stand-in exercising the getattr paths in validate_section."""
    ns = types.SimpleNamespace()
    ns.n_obs = n
    coords = np.random.default_rng(0).random((n, 2)) * 100
    ns.obsm = {key: coords} if spatial else {}
    ns.var_names = list(genes)
    ns.X = (np.random.default_rng(1).random((n, len(genes))) if X is None else X)
    ns.obs = types.SimpleNamespace(columns=list(obs_cols))
    return ns


class TestSectionValidation:
    def test_empty_section_rejected(self):
        with pytest.raises(rg.RobustnessError, match="empty"):
            rg.validate_section(_stub_section(n=0))

    def test_single_spot_section_rejected(self):
        with pytest.raises(rg.RobustnessError, match="at least"):
            rg.validate_section(_stub_section(n=1))

    def test_missing_spatial_key_lists_available(self):
        with pytest.raises(rg.RobustnessError, match="obsm"):
            rg.validate_section(_stub_section(spatial=False))

    def test_wrong_spatial_key(self):
        s = _stub_section(key="X_umap")
        with pytest.raises(rg.RobustnessError, match="Available obsm keys"):
            rg.validate_section(s, spatial_key="spatial")

    def test_nan_in_expression_rejected(self):
        X = np.random.random((100, 3)); X[0, 0] = np.nan
        with pytest.raises(rg.RobustnessError, match="expression"):
            rg.validate_section(_stub_section(X=X))

    def test_all_zero_expression_warns(self):
        with pytest.warns(RuntimeWarning, match="entirely zero"):
            rg.validate_section(_stub_section(X=np.zeros((100, 3))))

    def test_valid_section_passes(self):
        rg.validate_section(_stub_section())    # no raise

    def test_disjoint_panels_rejected(self):
        A = _stub_section(genes=("a", "b", "c"))
        B = _stub_section(genes=("x", "y", "z"))
        with pytest.raises(rg.RobustnessError, match="disjoint|NO genes"):
            rg.validate_section_pair(A, B, check_expression=False)

    def test_tiny_panel_overlap_warns(self):
        A = _stub_section(genes=tuple(f"g{i}" for i in range(50)))
        B = _stub_section(genes=("g0", "g1") + tuple(f"h{i}" for i in range(50)))
        with pytest.warns(RuntimeWarning, match="share only"):
            rg.validate_section_pair(A, B, check_expression=False)

    def test_size_imbalance_warns(self):
        A = _stub_section(n=2000)          # default 20-gene panel -> no panel warning
        B = _stub_section(n=50)
        with pytest.warns(RuntimeWarning, match="imbalance"):
            rg.validate_section_pair(A, B, check_expression=False)

    def test_missing_visium_bridge_columns_rejected(self):
        A = _stub_section(obs_cols=())
        B = _stub_section()
        with pytest.raises(rg.RobustnessError, match="array_row|array_col"):
            rg.validate_section_pair(A, B, check_expression=False, require_visium_bridge=True)


# =========================================================================== #
# S12. h5ad reading guards
# =========================================================================== #
class TestH5adReading:
    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(rg.RobustnessError, match="not found"):
            rg.safe_read_h5ad(tmp_path / "does_not_exist.h5ad")

    def test_empty_file_rejected(self, tmp_path):
        p = tmp_path / "empty.h5ad"; p.write_bytes(b"")
        with pytest.raises(rg.RobustnessError, match="empty"):
            rg.safe_read_h5ad(p)

    def test_corrupted_file_rejected(self, tmp_path):
        p = tmp_path / "corrupt.h5ad"
        p.write_bytes(b"this is not a valid HDF5 file, it is garbage bytes" * 100)
        with pytest.raises(rg.RobustnessError, match="corrupt|failed to read"):
            rg.safe_read_h5ad(p)


# =========================================================================== #
# S13. Fuzz: no input in a broad random sweep produces an uncaught exception
#      or a silent NaN leak. Everything is either a clean result or a RobustnessError.
# =========================================================================== #
class TestFuzz:
    @pytest.mark.parametrize("seed", range(40))
    def test_random_inputs_never_crash_or_leak(self, seed):
        rng = np.random.default_rng(seed)
        n = int(rng.integers(0, 400))
        scale = 10.0 ** rng.integers(-9, 10)
        base = rng.normal(0, scale, (n, 2))
        moving = rng.normal(0, scale, (n, 2))
        # randomly corrupt
        if n and rng.random() < 0.4:
            k = rng.integers(0, max(1, n // 3))
            base[rng.integers(0, n, k)] = rng.choice([np.nan, np.inf, -np.inf])
        if n and rng.random() < 0.3:
            moving[rng.integers(0, n)] = np.nan
        order = rng.choice(rg.VALID_ORDERS)
        pitch = rng.choice([None, 1.0, scale, 0.0, -1.0])
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out = rg.safe_gate_refine(base, moving, order=str(order), pitch=pitch,
                                          on_nonfinite_moving="drop")
        except rg.RobustnessError:
            return                                  # acceptable: clean rejection
        # if it returned, output must not leak NaN where base+moving were finite
        base_ok = np.isfinite(base).all(1)
        mov_ok = np.isfinite(moving).all(1)
        good = base_ok & mov_ok
        assert np.isfinite(out[good]).all(), f"NaN leak, seed={seed}"
