"""
tear_detect_compare - quantify how well our SYNTHETIC benchmark (src/warp_slice.apply_warp)
reflects REAL tissue damage, and show that the realistic generator (tear_detect_realgen) closes
the gap.

It (1) appends realistic-generator rows to research/results/tear_detect.csv (kinds `realistic`
= warp+damage and `realistic_dmg` = damage only), then (2) writes comparison plots and a printed
summary contrasting the damage signatures of:

    real          - untouched real sections (intrinsic damage)
    synthetic     - apply_warp(tear=True)      (smooth warp + rigid-translated 40% chunk)
    warp_only     - apply_warp(tear=False)     (smooth warp only)
    realistic     - realgen (smooth warp + excision + fold)
    realistic_dmg - realgen damage only (no warp)  <- directly comparable to `real`

Plots (research/results/):
    tear_detect_displacement.png   coordinate-displacement axis by kind (the headline gap)
    tear_detect_geometry.png       void area / elongation / fold / expr-jump by kind
    tear_detect_signature.png      2D damage signature (displacement vs missing-tissue)

Usage:
    python research/src/tear_detect_compare.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent.parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import anndata as ad  # noqa: E402
import tear_detect as td  # noqa: E402
from tear_detect_realgen import apply_realistic_damage  # noqa: E402
from tear_detect_scan import SYNTH_BASES, SYNTH_SEVS, SYNTH_SEEDS, FIELDS as _F  # noqa: E402

OUT = ROOT / "research" / "results"
CSV_PATH = OUT / "tear_detect.csv"

KIND_ORDER = ["real", "warp_only", "synthetic", "realistic", "realistic_dmg"]
KIND_COLOR = {"real": "#2a9d8f", "warp_only": "#e9c46a", "synthetic": "#e76f51",
              "realistic": "#8ab17d", "realistic_dmg": "#264653"}
KIND_LABEL = {"real": "real (intrinsic)", "warp_only": "apply_warp (warp only)",
              "synthetic": "apply_warp (warp+rigid tear)", "realistic": "realgen (warp+damage)",
              "realistic_dmg": "realgen (damage only)"}


def _append_realistic():
    """Generate realgen rows and append (idempotently) to the scan CSV."""
    df = pd.read_csv(CSV_PATH)
    have = set(zip(df["kind"].astype(str), df["name"].astype(str)))
    rows = []
    for bname, bpath in SYNTH_BASES:
        if not Path(bpath).exists():
            continue
        base = ad.read_h5ad(bpath)
        base.obsm["spatial"] = np.asarray(base.obsm["spatial"], float)
        for seed in SYNTH_SEEDS:
            for sev in SYNTH_SEVS:
                for warp, kind in ((True, "realistic"), (False, "realistic_dmg")):
                    nm = f"{kind}_{bname}_s{sev:g}_seed{seed}"
                    if (kind, nm) in have:
                        continue
                    try:
                        w, _ = apply_realistic_damage(base, sev, seed=seed, warp=warp)
                        w.obsm["spatial"] = np.asarray(w.obsm["spatial"], float)
                        rep = td.characterize(w, nm)
                        d = rep.to_row()
                        d.update(dict(kind=kind, tissue="realistic", severity=sev, seed=seed,
                                      base=bname, timestamp="compare"))
                        rows.append(d)
                    except Exception as e:  # noqa: BLE001
                        print(f"  realgen FAIL {nm}: {e!r}")
    if rows:
        add = pd.DataFrame(rows)
        allcols = list(df.columns)
        for c in allcols:
            if c not in add.columns:
                add[c] = np.nan
        add = add[allcols]
        add.to_csv(CSV_PATH, mode="a", header=False, index=False)
        print(f"appended {len(rows)} realistic rows")
    return pd.read_csv(CSV_PATH)


def _box_by_kind(ax, df, col, title, ylabel, logy=False):
    data, labels, colors = [], [], []
    for k in KIND_ORDER:
        v = df.loc[df["kind"] == k, col].dropna().values
        if len(v):
            data.append(v); labels.append(k); colors.append(KIND_COLOR[k])
    if not data:
        return
    bp = ax.boxplot(data, patch_artist=True, showfliers=True, widths=0.6)
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c); patch.set_alpha(0.75)
    for med in bp["medians"]:
        med.set_color("black")
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=9)
    if logy:
        ax.set_yscale("symlog", linthresh=1e-3)
    ax.grid(axis="y", alpha=0.3)


def make_plots(df):
    # only sev>0 for the synthetic/realistic kinds (sev=0 is pristine); real has NaN sev
    dmg = df[(df["kind"] == "real") | (df["severity"].fillna(1) > 0)].copy()

    # --- Plot 1: displacement axis (headline) ---
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    _box_by_kind(axes[0], dmg, "frac_displaced",
                 "Fraction of spots displaced > 0.5 pitch\n(real tissue spots NEVER move)",
                 "frac displaced")
    _box_by_kind(axes[1], dmg, "max_coord_resid_pitch",
                 "Max coordinate residual vs array lattice", "pitches", logy=True)
    fig.suptitle("Coordinate-displacement signature: apply_warp injects a shift absent in real data",
                 fontsize=11, y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "tear_detect_displacement.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    # --- Plot 2: damage geometry ---
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    _box_by_kind(axes[0, 0], dmg, "void_area_frac",
                 "Missing-tissue (void) area fraction", "frac of spots", logy=True)
    _box_by_kind(axes[0, 1], dmg, "max_void_elongation",
                 "Void elongation (1=round, >>1=linear cut)", "elongation")
    _box_by_kind(axes[1, 0], dmg, "frac_high_jump_edges",
                 "Expression discontinuity (high-jump neighbor edges)", "frac edges")
    _box_by_kind(axes[1, 1], dmg, "damage_score",
                 "Overall damage score (physically grounded)", "score", logy=True)
    fig.suptitle("Damage geometry: real damage = missing tissue + expression seams; "
                 "apply_warp's rigid tear has neither", fontsize=11, y=1.01)
    fig.tight_layout()
    fig.savefig(OUT / "tear_detect_geometry.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    # --- Plot 3: 2D signature ---
    fig, ax = plt.subplots(figsize=(7.5, 6))
    for k in KIND_ORDER:
        sub = dmg[dmg["kind"] == k]
        if not len(sub):
            continue
        ax.scatter(sub["frac_displaced"] + np.random.default_rng(0).normal(0, 0.006, len(sub)),
                   sub["void_area_frac"].clip(lower=5e-5),
                   s=34, alpha=0.7, color=KIND_COLOR[k], label=KIND_LABEL[k], edgecolors="none")
    ax.set_xlabel("fraction of spots displaced (coordinate artifact)")
    ax.set_ylabel("missing-tissue void area fraction (real damage)")
    ax.set_yscale("log")
    ax.set_title("Damage signature: real & realgen-damage cluster at ZERO displacement;\n"
                 "apply_warp sits at ~1.0 displacement with no missing tissue")
    ax.legend(fontsize=8, loc="center right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "tear_detect_signature.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("wrote plots: tear_detect_displacement.png, tear_detect_geometry.png, "
          "tear_detect_signature.png")


def summary(df):
    dmg = df[(df["kind"] == "real") | (df["severity"].fillna(1) > 0)].copy()
    cols = ["frac_displaced", "max_coord_resid_pitch", "void_area_frac",
            "max_void_elongation", "n_voids", "n_folds", "frac_high_jump_edges", "damage_score"]
    g = dmg.groupby("kind")[cols].median(numeric_only=True).reindex(KIND_ORDER)
    print("\n=== median damage signature by kind ===")
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(g.round(4).to_string())
    return g


def main():
    df = _append_realistic()
    g = summary(df)
    make_plots(df)
    g.to_csv(OUT / "tear_detect_signature_medians.csv")
    print("\nwrote research/results/tear_detect_signature_medians.csv")


if __name__ == "__main__":
    main()
