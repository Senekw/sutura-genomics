"""Overlay the Sutura leave-one-out generalization curves.

Two questions caveat #2 raised, one panel each:

  LEFT  — generalization gap. Sutura median on the TRAINING pair (151507/151508,
          held-out warp seeds = in-sample) vs the HELD-OUT pair (151669/151670,
          unseen donor). If the held-out curve tracks the in-sample one, Sutura
          generalizes across tissue rather than memorizing one deformation field.

  RIGHT — does Sutura still beat PASTE2 on tissue it never trained on? Sutura held-out
          median vs PASTE2 run on the SAME held-out pair / same warps / same GT
          (sweep_deformation --reference 151669 --sample 151670 --tear). PASTE2 is
          unsupervised, so it has no train/test distinction — this is its honest
          number on subj2.

All curves: severities 0,1,2,3,4,6,8, tear regime, eval-seed 0, registration
error median (px) vs the array-bridge GT in each pair's own pixel frame.
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parent.parent / "results"
PITCH = 137.0


def load(name, cols):
    with open(RESULTS / name) as fh:
        rows = list(csv.DictReader(fh))
    return {c: [float(r[c]) for r in rows] for c in cols}


test = load("arca_loo_test_curve.csv",
            ["severity", "reg_err_median", "reg_err_mean", "reg_err_p90"])
train = load("arca_loo_train_curve.csv", ["severity", "reg_err_median"])

# PASTE2 on the held-out pair — optional until the sweep finishes.
paste2_loo_path = RESULTS / "sweep_deformation_cross_tear_loo.csv"
paste2 = (load("sweep_deformation_cross_tear_loo.csv",
               ["severity", "reg_err_median"])
          if paste2_loo_path.exists() else None)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

# --- left: generalization gap (in-sample vs held-out, Sutura) ---
ax1.plot(train["severity"], train["reg_err_median"], "o-", color="tab:green",
         lw=2, ms=7, label="Sutura in-sample (subj1, train tissue)")
ax1.plot(test["severity"], test["reg_err_median"], "o-", color="tab:blue",
         lw=2, ms=7, label="Sutura held-out (subj2, unseen donor)")
ax1.axhline(PITCH, color="gray", ls=":", lw=1, label=f"1 spot pitch ({PITCH:.0f} px)")
ax1.set_xlabel("tear severity (spot-pitches)")
ax1.set_ylabel("registration error — median (px)")
ax1.set_title("Generalization gap: train tissue vs held-out donor")
ax1.set_ylim(0, None)
ax1.grid(alpha=0.3)
ax1.legend()
for x, y in zip(test["severity"], test["reg_err_median"]):
    ax1.annotate(f"{y:.0f}", (x, y), textcoords="offset points",
                 xytext=(0, 8), ha="center", fontsize=8, color="tab:blue")

# --- right: head-to-head on the held-out pair ---
if paste2 is not None:
    ax2.plot(paste2["severity"], paste2["reg_err_median"], "s-", color="crimson",
             lw=2, ms=7, label="PASTE2 (GW/OT) — held-out subj2")
ax2.plot(test["severity"], test["reg_err_median"], "o-", color="tab:blue",
         lw=2, ms=7, label="Sutura (GNN) — held-out subj2")
ax2.axhline(PITCH, color="gray", ls=":", lw=1, label=f"1 spot pitch ({PITCH:.0f} px)")
ax2.set_xlabel("tear severity (spot-pitches)")
ax2.set_ylabel("registration error — median (px)")
ax2.set_title("Head-to-head on UNSEEN tissue (same warps, same GT)")
ax2.set_ylim(0, None)
ax2.grid(alpha=0.3)
ax2.legend()

fig.tight_layout()
out = RESULTS / "arca_loo_generalization.png"
fig.savefig(out, dpi=130)
print(f"wrote {out}")

# --- console summary ---
print("\nseverity | Sutura in-sample | Sutura held-out | "
      + ("PASTE2 held-out" if paste2 else "(PASTE2 pending)"))
for i, sv in enumerate(test["severity"]):
    p = f"{paste2['reg_err_median'][i]:9.1f}px" if paste2 else "     --   "
    print(f"   {sv:>4} | {train['reg_err_median'][i]:11.1f}px | "
          f"{test['reg_err_median'][i]:10.1f}px | {p}")

ti0, ti8 = train["reg_err_median"][0], train["reg_err_median"][-1]
te0, te8 = test["reg_err_median"][0], test["reg_err_median"][-1]
print(f"\nSutura in-sample : {ti0:.0f} -> {ti8:.0f} px  (+{ti8-ti0:.0f})")
print(f"Sutura held-out  : {te0:.0f} -> {te8:.0f} px  (+{te8-te0:.0f})")
gap = (sum(test['reg_err_median']) - sum(train['reg_err_median'])) / len(test['severity'])
print(f"mean held-out minus in-sample median gap: {gap:+.1f} px "
      f"(the cross-tissue generalization cost)")
if paste2:
    pe8 = paste2["reg_err_median"][-1]
    print(f"At sev8 on UNSEEN tissue: Sutura {te8:.0f}px vs PASTE2 {pe8:.0f}px "
          f"-> Sutura {pe8/te8:.1f}x lower.")
