"""
tear_detect_scan - run the GT-free damage detector across EVERY available dataset and,
on a representative subset, across SYNTHETIC tears (src/warp_slice.apply_warp), writing one
incremental CSV so we can characterize what real damage looks like and compare it head-to-head
with our synthetic benchmark.

Rows carry a `kind`:
    real        - an untouched section (real tissue; whatever damage is intrinsic)
    synthetic   - the same section after apply_warp(tear=True, severity, seed)
    warp_only   - apply_warp(tear=False) (smooth warp, no excision) as a control

Output: research/results/tear_detect.csv     (append-only, resumable via a done-set)
        research/results/tear_detect_scan.log (heartbeat + per-row log)

Detached-friendly: incremental flush per row, per-row try/except, background heartbeat thread.
Usage:
    python research/src/tear_detect_scan.py            # full scan
    python research/src/tear_detect_scan.py --smoke    # a couple datasets only
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent.parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "src"))

import anndata as ad  # noqa: E402
import tear_detect as td  # noqa: E402
from warp_slice import apply_warp  # noqa: E402

OUT = ROOT / "research" / "results"
CSV_PATH = OUT / "tear_detect.csv"
LOG_PATH = OUT / "tear_detect_scan.log"
HEARTBEAT = 20

# synthetic-tear grid (kept modest; enough to trace the severity trend)
SYNTH_SEVS = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
SYNTH_SEEDS = [0, 1]

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


# ------------------------------------------------------------------------- #
# dataset discovery
# ------------------------------------------------------------------------- #
def discover_real():
    """Return list of (name, path, tissue_group)."""
    items = []
    for p in sorted(glob.glob(str(ROOT / "data" / "DLPFC_*.h5ad"))):
        items.append((Path(p).stem, p, "dlpfc"))
    ext = ROOT / "data" / "external"
    for fn, grp in [("V1_Breast_Cancer_Block_A_Section_1.h5ad", "breast"),
                    ("V1_Breast_Cancer_Block_A_Section_2.h5ad", "breast"),
                    ("V1_Mouse_Brain_Sagittal_Posterior.h5ad", "mouse_brain"),
                    ("V1_Mouse_Brain_Sagittal_Posterior_Section_2.h5ad", "mouse_brain"),
                    ("V1_Mouse_Kidney.h5ad", "kidney")]:
        p = ext / fn
        if p.exists():
            items.append((p.stem, str(p), grp))
    for p in sorted(glob.glob(str(ROOT / "research" / "data" / "atlas" / "*.h5ad"))):
        name = Path(p).stem
        grp = "atlas"
        low = name.lower()
        if "cerebell" in low: grp = "cerebellum"
        elif "brain" in low or "glio" in low: grp = "brain_tumor" if "glio" in low else "brain"
        elif "heart" in low: grp = "heart"
        elif "kidney" in low: grp = "kidney"
        elif "breast" in low: grp = "breast"
        elif "colorectal" in low or "ovarian" in low or "spinal" in low: grp = "atlas_other"
        items.append((name, p, grp))
    return items


# representative bases for the synthetic comparison (diverse tissues, all present locally)
SYNTH_BASES = [
    ("DLPFC_151507", ROOT / "data" / "DLPFC_151507.h5ad"),
    ("DLPFC_151508", ROOT / "data" / "DLPFC_151508.h5ad"),
    ("DLPFC_151669", ROOT / "data" / "DLPFC_151669.h5ad"),
    ("breast_A1", ROOT / "data" / "external" / "V1_Breast_Cancer_Block_A_Section_1.h5ad"),
    ("cerebellum", ROOT / "research" / "data" / "atlas" / "Parent_Visium_Human_Cerebellum.h5ad"),
    ("glioblastoma", ROOT / "research" / "data" / "atlas" / "Parent_Visium_Human_Glioblastoma.h5ad"),
    ("mouse_kidney", ROOT / "research" / "data" / "atlas" / "V1_Mouse_Kidney.h5ad"),
]

FIELDS = None  # discovered from the first report row


def _row_dict(rep, kind, tissue, severity, seed, base):
    d = rep.to_row()
    d.update(dict(kind=kind, tissue=tissue, severity=severity, seed=seed,
                  base=base, timestamp=_now()))
    return d


def _load_done():
    done = set()
    if CSV_PATH.exists():
        try:
            import pandas as pd
            df = pd.read_csv(CSV_PATH)
            for _, r in df.iterrows():
                done.add((str(r.get("kind")), str(r.get("name")),
                          str(r.get("severity")), str(r.get("seed"))))
        except Exception:
            pass
    return done


def _append(row):
    global FIELDS
    OUT.mkdir(parents=True, exist_ok=True)
    new = not CSV_PATH.exists()
    if FIELDS is None:
        FIELDS = list(row.keys())
    with open(CSV_PATH, "a", newline="", encoding="ascii", errors="replace") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def main():
    global _HB_STOP
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    log("=" * 80)
    log(f"tear_detect_scan START smoke={args.smoke} csv={CSV_PATH}")

    done = _load_done()
    log(f"resuming: {len(done)} rows already present")

    reals = discover_real()
    bases = SYNTH_BASES
    if args.smoke:
        reals = reals[:2] + [r for r in reals if "Glioblastoma" in r[0]][:1]
        bases = SYNTH_BASES[:1]

    t_all = time.time()

    # ---- real sections ----
    log(f"scanning {len(reals)} real sections ...")
    for name, path, grp in reals:
        key = ("real", name, "nan", "nan")
        if key in done:
            continue
        stage(f"real:{name}")
        t0 = time.time()
        try:
            a = ad.read_h5ad(path)
            a.obsm["spatial"] = np.asarray(a.obsm["spatial"], float)
            rep = td.characterize(a, name)
            _append(_row_dict(rep, "real", grp, float("nan"), float("nan"), name))
            log(f"[real] {name} ({grp}): score={rep.damage_score:.3f} "
                f"{rep.severity_label} voids={rep.n_voids} folds={rep.n_folds} "
                f"tears={rep.n_tears} ({time.time()-t0:.0f}s)")
        except Exception as e:  # noqa: BLE001
            log(f"[real] {name} FAILED: {e!r}\n{traceback.format_exc()}")

    # ---- synthetic tears (+ warp-only control) on representative bases ----
    sevs = [4.0] if args.smoke else SYNTH_SEVS
    seeds = [0] if args.smoke else SYNTH_SEEDS
    log(f"generating synthetic tears on {len(bases)} bases x {len(sevs)} sev x {len(seeds)} seed ...")
    for bname, bpath in bases:
        if not Path(bpath).exists():
            log(f"[synth] base missing: {bpath}")
            continue
        try:
            base = ad.read_h5ad(bpath)
            base.obsm["spatial"] = np.asarray(base.obsm["spatial"], float)
        except Exception as e:  # noqa: BLE001
            log(f"[synth] base load FAILED {bname}: {e!r}")
            continue
        for seed in seeds:
            for sev in sevs:
                for tear, kind in ((True, "synthetic"), (False, "warp_only")):
                    nm = f"{kind}_{bname}_s{sev:g}_seed{seed}"
                    key = (kind, nm, f"{sev}", f"{seed}")
                    if key in done:
                        continue
                    stage(f"{kind}:{bname}:s{sev:g}:seed{seed}")
                    t0 = time.time()
                    try:
                        w, _ = apply_warp(base, sev, seed=seed, tear=tear)
                        w.obsm["spatial"] = np.asarray(w.obsm["spatial"], float)
                        rep = td.characterize(w, nm)
                        _append(_row_dict(rep, kind, "synthetic", sev, seed, bname))
                        log(f"[{kind}] {bname} s{sev:g} seed{seed}: "
                            f"score={rep.damage_score:.3f} fdisp={rep.frac_displaced*100:.0f}% "
                            f"maxresid={rep.max_coord_resid_pitch:.1f}pitch "
                            f"voids={rep.n_voids} ({time.time()-t0:.0f}s)")
                    except Exception as e:  # noqa: BLE001
                        log(f"[{kind}] {nm} FAILED: {e!r}")

    _HB_STOP = True
    log(f"tear_detect_scan DONE total={time.time()-t_all:.0f}s rows_csv={CSV_PATH}")
    log("DONE")


if __name__ == "__main__":
    main()
