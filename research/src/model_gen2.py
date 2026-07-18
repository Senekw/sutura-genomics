"""
model-gen-2 : can a LEARNED correction beat the hand-designed gate on torn tissue?

Context (from research/FINDINGS_hybrid_combined.md and the cross-donor gap work):
  * The supervised absolute-coordinate model does NOT generalize to a held-out donor
    (~9 spot-pitches; the plain shared-basis plateau).
  * PASTE2 (optimal-transport correspondence) generalizes for free: ~4.4 pitch LODO.
  * The GATE -- a fit-residual-gated per-piece rigid refinement layered ON PASTE2 --
    BEATS PASTE2 (~3.7 pitch LODO, wins all 3 folds). It works because it is a
    CORRECTION expressed in BASE-RELATIVE geometry (per-piece rigid-fit residual),
    not an absolute prediction, so it transfers across donors.
  * A learned residual using ABSOLUTE / expression features, trained on one base and
    applied on PASTE2, was catastrophic (~13 pitch) -- it destroyed PASTE2's output.

Hypothesis this script tests systematically: corrections generalize, absolute
predictions don't -- so a LEARNED corrector restricted to BASE-RELATIVE features
(piece rigid-fit residual, confidence, local base-field geometry) should transfer from
a cheap training base (the expression-OT surrogate, computed with NO real PASTE2) to the
real PASTE2 base at inference, and might beat the hand-tuned gate. We also run the
requested comparators honestly, including the ones expected to fail:

  Families (each a `Corrector`):
    base_ot / base_paste2   : the raw base (reference rows; no correction).
    hand_gate               : the deployed fit-residual gate (GATE_THR/GATE_SCALE), no training.
    learned_gate            : LEARNED per-piece blend (logistic on base-relative piece feats).
    learned_gate_mlp        : same, small MLP (nonlinear blend).
    piece_affine            : LEARNED per-piece correction to the rigid fit (piece-aware arch).
    resid_georel[_L1/L2/Huber][_d{2,3,4}][_dr{none,mod,agg}]
                            : per-spot MLP residual on the base, BASE-RELATIVE features only.
    resid_georel_expr       : + expression features (does expression help or hurt the correction?).
    resid_expr              : prior-style expression+attention residual (expected to fail -- ablation).
    resid_expr_contrastive  : + InfoNCE aligning attention to OT couplings (correspondence prior).
    gate_then_resid         : ENSEMBLE -- learned base-relative residual on top of the gated base.
    learned_gate_then_resid : ENSEMBLE -- learned residual on top of the learned gate.

  Bases evaluated: the expression-OT surrogate (`ot`, free, warp-invariant, weak ~11) and
  the REAL PASTE2 barycentric coordinate (`paste2`, cached per (fold,severity,seed)). The
  gate's 3.7 and PASTE2's 4.4 both live on the `paste2` base, so `paste2` is where a real
  "beat the gate" claim must be made; `ot` is reported as a transfer sanity check.

Benchmark: 3-donor DLPFC leave-one-donor-out (Br5292/Br5595/Br8100), tear=True, >=3 seeds,
median registration error in spot-pitches, identical prep to generalization_max.py.

Leakage discipline (audited in write-up): the fold basis, every trained corrector, the
learned gate, and the advisor are fit ONLY on the two TRAIN donors' synthetic tears. No
ground-truth correspondence, no test warp, and no held-out coordinate ever enters training
or the base. The eval warp seed is disjoint from any training seed stream. PASTE2 is run on
the test slice at inference only (as a baseline/base), never used to supervise anything.

Robustness: detached-friendly. Heartbeat thread logs liveness+stage every HEARTBEAT s. Each
(config x fold x seed) cell is wrapped in try/except and appended to the CSV immediately.
Real PASTE2 solves run under a per-call watchdog and are cached to disk so reruns are cheap
and one wedged solve drops a single severity instead of hanging the run.

Outputs: research/results/model_gen2.csv, research/results/model_gen2.png,
research/FINDINGS_model_gen2.md
Usage:
  python research/src/model_gen2.py                 # full sweep (detached-friendly)
  python research/src/model_gen2.py --smoke          # 1 fold/1 seed, tiny epochs, no PASTE2
  python research/src/model_gen2.py --no-paste2      # OT base only (skip real PASTE2)
  python research/src/model_gen2.py --folds Br8100 --seeds 0
  python research/src/model_gen2.py --plot-only      # re-plot + re-write findings from CSV
"""
from __future__ import annotations

import argparse
import csv
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from scipy.spatial import cKDTree

# --------------------------------------------------------------------------- #
# paths: import the existing harness from arca/src READ-ONLY (never modified)
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve()
RESEARCH = HERE.parent.parent           # arca/research
ROOT = RESEARCH.parent                  # arca/
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import generalization_max as gm                       # noqa: E402
from hybrid_ot import ot_coordinate                   # noqa: E402
from train_cross import ARCACrossNet, graph_tensors   # noqa: E402
from warp_slice import apply_warp                      # noqa: E402
from scoring import registration_error_stats, barycentric_projection  # noqa: E402

gm.DATA = ROOT / "data"

OUT = RESEARCH / "results"
CSV_PATH = OUT / "model_gen2.csv"
LOG_PATH = OUT / "model_gen2.log"
PNG_PATH = OUT / "model_gen2.png"
CACHE_DIR = OUT / "model_gen2_paste2cache"
FINDINGS = RESEARCH / "FINDINGS_model_gen2.md"

KNN = gm.HP["knn"]
PCA_DIM = gm.HP["pca_dim"]
PASTE2_EXTREF = float(np.mean(list(gm.PASTE2.values())))   # ~4.36, the "PASTE2 4.3" line
GATE_THR = 4.5           # deployed hand-gate params (from hybrid_combined, mechanism-set)
GATE_SCALE = 1.0

# eval severity grids: OT base is free (full grid); PASTE2 base is cached (lean grid)
OT_SEVS = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
PASTE2_SEVS = [0.0, 2.0, 4.0, 6.0, 8.0]
MAX_SEV = 8.0
TEAR_PROB = 0.6
HEARTBEAT = 60
PASTE2_TIMEOUT = 900
CONFIG_TIMEOUT = 1800    # per (config x fold x seed) soft budget for training+eval

