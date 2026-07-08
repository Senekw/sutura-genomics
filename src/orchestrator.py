"""
Agentic alignment orchestrator for Sutura (branch: orchestrator).

Runs the full alignment pipeline autonomously for an input pair of sections and
routes each input to the method that actually wins on it:

  1. Load & QC        - read sections; check spot counts, spatial coords, array
                        indices, expression; stop with a reason if QC fails.
  2. Distribution     - project expression through the FROZEN shared basis and
     check              measure Mahalanobis distance of the input's embedding mean
                        to the training-donor (Br5292+Br5595) distribution, plus
                        gene-vocabulary overlap. Emit an in-distribution confidence.
  3. Method selection - in-distribution (high confidence) -> Sutura (wins here);
                        off-distribution (low confidence)  -> PASTE2 (Sutura
                        collapses cross-donor). Decision + rationale are logged.
  4. Alignment        - run the selected method on the (tear-warped) pair.
  5. Post-align QC     - score the result (median error vs array-bridge GT if
                        available, else a neighbor-consistency proxy); if it is
                        above threshold, retry the alternate method and keep the
                        better result.
  6. Report           - structured record + plain-English summary.

Calibrated on our donors (Br5292/Br5595 in-distribution; Br8100/mouse/breast
off-distribution). Thresholds are configurable via OrchestratorConfig.

Sutura is run live (sub-second). PASTE2's full-resolution GW/OT (~250 s/pair) is
reused from the prior full-resolution sweep via a cache (results/
generalization_sweep.csv) so validation does not recompute identical numbers;
pass use_paste2_cache=False to force live PASTE2.

Usage:
  python src/orchestrator.py                 # validate on all datasets -> CSV
  python src/orchestrator.py --severity 4
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path

import anndata as ad
import numpy as np
import scipy.sparse as sp
import torch
from scipy.spatial import cKDTree

from train_cross import ARCACrossNet, graph_tensors, array_bridge
from warp_slice import apply_warp
from scoring import registration_error_stats, barycentric_projection
from shared_basis import load_basis

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXT = DATA / "external"
RESULTS = ROOT / "results"

# input pairs (reference, moving) + the true class for validation reporting
DATASETS = {
    "Br5292": dict(ref=DATA / "DLPFC_151507.h5ad", mov=DATA / "DLPFC_151508.h5ad",
                   tissue="human DLPFC", truth="in-distribution",
                   prior="DLPFC_Br5292_train"),
    "Br5595": dict(ref=DATA / "DLPFC_151669.h5ad", mov=DATA / "DLPFC_151670.h5ad",
                   tissue="human DLPFC", truth="in-distribution",
                   prior="DLPFC_Br5595"),
    "Br8100": dict(ref=DATA / "DLPFC_151673.h5ad", mov=DATA / "DLPFC_151674.h5ad",
                   tissue="human DLPFC", truth="off-distribution",
                   prior="DLPFC_Br8100"),
    "mouse": dict(ref=EXT / "V1_Mouse_Brain_Sagittal_Posterior.h5ad",
                  mov=EXT / "V1_Mouse_Brain_Sagittal_Posterior_Section_2.h5ad",
                  tissue="mouse brain", truth="off-distribution",
                  prior="MouseBrain_SagPost"),
    "breast": dict(ref=EXT / "V1_Breast_Cancer_Block_A_Section_1.h5ad",
                   mov=EXT / "V1_Breast_Cancer_Block_A_Section_2.h5ad",
                   tissue="human breast cancer", truth="off-distribution",
                   prior="BreastCancer_BlockA"),
}


@dataclass
class OrchestratorConfig:
    maha_threshold: float = 2.5      # Mahalanobis > this  -> off-distribution
    min_gene_overlap: float = 0.5    # overlap < this      -> off-distribution (gate)
    conf_steepness: float = 1.5      # sigmoid steepness for the confidence score
    min_spots: int = 100             # QC: minimum spots per section
    retry_error_pitch: float = 6.0   # post-QC (GT): median error above this -> retry
    min_coverage: float = 0.6        # post-QC (no-GT proxy): coverage below -> retry
    sutura_ckpt: str = "arca_shared_basis.pt"


# --------------------------------------------------------------------------- #
# frozen-basis projection with gene-vocabulary handling
# --------------------------------------------------------------------------- #
class Projector:
    def __init__(self):
        b = load_basis()
        self.genes = np.asarray(b["genes"])
        self.gpos = {g: i for i, g in enumerate(self.genes)}
        self.comp = b["components"]; self.mu = b["feat_mean"]; self.sd = b["feat_std"]
        # training-donor embedding distribution (Br5292 + Br5595, both sections)
        train = np.vstack([self.project(ad.read_h5ad(f))[0] for f in [
            DATA / "DLPFC_151507.h5ad", DATA / "DLPFC_151508.h5ad",
            DATA / "DLPFC_151669.h5ad", DATA / "DLPFC_151670.h5ad"]])
        self.tmu = train.mean(0)
        cov = np.cov(train.T) + 1e-3 * np.eye(train.shape[1])
        self.tinv = np.linalg.inv(cov)

    def project(self, a):
        """Frozen-basis features (zero-fill missing genes); returns (Z, overlap)."""
        vn = np.asarray(a.var_names)
        keep = [(j, self.gpos[g]) for j, g in enumerate(vn) if g in self.gpos]
        overlap = len(keep) / len(self.genes)
        X = a.X.tocsc() if sp.issparse(a.X) else np.asarray(a.X, np.float32)
        M = np.zeros((a.n_obs, len(self.genes)), np.float32)
        if keep:
            src = [j for j, _ in keep]; dst = [c for _, c in keep]
            sub = X[:, src].toarray() if sp.issparse(X) else X[:, src]
            M[:, dst] = sub
        counts = M.sum(1, keepdims=True); counts[counts == 0] = 1.0
        Z = ((np.log1p(M * (1e4 / counts)) @ self.comp.T) - self.mu) / self.sd
        return Z.astype(np.float32), overlap

    def mahalanobis(self, Z):
        d = Z.mean(0) - self.tmu
        return float(np.sqrt(d @ self.tinv @ d))


# --------------------------------------------------------------------------- #
# pipeline steps
# --------------------------------------------------------------------------- #
def load_and_qc(ref_path, mov_path, cfg):
    issues = []
    for tag, p in [("reference", ref_path), ("moving", mov_path)]:
        if not Path(p).exists():
            return None, None, {"ok": False, "issues": [f"{tag} file missing: {p}"]}
    A, B = ad.read_h5ad(ref_path), ad.read_h5ad(mov_path)
    for tag, x in [("reference", A), ("moving", B)]:
        if x.n_obs < cfg.min_spots:
            issues.append(f"{tag} has only {x.n_obs} spots (< {cfg.min_spots})")
        if "spatial" not in x.obsm:
            issues.append(f"{tag} missing obsm['spatial']")
        if not {"array_row", "array_col"} <= set(x.obs.columns):
            issues.append(f"{tag} missing array_row/array_col (no bridge GT)")
        if x.n_vars == 0:
            issues.append(f"{tag} has no genes")
    A.obsm["spatial"] = np.asarray(A.obsm["spatial"], float)
    B.obsm["spatial"] = np.asarray(B.obsm["spatial"], float)
    return A, B, {"ok": len(issues) == 0, "issues": issues,
                  "n_ref": A.n_obs, "n_mov": B.n_obs}


def distribution_check(A, B, proj, cfg):
    Za, ov_a = proj.project(A)
    Zb, ov_b = proj.project(B)
    overlap = min(ov_a, ov_b)
    if overlap < cfg.min_gene_overlap:
        return {"in_distribution": False, "confidence": round(0.02, 3),
                "maha": None, "gene_overlap": round(overlap, 3),
                "reason": f"gene-vocabulary overlap {overlap*100:.0f}% "
                          f"< {cfg.min_gene_overlap*100:.0f}% (incompatible panel)"}
    maha = proj.mahalanobis(np.vstack([Za, Zb]))
    conf = 1.0 / (1.0 + np.exp(-cfg.conf_steepness * (cfg.maha_threshold - maha)))
    in_dist = maha < cfg.maha_threshold
    return {"in_distribution": bool(in_dist), "confidence": round(float(conf), 3),
            "maha": round(maha, 2), "gene_overlap": round(overlap, 3),
            "reason": f"Mahalanobis {maha:.2f} "
                      f"{'<' if in_dist else '>'} threshold {cfg.maha_threshold} "
                      f"({'in' if in_dist else 'off'}-distribution)"}


def _paste2_cache():
    src = RESULTS / "generalization_sweep.csv"
    cache = {}
    if src.exists():
        for r in csv.DictReader(open(src)):
            if r["method"] == "paste2":
                cache[(r["dataset"], float(r["severity"]), int(r["seed"]))] = \
                    float(r["median_error_pitch"])
    return cache


def footprint_coverage_proxy(pred, ref_coords):
    """No-GT quality proxy: how well predicted locations fill the reference
    footprint. A collapsed alignment (Sutura off-distribution) piles predictions
    near the centroid, so its spread is far below the reference's. Returns a
    coverage ratio in [0, ~1]; ~1 = healthy, << 1 = collapse. Independent of any
    ground-truth correspondence."""
    def spread(P):
        c = P.mean(0)
        return float(np.median(np.linalg.norm(P - c, axis=1)))
    return spread(pred) / (spread(ref_coords) + 1e-9)


class Aligner:
    def __init__(self, cfg, proj):
        self.cfg = cfg; self.proj = proj
        ck = torch.load(RESULTS / cfg.sutura_ckpt, map_location="cpu",
                        weights_only=False)
        a = ck["args"]; self.knn = a["knn"]
        self.model = ARCACrossNet(ck["dim"], a["hidden"], a["layers"], a["attn_dim"])
        self.model.load_state_dict(ck["state_dict"]); self.model.eval()
        self.p2cache = _paste2_cache()

    def sutura(self, A, B0, severity, seed, return_pred=False):
        coords = A.obsm["spatial"]
        pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
        Z_A, _ = self.proj.project(A); Z_B, _ = self.proj.project(B0)
        ga = graph_tensors(coords, Z_A, self.knn, pitch)
        a_norm = torch.from_numpy((coords / pitch).astype(np.float32))
        gt_A, have = array_bridge(A, B0)
        w, _ = apply_warp(B0, severity, seed=seed, tear=True)
        gb = graph_tensors(np.asarray(w.obsm["spatial"], float), Z_B, self.knn, pitch)
        with torch.no_grad():
            pred = self.model(ga, gb, a_norm).numpy() * pitch
        err = registration_error_stats(pred, gt_A, mask=have)["median"] / pitch
        if return_pred:
            return err, pred, coords
        return err

    def paste2(self, A, B0, severity, seed, prior_name, use_cache):
        key = (prior_name, float(severity), int(seed))
        if use_cache and key in self.p2cache:
            return self.p2cache[key]
        from paste2.PASTE2 import partial_pairwise_align
        from paste2.helper import filter_for_common_genes
        coords = A.obsm["spatial"]
        pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
        gt_A, have = array_bridge(A, B0)
        w, _ = apply_warp(B0, severity, seed=seed, tear=True)
        Aa, Bb = A.copy(), w.copy(); filter_for_common_genes([Aa, Bb])
        pi = np.asarray(partial_pairwise_align(Aa, Bb, s=0.99, alpha=0.1,
                                               dissimilarity="pca", verbose=False))
        pb, cm = barycentric_projection(pi, Aa.obsm["spatial"])
        return registration_error_stats(pb, gt_A, mask=have & (cm > 0))["median"] / pitch

    def run(self, method, A, B0, severity, seed, prior_name, use_cache=True):
        if method == "sutura":
            return self.sutura(A, B0, severity, seed)
        return self.paste2(A, B0, severity, seed, prior_name, use_cache)


def plain_summary(name, qc, dcheck, initial_method, initial_err, retry,
                  alt_method, alt_err, final_method, final_err):
    parts = [f"[{name}] QC {'passed' if qc['ok'] else 'FAILED'} "
             f"({qc.get('n_ref','?')}+{qc.get('n_mov','?')} spots)."]
    parts.append(f"Distribution check: {dcheck['reason']}; "
                 f"in-distribution confidence {dcheck['confidence']:.2f}.")
    parts.append(f"Routed to {initial_method.upper()} -> median error "
                 f"{initial_err:.2f} pitch.")
    if retry:
        parts.append(f"Post-QC flagged it (> threshold); retried "
                     f"{alt_method.upper()} -> {alt_err:.2f} pitch; kept "
                     f"{final_method.upper()} ({final_err:.2f} pitch).")
    else:
        parts.append("Post-QC passed; no retry.")
    return " ".join(parts)


def orchestrate(name, cfg, proj, aligner, severity, seed, use_cache=True):
    ds = DATASETS[name]
    A, B, qc = load_and_qc(ds["ref"], ds["mov"], cfg)
    if not qc["ok"]:
        return {"dataset": name, "qc_ok": False, "reason": "; ".join(qc["issues"])}, \
            f"[{name}] QC FAILED: {'; '.join(qc['issues'])}"

    dcheck = distribution_check(A, B, proj, cfg)
    initial_method = "sutura" if dcheck["in_distribution"] else "paste2"
    alt_method = "paste2" if initial_method == "sutura" else "sutura"

    def run_qc(method):
        """Run a method; return (median_error, footprint_coverage_or_None)."""
        if method == "sutura":
            e, pred, refc = aligner.sutura(A, B, severity, seed, return_pred=True)
            return e, footprint_coverage_proxy(pred, refc)
        return aligner.run(method, A, B, severity, seed, ds["prior"], use_cache), None

    initial_err, coverage = run_qc(initial_method)
    final_method, final_err = initial_method, initial_err
    retry = False; alt_err = None
    # post-alignment QC: with array-bridge GT we use median error; the footprint-
    # coverage proxy is the no-GT fallback (flags gross collapse). Retry the
    # alternate method if either signal looks bad.
    bad = (initial_err > cfg.retry_error_pitch or
           (coverage is not None and coverage < cfg.min_coverage))
    if bad and not (alt_method == "sutura" and
                    dcheck["gene_overlap"] < cfg.min_gene_overlap):
        alt_err, _ = run_qc(alt_method)
        retry = True
        if alt_err < initial_err:
            final_method, final_err = alt_method, alt_err

    row = {"dataset": name, "tissue": ds["tissue"], "truth": ds["truth"],
           "qc_ok": True, "chosen_method": final_method,
           "initial_method": initial_method,
           "in_dist_confidence": dcheck["confidence"],
           "gene_overlap": dcheck["gene_overlap"], "maha": dcheck["maha"],
           "error": round(float(final_err), 3), "retry": retry,
           "retry_error": None if alt_err is None else round(float(alt_err), 3),
           "footprint_coverage": None if coverage is None else round(coverage, 3),
           "severity": severity, "seed": seed}
    return row, plain_summary(name, qc, dcheck, initial_method, initial_err,
                              retry, alt_method, alt_err, final_method, final_err)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--severity", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--maha-threshold", type=float, default=2.5)
    p.add_argument("--no-paste2-cache", action="store_true")
    p.add_argument("--out", default="orchestrator_eval.csv")
    args = p.parse_args()

    cfg = OrchestratorConfig(maha_threshold=args.maha_threshold)
    proj = Projector()
    aligner = Aligner(cfg, proj)
    use_cache = not args.no_paste2_cache

    rows = []
    print(f"orchestrator validation (tear severity={args.severity}, seed={args.seed})\n")
    for name in DATASETS:
        row, summary = orchestrate(name, cfg, proj, aligner, args.severity,
                                   args.seed, use_cache)
        rows.append(row)
        print(summary + "\n")

    RESULTS.mkdir(exist_ok=True)
    cols = ["dataset", "tissue", "truth", "qc_ok", "chosen_method",
            "in_dist_confidence", "gene_overlap", "maha", "error", "retry",
            "retry_error", "footprint_coverage", "severity", "seed"]
    with open(RESULTS / args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in cols})
    print(f"wrote {RESULTS / args.out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
