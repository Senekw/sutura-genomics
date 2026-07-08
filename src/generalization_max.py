"""
Generalization-max: push the shared-basis Sutura model to generalize to unseen
donors, evaluated with leave-one-donor-out (LODO) CV on the tear benchmark
(median error, spot-pitches). The frozen shared basis is kept throughout (re-fit
per fold on TRAINING donors only, transform-only).

Interventions (composable via Config):
  - donor diversity / pairs : train on 1 or 2 donors, 1 or 2 adjacent pairs each
  - augmentation + reg      : feature dropout/noise, spot subsample, batch shift,
                              wider tears + random rotation, weight decay, early stop
  - feature backend         : all-gene SVD ('svd') or shared-HVG SVD ('hvg')
  - loss terms              : correspondence-contrastive (InfoNCE) + spatial
                              displacement-smoothness regularizer

Only 3 DLPFC donors exist (Br5292/Br5595/Br8100), so LODO is 3-fold and max donor
diversity is 2 training donors. Results (in-dist, held-out, PASTE2) are appended to
results/generalization_max.csv.

Usage:
  python src/generalization_max.py --config baseline --lodo
  python src/generalization_max.py --matrix        # run the whole ranked matrix
"""
from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import anndata as ad
import numpy as np
import torch
import torch.nn.functional as F
from scipy.sparse import issparse
from scipy.spatial import cKDTree
from sklearn.decomposition import TruncatedSVD

from train_cross import ARCACrossNet, graph_tensors, array_bridge
from warp_slice import apply_warp
from scoring import registration_error_stats

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

DONORS = {
    "Br5292": [("DLPFC_151507", "DLPFC_151508"), ("DLPFC_151509", "DLPFC_151510")],
    "Br5595": [("DLPFC_151669", "DLPFC_151670"), ("DLPFC_151671", "DLPFC_151672")],
    "Br8100": [("DLPFC_151673", "DLPFC_151674"), ("DLPFC_151675", "DLPFC_151676")],
}
# PASTE2 held-out baselines (full-res, tear sev-avg 0-8) from prior sweeps
PASTE2 = {"Br5292": 5.28, "Br5595": 4.35, "Br8100": 3.46}
EVAL_SEVS = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
HP = dict(hidden=64, layers=3, attn_dim=64, knn=6, pca_dim=50)


@dataclass
class Config:
    name: str
    feature: str = "svd"            # svd | hvg
    pairs_per_donor: int = 1
    n_train_donors: int = 2         # 1 or 2 (2 = max diversity)
    augment: bool = False
    weight_decay: float = 0.0
    early_stop: bool = False
    contrastive: float = 0.0
    spatial: float = 0.0
    epochs: int = 50
    steps_per_epoch: int = 20
    lr: float = 1e-3
    hvg_n: int = 2000


# --------------------------------------------------------------------------- #
# per-fold frozen basis (fit on TRAINING donors only)
# --------------------------------------------------------------------------- #
def _lognorm(X, cols=None):
    X = X.tocsc()[:, cols] if (issparse(X) and cols is not None) else X
    X = np.asarray(X.todense(), np.float32) if issparse(X) else np.asarray(X, np.float32)
    if cols is not None and not issparse(X):
        X = X[:, cols]
    c = X.sum(1, keepdims=True); c[c == 0] = 1.0
    return np.log1p(X * (1e4 / c)).astype(np.float32)


def fit_fold_basis(train_slices, feature, dim, hvg_n):
    ref = ad.read_h5ad(DATA / f"{train_slices[0]}.h5ad")
    genes = np.asarray(ref.var_names)
    mats = [_lognorm(ad.read_h5ad(DATA / f"{s}.h5ad").X) for s in train_slices]
    pooled = np.vstack(mats)
    if feature == "hvg":
        # variance-based HVG selection on pooled TRAIN expression (shared across donors)
        v = pooled.var(0)
        keep = np.argsort(v)[-hvg_n:]
        keep.sort()
        genes = genes[keep]; pooled = pooled[:, keep]
    svd = TruncatedSVD(n_components=dim, random_state=0)
    Z = svd.fit_transform(pooled)
    return dict(genes=genes, components=svd.components_.astype(np.float32),
                feat_mean=Z.mean(0).astype(np.float32),
                feat_std=(Z.std(0) + 1e-6).astype(np.float32))


def transform(adata, basis):
    gpos = {g: j for j, g in enumerate(adata.var_names)}
    keep = [(bi, gpos[g]) for bi, g in enumerate(basis["genes"]) if g in gpos]
    X = adata.X.tocsc() if issparse(adata.X) else np.asarray(adata.X, np.float32)
    M = np.zeros((adata.n_obs, len(basis["genes"])), np.float32)
    if keep:
        bc = [b for b, _ in keep]; sc = [s for _, s in keep]
        sub = X[:, sc].toarray() if issparse(X) else X[:, sc]
        M[:, bc] = sub
    c = M.sum(1, keepdims=True); c[c == 0] = 1.0
    Z = (np.log1p(M * (1e4 / c)) @ basis["components"].T - basis["feat_mean"]) / basis["feat_std"]
    return Z.astype(np.float32)


