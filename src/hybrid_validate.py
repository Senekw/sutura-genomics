"""
Overnight validation + hardening of the hybrid torn-tissue result
(fit-residual-gated piecewise correction on PASTE2, and the self-supervised
off-distribution residual). Everything is measured against REAL PASTE2 on the
SAME warped slices, with the array-bridge ground truth, in spot-pitches -
identical metric to generalization_max.py / hybrid_combined.py.

What this driver does (all incremental, resumable, per-cell try/except):
  1. PASTE2 base CACHE. For each (dataset, severity, seed) it runs real PASTE2 ONCE
     (barycentric base coord), caches it to research/results/paste2_cache/*.npz, and
     reuses it for every config + re-analysis. This is the speedup that makes the full
     grid affordable and every later analysis free.
  2. Gate stress-test. Scores the fit-residual-gated piecewise correction across EVERY
     dataset x severity x seed, so we can report per-dataset/per-severity where it beats
     PASTE2 and where it does not.
  3. Leakage-clean self-supervision. Two residual variants per dataset:
       selfsup_leak  - trained on the A-B array-bridge correspondence (== last night's
                       breast setup; the training target IS the eval target -> leaking).
       selfsup_clean - trained ONLY on synthetic self-warps of the REFERENCE section A
                       (map warped-A back to A's own coords; the real A-B correspondence
                       is NEVER used) -> leakage-free, the honest generalization test.
  4. High-severity gate extension. Per-piece RIGID vs AFFINE vs QUADRATIC fits, each
     trust-gated by a CROSS-VALIDATED fit residual (fit on half the piece, score on the
     other half) so higher-DOF fits cannot win by overfitting PASTE2 noise.
  5. Combination. gated-piecewise (structural, on PASTE2) blended with selfsup_clean
     (learned) - does composing the two winners beat each alone?
  6. Gate-threshold robustness sweep (leakage/robustness audit): the same gate at several
     fixed thresholds, to show the win is not a lucky single threshold.

Config vocabulary (scored per dataset x sev x seed on the cached PASTE2 base):
  paste2, gated_rigid, gated_affine, gated_quad, gated_rigid_thr{2,3,6,8},
  selfsup_clean, selfsup_leak, combo_gated_selfsup

Robustness: detached; heartbeat every HEARTBEAT s with the current stage; every PASTE2
call under a watchdog TIMEOUT; every (dataset x sev x seed) cell and every config wrapped
in try/except; rows appended to the CSV immediately; PASTE2 bases cached so a restart
resumes instantly.

Outputs: research/results/hybrid_validate.csv (+ .log), paste2_cache/*.npz.
Usage:
  python src/hybrid_validate.py                 # full grid (detached-friendly)
  python src/hybrid_validate.py --smoke         # 1 dataset, 2 sev, 1 seed, tiny epochs
  python src/hybrid_validate.py --datasets Br8100,breast --seeds 0
"""
from __future__ import annotations

import argparse
import csv
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from scipy.spatial import cKDTree

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import anndata as ad  # noqa: E402
from train_cross import (ARCACrossNet, graph_tensors, cross_features,  # noqa: E402
                         array_bridge)
from warp_slice import apply_warp  # noqa: E402
from scoring import registration_error_stats, barycentric_projection  # noqa: E402
import generalization_max as gm  # noqa: E402
from hybrid_combined import (ot_coordinate, OTInitNet, detect_pieces, umeyama,  # noqa: E402
                             paste2_prior)

DATA = ROOT / "data"
EXT = DATA / "external"
OUT = ROOT / "research" / "results"
CACHE = OUT / "paste2_cache"
CSV_PATH = OUT / "hybrid_validate.csv"
LOG_PATH = OUT / "hybrid_validate.log"

PCA_DIM = 50
KNN = 6
HEARTBEAT = 20
PASTE2_TIMEOUT = 900
GATE_SCALE = 1.0
GATE_THR = 4.5
# training knobs for the self-supervised residuals (per dataset, trained once)
RES_EPOCHS = 40
RES_STEPS = 16
RES_LR = 1e-3
MAX_SEV = 8.0
TEAR_PROB = 0.5