# training knobs (kept modest so the whole sweep finishes overnight on CPU)
RES_EPOCHS = 35
RES_STEPS = 16
RES_LR = 1e-3

CSV_FIELDS = ["kind", "base", "config", "held_out", "seed", "reg_err_pitch", "per_sev",
              "base_err", "gate_err", "paste2_extref", "beats_base", "beats_gate",
              "seconds", "status", "timestamp", "detail"]

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


def stage(name):
    global _STAGE
    _STAGE = name


def _heartbeat():
    t0 = time.time()
    while not _HB_STOP:
        time.sleep(1)
        if _HB_STOP:
            break
        el = int(time.time() - t0)
        if el % HEARTBEAT == 0 and el > 0:
            log(f"... alive stage='{_STAGE}' ({el}s)")


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
    box = {}

    def worker():
        try:
            box["v"] = fn(*a, **k)
        except Exception as e:                       # noqa: BLE001
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
# piece detection + weighted similarity transform (copied from hybrid_combined so
# this file is self-contained and never imports/mutates the src/ pipeline)
# --------------------------------------------------------------------------- #
def detect_pieces(coords, pitch, k=8, stretch=2.2, min_frac=0.06):
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
    cents = {u: coords[root == u].mean(0) for u in big}
    big_list = list(big)
    cmat = np.stack([cents[u] for u in big_list])
    lab = np.zeros(n, dtype=int)
    for i in range(n):
        if root[i] in cents:
            lab[i] = big_list.index(root[i])
        else:
            lab[i] = int(np.argmin(((cmat - coords[i]) ** 2).sum(1)))
    return lab


def umeyama(src, dst, w=None):
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
    C = (w[:, None] * D).T @ S
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


def piece_fit(moving, base_px, conf, pitch):
    """Per detected piece, fit a weighted similarity transform moving->base. Return
    labels, the per-spot rigid-fitted point `fit_px`, and per-spot fit residual (pitch)."""
    labels = detect_pieces(moving, pitch)
    fit_px = base_px.copy()
    res_pitch = np.zeros(len(moving), np.float32)
    for lab in np.unique(labels):
        m = labels == lab
        if m.sum() < 5:
            res_pitch[m] = 0.0
            continue
        R, t, sc = umeyama(moving[m], base_px[m], w=conf[m])
        f = sc * (moving[m] @ R.T) + t
        fit_px[m] = f
        res_pitch[m] = float(np.median(np.linalg.norm(f - base_px[m], axis=1)) / pitch)
    return labels, fit_px, res_pitch


def hand_gate_predict(moving, base_px, conf, pitch, thr=GATE_THR, scale=GATE_SCALE):
    """The deployed gate: per piece, logistic blend of rigid fit and base by fit residual."""
    labels, _, _ = piece_fit(moving, base_px, conf, pitch)
    pred = base_px.copy()
    for lab in np.unique(labels):
        m = labels == lab
        if m.sum() < 5:
            continue
        R, t, sc = umeyama(moving[m], base_px[m], w=conf[m])
        fit = sc * (moving[m] @ R.T) + t
        res = float(np.median(np.linalg.norm(fit - base_px[m], axis=1)) / pitch)
        wgt = float(1.0 / (1.0 + np.exp((res - thr) / scale)))
        pred[m] = wgt * fit + (1 - wgt) * base_px[m]
    return pred


# --------------------------------------------------------------------------- #
# base-relative per-spot features (transfer across bases: no absolute coord)
# --------------------------------------------------------------------------- #
def base_rel_features(moving, base_px, conf, pitch, include_expr=None):
    """Per-spot BASE-RELATIVE features (all in pitch units / normalized, no absolute
    position), so a corrector trained on one base transfers to another:
      - base coord relative to its piece centroid                       (2)
      - rigid-fit vector (fit - base)                                   (2)
      - piece fit-residual magnitude (broadcast)                        (1)
      - confidence (row-normalized)                                     (1)
      - local base-field roughness: base minus mean of kNN-in-base      (2)
      - moving coord relative to its piece centroid                     (2)
      - piece size fraction                                             (1)
    Optionally concatenates reduced expression features (include_expr).
    """
    n = len(moving)
    labels, fit_px, res = piece_fit(moving, base_px, conf, pitch)
    feats = np.zeros((n, 11), np.float32)
    # piece centroids (in base and moving frames)
    for lab in np.unique(labels):
        m = labels == lab
        bc = base_px[m].mean(0)
        mc = moving[m].mean(0)
        feats[m, 0:2] = (base_px[m] - bc) / pitch
        feats[m, 7:9] = (moving[m] - mc) / pitch
        feats[m, 10] = m.sum() / n
    feats[:, 2:4] = (fit_px - base_px) / pitch
    feats[:, 4] = res
    c = conf / (conf.max() + 1e-9)
    feats[:, 5] = c
    # local base-field roughness on the moving kNN graph (captures base noise / warp)
    tree = cKDTree(moving)
    _, idx = tree.query(moving, k=min(7, n))
    nbr_mean = base_px[idx].mean(1)
    feats[:, 6] = np.linalg.norm(base_px - nbr_mean, axis=1) / pitch
    feats[:, 9] = np.tanh(np.linalg.norm(moving - base_px, axis=1) / (8 * pitch))
    if include_expr is not None:
        feats = np.concatenate([feats, include_expr.astype(np.float32)], axis=1)
    return feats, labels, fit_px, res


# --------------------------------------------------------------------------- #
# learned correctors
# --------------------------------------------------------------------------- #
class MLPResidual(torch.nn.Module):
    """Per-spot residual on the base coordinate from base-relative features."""

    def __init__(self, in_dim, hidden=64, depth=3):
        super().__init__()
        layers = [torch.nn.Linear(in_dim, hidden), torch.nn.ReLU()]
        for _ in range(depth - 2):
            layers += [torch.nn.Linear(hidden, hidden), torch.nn.ReLU()]
        layers += [torch.nn.Linear(hidden, 2)]
        self.net = torch.nn.Sequential(*layers)

    def forward(self, feats):
        return self.net(feats)          # residual in pitch units


