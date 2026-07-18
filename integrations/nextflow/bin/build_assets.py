#!/usr/bin/env python3
"""
build_assets.py - precompute the small, portable engine assets the container ships with.

The distribution router (in-distribution vs off-distribution) needs the training-donor
embedding distribution (mean + inverse covariance in the frozen-basis space). The research
code recomputes this at import time by reading four ~100 MB DLPFC h5ad files. That is fine
on the research workstation but far too heavy for a container.

This script computes that reference ONCE from the training donors and writes a tiny
``dist_reference.npz`` (a 50-vector mean + a 50x50 inverse covariance, a few KB) plus copies
the frozen basis and checkpoint into ``assets/`` so the runtime image is fully self-contained
and never needs the raw training data.

Run on the research workstation (where data/ exists):
    python integrations/nextflow/bin/build_assets.py --engine-root <repo-root>
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np


TRAIN_FILES = [
    "DLPFC_151507.h5ad", "DLPFC_151508.h5ad",   # Br5292
    "DLPFC_151669.h5ad", "DLPFC_151670.h5ad",   # Br5595
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine-root", default=None,
                    help="repo root containing src/, results/, data/ (default: auto-detect)")
    ap.add_argument("--assets", default=None,
                    help="output assets dir (default: integrations/nextflow/assets)")
    args = ap.parse_args()

    here = Path(__file__).resolve()
    root = Path(args.engine_root) if args.engine_root else here.parents[3]
    assets = Path(args.assets) if args.assets else here.parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    src = root / "src"
    results = root / "results"
    data = root / "data"
    sys.path.insert(0, str(src))

    from shared_basis import load_basis
    import anndata as ad
    import scipy.sparse as sp

    basis = load_basis(results / "shared_basis.npz")
    genes = np.asarray(basis["genes"])
    gpos = {g: i for i, g in enumerate(genes)}
    comp, mu, sd = basis["components"], basis["feat_mean"], basis["feat_std"]

    def project(a):
        vn = np.asarray(a.var_names)
        keep = [(j, gpos[g]) for j, g in enumerate(vn) if g in gpos]
        X = a.X.tocsc() if sp.issparse(a.X) else np.asarray(a.X, np.float32)
        M = np.zeros((a.n_obs, len(genes)), np.float32)
        if keep:
            s = [j for j, _ in keep]
            d = [c for _, c in keep]
            sub = X[:, s].toarray() if sp.issparse(X) else X[:, s]
            M[:, d] = sub
        counts = M.sum(1, keepdims=True)
        counts[counts == 0] = 1.0
        return (((np.log1p(M * (1e4 / counts)) @ comp.T) - mu) / sd).astype(np.float32)

    embeds = []
    for f in TRAIN_FILES:
        p = data / f
        if not p.exists():
            print(f"WARNING: training file missing, skipping: {p}", file=sys.stderr)
            continue
        embeds.append(project(ad.read_h5ad(p)))
    if not embeds:
        raise SystemExit("no training files found; cannot build distribution reference")

    train = np.vstack(embeds)
    tmu = train.mean(0)
    cov = np.cov(train.T) + 1e-3 * np.eye(train.shape[1])
    tinv = np.linalg.inv(cov)

    out = assets / "dist_reference.npz"
    np.savez_compressed(out, tmu=tmu.astype(np.float32), tinv=tinv.astype(np.float32),
                        n_train_spots=np.int64(train.shape[0]),
                        train_files=np.asarray([f for f in TRAIN_FILES]))
    print(f"wrote {out}  (tmu {tmu.shape}, tinv {tinv.shape}, "
          f"{train.shape[0]} training spots)")

    # copy the frozen basis + checkpoint so the container is self-contained
    for name in ["shared_basis.npz", "arca_shared_basis.pt"]:
        src_f = results / name
        if src_f.exists():
            shutil.copy2(src_f, assets / name)
            kb = (assets / name).stat().st_size / 1024
            print(f"copied {name} -> assets/  ({kb:.0f} KB)")
        else:
            print(f"WARNING: {src_f} not found; container will need results/ mounted",
                  file=sys.stderr)

    # vendor the minimal engine-code closure so the container build context
    # (integrations/nextflow/) is fully self-contained. These are the exact modules the
    # deploy path imports; copied verbatim so the image ships the code it was validated
    # against. Local (non-container) runs still use the live repo src/, never this copy.
    engine_out = here.parent.parent / "engine"
    engine_out.mkdir(parents=True, exist_ok=True)
    ENGINE_MODULES = ["shared_basis.py", "train_cross.py", "train.py",
                      "scoring.py", "gate_refine.py", "warp_slice.py"]
    (engine_out / "__init__.py").write_text(
        "# vendored Sutura engine modules (see build_assets.py); do not edit by hand\n")
    for name in ENGINE_MODULES:
        s = src / name
        if not s.exists():
            print(f"WARNING: engine module missing, container may not import: {s}",
                  file=sys.stderr)
            continue
        shutil.copy2(s, engine_out / name)
    print(f"vendored {len(ENGINE_MODULES)} engine modules -> engine/")


if __name__ == "__main__":
    main()
