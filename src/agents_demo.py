"""Validate the agent suite (agents.py) on a real pair: build genuine Sutura and
PASTE2 predictions, then run report / QC-retry / ensemble / parameter-tuning.
Writes results/agents_demo_report.md."""
from __future__ import annotations
import sys
from pathlib import Path
import anndata as ad, numpy as np, torch
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from train_cross import ARCACrossNet, graph_tensors, array_bridge
from scoring import registration_error_stats, barycentric_projection
from shared_basis import load_basis, transform
import agents

basis = load_basis()
ck = torch.load(ROOT / "results/arca_shared_basis.pt", map_location="cpu", weights_only=False)
hp = ck["args"]; dim = ck["dim"]
ref = ad.read_h5ad(ROOT / "data/DLPFC_151669.h5ad"); mov = ad.read_h5ad(ROOT / "data/DLPFC_151670.h5ad")
ref.obsm["spatial"] = np.asarray(ref.obsm["spatial"], float); mov.obsm["spatial"] = np.asarray(mov.obsm["spatial"], float)
coords = ref.obsm["spatial"]; pitch = float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))
gt, have = array_bridge(ref, mov)


def sutura_pred(knn):
    m = ARCACrossNet(dim, hp["hidden"], hp["layers"], hp["attn_dim"]); m.load_state_dict(ck["state_dict"]); m.eval()
    ga = graph_tensors(coords, transform(ref, basis), knn, pitch)
    gb = graph_tensors(np.asarray(mov.obsm["spatial"], float), transform(mov, basis), knn, pitch)
    with torch.no_grad():
        return m(ga, gb, torch.from_numpy((coords / pitch).astype(np.float32))).numpy() * pitch


print("building real Sutura + PASTE2 predictions on Br5595 (151669/151670)...", flush=True)
p_sut = sutura_pred(6)
from paste2.PASTE2 import partial_pairwise_align
from paste2.helper import filter_for_common_genes
Aa, Bb = ref.copy(), mov.copy(); filter_for_common_genes([Aa, Bb])
pi = np.asarray(partial_pairwise_align(Aa, Bb, s=0.99, alpha=0.1, dissimilarity="pca", verbose=False))
p_p2, cm = barycentric_projection(pi, Aa.obsm["spatial"]); p_p2[~np.isfinite(p_p2).all(1)] = coords.mean(0)
print(f"  sutura median={registration_error_stats(p_sut,gt,mask=have)['median']/pitch:.2f}p  "
      f"paste2 median={registration_error_stats(p_p2,gt,mask=have)['median']/pitch:.2f}p", flush=True)

# 1) QC + auto-retry agent
qc = agents.qc_retry_agent({"sutura": p_sut, "paste2": p_p2}, coords, mov.obsm["spatial"],
                           gt=gt, have=have, pitch=pitch)
print(f"\n[QC-retry] best={qc['best']} any_failed={qc['any_failed']} scores="
      + ", ".join(f"{k}:{v['value']}" for k, v in qc['scores'].items()))

# 2) ensemble agent (per-region)
ens = agents.ensemble_agent({"sutura": p_sut, "paste2": p_p2}, coords, mov.obsm["spatial"],
                            gt=gt, have=have, pitch=pitch)
print(f"[ensemble] merged_median={ens.get('merged_median_pitch')}p  region_fraction={ens['region_fraction']}")

# 3) parameter-tuning agent (sweep Sutura kNN)
grid = [{"knn": k} for k in (4, 6, 8, 10)]
def score(pred): return registration_error_stats(pred, gt, mask=have)["median"] / pitch, True
tune = agents.param_tuning_agent(lambda knn: sutura_pred(knn), grid, lambda p: score(p))
print(f"[param-tuning] best={tune['best_params']} value={tune['best_value']}p  grid={[(g['params']['knn'],g['value']) for g in tune['grid']]}")

# 4) report agent (with per-layer breakdown; DLPFC has layer labels)
aligned = mov.copy(); aligned.obsm["spatial_aligned"] = p_sut.astype(np.float32)
result = {"method": "sutura", "method_label": "Sutura", "reason": "in-distribution",
          "in_distribution": True, "in_dist_confidence": 0.90, "mahalanobis": 1.02,
          "gene_overlap": 1.0, "metric": "median_error_pitch",
          "score": round(registration_error_stats(p_sut, gt, mask=have)["median"] / pitch, 3),
          "has_ground_truth": True,
          "footprint_coverage": round(agents.footprint_coverage(p_sut, coords), 3)}
rep = agents.report_agent(result, aligned_adata=aligned, gt=gt, have=have, pitch=pitch)
(ROOT / "results/agents_demo_report.md").write_text(rep["markdown"], encoding="utf-8")
print(f"\n[report] flagged={rep['flagged'].get('n_high_error')} high-error spots; "
      f"recommendations={len(rep['recommendations'])}; wrote results/agents_demo_report.md")
print("\nALL FOUR AGENTS RAN OK")
