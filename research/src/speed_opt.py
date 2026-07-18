"""
speed_opt.py -- make PASTE2 alignment practical for interactive use WITHOUT
losing accuracy. Branch: speed-opt. Writes only research/results/speed_opt*.

PASTE2's real cost is its partial-FGW conditional-gradient solve: numItermax=1000
iterations, each doing O(n^2..n^3) matrix work plus an exact EMD network-simplex
solve, with a very tight stopThr=1e-9. On our largest / highest-severity pairs a
full-resolution solve runs multiple minutes and blew a 900s watchdog.

This driver studies four independent speed levers and reports the fastest
configuration that preserves accuracy within noise:

  (B) SUBSAMPLING     accuracy vs speed across 500/1000/1500/2500 spots + full,
                      random vs spatially-stratified vs expression-informed
                      (farthest-point) selection, with AND without the gate.
  (C) SOLVER          instrumented conditional-gradient FGW: every solve records
                      the barycentric error at each checkpoint iteration, so ONE
                      solve reveals the whole early-stopping (numItermax/stopThr)
                      accuracy curve. Plus exact-EMD vs armijo line search vs an
                      entropic (Sinkhorn) inner oracle.
  (D) CACHING         build-cost (dist matrices + PCA cost) vs solve-cost split,
                      and real reuse on a multi-section chain (shared section's
                      intra-distance / PCA reused across consecutive pairs).
  (E) PARALLEL        wall-clock for 4/8/12-section chains, sequential vs a
                      process pool (each worker BLAS-pinned to 1 thread).

Plus a SCALE test (largest pairs + severity 8, synthetic upsample to probe the
O(n^3) tail, confirm nothing hangs) and an END-TO-END recommended config.

Everything is measured against REAL PASTE2 math on the SAME warped slices with the
array-bridge ground truth in spot-pitches -- identical metric to hybrid_validate.py.

Robustness: detached-friendly; heartbeat; per-solve watchdog timeout with graceful
skip; every cell wrapped in try/except; rows appended to the CSV immediately;
resumable (already-done config keys are skipped on restart).

Outputs: research/results/speed_opt.csv (+ .log). Plot + FINDINGS are separate.
Usage:
  python research/src/speed_opt.py                 # full study (detached-friendly)
  python research/src/speed_opt.py --smoke         # tiny: 1 ds, 1 sev, small N
  python research/src/speed_opt.py --phases B,C     # subset of phases
  python research/src/speed_opt.py --datasets Br8100 --seeds 0
"""
from __future__ import annotations

import os
# BLAS thread cap: default 3 (fast-ish anchors while leaving headroom). The
# parallel phase pins its workers to 1 thread inside the worker process.
_THREADS = os.environ.get("SPEED_OPT_THREADS", "3")
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, _THREADS)

