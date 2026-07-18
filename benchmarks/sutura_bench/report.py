"""
Reporting: turn a run's per-cell CSV into an honest leaderboard and plots.

The aggregation protocol matches the research findings so numbers are directly
comparable:
  1. per (method, dataset, seed): average median_pitch over severities (the
     "sev-averaged error");
  2. per (method, dataset): mean +/- std of that over seeds;
  3. DLPFC-LODO mean: average the per-donor sev-averaged errors over the three
     first-pair DLPFC donors (Br5292, Br5595, Br8100).

Honesty rules baked in:
  * real_serial and self_warp datasets are NEVER pooled - self_warp is reported
    in a separate, explicitly-caveated section (degenerate; not a valid
    refinement test).
  * every table states which datasets carry array-bridge ground truth and which
    are self-warp, and the seed count behind each +/- std.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import config
from .metrics import SELF_WARP_FLOOR_PITCH

DLPFC_LODO_DONORS = ["Br5292", "Br5595", "Br8100"]


def load(csv_path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df[df["status"] == "ok"].copy()
    for c in ("severity", "seed", "median_pitch", "mean_pitch", "p90_pitch"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def sev_averaged(df: pd.DataFrame) -> pd.DataFrame:
    """Per (method, dataset): sev-averaged median_pitch, mean/std over seeds."""
    per_seed = (df.groupby(["method", "dataset", "regime", "group", "seed"])
                  ["median_pitch"].mean().reset_index())
    agg = (per_seed.groupby(["method", "dataset", "regime", "group"])
                   ["median_pitch"]
                   .agg(mean="mean", std="std", n_seeds="count").reset_index())
    agg["std"] = agg["std"].fillna(0.0)
    return agg.sort_values(["group", "dataset", "mean"])


def dlpfc_lodo(df: pd.DataFrame) -> pd.DataFrame:
    """DLPFC-LODO mean per method: mean over the three first-pair donors of each
    donor's sev-averaged error (mean/std over seeds of that donor-mean)."""
    sub = df[df["dataset"].isin(DLPFC_LODO_DONORS)]
    if sub.empty:
        return pd.DataFrame(columns=["method", "lodo_mean", "lodo_std", "n_seeds"])
    per_seed = (sub.groupby(["method", "seed"])["median_pitch"].mean().reset_index())
    agg = (per_seed.groupby("method")["median_pitch"]
                   .agg(lodo_mean="mean", lodo_std="std", n_seeds="count")
                   .reset_index())
    agg["lodo_std"] = agg["lodo_std"].fillna(0.0)
    return agg.sort_values("lodo_mean")


# --------------------------------------------------------------------------- #
# markdown leaderboard
# --------------------------------------------------------------------------- #
def _fmt(mean: float, std: float, seeds: int) -> str:
    if not np.isfinite(mean):
        return "-"
    return f"{mean:.2f} +/- {std:.2f}" if seeds > 1 else f"{mean:.2f}"


