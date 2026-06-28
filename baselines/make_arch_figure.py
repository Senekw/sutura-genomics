"""Sutura architecture schematic (publication quality, ~16:9, 300 DPI)."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path

OUT = Path("C:/Users/karti/AppData/Local/Temp/claude/"
           "C--Users-karti-arca/91577578-4279-4c48-9e32-6229c6e84288/"
           "scratchpad/sutura/research/figures/fig_architecture.png")

CIN = "#ededed"      # inputs / kNN  (light gray)
CENC = "#cfe2f3"     # encoder       (light blue)
CATT = "#ffe0a3"     # cross-attn    (orange)
CHEAD = "#fff2cc"    # head boxes    (light yellow)
COUT = "#d9ead3"     # output        (light green)
INK = "#222222"

fig, ax = plt.subplots(figsize=(14.2, 8.0))
ax.set_xlim(0, 18); ax.set_ylim(0, 9); ax.axis("off")
ax.set_facecolor("white"); fig.patch.set_facecolor("white")


def box(cx, cy, w, h, text, fc, fs=10, weight="normal"):
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                 boxstyle="round,pad=0.02,rounding_size=0.12",
                 linewidth=1.1, edgecolor="black", facecolor=fc, zorder=3))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs,
            color=INK, weight=weight, zorder=4)


def arrow(x1, y1, x2, y2, label=None, lx=None, ly=None, fs=9, rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2),
                 arrowstyle="-|>", mutation_scale=14, lw=1.3,
                 color="#444444", zorder=2,
                 connectionstyle=f"arc3,rad={rad}"))
    if label:
        ax.text(lx if lx is not None else (x1 + x2) / 2,
                ly if ly is not None else (y1 + y2) / 2 + 0.22,
                label, ha="center", va="center", fontsize=fs,
                color="#333333", style="italic", zorder=5,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none"))


def point_panel(x0, y0, w, h, title, warp_tear):
    ax.add_patch(FancyBboxPatch((x0, y0), w, h,
                 boxstyle="round,pad=0.02,rounding_size=0.1",
                 linewidth=1.1, edgecolor="black", facecolor=CIN, zorder=3))
    ax.text(x0 + w / 2, y0 + h + 0.22, title, ha="center", va="bottom",
            fontsize=10.5, weight="bold", color=INK)
    rng = np.random.default_rng(3)
    n = 150
    th = rng.uniform(0, 2 * np.pi, n); r = np.sqrt(rng.uniform(0, 1, n))
    px = r * np.cos(th); py = r * np.sin(th) * 0.85
    colors = np.array(["#34495e"] * n)
    if warp_tear:
        px += 0.10 * np.sin(2.2 * py)            # mild smooth warp
        seam = px > 0.15                          # torn block
        px[seam] += 0.42; py[seam] += 0.18        # displace -> visible gap
        colors[seam] = "#c0392b"
    # map to panel with padding
    pad = 0.14
    gx = x0 + pad * w + (px - px.min()) / (px.max() - px.min()) * w * (1 - 2 * pad)
    gy = y0 + pad * h + (py - py.min()) / (py.max() - py.min()) * h * (1 - 2 * pad)
    ax.scatter(gx, gy, s=9, c=colors, zorder=4, linewidths=0)


# ---- Inputs (point clouds) ----
point_panel(0.3, 4.85, 2.3, 2.7, "Reference slice A", warp_tear=False)
point_panel(0.3, 0.95, 2.3, 2.7, "Moving slice B (warped)", warp_tear=True)

# ---- kNN graphs ----
box(4.0, 6.2, 2.0, 1.15, "kNN graph\n(k = 6)", CIN, fs=10)
box(4.0, 2.3, 2.0, 1.15, "kNN graph\n(k = 6)", CIN, fs=10)
arrow(2.6, 6.2, 3.0, 6.2)
arrow(2.6, 2.3, 3.0, 2.3)

# ---- Shared encoder ----
box(6.7, 4.25, 2.5, 4.6,
    "Shared Graph\nEncoder\n\nLinear proj (64)\n$\\downarrow$\n3$\\times$ DeformConv\n(residual)\n\n"
    "$\\langle$ shared weights $\\rangle$", CENC, fs=10, weight="normal")
arrow(5.0, 6.2, 5.45, 5.4)
arrow(5.0, 2.3, 5.45, 3.1)
# shared-weights emphasis: a tie between the two input streams
ax.annotate("", xy=(5.3, 5.4), xytext=(5.3, 3.1),
            arrowprops=dict(arrowstyle="<->", color="#1f6fb2", lw=1.2,
                            connectionstyle="arc3,rad=-0.35"), zorder=6)
ax.text(4.75, 4.25, "same\nweights", ha="center", va="center", fontsize=8,
        color="#1f6fb2", style="italic", weight="bold")

# ---- Cross-attention ----
box(10.0, 4.25, 2.6, 2.0,
    "Cross-Attention (B $\\rightarrow$ A)\n\nscaled dot-product\nsoftmax over A", CATT, fs=10)
arrow(7.95, 5.2, 8.7, 4.7, "$z_A$", lx=8.35, ly=5.25)
arrow(7.95, 3.3, 8.7, 3.8, "$z_B$", lx=8.35, ly=3.35)

# ---- Coarse prediction (barycentric) ----
box(13.1, 5.55, 2.5, 1.5,
    "Barycentric\n\nattn @ $A_{coords}$", CHEAD, fs=10)
arrow(11.3, 4.6, 12.1, 5.3, "attention\nweights", lx=11.75, ly=5.05)

# ---- Residual refinement ----
box(13.1, 2.85, 2.6, 1.7,
    "Residual MLP\n\n($z_B$, weighted $z_A$,\ncoarse coord)", CHEAD, fs=9.5)
arrow(11.3, 3.9, 12.0, 3.2)                       # attn -> residual
arrow(13.1, 4.8, 13.1, 3.75)                      # coarse coord -> residual

# ---- Output ----
box(16.4, 2.85, 2.7, 1.9,
    "Predicted\nA-frame coordinates\nper B spot", COUT, fs=10, weight="bold")
arrow(14.45, 2.85, 15.05, 2.85)

ax.set_title("Sutura: graph cross-attention registration model",
             fontsize=13, weight="bold", pad=6)
fig.tight_layout()
fig.savefig(OUT, dpi=300, facecolor="white", bbox_inches="tight")
print("wrote", OUT)