import argparse
import csv
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree, distance

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # arca/
SRC = ROOT / "src"
for p in (SRC,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import anndata as ad                                            # noqa: E402
import ot                                                       # noqa: E402
from scoring import (registration_error_stats,                  # noqa: E402
                     barycentric_projection)
from warp_slice import apply_warp                               # noqa: E402
from train_cross import array_bridge                            # noqa: E402
from hybrid_combined import gated_piecewise, detect_pieces      # noqa: E402
# PASTE2 internals we reuse verbatim (the exact FGW math, just re-driven so we
# can instrument iterations and swap the inner oracle):
from paste2.PASTE2 import (gwgrad_partial, gwloss_partial,      # noqa: E402
                           fgwloss_partial, fgwgrad_partial)
from paste2.helper import intersect, pca_distance              # noqa: E402

DATA = ROOT / "data"
EXT = DATA / "external"
OUT = ROOT / "research" / "results"
CSV_PATH = OUT / "speed_opt.csv"
LOG_PATH = OUT / "speed_opt.log"

# --- dataset grid (matches hybrid_validate.py) ---
PAIRS = {
    "Br5292": ("DLPFC_151507", "DLPFC_151508", "dlpfc"),
    "Br5595": ("DLPFC_151669", "DLPFC_151670", "dlpfc"),
    "Br8100": ("DLPFC_151673", "DLPFC_151674", "dlpfc"),
    "breast": ("V1_Breast_Cancer_Block_A_Section_1",
               "V1_Breast_Cancer_Block_A_Section_2", "ood"),
    "mousebrain": ("V1_Mouse_Brain_Sagittal_Posterior",
                   "V1_Mouse_Brain_Sagittal_Posterior_Section_2", "ood"),
}
# DLPFC 4-section chain for caching / parallel phases (consecutive pairs share a
# section, so its intra-distance + expression PCA can be reused).
CHAIN = ["DLPFC_151673", "DLPFC_151674", "DLPFC_151675", "DLPFC_151676"]

SEVS = [0.0, 4.0, 8.0]
SEEDS = [0, 1]
N_LEVELS = [500, 1000, 1500, 2500]      # subsample targets (full added separately)
METHODS = ["random", "spatial", "expr"]

# PASTE2 base params (identical to hybrid_combined.paste2_prior)
S_OVERLAP = 0.99
ALPHA = 0.1
N_HVG = 2000
LATENT = 20

# solve caps: we run to a moderate cap and record per-iteration error, so any
# earlier numItermax can be read off the recorded curve post-hoc.
NUMITERMAX = 300
STOPTHR = 1e-6
CHECKPOINTS = [1, 2, 3, 5, 8, 12, 20, 30, 50, 75, 100, 150, 200, 300]
SOLVE_TIMEOUT = 900

HEARTBEAT = 20
_STAGE = "init"
_HB_STOP = False

CSV_FIELDS = ["phase", "dataset", "kind", "severity", "seed", "n_target",
              "n_a", "n_b", "sub_method", "solver", "config", "iter",
              "err_pitch", "paste2_err_pitch", "beats_paste2", "n_scored",
              "pitch", "build_s", "solve_s", "total_s", "status",
              "timestamp", "detail"]


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="ascii", errors="replace") as fh:
            fh.write(line + "\n")
    except Exception:                                            # noqa: BLE001
        pass


def stage(s):
    global _STAGE
    _STAGE = s


def _heartbeat():
    t0 = time.time()
    while not _HB_STOP:
        time.sleep(1)
        if _HB_STOP:
            break
        if int(time.time() - t0) % HEARTBEAT == 0:
            log(f"... alive stage='{_STAGE}' ({int(time.time()-t0)}s)")


_done_keys = set()


def _load_done():
    if not CSV_PATH.exists():
        return
    try:
        with open(CSV_PATH, newline="", encoding="ascii", errors="replace") as fh:
            for row in csv.DictReader(fh):
                _done_keys.add(_row_key(row))
    except Exception as e:                                       # noqa: BLE001
        log(f"could not preload done keys: {e!r}")
    log(f"resume: {len(_done_keys)} rows already present")


def _row_key(row):
    # a "cell" is uniquely identified up to config+iter; we resume at cell level
    return (row.get("phase", ""), row.get("dataset", ""), str(row.get("severity", "")),
            str(row.get("seed", "")), str(row.get("n_target", "")),
            row.get("sub_method", ""), row.get("solver", ""),
            row.get("config", ""), str(row.get("iter", "")))


def append_row(row):
    OUT.mkdir(parents=True, exist_ok=True)
    exists = CSV_PATH.exists()
    full = {k: row.get(k, "") for k in CSV_FIELDS}
    with open(CSV_PATH, "a", newline="", encoding="ascii", errors="replace") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(full)
    _done_keys.add(_row_key(full))


def cell_done(phase, dataset, sev, seed, n_target, method, solver):
    """True if this (phase,ds,sev,seed,N,method,solver) cell already has its
    final gated_rigid row -> skip on resume."""
    k = (phase, dataset, str(sev), str(seed), str(n_target), method, solver,
         "gated_rigid", "final")
    return k in _done_keys


def call_with_timeout(fn, timeout, *a, **k):
    box = {}

    def worker():
        try:
            box["v"] = fn(*a, **k)
        except Exception as e:                                   # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"exceeded {timeout}s")
    if "e" in box:
        raise box["e"]
    return box.get("v")


# --------------------------------------------------------------------------- #
# data loading
# --------------------------------------------------------------------------- #
def _find(name):
    fp = DATA / f"{name}.h5ad"
    return fp if fp.exists() else EXT / f"{name}.h5ad"


