"""
robustness_guard - a hardened, fail-loud validation layer in front of the gate_refine
OT-alignment refinement pipeline (src/gate_refine.py) and its scoring/loading helpers
(src/scoring.py, src/train_cross.array_bridge).

WHY THIS EXISTS
---------------
gate_refine is safe-by-construction on WELL-FORMED input, but real users feed real garbage:
NaNs in coordinates, degenerate geometry, duplicate spots, mismatched gene panels, the wrong
obsm key, corrupted h5ad, and slices with wildly different sizes. Left unguarded the pipeline
either (a) crashes with a cryptic stack trace from deep inside scipy / numpy that gives the user
no idea what they did wrong, or (b) - worse - silently returns a NaN-filled or geometrically
wrong answer. This module was written after an adversarial audit (research/FINDINGS_robustness.md)
that catalogued every such failure. Each guard here maps to a documented failure mode.

DESIGN RULES
------------
1. Every rejected input raises `RobustnessError` (a ValueError subclass) with a message that
   names the offending argument, says what is wrong, and says what to do about it. Never a raw
   scipy/numpy stack trace.
2. Never return a silently-wrong result. Non-finite output where the input was finite is a bug,
   so `safe_gate_refine` post-checks its own output and raises if it leaked non-finite values.
3. Numerically stable across scale (nanometres to millimetres), aspect ratio, and degenerate
   geometry - degeneracy is detected and reported, never divided-by.
4. Deterministic: canonicalises dtype to float64 so results are bit-reproducible for a fixed seed
   regardless of the caller's input dtype/memory layout.
5. Pure numpy + scipy for the coordinate path; anndata is imported lazily and only for the
   section-level helpers, so importing this module never requires the scientific stack for
   sections you do not use.

PUBLIC API
----------
    RobustnessError                              - the single exception type raised on bad input
    validate_coords(arr, name, ...)              - coerce/validate an (N,2) coordinate array
    resolve_pitch(moving, pitch)                 - compute or validate a positive finite pitch
    validate_weights(weights, n)                 - validate optional per-spot weights
    safe_gate_refine(base, moving, ...)          - hardened wrapper around gate_refine.gate_refine
    validate_transport_plan(pi, n_a, n_b)        - validate an OT plan before projection/scoring
    safe_barycentric_projection(pi, coords)      - barycentric projection with clear errors + warn
    safe_read_h5ad(path)                         - read an h5ad, translating corruption to a clear error
    validate_section(adata, name, ...)           - validate one spatial section (obsm, expression, size)
    validate_section_pair(A, B, ...)             - validate a moving/reference pair (panels, sizes, GT)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np

# Import the packaged pipeline from src/ (this module lives in research/src/).
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
import gate_refine as _gr  # noqa: E402

__all__ = [
    "RobustnessError",
    "validate_coords",
    "resolve_pitch",
    "validate_weights",
    "safe_gate_refine",
    "validate_transport_plan",
    "safe_barycentric_projection",
    "safe_read_h5ad",
    "validate_section",
    "validate_section_pair",
    "VALID_ORDERS",
    "DEFAULT_WARN_SPOTS",
    "DEFAULT_MAX_SPOTS",
]

VALID_ORDERS = ("rigid", "affine", "quadratic")

# Resource-limit defaults (see FINDINGS S6). gate_refine scales ~linearly at ~60 us/spot with
# a Python-level union-find loop in detect_pieces, so there is no hard OOM cliff, but very large
# slices take minutes and hurt interactivity. Warn past WARN, refuse/subsample past MAX.
DEFAULT_WARN_SPOTS = 100_000
DEFAULT_MAX_SPOTS = 500_000

# A pitch this small relative to the coordinate span means the geometry is effectively degenerate
# (all spots coincident / collinear-to-a-point): a real spot grid always has a finite positive pitch.
_MIN_REL_PITCH = 1e-9


class RobustnessError(ValueError):
    """Raised for any invalid/unsupported input to the alignment pipeline.

    Subclasses ValueError so existing `except ValueError` handlers keep working, while callers
    who want to distinguish 'the user gave us bad data' from other errors can catch this type.
    """


# --------------------------------------------------------------------------- #
# coordinate-level validation
# --------------------------------------------------------------------------- #
def validate_coords(arr, name: str, *, allow_nonfinite: bool = False,
                    min_spots: int = 0) -> np.ndarray:
    """Coerce `arr` to a contiguous float64 (N, 2) array and validate it.

    Parameters
    ----------
    name             : argument name, used verbatim in error messages.
    allow_nonfinite  : if False (default), any NaN/inf raises. Set True for the OT `base`
                       coordinates, where NaN rows (spots that received no transported mass)
                       are a legitimate, gate-handled input.
    min_spots        : raise if fewer than this many rows.

    Raises RobustnessError with an actionable message; never a raw numpy error.
    """
    try:
        a = np.asarray(arr, dtype=np.float64)
    except (ValueError, TypeError) as e:
        raise RobustnessError(
            f"{name} could not be interpreted as a numeric array ({e}). "
            f"Pass a numeric (N, 2) array of spot coordinates."
        ) from None
    if a.ndim != 2 or a.shape[1] != 2:
        raise RobustnessError(
            f"{name} must be a 2-D array of shape (N, 2) (one (x, y) per spot); "
            f"got shape {a.shape}. Spatial coordinates are 2-D - if you have a 3-D or "
            f"transposed array, reshape it to (N, 2) first."
        )
    n = a.shape[0]
    if n < min_spots:
        raise RobustnessError(
            f"{name} has only {n} spot(s); at least {min_spots} are required."
        )
    if not allow_nonfinite and n and not np.isfinite(a).all():
        bad = int((~np.isfinite(a).all(axis=1)).sum())
        first = int(np.flatnonzero(~np.isfinite(a).all(axis=1))[0])
        raise RobustnessError(
            f"{name} contains {bad} spot(s) with NaN/inf coordinates (first at row {first}). "
            f"Observed spot positions must be finite. Drop or repair these spots before "
            f"alignment (for the OT `base` argument NaN rows are allowed and handled)."
        )
    return np.ascontiguousarray(a)


def resolve_pitch(moving: np.ndarray, pitch) -> float:
    """Return a positive finite pitch. Compute from `moving` if `pitch` is None, else validate
    the supplied value. Detects degenerate geometry (duplicate / single / collinear-to-a-point
    spots) that would otherwise cause a silent divide-by-zero deep in the gate.
    """
    if pitch is None:
        if len(moving) < 2:
            raise RobustnessError(
                "Cannot infer spot pitch from fewer than 2 spots. Pass pitch=<spot spacing> "
                "explicitly, or supply more spots."
            )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            pitch = _gr.median_pitch(moving)
        if not np.isfinite(pitch) or pitch <= 0:
            raise RobustnessError(
                "Inferred spot pitch is not a positive finite number - the moving coordinates "
                "look degenerate (many duplicate or coincident spots, so the median "
                "nearest-neighbour distance is 0 or undefined). Deduplicate the spots or pass "
                "pitch=<spot spacing> explicitly."
            )
    else:
        try:
            pitch = float(pitch)
        except (TypeError, ValueError):
            raise RobustnessError(f"pitch must be a number; got {pitch!r}.") from None
        if not np.isfinite(pitch) or pitch <= 0:
            raise RobustnessError(
                f"pitch must be a positive finite number (the spot spacing / length scale); "
                f"got {pitch}. A zero, negative, or NaN pitch silently corrupts the trust gate."
            )
    # Guard against a pitch that is negligible relative to the coordinate span, which is the
    # degenerate-geometry signature even when a positive value slipped through.
    if len(moving) >= 2:
        span = float(np.ptp(moving, axis=0).max())
        if span > 0 and pitch < _MIN_REL_PITCH * span:
            raise RobustnessError(
                f"pitch ({pitch:g}) is negligible relative to the coordinate span ({span:g}); "
                f"the geometry is effectively degenerate. Check the coordinate units / pitch."
            )
    return float(pitch)


def validate_weights(weights, n: int):
    """Validate optional per-spot fit weights. Returns a clean float64 (n,) array or None."""
    if weights is None:
        return None
    try:
        w = np.asarray(weights, dtype=np.float64).ravel()
    except (ValueError, TypeError) as e:
        raise RobustnessError(f"weights could not be interpreted as a numeric array ({e}).") from None
    if w.shape[0] != n:
        raise RobustnessError(
            f"weights has length {w.shape[0]} but there are {n} spots; they must match."
        )
    if not np.isfinite(w).all():
        raise RobustnessError(
            "weights contains NaN/inf. Per-spot weights must be finite (a NaN weight makes the "
            "weighted least-squares fit diverge). Use 0 to down-weight a spot to nothing."
        )
    if (w < 0).any():
        raise RobustnessError(
            "weights contains negative values. Confidence weights must be >= 0."
        )
    if float(w.sum()) <= 0:
        raise RobustnessError(
            "weights sum to 0 - every spot is down-weighted to nothing, so no fit is possible. "
            "Provide at least one positive weight or pass weights=None for uniform weighting."
        )
    return w


# --------------------------------------------------------------------------- #
# hardened gate_refine
# --------------------------------------------------------------------------- #
def safe_gate_refine(base_coords, moving_coords, order="affine", *, pitch=None,
                     weights=None, on_nonfinite_moving="error", normalize=True,
                     warn_spots=DEFAULT_WARN_SPOTS, max_spots=DEFAULT_MAX_SPOTS,
                     on_oversize="error", subsample_seed=0, return_info=False, **kw):
    """Validated, fail-loud wrapper around gate_refine.gate_refine.

    Guarantees, for any input:
      * a clear RobustnessError (never a raw scipy/numpy trace) on malformed input, and
      * finite output at every spot whose moving coordinate is finite (no silent NaN leak).

    Parameters (beyond gate_refine's)
    ---------------------------------
    on_nonfinite_moving : "error" (default) | "drop". Moving coords are observed spot positions
                          and must be finite. "drop" removes non-finite moving spots, refines the
                          rest, and returns NaN in the dropped rows (shape preserved), with a warning.
    warn_spots          : emit a warning above this spot count (slow, hurts interactivity).
    max_spots           : hard limit. Above it, behaviour is `on_oversize`.
    on_oversize         : "error" (default) | "subsample". "subsample" deterministically downsamples
                          to max_spots (base is projected on the subsample; dropped rows are returned
                          as NaN) with a warning, rather than running for minutes.
    subsample_seed      : seed for the deterministic oversize subsample.
    normalize           : True (default) centres and scales the coordinates by the pitch before the
                          per-piece fit and un-normalises the result. This is mathematically
                          equivariant for the fit (identical result to raw gate_refine at normal
                          scale, to float precision) but dramatically better-conditioned, so it
                          keeps the refinement numerically stable - and never-regressing - at
                          extreme coordinate magnitudes (e.g. nanometres or 1e12 pixels) where the
                          raw un-normalised polynomial fit degrades or blows up (see FINDINGS S4).

    Extra keyword args are forwarded to gate_refine.gate_refine (thr, scale, cv, seed, stretch,
    min_frac, ...).
    """
    if isinstance(order, str):
        if order not in VALID_ORDERS:
            raise RobustnessError(
                f"order must be one of {VALID_ORDERS}; got {order!r}."
            )
    elif order not in (0, 1, 2):
        raise RobustnessError(
            f"order must be one of {VALID_ORDERS} (or 0/1/2); got {order!r}."
        )

    base = validate_coords(base_coords, "base_coords", allow_nonfinite=True)
    mov = validate_coords(moving_coords, "moving_coords", allow_nonfinite=True)
    if base.shape != mov.shape:
        raise RobustnessError(
            f"base_coords {base.shape} and moving_coords {mov.shape} must have the same shape "
            f"(one predicted (x, y) per moving spot)."
        )
    n = base.shape[0]

    # Empty / trivially small input: gate_refine already returns the base unchanged and safe.
    if n == 0:
        out = base.copy()
        return (out, {"labels": np.zeros(0, int), "pieces": [], "pitch": float("nan"),
                      "order": order, "thr": kw.get("thr", 4.5), "gated_fraction": 0.0}) \
            if return_info else out

    # base must have SOMETHING finite to refine toward.
    base_finite_rows = np.isfinite(base).all(axis=1)
    if not base_finite_rows.any():
        raise RobustnessError(
            "base_coords is entirely non-finite (no spot received a predicted reference "
            "coordinate). There is nothing to refine - check the upstream OT/alignment step."
        )

    # Handle non-finite moving coordinates.
    mov_finite_rows = np.isfinite(mov).all(axis=1)
    dropped_mask = ~mov_finite_rows
    if dropped_mask.any():
        if on_nonfinite_moving == "error":
            bad = int(dropped_mask.sum())
            first = int(np.flatnonzero(dropped_mask)[0])
            raise RobustnessError(
                f"moving_coords contains {bad} spot(s) with NaN/inf coordinates "
                f"(first at row {first}). Observed spot positions must be finite. "
                f"Pass on_nonfinite_moving='drop' to drop them (output NaN in those rows), "
                f"or repair the coordinates."
            )
        elif on_nonfinite_moving == "drop":
            warnings.warn(
                f"Dropping {int(dropped_mask.sum())} moving spot(s) with non-finite coordinates; "
                f"they are returned as NaN.", RuntimeWarning, stacklevel=2)
        else:
            raise RobustnessError(
                f"on_nonfinite_moving must be 'error' or 'drop'; got {on_nonfinite_moving!r}.")

    keep = mov_finite_rows
    weights = validate_weights(weights, n)

    # Resource limit on the number of spots actually processed.
    n_keep = int(keep.sum())
    if n_keep > warn_spots:
        warnings.warn(
            f"Refining {n_keep} spots; gate_refine runs a Python-level segmentation loop and "
            f"may take a while at this size (~60 us/spot). Consider subsampling for interactive use.",
            RuntimeWarning, stacklevel=2)
    if n_keep > max_spots:
        if on_oversize == "error":
            raise RobustnessError(
                f"Refining {n_keep} spots exceeds max_spots={max_spots}. Pass "
                f"on_oversize='subsample' for graceful downsampling, or raise max_spots if you "
                f"can afford the time/memory."
            )
        elif on_oversize == "subsample":
            keep_idx = np.flatnonzero(keep)
            rng = np.random.default_rng(subsample_seed)
            sel = np.sort(rng.choice(keep_idx, size=max_spots, replace=False))
            new_keep = np.zeros(n, bool)
            new_keep[sel] = True
            keep = new_keep
            warnings.warn(
                f"Subsampled {n_keep} -> {max_spots} spots (seed={subsample_seed}); "
                f"non-selected spots are returned as NaN.", RuntimeWarning, stacklevel=2)
        else:
            raise RobustnessError(
                f"on_oversize must be 'error' or 'subsample'; got {on_oversize!r}.")

    pitch = resolve_pitch(mov[keep], pitch)

    # Fast path: no rows to drop/subsample -> refine the whole array.
    if keep.all():
        res = _run_gate(base, mov, order, pitch, weights, normalize, return_info, kw)
        out = res[0] if return_info else res
        _postcheck(out, base_finite_rows & keep)
        return res

    # Subset path: run on the kept spots, scatter back, NaN elsewhere.
    sub_w = None if weights is None else weights[keep]
    sub = _run_gate(base[keep], mov[keep], order, pitch, sub_w, normalize, return_info, kw)
    sub_out = sub[0] if return_info else sub
    out = np.full((n, 2), np.nan)
    out[keep] = sub_out
    _postcheck(out, base_finite_rows & keep)
    if return_info:
        info = sub[1]
        info["dropped_spots"] = int((~keep).sum())
        return out, info
    return out


def _run_gate(base, mov, order, pitch, weights, normalize, return_info, kw):
    """Call gate_refine, optionally with pitch-normalised coordinates for conditioning.

    Normalisation centres moving on its own centroid and base on its own (finite-row) centroid,
    scales both by `pitch`, and runs the gate at pitch=1. Because the per-piece fit is invariant
    under an affine reparametrisation of source and target, and piece detection / the residual
    gate work in pitch units either way, the result equals the un-normalised run at normal scale
    (to float precision) while staying well-conditioned at any coordinate magnitude.
    """
    try:
        if not normalize:
            return _gr.gate_refine(base, mov, order=order, pitch=pitch, weights=weights,
                                   return_info=return_info, **kw)
        c_m = mov[np.isfinite(mov).all(axis=1)].mean(axis=0)
        fb = np.isfinite(base).all(axis=1)
        c_b = base[fb].mean(axis=0)
        mov_h = (mov - c_m) / pitch
        base_h = (base - c_b) / pitch
        res = _gr.gate_refine(base_h, mov_h, order=order, pitch=1.0, weights=weights,
                              return_info=return_info, **kw)
        out_h = res[0] if return_info else res
        out = out_h * pitch + c_b
        if return_info:
            info = res[1]
            info["pitch"] = pitch          # report the real pitch, not the normalised 1.0
            return out, info
        return out
    except RobustnessError:
        raise
    except Exception as e:  # noqa: BLE001 - translate any deep failure to a clear message
        raise RobustnessError(
            f"gate_refine failed unexpectedly on validated input "
            f"({type(e).__name__}: {e}). This is a bug in the guard's validation - "
            f"please report the input shape ({np.shape(base)}) and order={order!r}."
        ) from e


def _postcheck(out: np.ndarray, expect_finite_mask: np.ndarray) -> None:
    """Post-condition: output must be finite for every spot with a finite base AND finite moving
    coordinate (the set where a real answer is always possible). A spot with a NaN base that its
    piece was too small to place legitimately stays NaN - that is the honest 'cannot place'
    answer, not a silent NaN leak, so it is excluded from the mask by the caller.
    """
    bad = expect_finite_mask & ~np.isfinite(out).all(axis=1)
    if bad.any():
        raise RobustnessError(
            f"internal error: refinement produced non-finite output for {int(bad.sum())} "
            f"spot(s) that had a finite base and moving coordinate. Refusing to return a "
            f"silently-wrong result. Please report this input."
        )


# --------------------------------------------------------------------------- #
# transport-plan / scoring validation
# --------------------------------------------------------------------------- #
def validate_transport_plan(pi, n_a: int | None = None, n_b: int | None = None) -> np.ndarray:
    """Validate an OT transport plan `pi` (shape (n_a, n_b)) before projection/scoring."""
    try:
        pi = np.asarray(pi, dtype=np.float64)
    except (ValueError, TypeError) as e:
        raise RobustnessError(f"transport plan could not be read as a numeric array ({e}).") from None
    if pi.ndim != 2:
        raise RobustnessError(f"transport plan must be 2-D (n_a, n_b); got shape {pi.shape}.")
    if pi.size == 0:
        raise RobustnessError("transport plan is empty (0 spots on one side).")
    if not np.isfinite(pi).all():
        raise RobustnessError("transport plan contains NaN/inf entries.")
    if (pi < 0).any():
        raise RobustnessError("transport plan contains negative mass; a valid OT plan is >= 0.")
    if n_a is not None and pi.shape[0] != n_a:
        raise RobustnessError(
            f"transport plan has {pi.shape[0]} rows but the reference slice has {n_a} spots.")
    if n_b is not None and pi.shape[1] != n_b:
        raise RobustnessError(
            f"transport plan has {pi.shape[1]} columns but the moving slice has {n_b} spots.")
    return pi


def safe_barycentric_projection(pi, source_coords):
    """Barycentric projection with validation and a warning when the plan is degenerate.

    Returns (pred_coords (n_b, 2), col_mass (n_b,)) exactly like scoring.barycentric_projection,
    but raises a clear error on shape mismatch and warns (instead of silently returning all-NaN)
    when the plan transports no mass anywhere.
    """
    src = validate_coords(source_coords, "source_coords", allow_nonfinite=False)
    pi = validate_transport_plan(pi, n_a=src.shape[0])
    col_mass = pi.sum(axis=0)
    safe = col_mass > 0
    if not safe.any():
        warnings.warn(
            "transport plan carries no mass to any moving spot; every projected coordinate is "
            "NaN. The upstream OT step likely failed.", RuntimeWarning, stacklevel=2)
    pred = np.full((pi.shape[1], src.shape[1]), np.nan)
    pred[safe] = (pi[:, safe].T @ src) / col_mass[safe, None]
    return pred, col_mass


# --------------------------------------------------------------------------- #
# section-level (AnnData) validation
# --------------------------------------------------------------------------- #
def safe_read_h5ad(path):
    """Read an h5ad, translating a missing/corrupted file into a clear RobustnessError."""
    path = Path(path)
    if not path.exists():
        raise RobustnessError(f"h5ad file not found: {path}")
    if path.stat().st_size == 0:
        raise RobustnessError(f"h5ad file is empty (0 bytes): {path}")
    try:
        import anndata as ad
    except ImportError as e:
        raise RobustnessError(
            "anndata is required to read h5ad files but is not installed."
        ) from e
    try:
        return ad.read_h5ad(path)
    except Exception as e:  # noqa: BLE001 - h5py raises many low-level types on corruption
        raise RobustnessError(
            f"failed to read h5ad '{path}' ({type(e).__name__}: {e}). The file may be corrupted, "
            f"truncated, or not a valid AnnData/HDF5 file."
        ) from e


def validate_section(adata, name: str = "section", *, spatial_key: str = "spatial",
                     min_spots: int = 3, check_expression: bool = True,
                     warn_spots: int = DEFAULT_WARN_SPOTS) -> None:
    """Validate one spatial section (AnnData) before it enters the pipeline.

    Checks: obsm spatial key present (else lists available keys), spatial is finite (N, 2),
    enough spots, and - if check_expression - that the expression matrix has no NaN/inf and is
    not all-zero. Raises RobustnessError with an actionable message; warns on soft issues.
    """
    n = int(getattr(adata, "n_obs", 0))
    if n == 0:
        raise RobustnessError(f"{name} is empty (0 spots).")
    if n < min_spots:
        raise RobustnessError(
            f"{name} has only {n} spot(s); at least {min_spots} are needed to align.")

    obsm = getattr(adata, "obsm", {})
    if spatial_key not in obsm:
        avail = list(obsm.keys())
        raise RobustnessError(
            f"{name} has no obsm['{spatial_key}'] (spot coordinates). "
            f"Available obsm keys: {avail or '(none)'}. Set the coordinates under "
            f"'{spatial_key}' or pass the correct spatial_key."
        )
    # reuse coordinate validation (finite, (N,2))
    validate_coords(obsm[spatial_key], f"{name}.obsm['{spatial_key}']", min_spots=min_spots)

    if n > warn_spots:
        warnings.warn(
            f"{name} has {n} spots - alignment/refinement may be slow; consider subsampling.",
            RuntimeWarning, stacklevel=2)

    if check_expression:
        X = getattr(adata, "X", None)
        if X is not None:
            arr = X.toarray() if hasattr(X, "toarray") else np.asarray(X)
            if arr.size:
                if not np.isfinite(arr).all():
                    raise RobustnessError(
                        f"{name}.X (expression) contains NaN/inf. Clean or impute the expression "
                        f"matrix before alignment.")
                if not np.any(arr != 0):
                    warnings.warn(
                        f"{name}.X is entirely zero - the expression matrix carries no signal. "
                        f"Alignment that relies on expression will be meaningless.",
                        RuntimeWarning, stacklevel=2)


def validate_section_pair(A, B, *, spatial_key: str = "spatial",
                          min_panel_overlap: int = 10, size_ratio_warn: float = 10.0,
                          require_visium_bridge: bool = False, **kw) -> None:
    """Validate a (reference A, moving B) section pair.

    Runs validate_section on each, then cross-checks:
      * gene-panel overlap  - disjoint panels raise; a tiny overlap warns.
      * spot-count ratio    - a >size_ratio_warn imbalance warns (alignment gets unreliable).
      * (optional) the Visium array-bridge columns array_row/array_col needed by array_bridge()
        for synthetic-GT scoring - missing columns raise a clear error instead of a later KeyError.
    """
    validate_section(A, "reference (A)", spatial_key=spatial_key, **kw)
    validate_section(B, "moving (B)", spatial_key=spatial_key, **kw)

    va = set(map(str, getattr(A, "var_names", [])))
    vb = set(map(str, getattr(B, "var_names", [])))
    if va and vb:
        overlap = len(va & vb)
        if overlap == 0:
            raise RobustnessError(
                "reference and moving sections share NO genes - their panels are disjoint "
                "(different gene naming or different assays). A common gene panel is required.")
        if overlap < min_panel_overlap:
            warnings.warn(
                f"reference and moving sections share only {overlap} gene(s); expression-based "
                f"alignment will be unreliable. Check that the panels/naming match.",
                RuntimeWarning, stacklevel=2)

    na, nb = int(getattr(A, "n_obs", 0)), int(getattr(B, "n_obs", 0))
    if na and nb:
        ratio = max(na, nb) / min(na, nb)
        if ratio > size_ratio_warn:
            warnings.warn(
                f"reference has {na} spots and moving has {nb} ({ratio:.0f}x imbalance); "
                f"alignment between very differently sized slices is unreliable.",
                RuntimeWarning, stacklevel=2)

    if require_visium_bridge:
        for adata, nm in ((A, "reference (A)"), (B, "moving (B)")):
            obs = getattr(adata, "obs", None)
            cols = set(getattr(obs, "columns", []))
            missing = {"array_row", "array_col"} - cols
            if missing:
                raise RobustnessError(
                    f"{nm} is missing obs column(s) {sorted(missing)} required for the Visium "
                    f"array-bridge ground truth (array_bridge). This section is not Visium, or the "
                    f"array indices were not loaded. Provide array_row/array_col or use a "
                    f"different GT source.")