def leaderboard_markdown(csv_path, title: str = "Benchmark leaderboard") -> str:
    df = load(csv_path)
    if df.empty:
        return f"# {title}\n\n_No successful cells in {csv_path}._\n"
    agg = sev_averaged(df)
    lodo = dlpfc_lodo(df)
    lines = [f"# {title}", ""]
    lines.append(f"_Source: `{Path(csv_path).name}` | "
                 f"severity-averaged median registration error (spot-pitches), "
                 f"lower = better. `+/- std` is across seeds._")
    lines.append("")

    # --- DLPFC LODO headline ------------------------------------------------ #
    if not lodo.empty:
        lines += ["## DLPFC leave-one-donor-out (real serial, array-bridge GT)", "",
                  "| method | LODO-mean error (pitch) | seeds |", "|---|---|---|"]
        for _, r in lodo.iterrows():
            lines.append(f"| {r['method']} | {_fmt(r['lodo_mean'], r['lodo_std'], int(r['n_seeds']))} "
                         f"| {int(r['n_seeds'])} |")
        lines.append("")

    # --- per-dataset, real serial ------------------------------------------ #
    real = agg[agg["regime"] == "real_serial"]
    if not real.empty:
        methods = list(dict.fromkeys(real.sort_values("mean")["method"]))
        dsets = list(dict.fromkeys(real["dataset"]))
        lines += ["## Per-dataset (real serial sections, array-bridge GT)", "",
                  "| method | " + " | ".join(dsets) + " |",
                  "|" + "---|" * (len(dsets) + 1)]
        for m in methods:
            cells = []
            for d in dsets:
                row = real[(real["method"] == m) & (real["dataset"] == d)]
                cells.append(_fmt(row["mean"].iloc[0], row["std"].iloc[0],
                                  int(row["n_seeds"].iloc[0])) if not row.empty else "-")
            lines.append(f"| {m} | " + " | ".join(cells) + " |")
        lines.append("")

    # --- self-warp (degenerate) -------------------------------------------- #
    selfw = agg[agg["regime"] == "self_warp"]
    if not selfw.empty:
        lines += ["## Self-warp datasets (DEGENERATE - reported separately)", "",
                  f"> Self-warp aligns a section to a warped copy of itself. The base "
                  f"aligner matches identical expression and is near-exact, so refinement "
                  f"cannot be validated here and an error below ~{SELF_WARP_FLOOR_PITCH:g} "
                  f"pitch reflects the degeneracy, not method skill. **Never compare these "
                  f"to the real-serial numbers above.**", "",
                  "| method | dataset | sev-avg error (pitch) | seeds |",
                  "|---|---|---|---|"]
        for _, r in selfw.iterrows():
            lines.append(f"| {r['method']} | {r['dataset']} | "
                         f"{_fmt(r['mean'], r['std'], int(r['n_seeds']))} | {int(r['n_seeds'])} |")
        lines.append("")

    # --- caveats ------------------------------------------------------------ #
    lines += ["## Caveats", ""]
    n_ds = df["dataset"].nunique()
    lines.append(f"- {n_ds} datasets, {df['seed'].nunique()} seed(s), "
                 f"severities {sorted(df['severity'].unique())}.")
    lines.append("- Ground truth is the Visium array bridge (real serial) or the known "
                 "synthetic warp field (self-warp). All GT is Visium-array-specific.")
    lines.append("- Synthetic tears model tissue damage; real tears may differ. The gate "
                 "is a refinement of a base aligner (PASTE2), not a standalone aligner.")
    return "\n".join(lines) + "\n"


def write_leaderboard(csv_path, out_md: Optional[Path] = None,
                      title: str = "Benchmark leaderboard") -> Path:
    md = leaderboard_markdown(csv_path, title=title)
    out = Path(out_md) if out_md else Path(csv_path).with_name(Path(csv_path).stem + "_leaderboard.md")
    out.write_text(md, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# plots
# --------------------------------------------------------------------------- #
def plot_run(csv_path, out_png: Optional[Path] = None) -> Optional[Path]:
    """Error-vs-severity per method, one subplot per real-serial dataset, plus a
    DLPFC-LODO summary bar. Returns the PNG path (None if matplotlib absent)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    df = load(csv_path)
    real = df[df["regime"] == "real_serial"]
    if real.empty:
        return None
    dsets = sorted(real["dataset"].unique())
    lodo = dlpfc_lodo(df)
    ncols = min(3, len(dsets) + 1)
    nrows = int(np.ceil((len(dsets) + 1) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows), squeeze=False)
    axes = axes.ravel()

    for ax, d in zip(axes, dsets):
        sub = real[real["dataset"] == d]
        for m in sorted(sub["method"].unique()):
            curve = (sub[sub["method"] == m].groupby("severity")["median_pitch"]
                     .mean().reset_index().sort_values("severity"))
            ax.plot(curve["severity"], curve["median_pitch"], marker="o", label=m)
        ax.set_title(d); ax.set_xlabel("tear severity (pitch)")
        ax.set_ylabel("median error (pitch)"); ax.grid(alpha=0.3); ax.legend(fontsize=7)

    # LODO summary bar in the last axis
    ax = axes[len(dsets)]
    if not lodo.empty:
        ax.bar(lodo["method"], lodo["lodo_mean"],
               yerr=lodo["lodo_std"] if (lodo["n_seeds"] > 1).any() else None, capsize=4)
        ax.set_title("DLPFC-LODO mean"); ax.set_ylabel("median error (pitch)")
        ax.tick_params(axis="x", rotation=45)
    for ax in axes[len(dsets) + 1:]:
        ax.axis("off")
    fig.tight_layout()
    out = Path(out_png) if out_png else Path(csv_path).with_name(Path(csv_path).stem + ".png")
    fig.savefig(out, dpi=120); plt.close(fig)
    return out
