"""Does fine-tuning rescue Sutura's generalization to external breast tissue?

Follow-up to FINDINGS_external.md (pretrained arca_cross.pt does NOT generalize
zero-shot: ~5,270 px, worse than no-op, on breast).

Design (exact-GT, no leakage, "adapt-per-dataset" faithful):
  * We have one external adjacent pair (breast Block A S1, S2) and NO cross-section
    ground truth (independent captures don't share the Visium array frame). The
    only exact-GT supervision is the synthetic self-warp (warp a copy of a real
    section; GT = its original coordinates) — a self-SUPERVISED signal that needs
    no labels, which is exactly what an adapt-per-dataset product would use.
  * FINE-TUNE the pretrained checkpoint on **S1** self-warp pairs, a few epochs.
  * TEST on the fully held-out **S2** (never seen in fine-tuning): standard tear
    sweep sev 0..8, seeds. Compare (a) zero-shot pretrained, (b) fine-tuned,
    (c) PASTE2. -> results/finetune_rescue.csv
  * "Beat PASTE2" caveat: in the self-warp test PASTE2 is trivially ~0 (identical-
    expression copy). To answer "beat PASTE2" fairly we ALSO report the native
    cross-mode proxy (map real S2 -> S1: spread / footprint coverage / expression
    coherence) for pretrained vs fine-tuned vs PASTE2 — where PASTE2 is non-trivial.

Run: C:/Users/karti/arca/.venv/Scripts/python.exe research/validation/finetune_rescue.py
"""
from __future__ import annotations
import argparse, csv, sys
from pathlib import Path

import numpy as np
import anndata as ad
import scanpy as sc
import torch
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from train_cross import ARCACrossNet, cross_features, graph_tensors  # noqa: E402
from warp_slice import apply_warp  # noqa: E402
from scoring import barycentric_projection, registration_error_stats  # noqa: E402
from paste2.PASTE2 import partial_pairwise_align  # noqa: E402

DATA = ROOT / "data" / "external"
RESULTS = ROOT / "results"
CKPT = RESULTS / "arca_cross.pt"
FT_OUT = RESULTS / "arca_cross_breast_ft.pt"
KNN, PCA_DIM, FEAT_SEED = 6, 50, 0
SEVERITIES = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
SEEDS = [0, 9999, 10000]


def load_section(tag, max_spots, seed=0):
    a = ad.read_h5ad(DATA / f"{tag}.h5ad")
    a.var_names_make_unique()
    sc.pp.filter_genes(a, min_cells=3)
    if max_spots and a.n_obs > max_spots:
        keep = np.sort(np.random.default_rng(seed).choice(a.n_obs, max_spots, replace=False))
        a = a[keep].copy()
    return a


def build(A):
    """Self-consistency inference bundle for one section (A == reference frame)."""
    B = A.copy()
    coords = np.asarray(A.obsm["spatial"], np.float32)
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    Z_A, Z_B = cross_features(A, B, PCA_DIM, FEAT_SEED)
    ga = graph_tensors(coords, Z_A, KNN, pitch)
    a_norm = torch.from_numpy(coords / pitch)
    gt = coords.astype(float)
    have = np.ones(A.n_obs, bool)
    return dict(A=A, B=B, coords=coords, pitch=pitch, Z_B=Z_B, ga=ga,
                a_norm=a_norm, gt=gt, have=have)


def fresh_model():
    m = ARCACrossNet(PCA_DIM, 64, 3, 64)
    ck = torch.load(CKPT, map_location="cpu", weights_only=False)
    m.load_state_dict(ck["state_dict"])
    return m


def sutura_median(model, P, sev, seed):
    w, _ = apply_warp(P["B"], sev, seed=seed, tear=True)
    gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32), P["Z_B"], KNN, P["pitch"])
    with torch.no_grad():
        pred = model(P["ga"], gb, P["a_norm"]).numpy() * P["pitch"]
    return registration_error_stats(pred, P["gt"], mask=P["have"])["median"]


def finetune(model, P, epochs, steps, lr, seed=0):
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    gt_norm = torch.from_numpy(P["gt"] / P["pitch"]).float()
    mask = torch.from_numpy(P["have"])
    model.train()
    for ep in range(epochs):
        tot = 0.0
        for _ in range(steps):
            sv = float(rng.uniform(0, 8))
            w, _ = apply_warp(P["B"], sv, seed=int(rng.integers(1, 9999)),
                              tear=bool(rng.random() < 0.5))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], np.float32),
                               P["Z_B"], KNN, P["pitch"])
            opt.zero_grad()
            pred = model(P["ga"], gb, P["a_norm"])
            loss = (pred - gt_norm)[mask].norm(dim=1).mean()
            loss.backward(); opt.step(); tot += loss.item()
        if ep % 10 == 0 or ep == epochs - 1:
            print(f"    ft epoch {ep:3d} | loss {tot/steps:.3f} (pitch units)")
    model.eval()
    return model


# ---- native cross-mode proxy (map real S2 -> S1) ----
def lognorm_dense(a):
    b = a.copy(); sc.pp.normalize_total(b, target_sum=1e4); sc.pp.log1p(b)
    X = b.X
    return np.asarray(X.todense()) if hasattr(X, "todense") else np.asarray(X)