def _read(name):
    A = ad.read_h5ad(_find(name))
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    return A


def slice_embedding(adata, n_hvg=N_HVG, dim=30, seed=0):
    """Light per-slice expression embedding for expression-informed subsampling.
    Log-normalize, top-HVG, PCA. Returns (n_obs, dim) float32."""
    import scanpy as sc
    a = adata.copy()
    sc.pp.normalize_total(a, inplace=True)
    sc.pp.log1p(a)
    try:
        sc.pp.highly_variable_genes(a, flavor="seurat",
                                    n_top_genes=min(n_hvg, a.n_vars - 1),
                                    inplace=True, subset=True)
    except Exception:                                            # noqa: BLE001
        pass
    sc.pp.pca(a, min(dim, a.n_vars - 1, a.n_obs - 1))
    return np.asarray(a.obsm["X_pca"], np.float32)


# --------------------------------------------------------------------------- #
# subsampling methods
# --------------------------------------------------------------------------- #
def _fps(feats, k, seed):
    """Greedy farthest-point sampling in `feats` space. Even coverage of the
    feature space; O(k*n)."""
    n = len(feats)
    if k >= n:
        return np.arange(n)
    rng = np.random.default_rng(seed)
    sel = [int(rng.integers(n))]
    d = np.linalg.norm(feats - feats[sel[0]], axis=1)
    for _ in range(k - 1):
        i = int(np.argmax(d))
        sel.append(i)
        d = np.minimum(d, np.linalg.norm(feats - feats[i], axis=1))
    return np.sort(np.asarray(sel))


def subsample_idx(n, coords, emb, method, k, seed):
    """Return sorted indices of a size-<=k subsample of a slice.
    random   : uniform.
    spatial  : farthest-point in 2D spatial coords (even spatial coverage).
    expr     : farthest-point in expression-PCA space (even expression coverage).
    """
    if k >= n:
        return np.arange(n)
    if method == "random":
        return np.sort(np.random.default_rng(seed).choice(n, k, replace=False))
    if method == "spatial":
        return _fps(np.asarray(coords, float), k, seed)
    if method == "expr":
        if emb is None:
            return np.sort(np.random.default_rng(seed).choice(n, k, replace=False))
        return _fps(emb, k, seed)
    raise ValueError(method)


# --------------------------------------------------------------------------- #
# cost-matrix build (the cacheable expensive-but-fixed part) and the
# instrumented partial-FGW solve
# --------------------------------------------------------------------------- #
def build_costs(A, B, norm=True):
    """Replicate paste2.partial_pairwise_align setup: common genes, intra-slice
    spatial distance matrices D_A/D_B, expression cost M (PCA), normalized.
    This is the reusable/cacheable work; the FGW solve consumes it."""
    common = intersect(A.var.index, B.var.index)
    Aa = A[:, common]
    Bb = B[:, common]
    D_A = distance.cdist(Aa.obsm["spatial"], Aa.obsm["spatial"])
    D_B = distance.cdist(Bb.obsm["spatial"], Bb.obsm["spatial"])
    M = pca_distance(Aa, Bb, N_HVG, LATENT)
    a = np.ones(Aa.shape[0]) / Aa.shape[0]
    b = np.ones(Bb.shape[0]) / Bb.shape[0]
    if norm:
        D_A /= D_A[D_A > 0].min()
        D_B /= D_B[D_B > 0].min()
        D_A /= D_A[D_A > 0].max(); D_A *= M.max()
        D_B /= D_B[D_B > 0].max(); D_B *= M.max()
    return M, D_A, D_B, a, b


def _emd_oracle(p_ext, q_ext, gradF_emd):
    Gc, logemd = ot.lp.emd(p_ext, q_ext, gradF_emd, numItermax=1000000, log=True)
    if logemd["warning"] is not None:
        raise ValueError("EMD did not converge")
    return Gc


def _sinkhorn_oracle(p_ext, q_ext, gradF_emd, reg):
    """Entropic (Sinkhorn) approximation of the linear-minimization oracle. Costs
    are shifted non-negative for numerical stability. Much cheaper per iter than
    exact EMD network simplex, at the cost of a smoothed (blurrier) plan."""
    C = gradF_emd - gradF_emd.min()
    C = C / (C.max() + 1e-12)
    return ot.sinkhorn(p_ext, q_ext, C, reg, numItermax=200, stopThr=1e-6)


