"""Compare the orchestrator against Sutura-always and PASTE2-always across all
datasets, and plot. Reads results/orchestrator_eval.csv (chosen method + error),
results/shared_basis_eval.csv (shared-basis Sutura), and
results/generalization_sweep.csv (per-SVD Sutura + PASTE2). Writes
results/orchestrator_compare.png and prints the aggregate verdict.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parent.parent / "results"
SEV = 4.0
ORDER = ["Br5292", "Br5595", "Br8100", "mouse", "breast"]
PRIOR = {"Br5292": "DLPFC_Br5292_train", "Br5595": "DLPFC_Br5595",
         "Br8100": "DLPFC_Br8100", "mouse": "MouseBrain_SagPost",
         "breast": "BreastCancer_BlockA"}


def read(name):
    return list(csv.DictReader(open(RESULTS / name)))


orch = {r["dataset"]: r for r in read("orchestrator_eval.csv")}
sb = read("shared_basis_eval.csv")          # sutura_shared (DLPFC only)
gs = read("generalization_sweep.csv")        # per-SVD sutura + paste2


def _mean(rows, pred):
    # like-for-like with the orchestrator's single run: seed 0 only
    v = [float(r["median_error_pitch"]) for r in rows
         if pred(r) and int(r["seed"]) == 0]
    return float(np.mean(v)) if v else None


def sutura_always(name):
    # prefer the shared-basis Sutura (current model); on non-DLPFC panels it is
    # INAPPLICABLE (gene mismatch) so fall back to the per-SVD Sutura, which runs
    # but collapses -> reported with a flag.
    donor = {"Br5292": "Br5292", "Br5595": "Br5595", "Br8100": "Br8100"}.get(name)
    if donor:
        e = _mean(sb, lambda r: r["donor"] == donor and r["method"] == "sutura_shared"
                  and float(r["severity"]) == SEV)
        return e, "shared-basis"
    e = _mean(gs, lambda r: r["dataset"] == PRIOR[name] and r["method"] == "sutura"
              and float(r["severity"]) == SEV)
    return e, "per-SVD (shared-basis N/A: gene mismatch)"


def paste2_always(name):
    return _mean(gs, lambda r: r["dataset"] == PRIOR[name] and r["method"] == "paste2"
                 and float(r["severity"]) == SEV)


sut = {n: sutura_always(n) for n in ORDER}
pas = {n: paste2_always(n) for n in ORDER}
och = {n: float(orch[n]["error"]) for n in ORDER}

print(f"{'dataset':8s} {'Sutura-always':>26s} {'PASTE2-always':>14s} {'Orchestrator':>13s} {'chosen':>8s}")
for n in ORDER:
    s, tag = sut[n]
    print(f"{n:8s} {s:8.2f} [{tag[:15]:15s}] {pas[n]:14.2f} {och[n]:13.2f} "
          f"{orch[n]['chosen_method']:>8s}")
sut_mean = np.mean([sut[n][0] for n in ORDER])
pas_mean = np.mean([pas[n] for n in ORDER])
och_mean = np.mean([och[n] for n in ORDER])
sut_max = max(sut[n][0] for n in ORDER); pas_max = max(pas[n] for n in ORDER)
och_max = max(och[n] for n in ORDER)
print(f"\nMEAN     Sutura-always {sut_mean:.2f} | PASTE2-always {pas_mean:.2f} | "
      f"Orchestrator {och_mean:.2f}")
print(f"WORST    Sutura-always {sut_max:.2f} | PASTE2-always {pas_max:.2f} | "
      f"Orchestrator {och_max:.2f}")
beats = all(och[n] <= min(sut[n][0], pas[n]) + 1e-6 for n in ORDER)
print(f"Orchestrator <= min(Sutura,PASTE2) on every dataset: {beats}")

# --- plot: grouped bars ---
x = np.arange(len(ORDER)); w = 0.27
fig, ax = plt.subplots(figsize=(11, 5))
ax.bar(x - w, [sut[n][0] for n in ORDER], w, label="Sutura-always", color="tab:blue")
ax.bar(x, [pas[n] for n in ORDER], w, label="PASTE2-always", color="crimson")
ax.bar(x + w, [och[n] for n in ORDER], w, label="Orchestrator (routed)",
       color="tab:green")
for i, n in enumerate(ORDER):
    ax.annotate(orch[n]["chosen_method"], (i + w, och[n]), ha="center",
                va="bottom", fontsize=7, color="tab:green")
ax.axhline(1.0, color="gray", ls=":", lw=1)
ax.set_xticks(x); ax.set_xticklabels(
    [f"{n}\n({orch[n]['truth'][:3]})" for n in ORDER])
ax.set_ylabel("median registration error (spot-pitches)")
ax.set_title(f"Orchestrator vs fixed strategies (tear severity {SEV:g})\n"
             f"mean: Sutura-always {sut_mean:.1f} | PASTE2-always {pas_mean:.1f} | "
             f"Orchestrator {och_mean:.1f}")
ax.legend()
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
out = RESULTS / "orchestrator_compare.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"\nwrote {out}")