# --------------------------------------------------------------------------- #
# pair prep + augmentation
# --------------------------------------------------------------------------- #
def prep_pair(ref_name, mov_name, basis, knn):
    A = ad.read_h5ad(DATA / f"{ref_name}.h5ad"); B = ad.read_h5ad(DATA / f"{mov_name}.h5ad")
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B.obsm["spatial"] = np.asarray(B.obsm["spatial"], float)
    coords = A.obsm["spatial"]
    pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
    gt, have = array_bridge(A, B)
    gt_safe = gt.copy(); gt_safe[~have] = coords.mean(0)
    tgt = cKDTree(coords).query(gt_safe)[1]        # nearest A index per B spot (bridge)
    Z_A = transform(A, basis)
    return dict(A=A, B=B, coords=coords, pitch=pitch, Z_A=Z_A, Z_B=transform(B, basis),
                ga=graph_tensors(coords, Z_A, knn, pitch),
                a_norm=torch.from_numpy((coords / pitch).astype(np.float32)),
                gt_norm=torch.from_numpy((gt_safe / pitch).astype(np.float32)),
                gt=gt, mask=torch.from_numpy(have), have=have,
                tgt=torch.from_numpy(tgt).long(), knn=knn)


def augment_move(p, sev, rng, cfg):
    """Return (warped_coords, Z_B_aug) with domain randomization applied."""
    B = p["B"]; Z = p["Z_B"].copy()
    tear = rng.random() < 0.6
    w, _ = apply_warp(B, sev, seed=int(rng.integers(1, 99999)), tear=tear)
    coords = np.asarray(w.obsm["spatial"], float).copy()
    if cfg.augment:
        # random rotation about centroid
        th = rng.uniform(-np.pi, np.pi); c, s = np.cos(th), np.sin(th)
        cen = coords.mean(0); coords = (coords - cen) @ np.array([[c, -s], [s, c]]) + cen
        # feature dropout + gaussian noise + per-feature batch shift/scale
        drop = rng.random(Z.shape[1]) < 0.1; Z[:, drop] = 0.0
        Z = Z + rng.normal(0, 0.1, Z.shape).astype(np.float32)
        Z = Z * (1 + rng.normal(0, 0.05, Z.shape[1]).astype(np.float32)) + \
            rng.normal(0, 0.05, Z.shape[1]).astype(np.float32)
    return coords, Z.astype(np.float32)


def spatial_loss(pred_norm, coords, knn, pitch):
    """Smoothness of predicted displacement over the moving kNN graph."""
    g = graph_tensors(coords, np.zeros((len(coords), 1), np.float32), knn, pitch)
    idx = g["edge_index"]
    disp = pred_norm - torch.from_numpy((coords / pitch).astype(np.float32))
    return ((disp[idx[0]] - disp[idx[1]]) ** 2).sum(1).mean()


