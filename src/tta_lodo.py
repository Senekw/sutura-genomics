"""
Test-time adaptation (TTA) on the held-out donor - 3-DLPFC LODO tear benchmark.

WHY. The foundation-features experiment established the cross-donor gap is an ALIGNER
generalization problem, not a feature-transfer problem (neither learned embeddings nor
transductive featurization closed it). This tests the direct remedy on the aligner: at
inference, self-supervisedly adapt the trained aligner to the held-out donor's OWN
section geometry, then score the real held-out pair.

SELF-SUPERVISED TTA (no target correspondence used). For the held-out donor's ref
section A, generate synthetic tears of A (moving = warped copy of A, node features =
A's own SVD features), and adapt the model to map each warped-A spot back to its known
original A coordinate (self-GT; the real A-B correspondence is NEVER touched). Then
score the real held-out pair (A vs warped real B) exactly as the LODO benchmark does.
This is the honest "adapt to unseen geometry at deploy time" scenario (autoadapt.py's
`self` mode, but run inside the multi-severity 3-fold LODO protocol for the first time).

WHAT IS HELD FIXED: SVD features (features are not the variable here), the alignment
architecture, the median-spot-pitch metric, the 3-donor LODO protocol, and the base
training recipe (augment + wd + early stop). The base model is trained by reusing
generalization_max.train_fold UNCHANGED (captured via monkeypatch, no code fork); TTA
adapts a COPY so the no-TTA number is the same trained model.

Outputs: research/results/tta_lodo.{csv,png,log}, research/FINDINGS_tta_lodo.md
Usage:  python src/tta_lodo.py            # 3-fold LODO, TTA vs no-TTA vs PASTE2
        python src/tta_lodo.py --plot-only
"""
from __future__ import annotations

import argparse
import copy
import csv
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import generalization_max as gm  # noqa: E402
from train_cross import ARCACrossNet, graph_tensors  # noqa: E402
from warp_slice import apply_warp  # noqa: E402
from scoring import registration_error_stats  # noqa: E402

MAIN_REPO = Path(r"C:\Users\karti\arca")
if (MAIN_REPO / "data").exists():
    gm.DATA = MAIN_REPO / "data"

OUT_DIR = ROOT / "research" / "results"
CSV_PATH = OUT_DIR / "tta_lodo.csv"
LOG_PATH = OUT_DIR / "tta_lodo.log"
PNG_PATH = OUT_DIR / "tta_lodo.png"
FINDINGS_PATH = ROOT / "research" / "FINDINGS_tta_lodo.md"
LOCK_PATH = OUT_DIR / "tta_lodo.lock"

# Base-aligner recipe == generalization_max augment_reg (SVD features).
CFG = gm.Config(name="tta_base", feature="svd", n_train_donors=2, pairs_per_donor=2,
                augment=True, weight_decay=1e-4, early_stop=True, epochs=60,
                steps_per_epoch=20, lr=1e-3)
# TTA knobs (mirror autoadapt.py self mode).
TTA_EPOCHS = 30
TTA_STEPS = 12
TTA_LR = 1e-3
TTA_MAXSEV = 8.0
TTA_TEARP = 0.5
TTA_PATIENCE = 4
TTA_VAL_SEVS = (2.0, 6.0)
TTA_VAL_SEED = 777
MODE = "self"   # "self" (synthetic self-warps of held-out ref) | "sibling" (2nd pair GT)

CSV_FIELDS = ["held_out_donor", "train_donors", "held_out_notta", "held_out_tta",
              "delta_tta", "paste2_error", "svd_ref_heldout", "tta_beats_paste2",
              "in_dist", "tta_steps_used", "seconds", "status", "timestamp", "detail"]
SVD_REF_HELDOUT = 9.6


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="ascii", errors="replace") as fh:
        fh.write(line + "\n")


def append_row(row):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = CSV_PATH.exists()
    full = {k: row.get(k, "") for k in CSV_FIELDS}
    with open(CSV_PATH, "a", newline="", encoding="ascii", errors="replace") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(full)


