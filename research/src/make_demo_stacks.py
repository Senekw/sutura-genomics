"""Generate the three demo dataset point clouds for the 3D stacked-tissue viewer.

  - DLPFC Br5292: REAL coordinates + cortical layers from the .h5ad files.
  - Breast Tumor HTAN: plausible synthetic (tumor nests / stroma / immune / ...).
  - Kidney PCEN: plausible synthetic (cortex / medulla / glomeruli / tubules).

Each stack shares one schema:
  { dataset, tissue, layers[], layerColors[], spacing, slices:[{id,n,xy,layer}] }
so the viewer + results page render any of them uniformly.

Run: C:/Users/karti/arca/.venv/Scripts/python.exe research/src/make_demo_stacks.py
"""
import json
import os

import numpy as np

OUT_DIR = "public/demo"
os.makedirs(OUT_DIR, exist_ok=True)


def dump(name, obj):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    total = sum(s["n"] for s in obj["slices"])
    counts = {}
    for s in obj["slices"]:
        for li in s["layer"]:
            counts[li] = counts.get(li, 0) + 1
    print(f"\n{name}: {len(obj['slices'])} slices, {total} spots, "
          f"{os.path.getsize(path)/1024:.0f} KB")
    for i, lab in enumerate(obj["layers"]):
        print(f"   {lab}: {counts.get(i,0)} ({100*counts.get(i,0)/total:.1f}%)")


def organic_boundary(rng, n_lobes=3):
    """Return r(theta) callable for a lobular organic outline (~unit radius)."""
    phases = rng.uniform(0, 2 * np.pi, n_lobes)
    amps = rng.uniform(0.06, 0.16, n_lobes)
    ks = rng.integers(2, 5, n_lobes)

    def r(theta):
        rr = np.ones_like(theta) * 0.86
        for a, k, p in zip(amps, ks, phases):
            rr = rr + a * np.sin(k * theta + p)
        return rr

    return r


def sample_shape(rng, n, r_fn, squash=0.86):
    """Rejection-sample n points inside an organic blob, normalized to ~[-1,1]."""
    pts = []
    while len(pts) < n:
        m = (n - len(pts)) * 3
        xy = rng.uniform(-1, 1, (m, 2))
        xy[:, 1] /= squash
        theta = np.arctan2(xy[:, 1], xy[:, 0])
        rad = np.hypot(xy[:, 0], xy[:, 1])
        keep = rad <= r_fn(theta)
        pts.extend(xy[keep].tolist())
    return np.array(pts[:n])


def assign_by_seeds(xy, seeds, bg_class, rng, noise=0.03):
    """Assign each point the class of the strongest Gaussian seed, else bg."""
    labels = np.full(len(xy), bg_class, dtype=int)
    best = np.zeros(len(xy))
    for (cx, cy, sigma, strength, cls) in seeds:
        d2 = (xy[:, 0] - cx) ** 2 + (xy[:, 1] - cy) ** 2
        infl = strength * np.exp(-d2 / (2 * sigma * sigma))
        take = infl > np.maximum(best, 0.35)
        labels[take] = cls
        best = np.maximum(best, infl)
    flip = rng.random(len(xy)) < noise
    labels[flip] = rng.integers(0, labels.max() + 1, flip.sum())
    return labels


def round_xy(xy):
    return [[round(float(x), 4), round(float(y), 4)] for x, y in xy]


# ─────────────────────────── DLPFC (real) ───────────────────────────
def build_dlpfc(per_slice=3000):
    import anndata as ad

    SLICES = ["151507", "151508", "151509", "151510"]
    LAYERS = ["Layer1", "Layer2", "Layer3", "Layer4", "Layer5", "Layer6", "WM"]
    COLORS = ["#5e4fa2", "#3a7ecf", "#66c2a5", "#a6d96a", "#fee08b", "#fdae61", "#d53e4f"]
    rng = np.random.default_rng(0)

    def lidx(v):
        v = str(v)
        return LAYERS.index(v) if v in LAYERS else -1

    raw = []
    for sid in SLICES:
        a = ad.read_h5ad(f"research/data/DLPFC_{sid}.h5ad", backed="r")
        xy = np.asarray(a.obsm["spatial"], float)
        col = "sce.layer_guess" if "sce.layer_guess" in a.obs.columns else "layer"
        lab = np.array([lidx(v) for v in a.obs[col].to_numpy()])
        keep = lab >= 0
        xy, lab = xy[keep], lab[keep]
        xy = xy.copy()
        xy[:, 1] = -xy[:, 1]
        raw.append((sid, xy, lab))

    allxy = np.concatenate([r[1] for r in raw])
    center, scale = allxy.mean(0), np.abs(allxy - allxy.mean(0)).max()

    slices = []
    for sid, xy, lab in raw:
        if len(xy) > per_slice:
            idx = rng.choice(len(xy), per_slice, replace=False)
            xy, lab = xy[idx], lab[idx]
        norm = (xy - center) / scale
        slices.append({"id": sid, "n": len(norm), "xy": round_xy(norm),
                       "layer": [int(v) for v in lab]})

    return {"dataset": "DLPFC Br5292", "tissue": "Human dorsolateral prefrontal cortex",
            "layers": ["L1", "L2", "L3", "L4", "L5", "L6", "WM"],
            "layerColors": COLORS, "spacing": 30, "slices": slices}


