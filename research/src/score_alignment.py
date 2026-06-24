"""
Score a saved PASTE2 transport matrix by layer-label transfer, WITHOUT
re-running the (expensive) alignment.

Loads results/paste2_transport_<tag>.npy and the companion
results/paste2_transport_<tag>_meta.npz (which carries the layer labels), then
reports both the PASTE2 accuracy and the random-mapping floor, masking NA-labeled
spots on both slices.

Usage:
    python src/score_alignment.py                       # default 151507->151508
    python src/score_alignment.py --tag 151509_to_151510
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from scoring import print_report, report

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="151507_to_151508")
    p.add_argument("--random-trials", type=int, default=50)
    args = p.parse_args()

    npy = RESULTS_DIR / f"paste2_transport_{args.tag}.npy"
    meta = RESULTS_DIR / f"paste2_transport_{args.tag}_meta.npz"
    if not npy.exists() or not meta.exists():
        raise FileNotFoundError(f"Missing {npy} or {meta} — run baseline first.")

    pi = np.load(npy)
    m = np.load(meta, allow_pickle=True)
    layer_a, layer_b = m["layer_a"], m["layer_b"]
    s = m["s"] if "s" in m else "?"
    print(f"scoring {args.tag}: pi={pi.shape}, "
          f"A labels={len(layer_a)}, B labels={len(layer_b)}, s={s}\n")

    rep = report(pi, layer_a, layer_b, random_trials=args.random_trials)
    print_report(rep, header=f"BASELINE — PASTE2 layer transfer ({args.tag})")

    out = RESULTS_DIR / f"paste2_baseline_{args.tag}_scored.txt"
    mo, fl = rep["model"], rep["random_floor"]
    out.write_text(
        f"tag={args.tag} s={s}\n"
        f"paste2_accuracy={mo['accuracy']:.4f} "
        f"({mo['n_correct']}/{mo['n_scored']})\n"
        f"random_floor={fl['accuracy_mean']:.4f} +/- {fl['accuracy_std']:.4f} "
        f"({fl['n_trials']} trials)\n"
        f"masked_a_na={mo['n_dropped_a_na']} "
        f"masked_partner_na={mo['n_dropped_partner_na']}\n"
    )
    print(f"\nwrote -> {out}")


if __name__ == "__main__":
    main()
