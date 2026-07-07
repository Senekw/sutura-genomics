"""Plot the zero-shot generalization sweep: Sutura vs PASTE2 median registration
error (in spot-pitches) across datasets and tear severities.

Reads results/generalization_sweep.csv; writes results/generalization_sweep.png.
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

rows = list(csv.DictReader(open(RESULTS / "generalization_sweep.csv")))

# order: train anchor first, then generalization datasets
order, seen = [], set()
for r in rows:
    if r["dataset"] not in seen:
        order.append(r["dataset"]); seen.add(r["dataset"])
kind = {r["dataset"]: r["kind"] for r in rows}


def curve(dataset, method):
    """severity -> mean median-error(pitch) over seeds."""
    by = defaultdict(list)
    for r in rows:
        if r["dataset"] == dataset and r["method"] == method:
            by[float(r["severity"])].append(float(r["median_error_pitch"]))
    xs = sorted(by)
    return xs, [float(np.mean(by[x])) for x in xs]


ymax = max(float(np.mean([float(r["median_error_pitch"]) for r in rows
                          if r["dataset"] == ds and r["method"] == m and
                          float(r["severity"]) == s]))
           for ds in order for m in ("sutura", "paste2")
           for s in {float(r["severity"]) for r in rows if r["dataset"] == ds})

n = len(order)
fig, axes = plt.subplots(1, n, figsize=(3.6 * n, 4.4), sharey=True)
if n == 1:
    axes = [axes]
for ax, ds in zip(axes, order):
    sx, sy = curve(ds, "sutura")
    px, py = curve(ds, "paste2")
    ax.plot(sx, sy, "o-", color="tab:blue", lw=2, label="Sutura (zero-shot)")
    ax.plot(px, py, "s-", color="crimson", lw=2, label="PASTE2")
    ax.axhline(1.0, color="gray", ls=":", lw=1, label="1 spot-pitch (good)")
    # annotate the severity-averaged medians so both lines are legible even when
    # Sutura sits near the top of the shared axis
    ax.annotate(f"Sutura ~{np.mean(sy):.1f}", (sx[len(sx)//2], np.mean(sy)),
                textcoords="offset points", xytext=(0, 6), ha="center",
                fontsize=8, color="tab:blue")
    ax.annotate(f"PASTE2 ~{np.mean(py):.1f}", (px[len(px)//2], np.mean(py)),
                textcoords="offset points", xytext=(0, -14), ha="center",
                fontsize=8, color="crimson")
    ax.set_title(f"{ds}\n{kind[ds]}", fontsize=9)
    ax.set_xlabel("tear severity (pitches)")
    ax.grid(alpha=0.3)
    ax.set_ylim(0, ymax * 1.12)
axes[0].set_ylabel("median registration error (spot-pitches)")
axes[0].legend(fontsize=8, loc="center left")
fig.suptitle("Sutura zero-shot vs PASTE2 — synthetic tear benchmark across datasets",
             fontsize=12, y=1.02)
fig.tight_layout()
out = RESULTS / "generalization_sweep.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")

# console summary table (severity-averaged)
print(f"\n{'dataset':22s} {'kind':30s} {'Sutura(p)':>10s} {'PASTE2(p)':>10s}")
for ds in order:
    _, sy = curve(ds, "sutura")
    _, py = curve(ds, "paste2")
    print(f"{ds:22s} {kind[ds]:30s} {np.mean(sy):10.2f} {np.mean(py):10.2f}")