def solve_fgw(M, D_A, D_B, a, b, A_coords, gt, mask, pitch,
              alpha=ALPHA, m=S_OVERLAP, numItermax=NUMITERMAX, stopThr=STOPTHR,
              armijo=False, solver="emd", reg=1e-2, checkpoints=None,
              record=None):
    """Instrumented partial-FGW conditional gradient (identical math to
    paste2.partial_fused_gromov_wasserstein) with:
      * per-checkpoint barycentric error recorded (accuracy-vs-iteration curve),
      * pluggable inner oracle (exact EMD / entropic Sinkhorn),
      * armijo or exact line search.
    `record(iter, solve_s, err_pitch)` is called at each checkpoint.
    Returns (pi, n_iter, solve_s, curve[list of (iter, solve_s, err)])."""
    p, q = a, b
    G0 = np.outer(p, q)
    nb_dummies = 1
    dim_ext = (len(p) + nb_dummies, len(q) + nb_dummies)
    q_ext = np.append(q, [(np.sum(p) - m) / nb_dummies] * nb_dummies)
    p_ext = np.append(p, [(np.sum(q) - m) / nb_dummies] * nb_dummies)
    checkpoints = set(checkpoints or CHECKPOINTS)
    curve = []
    t0 = time.time()
    f_val = fgwloss_partial(alpha, M, D_A, D_B, G0)
    cpt = 0

    def _score(G):
        pred, col = barycentric_projection(G, A_coords)
        cen = A_coords.mean(0)
        bad = ~np.isfinite(pred).all(1)
        pred[bad] = cen
        return registration_error_stats(pred, gt, mask=mask)["median"] / pitch

    while cpt < numItermax:
        Gprev = np.copy(G0)
        old_fval = f_val
        gradF = fgwgrad_partial(alpha, M, D_A, D_B, G0)
        gradF_emd = np.zeros(dim_ext)
        gradF_emd[:len(p), :len(q)] = gradF
        gradF_emd[-nb_dummies:, -nb_dummies:] = np.max(gradF) * 1e2
        gradF_emd = np.asarray(gradF_emd, dtype=np.float64)

        if solver == "sinkhorn":
            Gc = _sinkhorn_oracle(p_ext, q_ext, gradF_emd, reg)
        else:
            Gc = _emd_oracle(p_ext, q_ext, gradF_emd)

        G0 = Gc[:len(p), :len(q)]
        deltaG = G0 - Gprev
        if not armijo:
            aa = alpha * gwloss_partial(D_A, D_B, deltaG)
            bb = ((1 - alpha) * np.sum(M * deltaG)
                  + 2 * alpha * np.sum(gwgrad_partial(D_A, D_B, deltaG) * 0.5 * Gprev))
            gamma = ot.optim.solve_1d_linesearch_quad(aa, bb)
        else:
            def f(x):
                return fgwloss_partial(alpha, M, D_A, D_B, x)
            gfk = fgwgrad_partial(alpha, M, D_A, D_B, Gprev)
            gamma, _, _ = ot.optim.line_search_armijo(
                lambda x, *_a: f(x), Gprev, deltaG, gfk, old_fval, ())
            if gamma is None:
                gamma = 0.0
        if gamma == 0:
            cpt = numItermax
        G0 = Gprev + gamma * deltaG
        f_val = fgwloss_partial(alpha, M, D_A, D_B, G0)
        cpt += 1

        if cpt in checkpoints or cpt >= numItermax:
            dt = time.time() - t0
            try:
                err = _score(G0)
            except Exception:                                    # noqa: BLE001
                err = float("nan")
            curve.append((cpt, dt, err))
            if record is not None:
                record(cpt, dt, err)

        abs_d = abs(f_val - old_fval)
        rel_d = abs_d / (abs(f_val) + 1e-15)
        if rel_d < stopThr or abs_d < 1e-9:
            if cpt not in checkpoints:                           # capture the stop point
                dt = time.time() - t0
                try:
                    err = _score(G0)
                except Exception:                                # noqa: BLE001
                    err = float("nan")
                curve.append((cpt, dt, err))
                if record is not None:
                    record(cpt, dt, err)
            break
    solve_s = time.time() - t0
    return G0, cpt, solve_s, curve