# --------------------------------------------------------------------------- #
# train one fold
# --------------------------------------------------------------------------- #
def train_fold(cfg, train_donors, held_out):
    rng = np.random.default_rng(0); torch.manual_seed(0)
    train_slices = [s for d in train_donors for pr in DONORS[d][:cfg.pairs_per_donor] for s in pr]
    basis = fit_fold_basis(train_slices, cfg.feature, HP["pca_dim"], cfg.hvg_n)
    dim = basis["components"].shape[0]

    train_pairs = []
    for d in train_donors:
        for pr in DONORS[d][:cfg.pairs_per_donor]:
            train_pairs.append(prep_pair(pr[0], pr[1], basis, HP["knn"]))
    # eval pairs
    ho_pair = prep_pair(*DONORS[held_out][0], basis, HP["knn"])          # held-out donor
    id_pair = prep_pair(*DONORS[train_donors[0]][0], basis, HP["knn"])   # in-distribution

    model = ARCACrossNet(dim, HP["hidden"], HP["layers"], HP["attn_dim"])
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)

    def eval_pair(p, sevs=EVAL_SEVS, seed=0):
        model.eval(); errs = []
        for sv in sevs:
            w, _ = apply_warp(p["B"], sv, seed=seed, tear=True)
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), p["Z_B"], p["knn"], p["pitch"])
            with torch.no_grad():
                pred = model(p["ga"], gb, p["a_norm"]).numpy() * p["pitch"]
            errs.append(registration_error_stats(pred, p["gt"], mask=p["have"])["median"] / p["pitch"])
        return float(np.mean(errs))

    best_val = 1e9; best_state = None; bad = 0; sev_hi = 8.0
    for epoch in range(cfg.epochs):
        model.train()
        for _ in range(cfg.steps_per_epoch):
            p = train_pairs[int(rng.integers(len(train_pairs)))]
            sev = float(rng.uniform(0, 10.0 if cfg.augment else sev_hi))
            coords, Zb = augment_move(p, sev, rng, cfg)
            n = coords.shape[0]
            if cfg.augment and n > 500 and rng.random() < 0.5:          # spot subsample
                sel = np.sort(rng.choice(n, int(n * rng.uniform(0.7, 1.0)), replace=False))
            else:
                sel = np.arange(n)
            coords_s, Zb_s = coords[sel], Zb[sel]
            gt_norm, mask, tgt = p["gt_norm"][sel], p["mask"][sel], p["tgt"][sel]
            gb = graph_tensors(coords_s, Zb_s, p["knn"], p["pitch"])
            opt.zero_grad()
            if cfg.contrastive > 0:
                pred, match = model(p["ga"], gb, p["a_norm"], return_match=True)
            else:
                pred = model(p["ga"], gb, p["a_norm"])
            loss = (pred - gt_norm)[mask].norm(dim=1).mean()
            if cfg.contrastive > 0 and mask.any():
                # correspondence-contrastive InfoNCE: each matched B spot should pick
                # its array-bridge A partner; negatives are all other A spots
                logits = match["cos_sim"][mask] / 0.1                  # (n_matched, n_A)
                loss = loss + cfg.contrastive * F.cross_entropy(logits, tgt[mask])
            if cfg.spatial > 0:
                loss = loss + cfg.spatial * spatial_loss(pred, coords_s, p["knn"], p["pitch"])
            loss.backward(); opt.step()
        if cfg.early_stop and (epoch % 5 == 0 or epoch == cfg.epochs - 1):
            v = eval_pair(id_pair, sevs=[2.0, 6.0], seed=555)   # in-dist val (held-out seed)
            if v < best_val - 1e-3:
                best_val = v; best_state = {k: t.clone() for k, t in model.state_dict().items()}; bad = 0
            else:
                bad += 1
                if bad >= 4:
                    break
    if best_state is not None:
        model.load_state_dict(best_state)

    return dict(in_dist=round(eval_pair(id_pair), 3), held_out=round(eval_pair(ho_pair), 3),
                n_train_pairs=len(train_pairs), dim=dim)


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def run_config(cfg, lodo, out_csv):
    donors = list(DONORS)
    folds = donors if lodo else ["Br8100"]
    rows = []
    for ho in folds:
        others = [d for d in donors if d != ho]
        train_donors = others if cfg.n_train_donors == 2 else others[:1]
        t0 = time.time()
        r = train_fold(cfg, train_donors, ho)
        dt = time.time() - t0
        row = dict(config=cfg.name, feature=cfg.feature, pairs_per_donor=cfg.pairs_per_donor,
                   n_train_donors=len(train_donors), augment=cfg.augment,
                   weight_decay=cfg.weight_decay, early_stop=cfg.early_stop,
                   contrastive=cfg.contrastive, spatial=cfg.spatial,
                   held_out_donor=ho, train_donors="+".join(train_donors),
                   in_dist_error=r["in_dist"], held_out_error=r["held_out"],
                   paste2_error=PASTE2[ho], beats_paste2=bool(r["held_out"] <= PASTE2[ho]),
                   n_train_pairs=r["n_train_pairs"], epochs=cfg.epochs, seconds=round(dt, 1))
        rows.append(row)
        print(f"  [{cfg.name}] hold-out {ho}: in-dist={r['in_dist']} held-out={r['held_out']} "
              f"(PASTE2 {PASTE2[ho]})  {dt:.0f}s", flush=True)
        _append(out_csv, row)
    ho_mean = float(np.mean([r["held_out_error"] for r in rows]))
    print(f"  [{cfg.name}] LODO mean held-out = {ho_mean:.2f} pitch", flush=True)
    return rows


def _append(path, row):
    path = Path(path); exists = path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if not exists:
            w.writeheader()
        w.writerow(row)


MATRIX = [
    Config("baseline_1donor", n_train_donors=1, pairs_per_donor=1),
    Config("baseline_2donor", n_train_donors=2, pairs_per_donor=1),
    Config("diversity_2donor_2pair", n_train_donors=2, pairs_per_donor=2),
    Config("augment_reg", n_train_donors=2, pairs_per_donor=2, augment=True,
           weight_decay=1e-4, early_stop=True, epochs=60),
    Config("hvg_features", n_train_donors=2, pairs_per_donor=2, feature="hvg",
           augment=True, weight_decay=1e-4, early_stop=True, epochs=60),
    Config("contrastive_spatial", n_train_donors=2, pairs_per_donor=2, augment=True,
           weight_decay=1e-4, contrastive=0.2, spatial=0.1, early_stop=True, epochs=60),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", action="store_true")
    p.add_argument("--config", default="")
    p.add_argument("--lodo", action="store_true")
    p.add_argument("--full-lodo-configs", default="baseline_2donor,diversity_2donor_2pair,augment_reg",
                   help="configs to run full 3-fold LODO; others run held-out Br8100 only")
    p.add_argument("--out", default="generalization_max.csv")
    args = p.parse_args()
    out = RESULTS / args.out
    if out.exists() and args.matrix:
        out.unlink()  # fresh matrix run

    full = set(args.full_lodo_configs.split(","))
    cfgs = MATRIX if args.matrix else [c for c in MATRIX if c.name == args.config]
    for cfg in cfgs:
        print(f"\n=== {cfg.name} ===", flush=True)
        run_config(cfg, lodo=(args.lodo or cfg.name in full), out_csv=out)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
