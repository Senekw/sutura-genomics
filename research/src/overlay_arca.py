"""Overlay ARCA's cross-tear registration-error curve on the PASTE2 tear axes.

Both curves are scored on the SAME warped slices (apply_warp seed=0, tear=True,
severities 0,1,2,3,4,6,8) against the SAME array-bridge ground truth in 151507's
pixel frame, so the comparison is apples-to-apples.

Left  : head-to-head median reg-err vs severity (PASTE2 tear vs ARCA).
Right : ARCA's own median / mean / p90 — shows the tear concentrates error in
        the torn-region tail while the median stays low.
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parent.parent / "results"


def load(name, cols):
    with open(RESULTS / name) as fh:
        rows = list(csv.DictReader(fh))
    return {c: [float(r[c]) for r in rows] for c in cols}


paste2 = load("sweep_deformation_cross_tear.csv", ["severity", "reg_err_median"])
arca = load("arca_cross_curve.csv",
            ["severity", "reg_err_median", "reg_err_mean", "reg_err_p90"])

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

# --- left: head-to-head median ---
ax1.plot(paste2["severity"], paste2["reg_err_median"], "s-", color="crimson",
         lw=2, ms=7, label="PASTE2 (GW/OT) tear")
ax1.plot(arca["severity"], arca["reg_err_median"], "o-", color="tab:blue",
         lw=2, ms=7, label="ARCA (GNN) tear")
ax1.axhline(137.0, color="gray", ls=":", lw=1, label="1 spot pitch (137 px)")
ax1.set_xlabel("tear severity (spot-pitches)")
ax1.set_ylabel("registration error — median (px)")
ax1.set_title("ARCA vs PASTE2 on torn tissue (same warps, same GT)")
ax1.set_ylim(0, None)
ax1.grid(alpha=0.3)
ax1.legend()
for x, y in zip(arca["severity"], arca["reg_err_median"]):
    ax1.annotate(f"{y:.0f}", (x, y), textcoords="offset points",
                 xytext=(0, -14), ha="center", fontsize=8, color="tab:blue")
for x, y in zip(paste2["severity"], paste2["reg_err_median"]):
    ax1.annotate(f"{y:.0f}", (x, y), textcoords="offset points",
                 xytext=(0, 8), ha="center", fontsize=8, color="crimson")

# --- right: ARCA error distribution (where tearing bites) ---
ax2.plot(arca["severity"], arca["reg_err_median"], "o-", color="tab:blue",
         label="median")
ax2.plot(arca["severity"], arca["reg_err_mean"], "s--", color="tab:orange",
         label="mean")
ax2.plot(arca["severity"], arca["reg_err_p90"], "^:", color="tab:red",
         label="p90")
ax2.axhline(137.0, color="gray", ls=":", lw=1, label="1 spot pitch")
ax2.set_xlabel("tear severity (spot-pitches)")
ax2.set_ylabel("ARCA registration error (px)")
ax2.set_title("ARCA error distribution — tail grows with the tear")
ax2.set_ylim(0, None)
ax2.grid(alpha=0.3)
ax2.legend()

fig.tight_layout()
out = RESULTS / "arca_vs_paste2_tear.png"
fig.savefig(out, dpi=130)
print(f"wrote {out}")

# console summary
print("\nseverity |  PASTE2 med |   ARCA med | ARCA mean | ARCA p90")
for i, sv in enumerate(arca["severity"]):
    print(f"   {sv:>4} | {paste2['reg_err_median'][i]:9.1f}px | "
          f"{arca['reg_err_median'][i]:7.1f}px | "
          f"{arca['reg_err_mean'][i]:6.1f}px | {arca['reg_err_p90'][i]:6.1f}px")
p0, p8 = paste2["reg_err_median"][0], paste2["reg_err_median"][-1]
a0, a8 = arca["reg_err_median"][0], arca["reg_err_median"][-1]
print(f"\nPASTE2 tear median: {p0:.0f} -> {p8:.0f} px  (+{p8-p0:.0f}, +{100*(p8-p0)/p0:.0f}%)")
print(f"ARCA   tear median: {a0:.0f} -> {a8:.0f} px  (+{a8-a0:.0f}, +{100*(a8-a0)/a0:.0f}%)")
print(f"ARCA median lower by {p8/a8:.1f}x at sev8, {p0/a0:.1f}x at sev0.")
