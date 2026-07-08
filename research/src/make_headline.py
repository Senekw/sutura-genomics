"""Combine the completed sweep CSVs into one headline figure for Sutura.

Left  : registration error (barycentric median, px) vs warp severity for the
        three alpha=0.1 regimes (smooth / tear / self), plus tear at alpha=0.5.
Right : layer-label transfer accuracy vs severity for the same.
This is the axes Sutura's curve will later overlay onto.
"""
from __future__ import annotations
import csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parent.parent / "results"
PITCH = 137.0


def load(name):
    with open(RESULTS / name) as fh:
        rows = list(csv.DictReader(fh))
    f = lambda k: [float(r[k]) for r in rows]
    return {"sev": f("severity"), "reg": f("reg_err_median"),
            "acc": f("paste2_acc"), "floor": f("random_floor")}

cross = load("sweep_deformation_cross.csv")
tear = load("sweep_deformation_cross_tear.csv")
self_ = load("sweep_deformation_self.csv")
tear05 = load("sweep_deformation_tear_a0p5.csv")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

ax1.plot(cross["sev"], cross["reg"], "o-", color="tab:blue",
         label="smooth, α=0.1")
ax1.plot(tear["sev"], tear["reg"], "s-", color="crimson",
         label="tear, α=0.1")
ax1.plot(tear05["sev"], tear05["reg"], "s--", color="darkred",
         label="tear, α=0.5 (sev 0,8)")
ax1.plot(self_["sev"], self_["reg"], "^-", color="tab:green",
         label="self-control, α=0.1")
ax1.axhline(PITCH, color="gray", ls=":", lw=1, label=f"1 spot pitch ({PITCH:.0f}px)")
ax1.set_xlabel("warp severity (spot-pitches)")
ax1.set_ylabel("registration error — median (px)")
ax1.set_title("PASTE2 registration error vs deformation")
ax1.legend(fontsize=8)
ax1.grid(alpha=0.3)

ax2.plot(cross["sev"], cross["acc"], "o-", color="tab:blue", label="smooth, α=0.1")
ax2.plot(tear["sev"], tear["acc"], "s-", color="crimson", label="tear, α=0.1")
ax2.plot(tear05["sev"], tear05["acc"], "s--", color="darkred",
         label="tear, α=0.5 (sev 0,8)")
ax2.plot(self_["sev"], self_["acc"], "^-", color="tab:green",
         label="self-control, α=0.1")
ax2.axhline(cross["floor"][0], color="gray", ls="--", lw=1, label="random floor")
ax2.set_xlabel("warp severity (spot-pitches)")
ax2.set_ylabel("layer-label transfer accuracy")
ax2.set_ylim(0, 1)
ax2.set_title("Label-transfer accuracy vs deformation")
ax2.legend(fontsize=8)
ax2.grid(alpha=0.3)

fig.tight_layout()
out = RESULTS / "headline_summary.png"
fig.savefig(out, dpi=140)
print(f"wrote {out}")