class ContrastiveNet(ARCACrossNet):
    """Expression+attention residual on a supplied base coord, exposing attention logits
    so an InfoNCE loss can pull the model's implicit correspondence toward OT couplings."""

    def forward(self, ga, gb, base_coord, return_match=False):
        z_a = self.encoder(ga["x"], ga["edge_index"], ga["edge_attr"])
        z_b = self.encoder(gb["x"], gb["edge_index"], gb["edge_attr"])
        qb, ka = self.q(z_b), self.k(z_a)
        scores = (qb @ ka.T) * self.scale
        attn = torch.softmax(scores, dim=1)
        attended_za = attn @ self.v(z_a)
        residual = self.head(torch.cat([z_b, attended_za, base_coord], dim=-1))
        pred = base_coord + residual
        if not return_match:
            return pred
        return pred, scores


def _loss_fn(kind):
    if kind == "L2":
        return lambda d: (d ** 2).sum(1).mean()
    if kind == "Huber":
        return lambda d: torch.nn.functional.huber_loss(d, torch.zeros_like(d),
                                                         delta=1.0, reduction="mean") * 2
    return lambda d: d.norm(dim=1).mean()      # L1 (default)


@dataclass
class Corrector:
    name: str
    family: str                          # base | hand_gate | learned_gate | piece_affine
    base: str = "paste2"                 # ot | paste2  (eval base)
    loss: str = "L1"
    depth: int = 3
    dr: str = "mod"                      # none | mod | agg   (domain randomization)
    expr: bool = False                   # add expression features
    contrastive: float = 0.0            # InfoNCE weight (ContrastiveNet only)
    ensemble_on: str = ""               # "" | hand_gate | learned_gate  (residual on top)
    mlp_gate: bool = False              # learned_gate: MLP instead of logistic


# --------------------------------------------------------------------------- #
# synthetic training-tear generator (base = OT surrogate, cheap; DR per config)
# --------------------------------------------------------------------------- #
def synth_tear(pair, rng, cfg):
    """One synthetic training example: warp the TRAIN moving slice, build the (cheap OT)
    base and moving geometry with domain randomization. Returns (moving, base_px, conf,
    Z_B, gt_px, have). GT is the fixed B->A bridge (warp-invariant in A-frame)."""
    sev = float(rng.uniform(0, MAX_SEV))
    tear = bool(rng.random() < TEAR_PROB)
    w, _ = apply_warp(pair["B"], sev, seed=int(rng.integers(1, 99999)), tear=tear)
    moving = np.asarray(w.obsm["spatial"], np.float32).copy()
    base_px = (pair["ot_coarse"].numpy() * pair["pitch"]).astype(np.float32).copy()
    conf = pair["ot_conf"].copy()
    Z = pair["Z_B"].copy()
    pitch = pair["pitch"]
    # mod: expression-space domain randomization only (moving-frame orientation is left
    # intact because the A-frame target/base are fixed and the per-piece rigid fit already
    # solves out global orientation; rotating moving alone would decorrelate the moving-
    # relative features from the fixed A-frame target).
    if cfg.dr in ("mod", "agg"):
        drop = rng.random(Z.shape[1]) < 0.1
        Z[:, drop] = 0.0
        Z = (Z + rng.normal(0, 0.1, Z.shape)).astype(np.float32)
    if cfg.dr == "agg":
        # aggressive: jitter the base to simulate an imperfect (PASTE2-like) base, and add a
        # small global similarity perturbation to moving+base+gt TOGETHER so correspondence
        # is preserved while the network sees varied scene poses.
        base_px = base_px + rng.normal(0, 0.6 * pitch, base_px.shape).astype(np.float32)
        Z = Z * (1 + rng.normal(0, 0.05, Z.shape[1])).astype(np.float32)
        th = rng.uniform(-np.pi, np.pi)
        c, s = np.cos(th), np.sin(th)
        R = np.array([[c, -s], [s, c]], np.float32)
        sc = float(rng.uniform(0.9, 1.1))
        cen = moving.mean(0)
        moving = (sc * (moving - cen) @ R.T + cen).astype(np.float32)
        # rotate the A-frame base+gt about A's centroid by the SAME transform so the learned
        # moving->A-frame correction stays consistent under the augmentation
        acen = base_px.mean(0)
        base_px = (sc * (base_px - acen) @ R.T + acen).astype(np.float32)
        gt = pair["gt"].copy()
        gt = (sc * (gt - acen) @ R.T + acen).astype(np.float32)
        return moving, base_px, conf, Z, gt, pair["have"]
    return moving, base_px, conf, Z, pair["gt"], pair["have"]


# --------------------------------------------------------------------------- #
# training the learned correctors (all supervised on TRAIN-donor synthetic tears only)
# --------------------------------------------------------------------------- #
def train_learned_gate(train_pairs, cfg, seed):
    """Learn P(rigid fit closer to GT than base) per piece from base-relative piece feats.
    Deployable blend = predicted prob. Logistic (default) or small MLP."""
    from sklearn.linear_model import LogisticRegression
    rng = np.random.default_rng(seed)
    X, y = [], []
    for pr in train_pairs:
        for _ in range(8):
            moving, base_px, conf, Z, gt, have = synth_tear(pr, rng, cfg)
            labels, fit_px, res = piece_fit(moving, base_px, conf, pr["pitch"])
            for lab in np.unique(labels):
                m = (labels == lab) & have
                if m.sum() < 5:
                    continue
                e_fit = np.median(np.linalg.norm(fit_px[m] - gt[m], axis=1))
                e_base = np.median(np.linalg.norm(base_px[m] - gt[m], axis=1))
                mm = labels == lab
                pf = np.array([np.median(res[mm]),
                               mm.sum() / len(moving),
                               float(conf[mm].mean() / (conf.max() + 1e-9)),
                               float(np.median(np.linalg.norm(fit_px[mm] - base_px[mm], axis=1))
                                     / pr["pitch"])], np.float32)
                X.append(pf)
                y.append(int(e_fit < e_base))
    X = np.array(X, np.float32)
    y = np.array(y, int)
    if len(np.unique(y)) < 2:
        return None
    if cfg.mlp_gate:
        net = MLPResidual(X.shape[1], hidden=32, depth=3)
        net.net[-1] = torch.nn.Linear(32, 1)     # scalar logit head
        opt = torch.optim.Adam(net.parameters(), lr=5e-3)
        Xt = torch.from_numpy(X)
        yt = torch.from_numpy(y.astype(np.float32))
        for _ in range(300):
            opt.zero_grad()
            logit = net(Xt).squeeze(1)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logit, yt)
            loss.backward()
            opt.step()
        net.eval()
        return ("mlp", net)
    clf = LogisticRegression(max_iter=500).fit(X, y)
    return ("logit", clf)