# --------------------------------------------------------------------------- #
def eval_ho(model, pair, sevs=None, seed=0):
    """Median error / pitch on the real held-out pair, averaged over severities
    (identical metric to generalization_max.eval_pair)."""
    sevs = gm.EVAL_SEVS if sevs is None else sevs
    model.eval()
    errs = []
    for sv in sevs:
        w, _ = apply_warp(pair["B"], sv, seed=seed, tear=True)
        gb = graph_tensors(np.asarray(w.obsm["spatial"], float), pair["Z_B"],
                           pair["knn"], pair["pitch"])
        with torch.no_grad():
            pred = model(pair["ga"], gb, pair["a_norm"]).numpy() * pair["pitch"]
        errs.append(registration_error_stats(pred, pair["gt"], mask=pair["have"])
                    ["median"] / pair["pitch"])
    return float(np.mean(errs))


def _self_recon_err(model, pair, sevs, seed):
    """Self-supervised val: warp the held-out REF A, check the model maps warped-A
    spots back to their own A coords. No real correspondence used."""
    coords = pair["coords"]
    pitch = pair["pitch"]
    gt_self = coords / pitch
    model.eval()
    errs = []
    for sv in sevs:
        w, _ = apply_warp(pair["A"], sv, seed=seed, tear=True)
        gb = graph_tensors(np.asarray(w.obsm["spatial"], float), pair["Z_A"],
                           pair["knn"], pair["pitch"])
        with torch.no_grad():
            pred = model(pair["ga"], gb, pair["a_norm"]).numpy()
        errs.append(float(np.median(np.linalg.norm(pred - gt_self, axis=1))))
    return float(np.mean(errs))


def tta_self_adapt(model, pair, seed=0):
    """Self-supervised TTA on the held-out donor's own ref section. Moving = synthetic
    tears of A; features = A's own SVD features; GT = A's own coords. Adapts ALL params
    (SVD basis stays frozen - features are precomputed). Early-stops on a disjoint-seed
    self-recon val. Returns (adapted_model, steps_used)."""
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=TTA_LR)
    coords = pair["coords"]
    pitch = pair["pitch"]
    gt_self = torch.from_numpy((coords / pitch).astype(np.float32))  # every A spot -> itself
    best_val = _self_recon_err(model, pair, TTA_VAL_SEVS, TTA_VAL_SEED)
    best_state = {k: t.clone() for k, t in model.state_dict().items()}
    bad = 0
    steps_used = 0
    for epoch in range(TTA_EPOCHS):
        model.train()
        for _ in range(TTA_STEPS):
            sv = float(rng.uniform(0, TTA_MAXSEV))
            w, _ = apply_warp(pair["A"], sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < TTA_TEARP))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), pair["Z_A"],
                               pair["knn"], pair["pitch"])
            opt.zero_grad()
            pred = model(pair["ga"], gb, pair["a_norm"])
            loss = (pred - gt_self).norm(dim=1).mean()
            loss.backward()
            opt.step()
            steps_used += 1
        if epoch % 2 == 0 or epoch == TTA_EPOCHS - 1:
            v = _self_recon_err(model, pair, TTA_VAL_SEVS, TTA_VAL_SEED)
            if v < best_val - 1e-3:
                best_val = v
                best_state = {k: t.clone() for k, t in model.state_dict().items()}
                bad = 0
            else:
                bad += 1
                if bad >= TTA_PATIENCE:
                    break
    model.load_state_dict(best_state)
    return model, steps_used


