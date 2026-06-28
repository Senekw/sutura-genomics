"""
Generate paper figures from existing result CSVs (300 DPI, publication style).
Reads from both repos (arca/results + sutura research/results), writes PNGs to
the sutura clone's research/figures/.
"""
import csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ARCA = Path("/c/Users/karti/arca/results".replace("/c/", "C:/"))
SUT_ROOT = Path("C:/Users/karti/AppData/Local/Temp/claude/"
                "C--Users-karti-arca/91577578-4279-4c48-9e32-6229c6e84288/"
                "scratchpad/sutura/research")
SUTR = SUT_ROOT / "results"
FIGDIR = SUT_ROOT / "figures"
FIGDIR.mkdir(parents=True, exist_ok=True)

# Okabe-Ito colour-blind-safe palette
C = {"sutura": "#0072B2", "paste2": "#009E73", "paste2_smooth": "#D55E00",
     "stalign": "#56B4E9", "gpsa": "#E69F00"}
PITCH = 137.0


def read(path, ycol, xcol="severity"):
    xs, ys = [], []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            xs.append(float(r[xcol])); ys.append(float(r[ycol]))
    return np.array(xs), np.array(ys)


def paste2_5seed_ci():
    """Mean +/- 95% CI of PASTE2 median over 5 in-sample tear seeds (sev 0,4,8)."""
    seeds = [0, 9999, 10000, 10001, 10002]
    by_sev = {}
    for s in seeds:
        x, y = read(SUTR / f"sweep_deformation_ms_tear_seed{s}.csv", "reg_err_median")
        for xi, yi in zip(x, y):
            by_sev.setdefault(xi, []).append(yi)
    sev = sorted(by_sev)
    mean = np.array([np.mean(by_sev[s]) for s in sev])
    ci = np.array([1.96 * np.std(by_sev[s]) / np.sqrt(len(by_sev[s])) for s in sev])
    return np.array(sev), mean, ci


def style(ax):
    ax.set_facecolor("white")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.grid(axis="y", color="0.85", lw=0.8)
    ax.set_axisbelow(True)


def pitch_line(ax):
    ax.axhline(PITCH, ls="--", lw=1.0, color="0.45", zorder=1)
    ax.text(0.02, PITCH + 25, "1 spot pitch (137 px)", color="0.4",
            fontsize=8, transform=ax.get_yaxis_transform())


# ---------------------------------------------------------------- Figure 1
def fig1(path, add_smooth=False):
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    style(ax)
    # Sutura in-sample (5-seed)
    sx, sy = read(SUTR / "sutura_multiseed_tear.csv", "median_mean")
    _, sci = read(SUTR / "sutura_multiseed_tear.csv", "median_ci")
    ax.errorbar(sx, sy, yerr=sci, color=C["sutura"], marker="o", ms=4, lw=2,
                capsize=2, label="Sutura (in-sample, 5-seed)", zorder=5)
    # PASTE2 (full-res line + 5-seed CI at 0/4/8)
    px, py = read(ARCA / "sweep_deformation_cross_tear.csv", "reg_err_median")
    ax.plot(px, py, color=C["paste2"], marker="s", ms=4, lw=2, label="PASTE2 (OT)")
    cx, cm, cci = paste2_5seed_ci()
    ax.errorbar(cx, cm, yerr=cci, color=C["paste2"], fmt="none", capsize=3, lw=1.5)
    # STalign (sev 0,4,8)
    tx, ty = read(SUTR / "stalign_tear.csv", "reg_err_median")
    ax.plot(tx, ty, color=C["stalign"], marker="^", ms=5, lw=2, label="STalign (LDDMM)")
    # GPSA
    gx, gy = read(ARCA / "gpsa_tear.csv", "reg_err_median")
    ax.plot(gx, gy, color=C["gpsa"], marker="D", ms=4, lw=2, label="GPSA (GP warp)")
    if add_smooth:
        mx, my = read(ARCA / "sweep_deformation_cross.csv", "reg_err_median")
        ax.plot(mx, my, color=C["paste2_smooth"], marker="s", ms=4, lw=2, ls=":",
                label="PASTE2 (smooth control)")
    pitch_line(ax)
    ax.set_xlabel("Tear Severity (spot pitches)")
    ax.set_ylabel("Median Registration Error (px)")
    ttl = ("Registration error vs tear severity"
           if not add_smooth else
           "Tear vs smooth (magnitude control)")
    ax.set_title(ttl, fontsize=11)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout(); fig.savefig(path, dpi=300); plt.close(fig)
    print("wrote", path)


# ---------------------------------------------------------------- Figure 2
def fig2(path):
    folds = [("S1", "sweep_deformation_cross_tear.csv", "arca_ctr_attn_l2p0_testS1",
              None),
             ("S2", "sweep_deformation_cross_tear_loo.csv", "arca_ctr_attn_l2p0_testS2",
              {0: (528, 7), 4: (580, 12), 8: (697, 18)}),
             ("S3", "sweep_deformation_cross_tear_subj3.csv", "arca_ctr_attn_l0p5_testS3",
              {0: (397, 7), 4: (465, 8), 8: (539, 19)})]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.3), sharey=True)
    for ax, (fold, p2file, best, p2ci) in zip(axes, folds):
        style(ax)
        bx, by = read(ARCA / f"arca_ctr_cosine_l0_test{fold}_test_curve.csv", "reg_err_median")
        ax.plot(bx, by, color=C["sutura"], marker="o", ms=4, lw=2, ls="--",
                label="Sutura, no contrastive")
        ex, ey = read(ARCA / f"{best}_test_curve.csv", "reg_err_median")
        ax.plot(ex, ey, color=C["sutura"], marker="o", ms=4, lw=2,
                label="Sutura, best contrastive")
        px, py = read(ARCA / p2file, "reg_err_median")
        ax.plot(px, py, color=C["paste2"], marker="s", ms=4, lw=2, label="PASTE2 (held-out)")
        if p2ci:
            xs = sorted(p2ci); ms = [p2ci[s][0] for s in xs]; es = [p2ci[s][1] for s in xs]
            ax.errorbar(xs, ms, yerr=es, color=C["paste2"], fmt="none", capsize=3, lw=1.5)
        pitch_line(ax)
        ax.set_title(f"Held-out donor {fold}", fontsize=11)
        ax.set_xlabel("Tear Severity (spot pitches)")
        ax.set_ylim(bottom=0)
        if fold == "S1":
            ax.set_ylabel("Median Registration Error (px)")
            ax.legend(frameon=False, fontsize=8.5, loc="center right")
    fig.suptitle("Leave-one-donor-out generalization (contrastive single-seed; "
                 "PASTE2 5-seed CI on S2/S3)", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=300); plt.close(fig)
    print("wrote", path)


fig1(FIGDIR / "fig1_benchmark.png")
fig2(FIGDIR / "fig2_lodo.png")
fig1(FIGDIR / "fig3_magnitude_control.png", add_smooth=True)
print("ALL FIGURES DONE ->", FIGDIR)
