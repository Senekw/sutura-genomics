"""Plot Fix A results: per-donor median registration error vs tear severity for the
old per-SVD model, the new shared-frozen-basis model, and PASTE2, with the
centroid-prediction (total-collapse) reference. Reads results/shared_basis_eval.csv.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parent.parent / "results"
CENTROID = {"Br5292": 24.28, "Br5595": 21.72, "Br8100": 22.16}
ORDER = ["Br5292", "Br5595", "Br8100"]
STYLE = {"sutura_persvd": ("s--", "gray", "old per-SVD model"),
         "sutura_shared": ("o-", "tab:blue", "shared frozen basis (new)"),
         "paste2": ("^-", "crimson", "PASTE2")}

rows = list(csv.DictReader(open(RESULTS / "shared_basis_eval.csv")))
cond = {r["donor"]: r["condition"] for r in rows}


def curve(donor, method):
    by = defaultdict(list)
    for r in rows:
        if r["donor"] == donor and r["method"] == method:
            by[float(r["severity"])].append(float(r["median_error_pitch"]))
    xs = sorted(by)
    return xs, [float(np.mean(by[x])) for x in xs]


fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), sharey=True)
for ax, donor in zip(axes, ORDER):
    ax.axhline(CENTROID[donor], color="black", ls=":", lw=1,
               label=f"centroid collapse ({CENTROID[donor]:.0f})")
    ax.axhline(1.0, color="green", ls=":", lw=1, alpha=0.6)
    for method, (fmt, color, lab) in STYLE.items():
        x, y = curve(donor, method)
        if x:
            ax.plot(x, y, fmt, color=color, lw=2, ms=6, label=lab)
    tag = "TRAIN donor" if cond[donor] == "in-distribution" else "HELD-OUT donor"
    ax.set_title(f"{donor}  ({tag})", fontsize=10)
    ax.set_xlabel("tear severity (spot-pitches)")
    ax.grid(alpha=0.3)
    ax.set_ylim(0, 25)
axes[0].set_ylabel("median registration error (spot-pitches)")
axes[0].legend(fontsize=8, loc="center right")
fig.suptitle("Fix A: shared frozen SVD basis — does it rescue cross-donor "
             "generalization?", fontsize=12, y=1.02)
fig.tight_layout()
out = RESULTS / "shared_basis_eval.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