def tta_sibling_adapt(model, adapt_pair, seed=0):
    """Weakly-supervised TTA on the held-out donor's SECOND (disjoint) section pair,
    using its real array-bridge correspondence (autoadapt.py `cross` mode). The
    SCORING pair (donor's first pair) is never touched, so no scoring leakage - only
    a different pair of the same donor provides adaptation signal. Returns
    (adapted_model, steps_used)."""
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=TTA_LR)
    gt_norm = adapt_pair["gt_norm"]
    mask = adapt_pair["mask"]

    def val_err(sevs, vseed):
        model.eval()
        errs = []
        for sv in sevs:
            w, _ = apply_warp(adapt_pair["B"], sv, seed=vseed, tear=True)
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), adapt_pair["Z_B"],
                               adapt_pair["knn"], adapt_pair["pitch"])
            with torch.no_grad():
                pred = model(adapt_pair["ga"], gb, adapt_pair["a_norm"]) * adapt_pair["pitch"]
            errs.append(registration_error_stats(pred.numpy(), adapt_pair["gt"],
                        mask=adapt_pair["have"])["median"] / adapt_pair["pitch"])
        return float(np.mean(errs))

    best_val = val_err(TTA_VAL_SEVS, TTA_VAL_SEED)
    best_state = {k: t.clone() for k, t in model.state_dict().items()}
    bad = 0
    steps_used = 0
    for epoch in range(TTA_EPOCHS):
        model.train()
        for _ in range(TTA_STEPS):
            sv = float(rng.uniform(0, TTA_MAXSEV))
            w, _ = apply_warp(adapt_pair["B"], sv, seed=int(rng.integers(1, 99999)),
                              tear=bool(rng.random() < TTA_TEARP))
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), adapt_pair["Z_B"],
                               adapt_pair["knn"], adapt_pair["pitch"])
            opt.zero_grad()
            pred = model(adapt_pair["ga"], gb, adapt_pair["a_norm"])
            loss = (pred - gt_norm)[mask].norm(dim=1).mean()
            loss.backward()
            opt.step()
            steps_used += 1
        if epoch % 2 == 0 or epoch == TTA_EPOCHS - 1:
            v = val_err(TTA_VAL_SEVS, TTA_VAL_SEED)
            if v < best_val - 1e-3:
                best_val = v
                best_state = {k: t.clone() for k, t in model.state_dict().items()}
                bad = 0
            else:
                bad += 1
                if bad >= TTA_PATIENCE:
                    break
    model.load_state_dict(best_state)
    return model, steps_used


# --------------------------------------------------------------------------- #
def run_fold(ho):
    """Train the base aligner (reuse gm.train_fold unchanged, captured via
    monkeypatch), then self-supervised-TTA a copy on the held-out donor and
    compare held-out error TTA vs no-TTA."""
    donors = list(gm.DONORS)
    train_donors = [d for d in donors if d != ho]
    cap = {}
    orig_fit = gm.fit_fold_basis
    orig_model = gm.ARCACrossNet

    def cap_fit(train_slices, feature, dim, hvg_n):
        b = orig_fit(train_slices, feature, dim, hvg_n)
        cap["basis"] = b
        return b

    def cap_ctor(*a, **k):
        m = orig_model(*a, **k)
        cap["model"] = m
        return m

    gm.fit_fold_basis = cap_fit
    gm.ARCACrossNet = cap_ctor
    try:
        r = gm.train_fold(CFG, train_donors, ho)   # base training + no-TTA eval
    finally:
        gm.fit_fold_basis = orig_fit
        gm.ARCACrossNet = orig_model

    base_model = cap["model"]
    basis = cap["basis"]
    notta = r["held_out"]

    # Rebuild the held-out pair (scoring pair) with the fold's frozen basis.
    ho_pair = gm.prep_pair(*gm.DONORS[ho][0], basis, gm.HP["knn"])

    # Adapt a COPY so the no-TTA number stays the base model's.
    tta_model = copy.deepcopy(base_model)
    if MODE == "sibling":
        # held-out donor's SECOND pair (disjoint from the scoring pair) with real GT
        adapt_pair = gm.prep_pair(*gm.DONORS[ho][1], basis, gm.HP["knn"])
        tta_model, steps_used = tta_sibling_adapt(tta_model, adapt_pair, seed=0)
    else:
        tta_model, steps_used = tta_self_adapt(tta_model, ho_pair, seed=0)
    tta_err = eval_ho(tta_model, ho_pair)

    return dict(in_dist=r["in_dist"], notta=notta, tta=round(tta_err, 3),
                steps=steps_used)


def _read_rows():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="", encoding="ascii", errors="replace") as fh:
        return list(csv.DictReader(fh))