# --------------------------------------------------------------------------- #
# pair preparation (loaded once, cached across sev/seed/N/method)
# --------------------------------------------------------------------------- #
_PAIRS = {}


def prep_pair(name):
    if name in _PAIRS:
        return _PAIRS[name]
    ref, mov, kind = PAIRS[name]
    stage(f"{name}:load")
    A = _read(ref)
    B = _read(mov)
    coords_A = np.asarray(A.obsm["spatial"], float)
    coords_B = np.asarray(B.obsm["spatial"], float)
    pitch = float(np.median(cKDTree(coords_A).query(coords_A, k=2)[0][:, 1]))
    gt, have = array_bridge(A, B)                    # per-B-spot A-pixel target
    stage(f"{name}:embed")
    try:
        emb_A = slice_embedding(A)
        emb_B = slice_embedding(B)
    except Exception as e:                                       # noqa: BLE001
        log(f"[{name}] embedding failed ({e!r}); expr-subsample falls back to random")
        emb_A = emb_B = None
    pair = dict(name=name, kind=kind, A=A, B=B, coords_A=coords_A,
                coords_B=coords_B, pitch=pitch, gt=gt, have=have,
                emb_A=emb_A, emb_B=emb_B)
    _PAIRS[name] = pair
    log(f"[{name}] A={A.n_obs} B={B.n_obs} pitch={pitch:.1f} bridge={have.mean()*100:.0f}%")
    return pair


# --------------------------------------------------------------------------- #
# one measured solve cell (subsample -> build -> solve -> score paste2 + gate)
# --------------------------------------------------------------------------- #
def run_cell(phase, pair, sev, seed, n_target, method, solver="emd",
             armijo=False, reg=1e-2, numItermax=NUMITERMAX, stopThr=STOPTHR):
    name = pair["name"]
    if cell_done(phase, name, sev, seed, n_target, method, solver):
        return None
    stage(f"{phase}:{name}:s{sev:g}:seed{seed}:N{n_target}:{method}:{solver}")
    base_meta = dict(phase=phase, dataset=name, kind=pair["kind"], severity=sev,
                     seed=seed, n_target=n_target, sub_method=method, solver=solver,
                     pitch=round(pair["pitch"], 1))
    try:
        # warp full B, then subsample A and warped-B
        w, _ = apply_warp(pair["B"], sev, seed=seed, tear=True)
        wcoords = np.asarray(w.obsm["spatial"], float)
        nA, nB = pair["A"].n_obs, pair["B"].n_obs
        ia = subsample_idx(nA, pair["coords_A"], pair["emb_A"], method, n_target, seed + 11)
        ib = subsample_idx(nB, wcoords, pair["emb_B"], method, n_target, seed + 23)
        A_sub = pair["A"][ia].copy()
        B_sub = w[ib].copy()
        A_coords = pair["coords_A"][ia]
        gt_sub = pair["gt"][ib]
        have_sub = pair["have"][ib]
        moving = wcoords[ib].astype(np.float32)
        pitch = pair["pitch"]
        if have_sub.sum() < 20:
            append_row({**base_meta, "config": "skip", "status": "skip",
                        "detail": f"bridge too small ({int(have_sub.sum())})",
                        "timestamp": _now()})
            return None

        tb = time.time()
        M, D_A, D_B, a, b = build_costs(A_sub, B_sub)
        build_s = time.time() - tb

        def record(it, solve_s, err):
            append_row({**base_meta, "config": "paste2", "iter": it,
                        "err_pitch": round(float(err), 4), "n_scored": int(have_sub.sum()),
                        "n_a": len(ia), "n_b": len(ib), "build_s": round(build_s, 2),
                        "solve_s": round(solve_s, 2),
                        "total_s": round(build_s + solve_s, 2),
                        "status": "ok", "timestamp": _now()})

        pi, n_iter, solve_s, curve = call_with_timeout(
            solve_fgw, SOLVE_TIMEOUT, M, D_A, D_B, a, b, A_coords, gt_sub,
            have_sub, pitch, numItermax=numItermax, stopThr=stopThr,
            armijo=armijo, solver=solver, reg=reg, record=record)

        # final paste2 base + gate
        pred, col = barycentric_projection(pi, A_coords)
        cen = A_coords.mean(0)
        pred[~np.isfinite(pred).all(1)] = cen
        p2_err = registration_error_stats(pred, gt_sub, mask=have_sub)["median"] / pitch
        conf = np.ones(len(ib), np.float32)
        total_s = build_s + solve_s
        gr = gated_piecewise(moving, pred.astype(np.float32), conf, pitch, order=0, seed=seed, cv=False)
        ga = gated_piecewise(moving, pred.astype(np.float32), conf, pitch, order=1, seed=seed, cv=True)
        gr_err = registration_error_stats(gr, gt_sub, mask=have_sub)["median"] / pitch
        ga_err = registration_error_stats(ga, gt_sub, mask=have_sub)["median"] / pitch
        for cfg, e in (("gated_rigid", gr_err), ("gated_affine", ga_err)):
            append_row({**base_meta, "config": cfg, "iter": "final",
                        "err_pitch": round(float(e), 4),
                        "paste2_err_pitch": round(float(p2_err), 4),
                        "beats_paste2": bool(e <= p2_err), "n_scored": int(have_sub.sum()),
                        "n_a": len(ia), "n_b": len(ib), "build_s": round(build_s, 2),
                        "solve_s": round(solve_s, 2), "total_s": round(total_s, 2),
                        "status": "ok", "timestamp": _now()})
        log(f"[{phase}] {name} s{sev:g} seed{seed} N{n_target}/{method}/{solver} "
            f"nA={len(ia)} nB={len(ib)} iters={n_iter} build={build_s:.1f}s "
            f"solve={solve_s:.1f}s p2={p2_err:.2f} grig={gr_err:.2f} gaff={ga_err:.2f}")
        return dict(p2=p2_err, gr=gr_err, ga=ga_err, build_s=build_s,
                    solve_s=solve_s, total_s=total_s, n_iter=n_iter,
                    n_a=len(ia), n_b=len(ib))
    except Exception as e:                                       # noqa: BLE001
        append_row({**base_meta, "config": "error", "status": "error",
                    "detail": f"{type(e).__name__}: {e}"[:180], "timestamp": _now()})
        log(f"[{phase}] {name} s{sev:g} seed{seed} N{n_target}/{method}/{solver} "
            f"FAILED: {e!r}")
        return None


