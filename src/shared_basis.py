"""
Fix A — a shared, FROZEN TruncatedSVD feature basis for the Sutura cross-slice
model.

The pretrained model collapsed off its training donor because node features were a
TruncatedSVD re-fit *per section*: SVD directions are only defined up to sign/
rotation, so every re-fit handed the encoder a differently-oriented basis. This
module fits ONE SVD basis on a pooled multi-donor reference set, freezes it
(directions AND the per-component standardization stats), and applies it by
transform-only to every section — training or test — so features mean the same
thing everywhere.

Basis file (results/shared_basis.npz):
  genes       (G,)      canonical gene order the basis was fit on
  components  (D, G)    SVD directions V^T  (transform = X_norm @ components.T)
  feat_mean   (D,)      per-component mean of the pooled reference projection
  feat_std    (D,)      per-component std  of the pooled reference projection
  meta        dict-ish  donors, dim, seed (stored as 0-d object array)

Usage:
  python src/shared_basis.py            # fit on Br5292+Br5595+Br8100, save npz
"""
from __future__ import annotations

from pathlib import Path

import anndata as ad
import numpy as np
from scipy.sparse import issparse
from sklearn.decomposition import TruncatedSVD

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
BASIS_PATH = RESULTS / "shared_basis.npz"

# Pooled reference set for the frozen basis: all three DLPFC donors, both slices
# each. Note: the held-out donor Br8100 contributes to the (unsupervised) basis by
# design — the basis is a shared reference atlas — but never to supervised training.
BASIS_SLICES = [
    DATA / "DLPFC_151507.h5ad", DATA / "DLPFC_151508.h5ad",   # Br5292
    DATA / "DLPFC_151669.h5ad", DATA / "DLPFC_151670.h5ad",   # Br5595
    DATA / "DLPFC_151673.h5ad", DATA / "DLPFC_151674.h5ad",   # Br8100
]


def lognorm_matrix(adata: ad.AnnData, genes: np.ndarray) -> np.ndarray:
    """Reindex to `genes`, library-normalize to 1e4, log1p. Returns dense (n,G)."""
    idx = adata.var_names.get_indexer(genes)
    if (idx < 0).any():
        raise ValueError("section is missing basis genes; cannot transform")
    X = adata.X
    X = X.tocsc()[:, idx] if issparse(X) else np.asarray(X, np.float32)[:, idx]
    X = np.asarray(X.todense(), np.float32) if issparse(X) else X
    counts = X.sum(1, keepdims=True)
    counts[counts == 0] = 1.0
    return np.log1p(X * (1e4 / counts)).astype(np.float32)


def fit_basis(slices, dim=50, seed=0) -> dict:
    """Fit ONE SVD basis on pooled log1p expression; freeze directions + z-stats."""
    ref = ad.read_h5ad(slices[0])
    genes = np.asarray(ref.var_names)
    mats = [lognorm_matrix(ad.read_h5ad(s), genes) for s in slices]
    pooled = np.vstack(mats)
    svd = TruncatedSVD(n_components=dim, random_state=seed)
    Z = svd.fit_transform(pooled)              # (N, D)
    return dict(
        genes=genes, components=svd.components_.astype(np.float32),
        feat_mean=Z.mean(0).astype(np.float32),
        feat_std=(Z.std(0) + 1e-6).astype(np.float32),
        meta=np.array({"donors": [Path(s).stem for s in slices],
                       "dim": dim, "seed": seed, "n_pooled": int(pooled.shape[0])},
                      dtype=object))


def save_basis(basis: dict, path: Path = BASIS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **basis)
    m = basis["meta"].item()
    print(f"saved frozen basis -> {path}")
    print(f"  genes={len(basis['genes'])} dim={basis['components'].shape[0]} "
          f"pooled_spots={m['n_pooled']} donors={m['donors']}")


def load_basis(path: Path = BASIS_PATH) -> dict:
    d = np.load(path, allow_pickle=True)
    return {k: d[k] for k in d.files}


def transform(adata: ad.AnnData, basis: dict) -> np.ndarray:
    """Frozen-basis node features: transform ONLY, never re-fit."""
    Xn = lognorm_matrix(adata, basis["genes"])
    Z = Xn @ basis["components"].T                       # (n, D)
    return ((Z - basis["feat_mean"]) / basis["feat_std"]).astype(np.float32)


if __name__ == "__main__":
    basis = fit_basis(BASIS_SLICES, dim=50, seed=0)
    save_basis(basis)
