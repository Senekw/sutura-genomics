"""
Batch-corrected shared-basis features for the Sutura cross-slice model
(branch: batch-correct).

Pipeline (the shared FROZEN SVD basis is kept as the feature extractor throughout):
    raw counts -> lib-norm + log1p -> FROZEN SVD projection (shared_basis.transform)
              -> [donor batch integration] -> per-component standardization -> features

Two integrations are tried, both operating on the frozen-basis 50-d embedding with
DONOR as the batch variable (section-level variation within a donor is the signal
the model needs, so it is NOT treated as batch). Integrating in the frozen-embedding
space — rather than in gene space — keeps the shared frozen basis intact and is
Harmony's native input space, and it lets Harmony and Scanorama be compared in the
same space and output dimension.

    none       — frozen-basis features unchanged (the shared-basis-alone baseline)
    harmony    — harmonypy.run_harmony(Z, donor)         -> corrected 50-d
    scanorama  — scanorama.integrate(per-donor Z blocks) -> integrated 50-d

Integration is transductive across all three donors (Br5292, Br5595, Br8100): the
held-out donor's expression participates in the UNSUPERVISED integration (as it
must — Harmony/Scanorama have no out-of-sample transform), but never in supervised
training. This is stated as a caveat in FINDINGS_batch_correct.md.

Features are cached to results/batchfeat_<method>.npz (keyed by slice stem) so
train and eval consume byte-identical features.

Usage:
  python src/batch_correct.py --method all
"""
from __future__ import annotations

import argparse
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

from shared_basis import load_basis, transform

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

# donor -> ordered list of (stem, path); order preserved for split-back
SLICES = [
    ("Br5292", "DLPFC_151507"), ("Br5292", "DLPFC_151508"),
    ("Br5595", "DLPFC_151669"), ("Br5595", "DLPFC_151670"),
    ("Br8100", "DLPFC_151673"), ("Br8100", "DLPFC_151674"),
]


def _frozen_embeddings(basis):
    Zs, donors, stems = [], [], []
    for donor, stem in SLICES:
        Z = transform(ad.read_h5ad(DATA / f"{stem}.h5ad"), basis)
        Zs.append(Z); donors.append(donor); stems.append(stem)
    return Zs, donors, stems


def _standardize(mats):
    """Pooled per-component z-score across all sections; return list, same split."""
    pooled = np.vstack(mats)
    mu, sd = pooled.mean(0), pooled.std(0) + 1e-6
    return [((m - mu) / sd).astype(np.float32) for m in mats]


def build(method: str, seed: int = 0) -> dict:
    basis = load_basis()
    Zs, donors, stems = _frozen_embeddings(basis)
    counts = [len(z) for z in Zs]

    if method == "none":
        feats = Zs  # frozen-basis features, unchanged (shared-basis-alone)

    elif method == "harmony":
        from harmonypy import run_harmony
        Zall = np.vstack(Zs)
        meta = pd.DataFrame({"donor": np.repeat(donors, counts)})
        ho = run_harmony(Zall, meta, ["donor"], random_state=seed)
        Zc = np.asarray(ho.Z_corr).T
        feats, off = [], 0
        for c in counts:
            feats.append(Zc[off:off + c]); off += c
        feats = _standardize(feats)

    elif method == "scanorama":
        import scanorama
        order = ["Br5292", "Br5595", "Br8100"]
        # per-donor blocks (each donor's sections concatenated, order preserved)
        blocks, idx_map = [], []
        for dn in order:
            members = [(i, s) for i, ((d, s)) in enumerate(SLICES) if d == dn]
            blk = np.vstack([Zs[i] for i, _ in members])
            blocks.append(blk); idx_map.append([i for i, _ in members])
        genes = [[f"c{j}" for j in range(Zs[0].shape[1])] for _ in order]
        integ, _ = scanorama.integrate(blocks, genes, dimred=Zs[0].shape[1],
                                       seed=seed, verbose=0)
        feats = [None] * len(SLICES)
        for dn_i, members in enumerate(idx_map):
            blk = integ[dn_i]
            off = 0
            for slice_i in members:
                c = counts[slice_i]
                feats[slice_i] = blk[off:off + c]; off += c
        feats = _standardize(feats)
    else:
        raise ValueError(method)

    out = {stems[i]: feats[i] for i in range(len(SLICES))}
    out["_meta"] = np.array({"method": method, "seed": seed,
                             "donors": donors, "stems": stems}, dtype=object)
    return out


def save(method, seed=0):
    d = build(method, seed)
    path = RESULTS / f"batchfeat_{method}.npz"
    np.savez(path, **d)
    shapes = {k: v.shape for k, v in d.items() if not k.startswith("_")}
    print(f"saved {path.name}: " + ", ".join(f"{k}{v}" for k, v in shapes.items()))
    return path


def load_feats(method):
    d = np.load(RESULTS / f"batchfeat_{method}.npz", allow_pickle=True)
    return {k: d[k] for k in d.files if not k.startswith("_")}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--method", default="all",
                   choices=["all", "none", "harmony", "scanorama"])
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    methods = ["none", "harmony", "scanorama"] if args.method == "all" else [args.method]
    for m in methods:
        save(m, args.seed)
