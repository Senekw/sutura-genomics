"""Plot batch-correction results: per-donor median registration error vs tear
severity for shared-basis (none), +Harmony, +Scanorama, and PASTE2.
Reads results/batch_correct.csv; writes results/batch_correct.png.
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
ORDER = ["Br5292", "Br5595", "Br8100"]
STYLE = {"shared_basis": ("o-", "tab:blue", "shared basis (no correction)"),
         "harmony": ("D-", "tab:green", "+ Harmony"),
         "scanorama": ("v-", "tab:purple", "+ Scanorama"),
         "paste2": ("^-", "crimson", "PASTE2")}

rows = list(csv.DictReader(open(RESULTS / "batch_correct.csv")))
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
    for method, (fmt, color, lab) in STYLE.items():
        x, y = curve(donor, method)
        if x:
            ax.plot(x, y, fmt, color=color, lw=2, ms=6, label=lab)
    ax.axhline(1.0, color="gray", ls=":", lw=1)
    tag = "TRAIN" if cond.get(donor) == "in-distribution" else "HELD-OUT"
    ax.set_title(f"{donor}  ({tag} donor)", fontsize=10)
    ax.set_xlabel("tear severity (spot-pitches)")
    ax.grid(alpha=0.3)
    ax.set_ylim(0, 12)
axes[0].set_ylabel("median registration error (spot-pitches)")
axes[-1].legend(fontsize=8, loc="upper left")
fig.suptitle("Batch correction on shared-basis features — does it close the "
             "held-out gap?", fontsize=12, y=1.02)
fig.tight_layout()
out = RESULTS / "batch_correct.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
