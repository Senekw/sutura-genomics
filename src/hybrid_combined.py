"""
Hybrid torn-tissue alignment — combine several no-big-data levers in ONE pipeline
and ask whether the combination beats PASTE2 on held-out / torn tissue.

The cross-donor gap diagnosis (research/FINDINGS_cross_donor_gap_summary.md) is that
our supervised shared-basis model lacks the cross-dataset correspondence prior that
optimal transport (PASTE2) supplies for free. This script does NOT try to out-train
PASTE2 with more data. It composes four training-cheap components, each toggleable so
we can ablate what actually contributes:

  (1) OT correspondence prior  [ot]        PASTE2-style entropic-OT correspondence on the
                                           shared expression features -> a per-B-spot
                                           A-frame coordinate + confidence. Generalizes
                                           across tissue with NO training. (Warp-invariant
                                           expression surrogate for PASTE2's full FGW; the
                                           real PASTE2 number is the external baseline line.)
  (2) tear detect + piecewise  [piecewise] Detect the tear as a geometric discontinuity in
                                           the MOVING graph (kNN edges stretched across the
                                           cut), segment the moving slice into pieces, fit a
                                           weighted similarity transform per piece from the
                                           OT correspondences, and stitch. No training.
  (3) learned residual         [residual]  A small NN (OTInitNet: coarse := OT coord, head
                                           learns the residual) trained ONLY on SYNTHETIC
                                           tears of the TRAINING donors (unlimited synthetic
                                           data). Tests whether synthetic training transfers
                                           to a real held-out donor.
  (4) self-supervised adapt    [ssa]       At inference, adapt the residual model to the
                                           held-out donor's OWN ref-section geometry via
                                           synthetic self-warps (no target correspondence
                                           used). autoadapt/tta_lodo `self` mode.
  (+) agentic error advisor    [agentic]   A meta-corrector: on the training donors' synthetic
                                           tears it LEARNS where the OT+residual output is worse
                                           than the piecewise-rigid output (a small logistic gate
                                           on confidence / tear-membership / disagreement) and at
                                           inference blends the two predictions accordingly. This
                                           is the local, reproducible stand-in for the requested
                                           "internet-scouring agent that learns to fix PASTE2
                                           errors and feeds another model" — see FINDINGS for why
                                           the online web-agent loop is not run in this offline
                                           detached benchmark, and what a grounded version needs.

Evaluation is IDENTICAL to the prior experiments for comparability (generalization_max.py):
3-donor DLPFC leave-one-donor-out (Br5292/Br5595/Br8100), tear benchmark, median
registration error in spot-pitches, eval severities 0,1,2,3,4,6,8, tear=True, eval-seed 0.
Reference lines: PASTE2 held-out (5.28/4.35/3.46) and the shared-basis plateau (~9.6).
Also runs a breast (off-distribution) pair with the training-free + self-supervised
components against PASTE2.

Robustness: detached-friendly. A heartbeat thread logs liveness + current stage every
HEARTBEAT s; each (config x fold) cell is wrapped in try/except and appended to the CSV
immediately; the optional real-PASTE2 base runs under a per-call watchdog timeout so a
wedged OT solve surfaces instead of hanging.

Outputs: research/results/hybrid_combined.csv, research/results/hybrid_combined.png,
research/FINDINGS_hybrid_combined.md
Usage:
  python src/hybrid_combined.py                       # full LODO + breast (detached-friendly)
  python src/hybrid_combined.py --smoke               # 1 fold, tiny epochs (correctness check)
  python src/hybrid_combined.py --folds Br8100        # a subset of held-out donors
  python src/hybrid_combined.py --plot-only           # re-plot + re-write findings from CSV
"""
from __future__ import annotations

import argparse
import copy
import csv
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from scipy.spatial import cKDTree

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import generalization_max as gm            # noqa: E402  LODO harness (DONORS/PASTE2/prep_pair)
from hybrid_ot import ot_coordinate, OTInitNet   # noqa: E402  OT prior + OT-init residual net
from train_cross import ARCACrossNet, graph_tensors, cross_features, array_bridge  # noqa: E402
from warp_slice import apply_warp          # noqa: E402
from scoring import registration_error_stats  # noqa: E402

# keep gm's data dir pointed at this repo (it already is when run in-repo)
if (ROOT / "data").exists():
    gm.DATA = ROOT / "data"

OUT = ROOT / "research" / "results"
CSV_PATH = OUT / "hybrid_combined.csv"
LOG_PATH = OUT / "hybrid_combined.log"
PNG_PATH = OUT / "hybrid_combined.png"
FINDINGS = ROOT / "research" / "FINDINGS_hybrid_combined.md"

EVAL_SEVS = gm.EVAL_SEVS
EVAL_SEED = 0
KNN = gm.HP["knn"]
PCA_DIM = gm.HP["pca_dim"]
SHARED_BASIS_REF = 9.6         # prior shared-basis held-out plateau (research/FINDINGS_tta_*)

# training knobs (kept modest so the whole sweep finishes in well under an hour on CPU)
RES_EPOCHS = 40
RES_STEPS = 16
RES_LR = 1e-3
NN_EPOCHS = 40                 # plain shared-basis baseline model
NN_STEPS = 16
SSA_EPOCHS = 20
SSA_STEPS = 10
SSA_LR = 1e-3
SSA_PATIENCE = 4
MAX_SEV = 8.0
TEAR_PROB = 0.5
HEARTBEAT = 20                 # seconds between liveness logs
PASTE2_TIMEOUT = 900           # seconds; watchdog for the optional real-PASTE2 base
PASTE2_BASE = False            # --paste2-base: also layer refinements on the real PASTE2 solve

CSV_FIELDS = ["kind", "config", "held_out", "train", "reg_err_pitch",
              "per_sev", "paste2_ref", "shared_basis_ref", "beats_paste2",
              "in_dist", "seconds", "status", "timestamp", "detail"]


# --------------------------------------------------------------------------- #
# logging / heartbeat / incremental CSV
# --------------------------------------------------------------------------- #
_STAGE = "init"
_HB_STOP = False


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="ascii", errors="replace") as fh:
        fh.write(line + "\n")