# --- grid ---
DLPFC = {  # held-out donor -> its scoring pair (matches gm.DONORS[d][0])
    "Br5292": ("DLPFC_151507", "DLPFC_151508"),
    "Br5595": ("DLPFC_151669", "DLPFC_151670"),
    "Br8100": ("DLPFC_151673", "DLPFC_151674"),
}
OOD = {
    "breast": ("V1_Breast_Cancer_Block_A_Section_1", "V1_Breast_Cancer_Block_A_Section_2"),
    "mousebrain": ("V1_Mouse_Brain_Sagittal_Posterior", "V1_Mouse_Brain_Sagittal_Posterior_Section_2"),
}
DLPFC_SEVS = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
OOD_SEVS = [0.0, 2.0, 4.0, 6.0, 8.0]
SEEDS = [0, 1, 2]
THR_SWEEP = [2.0, 3.0, 6.0, 8.0]           # gate-threshold robustness (plus the default 4.5)

CSV_FIELDS = ["dataset", "kind", "severity", "seed", "config", "err_pitch",
              "paste2_err", "beats_paste2", "n", "pitch", "seconds", "status",
              "timestamp", "detail"]

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
        except Exception as e:                      # noqa: BLE001
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
# dataset construction (per-pair features + array-bridge GT; deployable, no
# external training donors needed anywhere)
# --------------------------------------------------------------------------- #
def build_dataset(ref_name, mov_name):
    rf = (DATA / f"{ref_name}.h5ad")
    if not rf.exists():
        rf = EXT / f"{ref_name}.h5ad"
    mf = (DATA / f"{mov_name}.h5ad")
    if not mf.exists():
        mf = EXT / f"{mov_name}.h5ad"
    A = ad.read_h5ad(rf)
    B = ad.read_h5ad(mf)
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B.obsm["spatial"] = np.asarray(B.obsm["spatial"], float)
    coords = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    Z_A, Z_B = cross_features(A, B, PCA_DIM, 0)
    gt, have = array_bridge(A, B)
    gt_safe = gt.copy()
    gt_safe[~have] = coords.mean(0)
    ga = graph_tensors(coords, Z_A, KNN, pitch)
    a_norm = torch.from_numpy((coords / pitch).astype(np.float32))
    # OT coarse: B->A (for eval) and A->A (for clean self-sup training)
    ot_ba, ot_ba_conf = ot_coordinate(Z_B, Z_A, coords / pitch)
    ot_aa, _ = ot_coordinate(Z_A, Z_A, coords / pitch)
    return dict(A=A, B=B, coords=coords, pitch=pitch, Z_A=Z_A, Z_B=Z_B, ga=ga,
                a_norm=a_norm, gt=gt, have=have,
                gt_norm=torch.from_numpy((gt_safe / pitch).astype(np.float32)),
                mask=torch.from_numpy(have),
                ot_coarse=torch.from_numpy(ot_ba), ot_conf=ot_ba_conf,
                ot_self_coarse=torch.from_numpy(ot_aa))


# --------------------------------------------------------------------------- #
# PASTE2 base cache
# --------------------------------------------------------------------------- #
def paste2_base(ds_name, pair, sev, seed):
    CACHE.mkdir(parents=True, exist_ok=True)
    fp = CACHE / f"{ds_name}_s{sev:g}_seed{seed}.npz"
    if fp.exists():
        try:
            return np.load(fp)["base"], True
        except Exception:                            # noqa: BLE001
            pass
    w, _ = apply_warp(pair["B"], sev, seed=seed, tear=True)
    base = call_with_timeout(paste2_prior, PASTE2_TIMEOUT, pair["A"], w,
                             pair["coords"], pair["pitch"])
    np.savez_compressed(fp, base=base.astype(np.float32))
    return base, False


# --------------------------------------------------------------------------- #
# per-piece fitters (rigid / affine / quadratic) with cross-validated trust gate
# --------------------------------------------------------------------------- #
def _poly_design(P, order):
    x, y = P[:, 0], P[:, 1]
    o = np.ones_like(x)
    if order == 1:
        return np.stack([o, x, y], axis=1)
    return np.stack([o, x, y, x * x, x * y, y * y], axis=1)


def _poly_fit(src, dst, order, w):
    Phi = _poly_design(src, order)
    WPhi = w[:, None] * Phi
    G = Phi.T @ WPhi + 1e-6 * np.eye(Phi.shape[1])
    B = Phi.T @ (w[:, None] * dst)
    return np.linalg.lstsq(G, B, rcond=None)[0]


