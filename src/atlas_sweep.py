"""
Atlas sweep (branch: atlas-sweep).

Runs the Sutura orchestrator across every public spatial-transcriptomics dataset we
can pull programmatically, to map where the model wins (in-distribution) vs where it
routes away to PASTE2 (off-distribution), and to surface candidate training data.

For each dataset that provides two array-aligned serial sections (so array-bridge GT
exists), we record, at a fixed synthetic tear (severity 4.0, seed 0):
  - tissue / platform / spot counts
  - gene-vocabulary overlap with the frozen DLPFC basis + Mahalanobis distance
  - in-distribution confidence + route decision (Sutura in-dist / PASTE2 off-dist)
  - standalone numbers for  Sutura(zero-shot) | Sutura(auto-adapted) | PASTE2
  - error: median registration error in pitch units when bridge GT is derivable,
    else the footprint-coverage proxy (a collapse detector, NOT an error).
  - the orchestrator's chosen method+error, and the global best method (to show
    whether the router picked the true winner).

Robustness: each dataset is wrapped in try/except; failures are logged and the sweep
continues. The CSV is rewritten after every dataset so a crash keeps partial results.
Datasets without >=2 array-aligned sections are logged to the skip list with a reason.

Downloads land in research/data/atlas/ ; outputs in research/results/.

Usage:
  python src/atlas_sweep.py                         # full sweep
  python src/atlas_sweep.py --only breast,human_brain
  python src/atlas_sweep.py --skip-paste2 --skip-adapt   # fast smoke of route+zeroshot
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import numpy as np
import scipy.sparse as sp
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import torch  # noqa: E402
from train_cross import ARCACrossNet, array_bridge, graph_tensors  # noqa: E402
from warp_slice import apply_warp  # noqa: E402
from scoring import registration_error_stats, barycentric_projection  # noqa: E402
from shared_basis import load_basis, transform  # noqa: E402
from orchestrator import Projector, distribution_check, OrchestratorConfig, \
    footprint_coverage_proxy  # noqa: E402
from autoadapt import finetune, AdaptConfig  # noqa: E402

DATA = ROOT / "data"
EXT = DATA / "external"
ATLAS = ROOT / "research" / "data" / "atlas"
RESULTS = ROOT / "research" / "results"
LOGP = RESULTS / "atlas_sweep.log"
CSVP = RESULTS / "atlas_sweep.csv"
SKIPP = RESULTS / "atlas_sweep_skipped.csv"

SEVERITY = 4.0
SEED = 0
PASTE2_CAP = 1500   # subsample cap for PASTE2 (bounds O(n^2) GW cost/memory)

ATLAS.mkdir(parents=True, exist_ok=True)
RESULTS.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with open(LOGP, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# --------------------------------------------------------------------------- #
# dataset registry
# --------------------------------------------------------------------------- #
# Each entry either points at local h5ad files or names a 10x visium_sge sample to
# download. `extra` sections (same donor/block) enable supervised cross-adaptation;
# without them auto-adapt falls back to self-supervised on the reference section.
def D(p):  # local data-dir file
    return {"kind": "local", "path": DATA / p}


def X(p):  # local external file
    return {"kind": "local", "path": EXT / p}


def V(sample_id):  # 10x visium_sge download
    return {"kind": "10x", "sample_id": sample_id}


def SELF(sample_id, tissue, expected="off-distribution"):
    """A single 10x section as a self-alignment datapoint: aligned to a synthetically
    warped copy of itself (mov == ref). No serial partner needed, so this covers every
    single-section tissue in the 10x catalog. The distribution-check / routing map is
    valid per tissue; error is self-warp recovery (easier than true serial pairs -> the
    mode column marks it so the two are not conflated)."""
    return dict(name=sample_id, tissue=tissue, platform="Visium", expected=expected,
                source="10x", mode="self", ref=V(sample_id), mov=V(sample_id), extra=[])


REGISTRY = [
    # ---- in-distribution: DLPFC (spatialLIBD), one pair per donor + siblings ----
    dict(name="DLPFC_Br5292", tissue="human DLPFC", platform="Visium",
         expected="in-distribution", source="spatialLIBD",
         ref=D("DLPFC_151507.h5ad"), mov=D("DLPFC_151508.h5ad"),
         extra=[D("DLPFC_151509.h5ad"), D("DLPFC_151510.h5ad")]),
    dict(name="DLPFC_Br5595", tissue="human DLPFC", platform="Visium",
         expected="in-distribution", source="spatialLIBD",
         ref=D("DLPFC_151669.h5ad"), mov=D("DLPFC_151670.h5ad"),
         extra=[D("DLPFC_151671.h5ad"), D("DLPFC_151672.h5ad")]),
    dict(name="DLPFC_Br8100", tissue="human DLPFC", platform="Visium",
         expected="off-distribution", source="spatialLIBD",
         ref=D("DLPFC_151673.h5ad"), mov=D("DLPFC_151674.h5ad"),
         extra=[D("DLPFC_151675.h5ad"), D("DLPFC_151676.h5ad")]),
    # ---- off-distribution: 10x serial pairs (array-aligned Section 1/2) ----
    dict(name="breast_block_a", tissue="human breast cancer", platform="Visium",
         expected="off-distribution", source="10x",
         ref=X("V1_Breast_Cancer_Block_A_Section_1.h5ad"),
         mov=X("V1_Breast_Cancer_Block_A_Section_2.h5ad"), extra=[]),
    dict(name="mouse_sagittal_post", tissue="mouse brain", platform="Visium",
         expected="off-distribution", source="10x",
         ref=X("V1_Mouse_Brain_Sagittal_Posterior.h5ad"),
         mov=X("V1_Mouse_Brain_Sagittal_Posterior_Section_2.h5ad"), extra=[]),
    dict(name="mouse_sagittal_ant", tissue="mouse brain", platform="Visium",
         expected="off-distribution", source="10x",
         ref=V("V1_Mouse_Brain_Sagittal_Anterior"),
         mov=V("V1_Mouse_Brain_Sagittal_Anterior_Section_2"), extra=[]),
    dict(name="human_brain_cbl", tissue="human brain (cerebellum)", platform="Visium",
         expected="off-distribution", source="10x",
         ref=V("V1_Human_Brain_Section_1"),
         mov=V("V1_Human_Brain_Section_2"), extra=[]),
    dict(name="mouse_coronal", tissue="mouse brain (coronal)", platform="Visium",
         expected="off-distribution", source="10x",
         ref=V("V1_Adult_Mouse_Brain_Coronal_Section_1"),
         mov=V("V1_Adult_Mouse_Brain_Coronal_Section_2"), extra=[]),
    # ---- every remaining 10x public Visium tissue, as self-alignment datapoints ----
    # whole-transcriptome single sections
    SELF("V1_Human_Heart", "human heart"),
    SELF("V1_Human_Lymph_Node", "human lymph node"),
    SELF("V1_Mouse_Kidney", "mouse kidney"),
    SELF("V1_Adult_Mouse_Brain", "mouse brain (whole)"),
    SELF("Parent_Visium_Human_Cerebellum", "human cerebellum"),
    SELF("Parent_Visium_Human_SpinalCord", "human spinal cord"),
    SELF("Parent_Visium_Human_Glioblastoma", "human glioblastoma"),
    SELF("Parent_Visium_Human_BreastCancer", "human breast cancer"),
    SELF("Parent_Visium_Human_OvarianCancer", "human ovarian cancer"),
    SELF("Parent_Visium_Human_ColorectalCancer", "human colorectal cancer"),
    # targeted gene-panel sections (~1k genes -> low overlap; a gene-gate stress test)
    SELF("Targeted_Visium_Human_Cerebellum_Neuroscience", "human cerebellum (targeted panel)"),
    SELF("Targeted_Visium_Human_SpinalCord_Neuroscience", "human spinal cord (targeted panel)"),
    SELF("Targeted_Visium_Human_Glioblastoma_Pan_Cancer", "human glioblastoma (targeted panel)"),
    SELF("Targeted_Visium_Human_BreastCancer_Immunology", "human breast cancer (targeted panel)"),
    SELF("Targeted_Visium_Human_OvarianCancer_Pan_Cancer", "human ovarian cancer (targeted panel)"),
    SELF("Targeted_Visium_Human_OvarianCancer_Immunology", "human ovarian cancer (targeted immuno)"),
    SELF("Targeted_Visium_Human_ColorectalCancer_GeneSignature", "human colorectal cancer (targeted panel)"),
]

# sources we deliberately skip, with the reason (logged for the findings). The 10x
# single-section tissues that were previously skipped are now COVERED via self-alignment
# (see SELF() entries above); what remains skipped is non-Visium / no-array-grid data.
SKIPS = [
    ("squidpy visium_hne_adata / visium_fluo_adata",
     "single mouse-brain section - already represented by V1_Adult_Mouse_Brain (self-align)"),
    ("squidpy slideseqv2 / merfish / seqfish / imc / four_i / mibitof",
     "no Visium array grid (array_row/array_col) - array-bridge GT not derivable"),
    ("GEO spatial series (generic)",
     "no standardized array-aligned pair via direct download - bespoke per-series format"),
]


# --------------------------------------------------------------------------- #
# loading / standardization
# --------------------------------------------------------------------------- #
def standardize(a: ad.AnnData, tag: str, adapt_notes: list) -> ad.AnnData:
    before = a.n_vars
    a.var_names_make_unique()
    if a.n_vars != before:
        adapt_notes.append(f"{tag}: made {before - a.n_vars} duplicate var_names unique")
    if "spatial" not in a.obsm:
        raise ValueError(f"{tag}: missing obsm['spatial']")
    a.obsm["spatial"] = np.asarray(a.obsm["spatial"], float)
    if not {"array_row", "array_col"} <= set(a.obs.columns):
        raise ValueError(f"{tag}: missing array_row/array_col (no array-bridge GT)")
    return a


def resolve(section: dict, tag: str, adapt_notes: list) -> ad.AnnData:
    if section["kind"] == "local":
        p = section["path"]
        if not p.exists():
            raise FileNotFoundError(f"{tag}: local file missing {p}")
        a = ad.read_h5ad(p)
        adapt_notes.append(f"{tag}: loaded local {p.name}")
    else:
        import scanpy as sc
        sid = section["sample_id"]
        cache = ATLAS / f"{sid}.h5ad"
        if cache.exists():
            a = ad.read_h5ad(cache)
            adapt_notes.append(f"{tag}: cached download {sid}")
        else:
            log(f"    downloading 10x sample {sid} ...")
            a = sc.datasets.visium_sge(sample_id=sid)
            a.var_names_make_unique()
            a.write(cache)
            adapt_notes.append(f"{tag}: downloaded {sid} ({a.n_obs} spots, {a.n_vars} genes)")
    return standardize(a, tag, adapt_notes)


# --------------------------------------------------------------------------- #
# alignment runners
# --------------------------------------------------------------------------- #
def _pitch(coords):
    return float(np.median(cKDTree(coords).query(coords, k=2)[0][:, 1]))


def load_zero_model(ck):
    hp = ck["args"]
    m = ARCACrossNet(ck["dim"], hp["hidden"], hp["layers"], hp["attn_dim"])
    m.load_state_dict(ck["state_dict"]); m.eval()
    return m, hp["knn"]


def sutura_predict(model, A, B, basis, knn):
    """Return (pred coords in A-frame px, gt_A, have, ref_coords, pitch)."""
    coords = A.obsm["spatial"]; pitch = _pitch(coords)
    Z_A = transform(A, basis); Z_B = transform(B, basis)
    ga = graph_tensors(coords, Z_A, knn, pitch)
    a_norm = torch.from_numpy((coords / pitch).astype(np.float32))
    gt_A, have = array_bridge(A, B)
    w, _ = apply_warp(B, SEVERITY, seed=SEED, tear=True)
    gb = graph_tensors(np.asarray(w.obsm["spatial"], float), Z_B, knn, pitch)
    with torch.no_grad():
        pred = model(ga, gb, a_norm).numpy() * pitch
    return pred, gt_A, have, coords, pitch


def median_or_proxy(pred, gt_A, have, ref_coords, pitch):
    """median error/pitch if bridge GT exists, else footprint-coverage proxy."""
    if have.sum() > 0:
        err = registration_error_stats(pred, gt_A, mask=have)["median"] / pitch
        return float(err), "median_pitch", float(have.mean())
    cov = footprint_coverage_proxy(pred, ref_coords)
    return float(cov), "footprint_coverage_proxy", 0.0


def run_paste2(A, B, cap=PASTE2_CAP):
    """Subsampled PASTE2; returns median error/pitch (bridge GT) or None if no GT."""
    from paste2.PASTE2 import partial_pairwise_align
    from paste2.helper import filter_for_common_genes
    rng = np.random.default_rng(SEED)
    coords = A.obsm["spatial"]; pitch = _pitch(coords)
    gt_A, have = array_bridge(A, B)
    if have.sum() == 0:
        return None, 0.0
    w, _ = apply_warp(B, SEVERITY, seed=SEED, tear=True)
    Aa, Bb = A.copy(), w.copy()
    if Aa.n_obs > cap:
        Aa = Aa[rng.choice(Aa.n_obs, cap, replace=False)].copy()
    if Bb.n_obs > cap:
        idx = rng.choice(Bb.n_obs, cap, replace=False)
        Bb = Bb[idx].copy(); gt_A = gt_A[idx]; have = have[idx]
    filter_for_common_genes([Aa, Bb])
    pi = np.asarray(partial_pairwise_align(Aa, Bb, s=0.99, alpha=0.1,
                                           dissimilarity="pca", verbose=False))
    pb, cm = barycentric_projection(pi, Aa.obsm["spatial"])
    m = have & (cm > 0)
    if m.sum() == 0:
        return None, float(have.mean())
    return float(registration_error_stats(pb, gt_A, mask=m)["median"] / pitch), float(have.mean())


# --------------------------------------------------------------------------- #
# per-dataset
# --------------------------------------------------------------------------- #
COLS = ["name", "tissue", "platform", "source", "mode", "expected_class",
        "n_spots_ref", "n_spots_mov", "gene_overlap", "maha",
        "in_dist_confidence", "in_distribution", "route", "gt_coverage", "error_type",
        "sutura_zeroshot", "sutura_adapted", "paste2",
        "chosen_method", "chosen_error", "best_method", "best_error",
        "adapt_applicable", "adapt_seconds", "notes"]


def run_dataset(spec, ctx, args):
    name = spec["name"]
    notes = []
    A = resolve(spec["ref"], "ref", notes)
    B = resolve(spec["mov"], "mov", notes)
    extras = [resolve(e, f"extra{i}", notes) for i, e in enumerate(spec.get("extra", []))]

    # distribution check / route
    dcheck = distribution_check(A, B, ctx["proj"], ctx["cfg"])
    in_dist = dcheck["in_distribution"]
    overlap = dcheck["gene_overlap"]
    route = "sutura" if in_dist else "paste2"

    # zero-shot Sutura (always computed; on ~0-overlap inputs it collapses -> that is the point)
    pred, gt_A, have, refc, pitch = sutura_predict(ctx["zero"], A, B, ctx["basis"], ctx["knn"])
    zs_val, err_type, gt_cov = median_or_proxy(pred, gt_A, have, refc, pitch)
    zs = zs_val if err_type == "median_pitch" else None
    zs_proxy = zs_val if err_type != "median_pitch" else None

    # auto-adapted Sutura (only where the DLPFC panel is shared)
    adp = None; adapt_applicable = False; adapt_s = 0.0
    if not args.skip_adapt and overlap >= ctx["cfg"].min_gene_overlap:
        adapt_applicable = True
        mode = "cross" if extras else "self"
        adds = dict(adapt_mode=mode,
                    adapt_ref=(spec["extra"][0]["path"] if (mode == "cross" and
                               spec["extra"][0]["kind"] == "local") else None),
                    adapt_mov=(spec["extra"][1]["path"] if (mode == "cross" and
                               len(spec["extra"]) > 1 and
                               spec["extra"][1]["kind"] == "local") else None))
        # finetune reads adapt_ref/adapt_mov from disk; for cross we have local DLPFC sibs.
        if mode == "self":
            adds["adapt_ref"] = _write_tmp(A, ctx["tmp"], f"{name}_adaptref")
            adds["adapt_mov"] = None
        t0 = time.time()
        model, adapt_s2, _, _ = finetune(ck_state(ctx), ctx["dim"], ctx["hp"], adds,
                                         ctx["basis"], ctx["acfg"])
        adapt_s = round(time.time() - t0, 1)
        predA, gA, hv, rc, pt = sutura_predict(model, A, B, ctx["basis"], ctx["knn"])
        if hv.sum() > 0:
            adp = float(registration_error_stats(predA, gA, mask=hv)["median"] / pt)

    # PASTE2
    p2 = None
    if not args.skip_paste2:
        p2, _ = run_paste2(A, B)

    # candidates + decisions
    cands = {"sutura_zeroshot": zs, "sutura_adapted": adp, "paste2": p2}
    finite = {k: v for k, v in cands.items() if v is not None and np.isfinite(v)}
    best_method = min(finite, key=finite.get) if finite else None
    best_error = finite[best_method] if best_method else None
    # orchestrator's route-constrained choice: in-dist -> zero-shot Sutura;
    # off-dist -> best of {adapted, paste2}; post-QC keeps the better if route result is bad
    if in_dist:
        permitted = {k: finite[k] for k in ("sutura_zeroshot",) if k in finite}
    else:
        permitted = {k: finite[k] for k in ("sutura_adapted", "paste2") if k in finite}
    if not permitted:
        permitted = finite
    chosen_method = min(permitted, key=permitted.get) if permitted else None
    chosen_error = permitted[chosen_method] if chosen_method else None

    if zs_proxy is not None:
        notes.append(f"zero-shot no bridge GT; footprint proxy={round(zs_proxy,3)}")
    return {
        "name": name, "tissue": spec["tissue"], "platform": spec["platform"],
        "source": spec["source"], "mode": spec.get("mode", "serial"),
        "expected_class": spec["expected"],
        "n_spots_ref": A.n_obs, "n_spots_mov": B.n_obs,
        "gene_overlap": overlap, "maha": dcheck["maha"],
        "in_dist_confidence": dcheck["confidence"], "in_distribution": in_dist,
        "route": route, "gt_coverage": round(gt_cov, 3), "error_type": err_type,
        "sutura_zeroshot": None if zs is None else round(zs, 3),
        "sutura_adapted": None if adp is None else round(adp, 3),
        "paste2": None if p2 is None else round(p2, 3),
        "chosen_method": chosen_method,
        "chosen_error": None if chosen_error is None else round(chosen_error, 3),
        "best_method": best_method,
        "best_error": None if best_error is None else round(best_error, 3),
        "adapt_applicable": adapt_applicable, "adapt_seconds": adapt_s,
        "notes": "; ".join(notes),
    }


_TMP_CACHE = {}


def _write_tmp(a, tmpdir, key):
    p = tmpdir / f"{key}.h5ad"
    if key not in _TMP_CACHE:
        a.write(p); _TMP_CACHE[key] = p
    return _TMP_CACHE[key]


def ck_state(ctx):
    return ctx["ck"]["state_dict"]


def write_csv(rows):
    with open(CSVP, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in COLS})


def write_skips():
    with open(SKIPP, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "skip_reason"])
        for s, why in SKIPS:
            w.writerow([s, why])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", default="")
    p.add_argument("--skip-paste2", action="store_true")
    p.add_argument("--skip-adapt", action="store_true")
    args = p.parse_args()

    open(LOGP, "w").close()
    log("=== atlas sweep start ===")
    write_skips()
    log(f"logged {len(SKIPS)} skipped source classes -> {SKIPP.name}")

    cfg = OrchestratorConfig()
    acfg = AdaptConfig()
    log("building Projector (frozen DLPFC basis + training-donor distribution) ...")
    proj = Projector()
    basis = load_basis()
    ck = torch.load(ROOT / "results" / cfg.sutura_ckpt,
                    map_location="cpu", weights_only=False)
    zero, knn = load_zero_model(ck)
    tmp = ATLAS / "_tmp"; tmp.mkdir(exist_ok=True)
    ctx = dict(cfg=cfg, acfg=acfg, proj=proj, basis=basis, ck=ck, zero=zero,
               knn=knn, dim=ck["dim"], hp=ck["args"], tmp=tmp)

    names = [n.strip() for n in args.only.split(",") if n.strip()]
    specs = [s for s in REGISTRY if not names or s["name"] in names]

    # resume: keep datasets already in the CSV (deterministic), only run the rest
    rows = []
    done = set()
    if CSVP.exists():
        for r in csv.DictReader(open(CSVP, encoding="utf-8")):
            r.setdefault("mode", "serial")   # backfill for pre-mode rows (all serial)
            rows.append(r); done.add(r["name"])
        log(f"resuming: {len(done)} datasets already in CSV -> skipping them")
    todo = [s for s in specs if s["name"] not in done]
    log(f"running {len(todo)} of {len(specs)} datasets: {[s['name'] for s in todo]}")

    for spec in todo:
        t0 = time.time()
        log(f"--- {spec['name']} ({spec['tissue']}) ---")
        try:
            row = run_dataset(spec, ctx, args)
            rows.append(row)
            log(f"  route={row['route']} conf={row['in_dist_confidence']} "
                f"overlap={row['gene_overlap']} | zeroshot={row['sutura_zeroshot']} "
                f"adapted={row['sutura_adapted']} paste2={row['paste2']} "
                f"-> chosen={row['chosen_method']}({row['chosen_error']}) "
                f"best={row['best_method']}({row['best_error']}) [{time.time()-t0:.0f}s]")
        except Exception as e:
            log(f"  FAILED: {e}")
            log("  " + traceback.format_exc().replace("\n", "\n  "))
            rows.append({"name": spec["name"], "tissue": spec["tissue"],
                         "platform": spec["platform"], "source": spec["source"],
                         "expected_class": spec["expected"], "notes": f"FAILED: {e}"})
        write_csv(rows)   # incremental: survive a crash on the next dataset

    log(f"=== done: wrote {CSVP.name} ({len(rows)} rows) ===")


if __name__ == "__main__":
    main()