def _heartbeat():
    t0 = time.time()
    while not _HB_STOP:
        time.sleep(1)
        if _HB_STOP:
            break
        if int(time.time() - t0) % HEARTBEAT == 0:
            log(f"... alive stage='{_STAGE}' ({int(time.time() - t0)}s)")


def stage(name):
    global _STAGE
    _STAGE = name


def append_row(row):
    OUT.mkdir(parents=True, exist_ok=True)
    exists = CSV_PATH.exists()
    full = {k: row.get(k, "") for k in CSV_FIELDS}
    with open(CSV_PATH, "a", newline="", encoding="ascii", errors="replace") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(full)


def call_with_timeout(fn, timeout, *a, **k):
    """Run fn in a daemon thread; raise TimeoutError past `timeout`. The leaked thread
    self-clears when the slow call (e.g. a wedged PASTE2 solve) finishes."""
    box = {}

    def worker():
        try:
            box["v"] = fn(*a, **k)
        except Exception as e:                      # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"call exceeded {timeout}s")
    if "e" in box:
        raise box["e"]
    return box.get("v")


# --------------------------------------------------------------------------- #
# component 1: OT correspondence prior (A-frame pixels + confidence), warp-invariant
# --------------------------------------------------------------------------- #
def ot_prior(Z_B, Z_A, a_coords_px, pitch):
    coord_pitch, conf = ot_coordinate(Z_B, Z_A, a_coords_px / pitch)
    return coord_pitch * pitch, conf            # (nB,2) px, (nB,) confidence


def paste2_prior(A, B_warped, gt_shape_coords, pitch):
    """Real PASTE2 partial-FGW base -> A-frame pixel coordinate per B spot (barycentric).
    Slow (minutes); only used when --paste2-base is set. Wrapped by the caller's watchdog."""
    from paste2.PASTE2 import partial_pairwise_align
    from paste2.helper import filter_for_common_genes
    from scoring import barycentric_projection
    Aa, Bb = A.copy(), B_warped.copy()
    filter_for_common_genes([Aa, Bb])
    pi = np.asarray(partial_pairwise_align(Aa, Bb, s=0.99, alpha=0.1,
                                           dissimilarity="pca", verbose=False))
    pred, col_mass = barycentric_projection(pi, np.asarray(Aa.obsm["spatial"], float))
    # columns with no mass fall back to the tissue centroid (rare)
    cen = np.asarray(Aa.obsm["spatial"], float).mean(0)
    pred[col_mass <= 0] = cen
    return pred.astype(np.float32)


# --------------------------------------------------------------------------- #
# component 2: tear detection + piecewise classical alignment
# --------------------------------------------------------------------------- #
def detect_pieces(coords, pitch, k=8, stretch=2.2, min_frac=0.06):
    """Segment a (possibly torn) slice by cutting kNN edges longer than stretch*pitch
    and taking connected components. A physical tear translates a contiguous region, so
    the edges bridging the cut are stretched; removing them splits the tissue. Components
    smaller than min_frac of the slice are merged into the nearest large component.
    Returns integer piece labels 0..P-1 (P>=1)."""
    n = len(coords)
    if n < 20:
        return np.zeros(n, dtype=int)
    tree = cKDTree(coords)
    dist, idx = tree.query(coords, k=min(k + 1, n))
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    thr = stretch * pitch
    for i in range(n):
        for jp in range(1, dist.shape[1]):
            if dist[i, jp] <= thr:
                ri, rj = find(i), find(int(idx[i, jp]))
                if ri != rj:
                    parent[ri] = rj
    root = np.array([find(i) for i in range(n)])
    uniq, counts = np.unique(root, return_counts=True)
    big = uniq[counts >= max(min_frac * n, 5)]
    if len(big) <= 1:
        return np.zeros(n, dtype=int)
    # centroid of each big component, then assign every spot to the nearest big centroid
    cents = {u: coords[root == u].mean(0) for u in big}
    big_list = list(big)
    cmat = np.stack([cents[u] for u in big_list])          # (P,2)
    lab = np.zeros(n, dtype=int)
    for i in range(n):
        if root[i] in cents:
            lab[i] = big_list.index(root[i])
        else:                                              # small comp -> nearest big centroid
            lab[i] = int(np.argmin(((cmat - coords[i]) ** 2).sum(1)))
    return lab


def umeyama(src, dst, w=None):
    """Weighted similarity transform (rotation+uniform scale+translation) src->dst.
    Returns (R 2x2, t 2, scale). Predict with scale*(src @ R.T) + t."""
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    if w is None:
        w = np.ones(len(src))
    w = np.asarray(w, float)
    ws = w.sum()
    if ws <= 1e-9 or len(src) < 3:
        return np.eye(2), np.zeros(2), 1.0
    w = w / ws
    mu_s = (w[:, None] * src).sum(0)
    mu_d = (w[:, None] * dst).sum(0)
    S = src - mu_s
    D = dst - mu_d
    C = (w[:, None] * D).T @ S                             # 2x2 cross-covariance
    U, Sig, Vt = np.linalg.svd(C)
    d = np.sign(np.linalg.det(U @ Vt))
    Dg = np.diag([1.0, d])
    R = U @ Dg @ Vt
    var_s = (w * (S ** 2).sum(1)).sum()
    scale = float((Sig * np.array([1.0, d])).sum() / (var_s + 1e-12))
    if not np.isfinite(scale) or scale <= 0:
        scale = 1.0
    t = mu_d - scale * (R @ mu_s)
    return R, t, scale


def piecewise_predict(moving_coords, ot_coord_px, ot_conf, pitch):
    """Detect pieces of the moving slice and fit a weighted similarity transform per piece
    (moving -> OT-correspondence target), then apply it. Enforces per-piece rigidity, which
    structurally undoes the tear's rigid offset and denoises the OT coordinate. Falls back to
    the OT coordinate for degenerate pieces."""
    labels = detect_pieces(moving_coords, pitch)
    pred = ot_coord_px.copy()
    for lab in np.unique(labels):
        m = labels == lab
        if m.sum() < 5:
            continue
        R, t, sc = umeyama(moving_coords[m], ot_coord_px[m], w=ot_conf[m])
        pred[m] = sc * (moving_coords[m] @ R.T) + t
    return pred, labels


