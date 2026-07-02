"""Precompute a compact 4-slice DLPFC Br5292 point cloud for the web demo's
3D stacked-tissue viewer. Reads the real .h5ad files, pulls spatial coords +
cortical-layer labels, downsamples, normalizes to a shared frame, and writes a
small JSON to public/demo/br5292_stack.json.

Run: C:/Users/karti/arca/.venv/Scripts/python.exe research/src/make_stack_json.py
"""
import json
import os

import anndata as ad
import numpy as np

SLICES = ["151507", "151508", "151509", "151510"]
LAYERS = ["Layer1", "Layer2", "Layer3", "Layer4", "Layer5", "Layer6", "WM"]
# Spectral-style ordered palette (L1 -> WM), readable on white.
LAYER_COLORS = [
    "#5e4fa2", "#3a7ecf", "#66c2a5", "#a6d96a",
    "#fee08b", "#fdae61", "#d53e4f",
]
PER_SLICE = 1400  # downsample target per slice (keeps JSON small)
DATA_DIR = "research/data"
OUT = "public/demo/br5292_stack.json"

rng = np.random.default_rng(0)


def layer_index(v):
    v = str(v)
    if v in LAYERS:
        return LAYERS.index(v)
    return -1  # NA / unknown -> dropped


def main():
    # First pass: collect coords to compute a shared normalization.
    raw = []
    for sid in SLICES:
        a = ad.read_h5ad(os.path.join(DATA_DIR, f"DLPFC_{sid}.h5ad"), backed="r")
        xy = np.asarray(a.obsm["spatial"], dtype=float)
        col = "sce.layer_guess" if "sce.layer_guess" in a.obs.columns else "layer"
        labels = np.array([layer_index(v) for v in a.obs[col].to_numpy()])
        keep = labels >= 0
        xy, labels = xy[keep], labels[keep]
        # image-y grows downward; flip so cortex reads upright
        xy = xy.copy()
        xy[:, 1] = -xy[:, 1]
        raw.append((sid, xy, labels))

    allxy = np.concatenate([r[1] for r in raw], axis=0)
    center = allxy.mean(axis=0)
    scale = np.abs(allxy - center).max()  # normalize to ~[-1, 1]

    slices = []
    for sid, xy, labels in raw:
        n = len(xy)
        if n > PER_SLICE:
            idx = rng.choice(n, PER_SLICE, replace=False)
            xy, labels = xy[idx], labels[idx]
        norm = (xy - center) / scale
        slices.append({
            "id": sid,
            "n": int(len(norm)),
            # round to 4 dp to shrink the payload
            "xy": [[round(float(x), 4), round(float(y), 4)] for x, y in norm],
            "layer": [int(v) for v in labels],
        })

    out = {
        "dataset": "DLPFC Br5292",
        "layers": ["L1", "L2", "L3", "L4", "L5", "L6", "WM"],
        "layerColors": LAYER_COLORS,
        "spacing": 30,
        "slices": slices,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    total = sum(s["n"] for s in slices)
    print(f"wrote {OUT}: {len(slices)} slices, {total} spots, "
          f"{os.path.getsize(OUT) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
