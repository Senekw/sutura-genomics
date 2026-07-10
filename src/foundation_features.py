"""
Foundation-model node features for the Sutura cross-donor tear benchmark.

THE KEY EXPERIMENT. Sutura's per-dataset TruncatedSVD node features do not
transfer across donors (LODO held-out ~9.6 spot-pitches, vs PASTE2 ~3.5). The
hypothesis under test: a PRETRAINED / self-supervised foundation-model embedding
supplies the cross-dataset prior that a per-fold linear SVD basis lacks, and so
moves held-out-donor error toward or below PASTE2.

WHAT IS HELD FIXED (identical to generalization_max.py's `augment_reg` config):
  * the alignment architecture (ARCACrossNet: shared GNN encoder + cross-slice
    attention + deformation-residual head),
  * the tear benchmark (median registration error in spot-pitches, tear warps,
    severities 0..8),
  * leave-one-donor-out over the 3 DLPFC donors (train on 2, hold out the 3rd,
    rotate), and
  * the training recipe: domain-randomization augmentation + weight_decay=1e-4 +
    early stopping.

THE ONLY CHANGE: the node features fed to `graph_tensors`. Instead of a per-fold
frozen SVD basis, each condition uses a different embedding, fit on the TRAINING
donors only and applied transform-only to the held-out donor (same discipline as
the frozen SVD basis, so "model never saw the held-out donor" holds for features
too).

Conditions (each tried independently; a condition that will not install/train in
this environment logs the exact failure and is SKIPPED, never killing the run):
  svd         reference baseline in THIS harness (linear TruncatedSVD, per fold)
  scvi        scVI latent, trained here on pooled TRAIN-donor counts, no batch
              key -> an amortized nonlinear expression encoder applied to the
              held-out donor (the direct nonlinear analog of the SVD basis)
  scvi_batch  scVI with donor batch correction; held-out donor mapped in via
              scArches query surgery (load_query_data)
  scgpt       scGPT cell embeddings (pretrained), if importable
  geneformer  Geneformer embeddings (pretrained), if importable
  uce         Universal Cell Embeddings (pretrained), if importable

Robustness: writes research/results/foundation_features.csv incrementally after
every (feature x fold), logs to research/results/foundation_features.log, wraps
each feature and each fold in try/except. At the end emits
research/results/foundation_features.png and research/FINDINGS_foundation_features.md.

Usage:
  python src/foundation_features.py                       # all conditions, 3-fold LODO
  python src/foundation_features.py --features svd,scvi   # subset
  python src/foundation_features.py --plot-only           # regenerate png+md from csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import anndata as ad  # noqa: E402

# Reusable Sutura harness (unchanged): LODO driver, model, metric, PASTE2 refs.
import generalization_max as gm  # noqa: E402

# The 1.3 GB DLPFC h5ad data is gitignored and lives only in the MAIN checkout.
MAIN_REPO = Path(r"C:\Users\karti\arca")
DATA_DIR = MAIN_REPO / "data"
if DATA_DIR.exists():
    gm.DATA = DATA_DIR
DATA_DIR = gm.DATA  # authoritative for our own reads too

OUT_DIR = ROOT / "research" / "results"
CSV_PATH = OUT_DIR / "foundation_features.csv"
LOG_PATH = OUT_DIR / "foundation_features.log"
PNG_PATH = OUT_DIR / "foundation_features.png"
FINDINGS_PATH = ROOT / "research" / "FINDINGS_foundation_features.md"

# External references (SVD plateau vs PASTE2). PASTE2 per-fold numbers come from
# gm.PASTE2 (prior full-res tear sweeps on the same held-out pairs).
SVD_REF_HELDOUT = 9.6

# Training recipe held fixed across all conditions (== generalization_max augment_reg).
CFG = gm.Config(
    name="foundation", feature="svd", n_train_donors=2, pairs_per_donor=2,
    augment=True, weight_decay=1e-4, early_stop=True, epochs=60, steps_per_epoch=20,
    lr=1e-3,
)

CSV_FIELDS = [
    "feature", "held_out_donor", "train_donors", "feat_dim",
    "in_dist_error", "held_out_error", "paste2_error", "svd_ref_heldout",
    "beats_paste2", "delta_vs_paste2", "n_train_pairs", "seconds", "status",
    "timestamp", "detail",
]

# Keep the original SVD feature functions before we monkeypatch the dispatchers.
_ORIG_FIT_FOLD_BASIS = gm.fit_fold_basis
_ORIG_TRANSFORM = gm.transform


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="ascii", errors="replace") as fh:
        fh.write(line + "\n")


# --------------------------------------------------------------------------- #
# feature backends. Contract: fit(train_slices) -> basis dict with
# basis["components"].shape[0] == feat_dim; transform(adata, basis) ->
# (n_obs, feat_dim) float32 standardized node features.
# --------------------------------------------------------------------------- #
class Backend:
    name = "base"

    def available(self):
        return True, ""

    def fit(self, train_slices):
        raise NotImplementedError

    def transform(self, adata, basis):
        raise NotImplementedError


class SvdBackend(Backend):
    """Reference: the existing per-fold linear TruncatedSVD basis, unchanged."""
    name = "svd"

    def fit(self, train_slices):
        return _ORIG_FIT_FOLD_BASIS(train_slices, "svd", gm.HP["pca_dim"], CFG.hvg_n)

    def transform(self, adata, basis):
        return _ORIG_TRANSFORM(adata, basis)


def _load_counts(slice_name):
    a = ad.read_h5ad(DATA_DIR / f"{slice_name}.h5ad")
    a.obsm["spatial"] = np.asarray(a.obsm["spatial"], float)
    return a


class ScviBackend(Backend):
    """scVI latent as node features. fit: pool TRAIN-donor slices, pick HVGs on
    pooled counts, train an scVI VAE (CPU), n_latent == pca_dim. no batch key ->
    the amortized encoder is a pure expression->latent map applied unchanged to
    the held-out donor (mirrors the transform-only SVD basis). batch=True variant:
    donor batch correction + scArches load_query_data for the unseen donor."""
    def __init__(self, n_latent=50, hvg=1500, max_epochs=60, batch=False):
        self.n_latent = n_latent
        self.hvg = hvg
        self.max_epochs = max_epochs
        self.batch = batch
        self.name = "scvi_batch" if batch else "scvi"

    def available(self):
        try:
            import scvi  # noqa: F401
            import scanpy  # noqa: F401
            return True, f"scvi-tools {__import__('scvi').__version__}"
        except Exception as e:
            return False, f"import failed: {e!r}"

    def fit(self, train_slices):
        import logging
        import scvi
        import scanpy as sc
        for noisy in ("scvi", "pytorch_lightning", "lightning.pytorch"):
            logging.getLogger(noisy).setLevel(logging.ERROR)
        try:
            scvi.settings.seed = 0
        except Exception:
            pass

        adatas = []
        for s in train_slices:
            a = _load_counts(s)
            a.obs["slice_batch"] = s
            adatas.append(a)
        pooled = ad.concat(adatas, join="inner", index_unique="-")
        # HVG selection on the SPARSE pooled counts. Never densify the full
        # ~34k x 33538 matrix (that is ~4.5 GB and thrashes); seurat_v3 runs on
        # sparse. Densify only the small HVG submatrix below.
        n_hvg = int(min(self.hvg, pooled.n_vars))
        sc.pp.highly_variable_genes(pooled, n_top_genes=n_hvg, flavor="seurat_v3")
        genes = pooled.var_names[pooled.var["highly_variable"]].to_numpy()
        train_ad = pooled[:, genes].copy()
        Xs = train_ad.X
        train_ad.X = np.rint(np.asarray(
            Xs.todense() if hasattr(Xs, "todense") else Xs, dtype=np.float32))

        if self.batch:
            scvi.model.SCVI.setup_anndata(train_ad, batch_key="slice_batch")
        else:
            scvi.model.SCVI.setup_anndata(train_ad)
        model = scvi.model.SCVI(train_ad, n_latent=self.n_latent)
        model.train(max_epochs=self.max_epochs, accelerator="cpu",
                    early_stopping=True, enable_progress_bar=False,
                    check_val_every_n_epoch=5)

        z = model.get_latent_representation()
        mu = z.mean(0).astype(np.float32)
        sd = (z.std(0) + 1e-6).astype(np.float32)
        return dict(
            backend="scvi", model=model, genes=genes, mu=mu, sd=sd,
            batch=self.batch, train_slices=list(train_slices),
            components=np.zeros((self.n_latent, 1), np.float32))

    def _subset(self, adata, genes):
        sub = adata[:, list(genes)].copy()
        X = sub.X.todense() if hasattr(sub.X, "todense") else sub.X
        sub.X = np.rint(np.asarray(X, dtype=np.float32))
        return sub

    def transform(self, adata, basis):
        import scvi
        model = basis["model"]
        sub = self._subset(adata, basis["genes"])
        if basis["batch"]:
            slice_id = str(adata.obs["sample_id"].iloc[0]) if "sample_id" in adata.obs \
                else "query"
            sub.obs["slice_batch"] = slice_id
            train_ids = set(basis["train_slices"])
            seen = (slice_id in train_ids) or (f"DLPFC_{slice_id}" in train_ids)
            if seen:
                z = model.get_latent_representation(sub)
            else:
                scvi.model.SCVI.prepare_query_anndata(sub, model)
                q = scvi.model.SCVI.load_query_data(sub, model)
                q.train(max_epochs=40, accelerator="cpu",
                        enable_progress_bar=False,
                        plan_kwargs=dict(weight_decay=0.0))
                z = q.get_latent_representation()
        else:
            z = model.get_latent_representation(sub)
        return ((z - basis["mu"]) / basis["sd"]).astype(np.float32)


class PretrainedBackend(Backend):
    """scGPT / Geneformer / UCE. Need a large pretrained checkpoint + vocab
    download and (often) a CUDA / flash-attn build. Attempt import here so an
    unavailable model logs a precise reason and is skipped rather than faked."""
    def __init__(self, name, modules, note):
        self.name = name
        self._modules = modules
        self._note = note

    def available(self):
        errs = []
        for m in self._modules:
            try:
                __import__(m)
                return True, f"{m} importable"
            except Exception as e:
                errs.append(f"{m}: {type(e).__name__}: {e}")
        return False, f"no backend importable ({self._note}). " + " | ".join(errs)

    def fit(self, train_slices):
        raise RuntimeError(
            f"{self.name}: pretrained weights/vocab not available in this "
            f"environment ({self._note}).")

    def transform(self, adata, basis):
        raise RuntimeError(f"{self.name}: unavailable")


def make_backend(name):
    if name == "svd":
        return SvdBackend()
    if name == "scvi":
        return ScviBackend(n_latent=gm.HP["pca_dim"], max_epochs=40, batch=False)
    if name == "scvi_batch":
        return ScviBackend(n_latent=gm.HP["pca_dim"], max_epochs=40, batch=True)
    if name == "scgpt":
        return PretrainedBackend(
            "scgpt", ["scgpt"],
            "needs pretrained scGPT checkpoint + gene vocab download, often "
            "flash-attn/CUDA")
    if name == "geneformer":
        return PretrainedBackend(
            "geneformer", ["geneformer"],
            "needs HuggingFace Geneformer model + tokenizer/median-dict download")
    if name == "uce":
        return PretrainedBackend(
            "uce", ["uce", "UCE"],
            "needs UCE repo + multi-GB protein-embedding + model checkpoint download")
    raise ValueError(f"unknown feature backend: {name}")


DEFAULT_FEATURES = ["svd", "scvi", "scvi_batch", "scgpt", "geneformer", "uce"]


def append_row(row):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = CSV_PATH.exists()
    full = {k: row.get(k, "") for k in CSV_FIELDS}
    with open(CSV_PATH, "a", newline="", encoding="ascii", errors="replace") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(full)


def run_feature(name):
    log(f"=== feature '{name}' ===")
    backend = make_backend(name)
    ok, detail = backend.available()
    if not ok:
        log(f"[{name}] SKIP - not available: {detail}")
        append_row(dict(feature=name, status="skipped_unavailable",
                        detail=detail, timestamp=_now(), svd_ref_heldout=SVD_REF_HELDOUT))
        return
    log(f"[{name}] available: {detail}")

    def _patch():
        gm.fit_fold_basis = lambda train_slices, feature, dim, hvg_n: backend.fit(train_slices)
        gm.transform = lambda adata, basis: backend.transform(adata, basis)

    _patch()
    donors = list(gm.DONORS)
    for ho in donors:
        train_donors = [d for d in donors if d != ho]
        t0 = time.time()
        try:
            r = gm.train_fold(CFG, train_donors, ho)
            dt = round(time.time() - t0, 1)
            paste2 = gm.PASTE2[ho]
            row = dict(
                feature=name, held_out_donor=ho,
                train_donors="+".join(train_donors), feat_dim=r["dim"],
                in_dist_error=r["in_dist"], held_out_error=r["held_out"],
                paste2_error=paste2, svd_ref_heldout=SVD_REF_HELDOUT,
                beats_paste2=bool(r["held_out"] <= paste2),
                delta_vs_paste2=round(r["held_out"] - paste2, 3),
                n_train_pairs=r["n_train_pairs"], seconds=dt, status="ok",
                timestamp=_now(), detail=detail)
            append_row(row)
            log(f"[{name}] hold-out {ho}: held_out={r['held_out']} "
                f"in_dist={r['in_dist']} (PASTE2 {paste2}, SVD_ref {SVD_REF_HELDOUT}) "
                f"dim={r['dim']} {dt}s beats_paste2={row['beats_paste2']}")
        except Exception as e:
            dt = round(time.time() - t0, 1)
            tb = traceback.format_exc()
            log(f"[{name}] hold-out {ho} FAILED after {dt}s: {e!r}\n{tb}")
            append_row(dict(feature=name, held_out_donor=ho,
                            train_donors="+".join(train_donors), status="error",
                            seconds=dt, timestamp=_now(),
                            svd_ref_heldout=SVD_REF_HELDOUT,
                            detail=f"{type(e).__name__}: {e}"))
        finally:
            _patch()

    gm.fit_fold_basis = _ORIG_FIT_FOLD_BASIS
    gm.transform = _ORIG_TRANSFORM


def _read_rows():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="", encoding="ascii", errors="replace") as fh:
        return list(csv.DictReader(fh))


def _feature_summary(rows):
    from collections import defaultdict
    ok = defaultdict(list)
    status = {}
    for r in rows:
        status.setdefault(r["feature"], r.get("status", ""))
        if r.get("status") == "ok" and r.get("held_out_error") not in ("", None):
            try:
                ok[r["feature"]].append(
                    (float(r["held_out_error"]), float(r["paste2_error"])))
            except (ValueError, TypeError):
                pass
        elif r.get("status", "").startswith("skipped") or r.get("status") == "error":
            status[r["feature"]] = r.get("status")
    out = {}
    for feat, vals in ok.items():
        ho = [v[0] for v in vals]
        p2 = [v[1] for v in vals]
        out[feat] = dict(mean_heldout=float(np.mean(ho)), folds=len(ho),
                         mean_paste2=float(np.mean(p2)), status="ok")
    for feat, st in status.items():
        if feat not in out:
            out[feat] = dict(mean_heldout=None, folds=0, mean_paste2=None, status=st)
    return out


def make_plot(rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        log(f"plot skipped - matplotlib import failed: {e!r}")
        return
    summ = _feature_summary(rows)
    feats = [f for f in DEFAULT_FEATURES if f in summ and summ[f]["status"] == "ok"]
    if not feats:
        log("plot skipped - no completed conditions")
        return
    mean_paste2 = float(np.mean([summ[f]["mean_paste2"] for f in feats]))
    vals = [summ[f]["mean_heldout"] for f in feats]

    fig, axo = plt.subplots(figsize=(max(6, 1.4 * len(feats) + 3), 5))
    x = np.arange(len(feats))
    colors = ["#6633ee" if f != "svd" else "#999999" for f in feats]
    axo.bar(x, vals, color=colors, width=0.6, zorder=3)
    axo.axhline(mean_paste2, color="#d1495b", ls="--", lw=2, zorder=2,
                label=f"PASTE2 (mean {mean_paste2:.2f})")
    axo.axhline(SVD_REF_HELDOUT, color="#2e7d32", ls=":", lw=2, zorder=2,
                label=f"prior SVD plateau ({SVD_REF_HELDOUT})")
    for xi, v in zip(x, vals):
        axo.text(xi, v + 0.15, f"{v:.2f}", ha="center", va="bottom", fontsize=10)
    axo.set_xticks(x)
    axo.set_xticklabels(feats, rotation=0)
    axo.set_ylabel("LODO held-out error (median spot-pitches, lower=better)")
    axo.set_title("Foundation-model node features vs SVD and PASTE2\n"
                  "(cross-donor generalization on the DLPFC tear benchmark)")
    axo.set_ylim(0, max(max(vals), SVD_REF_HELDOUT, mean_paste2) * 1.18 + 1)
    axo.legend(loc="upper right", frameon=False)
    axo.grid(axis="y", alpha=0.3, zorder=0)
    fig.tight_layout()
    fig.savefig(PNG_PATH, dpi=130)
    plt.close(fig)
    log(f"wrote {PNG_PATH}")


def write_findings(rows):
    summ = _feature_summary(rows)
    ranked = sorted(
        [(f, s) for f, s in summ.items() if s["status"] == "ok"],
        key=lambda kv: kv[1]["mean_heldout"])
    mean_paste2 = (float(np.mean([s["mean_paste2"] for _, s in ranked]))
                   if ranked else None)

    lines = []
    lines.append("# Foundation-model features vs Sutura SVD - cross-donor generalization\n")
    lines.append(f"_Generated {_now()} on branch `foundation-features`._\n")
    lines.append(
        "**Question.** Sutura's per-fold TruncatedSVD node features plateau at "
        f"~{SVD_REF_HELDOUT} spot-pitches held-out-donor error (PASTE2 ~3.5). Does "
        "swapping in a pretrained/self-supervised foundation-model embedding - with "
        "the alignment architecture, tear benchmark, LODO protocol, and training "
        "recipe (augmentation + weight decay + early stopping) all held fixed - move "
        "held-out error toward or below PASTE2?\n")

    if not ranked:
        lines.append("\n**Result: no condition completed.** See the log for why each "
                     "backend was skipped or errored.\n")
    else:
        best_feat, best = ranked[0]
        gap_closed = SVD_REF_HELDOUT - best["mean_heldout"]
        vs_paste2 = best["mean_heldout"] - best["mean_paste2"]
        verdict = ("CLOSES the gap: at or below PASTE2" if vs_paste2 <= 0 else
                   "narrows but does NOT reach PASTE2"
                   if best["mean_heldout"] < SVD_REF_HELDOUT else
                   "does NOT help vs the SVD plateau")
        lines.append(f"\n**Headline.** Best embedding = `{best_feat}` at "
                     f"{best['mean_heldout']:.2f} pitches held-out "
                     f"(PASTE2 {best['mean_paste2']:.2f}, prior SVD {SVD_REF_HELDOUT}). "
                     f"It **{verdict}** "
                     f"(moves {gap_closed:+.2f} vs the SVD plateau; "
                     f"{vs_paste2:+.2f} vs PASTE2).\n")

        lines.append("\n## Ranked held-out error (mean over LODO folds, lower is better)\n")
        lines.append("| rank | feature | held-out (pitch) | PASTE2 | vs PASTE2 | "
                     "vs SVD plateau | folds |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, (f, s) in enumerate(ranked, 1):
            lines.append(
                f"| {i} | `{f}` | {s['mean_heldout']:.2f} | {s['mean_paste2']:.2f} | "
                f"{s['mean_heldout'] - s['mean_paste2']:+.2f} | "
                f"{s['mean_heldout'] - SVD_REF_HELDOUT:+.2f} | {s['folds']} |")
        lines.append(f"\nReference lines: prior SVD plateau {SVD_REF_HELDOUT}, "
                     f"PASTE2 mean {mean_paste2:.2f} pitches.\n")

    skipped = [(f, s) for f, s in summ.items() if s["status"] != "ok"]
    if skipped:
        lines.append("\n## Conditions skipped or failed (installability / runtime)\n")
        for f, s in skipped:
            det = ""
            for r in rows:
                if r["feature"] == f and r.get("detail"):
                    det = r["detail"]
                    break
            lines.append(f"- `{f}`: {s['status']} - {det}")
        lines.append("")

    lines.append("\n## Per-fold detail\n")
    lines.append("| feature | held-out donor | held-out (pitch) | in-dist | PASTE2 | "
                 "beats PASTE2 | dim | sec | status |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r.get("status") == "ok":
            lines.append(
                f"| `{r['feature']}` | {r['held_out_donor']} | {r['held_out_error']} | "
                f"{r['in_dist_error']} | {r['paste2_error']} | {r['beats_paste2']} | "
                f"{r['feat_dim']} | {r['seconds']} | ok |")
        else:
            lines.append(
                f"| `{r['feature']}` | {r.get('held_out_donor','')} | - | - | - | - | "
                f"- | {r.get('seconds','')} | {r.get('status','')} |")

    lines.append("\n## Interpretation\n")
    if ranked:
        best_feat, best = ranked[0]
        if best["mean_heldout"] <= best["mean_paste2"]:
            lines.append(
                f"A foundation-model embedding (`{best_feat}`) reached PASTE2 on "
                "held-out donors where linear SVD could not - evidence that the "
                "cross-donor failure was a FEATURE-TRANSFER problem, not an "
                "architecture limit.")
        elif best["mean_heldout"] < SVD_REF_HELDOUT - 1.0:
            lines.append(
                f"`{best_feat}` narrows the cross-donor gap materially vs the SVD "
                f"plateau ({best['mean_heldout']:.2f} vs {SVD_REF_HELDOUT}) but still "
                "trails PASTE2 - the embedding is a better prior, yet not sufficient "
                "on its own.")
        else:
            lines.append(
                "No embedding tested meaningfully beat the SVD plateau. The "
                "cross-donor gap does NOT appear to be fixable by swapping node "
                "features alone - consistent with the atlas-diversity result that "
                "the bottleneck is donor count / the alignment prior, not the "
                "expression featurizer.")
    lines.append("")

    FINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FINDINGS_PATH.write_text("\n".join(lines), encoding="ascii", errors="replace")
    log(f"wrote {FINDINGS_PATH}")


def summarize():
    rows = _read_rows()
    make_plot(rows)
    write_findings(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--features", default=",".join(DEFAULT_FEATURES),
                   help="comma list from: " + ",".join(DEFAULT_FEATURES))
    p.add_argument("--plot-only", action="store_true",
                   help="regenerate png + findings from the existing csv and exit")
    args = p.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.plot_only:
        summarize()
        return

    feats = [f.strip() for f in args.features.split(",") if f.strip()]
    log("=" * 72)
    log(f"FOUNDATION-FEATURES run start | features={feats}")
    log(f"data dir: {DATA_DIR}")
    log(f"config: {CFG.name} augment={CFG.augment} wd={CFG.weight_decay} "
        f"early_stop={CFG.early_stop} epochs={CFG.epochs} "
        f"donors={list(gm.DONORS)} pairs_per_donor={CFG.pairs_per_donor}")
    log(f"PASTE2 held-out refs (pitch): {gm.PASTE2}  |  prior SVD plateau {SVD_REF_HELDOUT}")
    log("=" * 72)

    for feat in feats:
        try:
            run_feature(feat)
        except Exception as e:
            log(f"[{feat}] TOP-LEVEL FAILURE: {e!r}\n{traceback.format_exc()}")
            append_row(dict(feature=feat, status="error", timestamp=_now(),
                            detail=f"{type(e).__name__}: {e}"))
        try:
            summarize()
        except Exception as e:
            log(f"summary refresh failed: {e!r}")

    log("FOUNDATION-FEATURES run complete.")
    log("DONE")


if __name__ == "__main__":
    main()
