"""model-gen-2 timing probe: measure OT-surrogate solve, real PASTE2 solve, and a few
residual training steps so the overnight run can budget how much real-PASTE2 caching is
affordable. Read-only import of the existing src/ harness; writes nothing but stdout."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent.parent          # arca/
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import generalization_max as gm            # noqa: E402
from hybrid_ot import ot_coordinate        # noqa: E402
from warp_slice import apply_warp          # noqa: E402
from scoring import registration_error_stats, barycentric_projection  # noqa: E402

gm.DATA = ROOT / "data"
KNN = gm.HP["knn"]
PCA_DIM = gm.HP["pca_dim"]


def prep_one(ho="Br8100"):
    donors = list(gm.DONORS)
    train_donors = [d for d in donors if d != ho]
    train_slices = [s for d in train_donors for pr in gm.DONORS[d][:2] for s in pr]
    basis = gm.fit_fold_basis(train_slices, "svd", PCA_DIM, 2000)
    pair = gm.prep_pair(*gm.DONORS[ho][0], basis, KNN)
    return pair


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


def main():
    t = time.time()
    pair = prep_one()
    print(f"[probe] prep pair (basis+load): {time.time()-t:.1f}s  "
          f"nA={pair['coords'].shape[0]} nB={pair['B'].n_obs} pitch={pair['pitch']:.1f}",
          flush=True)

    w, _ = apply_warp(pair["B"], 4.0, seed=0, tear=True)
    Z_A = pair["ga"]["x"].numpy()

    t = time.time()
    coord, conf = ot_coordinate(pair["Z_B"], Z_A, pair["a_norm"].numpy())
    ot_s = time.time() - t
    ot_px = coord * pair["pitch"]
    st = registration_error_stats(ot_px, pair["gt"], mask=pair["have"])
    print(f"[probe] OT-surrogate solve: {ot_s:.2f}s  err={st['median']/pair['pitch']:.2f} pitch",
          flush=True)

    t = time.time()
    try:
        base_px = paste2_base(pair["A"], w)
        p2_s = time.time() - t
        st2 = registration_error_stats(base_px, pair["gt"], mask=pair["have"])
        print(f"[probe] REAL PASTE2 solve: {p2_s:.1f}s  err={st2['median']/pair['pitch']:.2f} pitch",
              flush=True)
    except Exception as e:
        print(f"[probe] PASTE2 FAILED: {e!r}", flush=True)
        p2_s = float("nan")

    print(f"\n[probe] BUDGET: one PASTE2 solve ~= {p2_s:.0f}s. "
          f"63 eval solves ~= {63*p2_s/60:.0f} min; +72 train solves ~= {135*p2_s/60:.0f} min total.",
          flush=True)


if __name__ == "__main__":
    main()
