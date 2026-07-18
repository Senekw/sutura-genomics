"""Plots for the global-reconstruction study. Reads research/results/global_recon.csv
and writes PNG panels into research/results/.

Figures:
  global_recon_drift.png     - drift (pose error) vs chain length, pairwise vs global
  global_recon_panels.png    - gate, robustness, and runtime/cost panels
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.abspath(os.path.join(HERE, "..", "results"))
CSV = os.path.join(RESULTS, "global_recon.csv")

C_PAIR = "#c1440e"     # pairwise (warm)
C_GADJ = "#8a8a8a"     # global adjacent-only
C_GBAND = "#1f6feb"    # global band
C_GFULL = "#0b3d91"    # global full


def _agg(df, method, metric, by="chain_len"):
    d = df[(df.method == method) & (df.metric == metric)]
    g = d.groupby(by).value.agg(["mean", "std", "count"]).reset_index()
    return g


def fig_drift(df):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    ctrl = df[df.experiment == "controlled"]

    for ax, metric, title in [
        (axes[0], "terminal_err", "Terminal-section error (worst drift)"),
        (axes[1], "mean_err", "Mean-over-sections error"),
    ]:
        for method, color, label in [
            ("pairwise_chain", C_PAIR, "pairwise chain (current)"),
            ("global_band", C_GBAND, "global solve (band-3)"),
            ("global_full", C_GFULL, "global solve (full)"),
        ]:
            g = _agg(ctrl, method, metric)
            if g.empty:
                continue
            ax.errorbar(g.chain_len, g["mean"], yerr=g["std"], marker="o",
                        color=color, label=label, capsize=3, lw=2)
        ax.set_xlabel("chain length (sections)")
        ax.set_ylabel("pose error (pixels, RMS vs ground truth)")
        ax.set_title(title)
        ax.set_xticks([2, 4, 8, 12])
        ax.grid(alpha=0.3)
        ax.legend(fontsize=9)
    fig.suptitle("Drift accumulation: pairwise chaining vs global solve "
                 "(controlled ground truth, DLPFC geometry)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = os.path.join(RESULTS, "global_recon_drift.png")
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print("wrote", out)


def fig_panels(df):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))

    # --- panel 1: gate vs fraction of bad edges ---
    ax = axes[0]
    gate = df[df.experiment == "gate"]
    if not gate.empty:
        gate = gate.copy()
        gate["frac"] = gate["note"].str.extract(r"frac_bad=([0-9.]+)").astype(float)
        for method, color, label in [
            ("global_band", C_PAIR, "no gate"),
            ("global_band_gated", C_GBAND, "gated"),
            ("global_band_gated_irls", C_GFULL, "gated + IRLS"),
        ]:
            d = gate[gate.method == method]
            g = d.groupby("frac").value.mean().reset_index()
            if not g.empty:
                ax.plot(g.frac, g.value, marker="o", color=color, label=label, lw=2)
        ax.set_yscale("log")
        ax.set_xlabel("fraction of corrupted edges")
        ax.set_ylabel("mean pose error (px, log)")
        ax.set_title("Gate inside the global solve")
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=9)

    # --- panel 2: robustness scenarios ---
    ax = axes[1]
    scen = []
    labels = []
    colors = []
    def add(exp, method, lab, col):
        d = df[(df.experiment == exp) & (df.method == method)]
        if not d.empty:
            scen.append(d.value.mean()); labels.append(lab); colors.append(col)
    add("robust_missing", "pairwise_chain", "missing\npairwise", C_PAIR)
    add("robust_missing", "global_band", "missing\nglobal", C_GBAND)
    add("robust_badedge", "global_naive", "bad edge\nnaive", C_PAIR)
    add("robust_badedge", "global_irls", "bad edge\nIRLS", C_GADJ)
    add("robust_badedge", "global_gated", "bad edge\ngated", C_GBAND)
    add("robust_inconsistent", "pairwise_chain", "noisy\npairwise", C_PAIR)
    add("robust_inconsistent", "global_band_irls", "noisy\nglobal", C_GBAND)
    if scen:
        ax.bar(range(len(scen)), scen, color=colors)
        ax.set_xticks(range(len(scen)))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_yscale("log")
        ax.set_ylabel("mean pose error (px, log)")
        ax.set_title("Robustness (lower is better)")
        ax.grid(alpha=0.3, axis="y", which="both")

    # --- panel 3: cost -- number of alignments (edges) vs sections ---
    ax = axes[2]
    rt = df[df.experiment == "runtime"]
    if not rt.empty:
        for method, color, label in [
            ("pairwise_chain", C_PAIR, "pairwise (N-1 edges)"),
            ("global_band3", C_GBAND, "global band-3 (~3N edges)"),
            ("global_full", C_GFULL, "global full (N(N-1)/2 edges)"),
        ]:
            d = rt[rt.method == method].sort_values("chain_len")
            if not d.empty:
                ax.plot(d.chain_len, d.n_edges, marker="o", color=color, label=label, lw=2)
        ax.set_xlabel("sections (N)")
        ax.set_ylabel("pairwise alignments required (edges)")
        ax.set_title("Cost: alignments to feed the solver")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=9)
    fig.suptitle("Gate, robustness, and cost of the global solve", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(RESULTS, "global_recon_panels.png")
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print("wrote", out)


def main():
    df = pd.read_csv(CSV)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    fig_drift(df)
    fig_panels(df)


if __name__ == "__main__":
    main()