def make_plot(rows):
    ok = [r for r in rows if r.get("status") == "ok"]
    if not ok:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        log(f"plot skipped: {e!r}")
        return
    donors = [r["held_out_donor"] for r in ok]
    notta = [float(r["held_out_notta"]) for r in ok]
    tta = [float(r["held_out_tta"]) for r in ok]
    p2 = [float(r["paste2_error"]) for r in ok]
    x = np.arange(len(donors))
    w = 0.27
    fig, ax = plt.subplots(figsize=(max(6, 1.6 * len(donors) + 3), 5))
    ax.bar(x - w, notta, w, label="Sutura no-TTA", color="#999999", zorder=3)
    ax.bar(x, tta, w, label="Sutura +self-TTA", color="#6633ee", zorder=3)
    ax.bar(x + w, p2, w, label="PASTE2", color="#d1495b", zorder=3)
    ax.axhline(SVD_REF_HELDOUT, color="#2e7d32", ls=":", lw=1.5,
               label=f"prior SVD plateau ({SVD_REF_HELDOUT})", zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels(donors)
    ax.set_ylabel("held-out error (median spot-pitches, lower=better)")
    ax.set_title("Test-time adaptation on the held-out donor\n"
                 "(self-supervised TTA vs no-TTA vs PASTE2, 3-donor LODO tear benchmark)")
    ax.legend(loc="upper right", frameon=False)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    fig.tight_layout()
    fig.savefig(PNG_PATH, dpi=130)
    plt.close(fig)
    log(f"wrote {PNG_PATH}")


def write_findings(rows):
    ok = [r for r in rows if r.get("status") == "ok"]
    lines = ["# Test-time adaptation on the held-out donor - LODO tear benchmark\n"]
    lines.append(f"_Generated {_now()} on branch `foundation-features`._\n")
    lines.append(
        "**Question.** The foundation-features experiment showed the cross-donor gap is "
        "an ALIGNER problem, not a feature problem. Does adapting the trained aligner to "
        "the held-out donor at inference - self-supervised, on the donor's own section "
        "geometry, no target correspondence used - close the gap to PASTE2?\n")
    if not ok:
        lines.append("\n**No folds completed.** See the log.\n")
    else:
        mn = float(np.mean([float(r["held_out_notta"]) for r in ok]))
        mt = float(np.mean([float(r["held_out_tta"]) for r in ok]))
        mp = float(np.mean([float(r["paste2_error"]) for r in ok]))
        nbeat = sum(1 for r in ok if r.get("tta_beats_paste2") == "True")
        verdict = ("CLOSES the gap (reaches PASTE2)" if mt <= mp else
                   "narrows the gap but does NOT reach PASTE2" if mt < mn else
                   "does NOT help")
        lines.append(
            f"\n**Headline.** Self-supervised TTA moves held-out error "
            f"{mn:.2f} -> {mt:.2f} pitches (PASTE2 {mp:.2f}). It **{verdict}** "
            f"({mt - mn:+.2f} vs no-TTA, {mt - mp:+.2f} vs PASTE2; "
            f"{nbeat}/{len(ok)} folds beat PASTE2).\n")
        lines.append("\n## Per-fold\n")
        lines.append("| held-out donor | no-TTA | +self-TTA | delta | PASTE2 | "
                     "beats PASTE2 | in-dist | TTA steps |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in ok:
            lines.append(
                f"| {r['held_out_donor']} | {r['held_out_notta']} | {r['held_out_tta']} | "
                f"{r['delta_tta']} | {r['paste2_error']} | {r['tta_beats_paste2']} | "
                f"{r['in_dist']} | {r['tta_steps_used']} |")
        lines.append(f"\nReference: prior SVD plateau {SVD_REF_HELDOUT}, "
                     f"inductive SVD no-TTA mean was ~8.26 pitches.\n")
        lines.append("\n## Interpretation\n")
        if mt <= mp:
            lines.append("Inference-time self-adaptation reaches PASTE2 - the aligner "
                         "CAN generalize to an unseen donor given a few unsupervised "
                         "steps on its geometry; the gap is a deploy-time adaptation "
                         "problem, not a fundamental limit.")
        elif mt < mn - 0.3:
            lines.append("Self-TTA recovers part of the gap (consistent with autoadapt's "
                         "~30-70% error reductions) but still trails PASTE2 - adaptation "
                         "helps yet the aligner's inductive bias remains the ceiling. "
                         "Routing OOD inputs to PASTE2 stays the right product call.")
        else:
            lines.append("Self-TTA does not materially help on the LODO tear benchmark - "
                         "the aligner cannot self-correct to an unseen donor's geometry "
                         "without target supervision. Confirms routing OOD to PASTE2.")
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
    p.add_argument("--plot-only", action="store_true")
    p.add_argument("--mode", choices=["self", "sibling"], default="self",
                   help="self: synthetic self-warps of held-out ref (no target GT); "
                        "sibling: held-out donor's 2nd pair with real GT (weakly sup.)")
    p.add_argument("--tag", default="", help="output-file suffix")
    p.add_argument("--features", choices=["svd", "scvi"], default="svd",
                   help="node featurizer for BOTH base training and TTA (scvi patches "
                        "generalization_max to use the scVI encoder, testing whether the "
                        "scVI-features and self-TTA levers compound)")
    args = p.parse_args()

    global MODE, CSV_PATH, LOG_PATH, PNG_PATH, FINDINGS_PATH, LOCK_PATH
    MODE = args.mode
    if args.features == "scvi":
        # compose the two working levers: scVI node features + self-TTA. Patch the
        # reusable harness's featurizer to the scVI backend for every fold; run_fold's
        # capture + prep_pair + the TTA loop then all operate on scVI features.
        import foundation_features as ff
        _sb = ff.ScviBackend(n_latent=gm.HP["pca_dim"], max_epochs=40, batch=False)
        gm.fit_fold_basis = lambda ts, f, d, h: _sb.fit(ts)
        gm.transform = lambda a, b: _sb.transform(a, b)
    if args.tag:
        t = args.tag
        CSV_PATH = OUT_DIR / f"tta_lodo_{t}.csv"
        LOG_PATH = OUT_DIR / f"tta_lodo_{t}.log"
        PNG_PATH = OUT_DIR / f"tta_lodo_{t}.png"
        FINDINGS_PATH = ROOT / "research" / f"FINDINGS_tta_lodo_{t}.md"
        LOCK_PATH = OUT_DIR / f"tta_lodo_{t}.lock"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.plot_only:
        summarize()
        return

    log("=" * 72)
    log(f"TTA-LODO run start (mode={MODE}, features={args.features}) out={CSV_PATH.name}")
    log(f"base cfg: augment_reg epochs={CFG.epochs}; TTA epochs={TTA_EPOCHS} "
        f"steps={TTA_STEPS} lr={TTA_LR} patience={TTA_PATIENCE}")
    log(f"PASTE2 refs: {gm.PASTE2} | prior SVD plateau {SVD_REF_HELDOUT}")
    log("=" * 72)

    for ho in list(gm.DONORS):
        t0 = time.time()
        try:
            r = run_fold(ho)
            dt = round(time.time() - t0, 1)
            paste2 = gm.PASTE2[ho]
            row = dict(held_out_donor=ho,
                       train_donors="+".join(d for d in gm.DONORS if d != ho),
                       held_out_notta=r["notta"], held_out_tta=r["tta"],
                       delta_tta=round(r["tta"] - r["notta"], 3), paste2_error=paste2,
                       svd_ref_heldout=SVD_REF_HELDOUT,
                       tta_beats_paste2=bool(r["tta"] <= paste2), in_dist=r["in_dist"],
                       tta_steps_used=r["steps"], seconds=dt, status="ok",
                       timestamp=_now(), detail="")
            append_row(row)
            log(f"[{ho}] no-TTA={r['notta']} +TTA={r['tta']} "
                f"(delta {row['delta_tta']:+}, PASTE2 {paste2}) steps={r['steps']} {dt}s "
                f"beats_paste2={row['tta_beats_paste2']}")
        except Exception as e:
            dt = round(time.time() - t0, 1)
            log(f"[{ho}] FAILED after {dt}s: {e!r}\n{traceback.format_exc()}")
            append_row(dict(held_out_donor=ho, status="error", seconds=dt,
                            timestamp=_now(), detail=f"{type(e).__name__}: {e}"))
        try:
            summarize()
        except Exception as e:
            log(f"summary refresh failed: {e!r}")

    log("TTA-LODO run complete.")
    log("DONE")


if __name__ == "__main__":
    main()