def _gate_blend(model, moving, base_px, conf, pitch):
    labels, fit_px, res = piece_fit(moving, base_px, conf, pitch)
    pred = base_px.copy()
    for lab in np.unique(labels):
        m = labels == lab
        if m.sum() < 5:
            continue
        R, t, sc = umeyama(moving[m], base_px[m], w=conf[m])
        fit = sc * (moving[m] @ R.T) + t
        pf = np.array([[float(np.median(res[m])),
                        m.sum() / len(moving),
                        float(conf[m].mean() / (conf.max() + 1e-9)),
                        float(np.median(np.linalg.norm(fit - base_px[m], axis=1)) / pitch)]],
                      np.float32)
        if model[0] == "mlp":
            with torch.no_grad():
                wgt = float(torch.sigmoid(model[1](torch.from_numpy(pf)).squeeze()).item())
        else:
            wgt = float(model[1].predict_proba(pf)[0, 1])
        pred[m] = wgt * fit + (1 - wgt) * base_px[m]
    return pred


def train_piece_affine(train_pairs, cfg, seed):
    """Piece-aware: learn a correction to each piece's rigid fit from piece-level features.
    Predicts a small residual translation (pitch) + log-scale applied about the piece centroid."""
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    net = MLPResidual(4, hidden=32, depth=3)
    net.net[-1] = torch.nn.Linear(32, 3)          # (dx, dy, dlog_scale)
    opt = torch.optim.Adam(net.parameters(), lr=RES_LR)
    lf = _loss_fn(cfg.loss)
    for _ in range(RES_EPOCHS):
        net.train()
        for _ in range(RES_STEPS):
            pr = train_pairs[int(rng.integers(len(train_pairs)))]
            moving, base_px, conf, Z, gt, have = synth_tear(pr, rng, cfg)
            labels, fit_px, res = piece_fit(moving, base_px, conf, pr["pitch"])
            feats, tgt, cen_list, msk = [], [], [], []
            for lab in np.unique(labels):
                m = labels == lab
                if m.sum() < 5 or (m & have).sum() < 3:
                    continue
                feats.append([float(np.median(res[m])), m.sum() / len(moving),
                              float(conf[m].mean() / (conf.max() + 1e-9)),
                              float(np.median(np.linalg.norm(fit_px[m] - base_px[m], axis=1))
                                    / pr["pitch"])])
                cen_list.append(fit_px[m].mean(0))
                tgt.append((m, gt, have))
            if not feats:
                continue
            ft = torch.tensor(feats, dtype=torch.float32)
            opt.zero_grad()
            out = net(ft)                                   # (P,3)
            total = 0.0
            nsp = 0
            for i, (m, gtv, hv) in enumerate(tgt):
                mm = m & hv
                cen = torch.tensor(fit_px[m].mean(0), dtype=torch.float32)
                fitp = torch.tensor(fit_px[mm], dtype=torch.float32)
                dscale = torch.exp(out[i, 2].clamp(-0.5, 0.5))
                pred = (fitp - cen) * dscale + cen + out[i, :2] * pr["pitch"]
                gtp = torch.tensor(gtv[mm], dtype=torch.float32)
                total = total + lf((pred - gtp) / pr["pitch"]) * mm.sum()
                nsp += mm.sum()
            if nsp > 0:
                (total / nsp).backward()
                opt.step()
    net.eval()
    return net


def _piece_affine_predict(net, moving, base_px, conf, pitch):
    labels, fit_px, res = piece_fit(moving, base_px, conf, pitch)
    pred = fit_px.copy()
    for lab in np.unique(labels):
        m = labels == lab
        if m.sum() < 5:
            pred[m] = base_px[m]
            continue
        pf = np.array([[float(np.median(res[m])), m.sum() / len(moving),
                        float(conf[m].mean() / (conf.max() + 1e-9)),
                        float(np.median(np.linalg.norm(fit_px[m] - base_px[m], axis=1)) / pitch)]],
                      np.float32)
        with torch.no_grad():
            o = net(torch.from_numpy(pf)).squeeze(0).numpy()
        cen = fit_px[m].mean(0)
        dscale = float(np.exp(np.clip(o[2], -0.5, 0.5)))
        pred[m] = (fit_px[m] - cen) * dscale + cen + o[:2] * pitch
    return pred


def _expr_reduce(Z):
    """Small fixed expression summary (first few SVD dims are already ordered)."""
    return Z[:, :8]


def train_resid(train_pairs, cfg, seed, ex_dim):
    """Per-spot base-relative residual MLP (optionally + expression). Trained on OT-base
    synthetic tears of the TRAIN donors; loss on the fixed B->A bridge (masked)."""
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    in_dim = 11 + (ex_dim if cfg.expr else 0)
    net = MLPResidual(in_dim, hidden=64, depth=cfg.depth)
    opt = torch.optim.Adam(net.parameters(), lr=RES_LR)
    lf = _loss_fn(cfg.loss)
    for _ in range(RES_EPOCHS):
        net.train()
        for _ in range(RES_STEPS):
            pr = train_pairs[int(rng.integers(len(train_pairs)))]
            moving, base_px, conf, Z, gt, have = synth_tear(pr, rng, cfg)
            ex = _expr_reduce(Z) if cfg.expr else None
            feats, _, _, _ = base_rel_features(moving, base_px, conf, pr["pitch"], include_expr=ex)
            ft = torch.from_numpy(feats)
            bt = torch.from_numpy(base_px / pr["pitch"])
            gt_t = torch.from_numpy((gt / pr["pitch"]).astype(np.float32))
            mask = torch.from_numpy(have)
            opt.zero_grad()
            pred = bt + net(ft)
            loss = lf((pred - gt_t)[mask])
            loss.backward()
            opt.step()
    net.eval()
    return net