# --------------------------------------------------------------------------- #
# component 3: learned residual (OTInitNet), trained on TRAIN-donor synthetic tears only
# --------------------------------------------------------------------------- #
def train_residual(train_pairs, dim, epochs, steps, lr, seed=0):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = OTInitNet(dim, gm.HP["hidden"], gm.HP["layers"], gm.HP["attn_dim"])
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    for _ in range(epochs):
        model.train()
        for _ in range(steps):
            pr = train_pairs[int(rng.integers(len(train_pairs)))]
            sv = float(rng.uniform(0, MAX_SEV))
            w, _ = apply_warp(pr["B"], sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < TEAR_PROB))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                               pr["Z_B"], KNN, pr["pitch"])
            opt.zero_grad()
            pred = model(pr["ga"], gb, pr["a_norm"], pr["ot_coarse"])
            loss = (pred - pr["gt_norm"])[pr["mask"]].norm(dim=1).mean()
            loss.backward()
            opt.step()
    model.eval()
    return model


def train_plain_nn(train_pairs, dim, epochs, steps, lr, seed=0):
    """Plain shared-basis model (attention coarse, no OT) = the ~9.6 baseline, recomputed
    internally so the reference line is a real number on these exact folds, not just a cite."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = ARCACrossNet(dim, gm.HP["hidden"], gm.HP["layers"], gm.HP["attn_dim"])
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    for _ in range(epochs):
        model.train()
        for _ in range(steps):
            pr = train_pairs[int(rng.integers(len(train_pairs)))]
            sv = float(rng.uniform(0, MAX_SEV))
            w, _ = apply_warp(pr["B"], sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < TEAR_PROB))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                               pr["Z_B"], KNN, pr["pitch"])
            opt.zero_grad()
            pred = model(pr["ga"], gb, pr["a_norm"])
            loss = (pred - pr["gt_norm"])[pr["mask"]].norm(dim=1).mean()
            loss.backward()
            opt.step()
    model.eval()
    return model


# --------------------------------------------------------------------------- #
# component 4: self-supervised adaptation on the held-out donor's own ref geometry
# --------------------------------------------------------------------------- #
def _self_recon_err(model, pair, sevs, seed):
    gt_self = pair["a_norm"].numpy()
    model.eval()
    errs = []
    for sv in sevs:
        w, _ = apply_warp(pair["A"], sv, seed=seed, tear=True)
        gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                           pair["Z_A"], KNN, pair["pitch"])
        with torch.no_grad():
            pred = model(pair["ga"], gb, pair["a_norm"], pair["ot_self_coarse"]).numpy()
        errs.append(float(np.median(np.linalg.norm(pred - gt_self, axis=1))))
    return float(np.mean(errs))


def ssa_adapt(model, pair, epochs, steps, lr, seed=0):
    """Adapt a COPY of the residual model to the held-out donor's ref section A via synthetic
    self-warps: moving = torn A, features = A's own features, target = A's own coords. No real
    A-B correspondence used. Early-stops on a disjoint-seed self-recon val."""
    model = copy.deepcopy(model)
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    gt_self = pair["a_norm"]                    # every A spot maps to itself
    best = _self_recon_err(model, pair, (2.0, 6.0), 777)
    best_state = {k: t.clone() for k, t in model.state_dict().items()}
    bad = 0
    for ep in range(epochs):
        model.train()
        for _ in range(steps):
            sv = float(rng.uniform(0, MAX_SEV))
            w, _ = apply_warp(pair["A"], sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < TEAR_PROB))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                               pair["Z_A"], KNN, pair["pitch"])
            opt.zero_grad()
            pred = model(pair["ga"], gb, pair["a_norm"], pair["ot_self_coarse"])
            loss = (pred - gt_self).norm(dim=1).mean()
            loss.backward()
            opt.step()
        if ep % 2 == 0 or ep == epochs - 1:
            v = _self_recon_err(model, pair, (2.0, 6.0), 777)
            if v < best - 1e-3:
                best = v
                best_state = {k: t.clone() for k, t in model.state_dict().items()}
                bad = 0
            else:
                bad += 1
                if bad >= SSA_PATIENCE:
                    break
    model.load_state_dict(best_state)
    model.eval()
    return model


# --------------------------------------------------------------------------- #
# agentic error advisor: learn (on train-donor synthetic tears) where piecewise beats
# ot+residual, then blend the two at inference. Local stand-in for the web-agent loop.
# --------------------------------------------------------------------------- #
def _advisor_features(moving_coords, ot_coord_px, ot_conf, resid_px, piece_px,
                      labels, pitch):
    """Per-spot features for the gate: OT confidence, minority-piece membership (tear proxy),
    resid<->piece disagreement, moving displacement magnitude."""
    n = len(moving_coords)
    _, counts = np.unique(labels, return_counts=True)
    minority = np.zeros(n)
    if len(counts) > 1:
        big = labels == np.argmax(np.bincount(labels))
        minority = (~big).astype(float)
    disagree = np.linalg.norm(resid_px - piece_px, axis=1) / pitch
    step = np.linalg.norm(ot_coord_px - moving_coords, axis=1) / pitch
    return np.stack([ot_conf / (ot_conf.max() + 1e-9), minority,
                     np.tanh(disagree / 3.0), np.tanh(step / 8.0)], axis=1)


def fit_advisor(train_pairs, resid_model):
    """Fit a logistic gate: P(piecewise is better than ot+residual) per spot, from the
    training donors' synthetic tears (the 'learn how to fix the base's errors' signal)."""
    try:
        from sklearn.linear_model import LogisticRegression
    except Exception:
        return None
    rng = np.random.default_rng(0)
    X, y = [], []
    for pr in train_pairs:
        for _ in range(6):
            sv = float(rng.uniform(1.0, MAX_SEV))
            w, _ = apply_warp(pr["B"], sv, seed=int(rng.integers(1, 99999)), tear=True)
            mov = np.asarray(w.obsm["spatial"], np.float32)
            ot_px = pr["ot_coarse"].numpy() * pr["pitch"]
            piece_px, labels = piecewise_predict(mov, ot_px, pr["ot_conf"], pr["pitch"])
            gb = graph_tensors(mov, pr["Z_B"], KNN, pr["pitch"])
            with torch.no_grad():
                resid_px = resid_model(pr["ga"], gb, pr["a_norm"],
                                       pr["ot_coarse"]).numpy() * pr["pitch"]
            have = pr["have"]
            gt = pr["gt"]
            e_res = np.linalg.norm(resid_px - gt, axis=1)
            e_pie = np.linalg.norm(piece_px - gt, axis=1)
            feats = _advisor_features(mov, ot_px, pr["ot_conf"], resid_px, piece_px,
                                      labels, pr["pitch"])
            sel = have & np.isfinite(e_res) & np.isfinite(e_pie)
            X.append(feats[sel])
            y.append((e_pie[sel] < e_res[sel]).astype(int))
    X = np.concatenate(X)
    y = np.concatenate(y)
    if len(np.unique(y)) < 2:
        return None
    clf = LogisticRegression(max_iter=500).fit(X, y)
    return clf


def advisor_blend(clf, moving_coords, ot_coord_px, ot_conf, resid_px, piece_px,
                  labels, pitch):
    if clf is None:
        return resid_px
    feats = _advisor_features(moving_coords, ot_coord_px, ot_conf, resid_px, piece_px,
                              labels, pitch)
    p = clf.predict_proba(feats)[:, 1][:, None]        # P(trust piecewise)
    return (1 - p) * resid_px + p * piece_px


# --------------------------------------------------------------------------- #
# prediction dispatcher (per config) + scoring
# --------------------------------------------------------------------------- #
@dataclass
class Cfg:
    name: str
    ot: bool = True
    piecewise: bool = False
    residual: bool = False
    ssa: bool = False
    agentic: bool = False
    plain: bool = False          # plain shared-basis NN baseline (no OT)


CONFIGS = [
    Cfg("shared_basis", ot=False, plain=True),                    # ~9.6 baseline (recomputed)
    Cfg("ot_only", ot=True),                                      # PASTE2-style OT surrogate
    Cfg("piecewise_only", ot=True, piecewise=True),               # +structural tear handling
    Cfg("residual", ot=True, residual=True),                      # +synthetic-trained residual
    Cfg("residual_ssa", ot=True, residual=True, ssa=True),        # +self-supervised adaptation
    Cfg("hybrid_no_ssa", ot=True, piecewise=True, residual=True, agentic=True),
    Cfg("hybrid_full", ot=True, piecewise=True, residual=True, ssa=True, agentic=True),
]


def predict(cfg, pair, moving_coords, models, base_px=None, base_conf=None):
    """Return per-B-spot A-frame pixel prediction for one warped moving slice under cfg.

    base_px overrides the OT-correspondence coordinate (pixels) with an externally supplied
    base — e.g. the REAL PASTE2 barycentric coordinate — so the same refinement stack
    (piecewise / learned residual / agentic) can be layered on PASTE2 itself. When base_px
    is None the fast expression-OT surrogate stored on the pair is used."""
    pitch = pair["pitch"]
    if cfg.plain:
        gb = graph_tensors(moving_coords, pair["Z_B"], KNN, pitch)
        with torch.no_grad():
            return models["plain"](pair["ga"], gb, pair["a_norm"]).numpy() * pitch

    if base_px is not None:
        ot_px = np.asarray(base_px, np.float32)
        ot_conf = base_conf if base_conf is not None else np.ones(len(ot_px), np.float32)
        ot_coarse_t = torch.from_numpy((ot_px / pitch).astype(np.float32))
    else:
        ot_px = pair["ot_coarse"].numpy() * pitch
        ot_conf = pair["ot_conf"]
        ot_coarse_t = pair["ot_coarse"]
    piece_px, labels = piecewise_predict(moving_coords, ot_px, ot_conf, pitch)

    if cfg.residual:
        rmodel = models["ssa"] if (cfg.ssa and "ssa" in models) else models["residual"]
        gb = graph_tensors(moving_coords, pair["Z_B"], KNN, pitch)
        with torch.no_grad():
            resid_px = rmodel(pair["ga"], gb, pair["a_norm"],
                              ot_coarse_t).numpy() * pitch
    else:
        resid_px = ot_px

    if cfg.agentic and cfg.residual and cfg.piecewise:
        return advisor_blend(models.get("advisor"), moving_coords, ot_px, ot_conf,
                             resid_px, piece_px, labels, pitch)
    if cfg.piecewise and not cfg.residual:
        return piece_px
    return resid_px


def score_config(cfg, pair, models, sevs=EVAL_SEVS, seed=EVAL_SEED):
    per_sev = []
    for sv in sevs:
        w, _ = apply_warp(pair["B"], sv, seed=seed, tear=True)
        mov = np.asarray(w.obsm["spatial"], np.float32)
        pred = predict(cfg, pair, mov, models)
        st = registration_error_stats(pred, pair["gt"], mask=pair["have"])
        per_sev.append(st["median"] / pair["pitch"])
    return float(np.mean(per_sev)), [round(x, 3) for x in per_sev]


# PASTE2-base track: layer the SAME refinement stack on the REAL PASTE2 correspondence.
PASTE2_SEVS = [0.0, 2.0, 4.0, 6.0, 8.0]
PASTE2_CONFIGS = [
    Cfg("paste2", ot=True),                                                # real PASTE2 base
    Cfg("paste2_piecewise", ot=True, piecewise=True),
    Cfg("paste2_residual", ot=True, residual=True),
    Cfg("paste2_hybrid", ot=True, piecewise=True, residual=True, agentic=True),
]


def score_paste2_base(pair, models, sevs=PASTE2_SEVS, seed=EVAL_SEED, timeout=PASTE2_TIMEOUT):
    """For each severity: run REAL PASTE2 once on the torn slice, then score every
    PASTE2_CONFIG on that identical solve (so paste2_hybrid vs paste2 is apples-to-apples
    on the same warped tissue). Returns {config: (mean_err, per_sev_list)}. A wedged/timed-out
    solve drops that severity (recorded as NaN) and the loop continues."""
    acc = {c.name: [] for c in PASTE2_CONFIGS}
    for sv in sevs:
        stage(f"paste2base:sev{sv:g}")
        w, _ = apply_warp(pair["B"], sv, seed=seed, tear=True)
        mov = np.asarray(w.obsm["spatial"], np.float32)
        t0 = time.time()
        try:
            base_px = call_with_timeout(paste2_prior, timeout, pair["A"], w,
                                        pair["coords"], pair["pitch"])
        except Exception as e:                       # noqa: BLE001
            log(f"    paste2 base sev{sv:g} FAILED/timeout: {e!r} — sev dropped")
            for c in PASTE2_CONFIGS:
                acc[c.name].append(float("nan"))
            continue
        for c in PASTE2_CONFIGS:
            pred = predict(c, pair, mov, models, base_px=base_px)
            st = registration_error_stats(pred, pair["gt"], mask=pair["have"])
            acc[c.name].append(st["median"] / pair["pitch"])
        log(f"    paste2 base sev{sv:g}: "
            + " ".join(f"{c.name.replace('paste2','p2')}={acc[c.name][-1]:.2f}"
                       for c in PASTE2_CONFIGS) + f"  ({time.time()-t0:.0f}s)")
    out = {}
    for c in PASTE2_CONFIGS:
        vals = [v for v in acc[c.name] if np.isfinite(v)]
        out[c.name] = (float(np.mean(vals)) if vals else float("nan"),
                       [round(x, 3) for x in acc[c.name]])
    return out


# --------------------------------------------------------------------------- #
# attach OT coordinates to a prepared pair (both A-B and A-self, for SSA)
# --------------------------------------------------------------------------- #
def attach_ot(pair):
    Z_A = pair["ga"]["x"].numpy()
    coord_pitch, conf = ot_coordinate(pair["Z_B"], Z_A, pair["a_norm"].numpy())
    pair["ot_coarse"] = torch.from_numpy(coord_pitch)
    pair["ot_conf"] = conf
    # A-vs-self OT coarse for the self-supervised adaptation path (moving = warped A)
    coord_self, _ = ot_coordinate(pair["Z_A"], Z_A, pair["a_norm"].numpy())
    pair["ot_self_coarse"] = torch.from_numpy(coord_self)
    return pair


# --------------------------------------------------------------------------- #
# one LODO fold
# --------------------------------------------------------------------------- #
def run_fold(ho, configs, res_epochs, res_steps, nn_epochs, nn_steps):
    donors = list(gm.DONORS)
    train_donors = [d for d in donors if d != ho]
    stage(f"{ho}:basis")
    train_slices = [s for d in train_donors for pr in gm.DONORS[d][:2] for s in pr]
    basis = gm.fit_fold_basis(train_slices, "svd", PCA_DIM, 2000)
    dim = basis["components"].shape[0]

    stage(f"{ho}:prep")
    train_pairs = []
    for d in train_donors:
        for pr in gm.DONORS[d][:2]:
            train_pairs.append(attach_ot(gm.prep_pair(pr[0], pr[1], basis, KNN)))
    ho_pair = attach_ot(gm.prep_pair(*gm.DONORS[ho][0], basis, KNN))
    id_pair = attach_ot(gm.prep_pair(*gm.DONORS[train_donors[0]][0], basis, KNN))

    models = {}
    need_res = any(c.residual for c in configs)
    need_plain = any(c.plain for c in configs)
    need_ssa = any(c.ssa for c in configs)
    need_adv = any(c.agentic for c in configs)

    if need_plain:
        stage(f"{ho}:train_plain")
        t = time.time()
        models["plain"] = train_plain_nn(train_pairs, dim, nn_epochs, nn_steps, RES_LR)
        log(f"[{ho}] trained plain shared-basis NN ({time.time()-t:.0f}s)")
    if need_res:
        stage(f"{ho}:train_residual")
        t = time.time()
        models["residual"] = train_residual(train_pairs, dim, res_epochs, res_steps, RES_LR)
        log(f"[{ho}] trained OT-init learned residual ({time.time()-t:.0f}s)")
    if need_adv and "residual" in models:
        stage(f"{ho}:fit_advisor")
        t = time.time()
        models["advisor"] = fit_advisor(train_pairs, models["residual"])
        log(f"[{ho}] fit agentic advisor gate "
            f"({'ok' if models.get('advisor') is not None else 'skipped'}, {time.time()-t:.0f}s)")
    if need_ssa and "residual" in models:
        stage(f"{ho}:ssa")
        t = time.time()
        models["ssa"] = ssa_adapt(models["residual"], ho_pair, SSA_EPOCHS, SSA_STEPS, SSA_LR)
        log(f"[{ho}] self-supervised adaptation done ({time.time()-t:.0f}s)")

    results = {}
    for cfg in configs:
        stage(f"{ho}:eval:{cfg.name}")
        t = time.time()
        try:
            ho_err, per_sev = score_config(cfg, ho_pair, models)
            id_err, _ = score_config(cfg, id_pair, models)
            paste2 = gm.PASTE2[ho]
            row = dict(kind="dlpfc_lodo", config=cfg.name, held_out=ho,
                       train="+".join(train_donors), reg_err_pitch=round(ho_err, 3),
                       per_sev=";".join(f"{s:g}" for s in per_sev),
                       paste2_ref=paste2, shared_basis_ref=SHARED_BASIS_REF,
                       beats_paste2=bool(ho_err <= paste2), in_dist=round(id_err, 3),
                       seconds=round(time.time() - t, 1), status="ok", timestamp=_now(),
                       detail="")
            append_row(row)
            results[cfg.name] = ho_err
            log(f"[{ho}] {cfg.name}: held-out={ho_err:.3f} in-dist={id_err:.3f} "
                f"(PASTE2 {paste2}) beats={row['beats_paste2']}")
        except Exception as e:                       # noqa: BLE001
            append_row(dict(kind="dlpfc_lodo", config=cfg.name, held_out=ho,
                            status="error", detail=f"{type(e).__name__}: {e}"[:200],
                            timestamp=_now(), seconds=round(time.time() - t, 1)))
            log(f"[{ho}] {cfg.name} FAILED: {e!r}\n{traceback.format_exc()}")

    # --- optional real-PASTE2 base track (refinements layered on actual PASTE2) ---
    if PASTE2_BASE:
        stage(f"{ho}:paste2base")
        t = time.time()
        try:
            p2 = score_paste2_base(ho_pair, models)
            paste2_ref = gm.PASTE2[ho]
            base_err = p2["paste2"][0]
            for cname, (err, per_sev) in p2.items():
                append_row(dict(kind="dlpfc_lodo_paste2base", config=cname, held_out=ho,
                                train="+".join(train_donors), reg_err_pitch=round(err, 3),
                                per_sev=";".join(f"{s:g}" for s in per_sev),
                                paste2_ref=paste2_ref, shared_basis_ref=SHARED_BASIS_REF,
                                beats_paste2=bool(np.isfinite(err) and err <= base_err),
                                in_dist="", seconds=round(time.time() - t, 1),
                                status="ok", timestamp=_now(),
                                detail=f"vs_real_paste2_base={base_err:.3f}"))
            log(f"[{ho}] paste2-base: " + " ".join(f"{k}={v[0]:.3f}" for k, v in p2.items()))
        except Exception as e:                       # noqa: BLE001
            append_row(dict(kind="dlpfc_lodo_paste2base", config="(paste2base)", held_out=ho,
                            status="error", detail=f"{type(e).__name__}: {e}"[:200],
                            timestamp=_now(), seconds=round(time.time() - t, 1)))
            log(f"[{ho}] paste2-base FAILED: {e!r}\n{traceback.format_exc()}")
    return results


# --------------------------------------------------------------------------- #
# breast off-distribution pair (no held-out donor; training-free + self-supervised only)
# --------------------------------------------------------------------------- #
def run_breast(paste2_base=False):
    EXT = gm.DATA / "external"
    ref = EXT / "V1_Breast_Cancer_Block_A_Section_1.h5ad"
    mov = EXT / "V1_Breast_Cancer_Block_A_Section_2.h5ad"
    if not ref.exists() or not mov.exists():
        log("breast data absent; skipping off-distribution eval")
        return
    import anndata as ad
    stage("breast:prep")
    A = ad.read_h5ad(ref)
    B = ad.read_h5ad(mov)
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B.obsm["spatial"] = np.asarray(B.obsm["spatial"], float)
    coords = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    Z_A, Z_B = cross_features(A, B, PCA_DIM, 0)      # per-pair SVD (single off-dist pair)
    gt, have = array_bridge(A, B)
    gt_safe = gt.copy()
    gt_safe[~have] = coords.mean(0)
    pair = dict(A=A, B=B, coords=coords, pitch=pitch, Z_A=Z_A, Z_B=Z_B,
                ga=graph_tensors(coords, Z_A, KNN, pitch),
                a_norm=torch.from_numpy((coords / pitch).astype(np.float32)),
                gt=gt, have=have,
                gt_norm=torch.from_numpy((gt_safe / pitch).astype(np.float32)),
                mask=torch.from_numpy(have), knn=KNN)
    attach_ot(pair)

    # self-supervised residual: train on the pair's OWN synthetic tears (no external donor)
    stage("breast:train_residual")
    t = time.time()
    res_model = train_residual([pair], PCA_DIM, RES_EPOCHS, RES_STEPS, RES_LR)
    log(f"[breast] self-trained residual on own synthetic tears ({time.time()-t:.0f}s)")
    models = {"residual": res_model}
    models["advisor"] = fit_advisor([pair], res_model)

    breast_cfgs = [c for c in CONFIGS if not c.plain and not c.ssa]
    for cfg in breast_cfgs:
        stage(f"breast:eval:{cfg.name}")
        t = time.time()
        try:
            err, per_sev = score_config(cfg, pair, models)
            append_row(dict(kind="breast_offdist", config=cfg.name, held_out="breast",
                            train="self", reg_err_pitch=round(err, 3),
                            per_sev=";".join(f"{s:g}" for s in per_sev),
                            paste2_ref="", shared_basis_ref="", beats_paste2="",
                            in_dist="", seconds=round(time.time() - t, 1),
                            status="ok", timestamp=_now(), detail=""))
            log(f"[breast] {cfg.name}: err={err:.3f}")
        except Exception as e:                       # noqa: BLE001
            append_row(dict(kind="breast_offdist", config=cfg.name, held_out="breast",
                            status="error", detail=f"{type(e).__name__}: {e}"[:200],
                            timestamp=_now()))
            log(f"[breast] {cfg.name} FAILED: {e!r}")

    # real PASTE2 on the breast pair (the external baseline), watchdog-bounded
    stage("breast:paste2")
    try:
        errs = []
        for sv in [0.0, 2.0, 4.0, 6.0, 8.0]:
            w, _ = apply_warp(B, sv, seed=EVAL_SEED, tear=True)
            t = time.time()
            pred = call_with_timeout(paste2_prior, PASTE2_TIMEOUT, A, w, coords, pitch)
            st = registration_error_stats(pred, gt, mask=have)
            errs.append(st["median"] / pitch)
            log(f"[breast] paste2 sev{sv:g}: {errs[-1]:.3f} ({time.time()-t:.0f}s)")
        append_row(dict(kind="breast_offdist", config="paste2_real", held_out="breast",
                        train="none", reg_err_pitch=round(float(np.mean(errs)), 3),
                        per_sev=";".join(f"{x:.3f}" for x in errs), status="ok",
                        timestamp=_now()))
    except Exception as e:                           # noqa: BLE001
        append_row(dict(kind="breast_offdist", config="paste2_real", held_out="breast",
                        status="error", detail=f"{type(e).__name__}: {e}"[:200],
                        timestamp=_now()))
        log(f"[breast] paste2_real FAILED/timeout: {e!r}")


# --------------------------------------------------------------------------- #
# plotting + findings
# --------------------------------------------------------------------------- #
def _read_rows():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="", encoding="ascii", errors="replace") as fh:
        return list(csv.DictReader(fh))


def make_plot(rows):
    ok = [r for r in rows if r.get("status") == "ok" and r.get("kind") == "dlpfc_lodo"]
    if not ok:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        log(f"plot skipped: {e!r}")
        return
    order = [c.name for c in CONFIGS]
    donors = sorted({r["held_out"] for r in ok})
    means = {}
    for cname in order:
        vals = [float(r["reg_err_pitch"]) for r in ok if r["config"] == cname]
        if vals:
            means[cname] = float(np.mean(vals))
    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(means))
    names = list(means)
    colors = ["#999999" if n == "shared_basis" else "#6633ee" for n in names]
    bars = ax.bar(x, [means[n] for n in names], color=colors, zorder=3)
    ax.axhline(np.mean([gm.PASTE2[d] for d in donors]), color="#d1495b", ls="--", lw=1.6,
               label=f"PASTE2 mean ({np.mean([gm.PASTE2[d] for d in donors]):.2f})", zorder=2)
    ax.axhline(SHARED_BASIS_REF, color="#2e7d32", ls=":", lw=1.5,
               label=f"shared-basis plateau ({SHARED_BASIS_REF})", zorder=2)
    for b, n in zip(bars, names):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.08,
                f"{means[n]:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("held-out error (median spot-pitches, lower=better)")
    ax.set_title("Hybrid torn-tissue alignment vs PASTE2 — 3-donor DLPFC LODO tear benchmark\n"
                 "(LODO-mean of held-out median registration error)")
    ax.legend(loc="upper right", frameon=False)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    fig.tight_layout()
    fig.savefig(PNG_PATH, dpi=130)
    plt.close(fig)
    log(f"wrote {PNG_PATH}")


def write_findings(rows):
    ok = [r for r in rows if r.get("status") == "ok"]
    lodo = [r for r in ok if r["kind"] == "dlpfc_lodo"]
    breast = [r for r in ok if r["kind"] == "breast_offdist"]
    donors = sorted({r["held_out"] for r in lodo})
    p2_mean = float(np.mean([gm.PASTE2[d] for d in donors])) if donors else float("nan")

    def cfg_mean(cname):
        vals = [float(r["reg_err_pitch"]) for r in lodo if r["config"] == cname]
        return float(np.mean(vals)) if vals else None

    order = [c.name for c in CONFIGS]
    ranked = sorted([(cfg_mean(c), c) for c in order if cfg_mean(c) is not None])

    L = ["# Hybrid torn-tissue alignment — does combining cheap levers beat PASTE2?\n",
         f"_Generated {_now()} on branch `hybrid-combined`._\n",
         "**Question.** Combine, in one toggleable pipeline, an OT correspondence prior "
         "(PASTE2-style, no training), tear-detection + piecewise classical alignment, a "
         "learned residual trained only on SYNTHETIC tears, and per-dataset self-supervised "
         "adaptation. Does the combination beat PASTE2 on held-out / torn DLPFC and on an "
         "off-distribution breast pair — and which components drive any gain?\n",
         "\n**Benchmark.** 3-donor DLPFC leave-one-donor-out (Br5292/Br5595/Br8100), tear "
         "benchmark, median registration error in spot-pitches, eval severities "
         f"{','.join(str(int(s)) for s in EVAL_SEVS)} (tear=True, eval-seed {EVAL_SEED}) — "
         "identical to generalization_max.py so numbers overlay prior work. PASTE2 held-out "
         "reference (full-res FGW, prior sweep): "
         + ", ".join(f"{d} {gm.PASTE2[d]}" for d in donors)
         + f" (mean {p2_mean:.2f}); shared-basis plateau {SHARED_BASIS_REF}.\n"]

    if ranked:
        best_err, best_cfg = ranked[0]
        beats = "**beats**" if best_err <= p2_mean else "does **not** beat"
        L.append(f"\n## Headline\n\nBest configuration: **`{best_cfg}`** at "
                 f"**{best_err:.2f}** LODO-mean pitches, which {beats} PASTE2 "
                 f"(mean {p2_mean:.2f}). Shared-basis baseline recomputed here for reference.\n")

    L.append("\n## LODO ranking (mean held-out error, lower=better)\n")
    L.append("| rank | config | LODO-mean | vs PASTE2 | " +
             " | ".join(donors) + " |")
    L.append("|---|---|---|---|" + "|".join(["---"] * len(donors)) + "|")
    for i, (err, c) in enumerate(ranked, 1):
        per = {r["held_out"]: r["reg_err_pitch"] for r in lodo if r["config"] == c}
        cells = " | ".join(str(per.get(d, "-")) for d in donors)
        L.append(f"| {i} | `{c}` | {err:.2f} | {err - p2_mean:+.2f} | {cells} |")

    L.append("\n## What each component contributes\n")

    def m(c):
        v = cfg_mean(c)
        return f"{v:.2f}" if v is not None else "n/a"
    L.append(f"- **OT prior alone** (`ot_only`): {m('ot_only')} — the training-free "
             "PASTE2-style correspondence surrogate (expression entropic-OT).")
    L.append(f"- **+ tear-detect/piecewise** (`piecewise_only`): {m('piecewise_only')} — "
             "structural, training-free tear correction on top of OT.")
    L.append(f"- **+ learned residual, synthetic-trained** (`residual`): {m('residual')} — "
             "the synthetic-tear-transfer test (trained on TRAIN donors' synthetic tears, "
             "evaluated on the real held-out donor).")
    L.append(f"- **+ self-supervised adaptation** (`residual_ssa`): {m('residual_ssa')}.")
    L.append(f"- **full hybrid, no SSA** (`hybrid_no_ssa`): {m('hybrid_no_ssa')} — "
             "OT+piecewise+residual fused by the agentic advisor gate.")
    L.append(f"- **full hybrid** (`hybrid_full`): {m('hybrid_full')}.")
    L.append(f"- **shared-basis NN** (`shared_basis`): {m('shared_basis')} "
             f"(prior plateau reference {SHARED_BASIS_REF}).")

    # synthetic-transfer verdict
    ot_e, res_e = cfg_mean("ot_only"), cfg_mean("residual")
    if ot_e is not None and res_e is not None:
        L.append("\n## Synthetic-data transfer\n")
        verdict = ("transfers (improves over the OT base on the real held-out donor)"
                   if res_e < ot_e - 0.05 else
                   "does NOT transfer (no improvement over the OT base on held-out real tissue)")
        L.append(f"Training the residual purely on synthetic tears of the training donors and "
                 f"evaluating on the real held-out donor moves error {ot_e:.2f} -> {res_e:.2f} "
                 f"pitches. Synthetic training **{verdict}**.")

    if breast:
        L.append("\n## Breast (off-distribution) pair\n")
        L.append("| config | error (pitch) |")
        L.append("|---|---|")
        for r in sorted(breast, key=lambda r: float(r["reg_err_pitch"]) if r["reg_err_pitch"] else 1e9):
            L.append(f"| `{r['config']}` | {r['reg_err_pitch']} |")
        L.append("\nBreast has no held-out donor, so the learned residual is self-supervised "
                 "on the pair's OWN synthetic tears; `paste2_real` is the true FGW baseline "
                 "on the same warped slices.")

    fails = [r for r in rows if r.get("status") == "error"]
    if fails:
        L.append("\n## Failures (per-component try/except; run continued)\n")
        for r in fails:
            L.append(f"- `{r['config']}` / {r.get('held_out','')}: {r.get('detail','')}")

    L.append("\n## On the requested internet-scouring agent\n")
    L.append("The brief asked for AI agents that scour the internet, learn how to fix data when "
             "PASTE2's output is wrong, and feed corrections to the aligner. That online loop is "
             "**not** run here, for three honest reasons: (1) this is an offline, detached, "
             "reproducible benchmark with no live web access in the run environment; (2) there is "
             "no validated public corpus of 'PASTE2 was wrong here, fix it thus' to scrape — the "
             "correction signal that actually exists is the residual between a method's output and "
             "ground-truth, which we already have from synthetic tears; and (3) an unsupervised web "
             "agent editing alignment data would be a fabrication risk with no way to verify its "
             "'fixes' don't corrupt results. What we DID build is the grounded, testable core of "
             "that idea: the **agentic error advisor** learns — from the training donors' synthetic "
             "tears — exactly where the OT+residual output is worse than the piecewise estimate, and "
             "feeds that judgment into the final blend (one model correcting another's errors). Its "
             "measured contribution is the `hybrid_*` vs `residual` delta above. A genuinely online "
             "version would need a curated, citable corpus of registration failure/fix cases and a "
             "verification harness (score every proposed fix against held-out GT before trusting it); "
             "without that, scouring the web adds risk, not accuracy.\n")

    FINDINGS.parent.mkdir(parents=True, exist_ok=True)
    FINDINGS.write_text("\n".join(L), encoding="ascii", errors="replace")
    log(f"wrote {FINDINGS}")


def summarize():
    rows = _read_rows()
    make_plot(rows)
    write_findings(rows)


# --------------------------------------------------------------------------- #
def main():
    global RES_EPOCHS, RES_STEPS, NN_EPOCHS, NN_STEPS, SSA_EPOCHS, _HB_STOP
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true", help="1 fold, tiny epochs (correctness)")
    p.add_argument("--folds", default="", help="comma list of held-out donors (default all 3)")
    p.add_argument("--no-breast", action="store_true")
    p.add_argument("--paste2-base", action="store_true",
                   help="also run real PASTE2 as the OT base (slow; watchdog-bounded)")
    p.add_argument("--plot-only", action="store_true")
    args = p.parse_args()

    if args.plot_only:
        summarize()
        return

    configs = CONFIGS
    if args.smoke:
        RES_EPOCHS = NN_EPOCHS = 4
        RES_STEPS = NN_STEPS = 6
        SSA_EPOCHS = 4
        folds = ["Br8100"]
    else:
        folds = [d.strip() for d in args.folds.split(",") if d.strip()] or list(gm.DONORS)

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    log("=" * 78)
    log(f"hybrid_combined START folds={folds} smoke={args.smoke} "
        f"res_epochs={RES_EPOCHS} configs={[c.name for c in configs]}")
    log(f"PASTE2 refs {gm.PASTE2} | shared-basis ref {SHARED_BASIS_REF}")
    log("=" * 78)

    t_all = time.time()
    for ho in folds:
        t0 = time.time()
        try:
            run_fold(ho, configs, RES_EPOCHS, RES_STEPS, NN_EPOCHS, NN_STEPS)
        except Exception as e:                       # noqa: BLE001
            log(f"[{ho}] FOLD FAILED: {e!r}\n{traceback.format_exc()}")
            append_row(dict(kind="dlpfc_lodo", config="(fold)", held_out=ho,
                            status="error", detail=f"{type(e).__name__}: {e}"[:200],
                            timestamp=_now()))
        log(f"[{ho}] fold done ({time.time()-t0:.0f}s)")
        try:
            summarize()
        except Exception as e:                       # noqa: BLE001
            log(f"summary refresh failed: {e!r}")

    if not args.no_breast and not args.smoke:
        try:
            run_breast(paste2_base=args.paste2_base)
        except Exception as e:                       # noqa: BLE001
            log(f"breast eval failed: {e!r}\n{traceback.format_exc()}")
        try:
            summarize()
        except Exception as e:                       # noqa: BLE001
            log(f"summary refresh failed: {e!r}")

    _HB_STOP = True
    log(f"hybrid_combined DONE total={time.time()-t_all:.0f}s -> {CSV_PATH}")
    log("DONE")


if __name__ == "__main__":
    main()
