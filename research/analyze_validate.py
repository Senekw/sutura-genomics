"""Aggregate research/results/hybrid_validate.csv into the validation tables + plot.
Safe to run any time (reads whatever rows exist so far). GT-free / read-only.

Produces:
  research/results/hybrid_validate_summary.txt   per-dataset/per-severity + LODO variance
  research/results/hybrid_validate.png           gated vs PASTE2 per dataset, and crossover
"""
import csv
from collections import defaultdict
from pathlib import Path
import numpy as np

OUT = Path(r"C:\Users\karti\arca\research\results")
CSV = OUT / "hybrid_validate.csv"
DLPFC = ["Br8100", "Br5292", "Br5595"]
OODS = ["breast", "mousebrain"]
KEY_CFGS = ["paste2", "gated_rigid", "gated_affine", "gated_quad",
            "selfsup_clean", "selfsup_leak", "combo_gated_selfsup"]


def read():
    if not CSV.exists():
        return []
    with open(CSV, newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("status") == "ok"]


def agg(rows):
    # (dataset, config, severity) -> list of err across seeds
    d = defaultdict(list)
    for r in rows:
        try:
            d[(r["dataset"], r["config"], float(r["severity"]))].append(float(r["err_pitch"]))
        except (ValueError, KeyError):
            pass
    return d


def mean_over_sev_seed(d, dataset, config, sevs):
    """Mean over severities of (mean over seeds), and the per-seed LODO-style spread."""
    per_sev_means = []
    for s in sevs:
        v = d.get((dataset, config, s))
        if v:
            per_sev_means.append(np.mean(v))
    return float(np.mean(per_sev_means)) if per_sev_means else None


def main():
    rows = read()
    if not rows:
        print("no rows yet")
        return
    d = agg(rows)
    sev_by_ds = {}
    for (ds, cfg, s) in d:
        sev_by_ds.setdefault(ds, set()).add(s)
    lines = []

    def out(x=""):
        lines.append(x)
        print(x)

    out("=" * 78)
    out("HYBRID VALIDATION SUMMARY (mean over seeds; err in spot-pitches, lower=better)")
    out("=" * 78)

    # per-dataset per-severity table for the key configs
    for ds in DLPFC + OODS:
        sevs = sorted(sev_by_ds.get(ds, []))
        if not sevs:
            continue
        seeds = sorted({int(r["seed"]) for r in rows if r["dataset"] == ds})
        out(f"\n### {ds}  (severities {[int(s) for s in sevs]}, seeds {seeds})")
        header = "config".ljust(20) + "".join(f"s{int(s):<6}" for s in sevs) + "  MEAN"
        out(header)
        for cfg in KEY_CFGS:
            cells = []
            present = False
            for s in sevs:
                v = d.get((ds, cfg, s))
                if v:
                    present = True
                    cells.append(f"{np.mean(v):<7.2f}")
                else:
                    cells.append(f"{'-':<7}")
            if present:
                m = mean_over_sev_seed(d, ds, cfg, sevs)
                out(cfg.ljust(20) + "".join(cells) + f"  {m:.2f}" if m else cfg.ljust(20) + "".join(cells))

    # DLPFC LODO-mean: gated vs paste2, per seed, with variance
    out("\n" + "=" * 78)
    out("DLPFC LODO-mean (mean over 3 donors of the sev-averaged error), per seed")
    out("=" * 78)
    seeds = sorted({int(r["seed"]) for r in rows if r["dataset"] in DLPFC})
    for cfg in ["paste2", "gated_rigid", "gated_affine", "gated_quad"]:
        per_seed = []
        for seed in seeds:
            fold_means = []
            for ds in DLPFC:
                sevs = sorted(sev_by_ds.get(ds, []))
                errs = []
                for s in sevs:
                    v = [float(r["err_pitch"]) for r in rows
                         if r["dataset"] == ds and r["config"] == cfg
                         and float(r["severity"]) == s and int(r["seed"]) == seed]
                    if v:
                        errs.append(np.mean(v))
                if errs:
                    fold_means.append(np.mean(errs))
            if len(fold_means) == len(DLPFC):
                per_seed.append(np.mean(fold_means))
        if per_seed:
            out(f"  {cfg:16s} seeds={[round(x,3) for x in per_seed]}  "
                f"mean={np.mean(per_seed):.3f}  std={np.std(per_seed):.3f}")

    # where gated beats / loses PASTE2 (per dataset x severity, mean over seeds)
    out("\n" + "=" * 78)
    out("Gated_rigid vs PASTE2 per (dataset x severity): + = gated wins, - = loses")
    out("=" * 78)
    for ds in DLPFC + OODS:
        sevs = sorted(sev_by_ds.get(ds, []))
        marks = []
        for s in sevs:
            p = d.get((ds, "paste2", s))
            g = d.get((ds, "gated_rigid", s))
            if p and g:
                delta = np.mean(g) - np.mean(p)
                marks.append(f"s{int(s)}:{'+' if delta < 0 else '-'}{abs(delta):.2f}")
        if marks:
            out(f"  {ds:12s} " + "  ".join(marks))

    (OUT / "hybrid_validate_summary.txt").write_text("\n".join(lines), encoding="ascii", errors="replace")
    print(f"\nwrote {OUT/'hybrid_validate_summary.txt'}")

    # plot
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"plot skipped: {e!r}")
        return
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(15, 6))
    # left: per-dataset gated vs paste2 (sev-averaged, mean over seeds)
    datasets = [ds for ds in DLPFC + OODS if sev_by_ds.get(ds)]
    x = np.arange(len(datasets))
    for i, cfg in enumerate(["paste2", "gated_rigid", "gated_affine", "gated_quad"]):
        vals = [mean_over_sev_seed(d, ds, cfg, sorted(sev_by_ds[ds])) for ds in datasets]
        vals = [v if v is not None else np.nan for v in vals]
        axL.bar(x + (i - 1.5) * 0.2, vals, 0.2, label=cfg)
    axL.set_xticks(x); axL.set_xticklabels(datasets, rotation=20)
    axL.set_ylabel("sev-averaged median error (pitch)"); axL.legend(frameon=False, fontsize=8)
    axL.set_title("Gated variants vs PASTE2 per dataset"); axL.grid(axis="y", alpha=0.3)
    # right: crossover on the DLPFC-mean (error vs severity)
    all_sev = sorted({s for ds in DLPFC for s in sev_by_ds.get(ds, [])})
    for cfg, c in [("paste2", "#d1495b"), ("gated_rigid", "#3a0ca3"),
                   ("gated_affine", "#2a9d8f"), ("gated_quad", "#e9c46a")]:
        ys = []
        for s in all_sev:
            vv = [np.mean(d[(ds, cfg, s)]) for ds in DLPFC if d.get((ds, cfg, s))]
            ys.append(np.mean(vv) if vv else np.nan)
        axR.plot(all_sev, ys, "o-", color=c, label=cfg)
    axR.set_xlabel("tear severity"); axR.set_ylabel("DLPFC-mean median error (pitch)")
    axR.set_title("Crossover vs severity (DLPFC mean)"); axR.legend(frameon=False, fontsize=8)
    axR.grid(alpha=0.3)
    fig.suptitle("Hybrid validation - gated piecewise vs PASTE2 across datasets & severity")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(OUT / "hybrid_validate.png", dpi=130)
    plt.close(fig)
    print(f"wrote {OUT/'hybrid_validate.png'}")


if __name__ == "__main__":
    main()
