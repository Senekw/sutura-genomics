"""Native cross-mode reality check on the external breast pair (S1 <- S2).

The self-warp benchmark (external_generalization.py) is confounded: it needs a
warped self-copy (identical expression -> trivial for PASTE2) and the checkpoint
is not a self-aligner. This script instead runs the model in the regime it was
actually trained for — two DIFFERENT real sections — aligning real Section 2 into
Section 1's frame, zero-shot. There is no exact per-spot GT across independent
captures, so we report method-NEUTRAL proxies of whether the alignment is sane:

  * spread ratio  = mean std of mapped-B coords / mean std of A coords. ~1 means
    B is spread across A's footprint; ->0 means the mapping collapsed (e.g. to a
    centroid), which is the failure signature we saw in self-mode.
  * footprint coverage = fraction of A spots with a mapped-B spot within 1 pitch.
  * expression coherence = median cosine similarity between each mapped-B spot's
    expression and the mean expression of its k nearest A spots (by mapped
    position). Higher = the alignment puts transcriptionally similar spots
    together. (Favors expression methods somewhat, but a collapsed mapping still
    scores poorly because neighborhoods become meaningless.)

Run: C:/Users/karti/arca/.venv/Scripts/python.exe research/validation/external_cross_check.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import anndata as ad
import scanpy as sc
import torch
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from train_cross import ARCACrossNet, cross_features, graph_tensors  # noqa: E402
from scoring import barycentric_projection  # noqa: E402
from paste2.PASTE2 import partial_pairwise_align  # noqa: E402
from paste2.helper import filter_for_common_genes  # noqa: E402

DATA = ROOT / "data" / "external"
CKPT = ROOT / "results" / "arca_cross.pt"
KNN, PCA_DIM, FEAT_SEED, MAX = 6, 50, 0, 1200


def load(tag):
    a = ad.read_h5ad(DATA / f"{tag}.h5ad")
    a.var_names_make_unique()
    sc.pp.filter_genes(a, min_cells=3)
    if a.n_obs > MAX:
        keep = np.sort(np.random.default_rng(0).choice(a.n_obs, MAX, replace=False))
        a = a[keep].copy()
    return a


def lognorm_dense(a):
    b = a.copy()
    sc.pp.normalize_total(b, target_sum=1e4)
    sc.pp.log1p(b)
    X = b.X
    return np.asarray(X.todense()) if hasattr(X, "todense") else np.asarray(X)


def coherence(mapped, a_coords, Xb, Xa, k=6):
    """median cosine sim of each B spot vs mean of its k nearest A spots."""
    tree = cKDTree(a_coords)
    _, nn = tree.query(mapped, k=k)
    nbr = Xa[nn].mean(1)                       # (nB, G)
    bn = Xb / (np.linalg.norm(Xb, axis=1, keepdims=True) + 1e-9)
    an = nbr / (np.linalg.norm(nbr, axis=1, keepdims=True) + 1e-9)
    return float(np.median((bn * an).sum(1)))


def metrics(name, mapped, A_coords, Xb, Xa, pitch):
    # partial OT can leave some B spots with ~zero transported mass -> NaN coords
    finite = np.isfinite(mapped).all(1)
    if not finite.all():
        mapped, Xb = mapped[finite], Xb[finite]
    spread = float(mapped.std(0).mean() / A_coords.std(0).mean())
    d, _ = cKDTree(mapped).query(A_coords, k=1)
    coverage = float((d < pitch).mean())
    coh = coherence(mapped, A_coords, Xb, Xa)
    print(f"  {name:8s} | spread {spread:5.2f} | coverage {coverage:5.2f} | "
          f"expr-coherence {coh:5.3f}")
    return dict(method=name, spread=spread, coverage=coverage, coherence=coh)


def main():
    A = load("breast_A_S1")   # reference
    B = load("breast_A_S2")   # moving (real, different section)
    # Subset both to a shared gene order (S1/S2 gene sets differ after filtering).
    common = A.var_names.intersection(B.var_names)
    A, B = A[:, common].copy(), B[:, common].copy()
    a_coords = np.asarray(A.obsm["spatial"], np.float32)
    pitch = float(np.median(cKDTree(a_coords).query(a_coords, k=2)[0][:, 1]))
    Xa, Xb = lognorm_dense(A), lognorm_dense(B)

    Z_A, Z_B = cross_features(A, B, PCA_DIM, FEAT_SEED)
    model = ARCACrossNet(PCA_DIM, 64, 3, 64)
    model.load_state_dict(torch.load(CKPT, map_location="cpu",
                                     weights_only=False)["state_dict"])
    model.eval()
    ga = graph_tensors(a_coords, Z_A, KNN, pitch)
    gb = graph_tensors(np.asarray(B.obsm["spatial"], np.float32), Z_B, KNN, pitch)
    a_norm = torch.from_numpy(a_coords / pitch)

    print("=" * 74)
    print("NATIVE CROSS-MODE reality check — Breast Block A: map S2 -> S1 (zero-shot)")
    print(f"  A(S1)={A.n_obs} B(S2)={B.n_obs} spots | common genes={A.n_vars} | "
          f"pitch={pitch:.1f}px")
    print("=" * 74)

    with torch.no_grad():
        sut = model(ga, gb, a_norm).numpy() * pitch
    metrics("Sutura", sut, a_coords, Xb, Xa, pitch)

    pi = np.asarray(partial_pairwise_align(A, B, s=0.99, alpha=0.1,
                                           dissimilarity="pca", verbose=False))
    pst, _ = barycentric_projection(pi, a_coords)
    metrics("PASTE2", np.asarray(pst, np.float32), a_coords, Xb, Xa, pitch)

    # reference points: A vs itself (upper bound) and B's raw coords (unmapped)
    metrics("A-self", a_coords, a_coords, Xa, Xa, pitch)


if __name__ == "__main__":
    main()
