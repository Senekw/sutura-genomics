"""
Plot the atlas sweep: Sutura (zero-shot + auto-adapted) vs PASTE2 vs the
orchestrator's chosen method, across every swept dataset.

Datasets are split by the router's decision (in-distribution -> Sutura,
off-distribution -> PASTE2) and sorted so the in-distribution wins sit together.
Bars are grouped median registration error in pitch units (lower = better);
datasets whose error is only a footprint-coverage proxy (no bridge GT) are
annotated and drawn on a separate marker so they are not read as real error.

Usage:  python src/plot_atlas_sweep.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "research" / "results"
CSVP = RESULTS / "atlas_sweep.csv"
PNGP = RESULTS / "atlas_sweep.png"


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def main():
    rows = [r for r in csv.DictReader(open(CSVP, encoding="utf-8"))
            if r.get("error_type") == "median_pitch"]
    # keep only rows with a real median error and sort: in-dist first, then by error
    rows.sort(key=lambda r: (r["in_distribution"] != "True", fnum(r["chosen_error"])))
    names = [r["name"] for r in rows]
    x = np.arange(len(names))
    w = 0.26

    zs = np.array([fnum(r["sutura_zeroshot"]) for r in rows])
    adp = np.array([fnum(r["sutura_adapted"]) for r in rows])
    p2 = np.array([fnum(r["paste2"]) for r in rows])
    chosen = np.array([fnum(r["chosen_error"]) for r in rows])
    in_dist = np.array([r["in_distribution"] == "True" for r in rows])

    fig, ax = plt.subplots(figsize=(max(9, 1.5 * len(names)), 6))
    ax.bar(x - w, zs, w, label="Sutura (zero-shot)", color="#6633ee")
    ax.bar(x, adp, w, label="Sutura (auto-adapted)", color="#a98bf5")
    ax.bar(x + w, p2, w, label="PASTE2", color="#f0a030")
    # mark the orchestrator's chosen result
    ax.scatter(x, chosen, marker="D", s=70, zorder=5, color="#111",
               label="Orchestrator chosen")

    for i, di in enumerate(in_dist):
        ax.axvspan(i - 0.5, i + 0.5, color=("#e8f5e9" if di else "#fdecea"),
                   alpha=0.5, zorder=0)

    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=35, ha="right", fontsize=9)
    ax.set_ylabel("median registration error (pitch units, lower better)")
    ax.set_title("Atlas sweep: Sutura vs PASTE2 vs orchestrator\n"
                 "green = routed to Sutura (in-distribution) | "
                 "red = routed to PASTE2 (off-distribution)")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(PNGP, dpi=130)
    print(f"wrote {PNGP} ({len(names)} datasets with real GT)")


if __name__ == "__main__":
    main()
