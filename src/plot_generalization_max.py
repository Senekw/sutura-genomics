"""Plot generalization-max results: (left) LODO mean held-out error by intervention
vs PASTE2; (right) held-out error vs training-data diversity for Br8100 with a
crude linear extrapolation to the PASTE2 level. Reads results/generalization_max.csv.
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
rows = list(csv.DictReader(open(RESULTS / "generalization_max.csv")))
for r in rows:
    r["held_out_error"] = float(r["held_out_error"])
    r["in_dist_error"] = float(r["in_dist_error"])
    r["paste2_error"] = float(r["paste2_error"])

PASTE2_MEAN = float(np.mean([r["paste2_error"] for r in rows])) if rows else 3.7

# per-config LODO mean held-out (and how many folds)
cfgs = []
for name in dict.fromkeys(r["config"] for r in rows):
    rs = [r for r in rows if r["config"] == name]
    cfgs.append(dict(name=name, ho=float(np.mean([r["held_out_error"] for r in rs])),
                     idist=float(np.mean([r["in_dist_error"] for r in rs])),
                     nfold=len(rs)))
cfgs.sort(key=lambda c: c["ho"])

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.2))

# left: ranked interventions
names = [c["name"] + ("" if c["nfold"] == 3 else f" ({c['nfold']}f)") for c in cfgs]
y = np.arange(len(cfgs))
ax1.barh(y, [c["ho"] for c in cfgs], color="tab:blue", label="held-out (LODO)")
ax1.barh(y, [c["idist"] for c in cfgs], color="tab:cyan", alpha=0.5, height=0.4,
         label="in-distribution")
ax1.axvline(PASTE2_MEAN, color="crimson", ls="--", lw=2, label=f"PASTE2 (~{PASTE2_MEAN:.1f})")
ax1.set_yticks(y); ax1.set_yticklabels(names, fontsize=9)
ax1.invert_yaxis()
ax1.set_xlabel("median registration error (spot-pitches)")
ax1.set_title("Held-out error by intervention (ranked)")
ax1.legend(fontsize=8); ax1.grid(axis="x", alpha=0.3)
for c, yy in zip(cfgs, y):
    ax1.annotate(f"{c['ho']:.1f}", (c["ho"], yy), xytext=(3, 0),
                 textcoords="offset points", va="center", fontsize=8)

# right: diversity trend for Br8100
def ho_b8100(cfg):
    rs = [r for r in rows if r["config"] == cfg and r["held_out_donor"] == "Br8100"]
    return float(np.mean([r["held_out_error"] for r in rs])) if rs else None
pts = []  # (training-pairs, error, label)
for cfg, npairs, lab in [("baseline_1donor", 1, "1 donor\n1 pair"),
                         ("baseline_2donor", 2, "2 donors\n1 pair each"),
                         ("diversity_2donor_2pair", 4, "2 donors\n2 pairs each")]:
    e = ho_b8100(cfg)
    if e is not None:
        pts.append((npairs, e, lab))
if len(pts) >= 2:
    xs = [p[0] for p in pts]; es = [p[1] for p in pts]
    ax2.plot(xs, es, "o-", color="tab:blue", lw=2, ms=8, label="Sutura held-out (Br8100)")
    for x, e, lab in pts:
        ax2.annotate(lab, (x, e), textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax2.axhline(PASTE2_MEAN, color="crimson", ls="--", lw=2, label=f"PASTE2 (~{PASTE2_MEAN:.1f})")
    # crude linear extrapolation in #pairs
    m, b = np.polyfit(xs, es, 1)
    if m < 0:
        need = (PASTE2_MEAN - b) / m
        ax2.annotate(f"linear extrapolation reaches PASTE2\nat ~{need:.0f} training pairs "
                     f"(~{need/2:.0f} donors)", (xs[-1], es[-1]),
                     textcoords="offset points", xytext=(10, -40), fontsize=8, color="gray")
ax2.set_xlabel("training adjacent pairs")
ax2.set_ylabel("held-out median error (spot-pitches)")
ax2.set_title("Does more donor diversity shrink held-out error?")
ax2.set_ylim(0, None); ax2.grid(alpha=0.3); ax2.legend(fontsize=8)

fig.tight_layout()
out = RESULTS / "generalization_max.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")

print(f"\n{'config':28s} {'in-dist':>8s} {'held-out':>9s} {'PASTE2':>7s} {'folds':>5s}")
for c in cfgs:
    print(f"{c['name']:28s} {c['idist']:8.2f} {c['ho']:9.2f} {PASTE2_MEAN:7.2f} {c['nfold']:5d}")
best = cfgs[0]
print(f"\nBest held-out: {best['name']} = {best['ho']:.2f} pitch  (PASTE2 ~{PASTE2_MEAN:.2f})")
print(f"Gap to PASTE2: {best['ho'] - PASTE2_MEAN:+.2f} pitch")
