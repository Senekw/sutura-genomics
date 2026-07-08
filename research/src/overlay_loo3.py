"""3-donor leave-one-out summary figure.

One panel per held-out donor (leave-out S1 / S2 / S3). Each panel overlays, vs
tear severity, the registration-error median (px):
  - Sutura in-sample (the fold's training pairs, held-out warp seeds) — green
  - Sutura held-out, global feature standardization      — blue
  - Sutura held-out, perslice (batch-corrected) features — purple
  - PASTE2 (unsupervised) on the same held-out pair    — crimson

Verdict the figure encodes: multi-donor training keeps Sutura sub-pitch IN-SAMPLE
but does NOT transfer — held-out medians sit ~8-11 spot pitches out under both
feature modes, above PASTE2 on every unseen donor. perslice helps marginally.
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parent.parent / "results"
PITCH = 137.0

FOLDS = [  # (held-out tag, pretty name, PASTE2 baseline csv for that held-out pair)
    ("S1", "subj1 (151507/08)", "sweep_deformation_cross_tear.csv"),
    ("S2", "subj2 (151669/70)", "sweep_deformation_cross_tear_loo.csv"),
    ("S3", "subj3 (151673/74)", "sweep_deformation_cross_tear_subj3.csv"),
]


def load(name):
    p = RESULTS / name
    if not p.exists():
        return None
    rows = list(csv.DictReader(open(p)))
    return ([float(r["severity"]) for r in rows],
            [float(r["reg_err_median"]) for r in rows])


fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
for ax, (tag, pretty, pfile) in zip(axes, FOLDS):
    tr = load(f"arca_loo3_global_test{tag}_train_curve.csv")     # in-sample
    g = load(f"arca_loo3_global_test{tag}_test_curve.csv")
    ps = load(f"arca_loo3_perslice_test{tag}_test_curve.csv")
    p2 = load(pfile)
    if tr: ax.plot(*tr, "o-", color="tab:green", lw=2, ms=6,
                   label="Sutura in-sample (train donors)")
    if g: ax.plot(*g, "o-", color="tab:blue", lw=2, ms=6,
                  label="Sutura held-out (global)")
    if ps: ax.plot(*ps, "s-", color="tab:purple", lw=2, ms=6,
                   label="Sutura held-out (perslice)")
    if p2: ax.plot(*p2, "D-", color="crimson", lw=2, ms=6,
                   label="PASTE2 (held-out)")
    ax.axhline(PITCH, color="gray", ls=":", lw=1, label=f"1 spot pitch ({PITCH:.0f}px)")
    ax.set_title(f"Held out: {pretty}")
    ax.set_xlabel("tear severity (spot-pitches)")
    ax.grid(alpha=0.3)
axes[0].set_ylabel("registration error — median (px)")
axes[0].legend(fontsize=8, loc="center right")
fig.suptitle("3-donor leave-one-out: Sutura does not transfer to unseen donors "
             "(in-sample sub-pitch; held-out ~8-11 pitches, above PASTE2)",
             fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.96])
out = RESULTS / "arca_loo3_summary.png"
fig.savefig(out, dpi=130)
print(f"wrote {out}")

# console summary table
print("\nheld-out | Sutura in-sample | Sutura global | Sutura perslice | PASTE2   (median sev0->8, px)")
for tag, pretty, pfile in FOLDS:
    def s(name):
        c = load(name)
        return f"{c[1][0]:4.0f}->{c[1][-1]:4.0f}" if c else "   -    "
    print(f"  {tag}    | {s(f'arca_loo3_global_test{tag}_train_curve.csv')}     "
          f"| {s(f'arca_loo3_global_test{tag}_test_curve.csv')}  "
          f"| {s(f'arca_loo3_perslice_test{tag}_test_curve.csv')}   "
          f"| {s(pfile)}")