def _fit_predict(src, dst, order, w, eval_src=None):
    """Fit a transform src->dst (order 0=rigid via Umeyama, 1=affine, 2=quadratic);
    return predictions at eval_src (default src)."""
    tgt = src if eval_src is None else eval_src
    if order == 0:
        R, t, sc = umeyama(src, dst, w=w)
        return sc * (tgt @ R.T) + t
    beta = _poly_fit(src, dst, order, w)
    return _poly_design(tgt, order) @ beta


def _cv_fit_residual(src, dst, order, w, pitch, rng):
    """Cross-validated fit residual (pitch): fit on half the piece, score the other half,
    both directions, averaged. Penalizes higher-DOF fits that overfit PASTE2 noise, so the
    trust gate is fair across rigid/affine/quadratic. GT-free."""
    n = len(src)
    idx = rng.permutation(n)
    h = n // 2
    if h < (order + 1) * 3:
        # too few points to CV-split for this DOF -> use full-fit residual (conservative)
        pred = _fit_predict(src, dst, order, w)
        return float(np.median(np.linalg.norm(pred - dst, axis=1)) / pitch)
    a, b = idx[:h], idx[h:]
    res = []
    for tr, te in ((a, b), (b, a)):
        pred = _fit_predict(src[tr], dst[tr], order, w[tr], eval_src=src[te])
        res.append(np.median(np.linalg.norm(pred - dst[te], axis=1)))
    return float(np.mean(res) / pitch)


def gated_piecewise(moving, base_px, conf, pitch, order=0, thr=GATE_THR,
                    scale=GATE_SCALE, seed=0, cv=True):
    """Detect pieces; per piece fit an (order) transform to the PASTE2 base and apply it,
    blended by a logistic on the fit residual (trust piecewise where the piece is
    well-explained by the fit, fall back to PASTE2 where it is not). GT-free.

    cv=False uses the FULL-fit residual (== last night's exact gate, for reproduction).
    cv=True uses a CROSS-VALIDATED residual (fit on half the piece, score the other half),
    which penalizes higher-DOF fits so affine/quadratic can't win by overfitting PASTE2 noise.
    order 0=rigid (Umeyama), 1=affine, 2=quadratic."""
    labels = detect_pieces(moving, pitch)
    rng = np.random.default_rng(seed)
    pred = base_px.copy()
    min_n = 6 if order == 0 else (10 if order == 1 else 18)
    for lab in np.unique(labels):
        m = labels == lab
        if m.sum() < min_n:
            continue
        s, d, wgt = moving[m], base_px[m], conf[m]
        fit = _fit_predict(s, d, order, wgt)
        if cv:
            res = _cv_fit_residual(s, d, order, wgt, pitch, rng)
        else:
            res = float(np.median(np.linalg.norm(fit - d, axis=1)) / pitch)
        w = float(1.0 / (1.0 + np.exp((res - thr) / scale)))
        pred[m] = w * fit + (1 - w) * d
    return pred


