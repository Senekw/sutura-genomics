"""Global multi-section 3D reconstruction: a true bundle-adjustment-style solve
vs. the pairwise-chained baseline.

Motivation
----------
Our serial-section reconstruction currently chains pairwise alignments: section
k+1 is aligned into section k's frame, and to build a common 3D frame we compose
those adjacent transforms sequentially (see cli reconstruct.build_pointcloud).
Each pairwise transform carries estimation error; composing a long chain lets
those errors accumulate as a random walk, so the terminal sections drift.

A *global* solve instead treats every section's pose as an unknown and every
measured pairwise transform -- adjacent AND non-adjacent -- as a constraint,
solving for all poses simultaneously (pose-graph optimisation / bundle
adjustment). Redundant non-adjacent constraints (loop closures) pin down the
poses so terminal error stays bounded instead of accumulating.

Transform model
---------------
We use 2D similarity transforms (rotation + uniform scale + translation), the
same family the pairwise reconstructor fits (Umeyama). A 2D similarity is a
complex affine map  z' = c*z + d  with c, d in C (c encodes rotation+scale, d
the translation). Composition and inversion are complex arithmetic, and -- the
key fact that makes the global solve cheap and exact -- the pose-graph
constraints are LINEAR in the complex pose parameters. So similarity
synchronisation is a single (optionally robust/iterative) linear least squares.

This module is self-contained (numpy + anndata). It writes an incremental CSV,
a heartbeat, and is fully wrapped in try/except so an overnight detached run
never dies silently. Plotting lives in global_recon_plot.py.

Honesty note: the controlled experiment measures drift against an EXACTLY known
ground-truth placement (random similarity poses applied to real DLPFC section
geometry). The real-data experiment has no ground-truth pose, so it reports
label-consistency of the reconstructed stack and the all-edge constraint
residual instead. Both are reported; neither is dressed up as the other.
"""
from __future__ import annotations

import os
import sys
import csv
import time
import json
import traceback
from itertools import combinations

import numpy as np

# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA_DIR = os.path.join(REPO, "data")
RESULTS_DIR = os.path.join(REPO, "research", "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

CSV_PATH = os.path.join(RESULTS_DIR, "global_recon.csv")
HEARTBEAT = os.path.join(RESULTS_DIR, "global_recon.heartbeat")
LOG_PATH = os.path.join(RESULTS_DIR, "global_recon.log")

# DLPFC donors: 4 serial sections each. Br8100 (151673-76) is the held-out donor.
DONORS = {
    "Br5292": [151507, 151508, 151509, 151510],
    "Br5595": [151669, 151670, 151671, 151672],
    "Br8100": [151673, 151674, 151675, 151676],
}
# One long ordered chain of all 12 (donor blocks concatenated in donor order).
FULL_CHAIN = DONORS["Br5292"] + DONORS["Br5595"] + DONORS["Br8100"]

LAYERS = ["Layer1", "Layer2", "Layer3", "Layer4", "Layer5", "Layer6", "WM"]


def log(msg: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def beat(msg: str) -> None:
    try:
        with open(HEARTBEAT, "w", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Similarity transforms as complex affine maps  z' = c*z + d
# ---------------------------------------------------------------------------
def to_c(pts):
    pts = np.asarray(pts, float)
    return pts[:, 0] + 1j * pts[:, 1]


def from_c(z):
    z = np.asarray(z)
    return np.column_stack([z.real, z.imag])


def t_apply(T, pts):
    c, d = T
    return from_c(c * to_c(pts) + d)


def t_compose(outer, inner):
    """x -> outer(inner(x)).  (c1,d1) o (c2,d2) = (c1*c2, c1*d2 + d1)."""
    c1, d1 = outer
    c2, d2 = inner
    return (c1 * c2, c1 * d2 + d1)


def t_invert(T):
    c, d = T
    return (1.0 / c, -d / c)


T_ID = (1.0 + 0j, 0.0 + 0j)


def fit_similarity(src, dst):
    """Least-squares similarity src -> dst. Returns (T, rms_fit_residual).

    Linear complex LS: solve for (c, d) in  dst ~= c*src + d.
    rms_fit_residual is the RMS landmark error after the fit -- our intrinsic
    quality signal for an edge (used by the gate and the robust weights).
    """
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    n = len(src)
    if n < 2 or n != len(dst):
        return T_ID, float("inf")
    zs = to_c(src)
    zd = to_c(dst)
    A = np.column_stack([zs, np.ones(n)])
    sol, *_ = np.linalg.lstsq(A, zd, rcond=None)
    c, d = sol[0], sol[1]
    resid = np.abs(A @ sol - zd)
    rms = float(np.sqrt((resid ** 2).mean()))
    return (c, d), rms


# ---------------------------------------------------------------------------
# Pairwise-chain reconstruction (the current approach)
# ---------------------------------------------------------------------------
def pairwise_chain_poses(n, edges):
    """Compose adjacent edges sequentially into global poses P_i (frame i->frame0).

    edges: dict (a,b) -> (T, rms) with T mapping frame a -> frame b.
    Only adjacent edges (i, i+1) are used; section 0 is the reference.
    Missing adjacent edge -> that section and all downstream inherit the last
    good pose (the chain is broken; honestly recorded by the caller).
    """
    poses = [T_ID] * n
    for i in range(1, n):
        e = edges.get((i - 1, i))
        if e is None:
            # broken chain: carry the previous pose (best we can do without a bridge)
            poses[i] = poses[i - 1]
            continue
        T_prev_to_i = e[0]                       # frame (i-1) -> frame i
        # P_i = P_{i-1} o inverse(edge):  frame i -> frame (i-1) -> ... -> frame 0
        poses[i] = t_compose(poses[i - 1], t_invert(T_prev_to_i))
    return poses


# ---------------------------------------------------------------------------
# Global solve: similarity synchronisation (pose-graph least squares)
# ---------------------------------------------------------------------------
def global_solve(n, edges, weights=None, irls_iters=0):
    """Solve for global poses P_i (frame i -> frame 0) from all measured edges.

    Each edge (a,b) carries T=(za,zb) [frame a -> frame b]; the pose-graph
    constraint P_a = P_b o T splits (in complex pose params) into a rotation+
    scale part and a translation part:
        c_a = za * c_b                        (rotation + scale)
        d_a = zb * c_b + d_b                  (translation)
    We solve this as the standard TWO-STEP similarity synchronisation, because a
    single joint least squares mixes unit-scale rotation residuals with
    coordinate-scale (~thousands) translation residuals and is badly
    conditioned:
      Step 1 (rotation+scale averaging): least squares  c_a - za*c_b = 0  with
              c_0 = 1 fixed (gauge). Uses every edge, adjacent and not.
      Step 2 (translation averaging): with the c_i fixed, the edges give
              d_a - d_b = za?..  -> d_a - d_b = c_b*zb, a well-conditioned
              graph-Laplacian system; d_0 = 0 fixed.
    Redundant non-adjacent edges make both steps over-determined, which is
    exactly what averages down per-edge noise instead of accumulating it.

    irls_iters>0 runs iteratively-reweighted least squares: after a solve, each
    edge is re-weighted by a robust (Huber) function of its residual, so bad /
    inconsistent edges are down-weighted. `weights` supplies a fixed prior
    weight per edge (e.g. a gate that zeroes poorly-fit edges).

    Returns (poses, info) with per-edge residuals and the final weights.
    """
    edge_list = list(edges.items())
    if not edge_list:
        return [T_ID] * n, {"edge_residuals": {}, "weights": {}}

    base_w = {}
    for (a, b), (T, rms) in edge_list:
        if weights is not None and (a, b) in weights:
            base_w[(a, b)] = float(weights[(a, b)])
        else:
            base_w[(a, b)] = 1.0

    def col(i):
        return i - 1                      # unknown index for section i (1..n-1)

    def solve_rotscale(w):
        # unknowns c_1..c_{n-1} (complex); c_0 = 1
        rows, rhs = [], []
        for (a, b), (T, rms) in edge_list:
            za, zb = T
            wt = np.sqrt(max(w[(a, b)], 1e-12))
            r = np.zeros(n - 1, dtype=complex)
            const = 0j
            if a == 0:
                const += 1.0                     # +c_0
            else:
                r[col(a)] += 1.0
            if b == 0:
                const += -za                     # -za*c_0
            else:
                r[col(b)] += -za
            rows.append(wt * r)
            rhs.append(wt * (-const))
        A = np.array(rows, dtype=complex)
        y = np.array(rhs, dtype=complex)
        if A.shape[1] == 0:
            return [1.0 + 0j]
        sol, *_ = np.linalg.lstsq(A, y, rcond=None)
        return [1.0 + 0j] + list(sol)

    def solve_trans(cvals, w):
        # unknowns d_1..d_{n-1}; d_0 = 0.  d_a - d_b = c_b * zb
        rows, rhs = [], []
        for (a, b), (T, rms) in edge_list:
            za, zb = T
            wt = np.sqrt(max(w[(a, b)], 1e-12))
            r = np.zeros(n - 1, dtype=complex)
            if a != 0:
                r[col(a)] += 1.0
            if b != 0:
                r[col(b)] += -1.0
            rows.append(wt * r)
            rhs.append(wt * (cvals[b] * zb))
        A = np.array(rows, dtype=complex)
        y = np.array(rhs, dtype=complex)
        if A.shape[1] == 0:
            return [0.0 + 0j]
        sol, *_ = np.linalg.lstsq(A, y, rcond=None)
        return [0.0 + 0j] + list(sol)

    def build(w):
        cvals = solve_rotscale(w)
        dvals = solve_trans(cvals, w)
        return [(cvals[i], dvals[i]) for i in range(n)]

    w = dict(base_w)
    poses = build(w)
    for _ in range(irls_iters):
        res = _edge_residuals(poses, edge_list)
        vals = np.array([v for v in res.values() if np.isfinite(v)])
        scale = np.median(vals) if len(vals) else 1.0
        delta = 1.4826 * (scale + 1e-9)
        for k, rr in res.items():
            w[k] = base_w[k] * (1.0 if rr <= delta else delta / (rr + 1e-12))
        poses = build(w)

    info = {"edge_residuals": _edge_residuals(poses, edge_list), "weights": w}
    return poses, info


def _edge_residuals(poses, edge_list):
    """Per-edge residual: RMS discrepancy of the constraint P_a = P_b o T,
    evaluated by mapping a unit landmark set through both sides."""
    probe = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    out = {}
    for (a, b), (T, rms) in edge_list:
        lhs = t_apply(poses[a], probe)
        rhs = t_apply(poses[b], t_apply(T, probe))
        out[(a, b)] = float(np.sqrt(((lhs - rhs) ** 2).sum(1).mean()))
    return out


# ---------------------------------------------------------------------------
# Edge measurement
# ---------------------------------------------------------------------------
def measure_edges(landmarks, pairs, rng, sev_noise=0.0):
    """Estimate the relative transform for each requested (a,b) pair by fitting
    a similarity to the (corresponded) landmark sets, with optional severity
    noise added to the destination landmarks (simulates imperfect registration).

    landmarks: list of (L, 2) arrays, one per section, rows in correspondence
    (layer centroids share semantics across DLPFC sections).
    Returns edges dict (a,b) -> (T mapping frame a -> frame b, rms_fit).
    """
    edges = {}
    for (a, b) in pairs:
        src = landmarks[a]
        dst = landmarks[b]
        ok = np.isfinite(src).all(1) & np.isfinite(dst).all(1)
        if ok.sum() < 2:
            continue
        s, d = src[ok], dst[ok]
        if sev_noise > 0:
            d = d + rng.normal(0.0, sev_noise, size=d.shape)
        edges[(a, b)] = fit_similarity(s, d)
    return edges


def band_pairs(n, k):
    """All ordered pairs (a,b) with 0 < b-a <= k (a<b)."""
    return [(a, b) for a in range(n) for b in range(a + 1, min(a + k + 1, n))]


# ---------------------------------------------------------------------------
# DLPFC loading
# ---------------------------------------------------------------------------
_CACHE = {}


def load_section(sid):
    """Return (coords (N,2) float, layer labels (N,) str) for one DLPFC section."""
    if sid in _CACHE:
        return _CACHE[sid]
    import anndata as ad
    path = os.path.join(DATA_DIR, f"DLPFC_{sid}.h5ad")
    a = ad.read_h5ad(path)
    coords = np.asarray(a.obsm["spatial"], float)
    col = "layer" if "layer" in a.obs else "sce.layer_guess"
    labels = a.obs[col].astype(str).to_numpy()
    _CACHE[sid] = (coords, labels)
    return coords, labels


def layer_centroids(coords, labels):
    """(L,2) array of per-layer centroids in LAYERS order; NaN if a layer absent."""
    out = np.full((len(LAYERS), 2), np.nan)
    for i, lay in enumerate(LAYERS):
        m = labels == lay
        if m.sum() >= 3:
            out[i] = coords[m].mean(0)
    return out


def section_landmarks(sid):
    coords, labels = load_section(sid)
    return layer_centroids(coords, labels)


def tissue_scale(sid):
    coords, _ = load_section(sid)
    return float(np.sqrt(((coords - coords.mean(0)) ** 2).sum(1).mean()))


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
CSV_FIELDS = [
    "experiment", "method", "chain_len", "severity", "seed", "edge_band",
    "gate", "metric", "value", "runtime_s", "n_edges", "note",
]


def csv_init():
    new = not os.path.exists(CSV_PATH)
    fh = open(CSV_PATH, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
    if new:
        w.writeheader()
        fh.flush()
    return fh, w


def emit(writer, fh, **row):
    full = {k: row.get(k, "") for k in CSV_FIELDS}
    writer.writerow(full)
    fh.flush()


# ---------------------------------------------------------------------------
# Ground-truth (controlled) drift experiment
# ---------------------------------------------------------------------------
def random_similarity(rng, rot_deg=180.0, scale_jit=0.15, trans=2000.0):
    theta = np.deg2rad(rng.uniform(-rot_deg, rot_deg))
    s = float(np.exp(rng.normal(0.0, scale_jit)))
    c = s * (np.cos(theta) + 1j * np.sin(theta))
    d = complex(rng.normal(0.0, trans), rng.normal(0.0, trans))
    return (c, d)


def controlled_pose_error(poses, G_true, eval_pts_list):
    """Mean over sections of RMS distance between the reconstructed placement of
    a section's eval points and their TRUE world placement.

    Section i observed coords X_i = G_i(W_i); true frame i->world = inv(G_i).
    Reconstructed pose P_i maps frame i -> frame 0 (= world, since G_0=id).
    So error_i = RMS( P_i(X_i)  vs  W_i ), where X_i = G_i(W_i).
    """
    errs = []
    for i, (P, G, W) in enumerate(zip(poses, G_true, eval_pts_list)):
        X_i = t_apply(G, W)
        placed = t_apply(P, X_i)
        errs.append(float(np.sqrt(((placed - W) ** 2).sum(1).mean())))
    return errs


def build_controlled_chain(base_sid, n, rng, bio_jitter):
    """Construct n synthetic sections from one real section's geometry.

    World placement W_i = base landmarks + independent biological jitter.
    Observed frame: X_i = G_i(W_i) with G_0 = identity, G_i random similarity.
    Returns (G_true list, landmark_obs list, eval_pts list).
    eval_pts are the real spot coords (world frame) used for dense error eval.
    """
    coords, labels = load_section(base_sid)
    base_lm = layer_centroids(coords, labels)
    finite = np.isfinite(base_lm).all(1)
    scale = tissue_scale(base_sid)

    G_true = [T_ID]
    for i in range(1, n):
        G_true.append(random_similarity(rng))

    lm_obs = []
    eval_pts = []
    # a fixed dense evaluation cloud (subsample of real spots), same across i
    idx = rng.choice(len(coords), size=min(400, len(coords)), replace=False)
    eval_world_base = coords[idx]
    for i in range(n):
        W_lm = base_lm.copy()
        W_lm[finite] = W_lm[finite] + rng.normal(0.0, bio_jitter * scale,
                                                 size=W_lm[finite].shape)
        lm_obs.append(t_apply(G_true[i], W_lm))
        # eval points share the SAME world layout (bio jitter only perturbs the
        # landmark estimation, not the evaluation geometry -> clean GT)
        eval_pts.append(eval_world_base)
    return G_true, lm_obs, eval_pts


def exp_controlled(writer, fh, seeds, chain_lens, severities, base_sid=151507):
    """Experiment A: drift vs chain length under exactly-known ground truth."""
    log("=== Experiment A: controlled drift vs chain length ===")
    scale = tissue_scale(base_sid)
    for sev in severities:
        sev_noise = sev * 0.01 * scale   # severity as % of tissue radius
        for n in chain_lens:
            for seed in seeds:
                beat(f"A n={n} sev={sev} seed={seed}")
                try:
                    rng = np.random.default_rng(1000 * seed + n + int(sev * 7))
                    G_true, lm_obs, eval_pts = build_controlled_chain(
                        base_sid, n, rng, bio_jitter=0.01)
                    band = min(3, n - 1)
                    # measure the FULL edge set once; all methods share the same
                    # measured edges (fair comparison -- only the SOLVER differs)
                    e_full = measure_edges(lm_obs, band_pairs(n, n - 1), rng, sev_noise)
                    e_adj = {k: v for k, v in e_full.items() if k[1] - k[0] == 1}
                    e_band = {k: v for k, v in e_full.items() if k[1] - k[0] <= band}
                    # --- pairwise chain (adjacent only) ---
                    t0 = time.perf_counter()
                    p_pair = pairwise_chain_poses(n, e_adj)
                    rt_pair = time.perf_counter() - t0
                    err_pair = controlled_pose_error(p_pair, G_true, eval_pts)
                    # --- global, adjacent-only (isolates 'simultaneous' effect) ---
                    t0 = time.perf_counter()
                    p_g1, _ = global_solve(n, e_adj)
                    rt_g1 = time.perf_counter() - t0
                    err_g1 = controlled_pose_error(p_g1, G_true, eval_pts)
                    # --- global with non-adjacent band (loop closures) ---
                    t0 = time.perf_counter()
                    p_g, _ = global_solve(n, e_band)
                    rt_g = time.perf_counter() - t0
                    err_g = controlled_pose_error(p_g, G_true, eval_pts)
                    # --- global full (all pairs) ---
                    t0 = time.perf_counter()
                    p_gf, _ = global_solve(n, e_full)
                    rt_gf = time.perf_counter() - t0
                    err_gf = controlled_pose_error(p_gf, G_true, eval_pts)

                    common = dict(experiment="controlled", chain_len=n,
                                  severity=sev, seed=seed)
                    # terminal-section error (last section = worst drift)
                    emit(writer, fh, **common, method="pairwise_chain",
                         edge_band=1, metric="terminal_err", value=err_pair[-1],
                         runtime_s=rt_pair, n_edges=len(e_adj))
                    emit(writer, fh, **common, method="global_adj",
                         edge_band=1, metric="terminal_err", value=err_g1[-1],
                         runtime_s=rt_g1, n_edges=len(e_adj))
                    emit(writer, fh, **common, method="global_band",
                         edge_band=band, metric="terminal_err", value=err_g[-1],
                         runtime_s=rt_g, n_edges=len(e_band))
                    emit(writer, fh, **common, method="global_full",
                         edge_band=n - 1, metric="terminal_err", value=err_gf[-1],
                         runtime_s=rt_gf, n_edges=len(e_full))
                    # mean-over-sections error
                    emit(writer, fh, **common, method="pairwise_chain",
                         edge_band=1, metric="mean_err", value=float(np.mean(err_pair)),
                         runtime_s=rt_pair, n_edges=len(e_adj))
                    emit(writer, fh, **common, method="global_band",
                         edge_band=band, metric="mean_err", value=float(np.mean(err_g)),
                         runtime_s=rt_g, n_edges=len(e_band))
                    emit(writer, fh, **common, method="global_full",
                         edge_band=n - 1, metric="mean_err", value=float(np.mean(err_gf)),
                         runtime_s=rt_gf, n_edges=len(e_full))
                except Exception as ex:
                    log(f"  A FAIL n={n} sev={sev} seed={seed}: {ex}")
                    log(traceback.format_exc())
    log("Experiment A done.")


# ---------------------------------------------------------------------------
# Real-data experiment (no synthetic ground truth)
# ---------------------------------------------------------------------------
def stack_label_consistency(poses, sids, k=6):
    """Reconstruct the stack, then measure how often a spot's nearest neighbours
    in the ADJACENT section (in the common frame) share its layer label.
    Higher = better in-plane alignment of matching cortical layers across z.
    """
    from numpy.linalg import norm
    placed = []
    labs = []
    for P, sid in zip(poses, sids):
        coords, labels = load_section(sid)
        placed.append(t_apply(P, coords))
        labs.append(labels)
    agree = []
    for i in range(len(sids) - 1):
        A, B = placed[i], placed[i + 1]
        la, lb = labs[i], labs[i + 1]
        # subsample for speed
        rng = np.random.default_rng(0)
        idx = rng.choice(len(A), size=min(300, len(A)), replace=False)
        for j in idx:
            d = ((B - A[j]) ** 2).sum(1)
            nn = np.argpartition(d, k)[:k]
            match = np.mean([lb[m] == la[j] for m in nn if lb[m] != "nan"
                             and lb[m] != "NA"])
            if not np.isnan(match):
                agree.append(match)
    return float(np.mean(agree)) if agree else float("nan")


def all_edge_residual(poses, edges):
    r = _edge_residuals(poses, list(edges.items()))
    return float(np.mean(list(r.values()))) if r else float("nan")


def exp_real(writer, fh, seeds, severities):
    """Experiment B: global vs pairwise on the real 12-section chains.
    Metrics: label-consistency of the reconstructed stack, and the all-edge
    constraint residual (how self-consistent the recovered poses are)."""
    log("=== Experiment B: real DLPFC chains ===")
    chains = {f"donor_{name}": sids for name, sids in DONORS.items()}
    chains["full12"] = FULL_CHAIN
    for cname, sids in chains.items():
        n = len(sids)
        lm = [section_landmarks(s) for s in sids]
        for sev in severities:
            scale = np.nanmean([tissue_scale(s) for s in sids])
            sev_noise = sev * 0.01 * scale
            for seed in seeds:
                beat(f"B {cname} sev={sev} seed={seed}")
                try:
                    rng = np.random.default_rng(7000 + seed + int(sev))
                    band = min(3, n - 1)
                    e_full = measure_edges(lm, band_pairs(n, n - 1), rng, sev_noise)
                    e_adj = {k: v for k, v in e_full.items() if k[1] - k[0] == 1}
                    e_band = {k: v for k, v in e_full.items() if k[1] - k[0] <= band}

                    p_pair = pairwise_chain_poses(n, e_adj)
                    p_gb, _ = global_solve(n, e_band)
                    p_gf, _ = global_solve(n, e_full)

                    common = dict(experiment=f"real_{cname}", chain_len=n,
                                  severity=sev, seed=seed)
                    # constraint residual against the FULL edge set (fair to all)
                    emit(writer, fh, **common, method="pairwise_chain", edge_band=1,
                         metric="alledge_resid",
                         value=all_edge_residual(p_pair, e_full), n_edges=len(e_adj))
                    emit(writer, fh, **common, method="global_band", edge_band=band,
                         metric="alledge_resid",
                         value=all_edge_residual(p_gb, e_full), n_edges=len(e_band))
                    emit(writer, fh, **common, method="global_full", edge_band=n - 1,
                         metric="alledge_resid",
                         value=all_edge_residual(p_gf, e_full), n_edges=len(e_full))
                    # label consistency (seed-independent geometry; compute once)
                    if seed == seeds[0] and sev == severities[0]:
                        lc_pair = stack_label_consistency(p_pair, sids)
                        lc_gf = stack_label_consistency(p_gf, sids)
                        emit(writer, fh, **common, method="pairwise_chain",
                             edge_band=1, metric="label_consistency", value=lc_pair)
                        emit(writer, fh, **common, method="global_full",
                             edge_band=n - 1, metric="label_consistency", value=lc_gf)
                except Exception as ex:
                    log(f"  B FAIL {cname} sev={sev} seed={seed}: {ex}")
                    log(traceback.format_exc())
    log("Experiment B done.")


# ---------------------------------------------------------------------------
# Robustness: missing sections, bad edges, inconsistent estimates
# ---------------------------------------------------------------------------
def exp_robustness(writer, fh, seeds, base_sid=151507):
    """Experiment C: real-world degradations, using the controlled GT so we can
    score recovery honestly."""
    log("=== Experiment C: robustness ===")
    n = 12
    scale = tissue_scale(base_sid)
    sev_noise = 3 * 0.01 * scale   # moderate severity
    for seed in seeds:
        beat(f"C seed={seed}")
        try:
            rng = np.random.default_rng(3000 + seed)
            G_true, lm_obs, eval_pts = build_controlled_chain(
                base_sid, n, rng, bio_jitter=0.01)

            # ---- (1) MISSING SECTION: drop the adjacent edge across a gap ----
            # remove section 6's adjacent links; pairwise chain must bridge, the
            # global solve routes around it via non-adjacent band edges.
            band = 3
            pr = band_pairs(n, band)
            drop = {6}
            pr_missing = [(a, b) for (a, b) in pr if a not in drop and b not in drop]
            e_missing = measure_edges(lm_obs, pr_missing, rng, sev_noise)
            # pairwise sees only adjacent, which is broken at the gap
            adj_missing = {k: v for k, v in e_missing.items() if k[1] - k[0] == 1}
            p_pair = pairwise_chain_poses(n, adj_missing)
            p_glob, _ = global_solve(n, e_missing)
            err_pair = controlled_pose_error(p_pair, G_true, eval_pts)
            err_glob = controlled_pose_error(p_glob, G_true, eval_pts)
            keep = [i for i in range(n) if i not in drop]
            common = dict(experiment="robust_missing", chain_len=n,
                          severity=3, seed=seed)
            emit(writer, fh, **common, method="pairwise_chain", edge_band=1,
                 metric="mean_err_kept",
                 value=float(np.mean([err_pair[i] for i in keep])),
                 n_edges=len(adj_missing), note="section6_missing")
            emit(writer, fh, **common, method="global_band", edge_band=band,
                 metric="mean_err_kept",
                 value=float(np.mean([err_glob[i] for i in keep])),
                 n_edges=len(e_missing), note="section6_missing")

            # ---- (2) BAD EDGE: one grossly corrupted adjacent estimate ----
            pr = band_pairs(n, band)
            e_all = measure_edges(lm_obs, pr, rng, sev_noise)
            bad_key = (5, 6)
            # corrupt the (5,6) edge with a large bogus rotation+shift
            bogus = (np.exp(1j * 1.3) * 0.7, complex(1500, -1200))
            e_bad = dict(e_all)
            e_bad[bad_key] = (bogus, 999.0)     # huge fit residual flags it
            # naive global (no robustness)
            p_naive, _ = global_solve(n, e_bad)
            # robust global (IRLS down-weights the outlier)
            p_robust, _ = global_solve(n, e_bad, irls_iters=5)
            # gated global: drop edges whose fit residual exceeds the gate
            gate_thr = _gate_threshold(e_bad)
            w_gate = {k: (1.0 if v[1] <= gate_thr else 0.0) for k, v in e_bad.items()}
            p_gate, _ = global_solve(n, e_bad, weights=w_gate)
            for tag, poses, ne in [
                ("global_naive", p_naive, len(e_bad)),
                ("global_irls", p_robust, len(e_bad)),
                ("global_gated", p_gate, sum(w_gate.values()))]:
                emit(writer, fh, experiment="robust_badedge", method=tag,
                     chain_len=n, severity=3, seed=seed, edge_band=band,
                     metric="mean_err", value=float(np.mean(
                         controlled_pose_error(poses, G_true, eval_pts))),
                     n_edges=int(ne), note="edge(5,6)_corrupted")

            # ---- (3) INCONSISTENT ESTIMATES: high measurement noise everywhere -
            hi_noise = 8 * 0.01 * scale
            pr = band_pairs(n, band)
            e_noisy = measure_edges(lm_obs, pr, rng, hi_noise)
            adj_noisy = {k: v for k, v in e_noisy.items() if k[1] - k[0] == 1}
            p_pair2 = pairwise_chain_poses(n, adj_noisy)
            p_glob2, _ = global_solve(n, e_noisy, irls_iters=3)
            emit(writer, fh, experiment="robust_inconsistent",
                 method="pairwise_chain", chain_len=n, severity=8, seed=seed,
                 edge_band=1, metric="mean_err", value=float(np.mean(
                     controlled_pose_error(p_pair2, G_true, eval_pts))),
                 n_edges=len(adj_noisy), note="high_noise")
            emit(writer, fh, experiment="robust_inconsistent",
                 method="global_band_irls", chain_len=n, severity=8, seed=seed,
                 edge_band=band, metric="mean_err", value=float(np.mean(
                     controlled_pose_error(p_glob2, G_true, eval_pts))),
                 n_edges=len(e_noisy), note="high_noise")
        except Exception as ex:
            log(f"  C FAIL seed={seed}: {ex}")
            log(traceback.format_exc())
    log("Experiment C done.")


def _gate_threshold(edges):
    """Gate = median fit residual + 3*MAD (robust upper fence). Edges above are
    'poorly fit' and get dropped/down-weighted."""
    r = np.array([v[1] for v in edges.values() if np.isfinite(v[1])])
    if len(r) == 0:
        return float("inf")
    med = np.median(r)
    mad = np.median(np.abs(r - med)) + 1e-9
    return float(med + 3 * 1.4826 * mad)


# ---------------------------------------------------------------------------
# Gate within the global solve
# ---------------------------------------------------------------------------
def exp_gate(writer, fh, seeds, base_sid=151507):
    """Experiment E: apply the gate (fit-residual gating of edges) inside the
    global solve, on chains that contain a realistic fraction of bad edges."""
    log("=== Experiment E: gate within the global solve ===")
    n = 12
    band = 3
    scale = tissue_scale(base_sid)
    sev_noise = 3 * 0.01 * scale
    for frac_bad in (0.0, 0.1, 0.2):
        for seed in seeds:
            beat(f"E frac_bad={frac_bad} seed={seed}")
            try:
                rng = np.random.default_rng(5000 + seed + int(frac_bad * 100))
                G_true, lm_obs, eval_pts = build_controlled_chain(
                    base_sid, n, rng, bio_jitter=0.01)
                pr = band_pairs(n, band)
                edges = measure_edges(lm_obs, pr, rng, sev_noise)
                # corrupt a fraction of edges
                keys = list(edges.keys())
                nbad = int(round(frac_bad * len(keys)))
                bad = set(rng.choice(len(keys), size=nbad, replace=False).tolist()) \
                    if nbad else set()
                for bi in bad:
                    k = keys[bi]
                    edges[k] = ((np.exp(1j * rng.uniform(-2, 2)) *
                                 float(np.exp(rng.normal(0, 0.5))),
                                 complex(rng.normal(0, 1500), rng.normal(0, 1500))),
                                500.0 + rng.uniform(0, 500))
                # no gate
                p_nog, _ = global_solve(n, edges)
                # gate (drop edges above robust fit-residual fence)
                thr = _gate_threshold(edges)
                w_gate = {k: (1.0 if v[1] <= thr else 0.0) for k, v in edges.items()}
                p_gate, _ = global_solve(n, edges, weights=w_gate)
                # gate + IRLS (belt and suspenders)
                p_both, _ = global_solve(n, edges, weights=w_gate, irls_iters=4)
                for tag, poses, gate_on, ne in [
                    ("global_band", p_nog, "off", len(edges)),
                    ("global_band_gated", p_gate, "on", int(sum(w_gate.values()))),
                    ("global_band_gated_irls", p_both, "on+irls",
                     int(sum(w_gate.values())))]:
                    emit(writer, fh, experiment="gate", method=tag, chain_len=n,
                         severity=3, seed=seed, edge_band=band, gate=gate_on,
                         metric="mean_err", value=float(np.mean(
                             controlled_pose_error(poses, G_true, eval_pts))),
                         n_edges=ne, note=f"frac_bad={frac_bad}")
            except Exception as ex:
                log(f"  E FAIL frac_bad={frac_bad} seed={seed}: {ex}")
                log(traceback.format_exc())
    log("Experiment E done.")


# ---------------------------------------------------------------------------
# Runtime scaling
# ---------------------------------------------------------------------------
def exp_runtime(writer, fh, base_sid=151507):
    """Experiment D: cost of measuring edges + solving, vs section count and
    edge density. Reports wall time and edge count (the dominant cost is the
    number of pairwise alignments you must run to feed the solver)."""
    log("=== Experiment D: runtime scaling ===")
    scale = tissue_scale(base_sid)
    sev_noise = 3 * 0.01 * scale
    for n in (2, 4, 8, 12, 16, 24, 32):
        beat(f"D n={n}")
        try:
            rng = np.random.default_rng(42)
            G_true, lm_obs, eval_pts = build_controlled_chain(
                base_sid, n, rng, bio_jitter=0.01)
            # pairwise: measure adjacent + chain
            t0 = time.perf_counter()
            adj = band_pairs(n, 1)
            e_adj = measure_edges(lm_obs, adj, rng, sev_noise)
            _ = pairwise_chain_poses(n, e_adj)
            rt_pair = time.perf_counter() - t0
            emit(writer, fh, experiment="runtime", method="pairwise_chain",
                 chain_len=n, edge_band=1, metric="wall_s", value=rt_pair,
                 n_edges=len(e_adj))
            # global band-3
            for band, tag in [(3, "global_band3"), (n - 1, "global_full")]:
                t0 = time.perf_counter()
                pr = band_pairs(n, band)
                e = measure_edges(lm_obs, pr, rng, sev_noise)
                _ = global_solve(n, e, irls_iters=3)
                rt = time.perf_counter() - t0
                emit(writer, fh, experiment="runtime", method=tag, chain_len=n,
                     edge_band=band, metric="wall_s", value=rt, n_edges=len(e))
        except Exception as ex:
            log(f"  D FAIL n={n}: {ex}")
            log(traceback.format_exc())
    log("Experiment D done.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log("################ global_recon run start ################")
    beat("starting")
    fh, writer = csv_init()
    try:
        seeds = list(range(5))                 # 5 seeds
        chain_lens = [2, 4, 8, 12]
        severities = [1, 3, 5]                 # % of tissue radius
        exp_controlled(writer, fh, seeds, chain_lens, severities)
        exp_real(writer, fh, seeds, severities)
        exp_robustness(writer, fh, seeds)
        exp_gate(writer, fh, seeds)
        exp_runtime(writer, fh)
    except Exception as ex:
        log(f"FATAL: {ex}")
        log(traceback.format_exc())
    finally:
        fh.close()
        beat("done")
        log("################ global_recon run end ################")


if __name__ == "__main__":
    main()
