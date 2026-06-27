"""Aggregate the held-out multi-seed runs (folds S2, S3) into an error-bar table.

Reads:
  results/sweep_deformation_ms_tear_S{2,3}_seed{0,9999,10000,10001,10002}.csv  (PASTE2)
  results/stalign_tear_S{2,3}.csv                                              (STalign, seed 0)
  results/sutura_multiseed_lodo.csv                                            (Sutura, pre-aggregated)
Writes:
  results/ms_lodo_summary.txt    (the head-to-head with 5-seed 95% CIs)
"""
import csv, numpy as np
from pathlib import Path

R = Path(__file__).resolve().parents[1] / "results"
SEEDS = [0, 9999, 10000, 10001, 10002]
SEV = [0.0, 4.0, 8.0]
FOLDS = {"S2": "151669/151670", "S3": "151673/151674"}


def rd(f):
    return {float(r["severity"]): r for r in csv.DictReader(open(R / f))}


def ci95(x):
    x = np.asarray(x, float)
    return 1.96 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0


def paste2_ms(fold):
    """5-seed mean+/-CI for PASTE2 bary & argmax median per severity."""
    tabs = [rd(f"sweep_deformation_ms_tear_{fold}_seed{s}.csv") for s in SEEDS]
    out = {}
    for sv in SEV:
        bary = [float(t[sv]["reg_err_median"]) for t in tabs]
        arg = [float(t[sv]["reg_err_median_argmax"]) for t in tabs]
        acc = [float(t[sv]["paste2_acc"]) for t in tabs]
        out[sv] = dict(bary=(np.mean(bary), ci95(bary)),
                       argmax=(np.mean(arg), ci95(arg)),
                       acc=(np.mean(acc) * 100, ci95(acc) * 100))
    return out


def sutura_ms():
    rows = list(csv.DictReader(open(R / "sutura_multiseed_lodo.csv")))
    out = {}  # (fold, mode, sev) -> (mean, ci)
    for r in rows:
        out[(r["fold"], r["mode"], float(r["severity"]))] = (
            float(r["median_mean"]), float(r["median_ci"]))
    return out


def main():
    lines = []
    def p(s=""):
        print(s); lines.append(s)

    sut = sutura_ms()
    p("=" * 92)
    p("HELD-OUT MULTI-SEED ERROR BARS — folds S2 & S3 (tear regime, 5 seeds: 0,9999,10000,10001,10002)")
    p("registration error median px, mean +/- 95% CI across seeds")
    p("=" * 92)
    for fold, pair in FOLDS.items():
        pp = paste2_ms(fold)
        p(f"\n### Fold {fold}  (held-out donor {pair}) ###")
        p(f"{'sev':>4} | {'Sutura global':>18} | {'Sutura perslice':>18} | "
          f"{'PASTE2 bary':>16} | {'PASTE2 argmax':>16} | {'STalign(s0)':>11}")
        p("-" * 92)
        stal = rd(f"stalign_tear_{fold}.csv")
        for sv in SEV:
            sg = sut.get((fold, "global", sv))
            sp = sut.get((fold, "perslice", sv))
            sg_s = f"{sg[0]:6.0f} +/- {sg[1]:4.0f}" if sg else "      n/a"
            sp_s = f"{sp[0]:6.0f} +/- {sp[1]:4.0f}" if sp else "      n/a"
            b = pp[sv]["bary"]; a = pp[sv]["argmax"]
            st = float(stal[sv]["reg_err_median"]) if sv in stal else float("nan")
            p(f"{sv:>4.0f} | {sg_s:>18} | {sp_s:>18} | "
              f"{b[0]:6.0f} +/- {b[1]:4.0f} | {a[0]:6.0f} +/- {a[1]:4.0f} | {st:>11.0f}")
        # degradation summary (sev0 -> sev8)
        bg0, bg8 = sut.get((fold, "global", 0.0)), sut.get((fold, "global", 8.0))
        if bg0 and bg8:
            p(f"   Sutura-global degradation sev0->8: {bg0[0]:.0f} -> {bg8[0]:.0f} px "
              f"({bg8[0]-bg0[0]:+.0f})")
        p(f"   PASTE2-bary  degradation sev0->8: {pp[0.0]['bary'][0]:.0f} -> {pp[8.0]['bary'][0]:.0f} px "
          f"({pp[8.0]['bary'][0]-pp[0.0]['bary'][0]:+.0f})")
        p(f"   STalign      degradation sev0->8: {float(stal[0.0]['reg_err_median']):.0f} -> "
          f"{float(stal[8.0]['reg_err_median']):.0f} px")

    p("\n(In-sample S1 reference for scale: Sutura 99->118, PASTE2 bary 659->838, STalign 79->866.)")
    out = R / "ms_lodo_summary.txt"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