# --------------------------------------------------------------------------- #
# self-supervised residuals (per dataset, trained once)
# --------------------------------------------------------------------------- #
def train_selfsup(pair, mode, epochs=RES_EPOCHS, steps=RES_STEPS, lr=RES_LR, seed=0):
    """mode='leak': train on warps of B with the A-B array-bridge GT (== last night's
    breast setup; training target == eval target). mode='clean': train ONLY on synthetic
    self-warps of the reference A (map warped-A -> A's own coords); the A-B correspondence
    is never used -> leakage-free."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    dim = pair["Z_A"].shape[1]
    model = OTInitNet(dim, gm.HP["hidden"], gm.HP["layers"], gm.HP["attn_dim"])
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    if mode == "clean":
        src_ad, Zsrc, coarse = pair["A"], pair["Z_A"], pair["ot_self_coarse"]
        gt_norm = pair["a_norm"]                     # every A spot -> itself
        mask = torch.ones(pair["A"].n_obs, dtype=torch.bool)
    else:  # leak
        src_ad, Zsrc, coarse = pair["B"], pair["Z_B"], pair["ot_coarse"]
        gt_norm, mask = pair["gt_norm"], pair["mask"]
    for _ in range(epochs):
        model.train()
        for _ in range(steps):
            sv = float(rng.uniform(0, MAX_SEV))
            w, _ = apply_warp(src_ad, sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < TEAR_PROB))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32), Zsrc, KNN, pair["pitch"])
            opt.zero_grad()
            pred = model(pair["ga"], gb, pair["a_norm"], coarse)
            loss = (pred - gt_norm)[mask].norm(dim=1).mean()
            loss.backward()
            opt.step()
    model.eval()
    return model


def selfsup_predict(model, pair, moving):
    gb = graph_tensors(moving, pair["Z_B"], KNN, pair["pitch"])
    with torch.no_grad():
        return model(pair["ga"], gb, pair["a_norm"], pair["ot_coarse"]).numpy() * pair["pitch"]


# --------------------------------------------------------------------------- #
# scoring for one (dataset, sev, seed) on the cached PASTE2 base
# --------------------------------------------------------------------------- #
def score_cell(ds_name, kind, pair, sev, seed, models, base_px):
    pitch = pair["pitch"]
    # the gate uses UNIFORM weights -> depends only on PASTE2 base coords + moving geometry,
    # no features at all (feature-free, fully deployable; reproduces last night's numbers).
    conf = np.ones(pair["B"].n_obs, np.float32)
    w, _ = apply_warp(pair["B"], sev, seed=seed, tear=True)
    moving = np.asarray(w.obsm["spatial"], np.float32)

    def err(pred):
        return registration_error_stats(pred, pair["gt"], mask=pair["have"])["median"] / pitch

    preds = {}
    preds["paste2"] = base_px
    # gated_rigid == last night's exact gate (full-fit residual) -> reproduces the 3.73 result
    preds["gated_rigid"] = gated_piecewise(moving, base_px, conf, pitch, order=0, seed=seed, cv=False)
    # CV-gated variants (fair across DOF); affine/quad target the high-severity regime
    preds["gated_rigid_cv"] = gated_piecewise(moving, base_px, conf, pitch, order=0, seed=seed, cv=True)
    preds["gated_affine"] = gated_piecewise(moving, base_px, conf, pitch, order=1, seed=seed, cv=True)
    preds["gated_quad"] = gated_piecewise(moving, base_px, conf, pitch, order=2, seed=seed, cv=True)
    for thr in THR_SWEEP:
        preds[f"gated_rigid_thr{thr:g}"] = gated_piecewise(moving, base_px, conf, pitch,
                                                           order=0, thr=thr, seed=seed, cv=False)
    sc = selfsup_predict(models["clean"], pair, moving) if "clean" in models else None
    if sc is not None:
        preds["selfsup_clean"] = sc
    if "leak" in models:
        preds["selfsup_leak"] = selfsup_predict(models["leak"], pair, moving)
    # combination: blend the two winners (gated structural + clean learned)
    if sc is not None:
        gr = preds["gated_rigid"]
        preds["combo_gated_selfsup"] = 0.5 * (gr + sc)

    base_err = err(base_px)
    out = {}
    for cfg, pred in preds.items():
        e = err(pred)
        out[cfg] = e
        append_row(dict(dataset=ds_name, kind=kind, severity=sev, seed=seed, config=cfg,
                        err_pitch=round(e, 4), paste2_err=round(base_err, 4),
                        beats_paste2=bool(e <= base_err), n=int(pair["have"].sum()),
                        pitch=round(pitch, 1), seconds="", status="ok",
                        timestamp=_now(), detail=""))
    return out, base_err


# --------------------------------------------------------------------------- #
_PREPARED = {}   # ds_name -> (pair, models)


def prep_dataset(ds_name, ref, mov, train_leak, smoke_epochs=None):
    """Build the dataset and train its self-supervised residuals ONCE (memoized), so a
    seed-outer loop does not retrain per seed."""
    if ds_name in _PREPARED:
        return _PREPARED[ds_name]
    stage(f"{ds_name}:build")
    log(f"=== prepare dataset {ds_name} ({ref} / {mov}) ===")
    pair = build_dataset(ref, mov)
    log(f"[{ds_name}] A={pair['A'].n_obs} B={pair['B'].n_obs} pitch={pair['pitch']:.1f} "
        f"bridge={pair['have'].mean()*100:.0f}%")
    models = {}
    ep = smoke_epochs or RES_EPOCHS
    st = 6 if smoke_epochs else RES_STEPS
    for mode in (["clean", "leak"] if train_leak else ["clean"]):
        stage(f"{ds_name}:train_selfsup_{mode}")
        t = time.time()
        try:
            models[mode] = train_selfsup(pair, mode, epochs=ep, steps=st)
            log(f"[{ds_name}] trained selfsup_{mode} ({time.time()-t:.0f}s)")
        except Exception as e:                       # noqa: BLE001
            log(f"[{ds_name}] selfsup_{mode} FAILED: {e!r}")
    _PREPARED[ds_name] = (pair, models)
    return pair, models


def score_one(ds_name, kind, pair, models, sev, seed):
    stage(f"{ds_name}:s{sev:g}:seed{seed}:paste2")
    t0 = time.time()
    try:
        base_px, cached = paste2_base(ds_name, pair, sev, seed)
    except Exception as e:                           # noqa: BLE001
        append_row(dict(dataset=ds_name, kind=kind, severity=sev, seed=seed,
                        config="paste2", status="error",
                        detail=f"paste2 {type(e).__name__}: {e}"[:180], timestamp=_now()))
        log(f"[{ds_name}] s{sev:g} seed{seed} PASTE2 FAILED/timeout: {e!r}")
        return
    stage(f"{ds_name}:s{sev:g}:seed{seed}:score")
    try:
        out, base_err = score_cell(ds_name, kind, pair, sev, seed, models, base_px)
        tag = "cache" if cached else f"{time.time()-t0:.0f}s"
        log(f"[{ds_name}] s{sev:g} seed{seed}: paste2={base_err:.2f} "
            f"gated_rigid={out.get('gated_rigid', float('nan')):.2f} "
            f"gated_affine={out.get('gated_affine', float('nan')):.2f} "
            f"selfsup_clean={out.get('selfsup_clean', float('nan')):.2f} "
            f"selfsup_leak={out.get('selfsup_leak', float('nan')):.2f} ({tag})")
    except Exception as e:                           # noqa: BLE001
        append_row(dict(dataset=ds_name, kind=kind, severity=sev, seed=seed,
                        config="(score)", status="error",
                        detail=f"{type(e).__name__}: {e}"[:180], timestamp=_now()))
        log(f"[{ds_name}] s{sev:g} seed{seed} SCORE FAILED: {e!r}\n{traceback.format_exc()}")


# --------------------------------------------------------------------------- #
def main():
    global _HB_STOP
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--datasets", default="", help="comma subset of dataset names")
    p.add_argument("--seeds", default="", help="comma subset of seeds")
    p.add_argument("--no-leak", action="store_true", help="skip the leaking self-sup variant")
    args = p.parse_args()

    all_ds = {**{k: (v, "dlpfc") for k, v in DLPFC.items()},
              **{k: (v, "ood") for k, v in OOD.items()}}
    # DLPFC first (the expensive, core result), OOD last (cheap PASTE2)
    order = ["Br8100", "Br5292", "Br5595", "breast", "mousebrain"]
    names = [d.strip() for d in args.datasets.split(",") if d.strip()] or \
            [n for n in order if n in all_ds]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()] or SEEDS
    smoke_epochs = None
    if args.smoke:
        names = ["Br8100"]
        seeds = [0]
        smoke_epochs = 3

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    log("=" * 80)
    log(f"hybrid_validate START datasets={names} seeds={seeds} smoke={args.smoke}")
    log(f"gate thr={GATE_THR} sweep={THR_SWEEP} | PASTE2 timeout={PASTE2_TIMEOUT}s | cache={CACHE}")
    log("=" * 80)

    t_all = time.time()
    # seed-OUTER so seed 0 across ALL datasets (reproduction + full per-severity) lands first,
    # then seeds add variance. Datasets are memoized so self-sup training happens once each.
    for seed in seeds:
        for name in names:
            if name not in all_ds:
                log(f"unknown dataset {name}, skipping")
                continue
            (ref, mov), kind = all_ds[name]
            sevs = ([0.0, 4.0] if args.smoke else
                    (DLPFC_SEVS if kind == "dlpfc" else OOD_SEVS))
            try:
                pair, models = prep_dataset(name, ref, mov, train_leak=not args.no_leak,
                                            smoke_epochs=smoke_epochs)
                for sev in sevs:
                    score_one(name, kind, pair, models, sev, seed)
            except Exception as e:                   # noqa: BLE001
                log(f"[{name}] DATASET FAILED: {e!r}\n{traceback.format_exc()}")
        log(f"=== seed {seed} pass done ({time.time()-t_all:.0f}s elapsed) ===")

    _HB_STOP = True
    log(f"hybrid_validate DONE total={time.time()-t_all:.0f}s -> {CSV_PATH}")
    log("DONE")


if __name__ == "__main__":
    main()