def proxy(name, mapped, a_coords, Xb, Xa, pitch):
    finite = np.isfinite(mapped).all(1)
    mapped, Xb = mapped[finite], Xb[finite]
    spread = float(mapped.std(0).mean() / a_coords.std(0).mean())
    d, _ = cKDTree(mapped).query(a_coords, k=1)
    cov = float((d < pitch).mean())
    tree = cKDTree(a_coords); _, nn = tree.query(mapped, k=6)
    nbr = Xa[nn].mean(1)
    bn = Xb / (np.linalg.norm(Xb, axis=1, keepdims=True) + 1e-9)
    an = nbr / (np.linalg.norm(nbr, axis=1, keepdims=True) + 1e-9)
    coh = float(np.median((bn * an).sum(1)))
    print(f"    {name:16s} | spread {spread:5.2f} | coverage {cov:5.2f} | coherence {coh:5.3f}")
    return dict(method=name, spread=round(spread, 3), coverage=round(cov, 3), coherence=round(coh, 3))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--max-spots", type=int, default=1500)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--lr", type=float, default=5e-4)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()

    S1 = load_section("breast_A_S1", args.max_spots)   # fine-tune section
    S2 = load_section("breast_A_S2", args.max_spots)   # HELD-OUT test section
    ft, te = build(S1), build(S2)

    print("=" * 74)
    print("FINE-TUNE RESCUE — external breast (fine-tune S1, HELD-OUT test S2)")
    print(f"  S1={S1.n_obs} spots  S2={S2.n_obs} spots  pitch~{te['pitch']:.0f}px  "
          f"epochs={args.epochs} steps={args.steps} lr={args.lr}")
    print("=" * 74)

    print("  fine-tuning on S1 self-warp pairs...")
    ftmodel = finetune(fresh_model(), ft, args.epochs, args.steps, args.lr)
    torch.save({"state_dict": ftmodel.state_dict(), "note": "arca_cross fine-tuned on breast S1 self-warp"}, FT_OUT)
    zsmodel = fresh_model(); zsmodel.eval()

    sevs = [0.0, 4.0, 8.0] if args.smoke else SEVERITIES
    seeds = [0] if args.smoke else SEEDS
    rows = []
    print("\n  held-out S2 tear sweep (median px):")
    for sev in sevs:
        for sd in seeds:
            mz = sutura_median(zsmodel, te, sev, sd)
            mf = sutura_median(ftmodel, te, sev, sd)
            # PASTE2 on the same torn self-pair
            w, _ = apply_warp(te["B"], sev, seed=sd, tear=True)
            Aa, Bb = te["A"].copy(), w.copy()
            pi = np.asarray(partial_pairwise_align(Aa, Bb, s=0.99, alpha=0.1,
                                                   dissimilarity="pca", verbose=False))
            pred_b, cm = barycentric_projection(pi, te["coords"])
            mp = registration_error_stats(pred_b, te["gt"], mask=(cm > 0))["median"]
            for meth, val in [("Sutura zero-shot", mz), ("Sutura fine-tuned", mf), ("PASTE2", mp)]:
                rows.append(dict(dataset="Breast_Block_A_S2_heldout", severity=sev,
                                 method=meth, median_error=round(val, 2), seed=sd))
            print(f"    sev={sev:>4} seed={sd:<6} | zero-shot {mz:8.1f} | "
                  f"fine-tuned {mf:8.1f} | PASTE2 {mp:8.1f}")

    # In-set reference: fine-tuned model tested back on S1 (the section it saw).
    # Shows whether fine-tuning fit where applied vs transferred to held-out S2.
    print("\n  in-set check — fine-tuned model on its OWN section S1 (median px):")
    for sev in sevs:
        for sd in seeds:
            mi = sutura_median(ftmodel, ft, sev, sd)
            rows.append(dict(dataset="Breast_Block_A_S1_insample", severity=sev,
                             method="Sutura fine-tuned (in-set)", median_error=round(mi, 2), seed=sd))
            print(f"    sev={sev:>4} seed={sd:<6} | fine-tuned in-set {mi:8.1f}")

    if not args.smoke:
        RESULTS.mkdir(parents=True, exist_ok=True)
        out = RESULTS / "finetune_rescue.csv"
        with open(out, "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=["dataset", "severity", "method", "median_error", "seed"])
            wr.writeheader(); wr.writerows(rows)
        print(f"\n  wrote {out} ({len(rows)} rows)")

        # native cross-mode proxy on real S2 -> S1 (PASTE2 non-trivial here)
        print("\n  native cross-mode proxy (map real S2 -> S1):")
        common = te["A"].var_names.intersection(S2.var_names)
        A = S1[:, S1.var_names.intersection(S2.var_names)].copy()
        B = S2[:, S1.var_names.intersection(S2.var_names)].copy()
        ac = np.asarray(A.obsm["spatial"], np.float32)
        pitch = float(np.median(cKDTree(ac).query(ac, k=2)[0][:, 1]))
        Xa, Xb = lognorm_dense(A), lognorm_dense(B)
        Z_A, Z_B = cross_features(A, B, PCA_DIM, FEAT_SEED)
        ga = graph_tensors(ac, Z_A, KNN, pitch)
        gb = graph_tensors(np.asarray(B.obsm["spatial"], np.float32), Z_B, KNN, pitch)
        an = torch.from_numpy(ac / pitch)
        with torch.no_grad():
            proxy("Sutura zero-shot", zsmodel(ga, gb, an).numpy() * pitch, ac, Xb, Xa, pitch)
            proxy("Sutura fine-tuned", ftmodel(ga, gb, an).numpy() * pitch, ac, Xb, Xa, pitch)
        pi = np.asarray(partial_pairwise_align(A, B, s=0.99, alpha=0.1, dissimilarity="pca", verbose=False))
        pst, _ = barycentric_projection(pi, ac)
        proxy("PASTE2", np.asarray(pst, np.float32), ac, Xb, Xa, pitch)


if __name__ == "__main__":
    main()