# --------------------------------------------------------------------------- #
# self-contained one-pair solve for the parallel/chain phase. Runs in a fresh
# process (BLAS pinned via SPEED_OPT_THREADS env), returns timing only -- no CSV
# writes from workers (parent aggregates), so concurrent runs can't corrupt it.
# --------------------------------------------------------------------------- #
def chain_task(ref, mov, sev, seed, n_target, numItermax=150, stopThr=1e-6):
    t0 = time.time()
    A = _read(ref)
    B = _read(mov)
    coords_A = np.asarray(A.obsm["spatial"], float)
    pitch = float(np.median(cKDTree(coords_A).query(coords_A, k=2)[0][:, 1]))
    gt, have = array_bridge(A, B)
    w, _ = apply_warp(B, sev, seed=seed, tear=True)
    wcoords = np.asarray(w.obsm["spatial"], float)
    ia = subsample_idx(A.n_obs, coords_A, None, "random", n_target, seed + 11)
    ib = subsample_idx(B.n_obs, wcoords, None, "random", n_target, seed + 23)
    A_sub, B_sub = A[ia].copy(), w[ib].copy()
    M, D_A, D_B, a, b = build_costs(A_sub, B_sub)
    pi, n_iter, solve_s, _ = solve_fgw(
        M, D_A, D_B, a, b, coords_A[ia], gt[ib], have[ib], pitch,
        numItermax=numItermax, stopThr=stopThr, checkpoints=[])
    return dict(ref=ref, mov=mov, sev=sev, n=n_target, wall_s=time.time() - t0,
                solve_s=solve_s, n_iter=n_iter, n_a=len(ia), n_b=len(ib))


if __name__ == "__main__":                                       # dispatch in phases module
    from speed_opt_run import main
    main()