def _resid_predict(net, moving, base_px, conf, pitch, cfg, Z=None):
    ex = _expr_reduce(Z) if (cfg.expr and Z is not None) else None
    feats, _, _, _ = base_rel_features(moving, base_px, conf, pitch, include_expr=ex)
    with torch.no_grad():
        r = net(torch.from_numpy(feats)).numpy()
    return base_px + r * pitch


def train_expr_resid(train_pairs, cfg, seed):
    """Prior-style expression+attention residual on the base coord (expected to FAIL on a
    cross-donor base). Optional InfoNCE aligning attention to the OT coupling."""
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    dim = train_pairs[0]["Z_B"].shape[1]
    net = ContrastiveNet(dim, gm.HP["hidden"], gm.HP["layers"], gm.HP["attn_dim"])
    opt = torch.optim.Adam(net.parameters(), lr=RES_LR)
    lf = _loss_fn(cfg.loss)
    for _ in range(RES_EPOCHS):
        net.train()
        for _ in range(RES_STEPS):
            pr = train_pairs[int(rng.integers(len(train_pairs)))]
            moving, base_px, conf, Z, gt, have = synth_tear(pr, rng, cfg)
            gb = graph_tensors(moving, Z, KNN, pr["pitch"])
            bt = torch.from_numpy(base_px / pr["pitch"])
            gt_t = torch.from_numpy((gt / pr["pitch"]).astype(np.float32))
            mask = torch.from_numpy(have)
            opt.zero_grad()
            if cfg.contrastive > 0:
                pred, scores = net(pr["ga"], gb, bt, return_match=True)
                loss = lf((pred - gt_t)[mask])
                tgt_idx = torch.from_numpy(pr["ot_target"]).long()
                w = torch.from_numpy(pr["ot_conf"])
                ce = torch.nn.functional.cross_entropy(scores, tgt_idx, reduction="none")
                loss = loss + cfg.contrastive * (ce * w).sum() / (w.sum() + 1e-9)
            else:
                pred = net(pr["ga"], gb, bt)
                loss = lf((pred - gt_t)[mask])
            loss.backward()
            opt.step()
    net.eval()
    return net


def _expr_resid_predict(net, moving, base_px, conf, pitch, ga, Z):
    gb = graph_tensors(moving, Z, KNN, pitch)
    bt = torch.from_numpy(base_px / pitch)
    with torch.no_grad():
        pred = net(ga, gb, bt).numpy()
    return pred * pitch


# --------------------------------------------------------------------------- #
# fold prep: attach OT base + OT correspondence target for contrastive
# --------------------------------------------------------------------------- #
def attach_ot(pair):
    Z_A = pair["ga"]["x"].numpy()
    coord, conf = ot_coordinate(pair["Z_B"], Z_A, pair["a_norm"].numpy())
    pair["ot_coarse"] = torch.from_numpy(coord)
    pair["ot_conf"] = conf
    # OT argmax A-index per B spot -> pseudo-correspondence target for the InfoNCE loss.
    # Nearest neighbour in the shared expression space is a cheap proxy for the OT coupling
    # argmax and injects the same correspondence prior OT supplies for free.
    tree = cKDTree(Z_A)
    pair["ot_target"] = tree.query(pair["Z_B"], k=1)[1].astype(np.int64)
    return pair


# --------------------------------------------------------------------------- #
# real PASTE2 base (cached per (fold, sev, seed))
# --------------------------------------------------------------------------- #
def paste2_base(A, B_warped):
    from paste2.PASTE2 import partial_pairwise_align
    from paste2.helper import filter_for_common_genes
    Aa, Bb = A.copy(), B_warped.copy()
    filter_for_common_genes([Aa, Bb])
    pi = np.asarray(partial_pairwise_align(Aa, Bb, s=0.99, alpha=0.1,
                                           dissimilarity="pca", verbose=False))
    pred, col_mass = barycentric_projection(pi, np.asarray(Aa.obsm["spatial"], float))
    cen = np.asarray(Aa.obsm["spatial"], float).mean(0)
    pred[col_mass <= 0] = cen
    return pred.astype(np.float32)


