"""
Final robustness pass for the validated gate (gate_refine). Runs the packaged gate on
datasets NOT in the main grid and appends to the same validated CSV
(research/results/hybrid_validate.csv). Scores only the keeper configs - paste2 (base) and
gate_refine {rigid, affine, quad}. Does NOT re-introduce the retracted leaky self-supervised
component.

New datasets:
  * 3 more DLPFC CROSS-section pairs (the 2nd adjacent pair of each donor) - real cross-section,
    the strongest regime.
  * diverse-tissue SELF-alignment (single Space Ranger sections; moving = a synthetic-tear copy
    of the section, aligned back to itself): cerebellum, mouse kidney, glioblastoma, spinal cord,
    colorectal. Large sections are subsampled to keep PASTE2 tractable (subsampling was shown to
    preserve the gated win). Self-alignment shares the array-bridge GT (moving is a copy, so every
    spot maps to itself) and is labelled kind="self" so it is not conflated with the cross-section
    results.

Reuses hybrid_validate's PASTE2 cache + CSV writer; own log + heartbeat; per-cell try/except;
PASTE2 watchdog. Resumable (cached bases skipped).
Usage:  python src/hybrid_robustness.py            # full new-dataset pass (detached-friendly)
        python src/hybrid_robustness.py --smoke     # 1 dataset, 1 sev, 1 seed
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import anndata as ad  # noqa: E402
from train_cross import array_bridge  # noqa: E402
from warp_slice import apply_warp  # noqa: E402
from scoring import registration_error_stats  # noqa: E402
import gate_refine as gr  # noqa: E402
import hybrid_validate as hv  # noqa: E402  (reuse cache/append_row/paste2_base/watchdog)

DATA = ROOT / "data"
LOG_PATH = hv.OUT / "hybrid_robustness.log"
SUBSAMPLE = 3000               # cap self-alignment sections to keep PASTE2 tractable
HEARTBEAT = 20

DLPFC_B = {  # 2nd adjacent pair per donor (cross-section)
    "Br5292b": ("DLPFC_151509", "DLPFC_151510"),
    "Br5595b": ("DLPFC_151671", "DLPFC_151672"),
    "Br8100b": ("DLPFC_151675", "DLPFC_151676"),
}
SELF = {  # single sections -> self-alignment; value = loader spec
    "cerebellum":   ("visium", DATA / "Parent_Visium_Human_Cerebellum"),
    "kidney":       ("h5ad", DATA / "external" / "V1_Mouse_Kidney.h5ad"),
    "glioblastoma": ("visium", DATA / "Parent_Visium_Human_Glioblastoma"),
    "spinalcord":   ("visium", DATA / "Parent_Visium_Human_SpinalCord"),
    "colorectal":   ("visium", DATA / "Parent_Visium_Human_ColorectalCancer"),
}
DLPFC_SEVS = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
SELF_SEVS = [0.0, 2.0, 4.0, 6.0, 8.0]
SEEDS = [0, 1]
ORDERS = {"gated_rigid": "rigid", "gated_affine": "affine", "gated_quad": "quadratic"}

_STAGE = "init"
_HB_STOP = False


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    hv.OUT.mkdir(parents=True, exist_ok=True)
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


def load_section(spec):
    kind, path = spec
    if kind == "h5ad":
        a = ad.read_h5ad(path)
    else:
        import scanpy as sc
        a = sc.read_visium(path)
        a.var_names_make_unique()
    a.obsm["spatial"] = np.asarray(a.obsm["spatial"], float)
    return a


def subsample(a, n, seed=0):
    if n >= a.n_obs:
        return a
    idx = np.sort(np.random.default_rng(seed).choice(a.n_obs, n, replace=False))
    return a[idx].copy()


def build_cross(ref, mov):
    A = ad.read_h5ad(DATA / f"{ref}.h5ad")
    B = ad.read_h5ad(DATA / f"{mov}.h5ad")
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B.obsm["spatial"] = np.asarray(B.obsm["spatial"], float)
    coords = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    gt, have = array_bridge(A, B)
    return dict(A=A, B=B, coords=coords, pitch=pitch, gt=gt, have=have)


def build_self(spec):
    A = load_section(spec)
    A = subsample(A, SUBSAMPLE)
    B = A.copy()                                  # moving = a copy -> perfect array bridge (self)
    coords = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    gt, have = array_bridge(A, B)
    return dict(A=A, B=B, coords=coords, pitch=pitch, gt=gt, have=have)


def score_cell(ds_name, kind, pair, sev, seed):
    stage(f"{ds_name}:s{sev:g}:seed{seed}:paste2")
    t0 = time.time()
    try:
        base_px, cached = hv.paste2_base(ds_name, pair, sev, seed)
    except Exception as e:                           # noqa: BLE001
        hv.append_row(dict(dataset=ds_name, kind=kind, severity=sev, seed=seed,
                           config="paste2", status="error",
                           detail=f"paste2 {type(e).__name__}: {e}"[:180], timestamp=_now()))
        log(f"[{ds_name}] s{sev:g} seed{seed} PASTE2 FAILED/timeout: {e!r}")
        return
    stage(f"{ds_name}:s{sev:g}:seed{seed}:score")
    try:
        w, _ = apply_warp(pair["B"], sev, seed=seed, tear=True)
        moving = np.asarray(w.obsm["spatial"], np.float32)
        pitch, gt, have = pair["pitch"], pair["gt"], pair["have"]

        def err(p):
            return registration_error_stats(p, gt, mask=have)["median"] / pitch
        base_err = err(base_px)
        hv.append_row(dict(dataset=ds_name, kind=kind, severity=sev, seed=seed, config="paste2",
                           err_pitch=round(base_err, 4), paste2_err=round(base_err, 4),
                           beats_paste2=True, n=int(have.sum()), pitch=round(pitch, 1),
                           status="ok", timestamp=_now()))
        cells = [f"paste2={base_err:.2f}"]
        for cfg, order in ORDERS.items():
            pred = gr.gate_refine(base_px, moving, order=order, pitch=pitch)
            e = err(pred)
            hv.append_row(dict(dataset=ds_name, kind=kind, severity=sev, seed=seed, config=cfg,
                               err_pitch=round(e, 4), paste2_err=round(base_err, 4),
                               beats_paste2=bool(e <= base_err), n=int(have.sum()),
                               pitch=round(pitch, 1), status="ok", timestamp=_now()))
            cells.append(f"{cfg.replace('gated_','')}={e:.2f}")
        tag = "cache" if cached else f"{time.time()-t0:.0f}s"
        log(f"[{ds_name}] s{sev:g} seed{seed}: " + " ".join(cells) + f" ({tag})")
    except Exception as e:                           # noqa: BLE001
        hv.append_row(dict(dataset=ds_name, kind=kind, severity=sev, seed=seed, config="(score)",
                           status="error", detail=f"{type(e).__name__}: {e}"[:180], timestamp=_now()))
        log(f"[{ds_name}] s{sev:g} seed{seed} SCORE FAILED: {e!r}\n{traceback.format_exc()}")


def main():
    global _HB_STOP
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--datasets", default="")
    p.add_argument("--seeds", default="")
    args = p.parse_args()

    cross = {k: (v, "dlpfc_cross") for k, v in DLPFC_B.items()}
    selfd = {k: (v, "self") for k, v in SELF.items()}
    allds = {**cross, **selfd}
    # DEFAULT = the 3 new DLPFC CROSS-section pairs (the only valid remaining regime: real
    # adjacent sections with differing expression, where PASTE2 is good-but-imperfect). The
    # single-section tissues are degenerate under identical-copy self-alignment (PASTE2 ~0, so
    # nothing to refine) - available via explicit --datasets for the boundary note, not the default.
    names = [d.strip() for d in args.datasets.split(",") if d.strip()] or list(cross)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()] or SEEDS
    if args.smoke:
        names, seeds = ["kidney"], [0]

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    log("=" * 80)
    log(f"hybrid_robustness START datasets={names} seeds={seeds} smoke={args.smoke}")
    log(f"gate=gate_refine {list(ORDERS)} | subsample(self)={SUBSAMPLE} | cache={hv.CACHE}")
    log("=" * 80)

    t_all = time.time()
    for seed in seeds:
        for name in names:
            if name not in allds:
                log(f"unknown dataset {name}"); continue
            spec, kind = allds[name]
            sevs = ([0.0, 4.0] if args.smoke else
                    (DLPFC_SEVS if kind == "dlpfc_cross" else SELF_SEVS))
            try:
                stage(f"{name}:build")
                pair = build_cross(*spec) if kind == "dlpfc_cross" else build_self(spec)
                log(f"[{name}] built ({kind}): A={pair['A'].n_obs} B={pair['B'].n_obs} "
                    f"pitch={pair['pitch']:.1f} bridge={pair['have'].mean()*100:.0f}%")
                for sev in sevs:
                    score_cell(name, kind, pair, sev, seed)
            except Exception as e:                   # noqa: BLE001
                log(f"[{name}] DATASET FAILED: {e!r}\n{traceback.format_exc()}")
                hv.append_row(dict(dataset=name, kind=kind, config="(build)", status="error",
                                   detail=f"{type(e).__name__}: {e}"[:180], timestamp=_now()))
        log(f"=== seed {seed} pass done ({time.time()-t_all:.0f}s) ===")

    _HB_STOP = True
    log(f"hybrid_robustness DONE total={time.time()-t_all:.0f}s")
    log("DONE")


if __name__ == "__main__":
    main()