# ─────────────────────────── Breast (synthetic) ───────────────────────────
def build_breast(n_slices=4, per_slice=1500):
    LAYERS = ["Tumor", "Stroma", "Immune", "Necrosis", "Duct", "Vessel"]
    COLORS = ["#d6336c", "#7048e8", "#1c7ed6", "#495057", "#37b24d", "#f08c00"]
    rng = np.random.default_rng(11)
    r_fn = organic_boundary(rng, n_lobes=4)

    # tumor-nest centers shared across serial sections (small per-slice jitter)
    nests = rng.uniform(-0.6, 0.6, (4, 2))
    slices = []
    for si in range(n_slices):
        j = rng.normal(0, 0.03, nests.shape)
        xy = sample_shape(rng, per_slice, r_fn)
        seeds = []
        for k, (cx, cy) in enumerate(nests + j):
            seeds.append((cx, cy, 0.20, 1.6, 0))          # Tumor
            if k < 2:
                seeds.append((cx, cy, 0.07, 1.8, 3))      # Necrosis core
        for _ in range(3):
            ix, iy = rng.uniform(-0.7, 0.7, 2)
            seeds.append((ix, iy, 0.09, 1.2, 2))          # Immune clusters
        for _ in range(2):
            dx, dy = rng.uniform(-0.7, 0.7, 2)
            seeds.append((dx, dy, 0.06, 1.1, 4))          # Ducts
        lab = assign_by_seeds(xy, seeds, bg_class=1, rng=rng)   # bg Stroma
        # thin vasculature: a few random stroma points
        v = (lab == 1) & (rng.random(len(xy)) < 0.05)
        lab[v] = 5
        slices.append({"id": f"S{si+1}", "n": len(xy), "xy": round_xy(xy),
                       "layer": [int(x) for x in lab]})

    return {"dataset": "Breast Tumor HTAN", "tissue": "Human breast (invasive carcinoma)",
            "layers": LAYERS, "layerColors": COLORS, "spacing": 30, "slices": slices}


# ─────────────────────────── Kidney (synthetic) ───────────────────────────
def build_kidney(n_slices=3, per_slice=1167):
    LAYERS = ["Cortex", "Medulla", "Glomeruli", "Prox tubule", "Dist tubule", "Vessel"]
    COLORS = ["#4263eb", "#ae3ec9", "#e8590c", "#2f9e44", "#66a80f", "#f03e3e"]
    rng = np.random.default_rng(22)
    r_fn = organic_boundary(rng, n_lobes=3)

    glom = rng.uniform(-0.7, 0.7, (10, 2))
    slices = []
    for si in range(n_slices):
        j = rng.normal(0, 0.03, glom.shape)
        xy = sample_shape(rng, per_slice, r_fn, squash=0.9)
        rad = np.hypot(xy[:, 0], xy[:, 1])
        lab = np.where(rad < 0.45, 1, 0)   # inner Medulla / outer Cortex
        # tubules interleaved in cortex
        tub = (lab == 0) & (rng.random(len(xy)) < 0.45)
        lab[tub] = np.where(rng.random(tub.sum()) < 0.5, 3, 4)
        # glomeruli: tight clusters in the cortex band
        seeds = [(gx, gy, 0.05, 1.6, 2) for gx, gy in (glom + j)
                 if np.hypot(gx, gy) > 0.45]
        gl = assign_by_seeds(xy, seeds, bg_class=-1, rng=rng, noise=0.0)
        lab[gl == 2] = 2
        vessel = rng.random(len(xy)) < 0.04
        lab[vessel] = 5
        slices.append({"id": f"S{si+1}", "n": len(xy), "xy": round_xy(xy),
                       "layer": [int(x) for x in lab]})

    return {"dataset": "Kidney PCEN", "tissue": "Human kidney",
            "layers": LAYERS, "layerColors": COLORS, "spacing": 30, "slices": slices}


if __name__ == "__main__":
    dump("br5292_stack.json", build_dlpfc())
    dump("breast_htan_stack.json", build_breast())
    dump("kidney_pcen_stack.json", build_kidney())