def cached_paste2(pair, ho, sev, seed, enable):
    """Return the real PASTE2 A-frame base for the (ho,sev,seed) torn slice, cached to disk.
    Returns None if PASTE2 is disabled or the solve fails/times out."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = CACHE_DIR / f"{ho}_sev{sev:g}_seed{seed}.npy"
    if key.exists():
        try:
            return np.load(key)
        except Exception:
            pass
    if not enable:
        return None
    w, _ = apply_warp(pair["B"], sev, seed=seed, tear=True)
    t0 = time.time()
    try:
        base_px = call_with_timeout(paste2_base, PASTE2_TIMEOUT, pair["A"], w)
        np.save(key, base_px)
        log(f"    PASTE2 solve {ho} sev{sev:g} seed{seed}: {time.time()-t0:.0f}s cached")
        return base_px
    except Exception as e:                       # noqa: BLE001
        log(f"    PASTE2 solve {ho} sev{sev:g} seed{seed} FAILED: {e!r}")
        return None


# --------------------------------------------------------------------------- #
# evaluate one corrector on one held-out pair / base / seed
# --------------------------------------------------------------------------- #
def eval_corrector(cfg, pair, models, ho, seed, base_kind, enable_paste2):
    sevs = OT_SEVS if base_kind == "ot" else PASTE2_SEVS
    per_corr, per_base, per_gate = [], [], []
    for sv in sevs:
        w, _ = apply_warp(pair["B"], sv, seed=seed, tear=True)
        moving = np.asarray(w.obsm["spatial"], np.float32)
        if base_kind == "ot":
            base_px = (pair["ot_coarse"].numpy() * pair["pitch"]).astype(np.float32)
            conf = pair["ot_conf"]
        else:
            base_px = cached_paste2(pair, ho, sv, seed, enable_paste2)
            if base_px is None:
                per_corr.append(np.nan); per_base.append(np.nan); per_gate.append(np.nan)
                continue
            conf = np.ones(len(base_px), np.float32)

        def err(p):
            return registration_error_stats(p, pair["gt"], mask=pair["have"])["median"] / pair["pitch"]

        base_err = err(base_px)
        gate_err = err(hand_gate_predict(moving, base_px, conf, pair["pitch"]))
        # corrector prediction
        eff_base = base_px
        if cfg.ensemble_on == "hand_gate":
            eff_base = hand_gate_predict(moving, base_px, conf, pair["pitch"])
        elif cfg.ensemble_on == "learned_gate" and models.get("gate") is not None:
            eff_base = _gate_blend(models["gate"], moving, base_px, conf, pair["pitch"])

        if cfg.family == "base":
            pred = base_px
        elif cfg.family == "hand_gate":
            pred = hand_gate_predict(moving, base_px, conf, pair["pitch"])
        elif cfg.family == "learned_gate":
            pred = _gate_blend(models["gate"], moving, base_px, conf, pair["pitch"]) \
                if models.get("gate") is not None else base_px
        elif cfg.family == "piece_affine":
            pred = _piece_affine_predict(models["net"], moving, base_px, conf, pair["pitch"])
        elif cfg.family == "resid":
            pred = _resid_predict(models["net"], moving, eff_base, conf, pair["pitch"], cfg,
                                  Z=pair["Z_B"])
        elif cfg.family == "expr_resid":
            pred = _expr_resid_predict(models["net"], moving, eff_base, conf, pair["pitch"],
                                       pair["ga"], pair["Z_B"])
        else:
            pred = base_px
        per_corr.append(err(pred)); per_base.append(base_err); per_gate.append(gate_err)
    return per_corr, per_base, per_gate, sevs


def _mean(x):
    v = [a for a in x if np.isfinite(a)]
    return float(np.mean(v)) if v else float("nan")


# --------------------------------------------------------------------------- #
# config catalogue
# --------------------------------------------------------------------------- #
def build_configs():
    C = []
    # references (both bases)
    for b in ("ot", "paste2"):
        C.append(Corrector(f"base_{b}", "base", base=b))
        C.append(Corrector(f"hand_gate_{b}", "hand_gate", base=b))
    # learned gate (logistic + mlp), both bases
    for b in ("ot", "paste2"):
        C.append(Corrector(f"learned_gate_{b}", "learned_gate", base=b))
        C.append(Corrector(f"learned_gate_mlp_{b}", "learned_gate", base=b, mlp_gate=True))
    # piece-aware learned affine correction
    for b in ("ot", "paste2"):
        C.append(Corrector(f"piece_affine_{b}", "piece_affine", base=b, loss="Huber"))
    # base-relative per-spot residual: loss / depth / DR / expr sweeps (paste2 base = the test)
    for loss in ("L1", "L2", "Huber"):
        C.append(Corrector(f"resid_georel_{loss}_paste2", "resid", base="paste2", loss=loss, dr="mod"))
    for d in (2, 4):
        C.append(Corrector(f"resid_georel_d{d}_paste2", "resid", base="paste2", depth=d, dr="mod"))
    for dr in ("none", "agg"):
        C.append(Corrector(f"resid_georel_dr{dr}_paste2", "resid", base="paste2", dr=dr))
    C.append(Corrector("resid_georel_expr_paste2", "resid", base="paste2", expr=True, dr="mod"))
    C.append(Corrector("resid_georel_mod_ot", "resid", base="ot", dr="mod"))    # transfer check
    # expression residual (prior failure) + contrastive
    C.append(Corrector("resid_expr_paste2", "expr_resid", base="paste2", dr="mod"))
    C.append(Corrector("resid_expr_contrastive_paste2", "expr_resid", base="paste2",
                        dr="mod", contrastive=0.5))
    # ensembles: learned residual on top of the gate(s)
    C.append(Corrector("gate_then_resid_paste2", "resid", base="paste2", dr="mod",
                        ensemble_on="hand_gate"))
    C.append(Corrector("learned_gate_then_resid_paste2", "resid", base="paste2", dr="mod",
                        ensemble_on="learned_gate"))
    return C


# which trained model does a config need? (dedup training across configs per fold/seed)
def needs(cfg):
    if cfg.family in ("base", "hand_gate"):
        return None
    if cfg.family == "learned_gate":
        return None            # trained inline (fast)
    if cfg.family == "piece_affine":
        return "piece_affine"
    if cfg.family == "resid":
        return "resid"
    if cfg.family == "expr_resid":
        return "expr_resid"
    return None


# --------------------------------------------------------------------------- #
# one LODO fold x seed
# --------------------------------------------------------------------------- #
def prep_fold(ho):
    """Fit the fold basis and prepare train + held-out pairs ONCE per fold (seed-independent).
    Returns (train_pairs, ho_pair). Reused across seeds to avoid re-paying the ~90s prep."""
    train_donors = [d for d in gm.DONORS if d != ho]
    stage(f"{ho}:basis")
    train_slices = [s for d in train_donors for pr in gm.DONORS[d][:2] for s in pr]
    basis = gm.fit_fold_basis(train_slices, "svd", PCA_DIM, 2000)
    stage(f"{ho}:prep")
    train_pairs = []
    for d in train_donors:
        for pr in gm.DONORS[d][:2]:
            train_pairs.append(attach_ot(gm.prep_pair(pr[0], pr[1], basis, KNN)))
    ho_pair = attach_ot(gm.prep_pair(*gm.DONORS[ho][0], basis, KNN))
    return train_pairs, ho_pair


def _run_config(cfg, train_pairs, ho_pair, ho, seed, enable_paste2, ex_dim):
    """Train (if needed) + eval one corrector. Returns the aggregated result tuple."""
    models = {}
    need = needs(cfg)
    if cfg.family == "learned_gate" or cfg.ensemble_on == "learned_gate":
        gcfg = cfg if cfg.family == "learned_gate" else Corrector("g", "learned_gate",
                                                                  base=cfg.base, dr=cfg.dr)
        models["gate"] = train_learned_gate(train_pairs, gcfg, seed)
    if need == "piece_affine":
        models["net"] = train_piece_affine(train_pairs, cfg, seed)
    elif need == "resid":
        models["net"] = train_resid(train_pairs, cfg, seed, ex_dim)
    elif need == "expr_resid":
        models["net"] = train_expr_resid(train_pairs, cfg, seed)
    return eval_corrector(cfg, ho_pair, models, ho, seed, cfg.base, enable_paste2)


def run_fold_seed(ho, seed, configs, enable_paste2, prepped, ex_dim=8):
    train_pairs, ho_pair = prepped
    for cfg in configs:
        stage(f"{ho}/s{seed}:{cfg.name}")
        t0 = time.time()
        try:
            per_corr, per_base, per_gate, sevs = call_with_timeout(
                _run_config, CONFIG_TIMEOUT, cfg, train_pairs, ho_pair, ho, seed,
                enable_paste2, ex_dim)
            corr_m, base_m, gate_m = _mean(per_corr), _mean(per_base), _mean(per_gate)
            if not np.isfinite(corr_m):
                append_row(dict(kind="dlpfc_lodo", base=cfg.base, config=cfg.name, held_out=ho,
                                seed=seed, status="skip", detail="no finite base (paste2 off?)",
                                timestamp=_now(), seconds=round(time.time() - t0, 1)))
                log(f"[{ho}/s{seed}] {cfg.name}: SKIP (no base)")
                continue
            append_row(dict(
                kind="dlpfc_lodo", base=cfg.base, config=cfg.name, held_out=ho, seed=seed,
                reg_err_pitch=round(corr_m, 3),
                per_sev=";".join(f"{x:.3f}" for x in per_corr),
                base_err=round(base_m, 3), gate_err=round(gate_m, 3),
                paste2_extref=round(PASTE2_EXTREF, 3),
                beats_base=bool(corr_m <= base_m), beats_gate=bool(corr_m <= gate_m),
                seconds=round(time.time() - t0, 1), status="ok", timestamp=_now(),
                detail=f"sevs={','.join(f'{s:g}' for s in sevs)}"))
            log(f"[{ho}/s{seed}] {cfg.name} [{cfg.base}]: corr={corr_m:.3f} "
                f"base={base_m:.3f} gate={gate_m:.3f} "
                f"beats_gate={corr_m <= gate_m} ({time.time()-t0:.0f}s)")
        except Exception as e:                       # noqa: BLE001
            append_row(dict(kind="dlpfc_lodo", base=cfg.base, config=cfg.name, held_out=ho,
                            seed=seed, status="error", detail=f"{type(e).__name__}: {e}"[:180],
                            timestamp=_now(), seconds=round(time.time() - t0, 1)))
            log(f"[{ho}/s{seed}] {cfg.name} FAILED: {e!r}\n{traceback.format_exc()}")


# --------------------------------------------------------------------------- #
# plotting + findings (importable; also run via --plot-only)
# --------------------------------------------------------------------------- #
def _read_rows():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="", encoding="ascii", errors="replace") as fh:
        return list(csv.DictReader(fh))


def _agg(rows, base, config):
    vals = [float(r["reg_err_pitch"]) for r in rows if r.get("status") == "ok"
            and r["base"] == base and r["config"] == config and r.get("reg_err_pitch") not in ("", None)]
    return (float(np.mean(vals)), float(np.std(vals)), len(vals)) if vals else (None, None, 0)


def make_plot(rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        log(f"plot skipped: {e!r}")
        return
    configs = []
    seen = set()
    for r in rows:
        if r.get("status") == "ok" and r["base"] == "paste2" and r["config"] not in seen:
            seen.add(r["config"]); configs.append(r["config"])
    if not configs:
        log("no paste2 rows to plot yet")
        return
    order = sorted(configs, key=lambda c: (_agg(rows, "paste2", c)[0] or 99))
    means = [_agg(rows, "paste2", c)[0] for c in order]
    stds = [_agg(rows, "paste2", c)[1] for c in order]
    base_m = _agg(rows, "paste2", "base_paste2")[0]
    gate_m = _agg(rows, "paste2", "hand_gate_paste2")[0]
    fig, ax = plt.subplots(figsize=(max(10, len(order) * 0.7), 6))
    x = np.arange(len(order))
    colors = ["#d1495b" if c == "base_paste2" else "#2e7d32" if c == "hand_gate_paste2"
              else "#8a63d2" for c in order]
    ax.bar(x, means, yerr=stds, color=colors, zorder=3, capsize=3)
    for xi, m in zip(x, means):
        if m is not None:
            ax.text(xi, m + 0.05, f"{m:.2f}", ha="center", va="bottom", fontsize=7)
    if base_m:
        ax.axhline(base_m, color="#d1495b", ls="--", lw=1.4, label=f"PASTE2 base ({base_m:.2f})")
    if gate_m:
        ax.axhline(gate_m, color="#2e7d32", ls=":", lw=1.6, label=f"hand gate ({gate_m:.2f})")
    ax.set_xticks(x); ax.set_xticklabels(order, rotation=40, ha="right", fontsize=7)
    ax.set_ylabel("held-out error (median spot-pitches, lower=better)")
    ax.set_title("model-gen-2: learned corrections on the REAL PASTE2 base\n"
                 "3-donor DLPFC LODO tear benchmark (mean over folds x seeds)")
    ax.legend(loc="upper right", frameon=False)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    fig.tight_layout()
    fig.savefig(PNG_PATH, dpi=130)
    plt.close(fig)
    log(f"wrote {PNG_PATH}")


def write_findings(rows):
    ok = [r for r in rows if r.get("status") == "ok"]
    base_m = _agg(rows, "paste2", "base_paste2")[0]
    gate_m = _agg(rows, "paste2", "hand_gate_paste2")[0]
    configs = sorted({r["config"] for r in ok if r["base"] == "paste2"})
    ranked = sorted(((c, *_agg(rows, "paste2", c)) for c in configs),
                    key=lambda t: (t[1] if t[1] is not None else 99))

    L = ["# model-gen-2 - can a learned correction beat the gate on torn tissue?\n",
         f"_Generated {_now()} on branch `model-gen-2`._\n",
         "**Question.** The learned absolute-coordinate model does not generalize to a "
         "held-out donor (~9 spot-pitches). PASTE2 generalizes for free (~4.4). The hand "
         "gate - a fit-residual-gated per-piece rigid refinement layered on PASTE2 - beats "
         "PASTE2 (~3.7) because it is a CORRECTION in base-relative geometry, not an absolute "
         "prediction. This experiment asks, systematically: can a LEARNED correction restricted "
         "to base-relative features transfer across donors and beat the hand gate?\n",
         "\n**Benchmark.** 3-donor DLPFC leave-one-donor-out (Br5292/Br5595/Br8100), tear=True, "
         f">=3 seeds, median registration error in spot-pitches. Reference lines: PASTE2 external "
         f"{PASTE2_EXTREF:.2f}; real PASTE2 base recomputed here = "
         f"{base_m:.3f} (n rows) ; hand gate = {gate_m:.3f} .\n" if base_m and gate_m else
         "\n**Benchmark.** (PASTE2 base not yet computed - re-run without --no-paste2.)\n"]

    L.append("\n## Ranked results on the REAL PASTE2 base (lower is better)\n")
    L.append("| config | err (pitch) | std | n | vs PASTE2 base | vs hand gate |\n")
    L.append("|---|---|---|---|---|---|\n")
    for c, m, sd, n in ranked:
        if m is None:
            continue
        vb = "-" if base_m is None else ("beats" if m <= base_m else f"+{m-base_m:.2f}")
        vg = "-" if gate_m is None else ("BEATS" if m <= gate_m else f"+{m-gate_m:.2f}")
        L.append(f"| {c} | {m:.3f} | {sd:.3f} | {n} | {vb} | {vg} |\n")

    # honest verdict
    gstr = f"{gate_m:.3f}" if gate_m is not None else "n/a"
    bstr = f"{base_m:.3f}" if base_m is not None else "n/a"
    winners = [c for c, m, sd, n in ranked if m is not None and gate_m is not None
               and m <= gate_m and c not in ("hand_gate_paste2",)]
    L.append("\n## Verdict\n")
    if gate_m is None:
        L.append("- PASTE2 base not yet computed; no verdict against the gate available.\n")
    elif winners:
        L.append(f"- **{len(winners)} learned config(s) matched/beat the hand gate "
                 f"({gstr}) on held-out donors**: {', '.join(winners)}. "
                 "These must pass the leakage audit below before being called a win.\n")
    else:
        L.append(f"- **No learned config beat the hand gate ({gstr}) on held-out donors.** "
                 "The gate remains the strongest torn-tissue corrector.\n")
    beat_p2 = [c for c, m, sd, n in ranked if m is not None and base_m is not None
               and m <= base_m and c not in ("base_paste2", "hand_gate_paste2")]
    if base_m is not None:
        L.append(f"- Configs beating the raw PASTE2 base ({bstr}): "
                 f"{', '.join(beat_p2) if beat_p2 else 'none'}.\n")
    # OT-base transfer sanity
    ot_gate = _agg(rows, "ot", "hand_gate_ot")[0]
    ot_base = _agg(rows, "ot", "base_ot")[0]
    if ot_base is not None:
        ogstr = f"{ot_gate:.2f}" if ot_gate is not None else "n/a"
        L.append(f"- OT-surrogate base (free, warp-invariant) is weak "
                 f"({ot_base:.2f}); its gate={ogstr} . Confirms all real headroom is on the "
                 "PASTE2 base, as expected.\n")
    L.append("\n## Leakage discipline\n"
             "- Fold basis, every trained corrector, the learned gate: fit ONLY on the two TRAIN "
             "donors' SYNTHETIC tears. No ground-truth correspondence, test warp, or held-out "
             "coordinate enters training or the base.\n"
             "- Base-relative correctors are trained on the cheap OT-surrogate base and evaluated "
             "on the real PASTE2 base; the transfer is legitimate precisely because the features "
             "carry no absolute/test information.\n"
             "- PASTE2 runs on the test slice at inference only (baseline/base), never as a "
             "training signal. Eval warp seeds are disjoint from training seed streams.\n")
    L.append("\n## Configs run\n")
    for c, m, sd, n in ranked:
        L.append(f"- `{c}`: {('%.3f' % m) if m is not None else 'n/a'} (n={n})\n")
    FINDINGS.write_text("".join(L), encoding="ascii", errors="replace")
    log(f"wrote {FINDINGS}")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--no-paste2", action="store_true")
    ap.add_argument("--folds", nargs="*", default=None)
    ap.add_argument("--seeds", nargs="*", type=int, default=None)
    ap.add_argument("--plot-only", action="store_true")
    args = ap.parse_args()

    if args.plot_only:
        rows = _read_rows()
        make_plot(rows)
        write_findings(rows)
        return

    global _HB_STOP, RES_EPOCHS, RES_STEPS
    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()

    enable_paste2 = not args.no_paste2
    folds = args.folds or list(gm.DONORS)
    seeds = args.seeds if args.seeds is not None else [0, 1, 2]
    configs = build_configs()
    if args.smoke:
        RES_EPOCHS, RES_STEPS = 3, 4
        folds, seeds, enable_paste2 = folds[:1], [0], False
        configs = [c for c in configs if c.base == "ot"][:6]

    log(f"=== model-gen-2 START folds={folds} seeds={seeds} paste2={enable_paste2} "
        f"configs={len(configs)} ===")
    t_start = time.time()
    for ho in folds:
        try:
            prepped = prep_fold(ho)
        except Exception as e:                       # noqa: BLE001
            log(f"[{ho}] PREP FAILED: {e!r}\n{traceback.format_exc()}")
            continue
        for seed in seeds:
            log(f"--- fold {ho} seed {seed} ---")
            try:
                run_fold_seed(ho, seed, configs, enable_paste2, prepped)
            except Exception as e:                   # noqa: BLE001
                log(f"[{ho}/s{seed}] FOLD FAILED: {e!r}\n{traceback.format_exc()}")
            # incremental plot/findings refresh after each fold-seed
            try:
                rows = _read_rows()
                make_plot(rows)
                write_findings(rows)
            except Exception as e:                   # noqa: BLE001
                log(f"plot/findings refresh failed: {e!r}")
    _HB_STOP = True
    log(f"=== model-gen-2 DONE ({time.time()-t_start:.0f}s) ===")


if __name__ == "__main__":
    main()
